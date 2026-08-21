const EXAMPLES = [
  "For God so loved the world that he gave his only begotten Son, that whosoever believeth in him should not perish but have everlasting life.",
  "Even though I walk through the darkest valley I will fear no evil, for you are with me. Your rod and your staff they comfort me.",
  "Think about that young man who left home, wasted everything his father gave him, ended up starving among pigs — and then came to his senses and returned home. His father saw him from far off and ran to embrace him.",
  "We are more than conquerors through him who loved us. Nothing — not death, not life, not angels or rulers — can separate us from the love of God. So put on the whole armor of God and stand firm."
];

const ALL_TRANSLATIONS  = ["KJV", "NIV", "NKJV", "NLT", "AMP"];
const SILENCE_DELAY     = 1500;   // ms of silence before auto-detect triggers
const MIN_NEW_CHARS     = 8;      // minimum new characters before triggering

let recognition      = null;
let isListening      = false;
let lastDetections   = [];
let autoDetectTimer  = null;
let lastProcessedLen = 0;
let cardCounter      = 0;
const seenReferences = new Set(); // tracks references already shown this session

// ── Live navigation state ─────────────────────────────────────────────────────
let currentLiveRef = null;
let currentLiveTranslation = 'KJV';
let selectedThemeId = 'default_black';
let allThemesCache = [];

// Auto-send: when enabled, high-confidence detections go live automatically,
// no manual "Send to Live" click needed. Persisted across sessions.
let autoSendEnabled = localStorage.getItem('autoSendEnabled') === 'true';

function toggleAutoSend() {
  autoSendEnabled = document.getElementById('autoSendToggle').checked;
  localStorage.setItem('autoSendEnabled', autoSendEnabled);
}

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

function getMinConfidence() {
  return document.getElementById('confidenceFilter')?.value || 'medium';
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function loadEx(i) {
  const ta = document.getElementById('transcriptBox');
  ta.value = EXAMPLES[i];
  lastProcessedLen = 0;
  scheduleAutoDetect();
}

function setStatus(msg) {
  document.getElementById('statusLine').innerHTML = msg;
}

// ── Auto-detect scheduler ─────────────────────────────────────────────────────
// Called whenever new text arrives (mic result OR keystroke OR paste)

// Regex to spot explicit reference calls in new text
// Matches: "let's have John 3:16", "turn to Romans 8:28", bare "John 3:16", etc.
const DIRECT_REF_RE = /(?:let['']?s\s+(?:have|read|go\s+to|open\s+to|look\s+at)|turn\s+to|open\s+to|read|go\s+to)?\s*(?:[123]\s*)?(?:genesis|exodus|leviticus|numbers|deuteronomy|joshua|judges|ruth|samuel|kings|chronicles|ezra|nehemiah|esther|job|psalms?|proverbs?|ecclesiastes|song|isaiah|jeremiah|lamentations|ezekiel|daniel|hosea|joel|amos|obadiah|jonah|micah|nahum|habakkuk|zephaniah|haggai|zechariah|malachi|matthew|mark|luke|john|acts|romans|corinthians?|galatians|ephesians|philippians|colossians|thessalonians?|timothy|titus|philemon|hebrews|james|peter|jude|revelation|gen|ex|lev|num|deut|josh|judg|ps|prov|eccl|isa|jer|lam|ezek|dan|hos|zech|mal|matt|mk|lk|jn|rom|gal|eph|phil|col|thess|tim|heb|jas|rev)\s+\d+:\d+/i;

function scheduleAutoDetect() {
  const ta = document.getElementById('transcriptBox');
  const newText = ta.value.trim().slice(lastProcessedLen).trim();

  // If the new text contains an explicit reference — detect immediately, no wait
  if (newText.length >= MIN_NEW_CHARS && DIRECT_REF_RE.test(newText)) {
    clearTimeout(autoDetectTimer);
    detectAndAppend(newText);
    return;
  }

  // Otherwise wait for silence before detecting
  clearTimeout(autoDetectTimer);
  autoDetectTimer = setTimeout(() => {
    const fresh = document.getElementById('transcriptBox').value.trim().slice(lastProcessedLen).trim();
    if (fresh.length >= MIN_NEW_CHARS) {
      detectAndAppend(fresh);
    }
  }, SILENCE_DELAY);
}

// ── Textarea event listeners — auto-detect on type/paste ─────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const ta = document.getElementById('transcriptBox');

  // Fill in the OBS overlay URL dynamically based on current host
  const overlayUrlEl = document.getElementById('overlayUrl');
  if (overlayUrlEl) {
    overlayUrlEl.textContent = `${window.location.origin}/overlay`;
  }

  // Typing
  ta.addEventListener('input', () => {
    scheduleAutoDetect();
  });

  // Paste — give browser time to update value first
  ta.addEventListener('paste', () => {
    setTimeout(scheduleAutoDetect, 50);
  });
});

