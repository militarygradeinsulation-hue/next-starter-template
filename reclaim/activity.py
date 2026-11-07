"""Etherscan V2 read-only indexed activity adapter.

An observed transaction timestamp is a *signal*, never proof of abandonment.
The five categories do not capture every possible contract state change.
"""
from __future__ import annotations
from datetime import datetime, timezone
import os
import time
from urllib.parse import urlencode

from engine import json_request, validate_address, validate_chain

ETHERSCAN_URL = 'https://api.etherscan.io/v2/api'
CHAIN_IDS = {'ethereum': 1, 'base': 8453, 'arbitrum': 42161, 'polygon': 137}
CATEGORIES = ('txlist', 'txlistinternal', 'tokentx', 'tokennfttx', 'token1155tx')


def parse_latest(data: dict, category: str) -> dict | None:
    if not isinstance(data, dict):
        raise RuntimeError('Invalid indexed activity provider response')
    rows = data.get('result')
    if str(data.get('status')) != '1':
        msg = str(data.get('message', ''))
        if isinstance(rows, str) and 'no transactions found' in rows.lower():
            return None
        if 'no transactions found' in msg.lower() and isinstance(rows, (str, list)) and not rows:
            return None
        raise RuntimeError('Indexed activity endpoint failed or was rate limited')
    if not isinstance(rows, list):
        raise RuntimeError('Indexed activity endpoint did not return a list')
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            seconds = int(row['timeStamp'])
            if not 1 <= seconds <= int(time.time()) + 300:
                continue
            at = datetime.fromtimestamp(seconds, timezone.utc)
            return {'timestamp': seconds, 'at': at.isoformat(), 'category': category,
                    'tx_hash': str(row.get('hash', ''))[:68]}
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return None


def index_activity(chain: str, address: str, *, key: str | None = None,
                   now: datetime | None = None, sleep_between: float = 0.40) -> dict:
    chain = validate_chain(chain)
    address = validate_address(address)
    key = key if key is not None else os.getenv('ETHERSCAN_API_KEY', '')
    if not key:
        return {'chain': chain, 'address': address, 'provider': 'etherscan_v2',
                'coverage': [], 'coverage_complete': False, 'status': 'not_configured',
                'last_observed_at': None, 'days_since_observed': None,
                'signal': 'unknown', 'note': 'Set ETHERSCAN_API_KEY to enable indexed history.'}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must include timezone')
    latest = None
    success = []
    failures = []
    for category in CATEGORIES:
        query = urlencode({'chainid': CHAIN_IDS[chain], 'module': 'account', 'action': category,
                           'address': address, 'startblock': 0, 'endblock': 999999999,
                           'page': 1, 'offset': 1, 'sort': 'desc', 'apikey': key})
        try:
            entry = parse_latest(json_request(ETHERSCAN_URL + '?' + query), category)
            success.append(category)
            if entry and (latest is None or entry['timestamp'] > latest['timestamp']):
                latest = entry
        except (RuntimeError, ValueError, TypeError):
            failures.append(category)
        if sleep_between and category != CATEGORIES[-1]:
            time.sleep(sleep_between)
    days = max(0, (now - datetime.fromtimestamp(latest['timestamp'], timezone.utc)).days) if latest else None
    coverage_complete = len(success) == len(CATEGORIES)
    signal = ('no_indexed_events' if coverage_complete else 'insufficient_coverage') if latest is None else (
        'older_observed_activity' if days >= 365 else 'recent_observed_activity')
    return {
        'chain': chain, 'address': address, 'provider': 'etherscan_v2',
        'coverage': success, 'coverage_complete': coverage_complete,
        'status': 'indexed' if coverage_complete else 'partial',
        'last_observed_at': latest['at'] if latest else None,
        'last_category': latest['category'] if latest else None,
        'last_tx_hash': latest['tx_hash'] if latest else None,
        'days_since_observed': days,
        'signal': signal,
        'failed_categories': failures,
        'note': 'Latest indexed transfer/transaction signal, not proof of wallet ownership, inactivity across every possible contract event, or recoverability.'
    }
