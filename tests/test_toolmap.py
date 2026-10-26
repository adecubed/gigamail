"""La mappa tool documentata deve coincidere con i tool reali del server."""

from gigamail import gen_toolmap


def test_mappa_allineata_al_server():
    path = gen_toolmap._mappa_path()
    current = path.read_text(encoding="utf-8")
    assert gen_toolmap.render(current) == current, (
        "MAPPA_MCP.md divergente dai tool del server: "
        "rigenera con `python -m gigamail.gen_toolmap`"
    )


def test_classificazione_dangerous_da_schema():
    import asyncio

    from gigamail.server import mcp
    tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert gen_toolmap._classify(by_name["send_mail"]) == "DANGEROUS"
    assert gen_toolmap._classify(by_name["delete_message"]) == "DANGEROUS"
    assert gen_toolmap._classify(by_name["mark_read"]) == "WRITE_SAFE"
    assert gen_toolmap._classify(by_name["read_message"]) == "READ"
    # ogni tool con request_id DEVE essere due-fasi: nessuno sfugge
    for t in tools:
        props = (t.input_schema or {}).get("properties", {})
        if "request_id" in props:
            assert gen_toolmap._classify(t) == "DANGEROUS"


def test_qualita_descrizioni_tool():
    """Guardia sul Tool Score (glama.ai, 22/08/2026: create_folder D 1.5,
    delete_* C — descrizioni italiane di una riga, 0% parametri
    documentati, nessuna annotation). Ogni tool deve avere una
    descrizione sostanziosa in inglese, le annotations MCP e TUTTI i
    parametri descritti nello schema."""
    import asyncio

    from gigamail.server import mcp
    tools = asyncio.new_event_loop().run_until_complete(mcp.list_tools())
    assert len(tools) == 30
    for t in tools:
        desc = (t.description or "").strip()
        assert len(desc) >= 120, f"{t.name}: descrizione troppo corta"
        assert t.annotations is not None, f"{t.name}: annotations mancanti"
        props = (t.input_schema or {}).get("properties", {})
        undocumented = [k for k, v in props.items() if not v.get("description")]
        assert not undocumented, f"{t.name}: parametri senza descrizione {undocumented}"
        # le classi dichiarate alle macchine coincidono con quelle della mappa
        cls = gen_toolmap._classify(t)
        assert t.annotations.read_only_hint is (cls == "READ"), t.name
        assert t.annotations.destructive_hint is (cls == "DANGEROUS"), t.name
        if cls == "DANGEROUS":
            assert "TWO-PHASE" in desc and "request_id" in desc, t.name


def test_map_is_english_first_then_italian():
    """The map is in English first, then Italian, each with its own
    generated tool box listing the same tools."""
    text = gen_toolmap._mappa_path().read_text(encoding="utf-8")
    en_begin, en_end = gen_toolmap.MARKERS["en"]
    it_begin, it_end = gen_toolmap.MARKERS["it"]
    assert text.index(en_begin) < text.index('<a id="italiano"></a>') < text.index(it_begin)
    en_box = text.split(en_begin)[1].split(en_end)[0]
    it_box = text.split(it_begin)[1].split(it_end)[0]
    assert "Exposed tools" in en_box and "Riepilogo tool esposti" in it_box
    names = lambda box: sorted(n for n in box.split("`")[1::2])  # noqa: E731
    assert names(en_box) == names(it_box)