// ── Microphone ────────────────────────────────────────────────────────────────

function toggleMic() {
  if (!SR) { setStatus('Web Speech API not supported — use Chrome'); return; }
  isListening ? stopListening() : startListening();
}

function startListening() {
  recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  const ta = document.getElementById('transcriptBox');

  recognition.onstart = () => {
    isListening = true;
    document.getElementById('micBtn').className = 'mic-btn listening';
    document.getElementById('micLabel').innerHTML = '<span class="live-dot"></span>&nbsp;Listening&hellip;';
    setStatus('Listening — speak now');
  };

  recognition.onresult = e => {
    const transcript = e.results[e.results.length - 1][0].transcript.trim();
    if (!transcript) return;

    ta.value = (ta.value.trim() ? ta.value.trim() + ' ' : '') + transcript;
    ta.scrollTop = ta.scrollHeight;

    // Schedule auto-detect after speech silence
    scheduleAutoDetect();
  };

  recognition.onerror = e => {
    if (e.error !== 'no-speech') {
      setStatus('Mic error: ' + e.error);
      stopListening();
    }
  };

  recognition.onend = () => {
    if (isListening) {
      try { recognition.start(); } catch(e) {}
    }
  };

  recognition.start();
}

function stopListening() {
  isListening = false;
  clearTimeout(autoDetectTimer);
  if (recognition) { recognition.onend = null; recognition.stop(); }
  document.getElementById('micBtn').className = 'mic-btn';
  document.getElementById('micLabel').textContent = 'Start Listening';
  setStatus('Click the button and speak');

  // Detect any remaining unprocessed text
  const ta = document.getElementById('transcriptBox');
  const remaining = ta.value.trim().slice(lastProcessedLen).trim();
  if (remaining.length >= MIN_NEW_CHARS) detectAndAppend(remaining);
}

// ── Clear ─────────────────────────────────────────────────────────────────────

function clearAll() {
  clearTimeout(autoDetectTimer);
  lastProcessedLen = 0;
  lastDetections = [];
  cardCounter = 0;
  seenReferences.clear();
  document.getElementById('transcriptBox').value = '';
  document.getElementById('results').innerHTML = '<div class="empty">Detections will appear here</div>';
  document.getElementById('errorBox').className = 'error-box';
  document.getElementById('clipboardBtn').disabled = true;
  setStatus('Click the button and speak');
}

// ── Reset results panel (without clearing transcript) ────────────────────────

