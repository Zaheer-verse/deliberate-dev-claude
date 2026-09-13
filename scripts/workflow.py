#!/usr/bin/env python3
"""Validate recorded workflow evidence without running commands or inspecting Git."""

import argparse
from datetime import datetime
import json
import ntpath
from pathlib import Path, PureWindowsPath
import posixpath
import re
import sys


MAX_INPUT_BYTES = 4 * 1024 * 1024
ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
REVISION_PATTERN = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z"
)


def skeleton(title):
    """Return an empty planning record; no test, review or execution is claimed."""
    return {
        "schema_version": 1,
        "title": title,
        "discovery": {
            "what": {"answer": "", "source": ""},
            "why": {"answer": "", "source": ""},
            "who": {"answer": "", "source": ""},
            "context": [],
        },
        "acceptance_criteria": [],
        "tasks": [],
        "integration": {},
    }


def valid_branch(value):
    """Check the relevant git-check-ref-format --branch syntax without executing Git."""
    if (not value or value in ("@", "HEAD") or value.startswith("-") or value.endswith(".")
            or ".." in value or "@{" in value or "//" in value):
        return False
    if any(ord(char) < 33 or ord(char) == 127 or char in "~^:?*[\\" for char in value):
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock")
               for part in value.split("/"))


def owned_path_key(value):
    normalized = value.replace("\\", "/")
    if (not normalized or normalized.startswith("/") or ":" in normalized
            or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
            or any(part in ("", ".", "..") for part in normalized.split("/"))):
        return None
    return normalized


def worktree_key(value):
    """Normalize lexical path identity; intentionally does not access the filesystem."""
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    windows_path = PureWindowsPath(value)
    if windows_path.is_absolute():
        if ".." in value.replace("\\", "/").split("/"):
            return None
        # Refuse device namespaces, streams, reserved names and trailing dot/space
        # aliases, which otherwise defeat distinct lexical worktree identities.
        if value.replace("\\", "/").startswith(("//?/", "//./")):
            return None
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT")
                        for number in "123456789\u00b9\u00b2\u00b3")
        for part in windows_path.parts[1:]:
            if (part.endswith((".", " ")) or any(char in '<>:"|?*' for char in part)
                    or part.split(".")[0].upper() in reserved):
                return None
        return ("windows", ntpath.normcase(ntpath.normpath(value)))
    if value.startswith("/") and not value.startswith("//"):
        if ".." in value.split("/"):
            return None
        return ("posix", posixpath.normpath(value))
    return None


