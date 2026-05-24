import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopDir = path.resolve(__dirname, "..");
const frontendPort = process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420";
const backendPort = process.env.WIII_PLAYWRIGHT_BACKEND_PORT || "8000";
const command = process.platform === "win32" ? "cmd.exe" : "npm";
const args = process.platform === "win32"
  ? ["/d", "/s", "/c", `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`]
  : ["run", "dev", "--", "--host", "127.0.0.1", "--port", frontendPort];

const child = spawn(
  command,
  args,
  {
    cwd: desktopDir,
    stdio: "inherit",
    env: {
      ...process.env,
      VITE_API_URL: process.env.VITE_API_URL || `http://127.0.0.1:${backendPort}`,
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
