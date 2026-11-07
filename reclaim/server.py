"""Local-first crypto intelligence service. Requires no external Python packages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import csv
import hmac
import io
import json
import os
import sqlite3
import threading
import time
from urllib.parse import urlparse

from engine import CHAINS, discover_block, fetch_prices, rpc_call, scan_wallet, validate_address, validate_chain, number
from activity import index_activity
from aave import read_position
from aave_discovery import scan_borrow_events, current_safe_head, MAX_BLOCK_SPAN
from reserve_analysis import read_reserve_snapshot
from market_price import live_market_price, MarketUnavailable

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "recovery.db"))).resolve()
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
APP_TOKEN = os.environ.get("APP_TOKEN", "")
DB_LOCK = threading.RLock()


@contextmanager
def db():
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript("""
        create table if not exists wallets (
          id integer primary key autoincrement, chain text not null,
          address text not null, label text not null default '',
          source text not null default 'manual',
          created_at text not null default (datetime('now')),
          unique(chain,address)
        );
        create table if not exists observations (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          scanned_at text not null, native_balance text not null,
          usdc_balance text not null, estimated_usd text,
          price_status text not null,
          last_activity text,
          unique(wallet_id,scanned_at)
        );
        create index if not exists observations_wallet on observations(wallet_id,id desc);
        create table if not exists activity_observations (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          scanned_at text not null default (datetime('now')),
          last_observed_at text,
          days_since_observed integer,
          provider text not null,
          status text not null,
          signal text not null,
          coverage_complete integer not null,
          categories text not null
        );
        create index if not exists activity_wallet on activity_observations(wallet_id,id desc);
        create table if not exists aave_observations (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          scanned_at text not null,
          health_factor text,
          debt_base_raw text not null,
          collateral_base_raw text not null,
          signal text not null,
          candidate integer not null
        );
        create index if not exists aave_wallet on aave_observations(wallet_id,id desc);
        create table if not exists aave_borrower_jobs (
          id integer primary key autoincrement, chain text not null,
          next_block integer not null, end_block integer not null,
          blocks_per_run integer not null default 250,
          confirmations integer not null default 20,
          scanned_blocks integer not null default 0,
          borrow_events integer not null default 0,
          status text not null default 'active',
          created_at text not null default (datetime('now')),
          updated_at text not null default (datetime('now')),
          check(blocks_per_run between 1 and 2000),
          check(next_block >= 0), check(end_block >= 0)
        );
        create table if not exists aave_borrow_events (
          chain text not null, tx_hash text not null, log_index integer not null,
          wallet_id integer not null references wallets(id) on delete cascade,
          reserve text not null, block_number integer not null,
          first_seen_at text not null default (datetime('now')),
          primary key(chain, tx_hash, log_index)
        );
        create index if not exists aave_borrow_by_wallet on aave_borrow_events(wallet_id,block_number desc);
        create table if not exists aave_reserve_analyses (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          block_number integer not null,
          analyzed_at text not null default (datetime('now')),
          health_factor text,
          reserve_count integer not null,
          pair_count integer not null,
          snapshot_json text not null,
          execution_ready integer not null default 0 check(execution_ready=0)
        );
        create index if not exists aave_reserve_analysis_latest on aave_reserve_analyses(wallet_id,id desc);
        create table if not exists market_quotes (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          chain text not null, sell_token text not null, buy_token text not null,
          sell_amount_raw text not null, buy_amount_raw text not null,
          aave_snapshot_block integer not null,
          quoted_at text not null, recorded_at text not null,
          source text not null, provider_price_impact text,
          rate_change_bps text, comparable_quote_id integer
        );
        create index if not exists market_quotes_asset_wallet on market_quotes(wallet_id,sell_token,id desc);
        create table if not exists discovery_jobs (
          id integer primary key autoincrement,
          chain text not null,
          next_block integer not null,
          end_block integer not null,
          blocks_per_run integer not null default 3,
          processed_blocks integer not null default 0,
          sampled_addresses integer not null default 0,
          status text not null default 'active',
          created_at text not null default (datetime('now')),
          updated_at text not null default (datetime('now')),
          check(next_block >= 0),
          check(end_block >= 0),
          check(blocks_per_run between 1 and 5)
        );
        """)


def add_wallets(chain, addresses, source="manual"):
    validate_chain(chain)
    if not isinstance(addresses, list) or len(addresses) > 100:
        raise ValueError("Supply at most 100 addresses")
    if not isinstance(source, str) or source not in ("manual", "historical_block", "aave_borrow_event"):
        raise ValueError("Unsupported source")
    normalized = list(dict.fromkeys(validate_address(a) for a in addresses))
    with DB_LOCK, db() as c:
        for a in normalized:
            c.execute("insert or ignore into wallets(chain,address,source) values(?,?,?)", (chain, a, source))
    return normalized


def query_wallets():
    with db() as c:
        rows = c.execute("""
        select w.id,w.chain,w.address,w.label,w.source,w.created_at,
               o.native_balance,o.usdc_balance,o.estimated_usd,o.price_status,o.scanned_at,
               a.last_observed_at as last_activity, a.scanned_at as activity_scanned_at,
               a.status as activity_status,
               a.signal as activity_signal, a.days_since_observed, a.coverage_complete,
               p.health_factor as aave_health_factor, p.signal as aave_signal,
               p.scanned_at as aave_scanned_at
        from wallets w left join observations o on o.id = (
          select max(id) from observations where wallet_id=w.id
        ) left join activity_observations a on a.id = (
          select max(id) from activity_observations where wallet_id=w.id
        ) left join aave_observations p on p.id = (
          select max(id) from aave_observations where wallet_id=w.id
        ) order by w.id desc limit 5000
        """).fetchall()
    return [dict(row) for row in rows]


def scan_ids(ids):
    if not isinstance(ids, list) or len(ids) > 25 or any(isinstance(v, bool) or not isinstance(v, int) for v in ids):
        raise ValueError("Select up to 25 wallet IDs")
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("Select at least one wallet")
    with db() as c:
        wallets = [dict(r) for r in c.execute(
            f"select id,chain,address from wallets where id in ({','.join('?' for _ in ids)})", ids
        ).fetchall()]
    if len(wallets) != len(ids):
        raise ValueError("One or more wallet IDs do not exist")
    try:
        prices = fetch_prices()
    except (RuntimeError, ValueError):
        prices = {}
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {pool.submit(scan_wallet, w["chain"], w["address"], prices): w for w in wallets}
        for future in as_completed(future_map):
            w = future_map[future]
            try:
                scan = future.result()
                with DB_LOCK, db() as c:
                    c.execute("""insert into observations(wallet_id,scanned_at,native_balance,usdc_balance,estimated_usd,price_status,last_activity)
                    values(?,?,?,?,?,?,?)""", (w["id"], scan["scanned_at"], scan["native_balance"], scan["usdc_balance"], scan["estimated_usd"], scan["price_status"], scan["last_activity"]))
                results.append({"id": w["id"], "status": "ok", **scan})
            except Exception as exc:
                results.append({"id": w["id"], "status": "error", "message": str(exc)[:220]})
    return sorted(results, key=lambda x: x["id"])






def create_discovery_job(chain, start_block, end_block, blocks_per_run=3):
    chain = validate_chain(chain)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (start_block, end_block, blocks_per_run)):
        raise ValueError('Block range and batch size must be integers')
    if start_block < 0 or end_block < start_block or end_block - start_block > 10000:
        raise ValueError('Supply a valid ascending range of up to 10001 blocks')
    if not 1 <= blocks_per_run <= 5:
        raise ValueError('Choose between 1 and 5 blocks per batch')
    with DB_LOCK, db() as c:
        c.execute('''insert into discovery_jobs(chain,next_block,end_block,blocks_per_run)
                     values (?,?,?,?)''', (chain, start_block, end_block, blocks_per_run))
        job_id = c.execute('select last_insert_rowid()').fetchone()[0]
    return job_id


def list_discovery_jobs():
    with db() as c:
        rows = c.execute('''select id,chain,next_block,end_block,blocks_per_run,processed_blocks,
                          sampled_addresses,status,created_at,updated_at
                          from discovery_jobs order by id desc limit 200''').fetchall()
    return [dict(row) for row in rows]


def run_discovery_job(job_id, maximum_override=None):
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError('Valid job ID required')
    with DB_LOCK:
        with db() as c:
            job = c.execute('select * from discovery_jobs where id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Discovery job not found')
        if job['status'] != 'active':
            raise ValueError('Discovery job is not active')
        current = job['next_block']
        limit = min(job['blocks_per_run'], maximum_override or 5)
        end = min(job['end_block'], current + limit - 1)
        if current > end:
            raise ValueError('Discovery job has no remaining blocks')
        sampled = 0
        processed = 0
        for height in range(current, end + 1):
            addresses = discover_block(job['chain'], height, maximum=75)
            add_wallets(job['chain'], addresses, source='historical_block')
            sampled += len(addresses)
            processed += 1
            with db() as c:
                c.execute('''update discovery_jobs set next_block=?,processed_blocks=processed_blocks+1,
                             sampled_addresses=sampled_addresses+?,updated_at=datetime('now'),status=? where id=?''',
                          (height + 1, len(addresses), 'complete' if height >= job['end_block'] else 'active', job_id))
    return {'job_id': job_id, 'blocks_processed': processed, 'addresses_sampled': sampled,
            'next_block': current + processed, 'complete': current + processed > job['end_block']}


def pause_discovery_job(job_id):
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError('Valid job ID required')
    with DB_LOCK, db() as c:
        r = c.execute('''update discovery_jobs set status='paused',updated_at=datetime('now')
                         where id=? and status='active' ''', (job_id,))
        if r.rowcount < 1:
            raise ValueError('No active discovery job found')
    return {'job_id': job_id, 'status': 'paused'}



def resume_discovery_job(job_id):
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError('Valid job ID required')
    with DB_LOCK, db() as c:
        r = c.execute('''update discovery_jobs set status='active',updated_at=datetime('now')
                         where id=? and status='paused' ''', (job_id,))
        if r.rowcount < 1:
            raise ValueError('No paused discovery job found')
    return {'job_id': job_id, 'status': 'active'}


def create_aave_borrower_job(chain, lookback_blocks=5000, blocks_per_run=250, confirmations=20):
    """Snapshot a finalized historical block range to discover Aave borrowers."""
    chain = validate_chain(chain)
    for name, value, minimum, maximum in (
        ('lookback_blocks', lookback_blocks, 1, 250000),
        ('blocks_per_run', blocks_per_run, 1, MAX_BLOCK_SPAN),
        ('confirmations', confirmations, 1, 1000),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    end_block = current_safe_head(chain, confirmations)
    start_block = max(0, end_block - lookback_blocks + 1)
    with DB_LOCK, db() as c:
        c.execute('insert into aave_borrower_jobs(chain,next_block,end_block,blocks_per_run,confirmations) values(?,?,?,?,?)',
                  (chain, start_block, end_block, blocks_per_run, confirmations))
        job_id = c.execute('select last_insert_rowid()').fetchone()[0]
    return {'job_id': job_id, 'chain': chain, 'start_block': start_block,
            'end_block': end_block, 'confirmations': confirmations}


def list_aave_borrower_jobs():
    with db() as c:
        rows = c.execute('select * from aave_borrower_jobs order by id desc limit 100').fetchall()
    return [dict(row) for row in rows]


def run_aave_borrower_job(job_id):
    """Atomic cursor advancement: no skipped blocks on transient provider failure."""
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError('Valid borrower job ID required')
    with DB_LOCK:
        with db() as c:
            job = c.execute('select * from aave_borrower_jobs where id=?', (job_id,)).fetchone()
        if job is None or job['status'] != 'active':
            raise ValueError('Active borrower job not found')
        first = job['next_block']
        end = min(job['end_block'], first + job['blocks_per_run'] - 1)
        if first > end:
            raise ValueError('No remaining finalized blocks')
        events = scan_borrow_events(job['chain'], first, end)
        addresses = {ev['address'] for ev in events}
        with db() as c:
            for address in addresses:
                c.execute('insert or ignore into wallets(chain,address,source) values(?,?,?)',
                          (job['chain'], address, 'aave_borrow_event'))
            wallet_ids = {row['address']: row['id'] for row in c.execute(
                'select id,address from wallets where chain=? and address in (' +
                ','.join('?' for _ in addresses) + ')',
                (job['chain'], *addresses)).fetchall()} if addresses else {}
            inserted = 0
            for event in events:
                cur = c.execute('insert or ignore into aave_borrow_events (chain,tx_hash,log_index,wallet_id,reserve,block_number) values(?,?,?,?,?,?)',
                                (job['chain'],event['tx_hash'],event['log_index'],wallet_ids[event['address']],
                                 event['reserve'],event['block_number']))
                inserted += cur.rowcount
            c.execute('update aave_borrower_jobs set next_block=?,scanned_blocks=scanned_blocks+?,borrow_events=borrow_events+?,status=?,updated_at=datetime(\'now\') where id=?',
                      (end+1, end-first+1, inserted, 'complete' if end >= job['end_block'] else 'active', job_id))
        return {'job_id': job_id, 'blocks_processed': end-first+1, 'events_indexed': inserted,
                'unique_borrowers_in_batch': len(addresses), 'wallet_ids': list(wallet_ids.values())[:20],
                'next_block': end+1, 'complete': end >= job['end_block'],
                'position_verified': False, 'execution_ready': False}


def change_aave_borrower_job(job_id, action):
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError('Valid borrower job ID required')
    if action not in ('pause', 'resume'):
        raise ValueError('Unsupported action')
    current = 'active' if action == 'pause' else 'paused'
    target = 'paused' if action == 'pause' else 'active'
    with DB_LOCK, db() as c:
        updated = c.execute('update aave_borrower_jobs set status=?,updated_at=datetime(\'now\') where id=? and status=?',
                            (target,job_id,current))
        if not updated.rowcount:
            raise ValueError('No matching active or paused borrower job')
    return {'job_id': job_id, 'status': target}


def query_borrower_events(limit=100):
    with db() as c:
        rows = c.execute('select e.chain,e.tx_hash,e.log_index,e.reserve,e.block_number,w.address,w.id as wallet_id from aave_borrow_events e join wallets w on w.id=e.wallet_id order by e.block_number desc limit ?',
                         (min(250,max(1,limit)),)).fetchall()
        total = c.execute('select count(*) from aave_borrow_events').fetchone()[0]
    return {'events': [dict(row) for row in rows], 'total_events': total,
            'current_debt_verified': False, 'execution_ready': False}


def _get_wallet_ids(ids, maximum):
    if not isinstance(ids, list) or not 1 <= len(ids) <= maximum or any(
            isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in ids):
        raise ValueError(f"Select 1 to {maximum} wallet IDs")
    ids = list(dict.fromkeys(ids))
    with db() as c:
        wallets = [dict(r) for r in c.execute(
            f"select id,chain,address from wallets where id in ({','.join('?' for _ in ids)})", ids
        ).fetchall()]
    if len(wallets) != len(ids):
        raise ValueError('One or more wallet IDs do not exist')
    return wallets


def scan_activity_ids(ids):
    '''Explicit action only: 5 Etherscan V2 requests per wallet.'''
    wallets = _get_wallet_ids(ids, 5)
    if not os.getenv('ETHERSCAN_API_KEY'):
        raise ValueError('ETHERSCAN_API_KEY is required for indexed activity scanning')
    results = []
    # Sequential by design, to reduce pressure on explorer API quotas.
    for w in wallets:
        try:
            data = index_activity(w['chain'], w['address'])
            with DB_LOCK, db() as c:
                c.execute('''insert into activity_observations (
                    wallet_id,last_observed_at,days_since_observed,provider,status,signal,coverage_complete,categories)
                    values (?,?,?,?,?,?,?,?)''',
                    (w['id'], data.get('last_observed_at'), data.get('days_since_observed'),
                     data['provider'], data['status'], data['signal'], int(data['coverage_complete']),
                     json.dumps(data['coverage'])))
            results.append({'id': w['id'], **data, 'index_status': data['status'], 'status': 'ok'})
        except Exception:
            results.append({'id': w['id'], 'status': 'error', 'message': 'Activity provider unavailable or rate limited'})
    return results


def scan_aave_ids(ids):
    wallets = _get_wallet_ids(ids, 20)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {pool.submit(read_position, w['chain'], w['address']): w for w in wallets}
        for future in as_completed(future_map):
            w = future_map[future]
            try:
                data = future.result()
                with DB_LOCK, db() as c:
                    c.execute('''insert into aave_observations
                        (wallet_id,scanned_at,health_factor,debt_base_raw,collateral_base_raw,signal,candidate)
                        values (?,?,?,?,?,?,?)''',
                        (w['id'], data['scanned_at'], data['health_factor'], data['total_debt_base_raw'],
                         data['total_collateral_base_raw'], data['signal'], int(data['candidate'])))
                results.append({'id': w['id'], 'status': 'ok', **data})
            except Exception:
                results.append({'id': w['id'], 'status': 'error', 'message': 'Aave position read failed'})
    return sorted(results, key=lambda r: r['id'])


def query_aave_candidates():
    with db() as c:
        rows = c.execute('''select w.id,w.chain,w.address,a.scanned_at,a.health_factor,a.debt_base_raw,
                      a.collateral_base_raw,a.signal
                      from wallets w join aave_observations a on a.id=(
                        select max(id) from aave_observations where wallet_id=w.id
                      ) where a.candidate=1 order by a.scanned_at desc limit 250''').fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            at = datetime.fromisoformat(item['scanned_at'].replace('Z', '+00:00'))
            fresh = abs((datetime.now(timezone.utc) - at).total_seconds()) <= 120
        except (ValueError, TypeError, AttributeError):
            fresh = False
        results.append({'execution_ready': False, 'profit_usd': None,
                        'eligibility': 'unverified', 'snapshot_fresh': fresh, **item})
    return results



def analyze_reserve_ids(ids, settings=None):
    """Read and persist actual Aave state, never estimated returns."""
    if settings not in (None, {}):
        raise ValueError('Synthetic profit settings are no longer supported')
    rows=[]
    for wallet in _get_wallet_ids(ids,2):
        try:
            detail=read_reserve_snapshot(wallet['chain'],wallet['address'])
            if detail.get('read_only') is not True or detail.get('execution_ready') is not False:
                raise RuntimeError('Unexpected execution status')
            with DB_LOCK, db() as c:
                c.execute("""insert into aave_reserve_analyses
                    (wallet_id,block_number,health_factor,reserve_count,pair_count,snapshot_json)
                    values (?,?,?,?,?,?)""",
                    (wallet['id'],detail['block_number'],detail['health_factor'],
                     len(detail['reserves']),0,json.dumps(detail)))
            rows.append({'id':wallet['id'],'status':'ok',**detail})
        except Exception:
            rows.append({'id':wallet['id'],'status':'error',
                         'message':'Live Aave reserve read failed. Check RPC settings and rate limits.'})
    return rows


def live_provider_status():
    """Actual network identity and block height, explicitly unavailable on errors."""
    expected={'ethereum':1,'base':8453,'arbitrum':42161,'polygon':137}
    rows=[]
    for chain in CHAINS:
        timestamp=datetime.now(timezone.utc).isoformat()
        try:
            identity=int(rpc_call(chain,'eth_chainId',[]),16)
            height=int(rpc_call(chain,'eth_blockNumber',[]),16)
            if identity!=expected[chain] or height<=0:
                raise RuntimeError('RPC chain ID or block invalid')
            rows.append({'chain':chain,'status':'connected','chain_id':identity,
                         'block_number':height,'observed_at':timestamp})
        except Exception:
            rows.append({'chain':chain,'status':'unavailable','chain_id':None,
                         'block_number':None,'observed_at':timestamp})
    return {'networks':rows,'source':'live_json_rpc','execution_enabled':False}


def list_reserve_analyses(limit=40):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid analysis result limit')
    with db() as c:
        entries = c.execute("""select x.id, x.wallet_id, x.block_number, x.analyzed_at,
                            x.snapshot_json, w.chain, w.address
                            from aave_reserve_analyses x join wallets w on w.id=x.wallet_id
                            where x.id=(select max(y.id) from aave_reserve_analyses y where y.wallet_id=x.wallet_id)
                            order by x.id desc limit ?""",(limit,)).fetchall()
    rows = []
    for entry in entries:
        record = json.loads(entry['snapshot_json'])
        rows.append({'id':entry['wallet_id'],'chain':entry['chain'],'address':entry['address'],
                     'block_number':entry['block_number'], 'analyzed_at':entry['analyzed_at'],
                     'health_factor':record['health_factor'],
                     'reserves':record.get('reserves',[]), 'pairs_evaluated':0,
                     'quote_currency':record['quote_currency'],
                     'emode_category':record['emode_category'],
                     'read_only':True, 'execution_ready':False})
    return rows


def market_quote_history(wallet_id=None, limit=60, freshness_seconds=90):
    """Recorded 0x data only. No past quote is an executable transaction."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Invalid history limit')
    if wallet_id is not None and (type(wallet_id) is not int or wallet_id <= 0):
        raise ValueError('Invalid wallet ID')
    with db() as c:
        if wallet_id is None:
            rows=c.execute("""select q.*,w.address from market_quotes q join wallets w on w.id=q.wallet_id
                              order by q.id desc limit ?""",(limit,)).fetchall()
        else:
            rows=c.execute("""select q.*,w.address from market_quotes q join wallets w on w.id=q.wallet_id
                              where q.wallet_id=? order by q.id desc limit ?""",(wallet_id,limit)).fetchall()
    now=datetime.now(timezone.utc)
    result=[]
    for row in rows:
        item=dict(row)
        age=int((now-datetime.fromisoformat(item['quoted_at'])).total_seconds())
        item['quote_age_seconds']=max(0,age)
        item['freshness']='fresh' if 0 <= age <= freshness_seconds else 'stale'
        item['executable_quote']=False
        item['liquidation_profit_usd']=None
        result.append(item)
    return result


