import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.proxybench.direct_benchmark import DirectBenchmark
from core.proxybench.settings import TCP_RULES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import pool


class MeasurementObserverTests(unittest.TestCase):
    def test_blocked_ui_writer_does_not_block_concurrent_tcp_measurements(self):
        ui_started=threading.Event()
        release_ui=threading.Event()
        probes_done=threading.Event()
        count=0
        errors=[]
        completed=[]
        async def probe(*_):
            nonlocal count
            await asyncio.sleep(0)
            count+=1
            if count==60:
                probes_done.set()
            return 90
        async def speed(nodes,*_,**__):
            nodes[0].speed_mbps=None
            return nodes
        def ui(**_):
            ui_started.set()
            release_ui.wait(3)
        with tempfile.TemporaryDirectory() as directory:
            def run():
                try:
                    DirectBenchmark(TCP_RULES,Control(Path(directory)),ui).batch(pool(20),completed.append)
                except BaseException as exc:
                    errors.append(exc)
            with patch('core.proxybench.direct_benchmark.tcp_probe',side_effect=probe),patch('core.proxybench.direct_benchmark.test_speed',side_effect=speed):
                task=threading.Thread(target=run)
                task.start()
                try:
                    self.assertTrue(ui_started.wait(2))
                    self.assertTrue(probes_done.wait(.7),'UI I/O stalled the TCP measurement loop')
                finally:
                    release_ui.set()
                    task.join(5)
            self.assertFalse(task.is_alive())
            self.assertEqual(errors,[])
            self.assertEqual(len(completed),20)
            self.assertTrue(all(r['tcp_rounds_ms']==[90,90,90] for r in completed))
