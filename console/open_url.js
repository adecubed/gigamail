// open_url.js — what a gigamail:// link asks of the console. The toast
// buttons (Read, Approve, Edit, Reject on an approval; Open on the summary
// of many; Reply on a client reply alert) and the agent's mail links all
// come through here, from the
// protocol handler, the second-instance argv or the CLI's forward.
(function () {
  function parse(url) {
    const u = String(url || '').trim();
    let m = u.match(/^gigamail:\/\/(show|approve|edit|reject)\/(req_[0-9A-Za-z]+)\/?$/i);
    if (m) return { kind: 'approval', action: m[1].toLowerCase(), id: m[2] };
    // the summary toast of a busy tick: open Waiting for you
    if (/^gigamail:\/\/pending\/?$/i.test(u)) return { kind: 'pending' };
    m = u.match(/^gigamail:\/\/reply\/([0-9a-f]{8})\/?$/i);
    if (m) return { kind: 'reply', key: m[1].toLowerCase() };
    m = u.match(/^gigamail:\/\/mail\/(\d+)\/([^/?#]+)(?:\?folder=([^&#]*))?/i);
    if (m) return { kind: 'mail', account_id: Number(m[1]), id: decodeURIComponent(m[2]), folder: m[3] ? decodeURIComponent(m[3]) : '' };
    return null;
  }

  /** The gigamail:// URL in a process argv, if any (--open-url=<url> or a bare URL). */
  function fromArgv(argv) {
    for (const a of argv || []) {
      const s = String(a || '');
      if (s.startsWith('--open-url=')) return s.slice('--open-url='.length);
      if (/^gigamail:\/\//i.test(s)) return s;
    }
    return '';
  }

  const OpenUrl = { parse, fromArgv };
  if (typeof module !== 'undefined' && module.exports) module.exports = OpenUrl;
  if (typeof window !== 'undefined') window.GMOpenUrl = OpenUrl;
})();
