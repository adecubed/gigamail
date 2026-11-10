"""What the console is told when a request fails, and where it is written.

A request that failed answered "Internal Server Error" and nothing else,
and the reason went to the backend's output, which the installed app shows
nowhere: a user whose inbox would not open had no way to tell why, and
neither had we. Now a failure of the mail server says so, with the
server's reason, and every failure is written to a log file with its
stack.

The log holds the route (as declared: `/mail/search/{query}`, never the
search text or a message id), the exception's type, the stack and the
first characters of the exception's message. That message can quote what
the mail server answered; it never holds a mail's body.
"""
import imaplib
import logging
import socket
import ssl
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gigamail import policy
from gigamail.core import calendar_router, data_paths

# How much of an exception's message is kept, in the log and in an answer.
MAX_REASON_CHARS = 300
_LOG_BYTES = 1024 * 1024
_LOG_FILES = 3

_logger = None


def log_path() -> Path:
    return data_paths.data_root() / "logs" / "console.log"


def log() -> logging.Logger:
    """The backend's log file: 1 MB, three files kept. Never raises: with
    no writable folder the failures are still answered, just not kept."""
    global _logger
    if _logger is None:
        logger = logging.getLogger("gigamail.console")
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


def _say(it: str, en: str) -> str:
    return it if policy.user_lang() == "it" else en


def reason(exc: BaseException) -> str:
    """The exception's message on one line, cut: an IMAP error can quote a
    whole server response."""
    text = " ".join(str(exc).split())
    return text if len(text) <= MAX_REASON_CHARS else text[:MAX_REASON_CHARS] + "…"


def _route(request: Request) -> str:
    """The route as declared, without the values in it."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return f"{request.method} {path or '(no route)'}"


def record(request: Request, exc: BaseException) -> None:
    """Write a failed request to the log. Never raises."""
    try:
        stack = "".join(traceback.format_tb(exc.__traceback__))
        cause = exc.__cause__ or exc.__context__
        chain = f" (from {type(cause).__name__})" if cause is not None else ""
        log().error("%s -> %s.%s%s: %s\n%s", _route(request), type(exc).__module__,
                    type(exc).__qualname__, chain, reason(exc), stack.rstrip())
    except Exception:
        pass


def install(app: FastAPI) -> None:
    @app.exception_handler(calendar_router.NoCalendar)
    async def _no_calendar(request: Request, exc: Exception):
        return JSONResponse({"detail": _say(
            "Nessun calendario collegato: GigaMail legge i calendari di Microsoft 365 "
            "e Google. Collegane uno da + Account.",
            "No calendar connected: GigaMail reads Microsoft 365 and Google "
            "calendars. Connect one from + Account.")}, status_code=409)

    @app.exception_handler(imaplib.IMAP4.error)
    async def _imap_error(request: Request, exc: Exception):
        record(request, exc)
        return JSONResponse({"detail": _say(
            f"Il server di posta ha risposto con un errore: {reason(exc)}",
            f"The mail server answered with an error: {reason(exc)}")}, status_code=502)

    @app.exception_handler(TimeoutError)
    async def _timeout(request: Request, exc: Exception):
        record(request, exc)
        return JSONResponse({"detail": _say(
            "Il server di posta non ha risposto in tempo.",
            "The mail server did not answer in time.")}, status_code=504)

    async def _unreachable(request: Request, exc: Exception):
        record(request, exc)
        return JSONResponse({"detail": _say(
            f"Server di posta non raggiungibile ({type(exc).__name__}): {reason(exc)}",
            f"Mail server not reachable ({type(exc).__name__}): {reason(exc)}")}, status_code=502)

    for kind in (ConnectionError, ssl.SSLError, socket.gaierror):
        app.add_exception_handler(kind, _unreachable)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        # Starlette answers with this and then raises the exception again,
        # so the backend's own output still shows it as before.
        record(request, exc)
        return JSONResponse({"detail": _say(
            f"Errore interno ({type(exc).__name__}). Dettagli nel log: {log_path()}",
            f"Internal error ({type(exc).__name__}). Details in the log: {log_path()}")},
            status_code=500)
