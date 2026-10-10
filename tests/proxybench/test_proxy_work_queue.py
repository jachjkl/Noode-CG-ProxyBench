from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.proxybench.benchmark import Benchmark
from core.proxybench.settings import RULES, SITES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import FakeManager, pool


class ProxyWorkQueueTests(unittest.TestCase):
    def bench(self, manager, candidates, rules, geo_urls=None):
        with tempfile.TemporaryDirectory() as directory:
            completed = []
            rows = Benchmark(manager, {**RULES, **rules}, Control(Path(directory)),
                             geo_urls=geo_urls or []).batch(candidates, object(), completed.append)
        self.assertEqual(len(completed), len(candidates))
        self.assertEqual(len({row['key'] for row in completed}), len(candidates))
        return rows

    def test_global_request_limit_and_timeouts_cover_every_site_of_all_failed_ips(self):
        manager = FakeManager()
        lock = threading.Lock()
        active = peak = 0
        calls = []
        def probe(name, url, expected, timeout):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
                calls.append((name, url, timeout))
            time.sleep(.002)
            with lock:
                active -= 1
            return {'success': False, 'latency_ms': None, 'destination': url}
        manager.controller.site_probe = probe
        rows = self.bench(manager, pool(100), {'delay_concurrency': 7, 'request_timeout_seconds': .2})
        self.assertLessEqual(peak, 7)
        self.assertEqual(len(calls), 300)
        self.assertTrue(all(call[2] == .2 for call in calls))
        self.assertEqual(len(set((name, url) for name, url, _ in calls)), 300)
        self.assertTrue(all(not row['qualified'] and row['proxy_loss_percent'] == 100 for row in rows))
        self.assertEqual(manager.controller.speed_calls, [])

    def test_slow_first_request_does_not_hold_back_next_candidate(self):
        manager = FakeManager()
        next_started = threading.Event()
        released = []
        original = manager.controller.delay

        def probe(name, url, expected, timeout):
            if name == 'PB-000001' and url == SITES[0][1]:
                released.append(next_started.wait(.4))
            if name == 'PB-000003':
                next_started.set()
            return original(name, url, expected, timeout)

        manager.controller.site_probe = probe
        self.bench(manager, pool(6), {'delay_concurrency': 2, 'adaptive_concurrency': 0})
        self.assertEqual(released, [True], 'a cohort barrier held the next candidate back')

    def test_three_sites_can_progress_independently_with_the_same_strict_mean(self):
        manager = FakeManager()
        second_site = threading.Event()
        independent = []
        values = dict(zip((site[1] for site in SITES), (100, 200, 303)))

        def probe(name, url, expected, timeout):
            if url == SITES[0][1]:
                independent.append(second_site.wait(.4))
            else:
                second_site.set()
            return {'success': True, 'latency_ms': values[url], 'selected_proxy': name,
                    'routing_proof': 'connection-chain', 'destination': url}

        manager.controller.site_probe = probe
        rows = self.bench(manager, pool(1), {'delay_concurrency': 3, 'adaptive_concurrency': 0,
                                           'max_proxy_average_latency_ms': 200})
        self.assertEqual(independent, [True])
        self.assertEqual(rows[0]['proxy_average_latency_ms'], 201)
        self.assertFalse(rows[0]['qualified'])
        self.assertEqual(manager.controller.speed_calls, [])
        self.assertTrue(all(len(rows[0]['probes'][site]) == 1 for site, _, _ in SITES))

    def test_geo_confirmation_does_not_occupy_the_only_download_slot(self):
        manager = FakeManager()
        manager.controller.named_ports = {'PB-000001': 1, 'PB-000002': 2}
        second_download = threading.Event()
        freed = []
        original_speed = manager.controller.legacy_speed
        original_geo = manager.controller.request

        def speed(name, url, **kwargs):
            if name == 'PB-000002':
                second_download.set()
            return original_speed(name, url, **kwargs)

        def geo(name, url, **kwargs):
            if name == 'PB-000001':
                freed.append(second_download.wait(.4))
            return original_geo(name, url, **kwargs)

        manager.controller.legacy_speed = speed
        manager.controller.request = geo
        rows = self.bench(manager, pool(2), {'speed_concurrency': 1}, ['https://ipwho.is/'])
        self.assertEqual(freed, [True], 'location queries occupied the download worker')
        self.assertTrue(all(row['qualified'] and row['geo_verified'] for row in rows))
