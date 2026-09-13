"""Reject undecodable Git configuration before a checkout can run filters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "worktrees.py"


@unittest.skipUnless(shutil.which("git"), "Git is required for integration tests")
class WorktreeEncodingTests(unittest.TestCase):
    def test_undecodable_filter_name_is_rejected_without_execution(self):
        with tempfile.TemporaryDirectory(prefix="deliberate encoding tests ") as temporary:
            directory = Path(temporary)
            repo = directory / "source"
            repo.mkdir()
            root = directory / "worktrees"
            marker = directory / "filter executed"
            environment = {
                key: value for key, value in os.environ.items()
                if not key.upper().startswith("GIT_")
            }
            environment.update({
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
            })

            def git(*arguments):
                return subprocess.run(
                    ["git", "-c", "core.hooksPath=" + os.devnull,
                     "-c", "core.fsmonitor=false", "-C", str(repo), *arguments],
                    capture_output=True, check=True, env=environment,
                )

            git("init", "--initial-branch=main")
            git("config", "user.name", "Encoding Test")
            git("config", "user.email", "encoding-test@localhost")
            git("config", "core.autocrlf", "false")
            (repo / "example.txt").write_text("original content\n", encoding="utf-8")
            (repo / ".gitattributes").write_bytes(b"example.txt filter=unsafe\xff\n")
            git("add", ".")
            git("commit", "-m", "initial fixture")

            filter_script = directory / "filter.sh"
            filter_script.write_text(
                "#!/bin/sh\nprintf triggered > " + shlex.quote(marker.as_posix()) + "\ncat\n",
                encoding="utf-8",
            )
            filter_script.chmod(0o755)
            # Git accepts raw subsection bytes. Lossy UTF-8 decoding changes this
            # driver's name, so overrides for the replacement name cannot disable it.
            with (repo / ".git" / "config").open("ab") as configuration:
                configuration.write(
                    b'\n[filter "unsafe\xff"]\n\tsmudge = sh '
                    + shlex.quote(filter_script.as_posix()).encode("utf-8") + b"\n"
                )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "create", "--repo", str(repo),
                 "--run-id", "encoding-check", "--task-id", "filter-check",
                 "--root", str(root), "--apply"],
                capture_output=True, text=True, env=environment,
            )
            self.assertFalse(marker.exists(), "An undecodable filter name allowed its command to execute.")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("error", json.loads(result.stderr))
            self.assertFalse(root.exists(), "Configuration rejection must precede destination creation.")
            self.assertEqual((repo / "example.txt").read_text(), "original content\n")


if __name__ == "__main__":
    unittest.main()
