# Worktree helper

`scripts/worktrees.py` plans and creates one separate Git worktree per task. It
uses Python 3.10+ and Git 2.36+ (including `worktree list --porcelain -z`).
It has no third-party Python dependencies and does not change
global Git configuration.

```console
python scripts/worktrees.py create --repo "/absolute/source repo" --run-id feature-one --task-id unit-one
python scripts/worktrees.py create --repo "/absolute/source repo" --run-id feature-one --task-id unit-one --apply
```

The first command validates the complete plan and prints JSON. The second
validates again and creates the worktree. Quote paths with spaces. Both IDs
must have 1–48 lowercase letters or digits, start with a letter, and may use
single internal hyphens. Windows device names such as `con` and `com1` are
rejected.

Optional arguments:

| Argument | Meaning |
| --- | --- |
| `--base COMMITISH` | Existing commit or commit-ish for the task. Defaults to `HEAD` and is resolved to a full commit ID before creation. |
| `--root PATH` | Parent of task worktrees. Defaults to `<source-parent>/<source-name>-deliberate-worktrees`. |
| `--apply` | Create the new branch and worktree. Without this flag the source checkout, index, refs, and destination are unchanged. Temporary empty hook directories are created and removed outside the repository. |

A successful dry run returns exit code `0` with a JSON object on stdout:

```json
{
  "action": "plan",
  "repo": "/workspace/source repo",
  "root": "/workspace/source repo-deliberate-worktrees",
  "worktree": "/workspace/source repo-deliberate-worktrees/feature-one--unit-one",
  "branch": "deliberate/feature-one/unit-one",
  "base_commit": "0123456789012345678901234567890123456789"
}
```

After creation, `action` is `created`; the other fields use the same schema.
All paths are absolute and use the current operating system's path syntax.
Failures return exit code `2` with `{"error": "explanation"}` on stderr.
`--help` uses ordinary help text. Missing Python or Git process startup can
also fail before the helper runs.

## Agent integration

Run each task agent with its current working directory set to the returned
`worktree` path. Merely creating a worktree does not move an existing agent or
shell into it. Give the task agent its task definition and repository
instructions; require it to write and run a failing test before implementation,
then run the passing tests and record correctness, security and quality review.

The orchestrator chooses the dependency base. Independent tasks may start from
the same recorded commit. A dependent task must start from a commit that
contains its reviewed prerequisites, using `--base`; this helper does not
integrate changes or decide whether dependencies are finished. Do not run task
agents concurrently in the source checkout. Worktrees share Git metadata, so
the orchestrator must coordinate branch operations and integration.

Use a new task ID for each task. An existing task directory or branch is an
error, including an empty directory. To resume a previously created task,
inspect its recorded path and Git state and continue in that worktree; the
helper intentionally does not reuse or overwrite it. It has no remove, merge,
reset, clean, or stash command.

## Validation and execution boundaries

The helper requires the exact root of a non-bare Git repository with an initial
commit. A clean linked worktree is also a valid source. It rejects staged,
unstaged, untracked and detected submodule changes and preserves them. Ignored
files are not copied into the task checkout. Commit a shared baseline only when
authorized; never discard a user's work to satisfy the clean-source check.

Paths containing `..`, symbolic links, junctions, or other Windows reparse
points are rejected before canonicalizing existing path prefixes, including
Windows short-name aliases. The destination parent must be outside every registered
worktree and the common Git metadata directory. Destination components are
derived only from validated IDs. The helper checks existing ancestors before
normalizing their meaning, reserves the destination with an exclusive directory
creation, and lets Git reject a competing branch creation.

Every Git command uses a subprocess argument array with `shell=False`.
Git output must decode as UTF-8 without replacement. Unsupported byte sequences
cause a JSON error before their paths or filter names can be used incorrectly.
Commit-ish validation uses `--end-of-options`; no recorded or user-supplied
command string is executed. Inherited `GIT_*` variables are cleared and global
and system Git configuration is disabled for these calls. Hooks point to a
new, empty temporary directory; fsmonitor hooks are disabled. Configured
checkout/clean filters are disabled for the source status checks and the new
worktree's checkout, including filters in initialized submodules and filters
configured specifically for the new worktree. Network protocols and lazy fetching are disabled; required objects
must already be local. Submodules are not initialized.

Filter suppression means Git LFS objects remain pointers and other smudge
transformations do not run. Filter-normalized source files may fail the clean
check when their on-disk contents differ from the stored form. Handle any
necessary trusted setup explicitly in the task worktree. These per-command
settings do not apply automatically to Git commands the agent runs later.

This helper is an isolation aid, not a sandbox against other local processes
or a guarantee that repository content is safe to execute. Concurrent hostile
filesystem changes can race path checks. If creation fails after reservation,
the error identifies the destination and branch; any directory, branch or Git
registration already created is left for inspection. There is no automatic
rollback or deletion. Review repository instructions and code before running
its tools, dependencies or tests.

## Verification

```console
python -m unittest discover -s tests -p test_worktrees.py
```

The integration tests use temporary Git repositories and local test identities.
They check dry-run preservation, worktree isolation with spaces in paths,
explicit bases, dirty-source preservation, invalid IDs and repositories,
existing destinations and branches, symlink/junction rejection, hook and filter
suppression, and inherited Git environment redirection. No tests edit a user's
global Git configuration.
