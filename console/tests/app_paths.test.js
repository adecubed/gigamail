// Unit tests for app_paths.js: the data root and the Python interpreter
// the main process picks on each platform, and the override shared with
// the backend.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { dataRoot, pythonPath, autoUpdateSupported, launcherPath } = require('../app_paths');

test('Windows: %APPDATA%\\ADE, as the backend', () => {
  assert.equal(dataRoot({ APPDATA: 'C:\\Users\\mario\\AppData\\Roaming' }, 'win32', 'C:\\Users\\mario'),
    path.join('C:\\Users\\mario\\AppData\\Roaming', 'ADE'));
});

test('macOS and Linux: ~/.ade, as the backend (not ~/ADE)', () => {
  assert.equal(dataRoot({}, 'darwin', '/Users/mario'), path.join('/Users/mario', '.ade'));
  assert.equal(dataRoot({ APPDATA: '/ignored' }, 'linux', '/home/mario'), path.join('/home/mario', '.ade'));
});

test('GIGAMAIL_ROOT and ADE_ROOT move everything, on every platform', () => {
  assert.equal(dataRoot({ GIGAMAIL_ROOT: '/tmp/x', ADE_ROOT: '/tmp/y', APPDATA: 'C:\\a' }, 'win32'), '/tmp/x');
  assert.equal(dataRoot({ ADE_ROOT: ' /tmp/y ' }, 'darwin'), '/tmp/y');
});

test('Python: embeddable on Windows, python-build-standalone layout on macOS', () => {
  assert.equal(pythonPath({ packaged: true, resourcesPath: 'R', devRoot: 'D', platform: 'win32' }),
    path.join('R', 'python', 'python.exe'));
  assert.equal(pythonPath({ packaged: true, resourcesPath: 'R', devRoot: 'D', platform: 'darwin' }),
    path.join('R', 'python', 'bin', 'python3'));
});

test('Python in development: the repo venv next to console/', () => {
  assert.equal(pythonPath({ packaged: false, resourcesPath: 'R', devRoot: 'D', platform: 'win32' }),
    path.join('D', '.venv', 'Scripts', 'python.exe'));
  assert.equal(pythonPath({ packaged: false, resourcesPath: 'R', devRoot: 'D', platform: 'darwin' }),
    path.join('D', '.venv', 'bin', 'python'));
});

test('auto-update: Windows and macOS, on Linux only the AppImage', () => {
  assert.equal(autoUpdateSupported('win32', {}), true);
  assert.equal(autoUpdateSupported('darwin', {}), true);
  assert.equal(autoUpdateSupported('linux', { APPIMAGE: '/home/u/Apps/GigaMail-0.6.7-x86_64.AppImage' }), true);
  // .deb, or a run from source: no APPIMAGE, nothing for electron-updater to replace
  assert.equal(autoUpdateSupported('linux', {}), false);
});

test('Python packaged on Linux: resources/python/bin/python3', () => {
  assert.equal(pythonPath({ packaged: true, resourcesPath: 'R', devRoot: 'D', platform: 'linux' }),
    path.join('R', 'python', 'bin', 'python3'));
});

test('console.json reopens the AppImage file, not its temporary mount', () => {
  assert.equal(launcherPath({ APPIMAGE: '/home/u/Apps/GigaMail.AppImage' }, '/tmp/.mount_ab12/gigamail-console', 'linux'),
    '/home/u/Apps/GigaMail.AppImage');
  assert.equal(launcherPath({}, '/opt/GigaMail/gigamail-console', 'linux'), '/opt/GigaMail/gigamail-console');
  assert.equal(launcherPath({ APPIMAGE: 'x' }, 'C:\\GigaMail\\GigaMail.exe', 'win32'), 'C:\\GigaMail\\GigaMail.exe');
});
