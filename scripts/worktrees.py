#!/usr/bin/env python3
"""Plan and create separate task worktrees without changing the source checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class WorktreeError(Exception):
    """A validation or creation error safe to report to a caller."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, json.dumps({"error": message}) + "\n")


def validate_slug(value: str, label: str) -> str:
    if len(value) > 48 or not SLUG.fullmatch(value) or value in RESERVED:
        raise WorktreeError(
            f"{label} must be a portable slug: 1-48 lowercase letters/digits, start with a letter, "
            "single internal hyphens allowed, and no Windows device names."
        )
    return value


def absolute_path(value: str, label: str) -> Path:
    if not value or any(ord(character) < 32 for character in value):
        raise WorktreeError(f"{label} must be a nonempty path without control characters.")
    path = Path(value).expanduser()
    if ".." in path.parts:
        raise WorktreeError(f"{label} must not contain parent-directory traversal (..).")
    if os.name == "nt":
        for part in path.parts[1:] if path.anchor else path.parts:
            if part.rstrip(" .") != part or ":" in part:
                raise WorktreeError(f"{label} contains a nonportable Windows path component.")
    path = Path(os.path.abspath(path))
    # Reject links before resolve() hides them, then collapse aliases such as
    # NTFS 8.3 names before comparing checkout and destination containment.
    reject_links(path)
    return path.resolve(strict=False)


def reject_links(path: Path) -> None:
    """Check before resolve(), which would hide a symlink or NTFS junction."""
    for component in [*reversed(path.parents), path]:
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise WorktreeError(f"Path uses a symbolic link, junction, or reparse point: {component}")
        if component != path and not stat.S_ISDIR(metadata.st_mode):
            raise WorktreeError(f"Path ancestor is not a directory: {component}")


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


