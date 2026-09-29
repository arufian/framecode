// Rendering only needs chrome-headless-shell (~200 MB); skip Puppeteer's full Chrome download.
module.exports = { chrome: { skipDownload: true } };
