#!/usr/bin/env node
// Review studio: serves the project to the browser, where the same engine draws
// every frame live (play, scrub, step, loop) in sync with the audio mix. Code
// edits hot-reload; review notes are saved to review/notes.json for the agent.
//
//   node engine/studio.js [--port 4600] [--open]

import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, statSync, watch, writeFileSync } from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { send, serveStatic } from './server.js';

const root = process.cwd();
const args = process.argv.slice(2);
const port = Number(args[args.indexOf('--port') + 1]) || Number(process.env.STUDIO_PORT) || 4600;
const host = '127.0.0.1';
const notesFile = path.join(root, 'review', 'notes.json');

const readNotes = () => { try { return JSON.parse(readFileSync(notesFile, 'utf8')); } catch { return []; } };
const writeNotes = (notes) => { mkdirSync(path.dirname(notesFile), { recursive: true }); writeFileSync(notesFile, JSON.stringify(notes, null, 2) + '\n'); };

function body(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; if (data.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(data ? JSON.parse(data) : {}); } catch (e) { reject(e); } });
  });
}

function audioStatus() {
  try {
    const timeline = JSON.parse(readFileSync(path.join(root, 'src/timeline.json'), 'utf8'));
    if (!timeline.audio?.mix) return { planned: false };
    const mix = path.join(root, 'public', timeline.audio.mix);
    if (!existsSync(mix)) return { planned: true, exists: false, stale: true };
    const mixTime = statSync(mix).mtimeMs;
    const inputs = [path.join(root, 'src/timeline.json'),
      ...timeline.lines.filter((l) => l.src).map((l) => path.join(root, 'public', l.src)),
      ...timeline.sfx.filter((c) => c.src).map((c) => path.join(root, 'public', c.src)),
      ...(timeline.music ? [path.join(root, 'public', timeline.music.src)] : [])];
    const stale = inputs.some((f) => existsSync(f) && statSync(f).mtimeMs > mixTime + 1000);
    return { planned: true, exists: true, stale, src: `/public/${timeline.audio.mix}` };
  } catch (error) {
    return { planned: false, error: String(error) };
  }
}

const clients = new Set();
let pending = null;
function broadcast(file) {
  clearTimeout(pending);
  pending = setTimeout(() => { for (const res of clients) res.write(`event: reload\ndata: ${JSON.stringify({ file })}\n\n`); }, 120);
}
const IGNORED = /^(node_modules|out|review|\.git|\.venv-tts|\.segments)(\/|$)|(^|\/)\./;
try {
  watch(root, { recursive: true }, (_, name) => {
    if (!name) return;
    const rel = name.split(path.sep).join('/');
    if (!IGNORED.test(rel) && /\.(js|json|css|wav|png|jpe?g|webp|svg|woff2?|ttf|otf)$/.test(rel)) broadcast(rel);
  });
} catch (error) {
  console.warn(`hot reload disabled: ${error.message}`);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  const pathname = decodeURIComponent(url.pathname);
  try {
    if (pathname === '/__events') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
      res.write('retry: 1000\n\n');
      clients.add(res);
      req.on('close', () => clients.delete(res));
      return;
    }
    if (pathname === '/__api/status') return send(res, 200, audioStatus());
    if (pathname === '/__api/notes' && req.method === 'GET') return send(res, 200, readNotes());
    if (pathname === '/__api/notes' && req.method === 'POST') {
      const { frame, time, scene, text } = await body(req);
      if (!String(text || '').trim()) return send(res, 400, { error: 'empty note' });
      const notes = readNotes();
      const note = { id: `N${String(notes.length + 1).padStart(3, '0')}`, frame, time, scene, text: String(text).trim(),
        status: 'open', created: new Date().toISOString() };
      notes.push(note);
      writeNotes(notes);
      return send(res, 201, note);
    }
    const match = /^\/__api\/notes\/([\w-]+)$/.exec(pathname);
    if (match && (req.method === 'PATCH' || req.method === 'DELETE')) {
      const notes = readNotes();
      const index = notes.findIndex((n) => n.id === match[1]);
      if (index < 0) return send(res, 404, { error: 'no such note' });
      if (req.method === 'DELETE') notes.splice(index, 1);
      else Object.assign(notes[index], (({ status, text }) => ({ ...(status && { status }), ...(text && { text }) }))(await body(req)));
      writeNotes(notes);
      return send(res, 200, notes[index] || { deleted: match[1] });
    }
    return serveStatic(req, res, root, pathname);
  } catch (error) {
    return send(res, 500, { error: String(error) });
  }
});

server.on('error', (error) => {
  console.error(error.code === 'EADDRINUSE' ? `port ${port} is busy: use --port <other>` : String(error));
  process.exit(1);
});
server.listen(port, host, () => {
  const address = `http://${host}:${port}/`;
  console.log(`Studio running at ${address}  (Ctrl+C to stop)`);
  console.log('Keys: Space play/pause, ←/→ frame, Shift+←/→ 1s, [ ] scenes, L loop scene, M mute, S safe area, N note');
  if (args.includes('--open')) spawn(process.platform === 'darwin' ? 'open' : 'xdg-open', [address], { stdio: 'ignore', detached: true }).unref();
});
