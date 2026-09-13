---
name: review-delivery
description: Review implemented task and integrated revisions for correctness, security and quality, using test evidence before marking delivery complete. Use after tests pass or when reviewed code changes.
---

# Review before delivery

Review the actual diff, acceptance criteria and test output for the named final revision. Use [the review template](../deliberate-dev/assets/review.md). A passing test suite is an input to review, not a substitute for it.

Perform these three passes on every task:

- **Correctness / QA:** acceptance coverage, edge and error cases, regressions, relevant red-before-green evidence, and tests that could catch the implementation being wrong. Confirm worktree and revision identities against actual Git state.
- **Security:** changed trust boundaries, authorization, untrusted input, injection, secrets in logs, unsafe filesystem/shell operations, dependency changes and sensitive data handling. Test a relevant abuse case when the change introduces such a boundary. Record a reason if an area is not applicable; avoid unrelated hardening scope.
- **Quality / architecture:** clear ownership/interfaces, maintainability, complexity, compatibility, failure handling, and whether the diff remains within the brief. Inspect conflicts and generated code just as carefully as handwritten code.

When subagents are available, request an independent reviewer with the brief, task, final revision, diff and evidence. Keep the reviewer read-only unless explicitly assigning a fix to its own task worktree. Without subagents, perform separate self-review passes and state that limitation. Never claim several people or independent agents reviewed work when they did not.

For each finding record an ID, severity, concrete file/location, reproducible issue, impact and required fix. Keep findings open until the fix has relevant test evidence and has been reviewed at the updated revision. All three passes must pass and all findings must be resolved before the task is done. Do not set a review status to passed merely to satisfy the JSON validator. If the user changes scope or accepts a limitation, update the requirement and affected tasks transparently; never relabel a failing required behavior as success.

After task reviews, integrate reviewed revisions in dependency order and rerun the combined acceptance/regression checks. Re-review the final integrated revision for correctness, security and quality. New code from conflict resolution requires relevant tests and review. If any task revision changes, update integration evidence as well.

The coordinator checks [workflow.py](../../scripts/workflow.py) with `check <run.json> --stage done`, following [the evidence format](../../docs/workflow-format.md). Compare the record with actual commands, outputs and commits first: the helper only validates supplied evidence, not its authenticity. Missing evidence or failed checks keep completion blocked.

The final report states the result, actual checks and review status, relevant branch/worktree or file locations, and material limitations. Do not claim deployment, external publication, or cleanup unless performed and authorized. Overall completion requires every task and the integrated result to pass.
