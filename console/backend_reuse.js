// backend_reuse.js — may the console reuse a backend already listening?
//
// The backend is left running when the window closes, so the next start is
// instant. That made an old backend outlive an update: the new console
// talked to the code of the previous version, and a feature added on both
// sides stayed invisible until someone killed the process by hand. Here the
// console decides whether the backend it found is current, and finds the
// process to replace when it is not. Pure functions: tests/backend_reuse.test.js.
'use strict';

/** Why the backend that answered /health must be replaced; '' to reuse it. */
function restartReason(health, appVersion) {
  if (!health || health.service !== 'gigamail-console') return '';   // not ours: not ours to stop
  // Up to 0.4.0 the backend did not say whether its code is current.
  if (typeof health.stale !== 'boolean') return 'backend older than this console';
  if (health.stale) return 'its code changed on disk since it started';
  const version = String(health.version || '');
  // "0.0.0+unknown": sources run without package metadata, nothing to compare.
  if (version && !version.startsWith('0.0.0') && appVersion && version !== String(appVersion)) {
    return `version ${version}, console ${appVersion}`;
  }
  return '';
}

/** PID listening on a local TCP port, from `netstat -ano -p TCP` (Windows). */
function pidFromNetstat(output, port) {
  for (const line of String(output || '').split(/\r?\n/)) {
    const cols = line.trim().split(/\s+/);
    if (cols.length < 5 || cols[0].toUpperCase() !== 'TCP') continue;
    if (!/LISTEN/i.test(cols[3])) continue;
    if (!cols[1].endsWith(`:${port}`)) continue;
    const pid = parseInt(cols[4], 10);
    if (pid > 0) return pid;
  }
  return 0;
}

/** PID from `lsof -nP -iTCP:<port> -sTCP:LISTEN -t` (macOS, Linux). */
function pidFromLsof(output) {
  const pid = parseInt(String(output || '').trim().split(/\s+/)[0], 10);
  return pid > 0 ? pid : 0;
}

module.exports = { restartReason, pidFromNetstat, pidFromLsof };
