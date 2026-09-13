---
name: isolated-worktrees
description: Give each planned implementation task a distinct Git worktree and branch, with a pinned dependency baseline and explicit command working directories. Use before tests or code are written for a Deliberate Dev task.
---

# Work in isolation

Each implementation task gets its own Git worktree and branch, including when one agent performs tasks sequentially. A branch alone, a subfolder, or a second agent in the same checkout is not isolation.

Inspect the repository root, existing worktrees, Git status and baseline commit. Keep the user's working changes intact. Do not stash, commit unrelated files, reset, force checkout, or clean as a shortcut. If the baseline contains uncommitted changes needed by the task, ask how to preserve/include them before proceeding; do not silently omit them. For a new project, establish an authorized initial Git baseline before task worktrees are created. If Git or worktrees cannot be used, report the blocker instead of substituting a shared directory.

Use [worktrees.py](../../scripts/worktrees.py) to prepare a validated dry-run plan:

```text
python <plugin-root>/scripts/worktrees.py create --repo <repo-root> --run-id <run-slug> --task-id <task-slug> --base <reviewed-base>
```

Quote actual absolute paths. Read [the CLI reference](../../docs/worktrees-cli.md) for accepted slugs and path rules. The default only prints a plan. Inspect its repo, branch, worktree and base_commit, then repeat with `--apply` under the existing authorization for local development. Record the returned absolute worktree, unique branch and pinned base revision in the run record.

The default destination is a sibling worktree directory; it must be writable. If the host sandbox permits only certain locations, choose an allowed explicit `--root` outside the source checkout or report the exact constraint. Do not bypass the sandbox. The helper preserves existing branches and destinations and does not clean them up.

For tasks with dependencies, first integrate the reviewed dependency commits into a clean integration branch/worktree, then use its commit as `--base`. Verify required interfaces are present before writing tests. Independent tasks can use the same pinned baseline. Resolve overlapping ownership before dispatch.

Tell every subagent its task, owned paths and absolute worktree path. Require the working directory explicitly on **every** shell/test/Git/edit command; shared host defaults may still point at another checkout. Keep separate build outputs and temp files. Allocate distinct ports or isolated services when tests need them, and avoid sharing a mutable test database.

On completion, return the final commit, test results and review findings to the coordinator. Keep the task worktree available for review. Integration and cleanup are separate operations: the helper never merges or removes anything. Only integrate reviewed commits, and remove a worktree only when authorized and after checking for uncommitted/unmerged work. Never use recursive filesystem deletion as worktree cleanup.
