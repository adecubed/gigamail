"""The Claude Code plugin (plugins/gigamail/) is consistent.

The plugin lives in its own folder, not at the repository root: the
directory portal scans the whole plugin root, and at the root it flagged
the server's own source, CLAUDE.md and the release scripts as if the
plugin shipped them. The folder holds only the manifest, the skill and
.mcp.json. `claude plugin marketplace add adecubed/gigamail` reads the
marketplace at the root, which points here.

Verified by hand with Claude Code 2.1.197: marketplace add, install,
one skill and one MCP server, server connected."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "gigamail"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_manifest_points_at_existing_files():
    plugin = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert plugin["name"] == "gigamail"
    assert (PLUGIN / plugin["skills"] / "gigamail" / "SKILL.md").is_file()
    assert (PLUGIN / plugin["mcpServers"]).is_file()


def test_manifest_agrees_with_the_codex_one():
    claude = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    codex = _load(ROOT / ".codex-plugin" / "plugin.json")
    for key in ("name", "version", "description", "license", "repository"):
        assert claude[key] == codex[key], key


def test_marketplace_points_at_the_plugin_folder():
    market = _load(ROOT / ".claude-plugin" / "marketplace.json")
    assert market["name"] == "gigamail"  # selector: gigamail@gigamail
    entry = {p["name"]: p for p in market["plugins"]}["gigamail"]
    assert (ROOT / entry["source"]).resolve() == PLUGIN
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()


def test_mcp_json_starts_the_same_server_as_the_codex_one():
    """Claude passes its whole environment, so no env_vars list here."""
    claude = _load(PLUGIN / ".mcp.json")["mcpServers"]["gigamail"]
    codex = _load(ROOT / ".mcp.json")["mcpServers"]["gigamail"]
    assert claude["command"] == codex["command"]
    assert claude.get("args", []) == codex.get("args", [])


def test_skill_is_the_same_as_the_codex_one():
    """Two copies of one skill: edit skills/gigamail/SKILL.md and copy it to
    plugins/gigamail/skills/gigamail/SKILL.md."""
    shared = (ROOT / "skills" / "gigamail" / "SKILL.md").read_text(encoding="utf-8")
    claude = (PLUGIN / "skills" / "gigamail" / "SKILL.md").read_text(encoding="utf-8")
    assert claude == shared


def test_plugin_folder_ships_nothing_else():
    """What the portal scans is what is here: keep it to the plugin."""
    files = {p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*") if p.is_file()}
    assert files <= {
        ".claude-plugin/plugin.json",
        ".claude-plugin/icon.png",
        ".mcp.json",
        "README.md",
        "skills/gigamail/SKILL.md",
    }, files


def test_skill_tells_both_clients_how_to_register_the_server():
    text = (PLUGIN / "skills" / "gigamail" / "SKILL.md").read_text(encoding="utf-8")
    assert "claude plugin install gigamail@gigamail" in text
    assert "codex plugin add gigamail@gigamail" in text


def test_tool_counts_in_the_listing_texts_match_the_server():
    """test_codex_plugin checks the tool names; the numbers in the prose
    went stale on their own (a listing said 29 with 30 tools)."""
    import asyncio
    import re

    from gigamail.server import mcp

    count = len(asyncio.new_event_loop().run_until_complete(mcp.list_tools()))
    texts = {
        "skill": (ROOT / "skills" / "gigamail" / "SKILL.md").read_text(encoding="utf-8"),
        "plugin README": (PLUGIN / "README.md").read_text(encoding="utf-8"),
        "codex manifest": _load(ROOT / ".codex-plugin" / "plugin.json")["interface"]["longDescription"],
    }
    for where, text in texts.items():
        numbers = {int(n) for n in re.findall(r"\b(\d+) (?:typed MCP )?tools\b", text)}
        assert numbers == {count}, (where, numbers)


def _publish_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("publish_claude_plugin", ROOT / "scripts" / "publish-claude-plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(version, description="Mail and calendar"):
    return json.dumps({"name": "gigamail", "version": version, "description": description}).encode()


def test_a_version_bump_alone_does_not_move_the_branch():
    """Every release bumps plugin.json; the directory must not get a new
    version to review for that alone."""
    script = _publish_script()
    old = {script.MANIFEST: _manifest("0.6.6"), "plugins/gigamail/README.md": b"same"}
    new = {script.MANIFEST: _manifest("0.6.7"), "plugins/gigamail/README.md": b"same"}
    assert not script.plugin_changed(old, new)


def test_a_real_change_moves_the_branch():
    script = _publish_script()
    base = {script.MANIFEST: _manifest("0.6.6"), "plugins/gigamail/README.md": b"old"}
    assert script.plugin_changed(base, {**base, "plugins/gigamail/README.md": b"new"})
    assert script.plugin_changed(base, {**base, script.MANIFEST: _manifest("0.6.6", "Other")})
    assert script.plugin_changed(base, {**base, "plugins/gigamail/extra.md": b"x"})
