"""Phase 3 mock-driven tests; no internet or paid API required."""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import aave_discovery
import server
from aave import POOLS

ADDR='0x'+'12'*20
RESERVE='0x'+'56'*20
TX='0x'+'a4'*32


def borrow_log(chain='ethereum', block=100, log_index=0, address=ADDR):
    topics=[aave_discovery.BORROW_TOPIC,
            '0x'+'0'*24+RESERVE[2:],
            '0x'+'0'*24+address[2:],
            '0x'+'0'*64]
    return {'address':POOLS[chain],'topics':topics,'blockNumber':hex(block),
            'logIndex':hex(log_index),'transactionHash':TX,'removed':False,'data':'0x'}


class DecodeTests(unittest.TestCase):
    def test_decodes_on_behalf_of_from_topic2(self):
        event=aave_discovery.decode_borrow_log('ethereum',borrow_log())
        self.assertEqual(event['address'],ADDR)
        self.assertEqual(event['reserve'],RESERVE)
        self.assertFalse(event['current_debt_verified'])

    def test_rejects_wrong_contract_or_abi_topic(self):
        wrong=borrow_log();wrong['address']='0x'+'a2'*20
        with self.assertRaises(ValueError):aave_discovery.decode_borrow_log('ethereum',wrong)
        wrong=borrow_log();wrong['topics'][2]='0x'+'1'*64
        with self.assertRaises(ValueError):aave_discovery.decode_borrow_log('ethereum',wrong)
        wrong=borrow_log();wrong['removed']=True
        with self.assertRaises(ValueError):aave_discovery.decode_borrow_log('ethereum',wrong)

    def test_get_logs_uses_pool_and_topic(self):
        log=borrow_log('base',125)
        with patch.object(aave_discovery,'rpc_call',return_value=[log]) as rpc:
            result=aave_discovery.scan_borrow_events('base',125,126)
        self.assertEqual(result[0]['address'],ADDR)
        self.assertEqual(rpc.call_args.args[1],'eth_getLogs')
        args=rpc.call_args.args[2][0]
        self.assertEqual(args['topics'],[aave_discovery.BORROW_TOPIC])
        self.assertEqual(args['address'],POOLS['base'])

    def test_reject_unbounded_or_wrong_provider_data(self):
        with self.assertRaises(ValueError):aave_discovery.scan_borrow_events('base',0,2000)
        with patch.object(aave_discovery,'rpc_call',return_value={'error':'not-logs'}):
            with self.assertRaises(RuntimeError):aave_discovery.scan_borrow_events('base',0,1)
        with patch.object(aave_discovery,'rpc_call',return_value=[borrow_log(block=5)]):
            with self.assertRaises(RuntimeError):aave_discovery.scan_borrow_events('ethereum',0,1)

    def test_confirmations(self):
        with patch.object(aave_discovery,'rpc_call',return_value=hex(900)):
            self.assertEqual(aave_discovery.current_safe_head('ethereum',20),880)
        with self.assertRaises(ValueError):aave_discovery.current_safe_head('ethereum',0)


class BorrowerJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=server.DB_PATH
        server.DB_PATH=pathlib.Path(self.tmp.name)/'borrowers.db'
        server.initialize()

    def tearDown(self):
        server.DB_PATH=self.old
        self.tmp.cleanup()

    def test_job_starts_at_confirmed_head(self):
        with patch.object(server,'current_safe_head',return_value=1000):
            j=server.create_aave_borrower_job('ethereum',lookback_blocks=100,blocks_per_run=25)
        self.assertEqual(j['start_block'],901)
        self.assertEqual(j['end_block'],1000)
        self.assertEqual(server.list_aave_borrower_jobs()[0]['next_block'],901)

    def test_job_persists_and_deduplicates_protocol_evidence(self):
        with patch.object(server,'current_safe_head',return_value=100):
            j=server.create_aave_borrower_job('ethereum',2,1)
        sample=aave_discovery.decode_borrow_log('ethereum',borrow_log(block=99))
        with patch.object(server,'scan_borrow_events',side_effect=[[sample],[]]) as scanner:
            result=server.run_aave_borrower_job(j['job_id'])
            self.assertEqual(result['unique_borrowers_in_batch'],1)
            self.assertFalse(result['position_verified'])
            self.assertEqual(result['events_indexed'],1)
            result=server.run_aave_borrower_job(j['job_id'])
        self.assertTrue(result['complete'])
        self.assertEqual(scanner.call_count,2)
        self.assertEqual(server.list_aave_borrower_jobs()[0]['next_block'],101)
        self.assertEqual(server.query_borrower_events()['total_events'],1)
        self.assertEqual(server.query_wallets()[0]['source'],'aave_borrow_event')
        self.assertFalse(server.query_borrower_events()['execution_ready'])

    def test_provider_failure_retains_cursor_and_evidence(self):
        with patch.object(server,'current_safe_head',return_value=51):
            job=server.create_aave_borrower_job('base',3,1)
        event=aave_discovery.decode_borrow_log('base',borrow_log(chain='base',block=49))
        with patch.object(server,'scan_borrow_events',side_effect=[[event],RuntimeError('quota')]):
            server.run_aave_borrower_job(job['job_id'])
            with self.assertRaises(RuntimeError):server.run_aave_borrower_job(job['job_id'])
        self.assertEqual(server.list_aave_borrower_jobs()[0]['next_block'],50)
        self.assertEqual(server.query_borrower_events()['total_events'],1)

    def test_job_pause_resume_and_bounds(self):
        with self.assertRaises(ValueError):server.create_aave_borrower_job('base',lookback_blocks=250001)
        with patch.object(server,'current_safe_head',return_value=150):
            j=server.create_aave_borrower_job('base',5,2)
        self.assertEqual(server.change_aave_borrower_job(j['job_id'],'pause')['status'],'paused')
        with self.assertRaises(ValueError):server.run_aave_borrower_job(j['job_id'])
        self.assertEqual(server.change_aave_borrower_job(j['job_id'],'resume')['status'],'active')
        with self.assertRaises(ValueError):server.change_aave_borrower_job(j['job_id'],'resume')

    def test_old_wallet_row_does_not_change_origin(self):
        server.add_wallets('ethereum',[ADDR])
        with patch.object(server,'current_safe_head',return_value=99):
            job=server.create_aave_borrower_job('ethereum',1,1)
        event=aave_discovery.decode_borrow_log('ethereum',borrow_log(block=99))
        with patch.object(server,'scan_borrow_events',return_value=[event]):
            server.run_aave_borrower_job(job['job_id'])
        self.assertEqual(server.query_wallets()[0]['source'],'manual')
        self.assertEqual(server.query_borrower_events()['total_events'],1)

if __name__=='__main__':unittest.main()

class ScenarioGateTests(unittest.TestCase):
    def test_50_percent_close_factor_on_marginal_liquidation(self):
        import engine
        # health = 8000*.8/6500 = 0.9846, close factor normally 50%.
        result=engine.liquidation_simulator(dict(collateral_usd=8000,debt_usd=6500,
            liquidation_threshold_pct=80,repay_usd=5000,bonus_pct=5))
        self.assertTrue(result['hf_below_one'])
        self.assertEqual(result['close_factor_pct'],'50.00')
        self.assertEqual(result['maximum_repay_by_close_factor_usd'],'3250.00')
        self.assertFalse(result['repayment_within_close_factor'])
        self.assertFalse(result['scenario_profitable'])

    def test_dust_rule_disallows_cheap_partial_remainder(self):
        import engine
        result=engine.liquidation_simulator(dict(collateral_usd=4000,debt_usd=3800,
            liquidation_threshold_pct=80,repay_usd=3000,bonus_pct=5))
        self.assertFalse(result['partial_dust_rule_met'])
        self.assertFalse(result['scenario_profitable'])

    def test_mev_and_flashloan_fees_count_in_cost(self):
        import engine
        result=engine.liquidation_simulator(dict(collateral_usd=8000,debt_usd=7000,
            liquidation_threshold_pct=80,repay_usd=2000,bonus_pct=5,
            flash_loan_fee_pct=0.1,mev_risk_usd=50,minimum_net_profit_usd=75))
        self.assertEqual(result['gross_profit_usd'],'100.00')
        self.assertEqual(result['estimated_costs_usd'],'52.00')
        self.assertFalse(result['scenario_profitable'])
