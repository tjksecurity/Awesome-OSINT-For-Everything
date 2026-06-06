// EVA PWA — client logic
// - Pairs with the server (URL + token in localStorage)
// - Streams chat via SSE (POST + ReadableStream)
// - Web Speech API for STT and TTS (iOS Safari supports both)

const $ = (sel) => document.querySelector(sel);
const els = {
  setup: $('#setup'),
  app: $('#app'),
  setupUrl: $('#setup-url'),
  setupToken: $('#setup-token'),
  setupGo: $('#setup-go'),
  chat: $('#chat'),
  input: $('#input'),
  send: $('#btn-send'),
  mic: $('#btn-mic'),
  voice: $('#btn-voice'),
  authorize: $('#btn-authorize'),
  menu: $('#menu'),
  menuBtn: $('#btn-menu'),
  statusDot: $('#status-dot'),
  statusText: $('#status-text'),
};

const state = {
  url: localStorage.getItem('eva.url') || '',
  token: localStorage.getItem('eva.token') || '',
  voiceEnabled: localStorage.getItem('eva.voice') === '1',
  authorizerMode: 'deny',
  currentEvaMsg: null,
  currentText: '',
  abortController: null,
  recognition: null,
  recognizing: false,
};

// ---------- pairing -------------------------------------------------------

function showSetup() {
  els.setup.classList.remove('hidden');
  els.app.classList.add('hidden');
  if (state.url) els.setupUrl.value = state.url;
  if (state.token) els.setupToken.value = state.token;
}

function showApp() {
  els.setup.classList.add('hidden');
  els.app.classList.remove('hidden');
  refreshState();
  setVoiceButtonState();
}

