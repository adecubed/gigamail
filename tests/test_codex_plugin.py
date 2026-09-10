"""Il plugin Codex (.codex-plugin, skills/, .mcp.json, marketplace) e' coerente.

Verificato a mano con codex-cli 0.148 (quello dentro l'app desktop Codex):
`codex plugin marketplace add <repo>` e poi `codex plugin add
gigamail@gigamail` leggono esattamente questi file. Qui si controlla che
restino coerenti fra loro e con il server: un percorso rotto o un tool
rinominato non deve arrivare a un utente."""
import asyncio
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "gigamail"


def _load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _server_tools():
    from ade_mail_agent.server import mcp

    return {t.name for t in asyncio.new_event_loop().run_until_complete(mcp.list_tools())}


def test_manifest_punta_a_file_esistenti():
    plugin = _load(".codex-plugin/plugin.json")
    assert plugin["name"] == "gigamail"
    assert (ROOT / plugin["skills"] / "gigamail" / "SKILL.md").is_file()
    assert (ROOT / plugin["mcpServers"]).is_file()
    ui = plugin["interface"]
    for key in ("composerIcon", "logo"):
        assert (ROOT / ui[key]).is_file(), key
    for shot in ui["screenshots"]:
        assert (ROOT / shot).is_file(), shot


def test_mcp_json_registra_il_server_e_inoltra_la_root():
    """Codex passa ai server stdio solo le variabili elencate in env_vars:
    senza APPDATA / GIGAMAIL_ROOT il server guarderebbe una cartella vuota
    (INTEGRATIONS.md, "una regola per ogni client")."""
    srv = _load(".mcp.json")["mcpServers"]["gigamail"]
    assert srv["command"] == "gigamail-server"
    assert {"APPDATA", "GIGAMAIL_ROOT", "ADE_ROOT", "PATH"} <= set(srv["env_vars"])


def test_marketplace_locale_espone_il_plugin():
    """`codex plugin marketplace add adecubed/gigamail` legge questo file: il
    plugin e' la radice del repo, cosi' il manifest in .codex-plugin/ e' lo
    stesso che scansiona il workflow plugin-scan."""
    market = _load(".agents/plugins/marketplace.json")
    entry = {p["name"]: p for p in market["plugins"]}["gigamail"]
    assert entry["source"]["source"] == "local"
    assert (ROOT / entry["source"]["path"]).resolve() == ROOT
    assert market["name"] == "gigamail"  # selettore: gigamail@gigamail


def test_voce_per_il_catalogo_openai_coerente_col_manifest():
    """integrations/codex/marketplace-entry.json e' la voce proposta per i
    cataloghi di openai/plugins: deve puntare a questo repo e portare lo
    stesso nome e la stessa categoria del manifest."""
    entry = _load("integrations/codex/marketplace-entry.json")
    plugin = _load(".codex-plugin/plugin.json")
    assert entry["name"] == plugin["name"]
    assert entry["source"] == {"source": "url", "url": plugin["repository"] + ".git"}
    assert entry["category"] == plugin["interface"]["category"]
    assert entry["interface"]["displayName"] == plugin["interface"]["displayName"]
    assert entry["policy"] == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}


def test_skill_frontmatter_e_metadata():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter mancante"
    front = yaml.safe_load(m.group(1))
    assert front["name"] == "gigamail"
    assert len(front["description"]) > 80
    ui = yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))["interface"]
    for key in ("icon_small", "icon_large"):
        assert (SKILL / ui[key]).is_file(), key
    assert "$gigamail" in ui["default_prompt"]


def test_skill_nomina_i_tool_veri():
    """La skill elenca i 24 tool per classe: ogni nome citato deve esistere
    sul server e ogni tool del server deve comparire. Una rinomina non puo'
    lasciare la skill a raccontare tool che non ci sono."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    tools = _server_tools()
    assert len(tools) == 24
    backticked = set(re.findall(r"`([a-z_]+)`", text))
    verbs = r"(?:list|get|read|search|send|reply|delete|create|move|mark|find)_[a-z_]+"
    mentioned = {t for t in backticked if re.fullmatch(verbs, t)}
    assert mentioned <= tools, mentioned - tools
    assert tools <= backticked, tools - backticked
