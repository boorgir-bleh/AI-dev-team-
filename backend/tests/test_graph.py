from pathlib import Path
import tempfile
import unittest

from backend.agents.mock import AgentOutputError, MockLLM
from backend.agents.schemas import Spec
from backend.graph.runner import GraphRunner


PROMPT = "Build a CLI tool that converts CSV files to JSON with schema validation."


def blocking_critic_response() -> dict[str, object]:
    return {
        "verdict": "REQUEST_CHANGES",
        "comments": [
            {
                "priority": "blocking",
                "comment": "Add explicit invalid-row behavior.",
                "rationale": "The acceptance criteria require schema validation but do not define what happens on invalid data.",
            }
        ],
    }


class GraphWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "checkpoints.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_mock_demo_reaches_final_acceptance_with_structured_events(self) -> None:
        with GraphRunner(self.database_path) as runner:
            result = runner.run(PROMPT, "demo-run")

        self.assertEqual(result["final_acceptance"]["status"], "completed")
        self.assertIn("spec", result)
        self.assertIn("design", result)
        self.assertIn("implementation", result)
        self.assertIn("documentation", result)
        self.assertIn("run_complete", [event["type"] for event in result["events"]])
        self.assertEqual(result["fix_iterations"], 0)

    def test_run_callback_streams_each_graph_event_once(self) -> None:
        streamed_events: list[dict[str, object]] = []
        with GraphRunner(self.database_path) as runner:
            result = runner.run(PROMPT, "streamed-run", on_event=streamed_events.append)

        self.assertCountEqual(
            [event["id"] for event in streamed_events],
            [event["id"] for event in result["events"]],
        )

    def test_design_review_loop_stops_at_configured_limit(self) -> None:
        scripts = {"critic_design": [blocking_critic_response() for _ in range(3)]}
        with GraphRunner(
            self.database_path,
            MockLLM(scripts),
            max_design_loops=2,
        ) as runner:
            result = runner.run(PROMPT, "design-loop")

        self.assertEqual(result["design_iterations"], 2)
        self.assertEqual(result["final_acceptance"]["status"], "failed")
        design_loops = [
            event for event in result["events"]
            if event["type"] == "loop_iteration" and event["payload"]["loop"] == "design_review"
        ]
        self.assertEqual(len(design_loops), 2)

    def test_code_fix_loop_stops_at_configured_limit(self) -> None:
        scripts = {"critic_code": [blocking_critic_response() for _ in range(5)]}
        with GraphRunner(
            self.database_path,
            MockLLM(scripts),
            max_fix_iterations=4,
        ) as runner:
            result = runner.run(PROMPT, "fix-loop")

        self.assertEqual(result["fix_iterations"], 4)
        self.assertEqual(result["final_acceptance"]["status"], "failed")
        code_loops = [
            event for event in result["events"]
            if event["type"] == "loop_iteration" and event["payload"]["loop"] == "code_review"
        ]
        self.assertEqual(len(code_loops), 4)

    def test_approval_interrupt_can_resume_from_sqlite_checkpoint(self) -> None:
        with GraphRunner(self.database_path) as runner:
            paused = runner.run(PROMPT, "approval-run", approval_required=True)
            self.assertIn("__interrupt__", paused)
        with GraphRunner(self.database_path) as resumed_runner:
            finished = resumed_runner.resume_approval("approval-run", approved=True)

        self.assertEqual(finished["final_acceptance"]["status"], "completed")

    def test_approval_resume_streams_new_events(self) -> None:
        initial_events: list[dict[str, object]] = []
        resumed_events: list[dict[str, object]] = []
        with GraphRunner(self.database_path) as runner:
            paused = runner.run(
                PROMPT,
                "streamed-approval-run",
                approval_required=True,
                on_event=initial_events.append,
            )
            self.assertIn("__interrupt__", paused)
            finished = runner.resume_approval(
                "streamed-approval-run",
                approved=True,
                on_event=resumed_events.append,
            )

        self.assertEqual(finished["final_acceptance"]["status"], "completed")
        initial_ids = {event["id"] for event in initial_events}
        resumed_ids = {event["id"] for event in resumed_events}
        final_ids = {event["id"] for event in finished["events"]}
        self.assertTrue(resumed_ids)
        self.assertTrue(resumed_ids.isdisjoint(initial_ids))
        self.assertTrue(resumed_ids.issubset(final_ids))

    def test_declined_spec_approval_stops_before_design(self) -> None:
        with GraphRunner(self.database_path) as runner:
            runner.run(PROMPT, "rejected-run", approval_required=True)
            finished = runner.resume_approval("rejected-run", approved=False)

        self.assertNotIn("design", finished)
        self.assertEqual(finished["final_acceptance"]["status"], "failed")
        self.assertIn("declined", finished["final_acceptance"]["known_issues"][0])

    def test_structured_mock_retries_invalid_output_then_accepts_valid_output(self) -> None:
        llm = MockLLM(
            {
                "orchestrator_spec": [
                    {"goals": [], "assumptions": [], "acceptance_criteria": [], "out_of_scope": []},
                    {
                        "goals": ["Convert CSV to JSON"],
                        "assumptions": [],
                        "acceptance_criteria": ["Output is valid JSON"],
                        "out_of_scope": [],
                    },
                ]
            }
        )
        result = llm.structured(
            "orchestrator_spec",
            Spec,
            Spec(
                goals=["fallback"],
                assumptions=[],
                acceptance_criteria=["fallback"],
                out_of_scope=[],
            ),
        )
        self.assertEqual(result.goals, ["Convert CSV to JSON"])

    def test_structured_mock_surfaces_exhausted_retries(self) -> None:
        invalid = {"goals": [], "assumptions": [], "acceptance_criteria": [], "out_of_scope": []}
        with self.assertRaisesRegex(AgentOutputError, "after 3 attempt"):
            MockLLM({"orchestrator_spec": [invalid]}).structured(
                "orchestrator_spec",
                Spec,
                Spec(
                    goals=["fallback"],
                    assumptions=[],
                    acceptance_criteria=["fallback"],
                    out_of_scope=[],
                ),
            )


if __name__ == "__main__":
    unittest.main()
