import pathlib
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from engine import validate_address, validate_chain, scan_wallet, discover_block
import engine
import server
from decimal import Decimal

ADDR = "0x" + "12" * 20

class EngineTests(unittest.TestCase):
    def test_address_validation(self):
        self.assertEqual(validate_address(ADDR.upper().replace('0X','0x')), ADDR.lower())
        for a in ("0xabc", "no", "0x" + "g" * 40, None):
            with self.assertRaises(ValueError):
                validate_address(a)

    def test_chain_rejection(self):
        with self.assertRaises(ValueError):
            validate_chain('bitcoin')

    def test_rpc_scan_usdc(self):
        responses = [hex(2 * 10**18), hex(13_750_000)]
        with patch.object(engine, 'rpc_call', side_effect=responses):
            scanned = scan_wallet('base', ADDR, {"ethereum": Decimal("3000"), "usd-coin": Decimal("1")})
        self.assertEqual(scanned['native_balance'], '2')
        self.assertEqual(scanned['usdc_balance'], '13.75')
        self.assertEqual(scanned['estimated_usd'], '6013.75')
        self.assertFalse(scanned['dormancy_verified'])
        self.assertEqual(scanned['recoverability'], 'ownership_authorization_required')

    def test_no_fake_price(self):
        with patch.object(engine, 'rpc_call', side_effect=['0x1', '0x0']):
            scanned = scan_wallet('base', ADDR, {})
        self.assertIsNone(scanned['estimated_usd'])

    def test_discover_deduplicates(self):
        with patch.object(engine, 'rpc_call', return_value={'transactions':[{'from':ADDR, 'to': ADDR}, {'from':ADDR, 'to': '0x' + 'ab' * 20}]}):
            found = discover_block('ethereum', 100)
        self.assertEqual(len(found), 2)

    def test_discover_no_negative_blocks(self):
        with self.assertRaises(ValueError):
            discover_block('ethereum', -1)

class SqliteTests(unittest.TestCase):
    def test_wallet_persistence_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior = server.DB_PATH
            try:
                server.DB_PATH = pathlib.Path(tmp) / 'test.sqlite'
                server.initialize()
                server.add_wallets('base', [ADDR,ADDR])
                server.add_wallets('base', [ADDR])
                self.assertEqual(len(server.query_wallets()), 1)
            finally:
                server.DB_PATH = prior

if __name__ == '__main__':
    unittest.main()
