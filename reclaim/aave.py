"""Read-only Aave V3 position snapshots from official deployed Pools.

This module never constructs or broadcasts a transaction. A sub-1 health
factor is an investigative signal, not guaranteed executable profit.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal

from engine import rpc_call, validate_chain, validate_address

# Verified against the aave-dao/aave-address-book sources for these markets.
POOLS = {
    'ethereum': '0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2',
    'base': '0xA238Dd80C259a72e81d7e4664a9801593F98d1c5',
    'arbitrum': '0x794a61358D6845594F94dc1DB02A252b5b4814aD',
    'polygon': '0x794a61358D6845594F94dc1DB02A252b5b4814aD',
}
SELECTOR = '0xbf92857c'  # getUserAccountData(address)


def decode_account_data(raw: str) -> tuple[int, int, int, int, int, int]:
    if not isinstance(raw, str) or not raw.startswith('0x') or len(raw) != 2 + 64 * 6:
        raise RuntimeError('Unexpected Aave Pool return data (six uint256 expected)')
    try:
        return tuple(int(raw[2 + i * 64:2 + (i + 1) * 64], 16) for i in range(6))
    except ValueError as exc:
        raise RuntimeError('Malformed Aave Pool return data') from exc


def read_position(chain: str, address: str) -> dict:
    chain = validate_chain(chain)
    address = validate_address(address)
    calldata = SELECTOR + address[2:].rjust(64, '0')
    raw = rpc_call(chain, 'eth_call', [{'to': POOLS[chain], 'data': calldata}, 'latest'])
    collateral, debt, available, threshold, ltv, hf_raw = decode_account_data(raw)
    hf = Decimal(hf_raw) / Decimal(10**18) if debt else None
    signal = 'below_one_candidate' if debt and collateral and hf < 1 else 'no_collateral' if debt and not collateral else 'healthy' if debt else 'no_debt'
    return {
        'chain': chain, 'address': address, 'protocol': 'Aave V3', 'pool': POOLS[chain],
        'total_collateral_base_raw': str(collateral), 'total_debt_base_raw': str(debt),
        'available_borrows_base_raw': str(available),
        'current_liquidation_threshold_bps': threshold,
        'ltv_bps': ltv, 'health_factor': str(hf.quantize(Decimal('0.000001'))) if hf is not None else None,
        'signal': signal, 'candidate': signal == 'below_one_candidate',
        'execution_ready': False, 'scanned_at': datetime.now(timezone.utc).isoformat(),
        'note': 'Read-only pool snapshot at latest block. Aave reserve eligibility, price data, close factor, liquidity, gas, MEV and profitability are not verified. Base amounts are unconverted oracle units.'
    }
