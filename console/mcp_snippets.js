// mcp_snippets.js — la configurazione che l'onboarding fa copiare al client
// MCP (Claude Desktop / Claude Code, oppure Codex) per avviare il server.
(function () {
  // Il server parte con il Python del backend (nell'app desktop quello
  // incluso) e -m gigamail.server: gigamail-server non e' nel PATH di
  // nessun utente dell'app. GIGAMAIL_ROOT: la cartella dati della console,
  // cosi' server e console vedono gli stessi account e approvazioni. Senza
  // risposta dal backend (backend vecchio), i nomi dell'installazione pip.
  function serverCmd(ag) {
    return ag && ag.python ? { command: ag.python, args: ['-m', 'gigamail.server'] }
                           : { command: 'gigamail-server', args: [] };
  }
  function mcpSnippet(ag) {
    const s = serverCmd(ag);
    const entry = { command: s.command };
    if (s.args.length) entry.args = s.args;
    if (ag && ag.root) entry.env = { GIGAMAIL_ROOT: ag.root };
    return JSON.stringify({ mcpServers: { gigamail: entry } }, null, 2);
  }
  // Codex legge ~/.codex/config.toml; `codex mcp add` scrive la stessa
  // cosa senza aprire il file. Nel TOML le stringhe si scrivono come in
  // JSON (backslash doppi); sulla riga di comando restano come sono.
  function codexSnippet(ag) {
    const s = serverCmd(ag);
    const root = (ag && ag.root) || '%APPDATA%\\ADE';
    const q = (v) => JSON.stringify(String(v));
    const arg = (v) => `"${v}"`;
    const add = `codex mcp add gigamail --env GIGAMAIL_ROOT=${arg(root)} -- ${arg(s.command)}${s.args.map((a) => ' ' + a).join('')}`;
    const toml = `[mcp_servers.gigamail]\ncommand = ${q(s.command)}\n` +
      (s.args.length ? `args = [${s.args.map(q).join(', ')}]\n` : '') +
      `\n[mcp_servers.gigamail.env]\nGIGAMAIL_ROOT = ${q(root)}`;
    return `${add}\n\n# or in ~/.codex/config.toml:\n${toml}`;
  }

  // Un comando della CLI da incollare nel terminale. Su Windows PowerShell un
  // percorso tra virgolette da solo e' una stringa, non un comando: serve &.
  function cliCommand(ag, args) {
    if (!(ag && ag.python)) return `gigamail ${args}`;
    const win = /^[A-Za-z]:\\|\\/.test(ag.python);
    return `${win ? '& ' : ''}"${ag.python}" -m gigamail.cli ${args}`;
  }

  const McpSnippets = { serverCmd, mcpSnippet, codexSnippet, cliCommand };
  if (typeof window !== 'undefined') window.McpSnippets = McpSnippets;
  if (typeof module !== 'undefined' && module.exports) module.exports = McpSnippets;
})();