function resetResults() {
  clearTimeout(autoDetectTimer);
  lastProcessedLen = 0;
  lastDetections = [];
  cardCounter = 0;
  seenReferences.clear();
  document.getElementById('results').innerHTML = '<div class="empty">Detections will appear here</div>';
  document.getElementById('errorBox').className = 'error-box';
  document.getElementById('clipboardBtn').disabled = true;
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function typeLabel(t) {
  return {
    direct_quote:      'Direct Quote',
    paraphrase:        'Paraphrase',
    semantic_allusion: 'Semantic Allusion',
    story_reference:   'Story Reference',
    reference_call:    'Called Reference'
  }[t] || t;
}

function buildTranslationsBlock(translations, id) {
  const hasAny = translations && Object.keys(translations).length > 0;
  const bodyId = `trans-body-${id}`;

  const rows = ALL_TRANSLATIONS.map(t => {
    const text = translations && translations[t];
    return `
      <div class="translation-row">
        <span class="trans-label">${t}</span>
        ${text
          ? `<span class="trans-text">${text}</span>`
          : `<span class="trans-missing">Not loaded — add ${t.toLowerCase()}.json to bibles/ folder</span>`}
      </div>`;
  }).join('');

  return `
    <div class="translations-section">
      <div class="translations-toggle open" onclick="toggleTranslations('${bodyId}', this)">
        <span>All Translations (${hasAny ? Object.keys(translations).length : 0} / ${ALL_TRANSLATIONS.length})</span>
        <span class="toggle-arrow">&#9660;</span>
      </div>
      <div class="translations-body open" id="${bodyId}">
        ${rows}
      </div>
    </div>`;
}

function toggleTranslations(id, toggleEl) {
  const body = document.getElementById(id);
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  toggleEl.classList.toggle('open', !isOpen);
}

// ── Core detection — appends results, never replaces ─────────────────────────

async function detectAndAppend(text) {
  if (!text || text.length < MIN_NEW_CHARS) return;

  // Advance the processed cursor immediately so overlapping calls don't re-send
  const ta = document.getElementById('transcriptBox');
  lastProcessedLen = ta.value.trim().length;

  const results = document.getElementById('results');

  // Remove empty placeholder
  const placeholder = results.querySelector('.empty');
  if (placeholder) placeholder.remove();

  // Inline loading indicator
  const loaderId = `loader-${Date.now()}`;
  const loader = document.createElement('div');
  loader.id = loaderId;
  loader.className = 'detection-loader';
  loader.innerHTML = `<div class="spinner-ring" style="width:18px;height:18px;border-width:1.5px"></div><span>Detecting&hellip;</span>`;
  results.appendChild(loader);
  results.scrollTop = results.scrollHeight;

  try {
    const res = await fetch('/detect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, min_confidence: getMinConfidence() })
    });

    document.getElementById(loaderId)?.remove();

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Detection failed');
    }

    const data = await res.json();
    const dets = data.detections || [];

    if (!dets.length) {
      const note = document.createElement('div');
      note.className = 'no-detect-note';
      note.textContent = 'No scripture detected in last segment.';
      results.appendChild(note);
      setTimeout(() => note.remove(), 3500);
      return;
    }

    // Segment divider
    const divider = document.createElement('div');
    divider.className = 'segment-divider';
    divider.innerHTML = `<span class="segment-quote">"${text.length > 80 ? text.slice(0, 80) + '&hellip;' : text}"</span>`;
    results.appendChild(divider);

    // Filter out references already shown this session
    const newDets = dets.filter(d => {
      const ref = d.reference || '';
      if (seenReferences.has(ref)) return false;
      seenReferences.add(ref);
      return true;
    });

    if (!newDets.length) {
      const note = document.createElement('div');
      note.className = 'no-detect-note';
      note.textContent = 'References already shown this session.';
      results.appendChild(note);
      setTimeout(() => note.remove(), 3500);
      return;
    }

    newDets.forEach(d => {
      cardCounter++;
      lastDetections.push(d);

      const cardId = `card-${cardCounter}`;
      const trans = d.translations || {};
      const kjvText = trans.KJV || Object.values(trans)[0] || '';

      const willAutoSend = autoSendEnabled && d.confidence === 'high';

      const card = document.createElement('div');
      card.className = 'detection-card' + (willAutoSend ? ' auto-sent' : '');
      card.id = cardId;
      card.innerHTML = `
        <div class="detection-top">
          <span class="type-pill tp-${d.type}">${typeLabel(d.type)}</span>
          <span class="ref-text">${d.reference || ''}</span>
          <span class="confidence-badge cb-${d.confidence}">${d.confidence}</span>
          ${willAutoSend ? '<span class="auto-sent-badge">&#9889; Auto-sent</span>' : ''}
          <button class="card-delete-btn" onclick="deleteCard('${cardId}', ${cardCounter - 1})" title="Dismiss">&#x2715;</button>
        </div>
        <div class="detection-body">
          <div class="phrase-block">"${d.detected_phrase || ''}"</div>
          ${d.explanation ? `<div class="expl">${d.explanation}</div>` : ''}
          <div class="card-actions-row">
            <button class="btn-preview" onclick='previewSlide(${JSON.stringify(d.reference || "")}, ${JSON.stringify(kjvText)}, "KJV")'>
              &#128065; Preview
            </button>
            <button class="btn-send-live" onclick='sendToLive(${JSON.stringify(d.reference || "")}, ${JSON.stringify(kjvText)}, "KJV")'>
              &#9658; Send to Live
            </button>
          </div>
          ${buildTranslationsBlock(d.translations, cardCounter)}
        </div>`;
      results.appendChild(card);

      if (willAutoSend) {
        sendToLive(d.reference || '', kjvText, 'KJV');
      }
    });

    document.getElementById('clipboardBtn').disabled = false;
    results.scrollTop = results.scrollHeight;
    // No auto-reset — cards stay until manually cleared or individually dismissed

  } catch (err) {
    document.getElementById(loaderId)?.remove();
    const eb = document.createElement('div');
    eb.className = 'error-box visible';
    eb.style.marginTop = '0.5rem';
    eb.textContent = 'Error: ' + err.message;
    results.appendChild(eb);
  }
}

