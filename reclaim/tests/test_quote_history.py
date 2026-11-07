"""Persist only actual provider observations; test fixtures are offline only."""
import pathlib,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import server

ADDR='0x'+'12'*20
TOKEN='0x'+'ab'*20
USDC=server.CHAINS['base']['usdc']
SOURCE='0x Swap API v2 /swap/allowance-holder/price'


class QuoteHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=server.DB_PATH
        server.DB_PATH=pathlib.Path(self.tmp.name)/'history.sqlite'
        server.initialize()
        server.add_wallets('base',[ADDR])
        with server.db() as conn:
            self.wallet=conn.execute('select id from wallets').fetchone()[0]

    def tearDown(self):
        server.DB_PATH=self.old
        self.tmp.cleanup()

    def quote(self,buy='100000000',sell='1000000000000000000',stamp=None):
        return {'source':SOURCE,'chain':'base','sell_token':TOKEN,'buy_token':USDC,
                'sell_amount_raw':sell,'buy_amount_raw':buy,'aave_snapshot_block':100,
                'quoted_at':stamp or datetime.now(timezone.utc).isoformat(),
                'estimated_price_impact':'0.01'}

    def test_saved_exact_provider_amount(self):
        r=server.save_real_market_quote(self.wallet,self.quote())
        self.assertEqual(r['freshness'],'fresh')
        h=server.market_quote_history()
        self.assertEqual(h[0]['buy_amount_raw'],'100000000')
        self.assertFalse(h[0]['executable_quote'])

    def test_rate_change_comparable_exact_amount(self):
        first=server.save_real_market_quote(self.wallet,self.quote())
        second=server.save_real_market_quote(self.wallet,self.quote(buy='101000000'))
        self.assertEqual(second['rate_change_bps'],'100.0000')
        self.assertEqual(second['compared_to_quote_id'],first['quote_id'])

    def test_different_size_has_no_comparison(self):
        server.save_real_market_quote(self.wallet,self.quote())
        second=server.save_real_market_quote(self.wallet,self.quote(buy='202000000',sell='2000000000000000000'))
        self.assertIsNone(second['rate_change_bps'])

    def test_stale_quote_is_not_saved(self):
        old=(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()
        with self.assertRaises(ValueError):
            server.save_real_market_quote(self.wallet,self.quote(stamp=old))
        self.assertEqual(server.market_quote_history(),[])

    def test_unknown_provider_rejected(self):
        d=self.quote()
        d['source']='demo'
        with self.assertRaises(ValueError):
            server.save_real_market_quote(self.wallet,d)

    def test_history_ages_into_stale(self):
        server.save_real_market_quote(self.wallet,self.quote())
        with server.db() as conn:
            conn.execute('update market_quotes set quoted_at=?',
                ((datetime.now(timezone.utc)-timedelta(seconds=125)).isoformat(),))
        self.assertEqual(server.market_quote_history()[0]['freshness'],'stale')

    def test_wallet_filter(self):
        server.save_real_market_quote(self.wallet,self.quote())
        self.assertEqual(server.market_quote_history(wallet_id=99999),[])

    def test_invalid_wallet_filter(self):
        with self.assertRaises(ValueError):
            server.market_quote_history(wallet_id=-1)
