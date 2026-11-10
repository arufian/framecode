// Studio client: draws the project live with the same engine and p5 code the renderer uses.
import { setPlatform, loadProject, renderFrame, sceneAt, clamp } from '/engine/core.js';
import { onFootageLoad } from '/engine/media.js';
import { browserPlatform } from '/engine/platform-browser.js';

const $ = (id) => document.getElementById(id);
const view = $('view'), vctx = view.getContext('2d');
const track = $('track'), tctx = track.getContext('2d');
const saved = JSON.parse(sessionStorage.getItem('studio') || '{}');

const state = {
  project: null, timeline: null, frame: saved.frame || 0, playing: false, loop: !!saved.loop, muted: !!saved.muted,
  safe: !!saved.safe, speed: saved.speed || 1, zoom: saved.zoom || 'fit', scale: 1, dirty: true,
  clockStart: 0, clockFrame: 0, audio: null, audioOk: false, notes: [], drawTimes: [], cache: {},
  followers: [], gains: null, audioCtx: null, mix: {}, // stems: music (and VO) follow the SFX stem
};

// ------------------------------------------------------------------ helpers

const fps = () => state.timeline.fps;
const total = () => state.timeline.durationInFrames;
function timecode(frame) {
  const s = frame / fps();
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, '0')}`;
}
function showError(error) {
  const el = $('error');
  if (!error) { el.classList.add('hidden'); return; }
  el.textContent = `${error.message || error}\n\n${(error.stack || '').split('\n').slice(1, 8).join('\n')}`;
  el.classList.remove('hidden');
}
function persist() {
  sessionStorage.setItem('studio', JSON.stringify({ frame: state.frame, loop: state.loop, muted: state.muted,
    safe: state.safe, speed: state.speed, zoom: state.zoom }));
}

// ------------------------------------------------------------------ layout

function layout() {
  const { width: W, height: H } = state.timeline;
  const stage = $('stage').getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  let cssW;
  if (state.zoom === 'fit') cssW = Math.min(stage.width - 36, (stage.height - 36) * (W / H));
  else cssW = (W * Number(state.zoom)) / dpr;
  cssW = Math.max(160, cssW);
  const cssH = cssW * (H / W);
  view.style.width = `${cssW}px`;
  view.style.height = `${cssH}px`;
  view.width = Math.round(cssW * dpr);
  view.height = Math.round(cssH * dpr);
  state.scale = view.width / W;
  const safe = $('safe');
  const r = view.getBoundingClientRect(), s = $('stage').getBoundingClientRect();
  Object.assign(safe.style, { left: `${r.left - s.left + $('stage').scrollLeft}px`, top: `${r.top - s.top + $('stage').scrollTop}px`,
    width: `${cssW}px`, height: `${cssH}px` });
  const tr = track.getBoundingClientRect();
  track.width = Math.round(tr.width * dpr);
  track.height = Math.round(tr.height * dpr);
  state.dirty = true;
}

// ------------------------------------------------------------------ drawing

function draw() {
  const t0 = performance.now();
  try {
    renderFrame(vctx, state.project, state.frame, state.scale, state.cache);
    showError(null);
  } catch (error) {
    showError(error);
  }
  state.drawTimes.push(performance.now() - t0);
  if (state.drawTimes.length > 30) state.drawTimes.shift();
  drawTrack();
  updatePanels();
}

const SCENE_COLORS = ['#5b7cfa', '#2bb5a0', '#e0913a', '#c85fd6', '#e05d6f', '#7cbf4a', '#4aa3df', '#d4b23a'];

function drawTrack() {
  const dpr = window.devicePixelRatio || 1;
  const W = track.width, H = track.height;
  const x = (f) => (f / total()) * W;
  tctx.clearRect(0, 0, W, H);
  tctx.font = `${11 * dpr}px ui-monospace, Menlo, monospace`;
  // ruler
  const step = [1, 2, 5, 10, 15, 30, 60].find((s) => (s * fps() / total()) * W > 60 * dpr) || 60;
  tctx.fillStyle = '#8b93a7';
  for (let s = 0; s * fps() <= total(); s += step) {
    tctx.fillRect(x(s * fps()), 0, 1, 6 * dpr);
    tctx.fillText(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`, x(s * fps()) + 3 * dpr, 10 * dpr);
  }
  const rows = { scene: [16, 34], line: [54, 14], sfx: [72, 10] };
  // scenes + transition overlaps
  state.timeline.scenes.forEach((scene, i) => {
    const [y, h] = rows.scene.map((v) => v * dpr);
    tctx.fillStyle = SCENE_COLORS[i % SCENE_COLORS.length] + 'cc';
    tctx.fillRect(x(scene.from), y, x(scene.durationInFrames) - 1, h);
    tctx.fillStyle = '#0b1020';
    tctx.save();
    tctx.beginPath(); tctx.rect(x(scene.from), y, x(scene.durationInFrames) - 2, h); tctx.clip();
    tctx.fillText(`${scene.id} · ${scene.component}`, x(scene.from) + 5 * dpr, y + h / 2 + 4 * dpr);
    tctx.restore();
  });
  // transition overlaps, drawn over both neighbouring scenes
  for (const scene of state.timeline.scenes) {
    if (!scene.outFrames) continue;
    const [y, h] = rows.scene.map((v) => v * dpr);
    const x0 = x(scene.from + scene.durationInFrames - scene.outFrames);
    tctx.fillStyle = 'rgba(255,255,255,0.28)';
    tctx.fillRect(x0, y, x(scene.outFrames), h);
    tctx.fillStyle = '#ffffff';
    tctx.fillText(scene.transitionOut.type, x0 + 3 * dpr, y - 3 * dpr + h);
  }
  // voice lines
  const speakers = [...new Set(state.timeline.lines.map((l) => l.speaker))];
  for (const line of state.timeline.lines) {
    const [y, h] = rows.line.map((v) => v * dpr);
    tctx.fillStyle = ['#ffb86b', '#7c9cff', '#4ade80', '#f472b6'][speakers.indexOf(line.speaker) % 4];
    tctx.fillRect(x(line.from), y, Math.max(2, x(line.durationInFrames)), h);
  }
  // sfx
  for (const cue of state.timeline.sfx) {
    const [y, h] = rows.sfx.map((v) => v * dpr);
    tctx.fillStyle = '#c9d1e3';
    tctx.fillRect(x(cue.syncFrame), y, 2 * dpr, h);
  }
  // notes
  for (const note of state.notes) {
    tctx.fillStyle = note.status === 'resolved' ? '#4ade80' : '#fbbf24';
    tctx.beginPath();
    tctx.arc(x(note.frame), 88 * dpr, 4 * dpr, 0, Math.PI * 2);
    tctx.fill();
  }
  // loop range + playhead
  if (state.loop) {
    const scene = sceneAt(state.timeline, state.frame);
    tctx.strokeStyle = '#ffb86b';
    tctx.lineWidth = 2 * dpr;
    tctx.strokeRect(x(scene.from), 14 * dpr, x(scene.durationInFrames), 38 * dpr);
  }
  tctx.fillStyle = '#ffffff';
  tctx.fillRect(x(state.frame) - dpr, 12 * dpr, 2 * dpr, H - 12 * dpr);
}