def save_real_market_quote(wallet_id, data):
    """Compare only identical chain, pair and sell amount; preserve exact integers."""
    from decimal import Decimal, localcontext
    if type(wallet_id) is not int or wallet_id <= 0:
        raise ValueError('Invalid wallet ID')
    if data.get('source') != '0x Swap API v2 /swap/allowance-holder/price':
        raise ValueError('Unexpected provider')
    chain=validate_chain(data['chain'])
    sell_token=validate_address(data['sell_token'])
    buy_token=validate_address(data['buy_token'])
    sell_amount,buy_amount=data['sell_amount_raw'],data['buy_amount_raw']
    if any(not isinstance(x,str) or not x.isdecimal() or int(x)<=0 or len(x)>80
           for x in (sell_amount,buy_amount)):
        raise ValueError('Invalid provider amounts')
    quoted_at=data['quoted_at']
    captured=datetime.fromisoformat(quoted_at)
    if captured.tzinfo is None or abs((datetime.now(timezone.utc)-captured).total_seconds())>90:
        raise ValueError('Provider quote is stale')
    block=data['aave_snapshot_block']
    if type(block) is not int or block<=0:
        raise ValueError('Missing observed block')
    with DB_LOCK, db() as c:
        previous=c.execute("""select id,buy_amount_raw from market_quotes
          where wallet_id=? and chain=? and sell_token=? and buy_token=? and sell_amount_raw=?
          order by id desc limit 1""",(wallet_id,chain,sell_token,buy_token,sell_amount)).fetchone()
        change=None
        if previous:
            with localcontext() as ctx:
                ctx.prec=70
                raw=(Decimal(buy_amount)-Decimal(previous['buy_amount_raw']))*Decimal(10000)/Decimal(previous['buy_amount_raw'])
                change=format(raw.quantize(Decimal('0.0001')),'f')
        cursor=c.execute("""insert into market_quotes
          (wallet_id,chain,sell_token,buy_token,sell_amount_raw,buy_amount_raw,aave_snapshot_block,
           quoted_at,recorded_at,source,provider_price_impact,rate_change_bps,comparable_quote_id)
          values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (wallet_id,chain,sell_token,buy_token,sell_amount,buy_amount,block,quoted_at,
           datetime.now(timezone.utc).isoformat(),data['source'],
           data.get('estimated_price_impact'),change,previous['id'] if previous else None))
        quote_id=cursor.lastrowid
    return {'quote_id':quote_id,'rate_change_bps':change,
            'compared_to_quote_id':previous['id'] if previous else None,
            'freshness':'fresh','execution_ready':False}


def quote_observed_collateral(wallet_id, sell_asset):
    """Quote only an actually observed fresh Aave collateral balance; never hypothetical input."""
    if type(wallet_id) is not int or wallet_id <= 0:
        raise ValueError('Valid wallet ID required')
    asset = validate_address(sell_asset)
    with db() as c:
        entry = c.execute("""select s.snapshot_json,s.analyzed_at,w.chain,w.address
                              from aave_reserve_analyses s join wallets w on w.id=s.wallet_id
                              where s.wallet_id=? order by s.id desc limit 1""",(wallet_id,)).fetchone()
    if entry is None:
        raise ValueError('No recorded Aave reserve snapshot. Read this position first.')
    # Reject stale data rather than using outdated amounts or quoting a fictional position.
    snapshot = json.loads(entry['snapshot_json'])
    captured = datetime.fromisoformat(snapshot['scanned_at'])
    if captured.tzinfo is None:
        raise ValueError('Snapshot lacks a timezone')
    age = (datetime.now(timezone.utc)-captured).total_seconds()
    if age < -10 or age > 120:
        raise ValueError('Aave snapshot is stale. Refresh on-chain position first.')
    if snapshot['chain'] != entry['chain'] or snapshot['address'].lower() != entry['address'].lower():
        raise ValueError('Aave observation does not match tracked wallet')
    reserve = next((r for r in snapshot.get('reserves', [])
                    if r['asset'].lower()==asset and r.get('collateral_enabled')), None)
    if reserve is None:
        raise ValueError('Asset is not a recorded collateral reserve in this position')
    amount = reserve['a_token_balance_raw']
    if not isinstance(amount,str) or not amount.isdecimal() or int(amount)<=0:
        raise ValueError('No positive observed collateral quantity available')
    data = live_market_price(snapshot['chain'],asset,amount,snapshot['block_number'])
    saved=save_real_market_quote(wallet_id,data)
    return {**data,**saved,'wallet_id':wallet_id,'collateral_symbol':reserve['symbol'],
            'collateral_decimals':reserve['decimals'],
            'source_explanation':'Aave underlying-equivalent collateral position. Quoted quantity is not spendable by RECLAIM and does not represent a liquidated amount.'}


class AutoScanner:
    '''Optional bounded balance scanning, never automatic financial execution.'''
    def __init__(self):
        try:
            minutes = int(os.getenv('AUTO_SCAN_INTERVAL_MINUTES', '0'))
        except ValueError:
            raise ValueError('AUTO_SCAN_INTERVAL_MINUTES must be an integer')
        if minutes and not 10 <= minutes <= 10080:
            raise ValueError('AUTO_SCAN_INTERVAL_MINUTES must be 0 or between 10 and 10080')
        self.interval_seconds = minutes * 60
        self.batch_limit = min(25, max(1, int(os.getenv('AUTO_SCAN_BATCH_LIMIT', '10'))))
        self.stop_signal = threading.Event()
        self.last_run = None
        self.next_run = None
        self.last_result = None
        self.thread = None
        self.discovery_enabled = os.getenv('AUTO_DISCOVERY_ENABLED', '0') == '1'
        self.aave_borrower_enabled = os.getenv('AUTO_AAVE_BORROWER_ENABLED', '0') == '1'

    def status(self):
        return {'enabled': bool(self.interval_seconds), 'interval_minutes': self.interval_seconds // 60,
                'batch_limit': self.batch_limit, 'last_run': self.last_run,
                'next_run': datetime.fromtimestamp(self.next_run, timezone.utc).isoformat()
                if self.next_run else None, 'last_result': self.last_result,
                'mode': 'balances_and_optional_discovery', 'discovery_enabled': self.discovery_enabled,
                'aave_borrower_enabled': self.aave_borrower_enabled,
                'transactions_enabled': False}

    def tick(self):
        with db() as c:
            rows = c.execute('''select w.id from wallets w left join observations o on o.id=(
                           select max(id) from observations where wallet_id=w.id)
                           order by case when o.scanned_at is null then 0 else 1 end, o.scanned_at asc
                           limit ?''', (self.batch_limit,)).fetchall()
        ids = [r['id'] for r in rows]
        if ids:
            results = scan_ids(ids)
            self.last_result = {'scanned': sum(r['status'] == 'ok' for r in results),
                                'failed': sum(r['status'] != 'ok' for r in results)}
        else:
            self.last_result = {'scanned': 0, 'failed': 0}
        if self.discovery_enabled:
            jobs = [j for j in list_discovery_jobs() if j['status'] == 'active']
            if jobs:
                try:
                    outcome = run_discovery_job(jobs[-1]['id'], maximum_override=2)
                    self.last_result['discovery_blocks'] = outcome['blocks_processed']
                    self.last_result['discovery_addresses'] = outcome['addresses_sampled']
                except Exception:
                    self.last_result['discovery_error'] = 'Scheduled discovery scan failed'
        if self.aave_borrower_enabled:
            jobs = [j for j in list_aave_borrower_jobs() if j['status'] == 'active']
            if jobs:
                try:
                    outcome = run_aave_borrower_job(jobs[-1]['id'])
                    self.last_result['aave_borrow_events'] = outcome['events_indexed']
                    self.last_result['aave_borrow_blocks'] = outcome['blocks_processed']
                except Exception:
                    self.last_result['aave_borrow_error'] = 'Automatic borrower index failed; checkpoint retained'
        self.last_run = datetime.now(timezone.utc).isoformat()

    def _loop(self):
        self.next_run = time.time() + 10
        while not self.stop_signal.wait(max(0, self.next_run - time.time())):
            try:
                self.tick()
            except Exception:
                self.last_result = {'error': 'Automatic balance scan failed'}
                self.last_run = datetime.now(timezone.utc).isoformat()
            self.next_run = time.time() + self.interval_seconds

    def start(self):
        if self.interval_seconds:
            self.thread = threading.Thread(target=self._loop, daemon=True, name='reclaim-autoscan')
            self.thread.start()

    def stop(self):
        self.stop_signal.set()
        if self.thread:
            self.thread.join(timeout=2)


AUTO_SCANNER = None


class Handler(BaseHTTPRequestHandler):
    server_version = "RecoveryEngine/0.1"

    def _headers(self, status=200, mimetype="application/json; charset=utf-8", length=None):
        self.send_response(status)
        self.send_header("Content-Type", mimetype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, payload, status=200):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self._headers(status, length=len(raw))
        self.wfile.write(raw)

    def _authorized(self):
        if not APP_TOKEN:
            return True  # only allowed when bound to loopback; enforced at startup
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + APP_TOKEN)

    def _body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid body length")
        if size <= 0 or size > 250_000:
            raise ValueError("JSON body must be between 1 and 250000 bytes")
        obj = json.loads(self.rfile.read(size))
        if not isinstance(obj, dict):
            raise ValueError("JSON body must be an object")
        return obj

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/styles.css", "/app.js"):
            actual = STATIC / ("index.html" if path == "/" else path.lstrip("/"))
            kind = "text/html; charset=utf-8" if actual.suffix == ".html" else "text/css; charset=utf-8" if actual.suffix == ".css" else "text/javascript; charset=utf-8"
            raw = actual.read_bytes()
            self._headers(200, kind, len(raw))
            self.wfile.write(raw)
            return
        if not self._authorized():
            self._json({"error": "Access token required"}, 401)
            return
        try:
            if path == "/api/health":
                self._json({"ok": True, "mode": "read_only", "storage": "sqlite", "chains": list(CHAINS), "aave_read_only": True, "reserve_screening": "live_onchain_only", "indexed_activity_configured": bool(os.getenv("ETHERSCAN_API_KEY"))})
            elif path == "/api/wallets":
                self._json({"wallets": query_wallets()})
            elif path == "/api/opportunities":
                self._json({"candidates": query_aave_candidates(), "execution_ready": False})
            elif path == "/api/market/status":
                self._json({"provider":"0x Swap API v2","configured":bool(os.getenv("ZEROX_API_KEY")),
                            "mode":"live_price_only","execution_enabled":False})
            elif path == "/api/market/history":
                from urllib.parse import parse_qs
                params=parse_qs(urlparse(self.path).query)
                value=params.get('wallet_id',[None])[0]
                if value is not None and (not value.isdecimal() or int(value)<=0):
                    raise ValueError('Invalid wallet ID')
                self._json({"quotes":market_quote_history(wallet_id=int(value) if value else None),
                            "execution_enabled":False})
            elif path == "/api/network/status":
                self._json(live_provider_status())
            elif path == "/api/aave/reserves/analyses":
                self._json({"analyses": list_reserve_analyses(), "execution_ready": False})
            elif path == "/api/discovery/jobs":
                self._json({"jobs": list_discovery_jobs()})
            elif path == "/api/aave/borrowers/jobs":
                self._json({"jobs": list_aave_borrower_jobs()})
            elif path == "/api/aave/borrowers/events":
                self._json(query_borrower_events())
            elif path == "/api/monitor":
                self._json({"scanner": AUTO_SCANNER.status() if AUTO_SCANNER else {"enabled": False},
                            "indexed_activity_configured": bool(os.getenv('ETHERSCAN_API_KEY')),
                            "aave_read_only": True, "aave_borrower_jobs": len(list_aave_borrower_jobs())})
            elif path == "/api/chains":
                self._json({"chains": [{"id": key, "name": val["label"], "symbol": val["symbol"]} for key, val in CHAINS.items()]})
            elif path == "/api/export.csv":
                stream = io.StringIO()
                rows = query_wallets()
                cols = ("chain", "address", "label", "source", "native_balance", "usdc_balance", "estimated_usd", "price_status", "scanned_at", "last_activity", "days_since_observed", "activity_status", "activity_signal", "coverage_complete", "aave_health_factor", "aave_signal")
                writer = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({col: "'" + str(row[col]) if str(row[col]).startswith(("=", "+", "-", "@")) else row[col] for col in cols})
                raw = stream.getvalue().encode("utf-8")
                self._headers(200, "text/csv; charset=utf-8", len(raw))
                self.wfile.write(raw)
            else:
                self._json({"error": "Not found"}, 404)
        except Exception:
            self._json({"error": "Unable to complete request"}, 500)

    def do_POST(self):
        if not self._authorized():
            self._json({"error": "Access token required"}, 401)
            return
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/wallets":
                normalized = add_wallets(body.get("chain", "ethereum"), body.get("addresses", []))
                self._json({"added_or_existing": len(normalized), "wallets": query_wallets()})
            elif path == "/api/scan":
                self._json({"results": scan_ids(body.get("ids", []))})
            elif path == "/api/discover":
                chain = validate_chain(body.get("chain", "ethereum"))
                block = body.get("block_number")
                addresses = discover_block(chain, block, maximum=75)
                add_wallets(chain, addresses, source="historical_block")
                self._json({"discovered": len(addresses), "block_number": block, "addresses": addresses})
            elif path == "/api/discovery/jobs":
                job_id = create_discovery_job(body.get('chain'), body.get('start_block'),
                                              body.get('end_block'), body.get('blocks_per_run', 3))
                self._json({"job_id": job_id, "jobs": list_discovery_jobs()}, 201)
            elif path == "/api/discovery/jobs/run":
                self._json(run_discovery_job(body.get('job_id')))
            elif path == "/api/discovery/jobs/pause":
                self._json(pause_discovery_job(body.get('job_id')))
            elif path == "/api/discovery/jobs/resume":
                self._json(resume_discovery_job(body.get('job_id')))
            elif path == "/api/aave/borrowers/jobs":
                result = create_aave_borrower_job(body.get('chain','ethereum'),
                       body.get('lookback_blocks',5000), body.get('blocks_per_run',250),
                       body.get('confirmations',20))
                self._json(result,201)
            elif path == "/api/aave/borrowers/jobs/run":
                self._json(run_aave_borrower_job(body.get('job_id')))
            elif path == "/api/aave/borrowers/jobs/pause":
                self._json(change_aave_borrower_job(body.get('job_id'), 'pause'))
            elif path == "/api/aave/borrowers/jobs/resume":
                self._json(change_aave_borrower_job(body.get('job_id'), 'resume'))
            elif path == "/api/activity/scan":
                self._json({"results": scan_activity_ids(body.get('ids', []))})
            elif path == "/api/aave/scan":
                self._json({"results": scan_aave_ids(body.get('ids', []))})
            elif path == "/api/market/price":
                self._json(quote_observed_collateral(body.get("wallet_id"),body.get("sell_asset")))
            elif path == "/api/aave/reserves/analyze":
                self._json({"analyses": analyze_reserve_ids(body.get('ids', [])),
                            "read_only": True, "execution_ready": False})
            else:
                self._json({"error": "Not found"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except MarketUnavailable as exc:
            self._json({"error": str(exc), "provider_status":"unavailable"}, 503)
        except Exception as exc:
            self._json({"error": "Operation failed: " + str(exc)[:180]}, 502)

    def log_message(self, fmt, *args):
        # Avoid emitting wallet addresses, request bodies or tokens to logs.
        pass


def main():
    if HOST not in ("127.0.0.1", "localhost", "::1") and not APP_TOKEN:
        raise SystemExit("Refusing network bind without APP_TOKEN. Set a strong token or use HOST=127.0.0.1")
    initialize()
    global AUTO_SCANNER
    AUTO_SCANNER = AutoScanner()
    AUTO_SCANNER.start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Recovery Engine running at http://{HOST}:{PORT} [read-only; execution disabled]", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AUTO_SCANNER.stop()
        srv.server_close()


if __name__ == "__main__":
    main()
