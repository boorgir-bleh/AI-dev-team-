import os
from pathlib import Path
from uuid import uuid4

from backend.graph.runner import GraphRunner


def main() -> None:
    runs_dir = Path(os.environ.get("DEV_OFFICE_RUNS_DIR", "runs")).resolve()
    run_id = f"demo-{uuid4().hex[:12]}"
    with GraphRunner(runs_dir / "checkpoints.sqlite3") as runner:
        result = runner.run(
            "Build a CLI tool that converts CSV files to JSON with schema validation.",
            run_id,
        )
    print(f"Run: {run_id}")
    print(f"Status: {result['final_acceptance']['status']}")
    print(result["final_acceptance"]["summary"])
    print("Artifacts: spec, design, implementation, documentation")


if __name__ == "__main__":
    main()
