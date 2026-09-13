---
name: plan-tasks
description: Split clarified software requirements into small, testable tasks with acceptance coverage, dependencies and file ownership. Use before assigning implementation work or when a requirement changes.
---

# Plan small tasks

Use the clarified brief as the source of scope. If what, why or who is missing, first use [clarify-request](../clarify-request/SKILL.md). Do not turn a guess into a confirmed requirement.

Assign stable acceptance IDs (AC1, AC2, ...) and task IDs (T1, T2, ...). Each task should deliver one independently testable behavior or a necessary enabling contract. Split a task when it needs unrelated behavioral changes, several separate interfaces, or cannot be explained and reviewed on its own. Avoid arbitrary line counts and unsupported time estimates.

For each task, fill [the task template](../deliberate-dev/assets/task.md): purpose, small scope, acceptance IDs, dependencies, owned paths, input/output contracts, test cases and commands, expected failing behavior, worktree assignment, and review criteria. Describe error cases at the same boundary as success cases. Dependencies refer to actual task IDs; reject cycles and missing IDs.

Map every acceptance criterion to at least one task; justify every task using the brief. Two tasks may contribute to a criterion if the integrated behavior is also tested. Plan an integration check for the user's complete scenario, including interactions between independently implemented parts.

Parallelize only tasks that do not rely on each other's unmerged output or modify the same interfaces/files. When paths overlap, assign one owner or add an ordering dependency. Establish shared interfaces before dispatch, and pass reviewed prerequisite revisions to dependents. A worktree made from the original main branch does not automatically contain prerequisite work.

Use [the workflow format](../../docs/workflow-format.md) for the machine-readable run record; [the example plan](../../examples/plan.json) illustrates a fictional small feature. Run the plan gate before starting task worktrees. Present a short user-readable sequence, then proceed under the user's existing authorization. Record changes to the plan and invalidate affected completion evidence when requirements change.
