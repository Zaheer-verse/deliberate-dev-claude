"""Exercise both CLIs together with actual red/green tests in isolated Git trees.

The review status fields below are test fixture assertions, not human review proof.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git"), "Git is required for the integration smoke test")
class EndToEndTests(unittest.TestCase):
    def test_external_record_real_tdd_isolation_and_completion_gate(self):
        with tempfile.TemporaryDirectory(prefix="deliberate-smoke-") as directory:
            root = Path(directory)
            repo = root / "source repo"
            repo.mkdir()
            hooks = root / "empty-hooks"
            hooks.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT="0")

            def run(argv, cwd=repo, expected=0):
                result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result

            def git(*args, cwd=repo):
                return run(["git", "-c", "user.name=Deliberate Test",
                            "-c", "user.email=test@localhost", "-c", f"core.hooksPath={hooks}",
                            "-c", "commit.gpgsign=false", *args], cwd).stdout.strip()

            def helper(name, *args, expected=0):
                result = run([sys.executable, str(PLUGIN / "scripts" / name), *map(str, args)],
                             expected=expected)
                return json.loads(result.stdout)

            def stamp():
                return datetime.now(timezone.utc).isoformat()

            git("init", "-b", "main")
            (repo / "greeting.py").write_text('def greet(name):\n    return "Hello, world!"\n', encoding="utf-8")
            git("add", "greeting.py")
            git("commit", "-m", "Existing greeting baseline")
            baseline = git("rev-parse", "HEAD")

            records = root / "run records"
            records.mkdir()
            record_path = records / "run.json"
            helper("workflow.py", "init", "--output", record_path, "--title", "Personalized greeting")
            self.assertFalse(helper("workflow.py", "check", record_path, "--stage", "plan", expected=1)["valid"])
            self.assertEqual(git("status", "--porcelain"), "")

            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["discovery"] = {
                "what": {"answer": "Greet the given name after trimming whitespace.", "source": "Test fixture"},
                "why": {"answer": "Personalize existing greetings.", "source": "Test fixture"},
                "who": {"answer": "Library callers.", "source": "Test fixture"},
                "context": ["Fixture tests local behavior; no network or user data."],
            }
            record["acceptance_criteria"] = [{"id": "AC1", "description": "Greet ' Alice ' as 'Hello, Alice!'."}]
            task = {"id": "T1", "title": "Personalize greeting", "scope": "Trim and greet the name.",
                    "acceptance_criteria": ["AC1"], "owned_paths": ["greeting.py", "tests/test_greeting.py"],
                    "dependencies": []}
            record["tasks"] = [task]

            def save():
                record_path.write_text(json.dumps(record), encoding="utf-8")

            save()
            self.assertTrue(helper("workflow.py", "check", record_path, "--stage", "plan")["valid"])
            args = ("create", "--repo", repo, "--run-id", "smoke", "--task-id", "t1")
            plan = helper("worktrees.py", *args)
            self.assertFalse(Path(plan["worktree"]).exists())
            created = helper("worktrees.py", *args, "--apply")
            task_tree = Path(created["worktree"])
            self.assertNotEqual(task_tree, repo)
            self.assertEqual(created["base_commit"], baseline)

            (task_tree / "tests").mkdir()
            (task_tree / "tests/test_greeting.py").write_text(
                'import unittest\nfrom greeting import greet\n\nclass GreetingTests(unittest.TestCase):\n'
                '    def test_name(self):\n        self.assertEqual(greet(" Alice "), "Hello, Alice!")\n',
                encoding="utf-8")
            git("add", "tests/test_greeting.py", cwd=task_tree)
            git("commit", "-m", "Test personalized greeting before changing implementation", cwd=task_tree)
            red_revision = git("rev-parse", "HEAD", cwd=task_tree)
            argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
            red = run(argv, task_tree, expected=1)
            self.assertIn("AssertionError", red.stderr)
            red_time = stamp()

            (task_tree / "greeting.py").write_text('def greet(name):\n    return f"Hello, {name.strip()}!"\n', encoding="utf-8")
            git("add", "greeting.py", cwd=task_tree)
            git("commit", "-m", "Implement personalized greeting", cwd=task_tree)
            final = git("rev-parse", "HEAD", cwd=task_tree)
            run(argv, task_tree)
            green_time = stamp()
            command = "python -m unittest discover -s tests -v"
            review = {"revision": final, "correctness": "passed", "security": "passed", "quality": "passed", "findings": []}
            task.update(isolation={"branch": created["branch"], "worktree": str(task_tree), "base_revision": baseline},
                        tdd={"red": {"command": command, "outcome": "failed", "reason": "Existing code ignores the name.",
                                     "expected_failure": True, "timestamp": red_time, "revision": red_revision},
                             "green": {"command": command, "outcome": "passed", "timestamp": green_time, "revision": final}},
                        final_revision=final, review=review)
            save()
            self.assertFalse(helper("workflow.py", "check", record_path, "--stage", "done", expected=1)["valid"])

            integrated = helper("worktrees.py", "create", "--repo", repo, "--run-id", "smoke",
                                "--task-id", "integration", "--base", final, "--apply")
            run(argv, Path(integrated["worktree"]))
            record["integration"] = {"task_revisions": {"T1": final}, "revision": final,
                "tests": {"command": command, "outcome": "passed", "timestamp": stamp(), "revision": final},
                "review": dict(review)}
            save()
            self.assertTrue(helper("workflow.py", "check", record_path, "--stage", "done")["valid"])
            task["review"]["quality"] = "failed"
            save()
            self.assertFalse(helper("workflow.py", "check", record_path, "--stage", "done", expected=1)["valid"])
            self.assertEqual(git("rev-parse", "HEAD"), baseline)
            self.assertEqual(git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
