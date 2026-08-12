"""Policy dei tool: classi di rischio, conferma a due fasi, audit log.

Classi:
  READ        — esecuzione libera
  WRITE_SAFE  — esecuzione libera, registrata nell'audit log
  DANGEROUS   — due fasi: la prima chiamata restituisce anteprima + confirm_token
                monouso (TTL 5 minuti); la seconda, col token, esegue.

L'audit log è JSONL append-only in %APPDATA%/ADE/agent_audit.jsonl.
"""
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Dict

READ = "READ"
WRITE_SAFE = "WRITE_SAFE"
DANGEROUS = "DANGEROUS"

_CONFIRM_TTL_SECONDS = 300
_pending: Dict[str, Dict[str, Any]] = {}  # token -> {tool, args, expires}


def _audit_path() -> Path:
    root = os.environ.get("ADE_ROOT") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "ADE"
    )
    os.makedirs(root, exist_ok=True)
    return Path(root) / "agent_audit.jsonl"


def audit(tool: str, args: Dict[str, Any], outcome: str, detail: str = "") -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": tool,
        "args": {k: v for k, v in args.items() if k not in ("body", "confirm_token")},
        "outcome": outcome,
    }
    if detail:
        entry["detail"] = detail[:500]
    with open(_audit_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _purge_expired() -> None:
    now = time.monotonic()
    for tok in [t for t, p in _pending.items() if p["expires"] < now]:
        del _pending[tok]


def request_confirmation(tool: str, args: Dict[str, Any], preview: Dict[str, Any]) -> Dict[str, Any]:
    """Fase 1 di un tool DANGEROUS: registra l'azione e restituisce l'anteprima."""
    _purge_expired()
    token = secrets.token_urlsafe(16)
    _pending[token] = {
        "tool": tool,
        "args": args,
        "expires": time.monotonic() + _CONFIRM_TTL_SECONDS,
    }
    audit(tool, args, "confirmation_requested")
    return {
        "status": "confirmation_required",
        "preview": preview,
        "confirm_token": token,
        "expires_in_seconds": _CONFIRM_TTL_SECONDS,
        "instructions": (
            "AZIONE NON ESEGUITA. Mostra l'anteprima all'utente e, solo dopo il suo "
            "esplicito consenso, richiama lo stesso tool con questo confirm_token."
        ),
    }


def consume_confirmation(tool: str, token: str) -> Dict[str, Any]:
    """Fase 2: valida e consuma il token. Solleva ValueError se non valido."""
    _purge_expired()
    pending = _pending.get(token)
    if pending is None or pending["tool"] != tool:
        audit(tool, {"confirm_token": "?"}, "confirmation_invalid")
        raise ValueError(
            "confirm_token non valido o scaduto: ripeti la chiamata senza token "
            "per ottenere una nuova anteprima."
        )
    del _pending[token]
    return pending["args"]


def execute_dangerous(
    tool: str,
    args: Dict[str, Any],
    confirm_token: str | None,
    preview_fn: Callable[[], Dict[str, Any]],
    execute_fn: Callable[[Dict[str, Any]], Any],
) -> Any:
    """Orchestrazione standard di un tool DANGEROUS."""
    if not confirm_token:
        return request_confirmation(tool, args, preview_fn())
    original_args = consume_confirmation(tool, confirm_token)
    try:
        result = execute_fn(original_args)
        audit(tool, original_args, "executed")
        return result
    except Exception as e:
        audit(tool, original_args, "error", str(e))
        raise
