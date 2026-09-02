// sync-version.js — allinea la versione di package.json (e del lock) a quella
// di pyproject.toml, la source of truth unica del progetto. npm lo esegue da
// solo prima di ogni build ("predist"): nessuna macchina puo' piu' impacchettare
// un installer con una versione diversa da quella del pacchetto Python.
const fs = require('fs');
const path = require('path');

const toml = fs.readFileSync(path.join(__dirname, '..', 'pyproject.toml'), 'utf-8');
const m = toml.match(/^version\s*=\s*"([^"]+)"/m);
if (!m) {
  console.error('sync-version: campo version non trovato in pyproject.toml');
  process.exit(1);
}
const version = m[1];

const pkgPath = path.join(__dirname, 'package.json');
const pkg = fs.readFileSync(pkgPath, 'utf-8');
// Sostituzione mirata per non riformattare il file: il primo "version" del
// file e' quello top-level (le dipendenze non hanno chiavi "version").
const updated = pkg.replace(/("version"\s*:\s*")[^"]+(")/, `$1${version}$2`);
if (updated !== pkg) {
  fs.writeFileSync(pkgPath, updated);
  console.log(`sync-version: package.json -> ${version}`);
} else {
  console.log(`sync-version: package.json gia' a ${version}`);
}

const lockPath = path.join(__dirname, 'package-lock.json');
if (fs.existsSync(lockPath)) {
  const lock = JSON.parse(fs.readFileSync(lockPath, 'utf-8'));
  if (lock.version !== version || lock.packages?.['']?.version !== version) {
    lock.version = version;
    if (lock.packages && lock.packages['']) lock.packages[''].version = version;
    fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2) + '\n');
    console.log(`sync-version: package-lock.json -> ${version}`);
  }
}