// Manual detect — sends only unprocessed text
async function detect() {
  const ta = document.getElementById('transcriptBox');
  const newText = ta.value.trim().slice(lastProcessedLen).trim();
  const textToSend = newText.length >= MIN_NEW_CHARS ? newText : ta.value.trim();
  if (textToSend) {
    clearTimeout(autoDetectTimer);
    await detectAndAppend(textToSend);
  }
}

// Ctrl/Cmd + Enter shortcut
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') detect();
});

// ── Send to Live / Manual Search ──────────────────────────────────────────────

async function sendToLive(reference, text, translation, kind = 'scripture', songId = '', sectionIndex = 0) {
  try {
    const res = await fetch('/live/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference, text, translation,
        theme_id: selectedThemeId,
        kind, song_id: songId, section_index: sectionIndex
      })
    });
    if (!res.ok) throw new Error('Failed to send to live');

    // Track what's live now so arrow-key navigation knows where to move from
    currentLiveRef = kind === 'scripture' ? reference : null;
    currentLiveTranslation = translation;

    const liveStatus = document.getElementById('liveStatus');
    if (liveStatus) {
      liveStatus.innerHTML = `Live: <strong>${reference}</strong> (${translation}) &nbsp;&mdash;&nbsp; use &larr; / &rarr; to navigate`;
      liveStatus.classList.add('active');
    }
  } catch (err) {
    console.error('sendToLive error:', err);
  }
}

async function clearLive() {
  try {
    await fetch('/live/clear', { method: 'POST' });
    currentLiveRef = null;
    const liveStatus = document.getElementById('liveStatus');
    if (liveStatus) {
      liveStatus.textContent = 'No live slide active';
      liveStatus.classList.remove('active');
    }
  } catch (err) {
    console.error('clearLive error:', err);
  }
}

// ── Verse navigation (→ / ←) ───────────────────────────────────────────────────

async function navigateVerse(direction) {
  if (!currentLiveRef) {
    const liveStatus = document.getElementById('liveStatus');
    if (liveStatus) {
      liveStatus.textContent = 'Send a verse live first, then use ← / → to navigate';
      setTimeout(() => {
        if (!currentLiveRef) liveStatus.textContent = 'No live slide active';
      }, 2000);
    }
    return;
  }

  try {
    const res = await fetch(
      `/verse-nav?ref=${encodeURIComponent(currentLiveRef)}&direction=${direction}&translation=${currentLiveTranslation}`
    );
    if (!res.ok) {
      const err = await res.json();
      const liveStatus = document.getElementById('liveStatus');
      if (liveStatus) liveStatus.innerHTML = `<span style="color:var(--rose)">${err.detail || 'No further verses'}</span>`;
      return;
    }

    const data = await res.json();
    await sendToLive(data.reference, data.text, currentLiveTranslation);
  } catch (err) {
    console.error('navigateVerse error:', err);
  }
}

// Arrow keys navigate verses — but not while typing in an input/textarea
document.addEventListener('keydown', e => {
  const tag = document.activeElement?.tagName;
  const isTyping = tag === 'INPUT' || tag === 'TEXTAREA';
  if (isTyping) return;

  if (e.key === 'ArrowRight') { e.preventDefault(); navigateVerse('next'); }
  if (e.key === 'ArrowLeft')  { e.preventDefault(); navigateVerse('prev'); }
});

// ── Manual search — text or voice, all 5 translations shown ───────────────────

let searchRecognition = null;

