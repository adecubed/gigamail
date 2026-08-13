/**
 * voice_mail.js — Sistema voce always-on ADE Mail
 * VAD (Voice Activity Detection) con AudioContext + MediaRecorder
 * Nessuna dipendenza Google — usa Whisper API sul backend.
 *
 * Flusso:
 * 1. MediaRecorder sempre attivo
 * 2. AudioContext analizza volume in tempo reale
 * 3. Quando rileva voce → inizia a raccogliere chunks
 * 4. Silenzio > 1.5s dopo voce → manda a /voice/transcribe
 * 5. Se testo inizia con "ade" → processa comando
 */

const VOICE_BACKEND    = 'http://localhost:8002';
const SILENCE_DELAY    = 1200;  // ms silenzio prima di inviare
const VOICE_THRESHOLD  = 8;     // volume minimo per rilevare voce
const PLAYBACK_STOP_THRESHOLD = 22; // soglia piu alta durante la lettura audio
const MIN_VOICE_MS     = 350;   // durata minima voce per non ignorare

let vadStream        = null;
let vadRecorder      = null;
let vadAnalyser      = null;
let vadAudioCtx      = null;
let vadChunks        = [];
let vadActive        = false;       // loop VAD attivo
let vadSpeaking      = false;       // sta parlando?
let vadSilenceTimer  = null;
let vadVoiceStart    = null;
let voiceProcessing  = false;
let voiceContext     = {};
let voiceRestartTimer = null;
let voicePlaybackActive = false;
let voiceStopRequested = false;
let voiceRequestAbortController = null;
let currentVoiceAudio = null;
let vadStopOnlyMode = false;

// ── Contesto mail ────────────────────────────────────────────
function updateVoiceContext(mailId, mailIndex) {
  voiceContext = { mail_id: mailId, mail_index: mailIndex, pending_send: false };
}

function resetVoiceContext() {
  updateVoiceContext(null, -1);
}

// ── Stato bottone ─────────────────────────────────────────────
function setVoiceState(state) {
  ['btnVoice', 'btnReplyVoice', 'btnVoiceCommand'].forEach((id) => {
    const btn = byId(id);
    if (!btn) return;
    btn.classList.remove('voice-listening', 'voice-processing', 'voice-error', 'active');
    const isSidebar = id === 'btnVoiceCommand';
    if (state === 'listening') {
      btn.classList.add('voice-listening', 'active');
      if (!isSidebar) btn.textContent = '🎙 ADE';
      btn.title = 'Ascolto attivo — di\' un comando';
    } else if (state === 'speaking') {
      btn.classList.add('voice-processing', 'active');
      if (!isSidebar) btn.textContent = '● REC';
      btn.title = 'Registrazione...';
    } else if (state === 'processing') {
      btn.classList.add('voice-processing', 'active');
      if (!isSidebar) btn.textContent = '⚡ ADE';
      btn.title = 'Elaborazione...';
    } else if (state === 'error') {
      btn.classList.add('voice-error');
      if (!isSidebar) btn.textContent = '✕ MIC';
      btn.title = 'Errore microfono';
    } else if (state === 'off') {
      if (!isSidebar) btn.textContent = '🎙 OFF';
      btn.title = 'Comando vocale — clicca per attivare';
    }
  });
}

// ── Polling UI actions ────────────────────────────────────────
let _uiActionPollingInterval = null;
function startUIActionPolling() {
  if (_uiActionPollingInterval) return;  // già attivo
  console.log('[VOICE] polling /ui/pending avviato');
  _uiActionPollingInterval = setInterval(async () => {
    try {
      const r    = await fetch(`${VOICE_BACKEND}/ui/pending`);
      const data = await r.json();
      if (data.action) handleVoiceUIAction(data.action);
    } catch (e) {}
  }, 1500);
}
function stopUIActionPolling() {
  if (_uiActionPollingInterval) {
    clearInterval(_uiActionPollingInterval);
    _uiActionPollingInterval = null;
    console.log('[VOICE] polling /ui/pending fermato');
  }
}

