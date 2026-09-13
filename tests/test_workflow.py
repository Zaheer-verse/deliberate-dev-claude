"""Behavior and CLI tests for the supplied-evidence workflow gate."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("workflow", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


def review(revision):
    return {
        "revision": revision,
        "correctness": "passed",
        "security": "passed",
        "quality": "passed",
        "findings": [],
    }


def valid_record():
    """Synthetic test fixture; these hashes are never presented as real evidence."""
    red, final, integrated = "a" * 40, "b" * 40, "c" * 40
    return {
        "schema_version": 1,
        "title": "Show the project status",
        "discovery": {
            "what": {"answer": "Show project status", "source": "User request"},
            "why": {"answer": "Find blocked work", "source": "User clarification"},
            "who": {"answer": "Project maintainers", "source": "User clarification"},
            "context": ["Existing local command-line application"],
        },
        "acceptance_criteria": [
            {"id": "AC1", "description": "Report blocked tasks accurately"}
        ],
        "tasks": [{
            "id": "T1",
            "title": "Add status calculation",
            "scope": "Calculate status from the existing task records",
            "acceptance_criteria": ["AC1"],
            "owned_paths": ["src/status.py", "tests/test_status.py"],
            "dependencies": [],
            "isolation": {
                "branch": "feature/status",
                "worktree": "/tmp/project-worktrees/T1",
                "base_revision": "d" * 40,
            },
            "tdd": {
                "red": {
                    "command": "python -m unittest tests.test_status",
                    "outcome": "failed",
                    "reason": "Missing status calculation behavior",
                    "expected_failure": True,
                    "timestamp": "2026-09-12T08:00:00Z",
                    "revision": red,
                },
                "green": {
                    "command": "python -m unittest tests.test_status",
                    "outcome": "passed",
                    "timestamp": "2026-09-12T08:01:00+00:00",
                    "revision": final,
                },
            },
            "final_revision": final,
            "review": review(final),
        }],
        "integration": {
            "task_revisions": {"T1": final},
            "revision": integrated,
            "tests": {
                "command": "python -m unittest discover -s tests",
                "outcome": "passed",
                "timestamp": "2026-09-12T08:03:00Z",
                "revision": integrated,
            },
            "review": review(integrated),
        },
    }


class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        self.record = valid_record()

    def errors(self, stage="done"):
        return workflow.validate(self.record, stage)

    def test_complete_record_passes_both_gates(self):
        self.assertEqual([], self.errors("plan"))
        self.assertEqual([], self.errors("done"))

    def test_plan_does_not_require_execution_evidence(self):
        task = self.record["tasks"][0]
        for field in ("isolation", "tdd", "final_revision", "review"):
            del task[field]
        del self.record["integration"]
        self.assertEqual([], self.errors("plan"))
        self.assertTrue(self.errors("done"))

    def test_each_discovery_answer_and_source_is_required(self):
        for question in ("what", "why", "who"):
            for field in ("answer", "source"):
                with self.subTest(question=question, field=field):
                    self.record = valid_record()
                    self.record["discovery"][question][field] = "  "
                    self.assertTrue(self.errors("plan"))

    def test_discovery_context_must_be_a_string_array(self):
        self.record["discovery"]["context"] = {"unexpected": True}
        self.assertTrue(self.errors("plan"))
        self.record["discovery"]["context"] = []
        self.assertEqual([], self.errors("plan"))

    def test_criteria_cannot_be_empty_duplicate_or_uncovered(self):
        for criteria in ([], [self.record["acceptance_criteria"][0]] * 2,
                         [{"id": "AC2", "description": "Other behavior"}]):
            with self.subTest(criteria=criteria):
                self.record = valid_record()
                self.record["acceptance_criteria"] = criteria
                self.assertTrue(self.errors("plan"))

    def test_each_task_must_map_at_least_one_known_criterion(self):
        for mapping in ([], ["AC99"], ["AC1", "AC1"]):
            with self.subTest(mapping=mapping):
                self.record["tasks"][0]["acceptance_criteria"] = mapping
                self.assertTrue(self.errors("plan"))

    def test_tasks_require_scope_and_owned_paths(self):
        for field in ("title", "scope", "owned_paths"):
            with self.subTest(field=field):
                self.record = valid_record()
                self.record["tasks"][0][field] = [] if field == "owned_paths" else ""
                self.assertTrue(self.errors("plan"))

    def test_tasks_cannot_be_empty_or_have_duplicate_ids(self):
        self.record["tasks"] *= 2
        self.assertTrue(self.errors("plan"))
        self.record["tasks"] = []
        self.assertTrue(self.errors("plan"))

    def test_owned_paths_are_relative_and_cannot_escape(self):
        for path in ("../outside.py", "/outside.py", "C:\\outside.py",
                     "src/../../outside.py", "\\\\server\\share", "src/file:stream",
                     "src\x00file", "."):
            with self.subTest(path=path):
                self.record["tasks"][0]["owned_paths"] = [path]
                self.assertTrue(self.errors("plan"))

    def test_dependency_graph_rejects_unknown_self_duplicate_and_cycles(self):
        second = copy.deepcopy(self.record["tasks"][0])
        second["id"] = "T2"
        self.record["tasks"].append(second)
        for dependencies in (["missing"], ["T1"], ["T2", "T2"]):
            with self.subTest(dependencies=dependencies):
                self.record["tasks"][0]["dependencies"] = dependencies
                self.assertTrue(self.errors("plan"))
        self.record["tasks"][0]["dependencies"] = ["T2"]
        second["dependencies"] = ["T1"]
        self.assertTrue(self.errors("plan"))
        second["dependencies"] = []
        self.assertEqual([], self.errors("plan"))

    def test_isolation_requires_distinct_branches_and_worktrees(self):
        second = copy.deepcopy(self.record["tasks"][0])
        second["id"] = "T2"
        second["isolation"]["branch"] = "feature/other"
        self.record["tasks"].append(second)
        self.record["integration"]["task_revisions"]["T2"] = second["final_revision"]
        self.assertTrue(self.errors())
        second["isolation"]["worktree"] = "/tmp/project-worktrees/T2"
        self.assertEqual([], self.errors())
        second["isolation"]["branch"] = self.record["tasks"][0]["isolation"]["branch"]
        self.assertTrue(self.errors())

    def test_windows_worktree_aliases_are_duplicate(self):
        self.record["tasks"][0]["isolation"]["worktree"] = "C:\\Worktrees\\T1"
        second = copy.deepcopy(self.record["tasks"][0])
        second["id"] = "T2"
        second["isolation"]["branch"] = "feature/other"
        second["isolation"]["worktree"] = "c:/worktrees/t1/"
        self.record["tasks"].append(second)
        self.record["integration"]["task_revisions"]["T2"] = second["final_revision"]
        self.assertTrue(self.errors())

    def test_isolation_worktree_must_be_absolute_and_branch_valid(self):
        for field, value in (("worktree", "../T1"), ("branch", "main..feature"),
                             ("branch", "-feature"), ("base_revision", "HEAD")):
            with self.subTest(field=field, value=value):
                self.record = valid_record()
                self.record["tasks"][0]["isolation"][field] = value
                self.assertTrue(self.errors())

    def test_windows_worktree_paths_reject_ambiguous_filesystem_aliases(self):
        for path in ("C:/Worktrees/T1.", "C:/Worktrees/T1 ",
                     "C:/Worktrees/NUL", "C:/Worktrees/file:stream",
                     "\\\\?\\C:\\Worktrees\\T1"):
            with self.subTest(path=path):
                self.record["tasks"][0]["isolation"]["worktree"] = path
                self.assertTrue(self.errors())

    def test_isolation_rejects_git_reserved_head_branch(self):
        self.record["tasks"][0]["isolation"]["branch"] = "HEAD"
        self.assertTrue(any(error.startswith("tasks[0].isolation.branch:")
                            for error in self.errors()))
        self.record["tasks"][0]["isolation"]["branch"] = "feature/HEAD"
        self.assertEqual([], self.errors())

    def test_red_requires_failed_expected_test_with_reason(self):
        for field, value in (("outcome", "passed"), ("expected_failure", False),
                             ("expected_failure", 1), ("reason", ""), ("command", "")):
            with self.subTest(field=field):
                self.record = valid_record()
                self.record["tasks"][0]["tdd"]["red"][field] = value
                self.assertTrue(self.errors())

    def test_red_must_precede_green_with_timezone_aware_timestamps(self):
        for timestamp in ("2026-09-12T08:01:00Z", "2026-09-12T09:00:00Z",
                          "2026-09-12T08:00:00", "invalid", 4):
            with self.subTest(timestamp=timestamp):
                self.record["tasks"][0]["tdd"]["red"]["timestamp"] = timestamp
                self.assertTrue(self.errors())

    def test_red_and_final_revisions_must_differ(self):
        self.record["tasks"][0]["tdd"]["red"]["revision"] = "b" * 40
        self.assertTrue(self.errors())

    def test_timestamp_offsets_reject_out_of_range_minutes(self):
        for field in ("red", "green", "integration"):
            for offset in ("+00:60", "+01:99", "-00:60", "-01:99"):
                with self.subTest(field=field, offset=offset):
                    self.record = valid_record()
                    if field == "integration":
                        target = self.record["integration"]["tests"]
                        where = "integration.tests.timestamp:"
                    else:
                        target = self.record["tasks"][0]["tdd"][field]
                        where = f"tasks[0].tdd.{field}.timestamp:"
                    target["timestamp"] = "2026-09-12T08:00:00" + offset
                    self.assertTrue(any(error.startswith(where) and "ISO 8601" in error
                                        for error in self.errors()))

    def test_valid_timezone_offsets_preserve_test_order(self):
        for offset in ("+00:59", "-00:59", "+05:30", "-03:30"):
            with self.subTest(offset=offset):
                self.record = valid_record()
                self.record["tasks"][0]["tdd"]["red"]["timestamp"] = "2026-09-12T08:00:00" + offset
                self.record["tasks"][0]["tdd"]["green"]["timestamp"] = "2026-09-12T08:01:00" + offset
                self.record["integration"]["tests"]["timestamp"] = "2026-09-12T08:03:00" + offset
                self.assertEqual([], self.errors())

    def test_green_and_review_bind_to_final_revision(self):
        for field in ("green", "review"):
            with self.subTest(field=field):
                self.record = valid_record()
                task = self.record["tasks"][0]
                target = task["tdd"]["green"] if field == "green" else task["review"]
                target["revision"] = "e" * 40
                self.assertTrue(self.errors())

    def test_green_tests_must_pass(self):
        self.record["tasks"][0]["tdd"]["green"]["outcome"] = "failed"
        self.assertTrue(self.errors())

    def test_reviews_require_all_three_passes_and_resolved_findings(self):
        for category in ("correctness", "security", "quality"):
            with self.subTest(category=category):
                self.record = valid_record()
                self.record["tasks"][0]["review"][category] = "pending"
                self.assertTrue(self.errors())
        self.record = valid_record()
        findings = [{"id": "F1", "description": "Incorrect edge case", "status": "open"}]
        self.record["tasks"][0]["review"]["findings"] = findings
        self.assertTrue(self.errors())
        findings[0]["status"] = "resolved"
        self.assertEqual([], self.errors())

    def test_integration_requires_exact_final_revision_set(self):
        for revisions in ({}, {"T1": "e" * 40}, {"T1": "b" * 40, "T2": "f" * 40}):
            with self.subTest(revisions=revisions):
                self.record["integration"]["task_revisions"] = revisions
                self.assertTrue(self.errors())

    def test_integration_test_and_review_bind_to_integrated_revision(self):
        for target in ("tests", "review"):
            with self.subTest(target=target):
                self.record = valid_record()
                self.record["integration"][target]["revision"] = "e" * 40
                self.assertTrue(self.errors())
        self.record = valid_record()
        self.record["integration"]["tests"]["outcome"] = "failed"
        self.assertTrue(self.errors())

    def test_integration_tests_cannot_predate_task_green(self):
        self.record["integration"]["tests"]["timestamp"] = "2026-09-12T07:00:00Z"
        self.assertTrue(self.errors())

    def test_malformed_nested_data_returns_errors_without_crashing(self):
        for record in (None, [], "bad", 7, True, {}, {"schema_version": True}):
            with self.subTest(record=record):
                self.assertTrue(workflow.validate(record, "done"))
        for location, value in (("discovery", []), ("acceptance_criteria", [None]),
                                ("tasks", [False]), ("integration", "bad")):
            with self.subTest(location=location):
                self.record = valid_record()
                self.record[location] = value
                self.assertTrue(self.errors())
        for field in ("dependencies", "acceptance_criteria", "owned_paths", "isolation", "tdd", "review"):
            with self.subTest(field=field):
                self.record = valid_record()
                self.record["tasks"][0][field] = [None, {}]
                self.assertTrue(self.errors())

    def test_unknown_validation_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            workflow.validate(self.record, "invented")


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "workflow.json"

    def run_cli(self, *arguments):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual("", result.stderr)
        return result.returncode, json.loads(result.stdout)

    def write_record(self, record):
        self.path.write_text(json.dumps(record), encoding="utf-8")

    def test_init_creates_editable_skeleton_that_fails_plan(self):
        code, result = self.run_cli("init", "--output", self.path, "--title", "A task")
        self.assertEqual(0, code)
        self.assertTrue(result["valid"])
        record = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual("A task", record["title"])
        self.assertEqual([], record["tasks"])
        self.assertEqual([], record["acceptance_criteria"])
        self.assertEqual("", record["discovery"]["what"]["answer"])
        self.assertTrue(workflow.validate(record, "plan"))

    def test_init_does_not_overwrite_existing_file(self):
        self.path.write_text("preserve this", encoding="utf-8")
        code, result = self.run_cli("init", "--output", self.path, "--title", "Task")
        self.assertEqual(2, code)
        self.assertFalse(result["valid"])
        self.assertEqual("preserve this", self.path.read_text(encoding="utf-8"))

    def test_init_rejects_empty_title_without_creating_file(self):
        code, result = self.run_cli("init", "--output", self.path, "--title", "  ")
        self.assertEqual(2, code)
        self.assertFalse(result["valid"])
        self.assertFalse(self.path.exists())

    def test_check_reports_success_and_gate_failure(self):
        self.write_record(valid_record())
        code, result = self.run_cli("check", self.path, "--stage", "done")
        self.assertEqual(0, code)
        self.assertEqual([], result["errors"])
        record = valid_record()
        record["tasks"][0]["review"]["security"] = "failed"
        self.write_record(record)
        code, result = self.run_cli("check", self.path, "--stage", "done")
        self.assertEqual(1, code)
        self.assertTrue(result["errors"])

    def test_invalid_json_missing_file_and_cli_usage_are_input_errors(self):
        code, _ = self.run_cli("check", self.path, "--stage", "plan")
        self.assertEqual(2, code)
        for document in ("{", '{"schema_version":1,"schema_version":1}', '{"x":NaN}'):
            with self.subTest(document=document):
                self.path.write_text(document, encoding="utf-8")
                code, result = self.run_cli("check", self.path, "--stage", "plan")
                self.assertEqual(2, code)
                self.assertFalse(result["valid"])
        code, _ = self.run_cli("check", self.path, "--stage", "unknown")
        self.assertEqual(2, code)

    def test_malformed_valid_json_is_a_gate_failure(self):
        self.write_record([{"not": "workflow"}])
        code, result = self.run_cli("check", self.path, "--stage", "done")
        self.assertEqual(1, code)
        self.assertFalse(result["valid"])

    def test_oversized_input_is_rejected(self):
        self.path.write_text(" " * (4 * 1024 * 1024 + 1), encoding="utf-8")
        code, result = self.run_cli("check", self.path, "--stage", "plan")
        self.assertEqual(2, code)
        self.assertFalse(result["valid"])

    def test_recorded_commands_are_never_executed(self):
        marker = self.directory / "unexpected-execution"
        record = valid_record()
        malicious_command = f'{sys.executable} -c "open({str(marker)!r}, \'w\').write(\'bad\')"'
        record["tasks"][0]["tdd"]["red"]["command"] = malicious_command
        record["tasks"][0]["tdd"]["green"]["command"] = malicious_command
        record["integration"]["tests"]["command"] = malicious_command
        self.write_record(record)
        code, _ = self.run_cli("check", self.path, "--stage", "done")
        self.assertEqual(0, code)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
