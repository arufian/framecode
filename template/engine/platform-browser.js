// Browser platform, shared by the studio and the headless render page: canvases,
// asset loaders, and the p5.js constructor the engine draws scenes with.

export async function browserPlatform() {
  let p5;
  try {
    ({ default: p5 } = await import('/node_modules/p5/lib/p5.esm.min.js'));
  } catch {
    throw new Error('p5.js is not installed in this project: run npm install --save-exact p5@2');
  }
  p5.disableFriendlyErrors = true; // parameter checks cost more than the drawing itself
  const container = document.createElement('div');
  container.hidden = true; // the p5 canvas is offscreen; the engine composites it
  document.body.appendChild(container);
  return {
    p5,
    container,
    createCanvas: (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h }),
    loaders: {
      loadJSON: async (p) => {
        const res = await fetch(`/${p}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`${p}: HTTP ${res.status}`);
        return res.json();
      },
      // Images arrive as p5.Image, ready for p.image(), p.tint(), and the draw.js helpers.
      loadImage: (p) => new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
          const out = new p5.Image(img.naturalWidth, img.naturalHeight);
          out.drawingContext.drawImage(img, 0, 0);
          resolve(out);
        };
        img.onerror = () => reject(new Error(`image failed to load: ${p}`));
        img.src = `/${p}`;
      }),
      loadFont: async ({ family, src, weight = 400, style = 'normal' }) => {
        const face = new FontFace(family, `url(/${src})`, { weight: String(weight), style });
        await face.load();
        document.fonts.add(face);
      },
    },
  };
}
