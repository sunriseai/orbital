from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

from orbital_test_helpers import ROOT, write_fake_acp_config


class OptionalSmokeValidationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("ORBITAL_RUN_PACKAGING_SMOKE") == "1",
        "set ORBITAL_RUN_PACKAGING_SMOKE=1 to run installed-package validation",
    )
    def test_installed_package_console_scripts_and_fake_smoke(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orbital-package-smoke-") as raw:
            tmp = Path(raw)
            venv = tmp / "venv"
            base = tmp / "base"
            workdir = tmp / "work"
            source = tmp / "source"
            base.mkdir()
            workdir.mkdir()
            write_fake_acp_config(base)
            smoke_env = {
                **os.environ,
                "PYTHONPATH": sysconfig.get_path("purelib"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            }
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".orbital",
                    ".tmp-test-*",
                    "__pycache__",
                    "*.pyc",
                    "*.egg-info",
                    "build",
                    "dist",
                ),
            )

            subprocess.run(
                [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            python = venv / "bin" / "python"
            bin_dir = venv / "bin"
            install = subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--no-build-isolation",
                    "-e",
                    str(source),
                ],
                cwd=source,
                env=smoke_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(install.returncode, 0, install.stderr + install.stdout)

            for command in [
                [str(bin_dir / "orbital"), "--help"],
                [str(bin_dir / "orbital"), "--base-dir", str(base), "doctor"],
                [str(bin_dir / "orbital"), "--base-dir", str(base), "profiles"],
                [str(bin_dir / "orbital"), "--base-dir", str(base), "mcp-config"],
                [str(bin_dir / "orbital-mcp"), "--help"],
                [str(bin_dir / "orbital-mcp-smoke"), "--help"],
            ]:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=smoke_env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)

            smoke = subprocess.run(
                [
                    str(bin_dir / "orbital-mcp-smoke"),
                    "--base-dir",
                    str(base),
                    "--profile",
                    "fake_acp",
                    "--workdir",
                    str(workdir),
                    "--timeout-seconds",
                    "5",
                ],
                cwd=ROOT,
                env=smoke_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stderr + smoke.stdout)
            payload = json.loads(smoke.stdout)
            self.assertEqual(payload["status"], "completed")
            self.assertTrue((workdir / "ORBITAL_SMOKE.md").exists())

    @unittest.skipUnless(
        os.environ.get("ORBITAL_RUN_REAL_HARNESS_SMOKE") == "1",
        "set ORBITAL_RUN_REAL_HARNESS_SMOKE=1 to run real-harness smoke tests",
    )
    def test_selected_real_harness_profiles_smoke(self) -> None:
        profiles = [
            item.strip()
            for item in os.environ.get("ORBITAL_REAL_HARNESS_PROFILES", "").split(",")
            if item.strip()
        ]
        if not profiles:
            self.skipTest("set ORBITAL_REAL_HARNESS_PROFILES to one or more profile ids")
        smoke = shutil.which("orbital-mcp-smoke")
        orbital = shutil.which("orbital")
        if not smoke or not orbital:
            self.skipTest("installed orbital console scripts are required for real-harness smoke tests")

        with tempfile.TemporaryDirectory(prefix="orbital-real-smoke-") as raw:
            tmp = Path(raw)
            doctor = subprocess.run(
                [orbital, "--base-dir", str(ROOT), "doctor"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)
            for profile in profiles:
                workdir = tmp / profile
                workdir.mkdir()
                completed = subprocess.run(
                    [
                        smoke,
                        "--base-dir",
                        str(ROOT),
                        "--profile",
                        profile,
                        "--workdir",
                        str(workdir),
                        "--timeout-seconds",
                        os.environ.get("ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS", "120"),
                    ],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=int(os.environ.get("ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS", "120")) + 30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                payload = json.loads(completed.stdout)
                self.assertIn(payload["status"], {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"})


if __name__ == "__main__":
    unittest.main()
