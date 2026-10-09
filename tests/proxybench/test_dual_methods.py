from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from core.proxybench.benchmark import Benchmark, calculate
from core.proxybench.cloud_nodes import read_published
from core.proxybench.direct_benchmark import DirectBenchmark, direct_failure, summarize
from core.proxybench.events import EventLog
from core.proxybench.export import gate, publish
from core.proxybench.modes import mode_settings, publication_limits
from core.proxybench.multi_dashboard import MultiModeDashboard
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import RULES, TCP_RULES, current_rules, load_settings, validate_rules
from core.proxybench.state import Control
from scripts.proxybench_channel import pack, unpack
from tests.proxybench.test_benchmark import FakeManager, pool


def records(normal, japan, mode="proxy"):
    result=[]
    for i in range(normal+japan):
        row={"ip":f"104.16.{i//254}.{i%254+1}","port":443,"lane":"general" if i<normal else "jp_append",
             "qualified":True,"measurement_mode":mode,"geo_country":"DE" if i<normal else "JP","geo_verified":True,"geo_conflict":False}
        if mode=="tcp_tls":
            row.update(tcp_average_latency_ms=100,tcp_loss_percent=0,tcp_jitter_ms=2,download_mbps=10)
        else:
            row.update(proxy_average_latency_ms=100,proxy_loss_percent=0,latency_jitter_ms=2,proxy_download_average_mbps=10)
        result.append(row)
    return result


