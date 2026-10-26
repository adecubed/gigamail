// home.js — the home page's small behaviours. Everything on the page is in
// the HTML; this only highlights the visitor's installer and drives the
// install tabs. Without JS all tabs' content is visible and nothing breaks.
(function () {
  // Download: mark the installer for the visitor's platform. Apple Silicon
  // cannot be told from Intel in a browser, so macOS gets the arm64 build as
  // the primary with the Intel one next to it.
  var ua = navigator.userAgent || '';
  var platform = /Windows/i.test(ua) ? 'win' : /Macintosh|Mac OS X/i.test(ua) ? 'mac-arm' : '';
  if (platform) {
    var mine = document.querySelector('.dl a[data-platform="' + platform + '"]');
    if (mine) mine.classList.add('is-mine');
    var primary = document.getElementById('hero-download');
    if (primary && mine) {
      primary.href = mine.href;
      var label = primary.querySelector('span');
      if (label) label.textContent = primary.getAttribute(platform === 'win' ? 'data-label-win' : 'data-label-mac');
    }
  }

  // Install tabs: one agent at a time, keyboard friendly.
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab[role="tab"]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.panel[role="tabpanel"]'));
  function select(id) {
    tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t.getAttribute('aria-controls') === id)); });
    panels.forEach(function (p) { p.hidden = p.id !== id; });
  }
  if (tabs.length && panels.length) {
    tabs.forEach(function (t) {
      t.addEventListener('click', function () { select(t.getAttribute('aria-controls')); });
    });
    var fromHash = location.hash && document.getElementById(location.hash.slice(1));
    select(fromHash && fromHash.getAttribute('role') === 'tabpanel' ? fromHash.id : tabs[0].getAttribute('aria-controls'));
  }

  // Hero clip: do not autoplay for people who asked for less motion.
  var hero = document.getElementById('hero-clip');
  if (hero && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    hero.removeAttribute('autoplay');
    hero.pause();
    hero.controls = true;
  }
})();
