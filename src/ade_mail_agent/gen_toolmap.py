"""Genera la sezione tool di MAPPA_MCP.md dal server reale (fonte di verita'
unica: mcp.list_tools). Uso:

    python -m ade_mail_agent.gen_toolmap          # riscrive la sezione
    python -m ade_mail_agent.gen_toolmap --check  # exit 1 se divergente (CI)

La classe di rischio e' derivata dal server stesso: DANGEROUS = il tool ha il
parametro confirm_token (due fasi); WRITE_SAFE = azioni reversibili note;
il resto e' READ.
"""
import asyncio
import sys
from pathlib import Path

BEGIN = "<!-- TOOLMAP:BEGIN (generato da gen_toolmap — non editare a mano) -->"
END = "<!-- TOOLMAP:END -->"

WRITE_SAFE_TOOLS = {"mark_read", "move_message", "create_folder"}


def _mappa_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "MAPPA_MCP.md"


def _classify(tool) -> str:
    props = (tool.input_schema or {}).get("properties", {})
    if "request_id" in props:
        return "DANGEROUS"
    if tool.name in WRITE_SAFE_TOOLS:
        return "WRITE_SAFE"
    return "READ"


def generate() -> str:
    from ade_mail_agent.server import mcp
    tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
    by_class = {"READ": [], "WRITE_SAFE": [], "DANGEROUS": []}
    for t in tools:
        by_class[_classify(t)].append(t.name)
    lines = [f"## Riepilogo tool esposti ({len(tools)} — generato dal server)", ""]
    lines.append(f"**READ ({len(by_class['READ'])}):** "
                 + ", ".join(f"`{n}`" for n in by_class["READ"]))
    lines.append(f"**WRITE_SAFE ({len(by_class['WRITE_SAFE'])}):** "
                 + ", ".join(f"`{n}`" for n in by_class["WRITE_SAFE"]))
    lines.append(f"**DANGEROUS ({len(by_class['DANGEROUS'])}, due fasi):** "
                 + ", ".join(f"`{n}`" for n in by_class["DANGEROUS"]))
    return "\n".join(lines)


def render(current: str) -> str:
    block = f"{BEGIN}\n{generate()}\n{END}"
    if BEGIN in current and END in current:
        pre = current.split(BEGIN)[0]
        post = current.split(END)[1]
        return pre + block + post
    raise SystemExit(f"Marker {BEGIN!r} non trovati in MAPPA_MCP.md")


def main() -> int:
    path = _mappa_path()
    current = path.read_text(encoding="utf-8")
    updated = render(current)
    if "--check" in sys.argv:
        if updated != current:
            print("MAPPA_MCP.md NON allineata ai tool del server: "
                  "rigenera con python -m ade_mail_agent.gen_toolmap")
            return 1
        print("MAPPA_MCP.md allineata al server.")
        return 0
    path.write_text(updated, encoding="utf-8", newline="")
    print(f"Sezione tool rigenerata in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
