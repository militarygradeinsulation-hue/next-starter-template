"""Evidence-only Aave V3 borrower discovery via Pool Borrow events.

Borrow events identify accounts on whose behalf debt was issued historically.
An event is NOT evidence the debt is still outstanding. Current state must be
read from getUserAccountData before considering any liquidation scenario.

Nothing in this module can sign, transfer, or broadcast transactions.
"""
from __future__ import annotations

import re
from engine import rpc_call, validate_chain
from aave import POOLS

# keccak256('Borrow(address,address,address,uint256,uint8,uint256,uint16)')
# Aave V3 IPool: topic1=reserve; topic2=onBehalfOf; topic3=referralCode.
BORROW_TOPIC = '0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0'
HEX_32 = re.compile(r'^0x[0-9a-fA-F]{64}$')
HEX_HASH = re.compile(r'^0x[0-9a-fA-F]{64}$')
MAX_LOGS_PER_REQUEST = 3000
MAX_BLOCK_SPAN = 2000


def decode_borrow_log(chain: str, log: dict) -> dict:
    """Reject malformed/nonmatching event logs rather than invent borrower IDs."""
    chain = validate_chain(chain)
    if not isinstance(log, dict):
        raise ValueError('Aave Borrow log must be an object')
    if str(log.get('address', '')).lower() != POOLS[chain].lower():
        raise ValueError('Log emitter is not the configured Aave V3 Pool')
    topics = log.get('topics')
    if not isinstance(topics, list) or len(topics) != 4 or any(not isinstance(t, str) or not HEX_32.fullmatch(t) for t in topics):
        raise ValueError('Unexpected Aave Borrow event topics')
    if topics[0].lower() != BORROW_TOPIC:
        raise ValueError('Not an Aave Borrow event')
    # ABI indexed address must be left padded with 12 zero bytes.
    for topic in (topics[1], topics[2]):
        if int(topic[2:26], 16) != 0:
            raise ValueError('Invalid ABI address padding')
    address = '0x' + topics[2][-40:].lower()
    reserve = '0x' + topics[1][-40:].lower()
    tx_hash = log.get('transactionHash')
    if not isinstance(tx_hash, str) or not HEX_HASH.fullmatch(tx_hash):
        raise ValueError('Missing valid event transaction hash')
    block_hex = log.get('blockNumber')
    index_hex = log.get('logIndex')
    if not isinstance(block_hex, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', block_hex):
        raise ValueError('Invalid event block number')
    if not isinstance(index_hex, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', index_hex):
        raise ValueError('Invalid event log index')
    if log.get('removed') is True:
        raise ValueError('Removed/reorganized event cannot be indexed')
    return {'chain': chain, 'address': address, 'reserve': reserve,
            'block_number': int(block_hex, 16), 'log_index': int(index_hex, 16),
            'tx_hash': tx_hash.lower(), 'evidence': 'historical_borrow_event',
            'current_debt_verified': False}


def scan_borrow_events(chain: str, first_block: int, last_block: int) -> list[dict]:
    """Fetch bounded Pool logs. On RPC failure the caller MUST keep its checkpoint."""
    chain = validate_chain(chain)
    if any(isinstance(b, bool) or not isinstance(b, int) for b in (first_block, last_block)):
        raise ValueError('Block heights must be integers')
    if first_block < 0 or last_block < first_block or last_block - first_block + 1 > MAX_BLOCK_SPAN:
        raise ValueError(f'Scan between 1 and {MAX_BLOCK_SPAN} consecutive blocks')
    raw = rpc_call(chain, 'eth_getLogs', [{
        'address': POOLS[chain], 'fromBlock': hex(first_block), 'toBlock': hex(last_block),
        'topics': [BORROW_TOPIC],
    }])
    if not isinstance(raw, list):
        raise RuntimeError('Provider did not return a log array')
    if len(raw) >= MAX_LOGS_PER_REQUEST:
        raise RuntimeError('Too many Aave events in one response; split into smaller ranges to avoid truncation')
    events = []
    for entry in raw:
        parsed = decode_borrow_log(chain, entry)
        if not first_block <= parsed['block_number'] <= last_block:
            raise RuntimeError('Provider returned event outside requested block range')
        events.append(parsed)
    return events


def current_safe_head(chain: str, confirmations: int = 20) -> int:
    if isinstance(confirmations, bool) or not isinstance(confirmations, int) or not 1 <= confirmations <= 1000:
        raise ValueError('Confirmations must be between 1 and 1000')
    height_hex = rpc_call(validate_chain(chain), 'eth_blockNumber', [])
    if not isinstance(height_hex, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', height_hex):
        raise RuntimeError('Invalid latest block response')
    return max(0, int(height_hex, 16) - confirmations)
