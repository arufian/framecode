// Render page: engine/render.js opens it in headless Chrome and drives it through
// window.framecode. Frames are drawn by the same engine and p5 code as the studio,
// then posted to the renderer as raw RGBA (video) or PNG (stills).
import { setPlatform, loadProject, renderFrameReady } from '/engine/core.js';
import { browserPlatform } from '/engine/platform-browser.js';

let project = null;
const cache = {};

function target(W, H) {
  const canvas = Object.assign(document.createElement('canvas'), { width: W, height: H });
  return { canvas, ctx: canvas.getContext('2d', { willReadFrequently: true }) };
}

async function post(url, blob) {
  const res = await fetch(url, { method: 'POST', body: blob }); // a Blob body uploads ~15x faster than a typed array
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status} ${await res.text()}`);
}

window.framecode = {
  async load() {
    const platform = await browserPlatform();
    setPlatform(platform);
    const module = await import('/project.js');
    project = await loadProject(module.default, platform.loaders);
    return project.timeline.scenes.length;
  },

  /** Draw each [frame, label] at design size; report the time or the error per frame. */
  async check(marks) {
    const { ctx } = target(project.timeline.width, project.timeline.height);
    const results = [];
    for (const [frame, label] of marks) {
      const t0 = performance.now();
      try {
        await renderFrameReady(ctx, project, frame, 1, cache);
        results.push({ frame, label, ms: performance.now() - t0 });
      } catch (error) {
        results.push({ frame, label, error: String(error.stack || error).split('\n').slice(0, 3).join(' | ') });
      }
    }
    return results;
  },

  async stills({ marks, W, H, scale }) {
    const { canvas, ctx } = target(W, H);
    for (const [frame, name] of marks) {
      await renderFrameReady(ctx, project, frame, scale, cache);
      const png = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      await post(`/__still/${name}`, png);
    }
  },

  /** Render frames [from, to) and post each one, in order, to the job's encoder. */
  async renderRange({ job, from, to, W, H, scale, motionBlur }) {
    const { ctx } = target(W, H);
    const samples = Math.max(1, motionBlur | 0);
    const acc = samples > 1 ? new Float32Array(W * H * 4) : null;
    const out = samples > 1 ? new Uint8ClampedArray(W * H * 4) : null;
    for (let f = from; f < to; f++) {
      let data;
      if (samples <= 1) {
        await renderFrameReady(ctx, project, f, scale, cache);
        data = ctx.getImageData(0, 0, W, H).data;
      } else {
        acc.fill(0);
        for (let k = 0; k < samples; k++) {
          const offset = ((k + 0.5) / samples - 0.5) * 0.5; // 180-degree shutter centred on the frame
          await renderFrameReady(ctx, project, Math.max(0, f + offset), scale, cache);
          const d = ctx.getImageData(0, 0, W, H).data;
          for (let i = 0; i < d.length; i++) acc[i] += d[i];
        }
        for (let i = 0; i < acc.length; i++) out[i] = acc[i] / samples + 0.5;
        data = out;
      }
      await post(`/__frame/${job}`, new Blob([data]));
    }
  },
};
