"""0x market-price adapter tests. Fixtures are test-only, never a production fallback."""
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import market_price as mp
import server

ADDR = '0x' + '12' * 20
TOKEN = '0x' + 'ab' * 20
USDC = server.CHAINS['base']['usdc']


def provider_response():
    return {'liquidityAvailable': True, 'sellAmount': '1000000000000000000',
            'buyAmount': '3010000000', 'estimatedPriceImpact': '0.01'}


class PriceAdapterTests(unittest.TestCase):
    def test_valid_provider_amounts(self):
        result = mp.parse_price(provider_response(), chain='base', asset=TOKEN,
                                buy_token=USDC, sell_amount='1000000000000000000',
                                snapshot_block=100)
        self.assertEqual(result['buy_amount_raw'], '3010000000')
        self.assertEqual(result['aave_snapshot_block'], 100)
        self.assertFalse(result['executable_quote'])
        self.assertIsNone(result['liquidation_profit_usd'])

    def test_reject_absent_liquidity(self):
        row = provider_response()
        row['liquidityAvailable'] = False
        with self.assertRaises(mp.MarketUnavailable):
            mp.parse_price(row, chain='base', asset=TOKEN, buy_token=USDC,
                           sell_amount='1000000000000000000', snapshot_block=100)

    def test_reject_mismatched_amount(self):
        row = provider_response()
        row['sellAmount'] = '100'
        with self.assertRaises(mp.MarketUnavailable):
            mp.parse_price(row, chain='base', asset=TOKEN, buy_token=USDC,
                           sell_amount='1000000000000000000', snapshot_block=100)

    def test_reject_missing_price_or_invalid_impact(self):
        for change in ({'buyAmount': '0'}, {'buyAmount': None},
                       {'estimatedPriceImpact': 'NaN'}):
            row = {**provider_response(), **change}
            with self.assertRaises(mp.MarketUnavailable):
                mp.parse_price(row, chain='base', asset=TOKEN, buy_token=USDC,
                               sell_amount='1000000000000000000', snapshot_block=100)

    def test_missing_provider_key_fails_closed(self):
        with patch.dict('os.environ', {'ZEROX_API_KEY': ''}):
            with self.assertRaises(mp.MarketUnavailable):
                mp.live_market_price('base', TOKEN, '1000000000000000000', 100)

    def test_invalid_amount_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            mp.live_market_price('base', TOKEN, '0', 100)
        with self.assertRaises(ValueError):
            mp.live_market_price('base', TOKEN, '1', 0)


class ObservedCollateralTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        server.DB_PATH = pathlib.Path(self.tmp.name) / 'test.sqlite'
        server.initialize()
        server.add_wallets('base', [ADDR])
        with server.db() as conn:
            self.id = conn.execute('select id from wallets').fetchone()[0]

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.tmp.cleanup()

    def store(self, age_seconds=0):
        snapshot = {
            'chain':'base', 'address':ADDR.lower(), 'block_number':100,
            'scanned_at':(datetime.now(timezone.utc)-timedelta(seconds=age_seconds)).isoformat(),
            'reserves':[{'asset':TOKEN, 'symbol':'WETH', 'decimals':18,
                         'collateral_enabled':True,
                         'a_token_balance_raw':'1000000000000000000'}]
        }
        with server.db() as conn:
            conn.execute("""insert into aave_reserve_analyses
                (wallet_id,block_number,health_factor,reserve_count,pair_count,snapshot_json)
                values (?,?,?,?,?,?)""",
                (self.id, 100, '0.95', 1, 0, json.dumps(snapshot)))

    def test_requires_actual_snapshot(self):
        with self.assertRaises(ValueError):
            server.quote_observed_collateral(self.id, TOKEN)

    def test_rejects_stale_snapshot(self):
        self.store(age_seconds=180)
        with patch.object(server, 'live_market_price') as quote:
            with self.assertRaises(ValueError):
                server.quote_observed_collateral(self.id, TOKEN)
            quote.assert_not_called()

    def test_rejects_unseen_asset(self):
        self.store()
        with self.assertRaises(ValueError):
            server.quote_observed_collateral(self.id, '0x' + '34' * 20)

    def test_passes_observed_amount_only(self):
        self.store()
        reply = {'source':'0x','buy_amount_raw':'3010000000'}
        with patch.object(server, 'live_market_price', return_value=reply) as quote, \
             patch.object(server, 'save_real_market_quote', return_value={'quote_id': 1}):
            actual = server.quote_observed_collateral(self.id, TOKEN)
        quote.assert_called_once_with('base', TOKEN, '1000000000000000000', 100)
        self.assertEqual(actual['wallet_id'], self.id)
        self.assertIn('not spendable', actual['source_explanation'])


if __name__ == '__main__':
    unittest.main()