// ── Azioni UI ─────────────────────────────────────────────────
async function handleVoiceUIAction(action) {
  const type   = action.type;
  const index  = action.index ?? 0;
  const sender = (action.sender || '').toLowerCase();
  const mailApi = window.ademail;
  const statusEl = byId('voiceStatus');

  if (type === 'open_mail') {
    let target = null;
    if (sender && currentMailList.length) {
      target = resolveVoiceMailTarget(currentMailList, sender);
    }
    if (!target && sender && mailApi?.searchMail) {
      try {
        const queries = [sender, ...voiceMailNeedleTokens(sender)];
        const merged = [];
        const seenIds = new Set();
        for (const query of queries) {
          if (!query) continue;
          const results = await mailApi.searchMail(query, activeAccountId);
          if (!Array.isArray(results) || !results.length) continue;
          for (const item of results) {
            const id = String(item?.id || '').trim();
            if (!id || seenIds.has(id)) continue;
            seenIds.add(id);
            merged.push(item);
          }
        }
        if (merged.length) {
          if (typeof renderMailList === 'function') {
            renderMailList(merged);
          } else {
            currentMailList = merged;
          }
          target = resolveVoiceMailTarget(merged, sender) || merged[0];
        }
      } catch (e) {
        console.error('[VOICE] searchMail sender:', e);
      }
    }
    if (!target && !sender && (!currentMailList || !currentMailList.length) && typeof refreshCurrentFolder === 'function') {
      try {
        await refreshCurrentFolder();
      } catch (e) {
        console.error('[VOICE] refreshCurrentFolder:', e);
      }
    }
    if (!target && currentMailList[index]) target = currentMailList[index];
    if (target) {
      currentMailIndex = currentMailList.indexOf(target);
      if (currentMailIndex < 0) {
        currentMailIndex = currentMailList.findIndex(m => String(m?.id || '') === String(target?.id || ''));
      }
      await openMail(target.id);
      document.querySelectorAll('.mail-item').forEach((el, i) => {
        el.classList.toggle('selected', i === currentMailIndex);
      });
      if (action.auto_read) {
        setTimeout(() => byId('btnAscolta')?.click(), 250);
      }
      if (statusEl) {
        const senderLabel = target.from?.emailAddress?.name || target.from?.emailAddress?.address || 'mail trovata';
        statusEl.textContent = `Apro: ${senderLabel}`;
        setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 2500);
      }
    } else if (statusEl) {
      statusEl.textContent = sender
        ? `Non ho trovato una mail chiara per "${sender}".`
        : 'Non ho trovato la mail richiesta.';
      setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
    }
  } else if (type === 'read_mail') {
    byId('btnAscolta')?.click();
  } else if (type === 'summarize_mail') {
    if (!selectedMailId && currentMailList[0]) {
      currentMailIndex = 0;
      await openMail(currentMailList[0].id);
    }
    byId('btnRiassumi')?.click();
  } else if (type === 'reply_mail') {
    // La risposta apre una FINESTRA separata: passa l'istruzione via funzione globale
    // (byId('replyText') non funziona, la textarea è nell'altra finestra).
    const instr = action.reply_instruction || action.text || '';
    if (typeof window.openReplyWithInstruction === 'function') {
      window.openReplyWithInstruction(instr);
    } else {
      byId('btnShowReply')?.click();  // fallback
    }
  } else if (type === 'fill_reply_text') {
    const instr = action.reply_instruction || action.text || '';
    if (typeof window.openReplyWithInstruction === 'function') {
      window.openReplyWithInstruction(instr);
    } else {
      byId('btnShowReply')?.click();
    }
  } else if (type === 'generate_reply') {
    byId('btnShowReply')?.click();
    setTimeout(() => byId('btnGenerateReply')?.click(), 250);
  } else if (type === 'send_reply') {
    byId('btnShowReply')?.click();
    setTimeout(() => byId('btnSendReply')?.click(), 250);
  } else if (type === 'cancel_reply') {
    byId('btnHideReply')?.click();
  } else if (type === 'next_mail') {
    const next = currentMailIndex + 1;
    if (currentMailList[next]) { currentMailIndex = next; await openMail(currentMailList[next].id); }
  } else if (type === 'prev_mail') {
    const prev = currentMailIndex - 1;
    if (prev >= 0 && currentMailList[prev]) { currentMailIndex = prev; await openMail(currentMailList[prev].id); }

  } else if (type === 'stop') {
    // Stop ascolto/lettura
    if (typeof stopVoicePlaybackOnly === 'function') stopVoicePlaybackOnly();
    if (typeof window.stopMailReading === 'function') window.stopMailReading();  // ferma lettura mail (ASCOLTA)
    stopVoice();

  } else if (type === 'refresh_mail') {
    // Aggiorna cartella corrente
    if (typeof refreshCurrentFolder === 'function') await refreshCurrentFolder();

  } else if (type === 'list_recent') {
    // Leggi ultime N mail (default 5)
    const n = action.count || 5;
    const recent = currentMailList.slice(0, n);
    if (recent.length && typeof renderMailList === 'function') {
      renderMailList(recent);
    }

  } else if (type === 'move_mail') {
    // Sposta mail corrente
    if (selectedMailId && typeof openMoveMailPanel === 'function') {
      await openMoveMailPanel(selectedMailId);
    }

  } else if (type === 'switch_account') {
    // Cambia account per nome
    const targetName = (action.account_name || '').toLowerCase();
    const sel = document.getElementById('accountSelect');
    if (sel && targetName) {
      const opt = Array.from(sel.options).find(o =>
        o.text.toLowerCase().includes(targetName)
      );
      if (opt) {
        sel.value = opt.value;
        sel.dispatchEvent(new Event('change'));
      }
    }

  } else if (type === 'new_mail') {
    // Scrivi nuova mail
    if (window.electronAPI?.openNewMailWindow) {
      window.electronAPI.openNewMailWindow({
        account_id: activeAccountId,
        to: action.to || '',
        subject: action.subject || '',
      });
    } else {
      byId('btnNewMail')?.click();
    }

  } else if (type === 'new_appointment') {
    // Fissa appuntamento — apre calendario
    if (window.electronAPI?.openCalendarWindow) {
      window.electronAPI.openCalendarWindow();
    }

  } else if (type === 'delete_mail') {
    // Elimina mail corrente
    byId('btnDelete')?.click();

  } else if (type === 'spam_mail') {
    // Sposta in spam
    byId('btnSpam')?.click();
  }
}

