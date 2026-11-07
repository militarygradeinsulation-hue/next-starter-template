"""Read-only Aave V3 reserve exposure and indicative liquidation economics.

Contract addresses are from aave-dao/aave-address-book (November 2026).
All RPC eth_call methods are pinned to one block. This module NEVER signs,
constructs or broadcasts a transaction. An indicated gain is not a swap quote.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re

from aave import POOLS, SELECTOR, decode_account_data
from engine import CHAINS, fetch_prices, rpc_call, validate_address, validate_chain

# Official per-market contracts, from Aave address book.
DATA_PROVIDERS = {
    'ethereum': '0x0a16f2FCC0D44FaE41cc54e079281D84A363bECD',
    'base': '0x0F43731EB8d45A581f4a36DD74F5f358bc90C73A',
    'arbitrum': '0x243Aa95cAC2a25651eda86e80bEe66114413c43b',
    'polygon': '0x243Aa95cAC2a25651eda86e80bEe66114413c43b',
}
ORACLES = {
    'ethereum': '0x54586bE62E3c3580375aE3723C145253060Ca0C2',
    'base': '0x2Cc0Fc26eD4563A5ce5e8bdcfe1A2878676Ae156',
    'arbitrum': '0xb56c2F0B653B2e0b10C9b928C8580Ac5Df02C7C7',
    'polygon': '0xb023e699F5a33916Ea823A16485e259257cA8Bd1',
}
# Ethereum ABI selectors, Keccak-256 of method signatures, confirmed against Aave ABI.
GET_RESERVES_LIST = '0xd1946dbc'
GET_USER_CONFIG = '0x4417a583'
GET_USER_EMODE = '0xeddf1b79'
GET_USER_RESERVE_DATA = '0x28dd2d01'
GET_CONFIGURATION = '0xc44b11f7'
GET_ASSET_PRICE = '0xb3596f07'
BASE_CURRENCY = '0xe19f4700'
BASE_CURRENCY_UNIT = '0x8c89b64f'
SYMBOL = '0x95d89b41'
USD_ADDRESS = '0x0000000000000000000000000000000000000348'
ZERO = Decimal('0')
ONE = Decimal('1')
BPS = Decimal('10000')
MAX_RESERVES = 140
MAX_ACTIVE_RESERVES = 32
HEX = re.compile(r'^0x(?:[0-9a-fA-F]{64})+$')
SMALL_HEX = re.compile(r'^0x[0-9a-fA-F]+$')


def abi_words(raw: str, minimum: int = 1) -> list[int]:
    if not isinstance(raw, str) or not HEX.fullmatch(raw):
        raise RuntimeError('Malformed contract ABI response')
    words = [int(raw[i:i + 64], 16) for i in range(2, len(raw), 64)]
    if len(words) < minimum or len(words) > 256:
        raise RuntimeError('Unexpected contract result length')
    return words


def encode_address(address: str) -> str:
    return validate_address(address)[2:].rjust(64, '0')


def eth_view(chain: str, to: str, data: str, block: str) -> str:
    validate_address(to)
    if not isinstance(data, str) or not data.startswith('0x') or not re.fullmatch(r'0x[0-9a-fA-F]+', data):
        raise ValueError('Invalid read-only calldata')
    value = rpc_call(chain, 'eth_call', [{'to': to, 'data': data}, block])
    if not isinstance(value, str) or not value.startswith('0x'):
        raise RuntimeError('Contract read returned an invalid result')
    return value


def abi_addresses(raw: str) -> list[str]:
    """Decode a single dynamic address[] result with strict ABI bounds."""
    words = abi_words(raw, 2)
    if words[0] != 32:
        raise RuntimeError('Unexpected address array offset')
    count = words[1]
    if count > MAX_RESERVES or len(words) != count + 2:
        raise RuntimeError('Aave reserve list too large or truncated')
    result = []
    for item in words[2:]:
        if item >> 160:
            raise RuntimeError('Non-canonical ABI address')
        result.append('0x' + f'{item:040x}')
    if len(set(result)) != len(result):
        raise RuntimeError('Duplicate reserve in provider response')
    return result


def decode_config(raw: str) -> dict:
    value = abi_words(raw, 1)
    if len(value) != 1:
        raise RuntimeError('Unexpected reserve config result')
    bits = value[0]
    return {
        'decimals': (bits >> 48) & 0xff,
        'liquidation_threshold_bps': (bits >> 16) & 0xffff,
        'liquidation_bonus_bps': (bits >> 32) & 0xffff,
        'protocol_fee_bps': (bits >> 152) & 0xffff,
        'active': bool((bits >> 56) & 1),
        'frozen': bool((bits >> 57) & 1),
        'paused': bool((bits >> 60) & 1),
    }


def decode_reserve_user(raw: str) -> dict:
    # Aave ProtocolDataProvider.getUserReserveData returns nine static words.
    fields = abi_words(raw, 9)
    if len(fields) != 9 or fields[8] not in (0, 1):
        raise RuntimeError('Unexpected getUserReserveData ABI')
    return {
        'a_token_balance_raw': fields[0],
        'stable_debt_raw': fields[1],
        'variable_debt_raw': fields[2],
        'collateral_enabled': bool(fields[8]),
    }


def read_symbol(chain: str, asset: str, block: str) -> str:
    """Optional ERC20 metadata; never allow malformed strings into UI unescaped."""
    try:
        words = abi_words(eth_view(chain, asset, SYMBOL, block))
        # Legacy ERC20 bytes32 symbol or standard dynamic string.
        if len(words) == 1:
            data = bytes.fromhex(f'{words[0]:064x}').rstrip(b'\x00')
        elif words[0] == 32 and 2 <= len(words) <= 5:
            size = words[1]
            if size > 32 * (len(words) - 2) or size > 32:
                raise ValueError('Invalid symbol length')
            data = b''.join(w.to_bytes(32, 'big') for w in words[2:])[:size]
        else:
            raise ValueError('Unexpected symbol ABI')
        symbol = data.decode('ascii')
        if symbol and len(symbol) <= 20 and re.fullmatch(r'[A-Za-z0-9._+\-]{1,20}', symbol):
            return symbol
    except (ValueError, UnicodeError, RuntimeError):
        pass
    return asset[:8] + '...' + asset[-4:]


def price_base(raw_amount: int, decimals: int, oracle_price: int, oracle_unit: int) -> Decimal:
    if decimals > 36 or oracle_unit <= 0 or oracle_price <= 0:
        raise RuntimeError('Invalid oracle price or token decimals')
    return Decimal(raw_amount) * Decimal(oracle_price) / (Decimal(10) ** decimals * Decimal(oracle_unit))


def read_reserve_snapshot(chain: str, address: str) -> dict:
    """Read one borrower and their active reserve exposure at a single block."""
    chain = validate_chain(chain)
    address = validate_address(address)
    block_hex = rpc_call(chain, 'eth_blockNumber', [])
    if not isinstance(block_hex, str) or not SMALL_HEX.fullmatch(block_hex):
        raise RuntimeError('Invalid current block response')
    block_number = int(block_hex, 16)
    if block_number <= 0:
        raise RuntimeError('Chain did not return a usable block')
    block = hex(block_number)
    pool = POOLS[chain]
    account = decode_account_data(eth_view(chain, pool, SELECTOR + encode_address(address), block))
    collateral_base, debt_base, available_base, threshold, ltv, hf_raw = account
    emode = abi_words(eth_view(chain, pool, GET_USER_EMODE + encode_address(address), block))[0]
    user_config = abi_words(eth_view(chain, pool, GET_USER_CONFIG + encode_address(address), block))[0]
    reserves = abi_addresses(eth_view(chain, pool, GET_RESERVES_LIST, block))
    unit_result = abi_words(eth_view(chain, ORACLES[chain], BASE_CURRENCY_UNIT, block))
    base_result = abi_words(eth_view(chain, ORACLES[chain], BASE_CURRENCY, block))
    if len(unit_result) != 1 or len(base_result) != 1 or unit_result[0] <= 0:
        raise RuntimeError('Invalid Aave oracle base currency metadata')
    oracle_unit = unit_result[0]
    is_usd = base_result[0] == int(USD_ADDRESS, 16)
    chosen = [(i, asset) for i, asset in enumerate(reserves) if (user_config >> (2 * i)) & 3]
    if len(chosen) > MAX_ACTIVE_RESERVES:
        raise RuntimeError('Too many active reserves; aborting before partial output')
    items = []
    for idx, asset in chosen:
        raw_user = eth_view(chain, DATA_PROVIDERS[chain], GET_USER_RESERVE_DATA + encode_address(asset) + encode_address(address), block)
        current = decode_reserve_user(raw_user)
        config = decode_config(eth_view(chain, pool, GET_CONFIGURATION + encode_address(asset), block))
        if not 0 <= config['decimals'] <= 36:
            raise RuntimeError('Invalid token decimals')
        price = abi_words(eth_view(chain, ORACLES[chain], GET_ASSET_PRICE + encode_address(asset), block))
        if len(price) != 1 or price[0] <= 0:
            raise RuntimeError('Aave oracle returned zero/unusable price')
        reserve_collateral = price_base(current['a_token_balance_raw'], config['decimals'], price[0], oracle_unit)
        reserve_debt = price_base(current['stable_debt_raw'] + current['variable_debt_raw'], config['decimals'], price[0], oracle_unit)
        if not current['collateral_enabled'] and not reserve_debt:
            continue
        items.append({
            'asset': asset,
            'symbol': read_symbol(chain, asset, block),
            'reserve_index': idx,
            'collateral_enabled': current['collateral_enabled'],
            'a_token_balance_raw': str(current['a_token_balance_raw']),
            'stable_debt_raw': str(current['stable_debt_raw']),
            'variable_debt_raw': str(current['variable_debt_raw']),
            'collateral_value_base': str(reserve_collateral.quantize(Decimal('0.000001'))),
            'debt_value_base': str(reserve_debt.quantize(Decimal('0.000001'))),
            'oracle_price_raw': str(price[0]),
            **config,
        })
    hf = Decimal(hf_raw) / Decimal(10**18) if debt_base else None
    signal = 'below_one_candidate' if debt_base and hf is not None and hf < ONE else 'healthy' if debt_base else 'no_debt'
    return {
        'chain': chain, 'address': address, 'pool': pool, 'oracle': ORACLES[chain],
        'block_number': block_number,
        'oracle_base_currency': USD_ADDRESS if is_usd else '0x'+f'{base_result[0]:040x}',
        'oracle_base_unit': str(oracle_unit),
        'quote_currency': 'USD' if is_usd else 'non_usd_oracle_base',
        'emode_category': emode,
        'collateral_base_raw': str(collateral_base),
        'debt_base_raw': str(debt_base),
        'collateral_value_base': str((Decimal(collateral_base)/oracle_unit).quantize(Decimal('0.000001'))),
        'debt_value_base': str((Decimal(debt_base)/oracle_unit).quantize(Decimal('0.000001'))),
        'health_factor': str(hf.quantize(Decimal('0.000001'))) if hf is not None else None,
        'signal': signal,
        'reserves': items,
        'read_only': True,
        'execution_ready': False,
        'scanned_at': datetime.now(timezone.utc).isoformat(),
    }


def _display(value: Decimal | None) -> str | None:
    return str(value.quantize(Decimal('0.01'))) if value is not None else None


def indicative_pairs(snapshot: dict, *, native_price_usd: Decimal | None = None,
                     gas_price_wei: int | None = None, gas_units: int = 650000,
                     slippage_bps: int = 100, funding_fee_bps: int = 9,
                     min_net_usd: Decimal = Decimal('10')) -> dict:
    """Price reserve pairs and list uncertainties; NEVER mark execution-ready.

    No DEX routing quote, L2 posting fee, MEV bundle, reserve-version-specific
    dust check or contract simulation is available here. Potential >0 net is
    only a research signal, not a validated liquidation or guaranteed return.
    """
    if type(gas_units) is not int or not 100000 <= gas_units <= 5000000:
        raise ValueError('gas_units must be between 100000 and 5000000')
    if type(slippage_bps) is not int or not 0 <= slippage_bps <= 5000:
        raise ValueError('slippage_bps out of range')
    if type(funding_fee_bps) is not int or not 0 <= funding_fee_bps <= 1000:
        raise ValueError('funding_fee_bps out of range')
    if native_price_usd is not None and (not native_price_usd.is_finite() or native_price_usd <= ZERO):
        raise ValueError('native price must be positive')
    if gas_price_wei is not None and (type(gas_price_wei) is not int or gas_price_wei <= 0):
        raise ValueError('gas_price_wei must be positive integer')
    if not min_net_usd.is_finite() or min_net_usd < ZERO:
        raise ValueError('min_net_usd invalid')
    hf = Decimal(snapshot['health_factor']) if snapshot.get('health_factor') is not None else None
    total_debt = Decimal(snapshot['debt_value_base'])
    total_coll = Decimal(snapshot['collateral_value_base'])
    close_factor = Decimal('100') if hf is not None and (hf <= Decimal('0.95') or total_debt < 2000 or total_coll < 2000) else Decimal('50')
    gas_usd = (Decimal(gas_price_wei) * gas_units * native_price_usd / Decimal(10)**18
               if native_price_usd is not None and gas_price_wei is not None else None)
    # No asset pairs until we establish genuine oracle USD denomination.
    blockers = []
    if hf is None or hf >= ONE:
        blockers.append('health_factor_not_below_one')
    if snapshot.get('quote_currency') != 'USD':
        blockers.append('oracle_currency_not_verified_usd')
    if snapshot.get('emode_category'):
        blockers.append('emode_pair_specific_rules_not_verified')
    if gas_usd is None:
        blockers.append('gas_usd_unavailable')
    pair_rows = []
    reserves = snapshot.get('reserves', [])
    for debt in reserves:
        debt_value = Decimal(debt['debt_value_base'])
        if debt_value <= ZERO:
            continue
        for coll in reserves:
            coll_value = Decimal(coll['collateral_value_base'])
            bonus_bps = coll['liquidation_bonus_bps']
            if not coll.get('collateral_enabled') or coll_value <= ZERO or bonus_bps <= 10000:
                continue
            if not coll.get('active') or not debt.get('active') or coll.get('paused') or debt.get('paused'):
                continue
            gross_bonus = Decimal(bonus_bps) / BPS
            repay = min(debt_value, total_debt * close_factor / 100,
                        coll_value / gross_bonus)
            if repay <= ZERO:
                continue
            # Protocol receives a fraction of the liquidation BONUS, not principal.
            fee_fraction = Decimal(coll['protocol_fee_bps']) / BPS
            if fee_fraction > ONE:
                continue
            seized_base = repay * gross_bonus
            gain = repay * (gross_bonus - ONE) * (ONE - fee_fraction)
            swap_impact = seized_base * Decimal(slippage_bps) / BPS
            funding_fee = repay * Decimal(funding_fee_bps) / BPS
            net = gain - swap_impact - funding_fee - gas_usd if gas_usd is not None else None
            # Avoid any USD net figure if the position is healthy, oracle unit
            # is not USD or EMode rules could change collateral valuation.
            if hf is None or hf >= ONE or snapshot.get('quote_currency') != 'USD' or snapshot.get('emode_category'):
                net = None
            pair_blockers = list(blockers)
            remaining_debt = total_debt - repay
            remaining_coll = total_coll - seized_base
            # Conservative dust screen for older and newer Aave V3 markets.
            if ZERO < remaining_debt < 1000 or ZERO < remaining_coll < 1000:
                pair_blockers.append('partial_liquidation_may_leave_dust')
            if seized_base > coll_value + Decimal('0.000001'):
                pair_blockers.append('insufficient_collateral')
            if net is not None and net <= min_net_usd:
                pair_blockers.append('below_minimum_indicative_profit')
            # Always include execution dependencies; this is not a firm swap quote.
            pair_blockers.extend(['swap_route_not_quoted', 'transaction_not_simulated'])
            if snapshot['chain'] in ('base','arbitrum','polygon'):
                pair_blockers.append('l2_posting_fee_not_modeled')
            pair_rows.append({
                'debt_asset': debt['asset'], 'debt_symbol': debt['symbol'],
                'collateral_asset': coll['asset'], 'collateral_symbol': coll['symbol'],
                'max_indicative_repay_usd': _display(repay),
                'gross_bonus_usd': _display(gain),
                'protocol_fee_bps': coll['protocol_fee_bps'],
                'estimated_gas_usd': _display(gas_usd),
                'slippage_allowance_usd': _display(swap_impact),
                'funding_fee_allowance_usd': _display(funding_fee),
                'indicative_net_usd': _display(net),
                'close_factor_pct_assumed': str(close_factor),
                'blocking_reasons': pair_blockers,
                'execution_ready': False,
            })
    pair_rows.sort(key=lambda p: Decimal(p['indicative_net_usd']) if p['indicative_net_usd'] is not None else Decimal('-1e50'), reverse=True)
    return {
        'chain': snapshot['chain'], 'address': snapshot['address'],
        'block_number': snapshot['block_number'], 'health_factor': snapshot['health_factor'],
        'indicative_pairs': pair_rows[:20],
        'pairs_evaluated': len(pair_rows),
        'estimated_gas_usd': _display(gas_usd),
        'cost_assumptions': {'estimated_gas_units': gas_units, 'slippage_bps': slippage_bps,
                             'funding_fee_bps': funding_fee_bps,
                             'native_token_usd': str(native_price_usd) if native_price_usd is not None else None,
                             'gas_price_wei': str(gas_price_wei) if gas_price_wei is not None else None,
                             'minimum_indicative_net_usd': str(min_net_usd)},
        'read_only': True, 'execution_ready': False,
        'quote_verified': False,
        'note': 'Indicative reserve-level screening only. Profit requires an executable swap quote, collateral/debt reserve rule verification, transaction simulation and full gas/MEV costs.',
    }


def analyze_live_position(chain: str, address: str, *, gas_units: int = 650000,
                          slippage_bps: int = 100, funding_fee_bps: int = 9,
                          min_net_usd: Decimal = Decimal('10')) -> dict:
    snapshot = read_reserve_snapshot(chain, address)
    gas_price = None
    try:
        result = rpc_call(chain, 'eth_gasPrice', [])
        if not isinstance(result, str) or not SMALL_HEX.fullmatch(result):
            raise ValueError('invalid gas price')
        gas_price = int(result, 16)
        if gas_price <= 0:
            gas_price = None
    except (RuntimeError, ValueError):
        pass
    native = None
    try:
        native = fetch_prices().get(CHAINS[chain]['price_id'])
    except (RuntimeError, ValueError):
        pass
    return {**snapshot, **indicative_pairs(snapshot, native_price_usd=native,
                gas_price_wei=gas_price, gas_units=gas_units,
                slippage_bps=slippage_bps, funding_fee_bps=funding_fee_bps,
                min_net_usd=min_net_usd)}