els.setupGo.addEventListener('click', async () => {
  const url = (els.setupUrl.value || '').trim().replace(/\/$/, '');
  const token = (els.setupToken.value || '').trim();
  if (!url || !token) {
    alert('Both fields are required.');
    return;
  }
  // Probe
  try {
    const res = await fetch(`${url}/api/state`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (e) {
    alert(`Connection failed: ${e.message}`);
    return;
  }
  state.url = url;
  state.token = token;
  localStorage.setItem('eva.url', url);
  localStorage.setItem('eva.token', token);
  showApp();
  pushSystem('Connection established.');
});

// ---------- chat UI -------------------------------------------------------

function pushUser(text) {
  const div = document.createElement('div');
  div.className = 'msg user';
  div.textContent = text;
  els.chat.appendChild(div);
  scrollToBottom();
}

function pushSystem(text) {
  const div = document.createElement('div');
  div.className = 'msg system';
  div.textContent = text;
  els.chat.appendChild(div);
  scrollToBottom();
}

function pushTool(name) {
  const div = document.createElement('div');
  div.className = 'msg tool';
  div.textContent = `· deploying ${name}…`;
  els.chat.appendChild(div);
  scrollToBottom();
}

function pushError(text) {
  const div = document.createElement('div');
  div.className = 'msg error';
  div.textContent = text;
  els.chat.appendChild(div);
  scrollToBottom();
}

function ensureEvaMsg() {
  if (state.currentEvaMsg) return state.currentEvaMsg;
  const div = document.createElement('div');
  div.className = 'msg eva';
  div.textContent = '';
  const cursor = document.createElement('span');
  cursor.className = 'cursor';
  cursor.textContent = ' ';
  div.appendChild(cursor);
  els.chat.appendChild(div);
  state.currentEvaMsg = div;
  state.currentText = '';
  return div;
}

function appendEvaText(text) {
  const div = ensureEvaMsg();
  state.currentText += text;
  // Replace the cursor with new text + cursor
  div.firstChild && (div.firstChild.textContent = state.currentText);
  scrollToBottom();
}

function finalizeEvaMsg() {
  if (!state.currentEvaMsg) return;
  // Remove cursor
  const cursor = state.currentEvaMsg.querySelector('.cursor');
  if (cursor) cursor.remove();
  // Speak if voice is on
  if (state.voiceEnabled && state.currentText.trim()) {
    speak(state.currentText);
  }
  state.currentEvaMsg = null;
  state.currentText = '';
}

function scrollToBottom() {
  els.chat.scrollTo({ top: els.chat.scrollHeight, behavior: 'smooth' });
}

// ---------- voice in (STT) ------------------------------------------------

function initRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.continuous = false;
  r.interimResults = false;
  r.lang = 'en-US';
  r.onresult = (e) => {
    const transcript = e.results[0]?.[0]?.transcript?.trim();
    if (transcript) {
      els.input.value = transcript;
      sendMessage();
    }
  };
  r.onend = () => {
    state.recognizing = false;
    els.mic.classList.remove('listening');
  };
  r.onerror = (e) => {
    state.recognizing = false;
    els.mic.classList.remove('listening');
    if (e.error !== 'no-speech' && e.error !== 'aborted') {
      pushError(`Speech recognition: ${e.error}`);
    }
  };
  return r;
}

els.mic.addEventListener('click', () => {
  if (!state.recognition) {
    state.recognition = initRecognition();
  }
  if (!state.recognition) {
    pushError('Speech recognition not supported on this device.');
    return;
  }
  if (state.recognizing) {
    state.recognition.stop();
    return;
  }
  // iOS requires user gesture; this click counts.
  try {
    state.recognition.start();
    state.recognizing = true;
    els.mic.classList.add('listening');
    // Cancel any speech output so EVA doesn't talk over you.
    window.speechSynthesis && window.speechSynthesis.cancel();
  } catch (e) {
    pushError(`Could not start mic: ${e.message}`);
  }
});

// ---------- voice out (TTS) ----------------------------------------------

function pickEvaVoice() {
  const voices = window.speechSynthesis.getVoices();
  // Preferred order: Ava (US), Allison, Samantha, then any female en-US.
  const preferred = ['Ava', 'Allison', 'Samantha', 'Victoria', 'Karen'];
  for (const name of preferred) {
    const v = voices.find((v) => v.name.includes(name));
    if (v) return v;
  }
  // Anything en-US that sounds female-ish
  return voices.find((v) => v.lang === 'en-US') || voices[0] || null;
}

let _voicesReady = false;
function warmVoices() {
  if (_voicesReady) return;
  window.speechSynthesis.getVoices();
  window.speechSynthesis.addEventListener('voiceschanged', () => { _voicesReady = true; }, { once: true });
}

function speak(text) {
  if (!window.speechSynthesis) return;
  // Strip markdown-ish noise that reads badly.
  const clean = text.replace(/[`*_#]/g, '').replace(/\[(OK|WARN|FAIL)\]/g, '').trim();
  if (!clean) return;
  const u = new SpeechSynthesisUtterance(clean);
  const voice = pickEvaVoice();
  if (voice) u.voice = voice;
  u.lang = 'en-US';
  u.rate = 1.05;
  u.pitch = 0.95;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

function setVoiceButtonState() {
  els.voice.classList.toggle('on', state.voiceEnabled);
  els.voice.textContent = state.voiceEnabled ? '🔊' : '🔇';
}

els.voice.addEventListener('click', () => {
  state.voiceEnabled = !state.voiceEnabled;
  localStorage.setItem('eva.voice', state.voiceEnabled ? '1' : '0');
  setVoiceButtonState();
  if (state.voiceEnabled) {
    // Warm the synth (iOS gesture requirement) with a short utterance.
    speak('Voice channel open.');
  } else {
    window.speechSynthesis && window.speechSynthesis.cancel();
  }
});

// ---------- chat send -----------------------------------------------------

async function sendMessage() {
  const text = (els.input.value || '').trim();
  if (!text) return;
  els.input.value = '';
  pushUser(text);
  await streamChat(text);
}

els.send.addEventListener('click', sendMessage);
els.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function streamChat(message) {
  setStatus('busy', 'thinking');
  state.abortController = new AbortController();
  try {
    const res = await fetch(`${state.url}/api/chat`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${state.token}`,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify({ message }),
      signal: state.abortController.signal,
    });
    if (!res.ok) {
      pushError(`Server returned ${res.status}: ${await res.text()}`);
      setStatus('err', 'error');
      return;
    }
    await consumeSSE(res);
  } catch (e) {
    if (e.name !== 'AbortError') {
      pushError(`Network: ${e.message}`);
      setStatus('err', 'error');
    }
  } finally {
    finalizeEvaMsg();
    if (els.statusDot.classList.contains('busy')) setStatus('online', 'ready');
    state.abortController = null;
  }
}