function searchByVoice() {
  if (!SR) {
    const resultBox = document.getElementById('manualSearchResult');
    resultBox.innerHTML = '<div class="search-error">Voice search not supported — use Chrome</div>';
    resultBox.classList.add('visible');
    return;
  }

  const micBtn = document.getElementById('searchMicBtn');
  micBtn.classList.add('listening');
  micBtn.disabled = true;

  searchRecognition = new SR();
  searchRecognition.continuous = false;
  searchRecognition.interimResults = false;
  searchRecognition.lang = 'en-US';

  searchRecognition.onresult = e => {
    const transcript = e.results[0][0].transcript.trim();
    document.getElementById('manualSearchInput').value = transcript;
    manualSearch();
  };

  searchRecognition.onerror = () => {
    micBtn.classList.remove('listening');
    micBtn.disabled = false;
  };

  searchRecognition.onend = () => {
    micBtn.classList.remove('listening');
    micBtn.disabled = false;
  };

  searchRecognition.start();
}

async function manualSearch() {
  const input = document.getElementById('manualSearchInput');
  const ref = input.value.trim();
  if (!ref) return;

  const resultBox = document.getElementById('manualSearchResult');
  resultBox.innerHTML = '<div class="search-loading">Searching&hellip;</div>';
  resultBox.classList.add('visible');

  try {
    const res = await fetch(`/search?ref=${encodeURIComponent(ref)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Not found');
    }

    const data = await res.json();
    const translations = data.translations || {};

    const rows = ALL_TRANSLATIONS.map(t => {
      const text = translations[t];
      return `
        <div class="translation-row search-translation-row">
          <span class="trans-label">${t}</span>
          ${text
            ? `<span class="trans-text">${text}</span>
               <button class="btn-preview-sm" onclick='previewSlide(${JSON.stringify(data.reference)}, ${JSON.stringify(text)}, "${t}")'>Preview</button>
               <button class="btn-send-live-sm" onclick='sendToLive(${JSON.stringify(data.reference)}, ${JSON.stringify(text)}, "${t}")'>
                 Send Live
               </button>`
            : `<span class="trans-missing">Not loaded</span>`}
        </div>`;
    }).join('');

    resultBox.innerHTML = `
      <div class="search-result-card">
        <div class="search-result-ref">${data.reference}</div>
        <div class="search-translations">${rows}</div>
      </div>`;
  } catch (err) {
    resultBox.innerHTML = `<div class="search-error">${err.message}</div>`;
  }
}

// ── Delete single card ───────────────────────────────────────────────────────

function deleteCard(cardId, detectionIndex) {
  // Remove the card element
  const card = document.getElementById(cardId);
  if (!card) return;

  // Also remove the segment divider above it if it has no siblings after removal
  const prev = card.previousElementSibling;

  card.style.transition = 'opacity 0.2s, transform 0.2s';
  card.style.opacity = '0';
  card.style.transform = 'translateX(12px)';

  setTimeout(() => {
    card.remove();
    // Remove orphaned segment divider (divider with no detection card after it)
    if (prev && prev.classList.contains('segment-divider')) {
      const next = prev.nextElementSibling;
      if (!next || next.classList.contains('segment-divider') || !next.classList.contains('detection-card')) {
        prev.remove();
      }
    }
    // Remove from lastDetections and seenReferences so it can be detected again
    const removed = lastDetections.splice(detectionIndex, 1);
    if (removed[0]?.reference) seenReferences.delete(removed[0].reference);
    // If no cards left, show empty state
    const results = document.getElementById('results');
    if (!results.querySelector('.detection-card')) {
      results.innerHTML = '<div class="empty">Detections will appear here</div>';
      document.getElementById('clipboardBtn').disabled = true;
    }
  }, 200);
}

// ── Clipboard ─────────────────────────────────────────────────────────────────

function copyLastToClipboard() {
  if (!lastDetections.length) return;
  const lines = lastDetections.map(d => {
    const kjvText = d.translations && d.translations.KJV ? d.translations.KJV : '';
    return `${d.reference}\n${kjvText}`;
  });
  navigator.clipboard.writeText(lines.join('\n\n')).then(() => {
    const btn = document.getElementById('clipboardBtn');
    const lbl = document.getElementById('clipboardBtnLabel');
    btn.classList.add('copied');
    lbl.textContent = 'Copied!';
    setTimeout(() => { btn.classList.remove('copied'); lbl.textContent = 'Copy Last Detection'; }, 2000);
  });
}

// ── Song Library ────────────────────────────────────────────────────────────

let allSongsCache = [];
let editingSongId = null;         // null = creating new song
let currentLiveSong = null;       // { song data, sectionIndex } when a song is live

async function loadSongList(query = '') {
  const listEl = document.getElementById('songList');
  listEl.innerHTML = '<div class="search-loading">Loading&hellip;</div>';

  try {
    const res = await fetch(`/songs?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    allSongsCache = data.songs || [];

    if (!allSongsCache.length) {
      listEl.innerHTML = '<div class="empty">No songs yet — click "+ Add Song" to create one.</div>';
      return;
    }

    listEl.innerHTML = allSongsCache.map(s => `
      <div class="song-list-item" onclick="openSong('${s.id}')">
        <div>
          <div class="song-list-title">${s.title}</div>
          ${s.author ? `<div class="song-list-author">${s.author}</div>` : ''}
        </div>
        <span class="song-list-arrow">&#8250;</span>
      </div>
    `).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="search-error">${err.message}</div>`;
  }
}

let songSearchTimer = null;
function songSearchDebounced() {
  clearTimeout(songSearchTimer);
  songSearchTimer = setTimeout(() => {
    loadSongList(document.getElementById('songSearchInput').value.trim());
  }, 300);
}

// Open a song — show its sections as sendable slide cards
async function openSong(songId) {
  try {
    const res = await fetch(`/songs/${songId}`);
    if (!res.ok) throw new Error('Song not found');
    const song = await res.json();

    currentLiveSong = { song, sectionIndex: 0 };

    const listEl = document.getElementById('songList');
    listEl.innerHTML = `
      <div class="song-detail-header">
        <button class="btn-sm" onclick="loadSongList()">&larr; Back to list</button>
        <button class="btn-sm" onclick="openSongEditor('${songId}')">Edit</button>
      </div>
      <div class="song-detail-title">${song.title}</div>
      ${song.author ? `<div class="song-list-author">${song.author}</div>` : ''}
      <div class="song-sections-list">
        ${song.sections.map((sec, i) => `
          <div class="song-section-card">
            <div class="song-section-label">${sec.label}</div>
            <div class="song-section-lines">${sec.lines.join('<br>')}</div>
            <div class="card-actions-row">
              <button class="btn-preview" onclick='previewSlide(${JSON.stringify(song.title + " — " + sec.label)}, ${JSON.stringify(sec.lines.join(String.fromCharCode(10)))}, "LYRICS")'>
                &#128065; Preview
              </button>
              <button class="btn-send-live" onclick='sendSongSectionLive(${JSON.stringify(song)}, ${i})'>
                &#9658; Send to Live
              </button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  } catch (err) {
    console.error('openSong error:', err);
  }
}

// Send a specific song section live — reuses the same /live/send endpoint as scripture
async function sendSongSectionLive(song, sectionIndex) {
  const section = song.sections[sectionIndex];
  if (!section) return;

  const text = section.lines.join('\n');
  const reference = `${song.title} — ${section.label}`;

  await sendToLive(reference, text, 'LYRICS', 'song', song.id, sectionIndex);

  // Track song-specific nav state so arrow keys move between sections
  currentLiveSong = { song, sectionIndex };
  currentLiveRef = null; // not a scripture reference — disables verse-nav path
}

// Arrow-key navigation extended: if a song is live, move between its sections
const _originalNavigateVerse = navigateVerse;
navigateVerse = async function(direction) {
  if (currentLiveSong && !currentLiveRef) {
    const { song, sectionIndex } = currentLiveSong;
    const nextIndex = direction === 'next' ? sectionIndex + 1 : sectionIndex - 1;

    if (nextIndex < 0 || nextIndex >= song.sections.length) {
      const liveStatus = document.getElementById('liveStatus');
      if (liveStatus) liveStatus.innerHTML = `<span style="color:var(--rose)">No ${direction === 'next' ? 'next' : 'previous'} section in this song</span>`;
      return;
    }

    await sendSongSectionLive(song, nextIndex);
    return;
  }
  // Fall back to scripture verse navigation
  await _originalNavigateVerse(direction);
};

// ── Song editor (add/edit) ────────────────────────────────────────────────────

function openSongEditor(songId = null) {
  editingSongId = songId;
  document.getElementById('songEditorOverlay').classList.add('visible');
  document.getElementById('songSectionsList').innerHTML = '';

  const deleteBtn = document.getElementById('songDeleteBtn');

  if (songId) {
    document.getElementById('songEditorTitle').textContent = 'Edit Song';
    deleteBtn.style.display = 'inline-block';
    fetch(`/songs/${songId}`).then(r => r.json()).then(song => {
      document.getElementById('songTitleInput').value = song.title;
      document.getElementById('songAuthorInput').value = song.author || '';
      song.sections.forEach(sec => addSongSection(sec.label, sec.lines.join('\n')));
    });
  } else {
    document.getElementById('songEditorTitle').textContent = 'Add Song';
    deleteBtn.style.display = 'none';
    document.getElementById('songTitleInput').value = '';
    document.getElementById('songAuthorInput').value = '';
    addSongSection('Verse 1', '');
  }
}

function closeSongEditor() {
  document.getElementById('songEditorOverlay').classList.remove('visible');
  editingSongId = null;
}

function addSongSection(label = '', lines = '') {
  const container = document.getElementById('songSectionsList');
  const div = document.createElement('div');
  div.className = 'song-section-editor';
  div.innerHTML = `
    <div class="song-section-editor-row">
      <input type="text" class="song-section-label-input" placeholder="Verse 1 / Chorus / Bridge" value="${label}">
      <button class="card-delete-btn" onclick="this.closest('.song-section-editor').remove()">&#x2715;</button>
    </div>
    <textarea class="song-section-lines-input" placeholder="Lyric lines, one per line&hellip;">${lines}</textarea>
  `;
  container.appendChild(div);
}

async function saveSong() {
  const title = document.getElementById('songTitleInput').value.trim();
  const author = document.getElementById('songAuthorInput').value.trim();

  if (!title) {
    alert('Song title is required');
    return;
  }

  const sectionEls = document.querySelectorAll('#songSectionsList .song-section-editor');
  const sections = Array.from(sectionEls).map(el => ({
    label: el.querySelector('.song-section-label-input').value.trim() || 'Section',
    lines: el.querySelector('.song-section-lines-input').value.split('\n').filter(l => l.trim())
  })).filter(s => s.lines.length > 0);

  if (!sections.length) {
    alert('Add at least one section with lyrics');
    return;
  }

  const payload = { title, author, sections };

  try {
    const url = editingSongId ? `/songs/${editingSongId}` : '/songs';
    const method = editingSongId ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to save song');

    closeSongEditor();
    loadSongList();
  } catch (err) {
    alert('Error saving song: ' + err.message);
  }
}

async function deleteSongFromEditor() {
  if (!editingSongId) return;
  if (!confirm('Delete this song permanently?')) return;

  try {
    await fetch(`/songs/${editingSongId}`, { method: 'DELETE' });
    closeSongEditor();
    loadSongList();
  } catch (err) {
    alert('Error deleting song: ' + err.message);
  }
}

// Load song list on page load
document.addEventListener('DOMContentLoaded', () => {
  loadSongList();
});

// ── Themes / Backgrounds ────────────────────────────────────────────────────

async function loadThemes() {
  try {
    const res = await fetch('/themes');
    const data = await res.json();
    allThemesCache = data.themes || [];

    const select = document.getElementById('themeSelect');
    if (select) {
      select.innerHTML = allThemesCache.map(t =>
        `<option value="${t.id}" ${t.id === selectedThemeId ? 'selected' : ''}>${t.name}</option>`
      ).join('');
    }
  } catch (err) {
    console.error('loadThemes error:', err);
  }
}

function onThemeSelected() {
  selectedThemeId = document.getElementById('themeSelect').value;
}

function openThemeManager() {
  document.getElementById('themeManagerOverlay').classList.add('visible');
  renderThemeManagerList();
}

function closeThemeManager() {
  document.getElementById('themeManagerOverlay').classList.remove('visible');
}

function renderThemeManagerList() {
  const listEl = document.getElementById('themeManagerList');
  listEl.innerHTML = allThemesCache.map(t => `
    <div class="theme-item">
      <div class="theme-swatch" style="${themeSwatchStyle(t)}"></div>
      <div class="theme-item-name">${t.name}</div>
      ${t.id !== 'default_black' ? `<button class="card-delete-btn" onclick="deleteThemeConfirm('${t.id}')">&#x2715;</button>` : ''}
    </div>
  `).join('');
}

function themeSwatchStyle(theme) {
  if (theme.bg_type === 'image') {
    return `background-image:url('/theme-images/${theme.bg_value}');background-size:cover;background-position:center;`;
  }
  return `background:${theme.bg_value};`;
}

async function deleteThemeConfirm(themeId) {
  if (!confirm('Delete this theme?')) return;
  try {
    await fetch(`/themes/${themeId}`, { method: 'DELETE' });
    await loadThemes();
    renderThemeManagerList();
  } catch (err) {
    alert('Error deleting theme: ' + err.message);
  }
}

async function createThemeFromForm() {
  const name = document.getElementById('newThemeName').value.trim();
  const bgType = document.getElementById('newThemeBgType').value;
  const textColor = document.getElementById('newThemeTextColor').value;
  const accentColor = document.getElementById('newThemeAccentColor').value;
  const overlayOpacity = parseFloat(document.getElementById('newThemeOverlay').value) || 0.4;

  if (!name) { alert('Theme name is required'); return; }

  let bgValue = '';

  if (bgType === 'color') {
    bgValue = document.getElementById('newThemeColorValue').value;
  } else if (bgType === 'gradient') {
    bgValue = document.getElementById('newThemeGradientValue').value.trim();
    if (!bgValue) { alert('Enter a CSS gradient, e.g. linear-gradient(135deg, #1a1a2e, #16213e)'); return; }
  } else if (bgType === 'image') {
    const fileInput = document.getElementById('newThemeImageFile');
    if (!fileInput.files.length) { alert('Choose an image file'); return; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
      const uploadRes = await fetch('/themes/upload-image', { method: 'POST', body: formData });
      if (!uploadRes.ok) throw new Error('Image upload failed');
      const uploadData = await uploadRes.json();
      bgValue = uploadData.filename;
    } catch (err) {
      alert('Error uploading image: ' + err.message);
      return;
    }
  }

  try {
    const res = await fetch('/themes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, bg_type: bgType, bg_value: bgValue,
        text_color: textColor, accent_color: accentColor,
        overlay_opacity: overlayOpacity
      })
    });
    if (!res.ok) throw new Error('Failed to create theme');

    document.getElementById('newThemeName').value = '';
    await loadThemes();
    renderThemeManagerList();
  } catch (err) {
    alert('Error creating theme: ' + err.message);
  }
}

function toggleThemeBgFields() {
  const bgType = document.getElementById('newThemeBgType').value;
  document.getElementById('themeColorField').style.display = bgType === 'color' ? 'block' : 'none';
  document.getElementById('themeGradientField').style.display = bgType === 'gradient' ? 'block' : 'none';
  document.getElementById('themeImageField').style.display = bgType === 'image' ? 'block' : 'none';
}

// ── Preview (renders exactly like /live but never touches server state) ──────

function previewSlide(reference, text, translation) {
  const theme = allThemesCache.find(t => t.id === selectedThemeId) || {
    bg_type: 'color', bg_value: '#000000', text_color: '#FFFFFF',
    accent_color: '#C9A84C', overlay_opacity: 0.4
  };

  const bgStyle = theme.bg_type === 'image'
    ? `background:url('/theme-images/${theme.bg_value}') center/cover no-repeat;`
    : `background:${theme.bg_value};`;

  document.getElementById('previewBgLayer').style.cssText = bgStyle;
  document.getElementById('previewOverlayLayer').style.background = `rgba(0,0,0,${theme.overlay_opacity ?? 0.4})`;
  document.getElementById('previewText').textContent = text || '';
  document.getElementById('previewText').style.color = theme.text_color || '#FFFFFF';
  document.getElementById('previewRef').textContent = reference || '';
  document.getElementById('previewRef').style.color = theme.accent_color || '#C9A84C';
  document.getElementById('previewTranslation').textContent = translation || '';

  document.getElementById('previewOverlay').classList.add('visible');
}

function closePreview() {
  document.getElementById('previewOverlay').classList.remove('visible');
}

// Load themes and restore auto-send toggle state on page load
document.addEventListener('DOMContentLoaded', () => {
  loadThemes();
  const toggle = document.getElementById('autoSendToggle');
  if (toggle) toggle.checked = autoSendEnabled;
});