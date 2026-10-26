"""Real launcher subprocess checks; synthetic entrypoint, no GUI or dependency download."""
from __future__ import annotations
import ensurepip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "packaging" / "bootstrap.py"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="abl1 launcher ")
        self.project = Path(self.tmp.name) / "Lab O'Neil & prøve Å"
        self.project.mkdir()
        if (ROOT / "packaging").is_dir():
            shutil.copytree(ROOT / "packaging", self.project / "packaging")
        for name in ("START_DRAGEN.cmd", "INSTALL_DRAGEN.cmd", "start.py", "install.py"):
            if (ROOT / name).is_file():
                shutil.copyfile(ROOT / name, self.project / name)
        (self.project / "src" / "abl1_workstation").mkdir(parents=True)
        for relative in ("engine/analyze.py", "desktop/data/pilot.json", "app/data/knowledge.json", "app/data/igv-manifest.json"):
            resource=self.project/relative;resource.parent.mkdir(parents=True,exist_ok=True);resource.write_text('{}')
        (self.project / "pyproject.toml").write_text(
            '[project]\nname="abl1-test"\nversion="0.3.0"\nrequires-python=">=3.12,<3.16"\n',
            encoding="utf-8")
        (self.project / "requirements-desktop.txt").write_text(
            f"pip=={ensurepip.version()}\n", encoding="utf-8")
        (self.project / "start_abl1.py").write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "Path('arguments.json').write_text(json.dumps(sys.argv[1:]))\n"
            "print('synthetic entrypoint stdout')\n"
            "print('synthetic entrypoint stderr',file=sys.stderr)\n"
            "raise SystemExit(7)\n", encoding="utf-8")
        self.env = dict(os.environ, ABL1_PYTHON=sys.executable,DRAGEN_LOCAL_PYTHON='1',ABL1_NO_PAUSE='1',
                        PYTHONIOENCODING="utf-8")
        self.env.pop("PYTHONPATH", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_bootstrap(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.project / "packaging/bootstrap.py"), *arguments],
            cwd=self.tmp.name, env=self.env, capture_output=True,
            encoding="utf-8", errors="replace", timeout=90)

    def test_check_missing_environment_never_installs_and_reports_paths(self):
        result = self.run_bootstrap("check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        diagnostic = json.loads(result.stdout)
        self.assertFalse(diagnostic["ready"])
        self.assertEqual(diagnostic["project"], str(self.project.resolve()))
        self.assertFalse((self.project / ".venv").exists())
        self.assertIn("INSTALL_DRAGEN.cmd", " ".join(diagnostic["errors"]))

    def test_start_does_not_install_or_launch_when_environment_is_missing(self):
        result = self.run_bootstrap("start", "--data-dir", "a data folder")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.project / ".venv").exists())
        self.assertFalse((self.project / "arguments.json").exists())

    def test_python_range_is_read_from_project_before_environment_creation(self):
        path = self.project / "pyproject.toml"
        path.write_text(path.read_text().replace(">=3.12,<3.16", ">=9.0,<10.0"))
        result = self.run_bootstrap("install", "--offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / ".venv").exists())
        self.assertIn(">=9.0,<10.0", result.stdout + result.stderr)

    def test_explicit_python_failure_is_not_silently_replaced(self):
        result = self.run_bootstrap("check", "--python", str(self.project / "missing.exe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing.exe", result.stdout + result.stderr)
        self.assertFalse((self.project / ".venv").exists())

    def test_offline_requires_local_wheelhouse_and_never_falls_back_online(self):
        result = self.run_bootstrap("install", "--offline")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wheelhouse", (result.stdout + result.stderr).lower())
        self.assertFalse((self.project / ".venv").exists())

    def test_real_offline_install_check_and_start_in_clean_source_folder(self):
        (self.project / "wheelhouse").mkdir()
        installed = self.run_bootstrap("install", "--offline")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        checked = self.run_bootstrap("check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        info = json.loads(checked.stdout)
        self.assertTrue(info["ready"])
        self.assertEqual(info["requirements"][0]["installed"], ensurepip.version())
        config = (self.project / ".venv/pyvenv.cfg").read_text().lower()
        self.assertIn("include-system-site-packages = false", config)
        started = self.run_bootstrap("start", "--data-dir", "a review & data folder")
        self.assertEqual(started.returncode, 7, started.stdout + started.stderr)
        self.assertEqual(json.loads((self.project / "arguments.json").read_text()),
                         ["--data-dir", "a review & data folder"])
        self.assertIn("synthetic entrypoint stdout", started.stdout)
        self.assertIn("synthetic entrypoint stderr", started.stderr)
        log = self.project / "work/launcher-logs/bootstrap.log"
        self.assertIn("synthetic entrypoint stderr", log.read_text(encoding="utf-8"))
        self.assertIn("exit_code=7", log.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "Windows CMD entrypoints")
    def test_actual_cmd_routes_handle_special_paths_and_failure_exit_code(self):
        (self.project / "wheelhouse").mkdir()
        (self.project/'install.py').write_text("import sys\nfrom pathlib import Path\nPath(__file__).with_name('cmd-install-args.json').write_text(__import__('json').dumps(sys.argv[1:]))\n",encoding='utf-8')
        (self.project/'start.py').write_text("import json,sys\nfrom pathlib import Path\nPath(__file__).with_name('arguments.json').write_text(json.dumps(sys.argv[1:]))\nraise SystemExit(7)\n",encoding='utf-8')
        def invoke(name, args=""):
            command = f'cmd.exe /d /s /c ""{self.project / name}" {args}"'
            return subprocess.run(command, cwd=self.tmp.name, env=self.env,
                                  input="", capture_output=True, encoding="utf-8",
                                  errors="replace", timeout=90)
        installed = invoke("INSTALL_DRAGEN.cmd", "--offline")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual(json.loads((self.project/'cmd-install-args.json').read_text()),['--offline'])
        started = invoke("START_DRAGEN.cmd", '--data-dir "a CMD review & data"')
        self.assertEqual(started.returncode, 7, started.stdout + started.stderr)
        self.assertEqual(json.loads((self.project / "arguments.json").read_text()),
                         ["--data-dir", "a CMD review & data"])


if __name__ == "__main__":
    unittest.main()