class _Validator:
    def __init__(self):
        self.errors = []

    def error(self, where, message):
        self.errors.append(f"{where}: {message}")

    def obj(self, value, where):
        if not isinstance(value, dict):
            self.error(where, "must be an object")
            return {}
        return value

    def array(self, value, where, nonempty=False):
        if not isinstance(value, list):
            self.error(where, "must be an array")
            return []
        if nonempty and not value:
            self.error(where, "must not be empty")
        return value

    def string(self, value, where):
        if not isinstance(value, str) or not value.strip():
            self.error(where, "must be a nonempty string")
            return ""
        return value

    def identifier(self, value, where):
        value = self.string(value, where)
        if value and not ID_PATTERN.fullmatch(value):
            self.error(where, "must start with a letter and contain at most 64 letters, digits, '_' or '-'")
            return ""
        return value

    def revision(self, value, where):
        value = self.string(value, where)
        if value and not REVISION_PATTERN.fullmatch(value):
            self.error(where, "must be a full 40- or 64-digit hexadecimal Git revision")
            return ""
        return value.lower()

    def timestamp(self, value, where):
        value = self.string(value, where)
        if value:
            try:
                if not TIMESTAMP_PATTERN.fullmatch(value):
                    raise ValueError("invalid format")
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if result.tzinfo is None or result.utcoffset() is None:
                    raise ValueError("missing timezone")
                return result
            except (ValueError, OverflowError):
                self.error(where, "must be an ISO 8601 timestamp with seconds and a timezone")
        return None

    def identifiers(self, value, where, nonempty=False):
        result = []
        seen = set()
        for index, item in enumerate(self.array(value, where, nonempty)):
            identifier = self.identifier(item, f"{where}[{index}]")
            if identifier:
                if identifier in seen:
                    self.error(where, f"duplicate ID {identifier!r}")
                seen.add(identifier)
                result.append(identifier)
        return result

    def test_run(self, value, where, outcome, expected_revision=None):
        value = self.obj(value, where)
        self.string(value.get("command"), f"{where}.command")
        if value.get("outcome") != outcome:
            self.error(f"{where}.outcome", f"must be {outcome!r}")
        revision = self.revision(value.get("revision"), f"{where}.revision")
        timestamp = self.timestamp(value.get("timestamp"), f"{where}.timestamp")
        if expected_revision and revision != expected_revision:
            self.error(f"{where}.revision", "must equal the final revision being validated")
        if outcome == "failed":
            self.string(value.get("reason"), f"{where}.reason")
            if value.get("expected_failure") is not True:
                self.error(f"{where}.expected_failure", "must be true for the intended missing behavior")
        return revision, timestamp

    def review(self, value, where, expected_revision):
        value = self.obj(value, where)
        revision = self.revision(value.get("revision"), f"{where}.revision")
        if expected_revision and revision != expected_revision:
            self.error(f"{where}.revision", "must equal the final revision being validated")
        for category in ("correctness", "security", "quality"):
            if value.get(category) != "passed":
                self.error(f"{where}.{category}", "must be 'passed'")
        seen = set()
        for index, item in enumerate(self.array(value.get("findings"), f"{where}.findings")):
            location = f"{where}.findings[{index}]"
            item = self.obj(item, location)
            identifier = self.identifier(item.get("id"), f"{location}.id")
            if identifier in seen:
                self.error(location, f"duplicate finding ID {identifier!r}")
            seen.add(identifier)
            self.string(item.get("description"), f"{location}.description")
            if item.get("status") != "resolved":
                self.error(f"{location}.status", "must be 'resolved'; open or waived findings block delivery")

    def run(self, data, stage):
        data = self.obj(data, "$record")
        if type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
            self.error("schema_version", "must be integer 1")
        self.string(data.get("title"), "title")
        discovery = self.obj(data.get("discovery"), "discovery")
        for question in ("what", "why", "who"):
            where = f"discovery.{question}"
            answer = self.obj(discovery.get(question), where)
            self.string(answer.get("answer"), f"{where}.answer")
            self.string(answer.get("source"), f"{where}.source")
        for index, context in enumerate(self.array(discovery.get("context"), "discovery.context")):
            self.string(context, f"discovery.context[{index}]")

        criteria = set()
        for index, item in enumerate(self.array(data.get("acceptance_criteria"), "acceptance_criteria", True)):
            where = f"acceptance_criteria[{index}]"
            item = self.obj(item, where)
            identifier = self.identifier(item.get("id"), f"{where}.id")
            if identifier in criteria:
                self.error(where, f"duplicate criterion ID {identifier!r}")
            if identifier:
                criteria.add(identifier)
            self.string(item.get("description"), f"{where}.description")

        graph, final_revisions, covered = {}, {}, set()
        branches, worktrees, green_times = set(), set(), []
        for index, item in enumerate(self.array(data.get("tasks"), "tasks", True)):
            where = f"tasks[{index}]"
            task = self.obj(item, where)
            identifier = self.identifier(task.get("id"), f"{where}.id")
            if identifier in graph:
                self.error(f"{where}.id", f"duplicate task ID {identifier!r}")
            self.string(task.get("title"), f"{where}.title")
            self.string(task.get("scope"), f"{where}.scope")
            mapped = self.identifiers(task.get("acceptance_criteria"), f"{where}.acceptance_criteria", True)
            covered.update(mapped)
            for criterion in mapped:
                if criterion not in criteria:
                    self.error(f"{where}.acceptance_criteria", f"unknown criterion {criterion!r}")
            seen_paths = set()
            for path_index, path in enumerate(self.array(task.get("owned_paths"), f"{where}.owned_paths", True)):
                location = f"{where}.owned_paths[{path_index}]"
                path = self.string(path, location)
                key = owned_path_key(path) if path else None
                if key is None:
                    self.error(location, "must be a relative file or directory path without traversal or empty components")
                elif key in seen_paths:
                    self.error(location, "duplicate owned path")
                else:
                    seen_paths.add(key)
            dependencies = self.identifiers(task.get("dependencies"), f"{where}.dependencies")
            if identifier:
                graph[identifier] = dependencies

            if stage == "done":
                isolation = self.obj(task.get("isolation"), f"{where}.isolation")
                branch = self.string(isolation.get("branch"), f"{where}.isolation.branch")
                if branch and not valid_branch(branch):
                    self.error(f"{where}.isolation.branch", "must be a valid Git branch name")
                if branch in branches:
                    self.error(f"{where}.isolation.branch", "must be unique across tasks")
                branches.add(branch)
                path = self.string(isolation.get("worktree"), f"{where}.isolation.worktree")
                key = worktree_key(path) if path else None
                if key is None:
                    self.error(f"{where}.isolation.worktree", "must be an absolute Windows or POSIX path without '..'")
                elif key in worktrees:
                    self.error(f"{where}.isolation.worktree", "must be unique across tasks")
                else:
                    worktrees.add(key)
                self.revision(isolation.get("base_revision"), f"{where}.isolation.base_revision")
                final = self.revision(task.get("final_revision"), f"{where}.final_revision")
                if identifier:
                    final_revisions[identifier] = final
                tdd = self.obj(task.get("tdd"), f"{where}.tdd")
                red_revision, red_time = self.test_run(tdd.get("red"), f"{where}.tdd.red", "failed")
                _, green_time = self.test_run(tdd.get("green"), f"{where}.tdd.green", "passed", final)
                if red_revision and final and red_revision == final:
                    self.error(f"{where}.tdd.red.revision", "must differ from the final implementation revision")
                if red_time is not None and green_time is not None and red_time >= green_time:
                    self.error(f"{where}.tdd", "the expected red failure must occur strictly before green")
                if green_time is not None:
                    green_times.append(green_time)
                self.review(task.get("review"), f"{where}.review", final)

        for missing in sorted(criteria - covered):
            self.error("tasks", f"acceptance criterion {missing!r} is not covered")
        self.check_graph(graph)
        if stage == "done":
            integration = self.obj(data.get("integration"), "integration")
            revision = self.revision(integration.get("revision"), "integration.revision")
            actual = self.obj(integration.get("task_revisions"), "integration.task_revisions")
            if set(actual) != set(final_revisions):
                self.error("integration.task_revisions", "must contain exactly the task IDs in the plan")
            for identifier, value in actual.items():
                mapped_revision = self.revision(value, f"integration.task_revisions.{identifier}")
                if identifier in final_revisions and mapped_revision != final_revisions[identifier]:
                    self.error(f"integration.task_revisions.{identifier}", "must equal this task's final revision")
            _, integration_time = self.test_run(integration.get("tests"), "integration.tests", "passed", revision)
            if integration_time is not None and any(integration_time < time for time in green_times):
                self.error("integration.tests.timestamp", "must not predate any task's green test run")
            self.review(integration.get("review"), "integration.review", revision)
        return self.errors

    def check_graph(self, graph):
        # Kahn's algorithm avoids recursion limits on long but valid task chains.
        indegree = dict.fromkeys(graph, 0)
        dependents = {identifier: [] for identifier in graph}
        for identifier, dependencies in graph.items():
            for dependency in dependencies:
                if dependency not in graph:
                    self.error(f"tasks.{identifier}.dependencies", f"unknown task {dependency!r}")
                else:
                    indegree[identifier] += 1
                    dependents[dependency].append(identifier)
        ready = [identifier for identifier, count in indegree.items() if count == 0]
        visited = 0
        while ready:
            identifier = ready.pop()
            visited += 1
            for dependent in dependents[identifier]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if visited != len(graph):
            self.error("tasks.dependencies", "must form an acyclic graph without self-dependencies")