class DualMethodTests(unittest.TestCase):
    def test_counts_100_200_300_and_japanese_zero_or_custom_are_used_by_the_gate(self):
        for normal,japan in [(100,10),(200,7),(300,0),(300,35)]:
            with self.subTest(normal=normal,japan=japan):
                limits=publication_limits({"publish_count":normal,"jp_publish_count":japan})
                rows=records(normal,japan)
                self.assertTrue(gate(rows,limits=limits))
                self.assertFalse(gate(rows[:-1],limits=limits))
                self.assertTrue(gate(rows[:-1],limits=limits,allow_partial=True))
        with self.assertRaises(ValueError):
            validate_rules({"publish_count":1001})
        with self.assertRaises(ValueError):
            validate_rules({"jp_publish_count":True})

    def test_mode_paths_and_saved_rules_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"config.yaml").write_text("proxybench: {}",encoding="utf-8")
            proxy=load_settings(root/"config.yaml")
            direct=mode_settings(proxy,"tcp_tls")
            proxy["rules_path"].parent.mkdir(parents=True)
            proxy["rules_path"].write_text(json.dumps({"publish_count":200,"jp_publish_count":3}),encoding="utf-8")
            direct["rules_path"].write_text(json.dumps({"publish_count":300,"jp_publish_count":20}),encoding="utf-8")
            self.assertEqual(publication_limits(current_rules(proxy)),{"general":200,"japan":3})
            self.assertEqual(publication_limits(current_rules(direct)),{"general":300,"japan":20})
            self.assertNotEqual(proxy["state_dir"],direct["state_dir"])
            self.assertEqual(direct["output_dir"],root.resolve()/"output/Nodes-TCP")

    def test_direct_tcp_measures_a_real_local_listener_three_times_without_proxy(self):
        async def scenario(root):
            async def accept(reader,writer):
                writer.close()
                await writer.wait_closed()
            server=await asyncio.start_server(accept,"127.0.0.1",0)
            try:
                port=server.sockets[0].getsockname()[1]
                record=await DirectBenchmark(TCP_RULES,Control(root)).tcp({"ip":"127.0.0.1","port":port})
                self.assertEqual(len(record["tcp_rounds_ms"]),3)
                self.assertEqual(record["tcp_success_count"],3)
                self.assertEqual(record["tcp_loss_percent"],0)
                self.assertTrue(all(v is not None and v>=0 for v in record["tcp_rounds_ms"]))
                self.assertEqual(record["entry_method"],"three-consecutive-direct-tcp-connects")
            finally:
                server.close()
                await server.wait_closed()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_three_attempts_continue_after_failure_and_loss_is_not_trimmed(self):
        with tempfile.TemporaryDirectory() as directory:
            fake=AsyncMock(side_effect=[100,TimeoutError(),120])
            with patch("core.proxybench.direct_benchmark.tcp_probe",fake):
                row=asyncio.run(DirectBenchmark(TCP_RULES,Control(Path(directory))).tcp(pool(1)[0]))
            self.assertEqual(fake.await_count,3)
            self.assertEqual(row["tcp_rounds_ms"],[100,None,120])
            self.assertEqual(row["tcp_average_latency_ms"],110)
            self.assertAlmostEqual(row["tcp_loss_percent"],100/3)
            self.assertEqual(row["status"],"Rejected TCP")

    def test_three_probe_arithmetic_and_jitter_keep_all_successful_values(self):
        mean,jitter,loss=summarize([100,200,300])
        self.assertEqual(mean,200)
        self.assertAlmostEqual(jitter,81.6496580928)
        self.assertEqual(loss,0)
        row={"tcp_average_latency_ms":200,"tcp_jitter_ms":jitter,"tcp_loss_percent":0}
        self.assertEqual(direct_failure(row,{**TCP_RULES,"max_jitter_ms":80},check_tls=False,check_download=False),"Rejected TCP")

    def test_direct_tls_three_calls_and_download_use_the_original_probe_and_ignore_client_loc(self):
        async def speed(nodes,options,**kwargs):
            node=nodes[0]
            node.speed_mbps=12
            node.probe_results["speed"]={"received_bytes":options["bytes_per_test"],"wanted_bytes":options["bytes_per_test"],"completion_ratio":1,"download_seconds":.35}
            return nodes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            tls=AsyncMock(side_effect=[(150,"TLSv1.3","cipher"),(180,"TLSv1.3","cipher"),(210,"TLSv1.3","cipher")])
            with patch("core.proxybench.direct_benchmark.tcp_probe",AsyncMock(side_effect=[80,90,100])), \
                 patch("core.proxybench.direct_benchmark.tls_probe",tls), \
                 patch("core.proxybench.direct_benchmark.test_speed",side_effect=speed), \
                 patch("core.proxybench.direct_benchmark._request",AsyncMock(return_value=(200,{"cf-ray":"test-NRT"},b"colo=NRT\nloc=CN\n",10))):
                row=DirectBenchmark({**TCP_RULES, "tls_enabled": 1},Control(root)).batch(pool(1),lambda _:None,reuse_tcp=False)[0]
            self.assertTrue(row["qualified"])
            self.assertEqual(tls.await_count,3)
            self.assertEqual(row["tls_average_latency_ms"],180)
            self.assertEqual(row["geo_country"],"JP")
            self.assertTrue(row["jp_qualified"])
            self.assertEqual(row["download_measurement"]["routing_proof"],"direct-pinned-candidate")
            self.assertNotIn("proxy_average_latency_ms",row)

    def test_tls_disabled_skips_independent_handshakes_but_keeps_download_quality_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            async def failed_speed(nodes,*args,**kwargs):
                nodes[0].speed_mbps=None
                nodes[0].probe_results["speed"]={"received_bytes":123}
                return nodes
            with patch("core.proxybench.direct_benchmark.tcp_probe",AsyncMock(return_value=90)), \
                 patch("core.proxybench.direct_benchmark.tls_probe",AsyncMock()) as tls, \
                 patch("core.proxybench.direct_benchmark.test_speed",side_effect=failed_speed):
                row=DirectBenchmark({**TCP_RULES,"tls_enabled":0},Control(Path(directory))).batch(pool(1),lambda _:None,reuse_tcp=False)[0]
            tls.assert_not_awaited()
            self.assertFalse(row["qualified"])
            self.assertEqual(row["status"],"Rejected Speed")

    def test_tls_average_or_jitter_exceeding_saved_limits_cannot_pass(self):
        row={"tcp_average_latency_ms":100,"tcp_loss_percent":0,"tcp_jitter_ms":1,"tls_rounds_ms":[290,310,330],
             "tls_average_latency_ms":310,"tls_loss_percent":0,"tls_jitter_ms":16}
        self.assertEqual(direct_failure(row,{**TCP_RULES, "tls_enabled": 1},check_download=False),"Rejected TLS")
        row.update(tls_average_latency_ms=200,tls_jitter_ms=201)
        self.assertEqual(direct_failure(row,{**TCP_RULES, "tls_enabled": 1},check_download=False),"Rejected TLS")

    def test_count_and_raw_attempt_rule_validation(self):
        for key in ["tcp_attempts","tls_attempts"]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_rules({key:2},"tcp_tls")
        self.assertEqual(validate_rules({"jp_publish_count":0},"tcp_tls")["jp_publish_count"],0)

    def test_tcp_publication_upload_keeps_the_proxy_namespace_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            local,cloud=root/"local",root/"cloud"
            health={"measurement_mode":"tcp_tls","publication_limits":{"general":200,"japan":7}}
            publish(local/"output/Nodes-TCP",records(200,7,"tcp_tls"),health)
            (cloud/"output").mkdir(parents=True)
            (cloud/"output/nodes.txt").write_text("keep proxy data",encoding="utf-8")
            content=pack(local,"result","tcp_tls")
            unpack(content,hashlib.sha256(content).hexdigest(),cloud,"result")
            self.assertEqual((cloud/"output/nodes.txt").read_text(),"keep proxy data")
            self.assertEqual(len((cloud/"output/Nodes-TCP/nodes.txt").read_text().splitlines()),207)

    def test_mixed_namespace_zip_is_rejected_before_any_cloud_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            publish(root/"output/Nodes-TCP",records(3,0,"tcp_tls"),{"measurement_mode":"tcp_tls","publication_limits":{"general":3,"japan":0}})
            good=pack(root,"result","tcp_tls")
            stream=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(good)) as source,zipfile.ZipFile(stream,"w") as dest:
                for name in source.namelist():
                    dest.writestr(name,source.read(name))
                dest.writestr("output/nodes.txt","wrong mode")
            blob=stream.getvalue()
            with self.assertRaises(ValueError):
                unpack(blob,hashlib.sha256(blob).hexdigest(),root/"cloud","result")
            self.assertFalse((root/"cloud").exists())

    def test_dynamic_cloud_counts_and_original_ranks_are_read_for_tcp_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            publish(root/"output/Nodes-TCP",records(200,7,"tcp_tls"),{"measurement_mode":"tcp_tls","publication_limits":{"general":200,"japan":7}})
            data=(root/"output/Nodes-TCP/nodes.json").read_bytes()
            health=(root/"output/Nodes-TCP/health.json").read_bytes()
            client=Mock(settings={"state_dir":root,"measurement_mode":"tcp_tls"})
            client.command.side_effect=["a"*40,{"content":base64.b64encode(data).decode()},{"content":base64.b64encode(health).decode()}]
            with patch("core.proxybench.cloud_nodes.download",side_effect=lambda dest,*args,**kwargs:dest.write_bytes(data)):
                result=read_published(client)
            self.assertEqual((result["total"],result["general"],result["japan"]),(207,200,7))
            self.assertEqual([r["rank"] for r in result["nodes"]],list(range(1,208)))

    def test_default_cloudflare_probe_uses_trace_even_without_validation_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            settings={"state_dir":root,"runtime_dir":root/"runtime","rules_path":root/"rules.json","rules":RULES}
            pipeline=Pipeline(settings,manager=FakeManager())
            self.assertEqual(pipeline.cloudflare_url,"https://www.cloudflare.com/cdn-cgi/trace")
            manager=FakeManager()
            urls=[]
            def delay(_name,url,*_args):
                urls.append(url)
                return {"success":"cp.cloudflare.com" not in url,"latency_ms":100 if "cp.cloudflare.com" not in url else None}
            manager.controller.delay=delay
            row=Benchmark(manager,{**RULES,"round_cooldown_seconds":0},Control(root),geo_urls=[]).batch(pool(1),object())[0]
            self.assertTrue(row["qualified"])
            self.assertNotIn("https://cp.cloudflare.com/",urls)

    def test_direct_pipeline_needs_no_profile_and_retests_all_three_tcp_samples_for_custom_quota(self):
        async def speed(nodes, options, **kwargs):
            nodes[0].speed_mbps = 12
            nodes[0].probe_results["speed"] = {"received_bytes": options["bytes_per_test"], "completion_ratio": 1}
            return nodes
        async def trace(node, **kwargs):
            colo = "NRT" if int(node.ip.split(".")[-1]) <= 7 else "FRA"
            return 200, {}, f"colo={colo}\nloc=CN\n".encode(), 10
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
            settings = mode_settings(load_settings(root / "config.yaml"), "tcp_tls")
            settings.update(max_cycles=1, auto_update=False, fast_entry_screen=False)
            settings["rules"].update(publish_count=200, jp_publish_count=7, tls_enabled=1)
            candidates = pool(210)
            builder = Mock(return_value=(candidates, {"seed": "fixture", "session_id": "fixture"}))
            tcp = AsyncMock(return_value=90)
            with patch("core.proxybench.pipeline.ProxyProfile.load", side_effect=AssertionError("direct mode must not load authentication")), \
                 patch("core.proxybench.direct_benchmark.tcp_probe", tcp), \
                 patch("core.proxybench.direct_benchmark.tls_probe", AsyncMock(return_value=(180, "TLSv1.3", "cipher"))), \
                 patch("core.proxybench.direct_benchmark.test_speed", side_effect=speed), \
                 patch("core.proxybench.direct_benchmark._request", side_effect=trace):
                pipeline = Pipeline(settings, pool_builder=builder)
                result = pipeline.run()
            self.assertTrue(result["published"])
            self.assertEqual((result["general_final_count"], result["jp_final_count"]), (200, 7))
            self.assertEqual(tcp.await_count, 3 * (210 + 207))
            builder.assert_called_once()
            rows = json.loads((root / "output/Nodes-TCP/nodes.json").read_text(encoding="utf-8"))
            self.assertTrue(all(len(r["tcp_rounds_ms"]) == len(r["tls_rounds_ms"]) == 3 for r in rows))
            self.assertEqual([r["rank"] for r in rows], list(range(1, 208)))
            self.assertFalse((root / "output/nodes.txt").exists())

    def test_new_proxy_jitter_rule_rejects_even_a_low_trimmed_average(self):
        samples=[10,100,100,100,2000]
        row={"probes":{site:[{"success":True,"latency_ms":v} for v in samples] for site in ["google","cloudflare","github"]}}
        calculate(row,{**RULES,"max_proxy_jitter_ms":50})
        self.assertEqual(row["proxy_average_latency_ms"],100)
        self.assertFalse(row["latency_passed"])

    def test_mode_router_saves_two_presets_and_blocks_duplicate_cross_mode_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"config.yaml").write_text("proxybench: {}",encoding="utf-8")
            legacy=SimpleNamespace(root=root,repository="jachjkl/Noode-CG-ProxyBench")
            router=MultiModeDashboard(legacy)
            router.action("rules",{"measurement_mode":"proxy","publish_count":200,"jp_publish_count":5})
            router.action("rules",{"measurement_mode":"tcp_tls","publish_count":300,"jp_publish_count":20})
            self.assertEqual(router.snapshot("proxy")["rules"]["publish_count"],200)
            self.assertEqual(router.snapshot("tcp_tls")["rules"]["publish_count"],300)
            proxy=router.controllers["proxy"]
            proxy.process=Mock()
            proxy.process.poll.return_value=None
            with self.assertRaisesRegex(ValueError,"正在运行"):
                router.action("start",{"measurement_mode":"tcp_tls"})
            router.action("choose-mode",{"mode":"tcp_tls"})
            router.action("stop",{})
            self.assertEqual(json.loads((proxy.settings["state_dir"]/"control.json").read_text())["action"],"stop")
            self.assertFalse((router.controllers["tcp_tls"].settings["state_dir"]/"control.json").exists())

    def test_logs_survive_close_and_are_readable_chinese_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            log=EventLog(root,"tcp_tls")
            log.append("TCP 三次实测完成，等待 TLS 验证")
            log.append("连接超时，已保存断点",level="error")
            restored=EventLog(root,"tcp_tls")
            self.assertEqual(len(restored.tail()),2)
            self.assertIn("三次",restored.tail()[0]["message"])
            self.assertEqual(restored.tail()[-1]["level"],"error")
