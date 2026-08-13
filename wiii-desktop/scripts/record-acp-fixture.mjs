#!/usr/bin/env node
/**
 * T203 fixture recorder — drives a REAL ACP agent over stdio and records
 * every frame (both directions) as annotated NDJSON for golden-fixture tests.
 *
 * Usage:
 *   node scripts/record-acp-fixture.mjs neko acp
 *   node scripts/record-acp-fixture.mjs gemini --experimental-acp
 *
 * Output: src/__tests__/neko-chill/fixtures/<agent>-acp-session.ndjson
 * Lines are prefixed objects: {"dir":"c2a"|"a2c","frame":{...}}
 *
 * The prompt asks for a file write so approval-gated agents emit
 * session/request_permission; the recorder answers with the first
 * REJECT-looking option (fail-closed shape capture, no side effects).
 */

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const [, , cmd, ...args] = process.argv;
if (!cmd) {
  console.error("usage: record-acp-fixture.mjs <cmd> [args...]");
  process.exit(1);
}

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "src", "__tests__", "neko-chill", "fixtures");
mkdirSync(outDir, { recursive: true });
const outFile = join(outDir, `${cmd.replace(/\W+/g, "-")}-acp-session.ndjson`);

const cwd = mkdtempSync(join(tmpdir(), "neko-chill-fixture-"));
const recorded = [];
let nextId = 1;
const pending = new Map();

const child = spawn(cmd, args, {
  stdio: ["pipe", "pipe", "inherit"],
  shell: process.platform === "win32", // resolve .cmd shims
});

function send(frame) {
  recorded.push({ dir: "c2a", frame });
  child.stdin.write(JSON.stringify(frame) + "\n");
}

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    send({ jsonrpc: "2.0", id, method, params });
  });
}

function finish(reason) {
  console.error(`\n[recorder] finishing: ${reason}`);
  const text = recorded.map((r) => JSON.stringify(r)).join("\n") + "\n";
  writeFileSync(outFile, text, "utf8");
  console.error(`[recorder] ${recorded.length} frames -> ${outFile}`);
  try {
    child.kill();
  } catch {}
  process.exit(0);
}

let buffer = "";
child.stdout.on("data", (chunk) => {
  buffer += chunk.toString("utf8");
  let idx;
  while ((idx = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;
    let frame;
    try {
      frame = JSON.parse(line);
    } catch {
      recorded.push({ dir: "a2c", raw: line });
      continue;
    }
    recorded.push({ dir: "a2c", frame });

    // Response to one of our requests
    if (frame.id !== undefined && !frame.method && pending.has(frame.id)) {
      pending.get(frame.id)(frame);
      pending.delete(frame.id);
      continue;
    }
    // Agent -> client REQUEST (permission etc.): answer fail-closed.
    if (frame.id !== undefined && frame.method === "session/request_permission") {
      const options = frame.params?.options ?? [];
      const reject =
        options.find((o) => /reject|deny|cancel/i.test(`${o.kind} ${o.optionId} ${o.name ?? ""}`)) ??
        options[options.length - 1];
      send({
        jsonrpc: "2.0",
        id: frame.id,
        result: { outcome: { outcome: "selected", optionId: reject?.optionId ?? "" } },
      });
      continue;
    }
    // Any other agent request: refuse politely so the turn can proceed/end.
    if (frame.id !== undefined && frame.method) {
      send({
        jsonrpc: "2.0",
        id: frame.id,
        error: { code: -32601, message: `client does not implement ${frame.method}` },
      });
    }
  }
});

child.on("exit", (code) => finish(`agent exited (${code})`));
setTimeout(() => finish("timeout 120s"), 120_000);

const init = await request("initialize", {
  protocolVersion: 1,
  clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
  clientInfo: { name: "neko-chill-recorder", title: "Neko Chill Fixture Recorder", version: "0.1.0" },
});
console.error("[recorder] initialize ok:", JSON.stringify(init.result?.agentCapabilities ?? init));

const session = await request("session/new", { cwd, mcpServers: [] });
const sessionId = session.result?.sessionId;
console.error("[recorder] sessionId:", sessionId);
if (!sessionId) finish("no sessionId");

const prompt = await request("session/prompt", {
  sessionId,
  prompt: [
    {
      type: "text",
      text: "Hãy tạo file hello.txt với nội dung đúng một chữ 'hi' trong thư mục hiện tại, sau đó dừng.",
    },
  ],
});
console.error("[recorder] stopReason:", prompt.result?.stopReason);
finish("prompt turn complete");