async function consumeSSE(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      handleSSEBlock(block);
    }
  }
}

function handleSSEBlock(block) {
  let event = 'message';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    else if (line.startsWith('data: ')) data += line.slice(6);
  }
  if (!data) return;
  let payload;
  try {
    payload = JSON.parse(data.replace(/\\n/g, '\n'));
  } catch {
    return;
  }
  if (event === 'state') {
    applyState(payload);
    return;
  }
  if (event === 'done') return;
  if (event === 'event') {
    const ev = payload;
    if (ev.kind === 'text') appendEvaText(ev.text);
    else if (ev.kind === 'tool_use_start') pushTool(ev.tool_name);
    else if (ev.kind === 'error') {
      if (ev.is_error) pushError(ev.text);
      else pushSystem(ev.text);
    }
    else if (ev.kind === 'turn_end') finalizeEvaMsg();
  }
}

// ---------- status, state, slash-commands --------------------------------

function applyState(s) {
  state.authorizerMode = s.authorizer?.mode || 'deny';
  els.authorize.classList.toggle('on', state.authorizerMode === 'session');
  els.authorize.classList.toggle('warn', state.authorizerMode === 'one_shot');
  els.authorize.textContent =
    state.authorizerMode === 'session' ? '🔓' :
    state.authorizerMode === 'one_shot' ? '🔑' : '🔒';
  if (els.statusText.textContent === 'offline') {
    setStatus('online', `${s.model}/${s.effort}`);
  }
}

function setStatus(kind, label) {
  els.statusDot.classList.remove('online', 'busy', 'err');
  els.statusDot.classList.add(kind);
  els.statusText.textContent = label;
}

async function refreshState() {
  try {
    const res = await fetch(`${state.url}/api/state`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const s = await res.json();
    applyState(s);
    setStatus('online', `${s.model}/${s.effort}`);
  } catch (e) {
    setStatus('err', 'offline');
  }
}

els.authorize.addEventListener('click', async () => {
  // Cycle: deny -> one_shot -> session -> deny
  const next =
    state.authorizerMode === 'deny' ? 'one_shot' :
    state.authorizerMode === 'one_shot' ? 'session' :
    'deny';
  try {
    const res = await fetch(`${state.url}/api/authorize`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${state.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ mode: next, ttl_seconds: next === 'session' ? 600 : 0 }),
    });
    const data = await res.json();
    pushSystem(data.message || `authorization: ${next}`);
    state.authorizerMode = data.mode;
    refreshState();
  } catch (e) {
    pushError(`Could not toggle auth: ${e.message}`);
  }
});

els.menuBtn.addEventListener('click', () => {
  els.menu.classList.toggle('hidden');
});
document.addEventListener('click', (e) => {
  if (!els.menu.contains(e.target) && e.target !== els.menuBtn) {
    els.menu.classList.add('hidden');
  }
});

els.menu.addEventListener('click', async (e) => {
  const cmd = e.target?.dataset?.cmd;
  if (!cmd) return;
  els.menu.classList.add('hidden');
  if (cmd === 'reset') {
    await fetch(`${state.url}/api/reset`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${state.token}` },
    });
    pushSystem('Tactical buffer cleared. Memory retained.');
  } else if (cmd === 'memory') {
    const res = await fetch(`${state.url}/api/memory`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    const data = await res.json();
    if (!data.entries?.length) {
      pushSystem('Memory is empty.');
    } else {
      const summary = data.entries
        .map((e) => `· ${e.key}: ${e.value}${e.tags?.length ? ' [' + e.tags.join(', ') + ']' : ''}`)
        .join('\n');
      pushSystem(summary);
    }
  } else if (cmd === 'state') {
    refreshState().then(() => pushSystem(`${els.statusText.textContent} · authorizer=${state.authorizerMode}`));
  } else if (cmd === 'unpair') {
    if (confirm('Unpair this device? Token will be removed.')) {
      localStorage.removeItem('eva.url');
      localStorage.removeItem('eva.token');
      state.url = state.token = '';
      els.chat.innerHTML = '';
      showSetup();
    }
  }
});

// ---------- service worker -----------------------------------------------

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* non-fatal */ });
}

// ---------- boot ----------------------------------------------------------

warmVoices();
if (state.url && state.token) {
  showApp();
} else {
  showSetup();
}
