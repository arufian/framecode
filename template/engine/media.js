// Footage: video clips as frame sequences (public/footage/<name>/00000.jpg, ...), written
// by media.py visuals and listed in public/media.json. Scenes draw a clip's frame for a
// time synchronously; a frame that is not loaded yet counts as a miss and starts loading.
// The renderer redraws a frame until it has no misses (renderFrameReady), so every
// rendered frame shows the exact footage frame. The studio shows the nearest loaded frame
// and redraws when the missing one arrives. Pure ES module, no browser globals at import.

const KEEP = 36;  // decoded frames kept per clip
const AHEAD = 12; // frames prefetched past the one drawn

let loader = null;
let onLoad = null;
const misses = new Map(); // "clip:index" -> [clip, index]

/** async (path) => drawable (ImageBitmap, image, canvas); set by the platform. */
export const setFootageLoader = (fn) => { loader = fn; };
/** Called whenever a frame finishes loading (the studio redraws). */
export const onFootageLoad = (fn) => { onLoad = fn; };

export function createClip(name, meta) {
  return { name, ext: 'jpg', ...meta, cache: new Map(), pending: new Map(), clock: 0, last: -1 };
}

/** Frame index of clip time `from + t * rate` (seconds); holds the last frame unless loop. */
export function clipIndex(clip, t, { rate = 1, from = 0, loop = false } = {}) {
  const n = clip.frames;
  const i = Math.floor((from + t * rate) * clip.fps + 1e-6);
  return loop ? ((i % n) + n) % n : Math.max(0, Math.min(n - 1, i));
}

function evict(clip) {
  while (clip.cache.size > KEEP) {
    let oldest = null;
    for (const [i, entry] of clip.cache) if (!oldest || entry.used < oldest[1].used) oldest = [i, entry];
    clip.cache.delete(oldest[0]);
    oldest[1].img.close?.();
  }
}

function request(clip, i) {
  if (clip.cache.has(i)) return Promise.resolve(clip.cache.get(i).img);
  if (clip.pending.has(i)) return clip.pending.get(i);
  if (!loader) return Promise.reject(new Error('footage loader is not set (engine platform)'));
  const path = `${clip.dir}/${String(i).padStart(5, '0')}.${clip.ext}`;
  const job = loader(path).then((img) => {
    clip.pending.delete(i);
    clip.cache.set(i, { img, used: ++clip.clock });
    evict(clip);
    if (onLoad) onLoad(clip, i);
    return img;
  }, (error) => {
    clip.pending.delete(i);
    throw new Error(`footage ${clip.name} frame ${i}: ${error.message || error}`);
  });
  clip.pending.set(i, job);
  return job;
}

function prefetch(clip, i) {
  const step = i >= clip.last ? 1 : -1; // follow the playback direction
  clip.last = i;
  for (let k = 1; k <= AHEAD; k++) {
    const j = i + k * step;
    if (j < 0 || j >= clip.frames) break;
    if (!clip.cache.has(j) && !clip.pending.has(j)) request(clip, j).catch(() => {});
  }
}

/** The drawable for clip time t, or the nearest loaded frame (null if none) on a miss. */
export function frameAt(clip, t, opts) {
  const i = clipIndex(clip, t, opts);
  const hit = clip.cache.get(i);
  prefetch(clip, i);
  if (hit) {
    hit.used = ++clip.clock;
    return hit.img;
  }
  misses.set(`${clip.name}:${i}`, [clip, i]);
  request(clip, i).catch(() => {});
  let near = null;
  for (const [j, entry] of clip.cache) if (!near || Math.abs(j - i) < Math.abs(near[0] - i)) near = [j, entry];
  return near ? near[1].img : null;
}

export const clearFootageMisses = () => misses.clear();
export const footageMisses = () => misses.size;

/** Load every frame the last draw missed; returns how many there were. */
export async function settleFootage() {
  const jobs = [...misses.values()].map(([clip, i]) => request(clip, i));
  misses.clear();
  await Promise.all(jobs);
  return jobs.length;
}
