# Contributing

Thank you for improving Deliberate Dev for Claude Code.

Use Python 3.10+ and Git 2.36+. No third-party Python packages are required by the helpers or tests.

```sh
python -m unittest discover -s tests -v
python scripts/workflow.py check examples/plan.json --stage plan
claude plugin validate .
```

Keep changes focused. For helper behavior, add a regression test that fails before the fix and passes afterwards. Do not weaken workflow gates, worktree boundaries, or evidence reporting to make a demonstration pass.

Do not commit credentials, private briefs, local run records, worktrees, caches, or release archives. Explain what changed, why, test results, and security implications in pull requests. For substantial changes, open an issue first. Report vulnerabilities under [SECURITY.md](SECURITY.md).