function updatePanels() {
  const { timeline } = state;
  const scene = sceneAt(timeline, state.frame);
  const local = state.frame - scene.from;
  $('clock').textContent = `${timecode(state.frame)} / ${timecode(total())}`;
  $('frame').textContent = `frame ${state.frame}`;
  $('now-scene').textContent = `${scene.id} · ${scene.component}  (${(local / fps()).toFixed(2)}s / ${(scene.durationInFrames / fps()).toFixed(2)}s)`;
  const line = timeline.lines.find((l) => state.frame >= l.from && state.frame < l.from + l.durationInFrames);
  $('now-line').innerHTML = line ? `<b>${escapeHtml(line.speaker)}</b>: ${escapeHtml(line.text)}` : 'No voice line';
  $('note-add').textContent = `Add note at ${timecode(state.frame)} (${scene.id})`;
  $('play').textContent = state.playing ? '❚❚' : '▶';
  const sorted = [...state.drawTimes].sort((a, b) => a - b);
  const avg = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0; // median: ignores one-off texture builds
  const budget = 1000 / fps();
  const perf = $('perf-badge');
  perf.textContent = `${avg.toFixed(1)} ms/frame`;
  perf.className = `badge ${avg < budget ? 'ok' : avg < budget * 2 ? 'warn' : 'bad'}`;
  perf.title = `Browser draw time. Budget for real-time ${fps()} fps playback: ${budget.toFixed(1)} ms. ` +
    'Slow previews still render correctly to video.';
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ------------------------------------------------------------------ transport

function seek(frame, { fromAudio = false } = {}) {
  state.frame = clamp(Math.round(frame), 0, total() - 1);
  if (state.playing) { state.clockStart = performance.now(); state.clockFrame = state.frame; }
  if (!fromAudio && state.audio && state.audioOk) {
    for (const a of [state.audio, ...state.followers]) a.currentTime = state.frame / fps();
  }
  state.dirty = true;
  persist();
}

function play(on = !state.playing) {
  state.playing = on;
  state.clockStart = performance.now();
  state.clockFrame = state.frame;
  if (state.audio && state.audioOk) {
    if (on) state.audioCtx?.resume();
    for (const a of [state.audio, ...state.followers]) {
      a.playbackRate = state.speed;
      a.currentTime = state.frame / fps();
      if (on) a.play().catch(() => {}); else a.pause();
    }
  }
  state.dirty = true;
}

function loopBounds() {
  const scene = sceneAt(state.timeline, state.frame);
  return [scene.from, scene.from + scene.durationInFrames];
}

function tick() {
  if (state.project && state.playing) {
    const useAudio = state.audio && state.audioOk && !state.audio.paused;
    if (useAudio) {
      for (const f of state.followers) if (Math.abs(f.currentTime - state.audio.currentTime) > 0.06) f.currentTime = state.audio.currentTime;
    }
    let next = useAudio ? Math.floor(state.audio.currentTime * fps() + 1e-6)
      : Math.floor(state.clockFrame + ((performance.now() - state.clockStart) / 1000) * fps() * state.speed);
    const [lo, hi] = state.loop ? state.loopRange || (state.loopRange = loopBounds()) : [0, total()];
    if (next >= hi) {
      if (state.loop) { next = lo; seek(lo); }
      else { next = total() - 1; play(false); }
    }
    if (next !== state.frame) { state.frame = next; state.dirty = true; }
  }
  if (state.project && state.dirty) { state.dirty = false; draw(); }
  requestAnimationFrame(tick);
}

function sceneJump(direction) {
  const scenes = state.timeline.scenes;
  const current = scenes.indexOf(sceneAt(state.timeline, state.frame));
  const target = scenes[clamp(current + direction, 0, scenes.length - 1)];
  seek(direction < 0 && state.frame > sceneAt(state.timeline, state.frame).from + 2 ? scenes[current].from : target.from);
  state.loopRange = null;
}

// ------------------------------------------------------------------ audio & notes

async function refreshAudio() {
  const status = await (await fetch('/__api/status', { cache: 'no-store' })).json();
  const badge = $('audio-badge');
  if (!status.planned) { badge.textContent = 'no audio planned'; badge.className = 'badge'; return; }
  if (!status.exists) { badge.textContent = 'audio mix missing — run mix_audio.py'; badge.className = 'badge bad'; return; }
  badge.textContent = status.stale ? 'audio stale — re-run mix_audio.py' : 'audio synced';
  badge.className = `badge ${status.stale ? 'warn' : 'ok'}`;
  const load = (src) => { const a = new Audio(`${src}?v=${Date.now()}`); a.preload = 'auto'; return a; };
  state.mix = status.mix || {};
  // With stems, the SFX stem is the clock; music and SFX play through gain nodes the sliders control.
  const audio = load(status.stems ? status.stems.sfx : status.src);
  audio.addEventListener('canplay', () => { state.audioOk = true; }, { once: true });
  audio.addEventListener('error', () => { state.audioOk = false; badge.textContent = 'audio failed to load'; badge.className = 'badge bad'; });
  state.audio = audio;
  if (!status.stems) { audio.muted = state.muted; return; }
  state.audioCtx = new AudioContext();
  const route = (el) => {
    const gain = state.audioCtx.createGain();
    state.audioCtx.createMediaElementSource(el).connect(gain).connect(state.audioCtx.destination);
    return gain;
  };
  const music = load(status.stems.music);
  state.gains = { sfx: route(audio), music: route(music) };
  state.followers = [music];
  if (status.stems.vo) { const vo = load(status.stems.vo); vo.muted = state.muted; state.followers.push(vo); }
  for (const [name, { set }] of Object.entries(LEVELS)) {
    $(`${name}-vol`).value = String(state.mix[set] ?? 0);
    $(`${name}-ctl`).classList.remove('hidden');
  }
  applyLevels();
}

// Each stem was mixed at its mixed*Db level (review/mix.json); its slider plays the difference live.
const LEVELS = { music: { set: 'musicDb', mixed: 'mixedMusicDb' }, sfx: { set: 'sfxDb', mixed: 'mixedSfxDb' } };
function applyLevels() {
  let changed = false;
  for (const [name, { set, mixed }] of Object.entries(LEVELS)) {
    const db = state.mix[set] ?? 0, base = state.mix[mixed] ?? db;
    $(`${name}-db`).textContent = `${db > 0 ? '+' : ''}${db} dB`;
    if (state.gains?.[name]) state.gains[name].gain.value = state.muted ? 0 : 10 ** ((db - base) / 20);
    if (db !== base) changed = true;
  }
  if (changed) { const badge = $('audio-badge'); badge.textContent = 'audio level changed — remix before render'; badge.className = 'badge warn'; }
}

let saveMix = null;
for (const [name, { set }] of Object.entries(LEVELS)) {
  $(`${name}-vol`).oninput = (e) => {
    state.mix[set] = Number(e.target.value);
    applyLevels();
    clearTimeout(saveMix);
    saveMix = setTimeout(() => fetch('/__api/mix', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ musicDb: state.mix.musicDb ?? 0, sfxDb: state.mix.sfxDb ?? 0 }) }), 300);
  };
}

