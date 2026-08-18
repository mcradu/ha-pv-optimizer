import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))


class RuntimeTests(unittest.TestCase):
    def test_poll_without_supervisor_is_blocked_not_crashed(self):
        with tempfile.TemporaryDirectory() as directory:
            options = Path(directory) / "options.json"
            state = Path(directory) / "state.json"
            with patch.dict(os.environ, {}, clear=True):
                import run
                with patch.object(run, "OPTIONS_PATH", options), patch.object(run, "STATE_PATH", state):
                    runtime = run.Runtime()
                    runtime.poll()
                    self.assertEqual(runtime.status["decision"]["state"], "blocked")
                    self.assertEqual(runtime.status["decision"]["target_export_w"], 0)
                    self.assertTrue(runtime.status["errors"])


if __name__ == "__main__":
    unittest.main()
