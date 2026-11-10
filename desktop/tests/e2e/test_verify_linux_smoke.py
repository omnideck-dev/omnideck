import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("verify_linux_smoke", Path(__file__).with_name("verify_linux_smoke.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PackagedSmokeTests(unittest.TestCase):
    def test_renderer_failure_cannot_pass_with_valid_cli_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof = {"cliVersion": "v1", "cliCommit": "abc", "schemaVersion": 4,
                     "operations": ["--version", "--json runtime status"], "mutation": False}
            (root / "smoke-proof.json").write_text(json.dumps(proof))
            for error in ["Could not create default EGL display: EGL_BAD_PARAMETER. Aborting...",
                          "Segmentation fault (core dumped)"]:
                with self.subTest(error=error):
                    (root / "host.stderr.log").write_text(error)
                    with self.assertRaisesRegex(ValueError, "renderer failed"):
                        MODULE.verify(root, "v1", "abc")
            (root / "host.stderr.log").write_text("Gtk-Message: Failed to load optional canberra-gtk-module\n")
            MODULE.verify(root, "v1", "abc")
            with self.assertRaisesRegex(ValueError, "cliVersion mismatch"):
                MODULE.verify(root, "v2", "abc")
            proof["mutation"] = 0
            (root / "smoke-proof.json").write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, "mutation mismatch"):
                MODULE.verify(root, "v1", "abc")


if __name__ == "__main__":
    unittest.main()