async function refreshNotes() {
  state.notes = await (await fetch('/__api/notes', { cache: 'no-store' })).json();
  const list = $('notes');
  list.innerHTML = '';
  const open = state.notes.filter((n) => n.status !== 'resolved').length;
  $('note-count').textContent = state.notes.length ? `${open} open / ${state.notes.length}` : '';
  for (const note of [...state.notes].sort((a, b) => a.frame - b.frame)) {
    const li = document.createElement('li');
    li.className = note.status === 'resolved' ? 'resolved' : '';
    li.innerHTML = `<button class="del" title="Delete note">✕</button><span class="when">${timecode(note.frame)}</span>` +
      `<span class="scene">${escapeHtml(note.scene || '')} · ${escapeHtml(note.id)}</span><div class="body">${escapeHtml(note.text)}</div>` +
      (note.resolution ? `<div class="resolution">✓ ${escapeHtml(note.resolution)}</div>` : '');
    li.addEventListener('click', (e) => {
      if (e.target.classList.contains('del')) {
        fetch(`/__api/notes/${note.id}`, { method: 'DELETE' }).then(refreshNotes);
        return;
      }
      play(false); seek(note.frame);
    });
    list.appendChild(li);
  }
  state.dirty = true;
}

$('note-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('note-text').value.trim();
  if (!text) return;
  const scene = sceneAt(state.timeline, state.frame);
  await fetch('/__api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frame: state.frame, time: +(state.frame / fps()).toFixed(3), scene: scene.id, text }) });
  $('note-text').value = '';
  $('note-text').blur();
  refreshNotes();
});

