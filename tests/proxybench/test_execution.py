import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.proxybench.execution import cli_python


class BackgroundExecutionTests(unittest.TestCase):
    def test_pythonw_ui_uses_console_sibling_for_synchronous_runner_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python.exe"
            python.touch()
            with patch.object(sys, "executable", str(Path(directory) / "pythonw.exe")):
                self.assertEqual(cli_python(), str(python))

    def test_missing_console_sibling_fails_before_background_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "executable", str(Path(directory) / "pythonw.exe")):
                with self.assertRaises(ValueError):
                    cli_python()

    def test_console_python_is_retained(self):
        self.assertEqual(cli_python(), sys.executable)
