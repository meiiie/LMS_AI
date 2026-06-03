import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopDir = path.resolve(__dirname, "..");
const SUMMARY_SCHEMA = "wiii.runtime_flow_browser_replay_summary.v1";
const ENV_FLAG = "WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE";
const ALLOW_FLAG = "--allow-run";
const SUMMARY_ENV = "WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON";

function parseArgs(argv) {
  const forwarded = [];
  let mode = process.env.WIII_RUNTIME_LEDGER_BROWSER_REPLAY_MODE || "local";
  let summaryPath = process.env[SUMMARY_ENV] || "";
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === ALLOW_FLAG) {
      continue;
    }
    if (item === "--mode") {
      mode = argv[index + 1] || "";
      index += 1;
      continue;
    }
    if (item.startsWith("--mode=")) {
      mode = item.slice("--mode=".length);
      continue;
    }
    if (item === "--out") {
      summaryPath = argv[index + 1] || "";
      index += 1;
      continue;
    }
    if (item.startsWith("--out=")) {
      summaryPath = item.slice("--out=".length);
      continue;
    }
    forwarded.push(item);
  }
  return { forwarded, mode, summaryPath };
}

function fail(message) {
  console.error(message);
  process.exit(2);
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`Usage: node scripts/probe-runtime-ledger-browser-replay-evidence.mjs ${ALLOW_FLAG} --out summary.json [--mode local|remote] [playwright args...]

Runs the guarded backend-evidence-to-desktop Runtime-tab replay and writes the
hash/count-only ${SUMMARY_SCHEMA} artifact.

Required guard:
  ${ENV_FLAG}=1
  ${ALLOW_FLAG}

Required output:
  --out summary.json or ${SUMMARY_ENV}=summary.json
`);
  process.exit(0);
}

if (process.env[ENV_FLAG] !== "1") {
  fail(`${ENV_FLAG}=1 is required to collect browser replay evidence.`);
}
if (!process.argv.includes(ALLOW_FLAG)) {
  fail(`${ALLOW_FLAG} is required to collect browser replay evidence.`);
}

const { forwarded, mode, summaryPath } = parseArgs(process.argv.slice(2));
if (!summaryPath) {
  fail(`--out or ${SUMMARY_ENV} is required to write browser replay summary evidence.`);
}
const runnerName =
  mode === "remote"
    ? "run-runtime-ledger-browser-replay.mjs"
    : mode === "local"
      ? "run-runtime-ledger-browser-replay-local.mjs"
      : "";
if (!runnerName) {
  fail("--mode must be either local or remote.");
}

const runner = path.join(__dirname, runnerName);
if (!existsSync(runner)) {
  fail(`Browser replay runner does not exist: ${runner}`);
}

const result = spawnSync(process.execPath, [runner, ...forwarded], {
  cwd: desktopDir,
  stdio: "inherit",
  env: {
    ...process.env,
    [ENV_FLAG]: "1",
    [SUMMARY_ENV]: summaryPath,
  },
});

if (typeof result.status === "number") {
  process.exit(result.status);
}
if (result.error) {
  console.error(`browser replay evidence runner failed to start: ${result.error.message}`);
}
process.exit(1);
