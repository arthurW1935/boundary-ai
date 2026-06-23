from pathlib import Path

from armoriq_mcp.workspace import SandboxWorkspace, WorkspaceError


def test_write_read_and_search(tmp_path: Path) -> None:
    workspace = SandboxWorkspace(tmp_path)

    write_result = workspace.write_file("notes/demo.txt", "hello armoriq\nsecure tool call")
    assert write_result["path"] == "notes/demo.txt"

    read_result = workspace.read_file("notes/demo.txt")
    assert "secure tool call" in read_result["content"]

    search_result = workspace.search_files("armoriq")
    assert search_result["matches"][0]["path"] == "notes/demo.txt"


def test_rejects_escape_outside_sandbox(tmp_path: Path) -> None:
    workspace = SandboxWorkspace(tmp_path)

    try:
        workspace.write_file("../escape.txt", "nope")
    except WorkspaceError as exc:
        assert "sandbox root" in str(exc)
    else:
        raise AssertionError("Expected WorkspaceError for sandbox escape")
