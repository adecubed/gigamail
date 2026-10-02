"""The Claude Code plugin (.claude-plugin/, skills/, .mcp.json) is consistent.

Verified by hand with Claude Code 2.1.197: `claude plugin marketplace add
<repo>` and `claude plugin install gigamail@gigamail` read exactly these
files, install the `gigamail` skill and connect the `gigamail` MCP server.
The skill and `.mcp.json` are shared with the Codex plugin
(test_codex_plugin.py); here we check the Claude manifests point at them
and agree with the Codex one."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_manifest_points_at_existing_files():
    plugin = _load(".claude-plugin/plugin.json")
    assert plugin["name"] == "gigamail"
    assert (ROOT / plugin["skills"] / "gigamail" / "SKILL.md").is_file()
    assert (ROOT / plugin["mcpServers"]).is_file()
    assert _load(plugin["mcpServers"])["mcpServers"]["gigamail"]


def test_manifest_agrees_with_the_codex_one():
    claude = _load(".claude-plugin/plugin.json")
    codex = _load(".codex-plugin/plugin.json")
    for key in ("name", "version", "description", "license", "repository", "skills", "mcpServers"):
        assert claude[key] == codex[key], key


def test_marketplace_exposes_the_plugin_at_the_repo_root():
    """`claude plugin marketplace add adecubed/gigamail` reads this file; the
    plugin is the repository root, so `gigamail@gigamail` installs it."""
    market = _load(".claude-plugin/marketplace.json")
    assert market["name"] == "gigamail"
    entry = {p["name"]: p for p in market["plugins"]}["gigamail"]
    assert entry["source"] == "./"
    assert (ROOT / entry["source"]).resolve() == ROOT


def test_skill_tells_both_clients_how_to_register_the_server():
    """The skill is shared: setup must not speak to one client only."""
    text = (ROOT / "skills" / "gigamail" / "SKILL.md").read_text(encoding="utf-8")
    assert "claude plugin install gigamail@gigamail" in text
    assert "codex plugin add gigamail@gigamail" in text
