// Local HTTP helpers shared by the studio and the renderer: static files with Range
// support, the studio's own pages under /__studio/, and project files. Dotfiles
// (such as .env) are never served.

import { createReadStream, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const studioDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'studio');

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.gif': 'image/gif', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf',
};

export function send(res, status, body, type = 'application/json; charset=utf-8') {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}

/** Static files with Range support (browsers need it to seek audio). */
export function serveFile(req, res, file) {
  let stat;
  try { stat = statSync(file); } catch { return send(res, 404, { error: 'not found' }); }
  if (!stat.isFile()) return send(res, 404, { error: 'not found' });
  const type = TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream';
  const range = req.headers.range && /bytes=(\d*)-(\d*)/.exec(req.headers.range);
  if (range) {
    const start = range[1] ? Number(range[1]) : 0;
    const end = range[2] ? Math.min(Number(range[2]), stat.size - 1) : stat.size - 1;
    res.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${start}-${end}/${stat.size}`,
      'Accept-Ranges': 'bytes', 'Content-Length': end - start + 1, 'Cache-Control': 'no-store' });
    createReadStream(file, { start, end }).pipe(res);
    return;
  }
  res.writeHead(200, { 'Content-Type': type, 'Content-Length': stat.size, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' });
  createReadStream(file).pipe(res);
}

/** The studio page at /, studio assets under /__studio/, everything else from the project root. */
export function serveStatic(req, res, root, pathname) {
  if (pathname === '/' || pathname === '/index.html') return serveFile(req, res, path.join(studioDir, 'index.html'));
  if (pathname.startsWith('/__studio/')) {
    const file = path.join(studioDir, pathname.slice('/__studio/'.length));
    if (!file.startsWith(studioDir + path.sep)) return send(res, 403, { error: 'forbidden' });
    return serveFile(req, res, file);
  }
  const file = path.join(root, pathname);
  if (!file.startsWith(root + path.sep) || pathname.split('/').some((part) => part.startsWith('.'))) {
    return send(res, 403, { error: 'forbidden' });
  }
  return serveFile(req, res, file);
}
