// home.js — small behaviours of the home and the install page. Everything
// on the page is in the HTML; this only points the download buttons at the
// visitor's installer and drives the install tabs. Without JS the buttons
// open the release page, all tabs' content is visible and nothing breaks.
(function () {
  // Download: pick the installer for the visitor's platform. Apple Silicon
  // cannot be told from Intel in a browser, so macOS gets the arm64 build;
  // the install page lists the Intel one too. Linux gets the .deb, which
  // also runs where the AppImage cannot use Chromium's sandbox; Android
  // says Linux too and has no build.
  var base = 'https://github.com/adecubed/gigamail/releases/latest/download/';
  var installers = { win: 'GigaMail-Setup.exe', 'mac-arm': 'GigaMail-arm64.dmg', linux: 'GigaMail-amd64.deb' };
  var ua = navigator.userAgent || '';
  var platform = /Windows/i.test(ua) ? 'win' : /Macintosh|Mac OS X/i.test(ua) ? 'mac-arm'
    : /Linux/i.test(ua) && !/Android/i.test(ua) ? 'linux' : '';
  if (platform) {
    var mine = document.querySelector('.dl a[data-platform="' + platform + '"]');
    if (mine) mine.classList.add('is-mine');
    Array.prototype.forEach.call(document.querySelectorAll('.js-download'), function (btn) {
      btn.href = base + installers[platform];
      var label = btn.querySelector('span');
      var text = btn.getAttribute('data-label-' + platform.split('-')[0]);
      if (label && text) label.textContent = text;
    });
  }

  // Release updates: the subscribe form posts to Buttondown's embed
  // endpoint for this list. It stays hidden while the list name is empty,
  // so the page never shows a form that goes nowhere; the RSS and GitHub
  // links next to it work either way.
  var newsletter = 'gigamail';
  if (newsletter) {
    Array.prototype.forEach.call(document.querySelectorAll('form[data-newsletter]'), function (form) {
      form.action = 'https://buttondown.com/api/emails/embed-subscribe/' + encodeURIComponent(newsletter);
      form.hidden = false;
    });
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

  // Feature cards rise in as they scroll into view (home.css, .js-reveal).
  // Only with IntersectionObserver and without reduced motion; otherwise the
  // class is never added and the cards are simply there.
  var cards = document.querySelectorAll('#features .feature');
  var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (cards.length && 'IntersectionObserver' in window && !calm) {
    document.documentElement.classList.add('js-reveal');
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var i = Array.prototype.indexOf.call(cards, e.target);
        e.target.style.transitionDelay = ((i % 4) * 70) + 'ms';
        e.target.classList.add('in-view');
        e.target.addEventListener('transitionend', function () { e.target.style.transitionDelay = ''; }, { once: true });
        io.unobserve(e.target);
      });
    }, { threshold: 0.15 });
    cards.forEach(function (c) { io.observe(c); });
  }

  // Hero clip: do not autoplay for people who asked for less motion.
  var hero = document.getElementById('hero-clip');
  if (hero && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    hero.removeAttribute('autoplay');
    hero.pause();
    hero.controls = true;
  }
})();
