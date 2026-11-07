"""Live 0x Swap API v2 *price*, not an executable quote or profit prediction.

Only pinned-block Aave collateral asset quantities are used as requested sell sizes.
No signing, /quote calls, approvals, custody, transfers, or made-up fallback prices.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from engine import CHAINS, validate_address, validate_chain

CHAIN_IDS = {'ethereum': 1, 'base': 8453, 'arbitrum': 42161, 'polygon': 137}
PRICE_URL = 'https://api.0x.org/swap/allowance-holder/price'
MAX_RESPONSE = 500_000


class MarketUnavailable(RuntimeError):
    pass


def parse_price(data: dict, *, chain: str, asset: str, buy_token: str,
                sell_amount: str, snapshot_block: int) -> dict:
    """Strict provider response validation; no balances or prices fabricated."""
    if not isinstance(data, dict):
        raise MarketUnavailable('Market provider returned invalid JSON')
    if data.get('liquidityAvailable') is not True:
        raise MarketUnavailable('No live liquidity available for this amount')
    buy = data.get('buyAmount')
    if not isinstance(buy, str) or not buy.isdecimal() or int(buy) <= 0 or len(buy) > 80:
        raise MarketUnavailable('Provider omitted valid buy amount')
    sell = data.get('sellAmount')
    if sell is not None and (not isinstance(sell,str) or sell != sell_amount):
        raise MarketUnavailable('Provider returned a mismatched sell amount')
    impact = data.get('estimatedPriceImpact')
    if impact is not None:
        try:
            from decimal import Decimal
            d = Decimal(str(impact))
            if not d.is_finite():
                raise ValueError()
        except (ValueError, TypeError, ArithmeticError):
            raise MarketUnavailable('Invalid provider price impact')
        impact = str(d)
    issues = data.get('issues')
    if issues is not None and not isinstance(issues, dict):
        raise MarketUnavailable('Invalid provider issues')
    return {
        'source': '0x Swap API v2 /swap/allowance-holder/price',
        'chain': chain,
        'chain_id': CHAIN_IDS[chain],
        'sell_token': asset,
        'buy_token': buy_token,
        'sell_amount_raw': sell_amount,
        'buy_amount_raw': buy,
        'buy_decimals': 6,
        'liquidity_available': True,
        'estimated_price_impact': impact,
        'simulation_incomplete': bool((issues or {}).get('simulationIncomplete', False)),
        'quoted_at': datetime.now(timezone.utc).isoformat(),
        'aave_snapshot_block': snapshot_block,
        'indicative_price_only': True,
        'executable_quote': False,
        'liquidation_profit_usd': None,
        'transaction_executed': False,
    }


def live_market_price(chain: str, sell_asset: str, sell_amount: str, snapshot_block: int) -> dict:
    chain = validate_chain(chain)
    asset = validate_address(sell_asset)
    buy_token = validate_address(CHAINS[chain]['usdc'])
    if asset == buy_token:
        raise ValueError('Collateral is already USDC')
    if not isinstance(sell_amount, str) or not sell_amount.isdecimal() or not 0 < int(sell_amount) < 10**60:
        raise ValueError('Observed collateral amount must be positive')
    if type(snapshot_block) is not int or snapshot_block <= 0:
        raise ValueError('Missing verified Aave snapshot block')
    key = os.getenv('ZEROX_API_KEY', '').strip()
    if not key:
        raise MarketUnavailable('ZEROX_API_KEY not configured. Live market prices unavailable')
    params = urllib.parse.urlencode({
        'chainId': CHAIN_IDS[chain], 'sellToken': asset,
        'buyToken': buy_token, 'sellAmount': sell_amount,
    })
    request = urllib.request.Request(
        PRICE_URL + '?' + params,
        headers={'0x-api-key':key, '0x-version':'v2',
                 'accept':'application/json', 'User-Agent':'RECLAIM-ReadOnly/0.6'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise MarketUnavailable('Price response exceeded size limit')
            data = json.loads(payload)
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):
            raise MarketUnavailable('0x rejected API credentials or chain access') from exc
        if exc.code == 429:
            raise MarketUnavailable('0x rate limit reached') from exc
        raise MarketUnavailable('Live 0x market price service returned an error') from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarketUnavailable('Live 0x market price provider is unreachable') from exc
    return parse_price(data, chain=chain, asset=asset, buy_token=buy_token,
                       sell_amount=sell_amount, snapshot_block=snapshot_block)
