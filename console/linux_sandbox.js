// Chromium's sandbox on Linux: GigaMail does not start without it.
//
// The windows show mail written by strangers, and the sandbox is what keeps
// a renderer bug from becoming code running as the user. On Linux it needs
// either unprivileged user namespaces or a setuid chrome-sandbox helper.
// The AppImage launcher electron-builder generates (AppRun) probes
// `unshare -Ur true` and, when that fails, quietly adds --no-sandbox: on
// Ubuntu 23.10 and later, where AppArmor restricts user namespaces, the
// AppImage would run every window unsandboxed. The same flag can come from
// the user or from ELECTRON_DISABLE_SANDBOX. In all those cases the packaged
// app refuses to start and says why, instead of degrading.
//
// The .deb does not hit this: it installs an AppArmor profile that allows
// the namespaces (and the setuid helper where namespaces do not exist).

const TEXTS = {
  it: {
    title: 'GigaMail non può partire in modo sicuro',
    body_appimage:
      'Questo sistema non permette a GigaMail di isolare le sue finestre (la sandbox di Chromium): '
      + 'servono i namespace utente, che qui sono disattivati o limitati da AppArmor, come su Ubuntu 23.10 e successivi.\n\n'
      + 'GigaMail mostra mail scritte da sconosciuti e senza isolamento non si avvia.\n\n'
      + 'Installa il pacchetto per Debian/Ubuntu (GigaMail-amd64.deb): porta con sé il profilo AppArmor che serve. '
      + 'In alternativa chiedi a chi amministra il computer di consentire i namespace utente a questa app.',
    body_flag:
      'GigaMail è stato avviato con la sandbox di Chromium disattivata (--no-sandbox o ELECTRON_DISABLE_SANDBOX).\n\n'
      + 'GigaMail mostra mail scritte da sconosciuti e senza isolamento non si avvia. Avvialo senza quell\'opzione.',
  },
  en: {
    title: 'GigaMail cannot start safely',
    body_appimage:
      'This system does not let GigaMail isolate its windows (the Chromium sandbox): '
      + 'it needs user namespaces, which are turned off here or restricted by AppArmor, as on Ubuntu 23.10 and later.\n\n'
      + 'GigaMail shows mail written by strangers and does not start without isolation.\n\n'
      + 'Install the Debian/Ubuntu package (GigaMail-amd64.deb): it carries the AppArmor profile that is needed. '
      + 'Otherwise ask whoever manages this computer to allow user namespaces for this app.',
    body_flag:
      'GigaMail was started with the Chromium sandbox turned off (--no-sandbox or ELECTRON_DISABLE_SANDBOX).\n\n'
      + 'GigaMail shows mail written by strangers and does not start without isolation. Start it without that option.',
  },
};

function envFlag(v) {
  const s = String(v == null ? '' : v).trim().toLowerCase();
  return s !== '' && s !== '0' && s !== 'false';
}

/** Is the Chromium sandbox switched off for this run? */
function disabled(argv = process.argv, env = process.env) {
  return (argv || []).some((a) => a === '--no-sandbox')
    || envFlag(env.ELECTRON_DISABLE_SANDBOX);
}

/** The probe AppRun itself uses: can this user create a user namespace?
 *  `run` is child_process.execFileSync, injected for the tests. */
function userNamespacesWork(run) {
  try { run('unshare', ['-Ur', 'true'], { stdio: 'ignore', timeout: 5000 }); return true; } catch (_) { return false; }
}

/** Title and text for the refusal, in the system language (it, else en).
 *  When user namespaces do not work, the flag came from the AppImage
 *  launcher (or the user worked around the same problem): the text says
 *  what to do about the system. Otherwise someone passed it on purpose. */
function message(env = process.env, namespacesWork = true) {
  const loc = String(env.LC_ALL || env.LC_MESSAGES || env.LANG || '').slice(0, 2).toLowerCase();
  const t = TEXTS[loc] || TEXTS.en;
  return { title: t.title, body: namespacesWork ? t.body_flag : t.body_appimage };
}

module.exports = { disabled, message, userNamespacesWork, TEXTS };
