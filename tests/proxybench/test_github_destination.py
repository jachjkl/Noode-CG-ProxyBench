from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.proxybench.cloud import CloudController, CloudError
from core.proxybench.github_destination import (
    check_destination,
    check_steps,
    destination,
    load_destination,
    save_destination,
)
from core.proxybench.multi_dashboard import MultiModeDashboard
from core.proxybench.settings import load_settings


class GithubDestinationTests(unittest.TestCase):
    def test_official_login_completion_starts_checks_and_cancellation_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("config.yaml").write_bytes(Path("config.yaml").read_bytes())
            ui = MultiModeDashboard(SimpleNamespace(root=root, repository="jachjkl/Noode-CG-ProxyBench"))
            ui.github_status = {"status": "Authenticating", "steps": check_steps()}
            ui.github_login_process = SimpleNamespace(poll=lambda: 0, returncode=0)
            with patch.object(ui, "check_github") as check:
                ui.snapshot()
                check.assert_called_once_with({})
            self.assertIsNone(ui.github_login_process)
            ui.github_status = {"status": "Authenticating", "steps": check_steps()}
            ui.github_login_process = SimpleNamespace(poll=lambda: 1, returncode=1)
            ui.snapshot()
            self.assertEqual(ui.github_status["status"], "Failed")
            self.assertEqual(ui.github_status["steps"][0]["status"], "failed")
    def test_live_checks_report_each_success_and_the_exact_failed_step(self):
        events = []
        result = check_destination(self.client(), destination("new-owner/project"), events.append)
        self.assertEqual([row["id"] for row in events if row["status"] == "completed"], ["account", "repository", "branch", "candidates", "publication"])
        self.assertTrue(all(row["status"] == "completed" for row in result["steps"]))
        self.assertEqual(events[1]["account"], "new-owner")
        events.clear()
        with self.assertRaises(ValueError):
            check_destination(self.client(push=False), destination("new-owner/project"), events.append)
        self.assertEqual((events[-1]["id"], events[-1]["status"]), ("repository", "failed"))
        self.assertEqual([row["id"] for row in events if row["status"] == "completed"], ["account"])
    def client(self, full_name="new-owner/renamed-project", *, push=True, actor="new-owner"):
        client = Mock()
        def command(args, **kwargs):
            path = args[1]
            if path == "user":
                return actor
            if path.count("/") == 2:
                return {"full_name": full_name, "permissions": {"push": push}}
            return {"state": "active"}
        client.command.side_effect = command
        return client

    def test_renamed_repository_and_other_owner_are_resolved_without_writes(self):
        client = self.client()
        result = check_destination(client, destination("new-owner/old-name", "release/v1"))
        self.assertTrue(result['renamed'])
        self.assertEqual(result['repository'], 'new-owner/renamed-project')
        self.assertTrue(all(call.args[0][0] == 'api' and '--method' not in call.args[0] for call in client.command.call_args_list))

    def test_saved_destination_survives_reopening_and_never_changes_measured_ips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            measured = root/'output/nodes.txt'
            measured.parent.mkdir()
            measured.write_text('82.139.242.5:443#DE\n', encoding='utf-8')
            saved = save_destination(root, destination('https://github.com/new-owner/new-project.git', 'develop'))
            self.assertEqual(load_destination(root), saved)
            self.assertEqual(json.loads((root/'data/github-settings.json').read_text()), saved)
            self.assertEqual(measured.read_text(), '82.139.242.5:443#DE\n')

    def test_invalid_targets_permissions_and_wrong_accounts_fail_without_mutation(self):
        for repository, branch in [('https://evil.example/owner/repo', 'main'), ('owner/repo?token=secret', 'main'), ('owner/repo', '--exec'), ('owner/repo', '../main')]:
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                destination(repository, branch)
        for client in (self.client(push=False), self.client(actor='wrong-owner')):
            with self.assertRaises(ValueError):
                check_destination(client, destination('new-owner/project'))

    def test_cloud_writes_check_the_current_account_before_dispatch_and_blob_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_destination(root, destination('new-owner/project', 'develop'))
            client = CloudController({'root': root, 'state_dir': root})
            client.gh = 'gh'
            for args in (['workflow', 'run', 'proxybench.yml', '--repo', client.repository],
                         ['api', '--method', 'POST', f'repos/{client.repository}/git/blobs']):
                with patch('core.proxybench.cloud.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='wrong-owner')) as run:
                    with self.assertRaises(CloudError):
                        client.command(args)
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][1:], ['api', 'user', '--jq', '.login'])
            with patch('core.proxybench.cloud.subprocess.run', side_effect=[SimpleNamespace(returncode=0, stdout='new-owner'), SimpleNamespace(returncode=0, stdout='{"sha":"result"}')]) as run:
                result = client.command(['api', '--method', 'POST', f'repos/{client.repository}/git/blobs'], as_json=True)
                self.assertEqual(result, {'sha': 'result'})
                self.assertEqual(run.call_count, 2)

    def test_saved_repository_and_branch_reach_both_engines_and_survive_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('config.yaml').write_bytes(Path('config.yaml').read_bytes())
            ui = MultiModeDashboard(SimpleNamespace(root=root, repository='jachjkl/Noode-CG-ProxyBench'))
            for child in ui.controllers.values():
                child.refresh_cloud = Mock()
            saved = ui.action('save-github-settings', {'repository': 'new-owner/project', 'branch': 'release/v1'})
            self.assertTrue(saved['saved'])
            for child in ui.controllers.values():
                self.assertEqual((child.settings['repository'], child.settings['branch']), ('new-owner/project', 'release/v1'))
                self.assertEqual(child.snapshot()['actions_url'], 'https://github.com/new-owner/project/actions')
            self.assertEqual(load_settings(root/'config.yaml')['branch'], 'release/v1')
            with patch.object(ui, 'active', return_value='proxy'), self.assertRaises(ValueError):
                ui.action('save-github-settings', {'repository': 'wrong-owner/repo'})
            self.assertEqual(load_destination(root)['repository'], 'new-owner/project')

    def test_target_change_during_cloud_read_cannot_replace_new_repository_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('config.yaml').write_bytes(Path('config.yaml').read_bytes())
            ui = MultiModeDashboard(SimpleNamespace(root=root, repository='jachjkl/Noode-CG-ProxyBench'))
            child = ui.controllers['proxy']
            started, finish = threading.Event(), threading.Event()
            def read(client):
                started.set()
                finish.wait(2)
                return {'repository': client.repository, 'nodes': ['stale-old-repository']}
            with patch('core.proxybench.cloud_nodes.read_published', side_effect=read):
                child.refresh_cloud()
                self.assertTrue(started.wait(1))
                thread = child.cloud_refresh_thread
                child.refresh_cloud = Mock()
                ui.controllers['tcp_tls'].refresh_cloud = Mock()
                ui.save_github({'repository': 'new-owner/project', 'branch': 'main'})
                finish.set()
                thread.join(2)
            self.assertEqual(child.cloud_published['nodes'], [])
            self.assertFalse((child.settings['state_dir']/'cloud-published.json').exists())
