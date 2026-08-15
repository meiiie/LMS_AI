import { copyFile, mkdir, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const brandRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(brandRoot, "..", "..", "..", "..");
const desktopRoot = path.join(repositoryRoot, "wiii-desktop");
const require = createRequire(path.join(desktopRoot, "package.json"));
const { chromium } = require("playwright");

const browserCandidates = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
];

const jobs = [
  { source: "wiii-readme-banner.svg", output: "wiii-readme-banner.png", width: 1600, height: 640 },
  { source: "wiii-social-card.svg", output: "wiii-social-card.png", width: 1200, height: 630 },
];

const executablePath = browserCandidates.find((candidate) => existsSync(candidate));
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});

try {
  await mkdir(path.join(brandRoot, "social"), { recursive: true });
  for (const job of jobs) {
    const source = await readFile(path.join(brandRoot, "social", job.source), "utf8");
    const page = await browser.newPage({
      viewport: { width: job.width, height: job.height },
      deviceScaleFactor: 1,
    });
    await page.setContent(`<!doctype html><style>
      html, body { width: ${job.width}px; height: ${job.height}px; margin: 0; overflow: hidden; background: transparent; }
      svg { display: block; width: 100%; height: 100%; }
    </style>${source}`);
    const output = path.join(brandRoot, "social", job.output);
    await page.screenshot({ path: output, omitBackground: true });
    await page.close();
    console.log(`Wrote ${output}`);
  }
} finally {
  await browser.close();
}

await copyFile(
  path.join(brandRoot, "social", "wiii-social-card.png"),
  path.join(desktopRoot, "public", "og-image.png"),
);
console.log("Synced Wiii social card to wiii-desktop/public/og-image.png");
