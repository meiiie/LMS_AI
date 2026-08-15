import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const brandRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(brandRoot, "..", "..", "..", "..");
const desktopRoot = path.join(repositoryRoot, "wiii-desktop");
const require = createRequire(path.join(desktopRoot, "package.json"));
const { chromium } = require("playwright");

const renders = [
  {
    source: "neko-peek-mark.svg",
    output: "neko-peek-vector-mark.png",
    width: 768,
    height: 768,
    background: "#e7e3de",
  },
  {
    source: "neko-peek-mark-on-dark.svg",
    output: "neko-peek-vector-mark-on-dark.png",
    width: 768,
    height: 768,
    background: "#232324",
  },
  {
    source: "neko-peek-wordmark.svg",
    output: "neko-peek-vector-wordmark.png",
    width: 1360,
    height: 512,
    background: "#e7e3de",
  },
];

const browserCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
];
const executablePath = browserCandidates.find((candidate) => existsSync(candidate));
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});
try {
  for (const render of renders) {
    const sourcePath = path.join(brandRoot, "logo", render.source);
    const outputPath = path.join(brandRoot, "previews", render.output);
    const svg = await readFile(sourcePath, "utf8");
    const page = await browser.newPage({
      viewport: { width: render.width, height: render.height },
      deviceScaleFactor: 1,
    });
    await page.setContent(`<!doctype html>
      <style>
        html, body {
          width: ${render.width}px;
          height: ${render.height}px;
          margin: 0;
          display: grid;
          place-items: center;
          overflow: hidden;
          background: ${render.background};
        }
        svg { width: 82%; height: 82%; }
      </style>
      ${svg}`);
    await page.screenshot({ path: outputPath });
    await page.close();
    console.log(`Wrote ${outputPath}`);
  }
} finally {
  await browser.close();
}
