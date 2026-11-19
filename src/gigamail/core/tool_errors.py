"""What the agent is told when an MCP tool fails, and where crashes are kept.

The MCP SDK hands the agent only "Error executing tool <name>" for any
exception that is not a ToolError, so GigaMail's own messages ("Folder not
found ...") were lost and an agent could only say "the read failed". Now an
expected failure reaches the agent with its text, and every failure is
written to `logs/mcp.log`.

The log holds the tool's name, the exception's type, the stack, the first
300 characters of the error message with addresses masked, plus the values
of a few identifying arguments (`LOGGED_ARGS`: ids and folders). It never
holds a mail's body: the other arguments are not written. An error message
can still name a folder or an attachment's file name.
"""
import functools
import inspect
import logging
import re
import threading
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from gigamail.core import data_paths

# Failures the code anticipated: their message is meant to be read. The
# `requests` ones are the Microsoft and Google mail servers not answering.
EXPECTED: tuple[type[BaseException], ...] = (
    ValueError, LookupError, PermissionError, ConnectionError, TimeoutError,
    RequestsConnectionError, RequestsTimeout)
# The only arguments written to the log, when a tool crashes.
LOGGED_ARGS = ("account_id", "folder", "folder_id", "source_folder", "message_id",
               "request_id", "top", "skip", "days")

MAX_REASON_CHARS = 300
_LOG_BYTES = 1024 * 1024
_LOG_FILES = 3
MAX_ARG_CHARS = 80
# The tools that look in the user's own folders log the request id only: the
# words, the folder and the path say what the user looks for and where.
LOGGED_ONLY = {"search_files": ("request_id",), "read_file": ("request_id",)}
_ADDRESS = re.compile(r"\S+@\S+")

_logger = None
_logger_lock = threading.Lock()


def log_path() -> Path:
    return data_paths.data_root() / "logs" / "mcp.log"


def _log():
    """The tools' log file: 1 MB, three files kept. With no writable folder
    the failures are still reported, just not kept."""
    global _logger
    if _logger is not None:
        return _logger
    with _logger_lock:
        if _logger is None:
            logger = logging.getLogger("gigamail.mcp")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            try:
                path = log_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(path, maxBytes=_LOG_BYTES, backupCount=_LOG_FILES,
                                              encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logger.addHandler(handler)
            except Exception:
                logger.addHandler(logging.NullHandler())
            _logger = logger
    return _logger


def _clean(text: str, limit: int) -> str:
    """One line, anything that looks like an address replaced, cut to `limit`.
    For the log only: the agent gets the message as it was."""
    text = _ADDRESS.sub("<address>", " ".join(text.split()))
    return text if len(text) <= limit else text[:limit] + "…"


def _reason(exc: BaseException) -> str:
    return _clean(str(exc), MAX_REASON_CHARS)


def _logged_args(fn: Callable, args: tuple, kwargs: dict) -> str:
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs).arguments
    except TypeError:
        bound = kwargs
    names = LOGGED_ONLY.get(fn.__name__, LOGGED_ARGS)
    return " ".join(f"{name}={_clean(repr(bound[name]), MAX_ARG_CHARS)}" for name in names if name in bound)


def _record(name: str, fn: Callable, args: tuple, kwargs: dict, exc: BaseException,
            expected: bool) -> None:
    """Write a failed call to the log. Never raises."""
    try:
        if expected:
            _log().info("%s -> %s: %s", name, type(exc).__name__, _reason(exc))
            return
        # Frames only: the last line of a full traceback repeats the message
        # uncut, which can quote a whole server answer.
        stack = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
        _log().error("%s(%s) -> %s.%s: %s\nTraceback (most recent call last):\n%s", name,
                     _logged_args(fn, args, kwargs), type(exc).__module__,
                     type(exc).__qualname__, _reason(exc), stack)
    except Exception:
        pass


def readable(fn: Callable) -> Callable:
    """Wrap a tool so that an expected failure reaches the agent as a
    ToolError with its own text; any other failure is logged and raised as
    it was. ToolError and MCPError pass through. The signature is kept, as
    the SDK builds the tool's input schema from it."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ToolError, MCPError):
            raise
        except EXPECTED as exc:
            _record(fn.__name__, fn, args, kwargs, exc, expected=True)
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            _record(fn.__name__, fn, args, kwargs, exc, expected=False)
            raise
    return wrapper
