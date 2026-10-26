// attachment_guard.js — attachments the console never opens: files that run
// a program when opened (programs, installers, scripts, shortcuts, disk
// images). "Open" writes the file to a temporary folder and hands it to the
// system, which for these means running it: one click on a mail from a
// stranger would run their program. "Save as" still works.
//
// The same list lives in src/gigamail/core/mail_guard.py
// (EXECUTABLE_EXTENSIONS); a Python test keeps the two equal.
(function () {
  const EXECUTABLE_EXTENSIONS = [
    // Windows programs, installers and libraries
    '.exe', '.com', '.scr', '.pif', '.msi', '.msp', '.dll', '.cpl',
    '.appx', '.msix', '.appinstaller',
    // scripts the system runs on a double click
    '.bat', '.cmd', '.js', '.jse', '.vbs', '.vbe', '.wsf', '.wsh',
    '.ps1', '.psm1', '.hta', '.jar', '.reg',
    // shortcuts and disk images
    '.lnk', '.iso', '.img', '.vhd', '.vhdx',
    // macOS
    '.app', '.pkg', '.dmg', '.command',
  ];

  /** True when a file with this name would run something if opened.
   * Windows drops trailing dots and spaces ("x.exe." runs as "x.exe"),
   * and a double extension counts by its last part ("a.pdf.exe"). */
  function isExecutableName(name) {
    const n = String(name || '').trim().toLowerCase().replace(/[. ]+$/, '');
    return EXECUTABLE_EXTENSIONS.some((ext) => n.endsWith(ext));
  }

  const AttachmentGuard = { EXECUTABLE_EXTENSIONS, isExecutableName };
  if (typeof module !== 'undefined' && module.exports) module.exports = AttachmentGuard;
  if (typeof window !== 'undefined') window.GMAttachmentGuard = AttachmentGuard;
})();
