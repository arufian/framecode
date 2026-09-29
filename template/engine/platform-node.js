// Node platform: @napi-rs/canvas surfaces (Skia, same rasterizer family as Chrome).
import { createCanvas, loadImage, GlobalFonts } from '@napi-rs/canvas';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export function nodePlatform(root) {
  const resolve = (p) => path.resolve(root, p);
  return {
    createCanvas: (w, h) => createCanvas(w, h),
    loaders: {
      loadJSON: async (p) => JSON.parse(await readFile(resolve(p), 'utf8')),
      loadImage: async (p) => loadImage(await readFile(resolve(p))),
      loadFont: async ({ family, src }) => {
        if (!GlobalFonts.registerFromPath(resolve(src), family)) throw new Error(`could not load font ${src}`);
      },
    },
  };
}