// ── Audio ─────────────────────────────────────────────────────
function playAudioB64(b64) {
  if (!b64) return;
  try {
    if (currentVoiceAudio) {
      try { currentVoiceAudio.pause(); } catch (e) {}
      currentVoiceAudio = null;
    }
    voicePlaybackActive = true;
    const blob  = new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], { type: 'audio/mpeg' });
    const url   = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentVoiceAudio = audio;
    audio.play();
    audio.onended = () => {
      voicePlaybackActive = false;
      currentVoiceAudio = null;
      URL.revokeObjectURL(url);
    };
    audio.onerror = () => {
      voicePlaybackActive = false;
      currentVoiceAudio = null;
      URL.revokeObjectURL(url);
    };
  } catch (e) {
    voicePlaybackActive = false;
    currentVoiceAudio = null;
    console.error('[VOICE] playAudio:', e);
  }
}

function cleanVoiceCommand(text) {
  return String(text || '').trim().replace(/\s+/g, ' ');
}

function voiceMailNeedleTokens(text) {
  return cleanVoiceCommand(text)
    .toLowerCase()
    .split(/\s+/)
    .map(token => token.trim())
    .filter(token => token.length >= 3);
}

function voiceMailMatchScore(message, needle) {
  if (!message || !needle) return -1;
  const senderName = String(message.from?.emailAddress?.name || '').toLowerCase();
  const senderAddr = String(message.from?.emailAddress?.address || '').toLowerCase();
  const subject = String(message.subject || '').toLowerCase();
  const preview = String(message.bodyPreview || '').toLowerCase();
  const haystack = `${senderName} ${senderAddr} ${subject} ${preview}`.trim();
  const tokens = voiceMailNeedleTokens(needle);
  if (!tokens.length) return -1;

  let score = 0;
  let matched = 0;
  for (const token of tokens) {
    if (!haystack.includes(token)) continue;
    matched += 1;
    score += 8;
    if (senderName.includes(token)) score += 10;
    if (senderAddr.includes(token)) score += 9;
    if (subject.includes(token)) score += 4;
  }
  if (!matched) return -1;
  if (matched < tokens.length) score -= (tokens.length - matched) * 4;
  return score;
}