// ------------------------------------------------------------------ input

function scrub(e) {
  const r = track.getBoundingClientRect();
  seek(((e.clientX - r.left) / r.width) * total());
  state.loopRange = null;
}
track.addEventListener('pointerdown', (e) => { track.setPointerCapture(e.pointerId); scrub(e); });
track.addEventListener('pointermove', (e) => { if (e.buttons) scrub(e); });

$('play').onclick = () => play();
$('step-back').onclick = () => { play(false); seek(state.frame - 1); };
$('step-fwd').onclick = () => { play(false); seek(state.frame + 1); };
$('prev-scene').onclick = () => sceneJump(-1);
$('next-scene').onclick = () => sceneJump(1);
$('loop').onchange = (e) => { state.loop = e.target.checked; state.loopRange = null; persist(); state.dirty = true; };
$('mute').onchange = (e) => {
  state.muted = e.target.checked;
  if (state.audio && !state.gains) state.audio.muted = state.muted;
  for (const f of state.followers.slice(1)) f.muted = state.muted; // VO; music and SFX mute through their gains
  applyLevels();
  persist();
};
$('safe-toggle').onchange = (e) => { state.safe = e.target.checked; $('safe').classList.toggle('hidden', !state.safe); persist(); };
$('speed').onchange = (e) => { state.speed = Number(e.target.value); if (state.playing) play(true); persist(); };
$('zoom').onchange = (e) => { state.zoom = e.target.value; layout(); persist(); };

