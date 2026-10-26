// Attachments the console never opens: files that run a program.
const test = require('node:test');
const assert = require('node:assert/strict');
const { isExecutableName, EXECUTABLE_EXTENSIONS } = require('../attachment_guard');

test('programs, scripts, shortcuts and disk images are executable', () => {
  for (const name of ['setup.exe', 'Fattura.PDF.EXE', 'run.ps1', 'link.lnk',
    'disk.iso', 'install.msi', 'app.dmg', 'start.command', 'script.js']) {
    assert.equal(isExecutableName(name), true, name);
  }
});

test('Windows trailing dots and spaces do not hide the extension', () => {
  assert.equal(isExecutableName('invoice.exe.'), true);
  assert.equal(isExecutableName('invoice.exe  '), true);
  assert.equal(isExecutableName(' invoice.exe . '), true);
});

test('documents and archives are not executable', () => {
  for (const name of ['listino.pdf', 'offerta.docx', 'foto.jpg', 'dati.csv',
    'archivio.zip', 'exe.pdf', 'note.txt', '', null, undefined]) {
    assert.equal(isExecutableName(name), false, String(name));
  }
});

test('every extension starts with a dot and is lower case', () => {
  for (const ext of EXECUTABLE_EXTENSIONS) {
    assert.match(ext, /^\.[a-z0-9]+$/);
  }
});
