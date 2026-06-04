import { closeSync, existsSync, mkdirSync, openSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(desktopDir, "..");
const backendDir = path.join(repoRoot, "maritime-ai-service");
const backendPort = process.env.WIII_PLAYWRIGHT_BACKEND_PORT || "8000";
const frontendPort = process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420";
const backendUrl =
  process.env.WIII_RUNTIME_FLOW_BACKEND_URL || `http://127.0.0.1:${backendPort}`;
const resultDir = path.join(repoRoot, "test-results", "runtime-flow-browser-replay");

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

async function healthOk() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2_000);
  try {
    const response = await fetch(`${backendUrl}/health`, {
      signal: controller.signal,
    });
    return response.status === 200;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForBackend(child) {
  const deadline = Date.now() + Number(process.env.WIII_RUNTIME_FLOW_BACKEND_START_TIMEOUT_MS || 180_000);
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`backend exited before health check succeeded, code=${child.exitCode}`);
    }
    if (await healthOk()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`backend did not become healthy at ${backendUrl}/health`);
}

function stopProcessTree(child) {
  if (!child || child.exitCode !== null || child.pid === undefined) {
    return;
  }
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
    });
    return;
  }
  child.kill("SIGTERM");
}

function backendCommand() {
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
  const python =
    explicitPython ||
    pythonCandidates.find((candidate) => candidate === "python" || existsSync(candidate));

  if (!useUv && !python) {
    throw new Error("could not find Python or uv for local backend startup");
  }

  return useUv
    ? {
        command: uvCommand,
        args: [
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
        ],
      }
    : {
        command: python,
        args: [
          "-m",
          "uvicorn",
          "app.main:app",
          "--host",
          "127.0.0.1",
          "--port",
          backendPort,
          "--log-level",
          "warning",
        ],
      };
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`Usage: node scripts/run-runtime-ledger-browser-replay-local.mjs [playwright args...]

Starts a disposable local Wiii backend if ${backendUrl}/health is not already
healthy, runs the backend evidence -> desktop browser replay loop, and cleans up
the backend process tree it started.

Forwarded arguments are passed to run-runtime-ledger-browser-replay.mjs.
`);
  process.exit(0);
}

let backend = null;
let stdoutFd = null;
let stderrFd = null;

try {
  if (await healthOk()) {
    console.log(`[INFO] Reusing healthy backend at ${backendUrl}`);
  } else {
    mkdirSync(resultDir, { recursive: true });
    stdoutFd = openSync(path.join(resultDir, "local-backend.out.log"), "w");
    stderrFd = openSync(path.join(resultDir, "local-backend.err.log"), "w");
    const backendProcess = backendCommand();
    console.log(`[INFO] Starting local backend: ${backendProcess.command} ${backendProcess.args.join(" ")}`);
    backend = spawn(backendProcess.command, backendProcess.args, {
      cwd: backendDir,
      stdio: ["ignore", stdoutFd, stderrFd],
      env: {
        ...process.env,
        ENVIRONMENT: "development",
        ENABLE_DEV_LOGIN: "true",
        DEV_LOGIN_DEFAULT_EMAIL:
          process.env.DEV_LOGIN_DEFAULT_EMAIL || "playwright@localhost",
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
        VITE_API_URL: process.env.VITE_API_URL || backendUrl,
        PYTHONIOENCODING: "utf-8",
      },
    });
    await waitForBackend(backend);
  }

  const runner = path.join(__dirname, "run-runtime-ledger-browser-replay.mjs");
  const result = spawnSync(process.execPath, [runner, ...process.argv.slice(2)], {
    cwd: desktopDir,
    stdio: "inherit",
    env: {
      ...process.env,
      WIII_RUNTIME_FLOW_BACKEND_URL: backendUrl,
    },
  });
  if (typeof result.status === "number") {
    process.exitCode = result.status;
  } else {
    if (result.error) {
      console.error(`runtime ledger browser replay failed to start: ${result.error.message}`);
    }
    process.exitCode = 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  stopProcessTree(backend);
  if (stdoutFd !== null) closeSync(stdoutFd);
  if (stderrFd !== null) closeSync(stderrFd);
}
