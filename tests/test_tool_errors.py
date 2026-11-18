"""Tool failures tell the agent why, and crashes are kept in a log."""
import asyncio
import logging

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from gigamail.core import tool_errors

# Number of tools registered before the wrapper existed.
TOOL_COUNT = 41


@pytest.fixture(autouse=True)
def _fresh_logger():
    tool_errors._logger = None
    yield
    logger = logging.getLogger("gigamail.mcp")
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
    tool_errors._logger = None


def test_an_expected_error_reaches_the_agent_with_its_text():
    @tool_errors.readable
    def tool(message_id: str):
        raise ValueError("Folder not found: 'Leads'")
    with pytest.raises(ToolError, match="Folder not found: 'Leads'") as info:
        tool(message_id="12")
    assert isinstance(info.value.__cause__, ValueError)


def test_a_crash_is_logged_with_its_stack_and_raised_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")

    @tool_errors.readable
    def read_message(message_id: str, body: str = ""):
        raise RuntimeError("boom " + "x" * 500)
    with pytest.raises(RuntimeError):
        read_message(message_id="12", body="Dear Mario, the price is 100")
    text = (tmp_path / "logs" / "mcp.log").read_text(encoding="utf-8")
    assert "read_message" in text and "RuntimeError" in text and "Traceback" in text
    assert "message_id='12'" in text
    assert "Dear Mario" not in text
    assert "x" * 301 not in text


def test_a_mail_server_that_does_not_answer_reaches_the_agent_with_its_text():
    import requests

    @tool_errors.readable
    def connection():
        raise requests.exceptions.ConnectionError("connection refused")

    @tool_errors.readable
    def slow():
        raise requests.exceptions.Timeout("read timed out")
    with pytest.raises(ToolError, match="connection refused"):
        connection()
    with pytest.raises(ToolError, match="read timed out"):
        slow()


def test_an_expected_error_is_logged_too_without_a_stack(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")

    @tool_errors.readable
    def list_folders():
        raise LookupError("No such folder " + "y" * 500)
    with pytest.raises(ToolError):
        list_folders()
    text = (tmp_path / "logs" / "mcp.log").read_text(encoding="utf-8")
    assert "INFO" in text and "list_folders" in text and "No such folder" in text
    assert "Traceback" not in text
    assert "y" * 301 not in text


def test_tool_error_passes_through_unlogged(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")
    original = ToolError("already readable")

    @tool_errors.readable
    def tool():
        raise original
    with pytest.raises(ToolError) as info:
        tool()
    assert info.value is original
    path = tmp_path / "logs" / "mcp.log"
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_a_log_folder_that_cannot_be_written_does_not_break_the_tool(tmp_path, monkeypatch):
    # A regular file where the folder should be: mkdir fails at once on any
    # platform (a missing drive letter can hang while Windows looks for it).
    (tmp_path / "logs").write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")

    @tool_errors.readable
    def tool():
        return {"ok": True}

    @tool_errors.readable
    def crash():
        raise RuntimeError("boom")
    assert tool() == {"ok": True}
    with pytest.raises(RuntimeError):
        crash()


def test_a_failing_log_handler_does_not_break_the_tool(monkeypatch):
    class Broken:
        def error(self, *a, **k):
            raise OSError("disk full")
        info = error
    monkeypatch.setattr(tool_errors, "_logger", Broken())

    @tool_errors.readable
    def crash():
        raise RuntimeError("boom")

    @tool_errors.readable
    def expected():
        raise ValueError("nope")
    with pytest.raises(RuntimeError):
        crash()
    with pytest.raises(ToolError, match="nope"):
        expected()


def test_every_registered_tool_is_wrapped_and_keeps_its_schema():
    from gigamail import server
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == TOOL_COUNT
    read = next(t for t in tools if t.name == "read_message")
    assert set(read.input_schema["properties"]) == {"message_id", "folder", "account_id"}


def test_a_missing_message_tells_the_agent_why(monkeypatch):
    from gigamail import server

    def gone(**kw):
        raise ValueError("Message not found for id: '12'")
    monkeypatch.setattr(server.mail_router, "get_message", gone)
    with pytest.raises(ToolError, match="Message not found for id: '12'"):
        asyncio.run(server.mcp.call_tool("read_message", {"message_id": "12"}))


def test_calling_the_module_function_still_raises_the_original_error(monkeypatch):
    from gigamail import server

    def gone(**kw):
        raise ValueError("x")
    monkeypatch.setattr(server.mail_router, "get_message", gone)
    with pytest.raises(ValueError):
        server.read_message("12")


def test_the_log_never_holds_an_address_but_the_agent_gets_the_full_text(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")
    text = ("IMAP connection failed after 3 attempts "
            "(mario.rossi@mail.example.com:993): timed out")

    @tool_errors.readable
    def expected():
        raise ConnectionError(text)

    @tool_errors.readable
    def crash():
        raise RuntimeError(text)
    with pytest.raises(ToolError) as info:
        expected()
    assert "mario.rossi@mail.example.com" in str(info.value)
    with pytest.raises(RuntimeError):
        crash()
    log = (tmp_path / "logs" / "mcp.log").read_text(encoding="utf-8")
    assert "mario.rossi" not in log and "example.com" not in log
    assert log.count("<address>") == 2


def test_a_logged_argument_is_cut_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_errors, "log_path", lambda: tmp_path / "logs" / "mcp.log")

    @tool_errors.readable
    def tool(folder: str, message_id: str):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        tool(folder="f" * 500, message_id="mario.rossi@example.com")
    log = (tmp_path / "logs" / "mcp.log").read_text(encoding="utf-8")
    assert "f" * 81 not in log and "f" * 40 in log
    assert "mario.rossi" not in log
