import { existsSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");

function commandWorks(command, args = ["--version"]) {
  try {
    const result = spawnSync(command, args, {
      stdio: "ignore",
      shell: process.platform === "win32",
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

const candidates = [
  process.env.WIII_PLAYWRIGHT_PYTHON,
  path.join(repoRoot, "maritime-ai-service", ".venv", "Scripts", "python.exe"),
  path.join(repoRoot, "maritime-ai-service", ".venv", "bin", "python"),
  "python",
].filter(Boolean);

const explicitPython = process.env.WIII_PLAYWRIGHT_PYTHON;
const uvCommand = process.env.WIII_PLAYWRIGHT_UV || "uv";
const useUv =
  !explicitPython &&
  process.env.WIII_PLAYWRIGHT_PYTHON_USE_UV !== "0" &&
  commandWorks(uvCommand);
const python = explicitPython || candidates.find((candidate) => candidate === "python" || existsSync(candidate));

if (!useUv && !python) {
  console.error("Could not find Python or uv for web_visual_smoke.py");
  process.exit(1);
}

const smokeScript = path.join(__dirname, "web_visual_smoke.py");
const command = useUv ? uvCommand : python;
const args = useUv
  ? ["run", "--no-project", "--with", "playwright", "python", smokeScript, ...process.argv.slice(2)]
  : [smokeScript, ...process.argv.slice(2)];
const result = spawnSync(command, args, {
  stdio: "inherit",
  cwd: repoRoot,
  env: {
    ...process.env,
    PYTHONUTF8: "1",
  },
  shell: process.platform === "win32" && useUv,
});

if (typeof result.status === "number") {
  process.exit(result.status);
}

process.exit(1);
