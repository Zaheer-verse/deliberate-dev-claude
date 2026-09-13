---
name: test-first
description: Implement a planned software task using failing behavioral tests before implementation, then passing tests and regression checks. Use inside an assigned task worktree for Deliberate Dev coding or bug fixes.
---

# Test before implementation

Start in the task's assigned [isolated worktree](../isolated-worktrees/SKILL.md), with clarified acceptance criteria and the reviewed dependency baseline. Set that absolute path as the working directory of every command. Inspect the existing test conventions and run the relevant baseline before edits. If it already fails, distinguish the existing failure from the new task; repair or report the prerequisite instead of using it as the task's red result.

1. **Red:** write a test of the required externally observable behavior before writing its implementation. For a bug, reproduce the failure. Include meaningful negative cases. Run it and inspect the output. It must fail because the requested behavior is absent or wrong. A missing test runner, syntax error, network outage or unrelated failure does not satisfy this step. If a test passes immediately, it does not demonstrate missing behavior; refine the case or conclude the behavior already exists.
2. Preserve the test-only state as a local commit when authorized by the development task. Stage only task-owned test files; never sweep up unrelated changes. Record task ID, working directory, exact command, exit code, timestamp with timezone, test identity, relevant output, the test-only revision, and why this is the expected failure. Redact secrets in logs.
3. **Green:** implement the smallest correct change in owned paths to satisfy the test. Run the same test, then relevant regressions. Do not delete assertions, skip the test or weaken its expectation to obtain a pass. If the requirement changes, update the brief and tests explicitly.
4. **Refactor:** improve structure only while preserving behavior. Rerun affected tests after changes. Commit the final task state, run the final checks from that revision and record the passing command, output, exit code, timestamp and revision. Repeat red/green for additional behaviors before their implementation; retain per-cycle evidence in the task report. The run JSON summarizes the task's initial relevant red and final green evidence.

Use suitable tests: unit tests for logic, integration tests for boundaries, and browser/API checks for user flows where needed. A documentation/configuration task still needs a meaningful acceptance check written before the edit, such as parsing a config or validating a referenced file. Do not add tests that merely repeat the implementation's constants or prose.

Run existing project-required checks in addition to task tests. Do not report unexecuted checks as passed. If tests cannot run, preserve the authored tests and explain the exact blocker; this strict workflow cannot mark the task complete. Hand the final revision and real evidence to [review-delivery](../review-delivery/SKILL.md). Any later code change invalidates that revision's passing/review evidence until checks are rerun.
