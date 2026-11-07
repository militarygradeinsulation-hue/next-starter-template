"""No network, credentials or transactions in reserve-analysis tests."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import reserve_analysis as ra
import server


def words(*values):
    return '0x' + ''.join(f'{int(v):064x}' for v in values)


COLL = '0x' + '11' * 20
DEBT = '0x' + '22' * 20
BORROWER = '0x' + 'aa' * 20


def make_config(decimals, threshold, bonus=10500, fee=1000, active=True, paused=False):
    value = (decimals << 48) | (threshold << 16) | (bonus << 32) | (fee << 152)
    if active:
        value |= 1 << 56
    if paused:
        value |= 1 << 60
    return words(value)


def example_snapshot(emode=0, chain='ethereum'):
    return {
        'chain': chain, 'address': BORROWER, 'block_number': 321,
        'health_factor': '0.900000', 'quote_currency': 'USD',
        'emode_category': emode,
        'debt_value_base': '10000', 'collateral_value_base': '10000',
        'reserves': [
            {'asset': COLL, 'symbol': 'WETH', 'collateral_enabled': True,
             'collateral_value_base': '10000', 'debt_value_base': '0',
             'active': True, 'paused': False, 'liquidation_bonus_bps': 10500,
             'protocol_fee_bps': 1000},
            {'asset': DEBT, 'symbol': 'USDC', 'collateral_enabled': False,
             'collateral_value_base': '0', 'debt_value_base': '10000',
             'active': True, 'paused': False, 'liquidation_bonus_bps': 10500,
             'protocol_fee_bps': 1000},
        ],
    }


class TestABI(unittest.TestCase):
    def test_addresses_round_trip(self):
        self.assertEqual(ra.abi_addresses(words(32, 2, int(COLL,16), int(DEBT,16))),
                         [COLL, DEBT])

    def test_reject_invalid_offset(self):
        with self.assertRaises(RuntimeError):
            ra.abi_addresses(words(0,1,int(COLL,16)))

    def test_reject_duplicate_reserves(self):
        with self.assertRaises(RuntimeError):
            ra.abi_addresses(words(32,2,int(COLL,16),int(COLL,16)))

    def test_reject_noncanonical_address(self):
        with self.assertRaises(RuntimeError):
            ra.abi_addresses(words(32,1,1<<200))

    def test_reject_oversized_reserve_list(self):
        with self.assertRaises(RuntimeError):
            ra.abi_addresses(words(32,ra.MAX_RESERVES+1))

    def test_reject_malformed_abi(self):
        for raw in ('0x', 'bad', '0x123', None):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                ra.abi_words(raw)

    def test_config_bits(self):
        cfg=ra.decode_config(make_config(18,8000,10750,1250,True,True))
        self.assertEqual(cfg['decimals'],18)
        self.assertEqual(cfg['liquidation_threshold_bps'],8000)
        self.assertEqual(cfg['liquidation_bonus_bps'],10750)
        self.assertEqual(cfg['protocol_fee_bps'],1250)
        self.assertTrue(cfg['active'])
        self.assertTrue(cfg['paused'])

    def test_user_reserve_abi(self):
        user=ra.decode_reserve_user(words(500,0,300,0,0,0,0,0,1))
        self.assertEqual(user['a_token_balance_raw'],500)
        self.assertEqual(user['variable_debt_raw'],300)
        self.assertTrue(user['collateral_enabled'])

    def test_user_reserve_boolean_invalid(self):
        with self.assertRaises(RuntimeError):
            ra.decode_reserve_user(words(1,0,1,0,0,0,0,0,2))

    def test_price_base(self):
        self.assertEqual(ra.price_base(5*10**18,18,2000*10**8,10**8),Decimal('10000'))
        self.assertEqual(ra.price_base(9500*10**6,6,10**8,10**8),Decimal('9500'))

    def test_price_rejects_zero(self):
        with self.assertRaises(RuntimeError):
            ra.price_base(1,18,0,10**8)


class TestReadSnapshot(unittest.TestCase):
    def _mock_rpc(self, chain, method, params):
        if method == 'eth_blockNumber':
            return '0xabc'
        if method != 'eth_call':
            raise AssertionError('Unexpected RPC call '+method)
        call, block=params
        self.assertEqual(block,'0xabc')
        to=call['to'].lower()
        data=call['data'].lower()
        if to == ra.POOLS[chain].lower():
            if data.startswith(ra.SELECTOR):
                return words(10000*10**8, 10000*10**8, 0, 9000, 8000, int(Decimal('.9')*10**18))
            if data.startswith(ra.GET_USER_EMODE):
                return words(0)
            if data.startswith(ra.GET_USER_CONFIG):
                return words(6)
            if data.startswith(ra.GET_RESERVES_LIST):
                return words(32, 2, int(COLL,16),int(DEBT,16))
            if data.startswith(ra.GET_CONFIGURATION):
                return make_config(18,9000) if data.endswith(COLL[2:]) else make_config(6,0)
        if to == ra.ORACLES[chain].lower():
            if data == ra.BASE_CURRENCY_UNIT:
                return words(10**8)
            if data == ra.BASE_CURRENCY:
                return words(int(ra.USD_ADDRESS,16))
            if data.startswith(ra.GET_ASSET_PRICE):
                return words(2000*10**8 if data.endswith(COLL[2:]) else 10**8)
        if to == ra.DATA_PROVIDERS[chain].lower():
            if data.startswith(ra.GET_USER_RESERVE_DATA):
                if data[10:74].endswith(COLL[2:]):
                    return words(5*10**18,0,0,0,0,0,0,0,1)
                return words(0,0,9500*10**6,0,0,0,0,0,0)
        if to in (COLL.lower(),DEBT.lower()) and data==ra.SYMBOL:
            name=b'WETH' if to==COLL.lower() else b'USDC'
            return words(int.from_bytes(name.ljust(32,b'\0'),'big'))
        raise AssertionError(f'Unexpected call {to} {data}')

    def test_ethereum_consistent_block_and_balances(self):
        with patch.object(ra,'rpc_call',side_effect=self._mock_rpc):
            data=ra.read_reserve_snapshot('ethereum',BORROWER)
        self.assertEqual(data['block_number'],0xabc)
        self.assertEqual(data['quote_currency'],'USD')
        self.assertEqual(data['signal'],'below_one_candidate')
        self.assertFalse(data['execution_ready'])
        self.assertEqual(len(data['reserves']),2)
        self.assertEqual(data['reserves'][0]['symbol'],'WETH')
        self.assertEqual(data['reserves'][0]['collateral_value_base'],'10000.000000')
        self.assertEqual(data['reserves'][1]['debt_value_base'],'9500.000000')

    def test_arbitrum_provider_calls(self):
        with patch.object(ra,'rpc_call',side_effect=self._mock_rpc):
            data=ra.read_reserve_snapshot('arbitrum',BORROWER)
        self.assertEqual(data['chain'],'arbitrum')
        self.assertEqual(len(data['reserves']),2)

    def test_rejects_bad_chain(self):
        with self.assertRaises(ValueError):
            ra.read_reserve_snapshot('fake',BORROWER)


class TestEconomics(unittest.TestCase):
    def estimate(self, **kw):
        return ra.indicative_pairs(example_snapshot(),native_price_usd=Decimal('2000'),gas_price_wei=10**10,**kw)

    def test_positive_is_still_unverified(self):
        result=self.estimate()
        pair=result['indicative_pairs'][0]
        self.assertEqual(result['pairs_evaluated'],1)
        self.assertGreater(Decimal(pair['gross_bonus_usd']), Decimal('0'))
        self.assertGreater(Decimal(pair['indicative_net_usd']), Decimal('0'))
        self.assertFalse(pair['execution_ready'])
        self.assertIn('swap_route_not_quoted',pair['blocking_reasons'])
        self.assertIn('transaction_not_simulated',pair['blocking_reasons'])

    def test_missing_gas_price_does_not_claim_net(self):
        result=ra.indicative_pairs(example_snapshot(),native_price_usd=None,gas_price_wei=None)
        self.assertIsNone(result['indicative_pairs'][0]['indicative_net_usd'])
        self.assertIn('gas_usd_unavailable',result['indicative_pairs'][0]['blocking_reasons'])

    def test_emode_flags_special_rules(self):
        snapshot=example_snapshot(emode=1)
        result=ra.indicative_pairs(snapshot,native_price_usd=Decimal('2000'),gas_price_wei=10**10)
        self.assertIn('emode_pair_specific_rules_not_verified',result['indicative_pairs'][0]['blocking_reasons'])

    def test_l2_posting_fees_unverified(self):
        snapshot=example_snapshot(chain='base')
        result=ra.indicative_pairs(snapshot,native_price_usd=Decimal('2000'),gas_price_wei=10**10)
        self.assertIn('l2_posting_fee_not_modeled',result['indicative_pairs'][0]['blocking_reasons'])

    def test_healthy_position_blocked(self):
        snapshot=example_snapshot(); snapshot['health_factor']='1.15'
        result=ra.indicative_pairs(snapshot,native_price_usd=Decimal('2000'),gas_price_wei=10**10)
        self.assertIn('health_factor_not_below_one',result['indicative_pairs'][0]['blocking_reasons'])
        self.assertIsNone(result['indicative_pairs'][0]['indicative_net_usd'])

    def test_paused_collateral_removed(self):
        snapshot=example_snapshot();snapshot['reserves'][0]['paused']=True
        result=ra.indicative_pairs(snapshot,native_price_usd=Decimal('2000'),gas_price_wei=10**10)
        self.assertEqual(result['pairs_evaluated'],0)

    def test_invalid_unbounded_inputs(self):
        for kwargs in [{'gas_units':100}, {'gas_units':True}, {'slippage_bps':6000}, {'funding_fee_bps':-1}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                self.estimate(**kwargs)

    def test_price_not_usd_blocks(self):
        snapshot=example_snapshot();snapshot['quote_currency']='non_usd_oracle_base'
        result=ra.indicative_pairs(snapshot,native_price_usd=Decimal('2000'),gas_price_wei=10**10)
        self.assertIn('oracle_currency_not_verified_usd',result['indicative_pairs'][0]['blocking_reasons'])
        self.assertIsNone(result['indicative_pairs'][0]['indicative_net_usd'])

    def test_high_gas_defeats_paper_profit(self):
        result=ra.indicative_pairs(example_snapshot(),native_price_usd=Decimal('4000'),gas_price_wei=2*10**11)
        pair=result['indicative_pairs'][0]
        self.assertLess(Decimal(pair['indicative_net_usd']),Decimal('0'))
        self.assertIn('below_minimum_indicative_profit',pair['blocking_reasons'])


class TestServerPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.original_path=server.DB_PATH
        server.DB_PATH=Path(self.tmp.name)/'phase4.db'
        server.initialize()
        server.add_wallets('ethereum',[BORROWER])
        self.wallet_id=server.query_wallets()[0]['id']

    def tearDown(self):
        server.DB_PATH=self.original_path
        self.tmp.cleanup()

    def _fake_detail(self, chain, address, **kwargs):
        d=example_snapshot()
        return {**d,'health_factor':'0.9','block_number':321,'reserves':d['reserves'],
                'indicative_pairs':ra.indicative_pairs(d,native_price_usd=Decimal('2000'),gas_price_wei=10**10)['indicative_pairs'],
                'pairs_evaluated':1, 'execution_ready':False}

    def test_save_and_load_latest_snapshot(self):
        with patch.object(server,'analyze_live_position',side_effect=self._fake_detail):
            result=server.analyze_reserve_ids([self.wallet_id])
        self.assertEqual(result[0]['status'],'ok')
        saved=server.list_reserve_analyses()
        self.assertEqual(len(saved),1)
        self.assertFalse(saved[0]['execution_ready'])
        self.assertEqual(len(saved[0]['indicative_pairs']),1)
        self.assertEqual(saved[0]['block_number'],321)

    def test_error_does_not_persist_partial(self):
        with patch.object(server,'analyze_live_position',side_effect=RuntimeError('provider down')):
            result=server.analyze_reserve_ids([self.wallet_id])
        self.assertEqual(result[0]['status'],'error')
        self.assertEqual(server.list_reserve_analyses(),[])

    def test_rejects_many_wallets(self):
        with self.assertRaises(ValueError):
            server.analyze_reserve_ids([1,2,3])

    def test_rejects_bad_settings(self):
        with self.assertRaises(ValueError):
            server.analyze_reserve_ids([self.wallet_id], {'gas_units':'unbounded'})


if __name__ == '__main__':
    unittest.main()