function resolveVoiceMailTarget(messages, needle) {
  const items = Array.isArray(messages) ? messages.filter(Boolean) : [];
  if (!items.length || !needle) return null;
  let best = null;
  let bestScore = -1;
  for (const msg of items) {
    const score = voiceMailMatchScore(msg, needle);
    if (score > bestScore) {
      best = msg;
      bestScore = score;
    }
  }
  return bestScore >= 8 ? best : null;
}

function isVoiceStopCommand(text) {
  const normalized = cleanVoiceCommand(text).toLowerCase().replace(/[^a-zàèéìòù\s]/g, '').replace(/\s+/g, ' ').trim();
  if (!normalized) return false;
  // Match esatto su varianti comuni
  const stopExact = ['stop','ade stop','fermati','ade fermati','smetti','ade smetti',
    'basta','ade basta','silenzio','ade silenzio','taci','ade taci',
    'spegni voce','ade spegni voce','disattiva voce','ade disattiva voce',
    'interrompi ascolto','ade interrompi ascolto'];
  if (stopExact.includes(normalized)) return true;
  // Match regex per frasi più libere — matcha anche con parole intorno
  if (/\b(stop|ferma(ti)?|basta|smetti|silenzio|taci|spegni la voce|disattiva la voce|interrompi)\b/.test(normalized)) return true;
  // Whisper trascrive "basta" come "asta" (taglia la b)
  if (/^(asta|hasta|ast|basta)$/.test(normalized)) return true;
  // Whisper trascrive "stop" come "ciao" in italiano
  if (/^(ciao|chao|ciao!)$/.test(normalized)) return true;
  return false;
}

function stopVoicePlaybackOnly() {
  try {
    if (currentVoiceAudio) {
      currentVoiceAudio.pause();
      currentVoiceAudio.currentTime = 0;
    }
  } catch (e) {}
  currentVoiceAudio = null;
  voicePlaybackActive = false;
}

document.addEventListener('ade-voice-playback', (event) => {
  voicePlaybackActive = Boolean(event?.detail?.active);
});

