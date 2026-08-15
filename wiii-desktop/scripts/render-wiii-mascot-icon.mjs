import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";

const desktopRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(desktopRoot, "..");
const canonicalIcon = path.join(
  repositoryRoot,
  "docs",
  "assets",
  "brand",
  "neko-family-v1",
  "logo",
  "png",
  "neko-peek-app-icon-master.png",
);
const outputPath = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(desktopRoot, "src-tauri", "icons", "wiii-mascot-app-icon.png");

await mkdir(path.dirname(outputPath), { recursive: true });
await copyFile(canonicalIcon, outputPath);
console.log(`Copied canonical Neko Peek icon to ${outputPath}`);
