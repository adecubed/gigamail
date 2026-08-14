"""La mappa tool documentata deve coincidere con i tool reali del server."""
from pathlib import Path

from ade_mail_agent import gen_toolmap


def test_mappa_allineata_al_server():
    path = gen_toolmap._mappa_path()
    current = path.read_text(encoding="utf-8")
    assert gen_toolmap.render(current) == current, (
        "MAPPA_MCP.md divergente dai tool del server: "
        "rigenera con `python -m ade_mail_agent.gen_toolmap`"
    )


def test_classificazione_dangerous_da_schema():
    import asyncio
    from ade_mail_agent.server import mcp
    tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert gen_toolmap._classify(by_name["send_mail"]) == "DANGEROUS"
    assert gen_toolmap._classify(by_name["delete_message"]) == "DANGEROUS"
    assert gen_toolmap._classify(by_name["mark_read"]) == "WRITE_SAFE"
    assert gen_toolmap._classify(by_name["read_message"]) == "READ"
    # ogni tool con confirm_token DEVE essere due-fasi: nessuno sfugge
    for t in tools:
        props = (t.input_schema or {}).get("properties", {})
        if "confirm_token" in props:
            assert gen_toolmap._classify(t) == "DANGEROUS"
