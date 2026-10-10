from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.proxybench import test_dashboard_pages
from tests.proxybench.test_benchmark import pool


class LiveQualifiedTests(unittest.TestCase):
    def test_only_finished_passes_under_current_rules_are_visible_in_rank_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = test_dashboard_pages.DashboardPageTests()
            dashboard = helper.controller(root)
            nodes = pool(7)
            def result(index, **values):
                return {**nodes[index], 'qualified': True, 'tested_at': '2026-10-10', 'status': 'Qualified',
                        'proxy_average_latency_ms': 100, 'proxy_loss_percent': 0,
                        'proxy_download_average_mbps': 5, **values}
            rows = [result(0, proxy_average_latency_ms=120), result(1, proxy_average_latency_ms=90),
                    result(2, qualified=False), result(3, proxy_average_latency_ms=301),
                    result(4, proxy_download_average_mbps=2), result(5, tested_at='', status='Location Testing')]
            helper.write(root/'data/proxy-bench/benchmark-results.json.gz', {str(i): row for i, row in enumerate(rows)})
            helper.write(root/'data/proxy-bench/live.json', {'run_id': 'now', 'phase': 'scan'})
            helper.write(root/'data/proxy-bench/partial-batch.json', {'run_id': 'now', 'phase': 'scan', 'results': {'partial': result(6, proxy_average_latency_ms=80)}})
            page = dashboard.action('qualified-results', {'page': 1})
            self.assertEqual([row['ip'] for row in page['rows']], [nodes[6]['ip'], nodes[1]['ip'], nodes[0]['ip']])
            helper.write(root/'data/proxybench-rules.json', {'max_proxy_average_latency_ms': 85})
            self.assertEqual(dashboard.rows('qualified-results', 1)['total'], 1)

    def test_qualified_results_have_their_own_300_row_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = test_dashboard_pages.DashboardPageTests()
            dashboard = helper.controller(root)
            rows = [{**row, 'qualified': True, 'status': 'Qualified', 'tested_at': '2026-10-10', 'proxy_loss_percent': 0,
                     'proxy_average_latency_ms': 100, 'proxy_download_average_mbps': 5} for row in pool(650)]
            helper.write(root/'data/proxy-bench/benchmark-results.json.gz', {str(i): row for i, row in enumerate(rows)})
            first = dashboard.rows('qualified-results', 1)
            self.assertEqual((first['total'], first['pages'], len(first['rows'])), (650, 3, 300))
            self.assertEqual(len(dashboard.rows('qualified-results', 3)['rows']), 50)
