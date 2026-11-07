"""Unit tests for real-observation adapters, with offline RPC patches only in tests."""
import pathlib,sys,unittest
from decimal import Decimal
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import reserve_analysis as ra
import server

class LiveReads(unittest.TestCase):
    def test_reject_corrupt_abi(self):
        for raw in ('0x','0x1234','invalid',None):
            with self.assertRaises(RuntimeError): ra.abi_words(raw)
    def test_reserve_user_fields(self):
        raw='0x'+''.join(format(x,'064x') for x in [500,0,300,0,0,0,0,0,1])
        d=ra.decode_reserve_user(raw)
        self.assertEqual(d['variable_debt_raw'],300)
        self.assertTrue(d['collateral_enabled'])
    def test_oracle_units(self):
        self.assertEqual(ra.price_base(1000000,6,100000000,100000000),Decimal('1'))
    def test_no_synthetic_settings(self):
        with self.assertRaises(ValueError):server.analyze_reserve_ids([],{ 'gas_units':650000 })
    def test_provider_unavailable_stays_unavailable(self):
        with patch.object(server,'rpc_call',side_effect=RuntimeError('network')):
            d=server.live_provider_status()
        self.assertEqual(len(d['networks']),4)
        self.assertTrue(all(n['status']=='unavailable' and n['block_number'] is None for n in d['networks']))
    def test_rpc_chain_identity(self):
        with patch.object(server,'rpc_call',side_effect=lambda chain,method,args:'0x1' if method=='eth_chainId' else '0x1234'):
            d=server.live_provider_status()
        self.assertEqual(d['networks'][0]['status'],'connected')
        self.assertTrue(all(n['status']=='unavailable' for n in d['networks'][1:]))