// ── Processa audio registrato ─────────────────────────────────
async function processVoiceBlob(blob, options = {}) {
  if (voiceProcessing) return;
  if (!vadActive && !options.stopOnly) return; // scarta se VAD già fermato
  voiceProcessing = true;
  setVoiceState('processing');
  voiceStopRequested = false;
  voiceRequestAbortController = new AbortController();

  const statusEl = byId('voiceStatus');

  try {
    // 1. Trascrivi con Whisper
    const formData = new FormData();
    formData.append('audio', blob, 'voice.webm');
    const resp = await fetch(`${VOICE_BACKEND}/voice/transcribe`, {
      method: 'POST',
      body:   formData,
      signal: voiceRequestAbortController.signal,
    });
    if (!resp.ok) throw new Error(`voice/transcribe HTTP ${resp.status}`);
    const { text } = await resp.json();
    console.log('[VOICE] Trascritto:', text);

    const cleanedText = cleanVoiceCommand(text);
    if (!cleanedText) {
      setVoiceState('listening');
      voiceProcessing = false;
      return;
    }

    // Anti-hallucination: blocca trascrizioni ripetitive di Whisper
    const words = cleanedText.split(/\s+/);
    if (words.length > 12) {
      const uniqueWords = new Set(words.map(w => w.toLowerCase()));
      if (uniqueWords.size < words.length * 0.4) {
        console.log('[VOICE] Hallucination ripetitiva, scarto');
        setVoiceState('listening');
        voiceProcessing = false;
        return;
      }
    }
    // Blacklist hallucination note di Whisper (sottotitoli video, rumori)
    const WHISPER_BLACKLIST = [
      'amara.org', 'sottotitoli creati', 'grazie per aver guardato',
      'iscriviti al canale', 'metti mi piace', 'seguici su',
      'thank you for watching', 'please subscribe', 'subtitles by',
      'transcribed by', 'traduzione a cura', 'sottotitolato da',
      'al prossimo episodio', 'edgy il sole',
    ];
    const lowerText = cleanedText.toLowerCase();
    if (WHISPER_BLACKLIST.some(b => lowerText.includes(b))) {
      console.log('[VOICE] Blacklist hallucination, scarto:', cleanedText.slice(0, 40));
      setVoiceState('listening');
      voiceProcessing = false;
      return;
    }

    console.log('[VOICE] cleanedText:', JSON.stringify(cleanedText));
    console.log('[VOICE] isStop:', isVoiceStopCommand(cleanedText));
    if (isVoiceStopCommand(cleanedText)) {
      if (statusEl) {
        statusEl.textContent = 'Voce fermata';
        setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 1500);
      }
      // Ferma sempre tutto — sia audio che VAD
      // Prima ferma audio in riproduzione
      if (typeof currentVoiceAudio !== 'undefined' && currentVoiceAudio) {
        try { currentVoiceAudio.pause(); currentVoiceAudio.currentTime = 0; } catch(e) {}
        currentVoiceAudio = null;
      }
      // Poi ferma tutti gli audio nella pagina
      document.querySelectorAll('audio').forEach(a => { try { a.pause(); a.currentTime = 0; } catch(e) {} });
      stopVoicePlaybackOnly();
      stopVoice();
      return;
    }

    if (options.stopOnly) {
      if (statusEl) {
        statusEl.textContent = 'Di\' "stop" per interrompere la lettura.';
        setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 1500);
      }
      return;
    }

    if (statusEl) statusEl.textContent = `"${cleanedText}"`;

    // 2. Interpreta comando
    const cmdResp = await fetch(`${VOICE_BACKEND}/voice/command`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ text: cleanedText, context: voiceContext }),
      signal:  voiceRequestAbortController.signal,
    });
    if (!cmdResp.ok) throw new Error(`voice/command HTTP ${cmdResp.status}`);
    const cmd = await cmdResp.json();

    if (cmd.audio_b64) playAudioB64(cmd.audio_b64);

    if (cmd.is_ui_action && cmd.action) {
      await handleVoiceUIAction({
        type: cmd.action,
        ...(cmd.params || {}),
        ...(cmd.extra || {}),
      });
    }

    if (cmd.action === 'list_mail' && cmd.extra?.mails) {
      const subjects = cmd.extra.mails.map((m, i) => `${i+1}. ${m.subject}`).join('\n');
      if (statusEl) statusEl.textContent = subjects;
      setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 8000);
    } else {
      setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
    }

    if (cmd.extra?.mail_id) {
      voiceContext.mail_id    = cmd.extra.mail_id;
      voiceContext.mail_index = cmd.extra.mail_index ?? voiceContext.mail_index;
    }
    if (cmd.extra?.pending_send) voiceContext.pending_send = true;
    if (['confirm_send', 'cancel'].includes(cmd.action)) voiceContext.pending_send = false;

  } catch (e) {
    if (e?.name === 'AbortError') {
      console.log('[VOICE] processVoiceBlob abortito');
      return;
    }
    console.error('[VOICE] processVoiceBlob:', e);
    if (statusEl) { statusEl.textContent = 'Errore voce'; setTimeout(() => { statusEl.textContent = ''; }, 3000); }
  } finally {
    voiceRequestAbortController = null;
    voiceProcessing = false;
    setVoiceState(vadActive ? 'listening' : 'off');
  }
}

// ── VAD loop — analizza volume ogni 100ms ─────────────────────
function startVADLoop(analyser) {
  const data = new Uint8Array(analyser.fftSize);

  function tick() {
    if (!vadActive) return;

    analyser.getByteTimeDomainData(data);

    // Calcola volume RMS
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128);
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);

    const threshold = voicePlaybackActive ? PLAYBACK_STOP_THRESHOLD : VOICE_THRESHOLD;

    if (rms > threshold) {
      // Voce rilevata
      if (!vadSpeaking) {
        vadSpeaking   = true;
        vadVoiceStart = Date.now();
        vadChunks     = [];
        vadStopOnlyMode = voicePlaybackActive;
        if (vadRecorder && vadRecorder.state === 'inactive') {
          vadRecorder.start();
          setVoiceState('speaking');
          console.log('[VOICE] Voce rilevata, inizio registrazione');
        }
      }
      // Reset timer silenzio
      clearTimeout(vadSilenceTimer);
      vadSilenceTimer = setTimeout(() => {
        if (vadSpeaking) {
          vadSpeaking = false;
          const duration = Date.now() - vadVoiceStart;
          if (vadRecorder && vadRecorder.state === 'recording') {
            vadRecorder.stop();
            console.log(`[VOICE] Silenzio rilevato, stop (${duration}ms)`);
          }
        }
      }, SILENCE_DELAY);

    }

    requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
}

