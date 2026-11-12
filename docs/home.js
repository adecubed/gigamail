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

  // Hero title: the words rise in one after the other, then an underline
  // draws itself under the highlighted sentence. The inline script in the
  // page's head hides the title until this has run (class js-fx on <html>);
  // without JS or with reduced motion the title is simply there.
  var title = document.querySelector('.hero h1');
  if (title && document.documentElement.classList.contains('js-fx')) {
    var lang = document.documentElement.lang || 'en';
    // Chinese has no spaces: split it into words where the browser can,
    // otherwise into single characters.
    var pieces = function (text) {
      if (lang.indexOf('zh') !== 0) return text.split(/(\s+)/);
      if (window.Intl && Intl.Segmenter) {
        return Array.from(new Intl.Segmenter(lang, { granularity: 'word' }).segment(text), function (s) { return s.segment; });
      }
      return Array.from(text);
    };
    var index = 0;
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 1 && child.tagName !== 'BR') { walk(child); return; }
        if (child.nodeType !== 3) return;
        var frag = document.createDocumentFragment();
        pieces(child.nodeValue).forEach(function (part) {
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(' ')); return; }
          var box = document.createElement('span');
          box.className = 'w';
          var inner = document.createElement('span');
          inner.textContent = part;
          inner.style.setProperty('--i', index++);
          box.appendChild(inner);
          frag.appendChild(box);
        });
        node.replaceChild(frag, child);
      });
    })(title);
    title.setAttribute('aria-label', title.textContent.replace(/\s+/g, ' ').trim());
    var mark = title.querySelector('em');
    if (mark) mark.style.setProperty('--draw-delay', (index * 55 + 350) + 'ms');
    title.classList.add('words');
  }

  // Hero exchange: a request types itself, the agent answers, and the
  // outcome follows: "waiting for your OK" turning into "approved" when the
  // action leaves a trace, or "nothing to approve" when it only reads. The
  // turns come from the page (.ask-data), so each language has its own; the
  // first one is already in the HTML for readers without scripts or motion.
  var ask = document.querySelector('.ask-box');
  var askData = ask && ask.querySelector('.ask-data');
  if (askData && !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
    var chat = JSON.parse(askData.textContent);
    var typed = ask.querySelector('.typed');
    var agent = ask.querySelector('.ask-agent');
    var reply = agent.querySelector('span');
    var state = ask.querySelector('.ask-state');
    var pill = state.querySelector('.ask-pill');
    var text = document.createElement('span');
    var caret = document.createElement('span');
    caret.className = 'caret';
    // Keep the box as tall as its longest turn, so the page below never jumps.
    var reserve = function () {
      [[typed.parentNode, typed, 0], [agent, reply, 1]].forEach(function (row) {
        var keep = row[1].textContent, tallest = 0;
        row[0].style.minHeight = '';
        chat.turns.forEach(function (turn) {
          row[1].textContent = turn[row[2]];
          tallest = Math.max(tallest, row[0].offsetHeight);
        });
        row[1].textContent = keep;
        row[0].style.minHeight = tallest + 'px';
      });
    };
    reserve();
    typed.textContent = '';
    typed.appendChild(text);
    typed.appendChild(caret);
    window.addEventListener('resize', function () {
      var now = text.textContent, said = reply.textContent;
      typed.textContent = now;
      reserve();
      typed.textContent = '';
      text.textContent = now;
      typed.appendChild(text);
      typed.appendChild(caret);
      reply.textContent = said;
    });
    ask.classList.add('live');
    var play = function (index) {
      var turn = chat.turns[index];
      var chars = Array.from(turn[0]);
      var reads = turn[2] === 'read';
      var at = 0;
      agent.classList.remove('on');
      state.classList.remove('on');
      text.textContent = '';
      caret.hidden = false;
      var key = function () {
        at += 1;
        text.textContent = chars.slice(0, at).join('');
        if (at < chars.length) { setTimeout(key, 34); return; }
        caret.hidden = true;
        setTimeout(function () {
          reply.textContent = turn[1];
          agent.classList.add('on');
        }, 550);
        setTimeout(function () {
          pill.className = 'ask-pill ' + (reads ? 'read' : 'wait');
          pill.textContent = chat.labels[reads ? 'read' : 'wait'];
          state.classList.add('on');
        }, 1700);
        if (!reads) setTimeout(function () {
          pill.className = 'ask-pill ok';
          pill.textContent = chat.labels[turn[2]];
        }, 3100);
        setTimeout(function () {
          agent.classList.remove('on');
          state.classList.remove('on');
        }, reads ? 4600 : 5900);
        setTimeout(function () { play((index + 1) % chat.turns.length); }, reads ? 5000 : 6300);
      };
      key();
    };
    setTimeout(function () { play(0); }, 1500);
  }

  // Story: the four steps play out like the hero prompt. When the list
  // scrolls into view the steps light up one after the other and each
  // description types itself. The untyped rest stays in the page, invisible,
  // so the cards keep their size and nothing jumps.
  var steps = Array.prototype.slice.call(document.querySelectorAll('.story ol li'));
  var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (steps.length && 'IntersectionObserver' in window && !still) {
    var list = steps[0].parentNode;
    var lines = steps.map(function (step) {
      var p = step.querySelector('p');
      var chars = Array.from(p.textContent);
      var shown = document.createElement('span');
      var caret = document.createElement('span');
      var rest = document.createElement('span');
      caret.className = 'caret';
      caret.hidden = true;
      rest.className = 'rest';
      rest.textContent = chars.join('');
      p.setAttribute('aria-label', chars.join(''));
      p.textContent = '';
      p.appendChild(shown); p.appendChild(caret); p.appendChild(rest);
      return { step: step, chars: chars, shown: shown, caret: caret, rest: rest };
    });
    list.classList.add('js-typing');
    var play = function (n) {
      if (n >= lines.length) return;
      var line = lines[n], at = 0;
      line.step.classList.add('on');
      line.caret.hidden = false;
      (function tick() {
        at = Math.min(line.chars.length, at + 2);
        line.shown.textContent = line.chars.slice(0, at).join('');
        line.rest.textContent = line.chars.slice(at).join('');
        if (at < line.chars.length) { setTimeout(tick, 22); return; }
        setTimeout(function () { line.caret.hidden = true; play(n + 1); }, 450);
      })();
    };
    new IntersectionObserver(function (entries, observer) {
      if (!entries[0].isIntersecting) return;
      observer.disconnect();
      play(0);
    }, { threshold: 0.4 }).observe(list);
  }

  // Hero clip: do not autoplay for people who asked for less motion.
  var hero = document.getElementById('hero-clip');
  if (hero && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    hero.removeAttribute('autoplay');
    hero.pause();
    hero.controls = true;
  }
})();
