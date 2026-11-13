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

  // Hero exchange: short scenes between you and the agent. Your lines type
  // themselves, the agent's fade in, and the outcome follows: "waiting for
  // your OK" turning into approved or rejected when the action leaves a
  // trace, or "nothing to approve" when it only reads. A scene may start
  // from the agent (the watcher announcing new mail) and a long one runs
  // over two pages. The pages come from the page (.ask-data), so each
  // language has its own; the first one is already in the HTML for readers
  // without scripts.
  //
  // The first scene is one the visitor plays: a reply waiting for the OK,
  // with the buttons of the app's approval window (read, edit, save,
  // reject, approve). Read opens the draft, Edit opens it in a text box,
  // and the others end the scene as they would in the app. A bubble points
  // at the buttons so it is clear they can be clicked. Nothing is sent:
  // the mail is invented and stays in the page. When nobody touches it the
  // loop moves on after a while and comes back to it.
  var ask = document.querySelector('.ask-box');
  var askData = ask && ask.querySelector('.ask-data');
  if (askData) {
    var calmAsk = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var chat = JSON.parse(askData.textContent);
    var rows = ask.querySelector('.ask-rows');
    var state = ask.querySelector('.ask-state');
    var pill = state.querySelector('.ask-pill');
    var caret = document.createElement('span');
    caret.className = 'caret';
    var look = { wait: 'wait', read: 'read', rejected: 'no', saved: 'saved' };
    var labelOf = function (key) { return (chat.try && chat.try.done && chat.try.done[key]) || chat.labels[key]; };
    var addRow = function (line, into) {
      var p = document.createElement('p');
      var label = document.createElement('b');
      var body = document.createElement('span');
      p.className = 'ask-row ask-' + line[0];
      label.textContent = chat.who[line[0]];
      p.appendChild(label);
      p.appendChild(body);
      into.appendChild(p);
      return body;
    };
    var showPill = function (key) {
      pill.className = 'ask-pill ' + (look[key] || 'ok');
      pill.textContent = labelOf(key);
      state.classList.add('on');
    };

    // The try-it scene. Built once; shown only while it plays.
    var T = chat.try;
    var trial = null;
    if (T) {
      var tryBox = document.createElement('div');
      var bar = document.createElement('div');
      var note = document.createElement('p');
      var mail = document.createElement('div');
      var tip = document.createElement('span');
      var again = document.createElement('button');
      tryBox.className = 'try';
      tryBox.hidden = true;
      bar.className = 'try-bar';
      bar.setAttribute('role', 'group');
      bar.setAttribute('aria-label', T.intro);
      note.className = 'try-note';
      note.textContent = T.note;
      mail.className = 'try-mail';
      mail.hidden = true;
      tip.className = 'try-tip';
      tip.setAttribute('aria-hidden', 'true');
      again.type = 'button';
      again.className = 'try-again';
      again.textContent = T.again;
      again.hidden = true;
      var button = function (act) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'try-btn' + (act === 'approve' || act === 'send' ? ' try-send' : act === 'reject' ? ' try-danger' : '');
        b.setAttribute('data-act', act);
        b.textContent = T.buttons[act];
        return b;
      };
      ['read', 'edit', 'save', 'reject', 'approve'].forEach(function (act) { bar.appendChild(button(act)); });
      tryBox.appendChild(bar);
      tryBox.appendChild(note);
      tryBox.appendChild(mail);
      ask.insertBefore(tryBox, state);
      ask.appendChild(tip);
      state.querySelector('span').appendChild(again);

      var draft = T.mail.body;
      var field = function (into, label, value) {
        var row = document.createElement('div');
        var l = document.createElement('span');
        row.className = 'try-row';
        l.className = 'try-label';
        l.textContent = label;
        row.appendChild(l);
        if (typeof value === 'string') {
          var v = document.createElement('span');
          v.textContent = value;
          row.appendChild(v);
        } else row.appendChild(value);
        into.appendChild(row);
      };
      // The draft as the app's approval window shows it: title, fields,
      // text, and the buttons at the bottom. editing swaps the text for a
      // text box and Approve for Send edited, as in the app.
      var openMail = function (editing) {
        mail.textContent = '';
        var title = document.createElement('div');
        var fields = document.createElement('div');
        var st = document.createElement('span');
        var chip = document.createElement('span');
        var tools = document.createElement('div');
        title.className = 'try-title';
        title.textContent = T.mail.title;
        fields.className = 'try-fields';
        st.className = 'try-state';
        st.textContent = T.mail.waiting;
        chip.className = 'try-chip';
        chip.textContent = T.mail.file;
        field(fields, T.mail.state, st);
        field(fields, T.mail.to, T.mail.to_value);
        field(fields, T.mail.subject, T.mail.subject_value);
        field(fields, T.mail.attachments, chip);
        mail.appendChild(title);
        mail.appendChild(fields);
        if (editing) {
          var edit = document.createElement('div');
          var hint = document.createElement('p');
          var area = document.createElement('textarea');
          edit.className = 'try-edit';
          hint.textContent = T.mail.edit_hint;
          area.value = draft;
          area.rows = 6;
          area.setAttribute('aria-label', T.mail.subject_value);
          area.addEventListener('input', function () { draft = area.value; });
          edit.appendChild(hint);
          edit.appendChild(area);
          mail.appendChild(edit);
        } else {
          var text = document.createElement('div');
          text.className = 'try-body';
          text.textContent = draft;
          mail.appendChild(text);
        }
        tools.className = 'try-tools';
        (editing ? ['save', 'reject', 'send'] : ['edit', 'save', 'reject', 'approve']).forEach(function (act) { tools.appendChild(button(act)); });
        mail.appendChild(tools);
        bar.hidden = true;
        note.hidden = true;
        mail.hidden = false;
        pointAt(0);
        var first = mail.querySelector(editing ? 'textarea' : '.try-btn');
        if (first && trial.byKeyboard) first.focus();
      };

      // The bubble walks over the buttons that are on screen, saying what
      // each does. It stops for good once the scene ends.
      var tipTimer = 0;
      var tipAt = 0;
      var pointAt = function (n) {
        clearTimeout(tipTimer);
        var list = Array.prototype.filter.call(tryBox.querySelectorAll('.try-btn'), function (b) { return b.offsetParent; });
        if (!list.length) { tip.classList.remove('on'); return; }
        var target = list[n % list.length];
        var box = ask.getBoundingClientRect();
        var r = target.getBoundingClientRect();
        // Above the button, or below it when the buttons wrap and it is not
        // on the first line, so the bubble never covers another button.
        var below = target.offsetTop > list[0].offsetTop;
        tip.textContent = T.hints[target.getAttribute('data-act')];
        tip.classList.toggle('below', below);
        tip.style.left = (r.left - box.left + r.width / 2) + 'px';
        tip.style.top = (below ? r.bottom - box.top + 8 : r.top - box.top - 8) + 'px';
        tip.classList.add('on');
        tipAt = n;
        if (!calmAsk) tipTimer = setTimeout(function () { pointAt(n + 1); }, 1700);
      };

      trial = { next: null, waitTimer: 0, touched: false, over: false, byKeyboard: false };
      var finish = function (key) {
        clearTimeout(tipTimer);
        clearTimeout(trial.waitTimer);
        tip.classList.remove('on');
        mail.hidden = true;
        bar.hidden = true;
        note.hidden = true;
        showPill(key);
        again.hidden = false;
        if (trial.byKeyboard) again.focus();
        moveOn(5000);
      };
      // Leave the scene for the animated ones, unless the visitor is on the
      // box: then wait until the pointer leaves.
      var moveOn = function (after) {
        clearTimeout(trial.waitTimer);
        if (!trial.next) return;
        trial.waitTimer = setTimeout(function () {
          if (trial.over || ask.contains(document.activeElement) && document.activeElement !== document.body) { moveOn(2500); return; }
          leave();
        }, after);
      };
      var leave = function () {
        clearTimeout(tipTimer);
        clearTimeout(trial.waitTimer);
        tip.classList.remove('on');
        tryBox.hidden = true;
        again.hidden = true;
        state.classList.remove('on');
        var go = trial.next;
        trial.next = null;
        if (go) go();
      };
      trial.start = function (next) {
        trial.next = next;
        trial.touched = false;
        draft = T.mail.body;
        rows.textContent = '';
        addRow(['agent', T.intro], rows).textContent = T.intro;
        var row = rows.lastChild;
        setTimeout(function () { row.classList.add('on'); }, 30);
        again.hidden = true;
        mail.hidden = true;
        bar.hidden = false;
        note.hidden = false;
        tryBox.hidden = false;
        showPill('wait');
        setTimeout(function () { pointAt(4); }, calmAsk ? 0 : 700);
        moveOn(15000);
      };
      tryBox.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-act]');
        if (!b) return;
        trial.touched = true;
        trial.byKeyboard = e.detail === 0;
        clearTimeout(trial.waitTimer);
        var act = b.getAttribute('data-act');
        if (act === 'read') openMail(false);
        else if (act === 'edit') openMail(true);
        else if (act === 'save') finish('saved');
        else if (act === 'reject') finish('rejected');
        else finish('sent');
      });
      again.addEventListener('click', function (e) {
        trial.byKeyboard = e.detail === 0;
        var next = trial.next;
        clearTimeout(trial.waitTimer);
        trial.start(next);
        if (trial.byKeyboard) bar.querySelector('.try-btn').focus();
      });
      ask.addEventListener('mouseenter', function () { trial.over = true; });
      ask.addEventListener('mouseleave', function () { trial.over = false; });
      window.addEventListener('resize', function () { if (tip.classList.contains('on')) pointAt(tipAt); });
    }

    // Keep the box as tall as its longest page, so the page below never
    // jumps: every page is laid out once in an invisible copy and measured.
    // The draft opened from the try-it scene may make it taller: that
    // happens on a click, so the move is expected.
    var reserve = function () {
      var ghost = document.createElement('div');
      var ghostRows = document.createElement('div');
      ghost.className = 'ask-box';
      ghost.style.cssText = 'position:absolute;visibility:hidden;box-sizing:border-box;margin:0;width:' + ask.offsetWidth + 'px';
      ghostRows.className = 'ask-rows';
      ghost.appendChild(ghostRows);
      ghost.appendChild(state.cloneNode(true));
      ask.parentNode.appendChild(ghost);
      var tallest = 0;
      chat.pages.forEach(function (page) {
        ghostRows.textContent = '';
        if (page.try) {
          if (!T) return;
          addRow(['agent', T.intro], ghostRows).textContent = T.intro;
          var copy = tryBox.cloneNode(true);
          copy.hidden = false;
          copy.querySelector('.try-bar').hidden = false;
          copy.querySelector('.try-note').hidden = false;
          copy.querySelector('.try-mail').hidden = true;
          ghostRows.appendChild(copy);
        } else {
          page.rows.forEach(function (line) { addRow(line, ghostRows).textContent = line[1]; });
        }
        tallest = Math.max(tallest, ghost.offsetHeight);
      });
      ask.parentNode.removeChild(ghost);
      ask.style.boxSizing = 'border-box';
      ask.style.minHeight = tallest + 'px';
    };
    var play = function (index) {
      var page = chat.pages[index];
      var after = function () { play((index + 1) % chat.pages.length); };
      if (page.try) {
        if (trial) trial.start(after); else after();
        return;
      }
      rows.textContent = '';
      state.classList.remove('on');
      var outcome = function (n) {
        showPill(page.pills[n]);
        if (n + 1 < page.pills.length) { setTimeout(function () { outcome(n + 1); }, 1400); return; }
        setTimeout(function () {
          Array.prototype.forEach.call(rows.children, function (p) { p.classList.remove('on'); });
          state.classList.remove('on');
        }, 2600);
        setTimeout(after, 3000);
      };
      var say = function (n) {
        if (n === page.rows.length) { setTimeout(function () { outcome(0); }, 300); return; }
        var line = page.rows[n];
        var chars = Array.from(line[1]);
        var body = addRow(line, rows);
        if (line[0] !== 'you') {
          body.textContent = line[1];
          setTimeout(function () { body.parentNode.classList.add('on'); }, 30);
          setTimeout(function () { say(n + 1); }, 800 + chars.length * 18);
          return;
        }
        var text = document.createElement('span');
        var at = 0;
        body.appendChild(text);
        body.appendChild(caret);
        caret.hidden = false;
        body.parentNode.classList.add('on');
        var key = function () {
          at += 1;
          text.textContent = chars.slice(0, at).join('');
          if (at < chars.length) { setTimeout(key, 34); return; }
          caret.hidden = true;
          setTimeout(function () { say(n + 1); }, 550);
        };
        setTimeout(key, n ? 400 : 0);
      };
      say(0);
    };
    reserve();
    window.addEventListener('resize', reserve);
    ask.classList.add('live');
    if (calmAsk) {
      // Less motion: no scenes rolling by, only the one the visitor plays.
      if (trial) trial.start(null);
    } else {
      rows.textContent = '';
      setTimeout(function () { play(0); }, 1500);
    }
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