window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'TEXTAREA') { if (e.key === 'Escape') e.target.blur(); return; }
  if (e.target.type === 'range' && e.key.startsWith('Arrow')) return; // arrows move the slider
  if (!state.timeline) return;
  const big = Math.round(fps());
  const actions = {
    ' ': () => play(),
    ArrowLeft: () => { play(false); seek(state.frame - (e.shiftKey ? big : 1)); },
    ArrowRight: () => { play(false); seek(state.frame + (e.shiftKey ? big : 1)); },
    Home: () => seek(0), End: () => seek(total() - 1),
    '[': () => sceneJump(-1), ']': () => sceneJump(1),
    l: () => { $('loop').click(); }, m: () => { $('mute').click(); }, s: () => { $('safe-toggle').click(); },
    n: () => { play(false); $('note-text').focus(); },
  };
  const action = actions[e.key] || actions[e.key.toLowerCase()];
  if (action) { e.preventDefault(); action(); }
});
window.addEventListener('resize', layout);

const events = new EventSource('/__events');
events.addEventListener('reload', () => { persist(); location.reload(); });

// ------------------------------------------------------------------ boot

(async () => {
  try {
    const platform = await browserPlatform();
    setPlatform(platform);
    const module = await import(`/project.js?v=${Date.now()}`);
    onFootageLoad(() => { state.dirty = true; }); // a footage frame arrived: redraw with it
    state.project = await loadProject(module.default, platform.loaders);
    state.timeline = state.project.timeline;
    state.frame = clamp(state.frame, 0, total() - 1);
    const { width, height, fps: rate, title } = state.timeline;
    document.title = `${title || 'Video'} · Studio`;
    $('title').textContent = title || 'Untitled video';
    $('meta').textContent = `${width}×${height} · ${rate} fps · ${timecode(total())} · ${state.timeline.scenes.length} scenes`;
    $('loop').checked = state.loop; $('mute').checked = state.muted; $('safe-toggle').checked = state.safe;
    $('safe').classList.toggle('hidden', !state.safe);
    $('speed').value = String(state.speed); $('zoom').value = String(state.zoom);
    $('loading').classList.add('hidden');
    layout();
    await Promise.all([refreshAudio(), refreshNotes()]);
    requestAnimationFrame(tick);
  } catch (error) {
    $('loading').classList.add('hidden');
    showError(error);
  }
})();
