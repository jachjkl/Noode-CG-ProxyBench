import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.io_utils import atomic_write_json
from core.proxybench.dashboard import BenchDashboard
from core.proxybench.pipeline import Pipeline
from core.proxybench.session_lifecycle import read_saved, upgrade_direct_parallelism
from core.proxybench.state import Store, partial_results
from tests.proxybench.test_dual_methods import records


class SessionRestartTests(unittest.TestCase):
    def create(self, root):
        (root/'config.yaml').write_text('proxybench: {}',encoding='utf-8')
        return BenchDashboard(SimpleNamespace(root=root,repository='jachjkl/Noode-CG-ProxyBench'),mode='tcp_tls')

    def seed(self, dashboard, status='Running'):
        store=Store(dashboard.settings['state_dir'])
        rows=records(2,0,'tcp_tls')
        for row in rows:
            row.update(key=f"{row['ip']}:{row['port']}",download_measurement={'success':True},tcp_rounds_ms=[100,100,100],tested_at='2026-10-09T00:00:00Z')
        store.state={'run_id':'fixture','phase':'scan','pool':rows,'results':{r['key']:r for r in rows}}
        store.commit()
        atomic_write_json(store.root/'live.json',{'status':status,'phase':'scan','run_id':'fixture'})
        return store

    def launch(self, dashboard):
        fake=Mock()
        fake.poll.return_value=None
        try:
            with patch('core.proxybench.dashboard.subprocess.Popen',return_value=fake) as create:
                dashboard.action('start',{})
                return create.call_args.args[0]
        finally:
            fake.poll.return_value=0
            if dashboard.log_handle:
                dashboard.log_handle.close()
                dashboard.log_handle=None

    def test_stop_save_then_normal_close_retains_measured_ips_and_reopens_without_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dashboard=self.create(root)
            store=self.seed(dashboard)
            dashboard.action('stop',{})
            dashboard.request_close()
            self.assertTrue(dashboard.finish_close(True))
            self.assertFalse((store.root/'batch-state.json').exists())
            self.assertEqual(len(read_saved(dashboard.settings)),2)
            reopened=self.create(root)
            self.assertFalse(reopened.recovery_pending)
            self.assertEqual(len(reopened.rows('results',1)['rows']),2)
            self.assertNotIn('--mode',self.launch(reopened))

    def test_error_exit_retains_checkpoint_and_start_automatically_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dashboard=self.create(root)
            store=self.seed(dashboard,'Failed')
            dashboard.request_close()
            self.assertFalse(dashboard.finish_close(True))
            self.assertTrue((store.root/'batch-state.json').exists())
            reopened=self.create(root)
            self.assertTrue(reopened.recovery_pending)
            command=self.launch(reopened)
            self.assertEqual(command[command.index('--mode')+1],'resume')

    def test_legacy_stopped_cache_is_cleaned_but_legacy_running_cache_is_resumed(self):
        for status,wanted in [('Stopped',False),('Running',True)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                first=self.create(root)
                store=self.seed(first,status)
                first.lifecycle_path.unlink()
                reopened=self.create(root)
                self.assertEqual(reopened.recovery_pending,wanted)
                self.assertEqual((store.root/'batch-state.json').exists(),wanted)

    def test_partial_journal_recovers_completed_rows_and_repairs_a_truncated_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            store=Store(root)
            store.state={'run_id':'fixture','phase':'scan'}
            store.commit()
            store.save_partial({'key':'one','qualified':True})
            with (root/'partial-batch.jsonl').open('ab') as stream:
                stream.write(b'{"unfinished":')
            reopened=Store(root)
            reopened.load()
            self.assertEqual(list(reopened.partial),['one'])
            reopened.save_partial({'key':'two','qualified':False})
            self.assertEqual(set(partial_results(root,'fixture','scan')),{'one','two'})
            self.assertEqual(partial_results(root,'fixture','general_retest'),{})
            reopened.state['results']=reopened.partial.copy()
            reopened.commit()
            self.assertFalse((root/'partial-batch.jsonl').exists())
            self.assertEqual(set(Store(root).load()['results']),{'one','two'})
            self.assertEqual(json.loads(gzip.decompress((root/'attempted.json.gz').read_bytes())),json.loads(gzip.decompress((root/'benchmark-results.json.gz').read_bytes())))

    def test_legacy_parallelism_upgrade_never_changes_quality_limits_and_runs_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dashboard=self.create(root)
            settings=dashboard.settings
            marker=root/'data/tcpbench-parallelism-v2.json'
            marker.unlink()
            old={**settings['rules'],'speed_concurrency':4,'tls_concurrency':32,'tcp_timeout_seconds':1.2,
                 'max_tcp_average_latency_ms':157,'max_tls_average_latency_ms':166,'publish_count':256,'jp_publish_count':4}
            atomic_write_json(settings['rules_path'],old)
            self.assertTrue(upgrade_direct_parallelism(settings))
            new=json.loads(settings['rules_path'].read_text())
            for key in old:
                if key not in {'speed_concurrency','tls_concurrency','tcp_timeout_seconds'}:
                    self.assertEqual(new[key],old[key])
            self.assertEqual((new['speed_concurrency'],new['tls_concurrency'],new['tcp_timeout_seconds']),(20,100,1))
            atomic_write_json(settings['rules_path'],old)
            self.assertFalse(upgrade_direct_parallelism(settings))
            self.assertEqual(json.loads(settings['rules_path'].read_text()),old)

    def test_nondefault_custom_parallelism_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dashboard=self.create(root)
            (root/'data/tcpbench-parallelism-v2.json').unlink()
            custom={**dashboard.settings['rules'],'speed_concurrency':2,'tls_concurrency':32,'tcp_timeout_seconds':1.2}
            atomic_write_json(dashboard.settings['rules_path'],custom)
            self.assertFalse(upgrade_direct_parallelism(dashboard.settings))
            self.assertEqual(json.loads(dashboard.settings['rules_path'].read_text()),custom)

    def test_saved_results_can_be_freshly_retested_and_manually_published_after_normal_close(self):
        async def speed(nodes,*_,**__):
            nodes[0].speed_mbps=12
            nodes[0].probe_results['speed']={'completion_ratio':1}
            return nodes
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dashboard=self.create(root)
            self.seed(dashboard)
            dashboard.action('stop',{})
            dashboard.request_close()
            self.assertTrue(dashboard.finish_close(True))
            with patch('core.proxybench.mihomo_manager.MihomoManager.ensure'), \
                 patch('core.proxybench.direct_benchmark.tcp_probe',return_value=90), \
                 patch('core.proxybench.direct_benchmark.test_speed',side_effect=speed), \
                 patch('core.proxybench.direct_benchmark._request',return_value=(200,{},b'colo=FRA\n',10)):
                report=Pipeline(dashboard.settings,pool_builder=Mock(side_effect=AssertionError('manual publish must not fetch new IPs'))).run(publish_only=True)
            self.assertTrue(report['published'])
            self.assertEqual(report['unique_final_count'],2)
