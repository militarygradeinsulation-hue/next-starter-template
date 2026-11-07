"""Deterministic adapter tests: no external API calls or RPC credits."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import activity
import aave
import server

ADDR = '0x' + '12' * 20


class ActivityTests(unittest.TestCase):
    def test_missing_api_key_is_unknown_not_abandoned(self):
        with patch.dict(os.environ, {}, clear=True):
            result = activity.index_activity('ethereum', ADDR)
        self.assertEqual(result['signal'], 'unknown')
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(result['status'], 'not_configured')

    def test_parse_latest(self):
        tx = {'hash': '0xabc', 'timeStamp': '1600000000'}
        result = activity.parse_latest({'status': '1', 'result': [tx]}, 'tokentx')
        self.assertEqual(result['timestamp'], 1600000000)
        self.assertEqual(result['category'], 'tokentx')
        self.assertIsNone(activity.parse_latest({'status': '0', 'result': 'No transactions found',
                                                   'message': 'No transactions found'}, 'txlist'))
        with self.assertRaises(RuntimeError):
            activity.parse_latest({'status': '0', 'result': 'Invalid API Key'}, 'txlist')

    def test_indexed_old_activity_does_not_claim_recoverability(self):
        returns = [
            {'status': '1', 'result': [{'hash': '0xabc', 'timeStamp': '1600000000'}]},
            *[{'status': '0', 'message': 'No transactions found',
               'result': 'No transactions found'} for _ in range(4)]
        ]
        with patch.object(activity, 'json_request', side_effect=returns) as requested:
            result = activity.index_activity('base', ADDR, key='placeholder',
                                             now=datetime(2026, 11, 7, tzinfo=timezone.utc),
                                             sleep_between=0)
        self.assertEqual(len(requested.call_args_list), 5)
        self.assertIn('chainid=8453', requested.call_args_list[0].args[0])
        self.assertEqual(result['signal'], 'older_observed_activity')
        self.assertEqual(result['status'], 'indexed')
        self.assertTrue(result['coverage_complete'])
        self.assertNotIn('recoverable', str(result).lower())

    def test_partial_coverage_never_counts_as_complete(self):
        with patch.object(activity, 'json_request', return_value={'status': '0', 'result': 'NOTOK'}):
            result = activity.index_activity('polygon', ADDR, key='placeholder', sleep_between=0)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['signal'], 'insufficient_coverage')
        self.assertFalse(result['coverage_complete'])


class AaveTests(unittest.TestCase):
    @staticmethod
    def words(*values):
        return '0x' + ''.join(f'{v:064x}' for v in values)

    def test_pool_decode(self):
        self.assertEqual(aave.decode_account_data(self.words(1, 2, 3, 4, 5, 6)), (1, 2, 3, 4, 5, 6))
        for raw in ('0x', '0xZZ', '1' * 64):
            with self.assertRaises(RuntimeError):
                aave.decode_account_data(raw)

    def test_live_hf_candidate_is_not_execution_ready(self):
        raw = self.words(800_000_000_000, 750_000_000_000, 0, 8000, 7000, 850_000_000_000_000_000)
        with patch.object(aave, 'rpc_call', return_value=raw) as rpc:
            result = aave.read_position('ethereum', ADDR)
        self.assertEqual(result['signal'], 'below_one_candidate')
        self.assertTrue(result['candidate'])
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['health_factor'], '0.850000')
        self.assertEqual(rpc.call_args.args[1], 'eth_call')
        self.assertEqual(rpc.call_args.args[2][0]['data'][:10], '0xbf92857c')

    def test_no_debt_does_not_show_maximum_uint_as_health(self):
        raw = self.words(0, 0, 0, 0, 0, 2**256 - 1)
        with patch.object(aave, 'rpc_call', return_value=raw):
            result = aave.read_position('arbitrum', ADDR)
        self.assertEqual(result['signal'], 'no_debt')
        self.assertIsNone(result['health_factor'])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DB_PATH
        server.DB_PATH = pathlib.Path(self.tmp.name) / 'test.db'
        server.initialize()
        server.add_wallets('ethereum', [ADDR])
        self.wallet_id = server.query_wallets()[0]['id']

    def tearDown(self):
        server.DB_PATH = self.old
        self.tmp.cleanup()

    def test_aave_observation_and_candidate_query(self):
        result = {'chain': 'ethereum', 'address': ADDR, 'scanned_at': '2026-11-07T13:00:00Z',
                  'health_factor': '0.900000', 'total_debt_base_raw': '2000',
                  'total_collateral_base_raw': '1000', 'signal': 'below_one_candidate',
                  'candidate': True}
        with patch.object(server, 'read_position', return_value=result):
            scanned = server.scan_aave_ids([self.wallet_id])
        self.assertEqual(scanned[0]['status'], 'ok')
        candidates = server.query_aave_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0]['profit_usd'])
        self.assertFalse(candidates[0]['execution_ready'])
        self.assertEqual(server.query_wallets()[0]['aave_signal'], 'below_one_candidate')

    def test_etherscan_activity_persistence(self):
        fake = {'chain': 'ethereum', 'address': ADDR, 'provider': 'etherscan_v2',
                'last_observed_at': '2020-01-01T00:00:00Z', 'days_since_observed': 2500,
                'status': 'indexed', 'signal': 'older_observed_activity',
                'coverage_complete': True, 'coverage': ['txlist'], 'note': 'test'}
        with patch.dict(os.environ, {'ETHERSCAN_API_KEY': 'testing'}):
            with patch.object(server, 'index_activity', return_value=fake):
                scanned = server.scan_activity_ids([self.wallet_id])
        self.assertEqual(scanned[0]['status'], 'ok')
        entry = server.query_wallets()[0]
        self.assertEqual(entry['days_since_observed'], 2500)
        self.assertEqual(entry['last_activity'], '2020-01-01T00:00:00Z')
        self.assertEqual(entry['activity_signal'], 'older_observed_activity')

    def test_automatic_scheduler_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            worker = server.AutoScanner()
        self.assertFalse(worker.status()['enabled'])
        self.assertFalse(worker.status()['transactions_enabled'])

    def test_scheduler_selects_watchlist_and_saves_results(self):
        with patch.dict(os.environ, {'AUTO_SCAN_INTERVAL_MINUTES': '10'}):
            worker = server.AutoScanner()
        scan = {'chain': 'ethereum', 'address': ADDR, 'native_balance': '0', 'usdc_balance': '0',
                'estimated_usd': None, 'price_status': 'unavailable', 'last_activity': None,
                'scanned_at': '2026-11-07T13:00:00+00:00'}
        with patch.object(server, 'fetch_prices', return_value={}):
            with patch.object(server, 'scan_wallet', return_value=scan):
                worker.tick()
        self.assertEqual(worker.last_result['scanned'], 1)
        self.assertEqual(server.query_wallets()[0]['native_balance'], '0')

    def test_discovery_job_creates_addresses_and_checkpoints(self):
        with patch.object(server, 'discover_block', side_effect=[[ADDR], ['0x' + '34' * 20]]) as sampled:
            job_id = server.create_discovery_job('base', 100, 101, 2)
            result = server.run_discovery_job(job_id)
        self.assertEqual(result['blocks_processed'], 2)
        self.assertTrue(result['complete'])
        self.assertEqual(sampled.call_count, 2)
        jobs = server.list_discovery_jobs()
        self.assertEqual(jobs[0]['status'], 'complete')
        self.assertEqual(jobs[0]['next_block'], 102)
        self.assertEqual(jobs[0]['sampled_addresses'], 2)
        self.assertEqual(len(server.query_wallets()), 3)

    def test_discovery_job_holds_checkpoint_on_provider_failure(self):
        with patch.object(server, 'discover_block', side_effect=[[ADDR], RuntimeError('provider failed')]):
            job_id = server.create_discovery_job('ethereum', 50, 51, 2)
            with self.assertRaises(RuntimeError):
                server.run_discovery_job(job_id)
        jobs = server.list_discovery_jobs()
        self.assertEqual(jobs[0]['next_block'], 51)
        self.assertEqual(jobs[0]['processed_blocks'], 1)
        self.assertEqual(jobs[0]['status'], 'active')

    def test_discovery_job_pause_and_input_bounds(self):
        with self.assertRaises(ValueError):
            server.create_discovery_job('base', 200, 150)
        with self.assertRaises(ValueError):
            server.create_discovery_job('base', 0, 10001, 10)
        job_id = server.create_discovery_job('base', 0, 3)
        self.assertEqual(server.pause_discovery_job(job_id)['status'], 'paused')
        with self.assertRaises(ValueError):
            server.run_discovery_job(job_id)
        self.assertEqual(server.resume_discovery_job(job_id)['status'], 'active')
        self.assertEqual(server.list_discovery_jobs()[0]['status'], 'active')

    def test_reject_unknown_wallet_ids(self):
        with self.assertRaises(ValueError):
            server.scan_aave_ids([9876])
        with self.assertRaises(ValueError):
            server.scan_aave_ids(list(range(1, 30)))


if __name__ == '__main__':
    unittest.main()
