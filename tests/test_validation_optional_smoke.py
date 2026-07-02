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


DEFAULT_REAL_HARNESS_PROFILES = [
    "codex_acp_local",
    "opencode_acp_local",
]


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
        ] or DEFAULT_REAL_HARNESS_PROFILES

        source_env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                item for item in [str(ROOT / "src"), os.environ.get("PYTHONPATH", "")] if item
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        timeout_seconds = int(os.environ.get("ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS", "120"))

        with tempfile.TemporaryDirectory(prefix="orbital-real-smoke-") as raw:
            tmp = Path(raw)
            smoke_base = tmp / "base"
            smoke_base.mkdir()
            doctor = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "orbital_mcp.setup_cli",
                    "--base-dir",
                    str(smoke_base),
                    "doctor",
                    "--json",
                ],
                cwd=ROOT,
                env=source_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)
            doctor_payload = json.loads(doctor.stdout)
            profile_status = {item["id"]: item for item in doctor_payload["profiles"]}
            ready_profiles = [
                profile
                for profile in profiles
                if profile in profile_status and profile_status[profile].get("ready") is True
            ]
            if not ready_profiles:
                self.skipTest(f"no selected real-harness profiles are ready: {', '.join(profiles)}")

            for profile in profiles:
                if profile not in profile_status:
                    self.fail(f"unknown real-harness profile: {profile}")
                if profile_status[profile].get("ready") is not True:
                    reason = ", ".join(profile_status[profile].get("missing_prerequisites") or ["not ready"])
                    with self.subTest(profile=profile):
                        self.skipTest(f"{profile} is not ready: {reason}")
                    continue
                workdir = tmp / profile
                workdir.mkdir()
                with self.subTest(profile=profile):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "orbital_mcp.smoke",
                            "--base-dir",
                            str(smoke_base),
                            "--profile",
                            profile,
                            "--workdir",
                            str(workdir),
                            "--timeout-seconds",
                            str(timeout_seconds),
                        ],
                        cwd=ROOT,
                        env=source_env,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds + 30,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                    payload = json.loads(completed.stdout)
                    self.assertEqual(payload["status"], "completed")


if __name__ == "__main__":
    unittest.main()