def validate(data, stage="done"):
    """Return gate failures; valid data returns []. Unknown stages raise ValueError."""
    if stage not in ("plan", "done"):
        raise ValueError("stage must be 'plan' or 'done'")
    return _Validator().run(data, stage)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"nonstandard JSON constant: {value}")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create an empty JSON record without overwriting")
    init.add_argument("--output", required=True)
    init.add_argument("--title", required=True)
    check = commands.add_parser("check", help="validate supplied evidence, without executing it")
    check.add_argument("path")
    check.add_argument("--stage", choices=("plan", "done"), required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "init":
            if not args.title.strip():
                raise ValueError("title must be a nonempty string")
            output = Path(args.output)
            # Exclusive create also refuses existing symlinks; do not mkdir or overwrite.
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(skeleton(args.title), stream, indent=2)
                stream.write("\n")
            result = {"valid": True, "created": str(output), "errors": []}
            code = 0
        else:
            with Path(args.path).open("rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("input exceeds the 4 MiB size limit")
            data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
            errors = validate(data, args.stage)
            result = {"valid": not errors, "stage": args.stage, "errors": errors}
            code = 1 if errors else 0
    except (OSError, ValueError, RecursionError) as error:
        result = {"valid": False, "errors": [str(error)]}
        code = 2
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
