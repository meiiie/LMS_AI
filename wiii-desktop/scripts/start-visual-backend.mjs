import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const backendDir = path.join(repoRoot, "maritime-ai-service");
const backendPort = process.env.WIII_PLAYWRIGHT_BACKEND_PORT || "8000";
const frontendPort = process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420";

function commandWorks(command, args = ["--version"]) {
  try {
    const result = spawnSync(command, args, {
      cwd: backendDir,
      stdio: "ignore",
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

const pythonCandidates = [
  process.env.WIII_PLAYWRIGHT_PYTHON,
  path.join(backendDir, ".venv", "Scripts", "python.exe"),
  path.join(backendDir, ".venv", "bin", "python"),
  "python",
].filter(Boolean);

const explicitPython = process.env.WIII_PLAYWRIGHT_PYTHON;
const uvCommand = process.env.WIII_PLAYWRIGHT_UV || "uv";
const useUv =
  !explicitPython &&
  process.env.WIII_PLAYWRIGHT_BACKEND_USE_UV !== "0" &&
  commandWorks(uvCommand);
const python = explicitPython || pythonCandidates.find((candidate) => candidate === "python" || existsSync(candidate));

if (!useUv && !python) {
  console.error("Could not find a Python executable for the visual backend.");
  process.exit(1);
}

const command = useUv ? uvCommand : python;
const args = useUv
  ? [
      "run",
      "--no-project",
      "--python",
      "3.12",
      "--with-requirements",
      "requirements.txt",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      backendPort,
      "--log-level",
      "warning",
    ]
  : [
      "-m",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      backendPort,
      "--log-level",
      "warning",
    ];

const child = spawn(
  command,
  args,
  {
    cwd: backendDir,
    stdio: "inherit",
    env: {
      ...process.env,
      ENVIRONMENT: "development",
      ENABLE_DEV_LOGIN: "true",
      DEV_LOGIN_DEFAULT_EMAIL: process.env.DEV_LOGIN_DEFAULT_EMAIL || "playwright@localhost",
      DEV_LOGIN_DEFAULT_ROLE: process.env.DEV_LOGIN_DEFAULT_ROLE || "admin",
      JWT_SECRET_KEY:
        process.env.JWT_SECRET_KEY ||
        "local-playwright-dev-secret-at-least-32-bytes",
      CORS_ORIGINS:
        process.env.CORS_ORIGINS ||
        JSON.stringify([
          `http://localhost:${frontendPort}`,
          `http://127.0.0.1:${frontendPort}`,
        ]),
      ENABLE_STRUCTURED_VISUALS: "true",
      ENABLE_CODE_STUDIO_STREAMING: "true",
      VITE_API_URL: process.env.VITE_API_URL || `http://127.0.0.1:${backendPort}`,
      PYTHONIOENCODING: "utf-8",
    },
  },
);

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));
process.on("exit", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
