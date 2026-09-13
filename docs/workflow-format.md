# Workflow evidence format and gates

`scripts/workflow.py` is a Python 3.10+ standard-library CLI. It checks the
consistency and completeness of supplied JSON evidence. It does not execute
recorded commands, inspect Git, contact services, or determine whether statements
are true. Agents must perform the actual discovery, testing and review, and retain
the test output and Git history that support their records.

## CLI

Run from the plugin directory, or use an absolute path to the script:

```text
python scripts/workflow.py init --output workflow.json --title "Project status command"
python scripts/workflow.py check workflow.json --stage plan
python scripts/workflow.py check workflow.json --stage done
```

`init` exclusively creates a new UTF-8 JSON file in an existing parent directory.
It refuses existing files and symlinks, makes no directories, and never overwrites
content. The result contains only an empty discovery form, empty criteria/tasks,
and an empty integration object. Its `valid: true` reports successful creation;
the newly created record will fail both workflow gates until completed.

`check --stage plan` checks discovery, acceptance criteria, task scope, ownership,
coverage and dependencies. It allows missing execution evidence so planning can
finish before worktrees or tests exist. `check --stage done` also checks every
task's isolation, test sequence, final revision and review, plus integration.

Both commands print one JSON result to stdout. `--help` prints ordinary help text.
Check success returns `{"valid": true, "stage": "done", "errors": []}`. A gate
failure returns `valid: false` and an `errors` array of messages with field paths.
Init success includes `created` and `errors`. Errors are never shell commands.

| Exit | Meaning |
| --- | --- |
| 0 | Requested operation succeeded; for `check`, the requested gate passed. |
| 1 | Readable JSON failed the requested workflow gate, including malformed schema. |
| 2 | Invalid arguments, invalid JSON/encoding, oversized input, or file I/O error. |

Inputs must be UTF-8 JSON (an optional UTF-8 BOM is accepted), at most 4 MiB.
Duplicate object keys and nonstandard `NaN`/`Infinity` constants are rejected.
Unknown fields are ignored, allowing additional human-readable evidence, log
paths, reviewer notes, and metadata. They do not satisfy required fields.

## Common types

- **Text:** a nonempty, non-whitespace string.
- **ID:** a letter followed by letters, digits, `_` or `-`, at most 64 characters
  overall. IDs and branches are case-sensitive.
- **Revision:** a full 40- or 64-digit hexadecimal Git object ID. Comparisons ignore
  hex letter case. Symbolic names such as `HEAD`, branch names, and abbreviated
  hashes are rejected.
- **Timestamp:** `YYYY-MM-DDTHH:MM:SS[.fraction]Z` or the same with a numeric
  `+HH:MM`/`-HH:MM` offset. Comparisons account for timezones. Use actual test times.

Do not fill missing evidence with invented values or example hashes. A populated
record is an auditable account of work, not permission to claim it happened.

## Required planning fields

| Field | Type and rule |
| --- | --- |
| `schema_version` | Integer `1`, not a boolean. |
| `title` | Text describing the overall task. |
| `discovery.what` | Object with text `answer` and `source`. |
| `discovery.why` | Object with text `answer` and `source`. |
| `discovery.who` | Object with text `answer` and `source`. |
| `discovery.context` | Array of text notes or references; may be empty if no further context exists. |
| `acceptance_criteria` | Nonempty array of objects with unique `id` and text `description`. |
| `tasks` | Nonempty array of task objects described below. |

Each discovery `source` identifies the user answer, supplied artifact, repository
reference, or explicitly accepted assumption behind the answer. Merely filling
these fields does not prove discovery took place. The discovery skill requires
agents to ask focused questions when the supplied context is insufficient.

Each task needs:

| Field | Type and rule |
| --- | --- |
| `id` | Unique task ID. |
| `title` | Text giving the task a recognizable name. |
| `scope` | Text describing one small, bounded result. |
| `acceptance_criteria` | Nonempty array of known criterion IDs, with no duplicates. |
| `owned_paths` | Nonempty array of distinct relative file/directory paths. |
| `dependencies` | Array of known task IDs, possibly empty, with no duplicates. |

Every acceptance criterion must be mapped to at least one task. Dependencies must
form an acyclic graph; self-dependencies fail. The validator requires a scope but
cannot judge whether it is small enough or whether the criteria reflect the
user's real need. The planning and review skills supply that judgment.