class Git:
    """All Git calls use argv arrays, temporary empty hooks, and a scoped environment."""

    def __init__(self, hooks: str):
        self.executable = shutil.which("git")
        if not self.executable:
            raise WorktreeError("Git was not found on PATH.")
        self.environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        self.environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
        })
        self.configuration = [
            "-c", f"core.hooksPath={hooks}", "-c", "core.fsmonitor=false",
            "-c", f"core.attributesFile={os.devnull}", "-c", "protocol.allow=never",
            "-c", "submodule.recurse=false",
        ]

    def run(self, repo: Path, *args: str, config: list[str] | None = None, check: bool = True):
        try:
            result = subprocess.run(
                [self.executable, "--no-pager", *self.configuration, *(config or []), "-C", str(repo), *args],
                shell=False, capture_output=True,
                env=self.environment,
            )
            # Decode on this thread: Windows subprocess text readers can otherwise
            # raise in a background thread and leave stdout/stderr as None.
            result.stdout = result.stdout.decode("utf-8", errors="strict")
            result.stderr = result.stderr.decode("utf-8", errors="strict")
        except UnicodeError as error:
            # Lossy decoding can change a filter name and leave its real command
            # enabled, or change a path used in containment checks. Fail closed.
            raise WorktreeError("Git output is not valid UTF-8; refusing lossy configuration or path decoding.") from error
        if check and result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or f"Git exited {result.returncode}"
            raise WorktreeError(message)
        return result

    def disable_filters(self, repo: Path, recursive: bool = False) -> list[str]:
        # A clean/smudge/process command can execute on status/checkout even with hooks disabled.
        names = set()
        pending = [repo]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                raise WorktreeError("Recursive submodule paths are unsupported.")
            visited.add(current)
            result = self.run(current, "config", "--null", "--get-regexp", r"^filter\..*\.(smudge|process|clean|required)$", check=False)
            if result.returncode not in (0, 1):
                raise WorktreeError("Cannot inspect repository checkout filters: " + result.stderr.strip())
            for record in result.stdout.split("\0"):
                if not record:
                    continue
                key, separator, _ = record.partition("\n")
                if not separator or not re.fullmatch(r"filter\..+\.(smudge|process|clean|required)", key):
                    raise WorktreeError("Unsupported checkout filter configuration.")
                names.add(key[len("filter."):].rsplit(".", 1)[0])
            if recursive:
                # Parent status delegates to initialized submodules; suppress their filter names too.
                entries = self.run(current, "ls-files", "--stage", "-z").stdout.split("\0")
                for entry in entries:
                    if not entry.startswith("160000 "):
                        continue
                    _, separator, relative = entry.partition("\t")
                    if not separator:
                        raise WorktreeError("Cannot inspect a submodule index entry.")
                    module = absolute_path(str(current / relative), "submodule")
                    if not inside(module, current) or module == current:
                        raise WorktreeError("Submodule path escapes its repository.")
                    reject_links(module)
                    reject_links(module / ".git")
                    if not (module / ".git").exists():
                        continue  # Uninitialized submodule; Git will not run its status.
                    top = absolute_path(self.run(module, "rev-parse", "--show-toplevel").stdout.strip(), "submodule root")
                    if top != module:
                        raise WorktreeError("Initialized submodule must have its own working tree.")
                    pending.append(module)
        overrides = []
        for name in sorted(names):
            for operation in ("clean", "smudge", "process"):
                overrides += ["-c", f"filter.{name}.{operation}="]
            overrides += ["-c", f"filter.{name}.required=false"]
        return overrides

    def commit(self, repo: Path, ref: str, label: str) -> str:
        if not ref or any(ord(character) < 32 for character in ref):
            raise WorktreeError(f"{label} must name an existing commit.")
        result = self.run(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}", check=False)
        commit = result.stdout.strip()
        if result.returncode or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit):
            raise WorktreeError(f"{label} must resolve to an existing commit: {ref}")
        return commit

    def clean(self, repo: Path, config: list[str]) -> None:
        result = self.run(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none", config=config)
        if result.stdout:
            raise WorktreeError(
                "Source repository must be clean, including staged, unstaged, untracked and submodule changes. "
                "Preserve and resolve existing user changes before retrying; the helper will not stash or discard them."
            )


def create(args, git: Git) -> dict:
    run_id = validate_slug(args.run_id, "run-id")
    task_id = validate_slug(args.task_id, "task-id")
    repo = absolute_path(args.repo, "repo")
    reject_links(repo)
    if not repo.is_dir():
        raise WorktreeError(f"Repository directory does not exist: {repo}")
    reject_links(repo / ".git")
    state = git.run(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if state.returncode:
        raise WorktreeError("The supplied directory is not a Git repository.")
    if state.stdout.strip() != "true":
        raise WorktreeError("A non-bare Git repository with a working tree is required.")
    top = absolute_path(git.run(repo, "rev-parse", "--show-toplevel").stdout.strip(), "repository root")
    if repo != top:
        raise WorktreeError(f"--repo must name the repository root: {top}")
    common = absolute_path(git.run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip(), "Git metadata")
    reject_links(common)
    git.commit(repo, "HEAD", "HEAD (an initial commit is required)")
    base = git.commit(repo, args.base, "base commit")
    filters = git.disable_filters(repo, recursive=True)
    git.clean(repo, filters)

    root = absolute_path(args.root, "root") if args.root is not None else repo.parent / (repo.name + "-deliberate-worktrees")
    reject_links(root)
    registered = git.run(repo, "worktree", "list", "--porcelain", "-z").stdout.split("\0")
    existing_roots = []
    for record in registered:
        if record.startswith("worktree "):
            existing_root = absolute_path(record[len("worktree "):], "registered worktree")
            reject_links(existing_root)
            existing_roots.append(existing_root)
    if inside(root, common) or any(inside(root, checkout) for checkout in [repo, *existing_roots]):
        raise WorktreeError("Worktree root must not be inside any registered worktree or Git metadata.")
    if root.exists() and not root.is_dir():
        raise WorktreeError(f"Worktree root is not a directory: {root}")
    destination = root / (run_id + "--" + task_id)
    reject_links(destination)
    if not inside(destination, root) or destination == root:
        raise WorktreeError("Worktree destination escapes its root.")
    if os.path.lexists(destination):
        raise WorktreeError(f"Worktree destination already exists: {destination}")
    branch = f"deliberate/{run_id}/{task_id}"
    existing = git.run(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch, check=False)
    if existing.returncode == 0:
        raise WorktreeError(f"Task branch already exists: {branch}")
    if existing.returncode != 1:
        raise WorktreeError("Cannot check whether task branch exists.")
    plan = {"action": "plan", "repo": str(repo), "root": str(root), "worktree": str(destination),
            "branch": branch, "base_commit": base}
    if not args.apply:
        return plan

    # Repeat mutable-state validation immediately before reserving the destination.
    reject_links(root)
    git.clean(repo, filters)
    try:
        root.mkdir(parents=True, exist_ok=True)
        reject_links(root)
        destination.mkdir(exist_ok=False)
        reject_links(destination)
        # Inspect destination-specific config before any file checkout (includeIf/worktree config may differ).
        git.run(repo, "worktree", "add", "--no-checkout", "-b", branch, "--", str(destination), base, config=filters)
        destination_filters = git.disable_filters(destination)
        git.run(destination, "checkout", "--force", "--no-recurse-submodules", config=destination_filters)
    except (WorktreeError, OSError) as error:
        raise WorktreeError(
            f"Worktree creation did not finish: {error} Inspect destination {destination} and branch {branch}. "
            "Any created directory, branch and registration are preserved; no automatic rollback is performed."
        ) from error
    plan["action"] = "created"
    return plan


def main(argv=None) -> int:
    parser = JsonArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("create", help="Validate a plan; use --apply to create its worktree.")
    command.add_argument("--repo", required=True, help="Exact root of a clean, committed, non-bare repository.")
    command.add_argument("--run-id", required=True)
    command.add_argument("--task-id", required=True)
    command.add_argument("--base", default="HEAD", help="Existing commit-ish, default HEAD.")
    command.add_argument("--root", help="Parent for new worktrees; default is a sibling of the source repository.")
    command.add_argument("--apply", action="store_true", help="Create the validated branch and worktree.")
    args = parser.parse_args(argv)
    try:
        # Never point hooks at an existing user-controlled directory or rely on a platform-specific null path.
        with tempfile.TemporaryDirectory(prefix="deliberate-empty-hooks-") as hooks:
            result = create(args, Git(hooks))
        print(json.dumps(result, indent=2))
        return 0
    except (WorktreeError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
