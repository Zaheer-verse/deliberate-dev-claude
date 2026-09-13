# Changelog

## 0.1.2

- Compare canonical Windows worktree paths in tests, avoiding false failures from 8.3 temporary-directory aliases.

## 0.1.1

- Reject invalid UTF-8 in local Git configuration before filter inspection can invoke a configured checkout filter.
- Canonicalize the default worktree root so Windows short-path aliases cannot make a valid plan look inconsistent.

## 0.1.0

Initial public release.

- Six Claude Code skills for discovery, planning, tests first, isolated Git worktrees, review, and delivery.
- Standard-library Python helpers for workflow evidence and task worktrees.
- Templates, an example plan, and automated behavioral, integration, and package tests.
