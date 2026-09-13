"""Behavioral tests for the worktree helper using disposable real Git repositories."""

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
class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deliberate tests ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.repo = self.directory / "source repo"
        self.repo.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Test Builder")
        self.git("config", "user.email", "test@localhost")
        self.git("config", "core.autocrlf", "false")
        (self.repo / "hello.txt").write_text("original\n", encoding="utf-8")
        self.git("add", "hello.txt")
        self.git("-c", "core.hooksPath=" + os.devnull, "commit", "-m", "initial")
        self.initial = self.git("rev-parse", "HEAD").stdout.strip()
        self.root = self.directory / "task worktrees"

    def git(self, *args, cwd=None, check=True):
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
             "-C", str(cwd or self.repo), *args],
            capture_output=True, text=True, check=check, env=env,
        )

    def cli(self, *extra, repo=None, run="feature-one", task="unit-one", env=None):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--repo", str(repo or self.repo),
             "--run-id", run, "--task-id", task, "--root", str(self.root), *extra],
            capture_output=True, text=True, env=env,
        )
        payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        return result, payload

    def assert_rejected(self, *extra, contains=None, **kwargs):
        result, payload = self.cli(*extra, **kwargs)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("error", payload)
        if contains:
            self.assertIn(contains.lower(), payload["error"].lower())
        return payload

    def test_dry_run_has_absolute_plan_and_does_not_mutate_repo(self):
        index_before = (self.repo / ".git" / "index").read_bytes()
        refs_before = self.git("show-ref").stdout
        result, data = self.cli()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["action"], "plan")
        self.assertEqual(data["base_commit"], self.initial)
        self.assertEqual(data["branch"], "deliberate/feature-one/unit-one")
        self.assertEqual(Path(data["repo"]), self.repo.resolve())
        self.assertEqual(Path(data["worktree"]), (self.root / "feature-one--unit-one").resolve())
        self.assertFalse(self.root.exists())
        self.assertEqual(self.git("show-ref").stdout, refs_before)
        self.assertEqual((self.repo / ".git" / "index").read_bytes(), index_before)

    def test_apply_creates_isolated_branch_worktree_with_spaces(self):
        result, data = self.cli("--apply")
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual(data["action"], "created")
        worktree = Path(data["worktree"])
        self.assertEqual((worktree / "hello.txt").read_text(), "original\n")
        self.assertEqual(self.git("branch", "--show-current", cwd=worktree).stdout.strip(), data["branch"])
        (worktree / "hello.txt").write_text("task change\n")
        self.assertEqual((self.repo / "hello.txt").read_text(), "original\n")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.initial)

    def test_default_root_is_sibling_of_source(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--repo", str(self.repo),
             "--run-id", "run", "--task-id", "task"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)["root"]), (self.directory / "source repo-deliberate-worktrees").resolve())

    def test_explicit_base_is_used_and_source_branch_unchanged(self):
        (self.repo / "hello.txt").write_text("second\n")
        self.git("add", "hello.txt")
        self.git("-c", "core.hooksPath=" + os.devnull, "commit", "-m", "second")
        source_head = self.git("rev-parse", "HEAD").stdout
        result, data = self.cli("--base", self.initial, "--apply")
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual((Path(data["worktree"]) / "hello.txt").read_text(), "original\n")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, source_head)

    def test_tracked_dirty_source_is_rejected_and_preserved(self):
        (self.repo / "hello.txt").write_text("user edits\n")
        self.assert_rejected("--apply", contains="clean")
        self.assertEqual((self.repo / "hello.txt").read_text(), "user edits\n")
        self.assertFalse(self.root.exists())

    def test_staged_source_is_rejected_and_preserved(self):
        (self.repo / "hello.txt").write_text("staged work\n")
        self.git("add", "hello.txt")
        before = (self.repo / ".git" / "index").read_bytes()
        self.assert_rejected("--apply", contains="clean")
        self.assertEqual((self.repo / ".git" / "index").read_bytes(), before)

    def test_untracked_source_is_rejected_and_preserved(self):
        user_file = self.repo / "private notes.txt"
        user_file.write_text("keep this")
        self.assert_rejected("--apply", contains="clean")
        self.assertEqual(user_file.read_text(), "keep this")
        self.assertFalse(self.root.exists())

    def test_rejects_nonrepository(self):
        unrelated = self.directory / "ordinary directory"
        unrelated.mkdir()
        self.assert_rejected(repo=unrelated, contains="repository")

    def test_rejects_missing_repository(self):
        self.assert_rejected(repo=self.directory / "missing", contains="directory")

    def test_requires_repository_root(self):
        child = self.repo / "child"
        child.mkdir()
        self.assert_rejected(repo=child, contains="root")

    def test_rejects_repository_without_initial_commit(self):
        empty = self.directory / "empty repo"
        empty.mkdir()
        self.git("init", cwd=empty)
        self.assert_rejected(repo=empty, contains="commit")

    def test_rejects_bare_repository(self):
        bare = self.directory / "bare.git"
        self.git("init", "--bare", str(bare))
        self.assert_rejected(repo=bare, contains="working")

    def test_rejects_missing_base(self):
        self.assert_rejected("--base", "does-not-exist", "--apply", contains="commit")
        self.assertFalse(self.root.exists())

    def test_option_looking_base_cannot_become_git_option(self):
        self.assert_rejected("--base=--output=unexpected", "--apply", contains="commit")
        self.assertFalse(self.root.exists())

    def test_rejects_noncommit_base(self):
        blob = self.git("rev-parse", "HEAD:hello.txt").stdout.strip()
        self.assert_rejected("--base", blob, contains="commit")

    def test_rejects_unsafe_or_nonportable_ids(self):
        invalid = ["../outside", "a/b", "a\\b", "-flag", "a b", "a..b", "a;echo", "a\nother",
                   "CON", "con", "nul", "aux", "com1", "lpt9", "Uppercase", "a_thing", "a" * 49]
        for slug in invalid:
            with self.subTest(slug=repr(slug)):
                # Equals form prevents argparse treating malicious input as its own option.
                self.assert_rejected("--task-id=" + slug, contains="slug")
        self.assertFalse(self.root.exists())

    def test_rejects_existing_destination_without_modifying_it(self):
        destination = self.root / "feature-one--unit-one"
        destination.mkdir(parents=True)
        (destination / "keep.txt").write_text("keep")
        self.assert_rejected("--apply", contains="exists")
        self.assertEqual((destination / "keep.txt").read_text(), "keep")

    def test_rejects_existing_branch(self):
        self.git("branch", "deliberate/feature-one/unit-one")
        self.assert_rejected("--apply", contains="branch")
        self.assertFalse(self.root.exists())

    def test_rejects_root_inside_repository(self):
        self.assert_rejected("--root", str(self.repo / "nested worktrees"), "--apply", contains="inside")
        self.assertFalse((self.repo / "nested worktrees").exists())

    def test_rejects_root_equal_to_repository(self):
        self.assert_rejected("--root", str(self.repo), contains="inside")

    def test_rejects_file_as_root(self):
        self.root.write_text("keep")
        self.assert_rejected("--apply", contains="directory")
        self.assertEqual(self.root.read_text(), "keep")

    def test_rejects_explicitly_empty_root(self):
        self.assert_rejected("--root", "", "--apply", contains="path")

    def test_rejects_symlink_or_junction_ancestor(self):
        real = self.directory / "real target"
        real.mkdir()
        link = self.directory / "linked root"
        if os.name == "nt":
            # NTFS junction creation needs no elevated symlink privilege.
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            command = ["powershell", "-NoProfile", "-Command",
                       "New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(real) + " | Out-Null"]
            created = subprocess.run(command, capture_output=True, text=True)
            if created.returncode:
                self.skipTest("Cannot create a junction: " + created.stderr)
        else:
            link.symlink_to(real, target_is_directory=True)
        self.assert_rejected("--root", str(link / "nested"), "--apply", contains="link")
        self.assertEqual(list(real.iterdir()), [])

    def test_does_not_execute_repository_hooks_or_fsmonitor(self):
        marker = self.directory / "hook executed"
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nprintf triggered > " + shlex.quote(marker.as_posix()) + "\n")
        hook.chmod(0o755)
        self.git("config", "core.fsmonitor", hook.as_posix())
        result, data = self.cli("--apply")
        self.assertEqual(result.returncode, 0, data)
        self.assertFalse(marker.exists())

    def test_does_not_execute_checkout_filters(self):
        marker = self.directory / "filter executed"
        hook = self.directory / "filter.sh"
        hook.write_text("#!/bin/sh\nprintf triggered > " + shlex.quote(marker.as_posix()) + "\ncat\n")
        hook.chmod(0o755)
        (self.repo / ".gitattributes").write_text("hello.txt filter=untrusted\n")
        self.git("add", ".gitattributes")
        self.git("-c", "core.hooksPath=" + os.devnull, "commit", "-m", "attributes")
        self.git("config", "filter.untrusted.smudge", "sh " + shlex.quote(hook.as_posix()))
        result, data = self.cli("--apply")
        self.assertEqual(result.returncode, 0, data)
        self.assertFalse(marker.exists())
        self.assertEqual((Path(data["worktree"]) / "hello.txt").read_text(), "original\n")

    def test_submodule_status_does_not_execute_clean_filters(self):
        upstream = self.directory / "module upstream"
        upstream.mkdir()
        self.git("init", cwd=upstream)
        self.git("config", "user.name", "Test Builder", cwd=upstream)
        self.git("config", "user.email", "test@localhost", cwd=upstream)
        (upstream / "module.txt").write_text("module content\n")
        (upstream / ".gitattributes").write_text("module.txt filter=module-filter\n")
        self.git("add", ".", cwd=upstream)
        self.git("commit", "-m", "module", cwd=upstream)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(upstream), "module")
        self.git("add", ".")
        self.git("commit", "-m", "add module")
        module = self.repo / "module"
        marker = self.directory / "module filter executed"
        hook = self.directory / "module-filter.sh"
        hook.write_text("#!/bin/sh\nprintf triggered > " + shlex.quote(marker.as_posix()) + "\ncat\n")
        hook.chmod(0o755)
        self.git("config", "filter.module-filter.clean", "sh " + shlex.quote(hook.as_posix()), cwd=module)
        # A stat change forces Git to inspect content; the clean command must still not execute.
        (module / "module.txt").write_text("module changed\n")
        self.git("status", "--porcelain", cwd=module)
        self.assertTrue(marker.exists(), "The fixture must prove its clean filter can execute.")
        marker.unlink()
        self.assert_rejected("--apply", contains="clean")
        self.assertFalse(marker.exists())
        self.assertEqual((module / "module.txt").read_text(), "module changed\n")

    def test_ignores_inherited_git_environment_redirects(self):
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.directory / "does not exist")
        env["GIT_WORK_TREE"] = str(self.directory)
        env["GIT_INDEX_FILE"] = str(self.directory / "foreign-index")
        result, data = self.cli(env=env)
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual(data["base_commit"], self.initial)
        self.assertFalse((self.directory / "foreign-index").exists())

    def test_can_create_from_an_existing_clean_linked_worktree(self):
        result, first = self.cli("--apply")
        self.assertEqual(result.returncode, 0, first)
        result, second = self.cli("--apply", repo=Path(first["worktree"]), task="unit-two")
        self.assertEqual(result.returncode, 0, second)
        self.assertNotEqual(first["worktree"], second["worktree"])
        self.assertEqual(second["base_commit"], self.initial)

    def test_rejects_root_inside_another_registered_worktree(self):
        result, first = self.cli("--apply")
        self.assertEqual(result.returncode, 0, first)
        self.assert_rejected("--root", str(self.repo / "nested tasks"), "--apply",
                             repo=Path(first["worktree"]), task="unit-two", contains="inside")
        self.assertFalse((self.repo / "nested tasks").exists())

    @unittest.skipUnless(os.name == "nt", "Windows short-name aliases only")
    def test_rejects_short_name_alias_inside_source(self):
        import ctypes
        from ctypes import wintypes

        short_path = ctypes.windll.kernel32.GetShortPathNameW
        short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        short_path.restype = wintypes.DWORD
        size = short_path(str(self.repo), None, 0)
        self.assertGreater(size, 0)
        buffer = ctypes.create_unicode_buffer(size)
        self.assertGreater(short_path(str(self.repo), buffer, size), 0)
        alias = Path(buffer.value)
        if alias == self.repo:
            self.skipTest("This volume does not expose a distinct 8.3 alias")
        refs_before = self.git("show-ref").stdout
        self.assert_rejected("--root", str(alias / "nested tasks"), "--apply", contains="inside")
        self.assertFalse((self.repo / "nested tasks").exists())
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("show-ref").stdout, refs_before)


if __name__ == "__main__":
    unittest.main()
