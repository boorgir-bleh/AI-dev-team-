import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
import zipfile


def save_run_artifacts(
    run_directory: Path,
    result: dict[str, Any],
    *,
    project_directory: Path | None = None,
) -> Path:
    workspace = run_directory / "workspace"
    artifacts = run_directory / "artifacts"
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    project = project_directory or workspace
    project.mkdir(parents=True, exist_ok=True)
    destinations = [workspace] if project.resolve() == workspace.resolve() else [workspace, project]

    state = {key: value for key, value in result.items() if key != "events"}
    (artifacts / "final_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    implementation = result.get("implementation", {})
    documentation = result.get("documentation", {})
    files = {}
    if isinstance(implementation, dict):
        files.update(implementation.get("files", {}))
    if isinstance(documentation, dict):
        files.update(documentation.get("files", {}))
    for relative_name, contents in files.items():
        for destination in destinations:
            target = _workspace_file(destination, relative_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")

    for key in (
        "spec",
        "design",
        "design_security_report",
        "design_critic_report",
        "security_report",
        "critic_report",
        "test_report",
        "final_acceptance",
    ):
        if key in state:
            for destination in destinations:
                metadata = destination / ".devoffice"
                metadata.mkdir(exist_ok=True)
                (metadata / f"{key}.json").write_text(
                    json.dumps(state[key], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    zip_path = artifacts / "deliverable.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(project.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(project).as_posix())
    return zip_path


def _workspace_file(workspace: Path, relative_name: str) -> Path:
    if not isinstance(relative_name, str) or not relative_name.strip():
        raise ValueError("Generated file paths must be non-empty strings")
    normalized = relative_name.replace("\\", "/")
    relative = PurePosixPath(normalized)
    windows_path = PureWindowsPath(relative_name)
    if (
        relative.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise ValueError(f"Generated file path is not a safe relative path: {relative_name}")
    root = workspace.resolve()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Generated file path escapes the workspace: {relative_name}")
    return target
