import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from core.proxybench.benchmark import ranking_key
from core.proxybench.direct_benchmark import DirectBenchmark, direct_failure
from core.proxybench.modes import mode_settings
from core.proxybench.multi_dashboard import MultiModeDashboard
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import TCP_RULES, current_rules, load_settings
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import pool


class ExclusiveDirectTests(unittest.TestCase):
    def test_tls_has_no_tcp_quality_gate_and_keeps_all_three_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            tls = AsyncMock(side_effect=[(180,"TLSv1.3","cipher"),TimeoutError(),(190,"TLSv1.3","cipher")])
            with patch("core.proxybench.direct_benchmark.tcp_probe", AsyncMock()) as tcp, \
                 patch("core.proxybench.direct_benchmark.tls_probe", tls):
                row = asyncio.run(DirectBenchmark({**TCP_RULES,"tls_enabled":1},Control(Path(directory)),domain="example.com").latency(pool(1)[0]))
            tcp.assert_not_awaited()
            self.assertEqual(tls.await_count,3)
            self.assertEqual(tls.await_args.args[1],"example.com")
            self.assertEqual(row["tcp_rounds_ms"],[])
            self.assertEqual(row["tls_rounds_ms"],[180,None,190])
            self.assertEqual(row["tls_average_latency_ms"],185)
            self.assertAlmostEqual(row["tls_loss_percent"],100/3)
            self.assertEqual(row["status"],"Rejected TLS")

    def test_only_selected_limit_applies_and_old_other_method_requires_retest(self):
        rules={**TCP_RULES,"tls_enabled":1,"max_tls_average_latency_ms":200}
        row={"latency_probe":"tls","tls_average_latency_ms":200,"tls_loss_percent":0,"tls_jitter_ms":0,"tcp_average_latency_ms":9999}
        self.assertEqual(direct_failure(row,rules,check_download=False),"")
        row["tls_average_latency_ms"]=200.01
        self.assertEqual(direct_failure(row,rules,check_download=False),"Rejected TLS")
        row["latency_probe"]="tcp"
        self.assertEqual(direct_failure(row,rules,check_download=False),"Retest Required")

    def test_tls_ranking_uses_its_own_measurements(self):
        slow={"measurement_mode":"tcp_tls","latency_probe":"tls","ip":"104.17.0.1","port":443,
              "tls_average_latency_ms":190,"tls_loss_percent":0,"tls_jitter_ms":2,"tcp_average_latency_ms":1}
        fast={**slow,"ip":"104.17.0.2","tls_average_latency_ms":90,"tcp_average_latency_ms":9999}
        self.assertLess(ranking_key(fast),ranking_key(slow))

    def test_selector_is_saved_but_cannot_change_running_direct_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"config.yaml").write_text("proxybench: {}",encoding="utf-8")
            router=MultiModeDashboard(SimpleNamespace(root=root,repository="jachjkl/Noode-CG-ProxyBench"))
            router.action("choose-mode",{"mode":"tcp_tls","probe":"tls"})
            self.assertEqual(current_rules(router.controllers["tcp_tls"].settings)["tls_enabled"],1)
            restored=MultiModeDashboard(SimpleNamespace(root=root,repository="jachjkl/Noode-CG-ProxyBench"))
            self.assertEqual(restored.mode,"tcp_tls")
            self.assertEqual(restored.snapshot()["rules"]["tls_enabled"],1)
            restored.controllers["tcp_tls"].process=Mock()
            restored.controllers["tcp_tls"].process.poll.return_value=None
            with self.assertRaisesRegex(ValueError,"停止"):
                restored.action("choose-mode",{"mode":"tcp_tls","probe":"tcp"})
            self.assertEqual(current_rules(restored.controllers["tcp_tls"].settings)["tls_enabled"],1)

    def test_first_hundred_finish_download_before_next_batch_start_latency(self):
        async def speed(nodes,options,**kwargs):
            self.assertEqual(tcp.await_count,300 if len(completed)<100 else 600)
            nodes[0].speed_mbps=12
            nodes[0].probe_results["speed"]={"completion_ratio":1}
            return nodes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"config.yaml").write_text("proxybench: {}",encoding="utf-8")
            settings=mode_settings(load_settings(root/"config.yaml"),"tcp_tls")
            settings["rules"].update(quick_finish=0)
            pipeline=Pipeline(settings)
            pipeline.store.state={"run_id":"batch-fixture","phase":"scan","pool":pool(200),"results":{}}
            completed=[]
            tcp=AsyncMock(return_value=90)
            pipeline.events.append=lambda *_,**__:None
            pipeline.store.save_partial=lambda row:completed.append(row)
            with patch("core.proxybench.direct_benchmark.tcp_probe",tcp), \
                 patch("core.proxybench.direct_benchmark.tls_probe",AsyncMock()) as tls, \
                 patch("core.proxybench.direct_benchmark.test_speed",side_effect=speed), \
                 patch("core.proxybench.direct_benchmark._request",AsyncMock(return_value=(200,{},b"colo=FRA\n",1))):
                pipeline.scan(pipeline.ordered_candidates(pool(200)),"results",{})
            tls.assert_not_awaited()
            self.assertEqual(tcp.await_count,600)
            self.assertEqual(len(completed),200)
            self.assertTrue(all(r["qualified"] for r in completed))