// ── Avvia VAD ─────────────────────────────────────────────────
async function startVoice() {
  console.log('[VOICE] startVoice chiamato');
  startUIActionPolling();
  try {
    voiceStopRequested = false;
    vadStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

    // AudioContext per VAD
    vadAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = vadAudioCtx.createMediaStreamSource(vadStream);
    vadAnalyser  = vadAudioCtx.createAnalyser();
    vadAnalyser.fftSize = 256;
    source.connect(vadAnalyser);

    // MediaRecorder per catturare audio
    vadRecorder = new MediaRecorder(vadStream, { mimeType: 'audio/webm' });
    vadRecorder.ondataavailable = e => { if (e.data.size > 0) vadChunks.push(e.data); };
    vadRecorder.onstop = () => {
      if (voiceStopRequested || !vadActive) {
        vadChunks = [];
        vadStopOnlyMode = false;
        return;
      }
      const duration = Date.now() - (vadVoiceStart || Date.now());
      if (duration >= MIN_VOICE_MS && vadChunks.length > 0) {
        const blob = new Blob(vadChunks, { type: 'audio/webm' });
        processVoiceBlob(blob, { stopOnly: vadStopOnlyMode });
      }
      vadChunks = [];
      vadStopOnlyMode = false;
    };

    vadActive = true;
    setVoiceState('listening');
    startVADLoop(vadAnalyser);
    console.log('[VOICE] VAD avviato');

  } catch (e) {
    console.error('[VOICE] startVoice error:', e);
    setVoiceState('error');
  }
}

// ── Ferma VAD ─────────────────────────────────────────────────
function stopVoice() {
  voiceStopRequested = true;
  vadActive = false;
  stopUIActionPolling();
  clearTimeout(vadSilenceTimer);
  clearTimeout(voiceRestartTimer);
  try { voiceRequestAbortController?.abort(); } catch (e) {}
  try {
    if (currentVoiceAudio) {
      currentVoiceAudio.pause();
      currentVoiceAudio.currentTime = 0;
    }
  } catch (e) {}
  currentVoiceAudio = null;
  voicePlaybackActive = false;
  try { vadRecorder?.stop(); } catch (e) {}
  try { vadStream?.getTracks().forEach(t => t.stop()); } catch (e) {}
  try { vadAudioCtx?.close(); } catch (e) {}
  vadChunks = [];
  vadRecorder = null;
  vadStream   = null;
  vadAudioCtx = null;
  vadAnalyser = null;
  vadSpeaking = false;
  vadVoiceStart = null;
  vadStopOnlyMode = false;
  setVoiceState('off');
  console.log('[VOICE] VAD fermato');
}

// ── Bind ──────────────────────────────────────────────────────
function bindVoice() {
  console.log('[VOICE] bindVoice chiamato');

  // Bottone principale (reply panel)
  const btn = byId('btnVoice');
  if (btn) {
    btn.addEventListener('click', () => {
      if (vadActive) stopVoice();
      else startVoice();
    });
    btn.title = 'Ascolto always-on — di\' "ade ..." per un comando';
  }

  // Bottone sidebar
  const btnSidebar = byId('btnVoiceCommand');
  if (btnSidebar) {
    btnSidebar.addEventListener('click', () => {
      if (vadActive) stopVoice();
      else startVoice();
    });
  }

  setVoiceState('off');
  // Polling NON parte all'avvio — solo quando Sofia viene attivata
}

console.log('[VOICE] voice_mail.js caricato, bindVoice:', typeof bindVoice);