Owned paths use `/` or `\\` separators and cannot contain a drive, leading
separator, `:`, control characters, empty components, `.` or `..`. Omit trailing
directory slashes. Path ownership is descriptive: this CLI does not access these
paths or stop an agent from editing another file. Coordinate overlapping ownership
through dependencies and review.

## Per-task completion evidence

The `done` gate requires all planning fields and these additional task fields:

| Field | Type and rule |
| --- | --- |
| `isolation.branch` | Syntactically valid Git branch name, unique across tasks. |
| `isolation.worktree` | Absolute Windows or POSIX path, unique across tasks. |
| `isolation.base_revision` | Revision from which the task worktree began. Several tasks may share a base. |
| `tdd.red` | Failed test run object, described below. |
| `tdd.green` | Passing test run object, described below. |
| `final_revision` | Revision containing the final task implementation and tests. |
| `review` | Review object bound to `final_revision`. |

Worktree identity is lexical. Separators, trailing separators and case are
normalized for Windows paths; POSIX paths preserve case. Traversal with `..` is
rejected. Windows device namespaces, stream syntax, reserved device names and
components ending in a space/dot are rejected to avoid common aliases. The CLI
does not resolve symlinks, junctions or mounted aliases, or prove a path is a Git
worktree. Verify actual worktree registration with the isolation helper and Git.

Every test run has text `command`, a `timestamp`, a `revision` and an `outcome`.
The command records exactly what was run; its contents remain inert data here.

- `tdd.red.outcome` is `"failed"`; `expected_failure` is the JSON boolean `true`;
  and text `reason` explains the intended missing behavior. A broken environment
  or unrelated failure does not establish a valid red result.
- `tdd.red.revision` identifies committed tests before implementation and differs
  from `final_revision`. Its timestamp must be strictly earlier than green.
- `tdd.green.outcome` is `"passed"` and its revision equals `final_revision`.

Inspect the red failure before implementing. Record actual commands and retain
their output. After any later code or test change, rerun the affected checks and
bind green evidence and review to the new final revision.

All review objects have:

| Field | Type and rule |
| --- | --- |
| `revision` | The exact final revision being reviewed. |
| `correctness` | `"passed"`. |
| `security` | `"passed"`. |
| `quality` | `"passed"`. |
| `findings` | Array, empty if nothing was found. Every finding has unique `id`, text `description`, and `status: "resolved"`. |

An open, waived, or pending finding prevents delivery. The gate checks declared
review results and revision binding; reviewers must read the changes, assess the
test coverage, examine security boundaries and explain their conclusions in the
accompanying evidence. Optional fields such as `notes` and `reviewer` can retain
that detail without affecting the gate.

## Integration and overall completion

The top-level `integration` object is required for `done`:

| Field | Type and rule |
| --- | --- |
| `task_revisions` | Object containing exactly every planned task ID, each mapped to that task's `final_revision`. |
| `revision` | Final integrated Git revision. |
| `tests` | Test run with `outcome: "passed"` and `revision` equal to the integrated revision. |
| `review` | Review object with `revision` equal to the integrated revision. |

The integration test timestamp cannot predate any task's green test run. Run the
combined suite against the integrated result and review conflicts or interactions
between tasks. A passing per-task test does not replace integration testing.

Store final evidence outside the code revision it describes, or in a subsequent
evidence-only commit. Otherwise writing the evidence would change the very Git
hash it claims to describe. When applying more implementation changes, record and
review the resulting revision again before claiming completion.

## Assurance boundary

The validator checks supplied evidence, not its provenance. It cannot prove that
tests ran, a commit exists or is an ancestor of another commit, no implementation
predated red, a working directory was clean, branches were actually isolated, or
that a review was competent. It also cannot establish that the current checkout
matches the recorded integrated revision. Agents and reviewers must verify those
facts against the repository and retained output. Never describe this helper as
tamperproof enforcement or use `valid: true` as a substitute for the workflow.

Python callers may import `validate(data, stage="done")`; it returns a list of
gate errors (`[]` for success). Unknown stages raise `ValueError`. The API validates
JSON-compatible values; the CLI also supplies strict parsing and the input limit.
