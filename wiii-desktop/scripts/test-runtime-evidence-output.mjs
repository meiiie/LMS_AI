import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  OUTPUT_PATH_DIRECTORY_ERROR,
  OUTPUT_PATH_PARENT_SYMLINK_ERROR,
  OUTPUT_PATH_SYMLINK_ERROR,
  writeJsonFile,
} from "./runtime-evidence-output.mjs";

function withTempDir(callback) {
  const tempDir = mkdtempSync(path.join(os.tmpdir(), "wiii-runtime-evidence-output-"));
  try {
    callback(tempDir);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function trySymlink(target, linkPath, type) {
  try {
    symlinkSync(target, linkPath, type);
  } catch (error) {
    if (error && ["EPERM", "EACCES", "ENOSYS"].includes(error.code)) {
      return false;
    }
    throw error;
  }
  return true;
}

function assertNoTempFiles(tempDir, outputName) {
  assert.deepEqual(
    readdirSync(tempDir).filter(
      (entry) => entry.startsWith(`.${outputName}.`) && entry.endsWith(".tmp"),
    ),
    [],
  );
}

withTempDir((tempDir) => {
  const outputPath = path.join(tempDir, "evidence.json");
  writeJsonFile(outputPath, { status: "pass" });
  assert.deepEqual(JSON.parse(readFileSync(outputPath, "utf8")), { status: "pass" });
  assertNoTempFiles(tempDir, "evidence.json");
});

withTempDir((tempDir) => {
  const outputPath = path.join(tempDir, "evidence.json");
  writeFileSync(outputPath, "old", "utf8");
  writeJsonFile(outputPath, { status: "pass", count: 1 });
  assert.deepEqual(JSON.parse(readFileSync(outputPath, "utf8")), {
    status: "pass",
    count: 1,
  });
  assertNoTempFiles(tempDir, "evidence.json");
});

withTempDir((tempDir) => {
  const outputPath = path.join(tempDir, "evidence");
  mkdirSync(outputPath);
  assert.throws(
    () => writeJsonFile(outputPath, { status: "pass" }),
    new RegExp(OUTPUT_PATH_DIRECTORY_ERROR),
  );
  assert.deepEqual(readdirSync(outputPath), []);
});

withTempDir((tempDir) => {
  const targetPath = path.join(tempDir, "target.json");
  writeFileSync(targetPath, "keep", "utf8");
  const outputPath = path.join(tempDir, "evidence.json");
  if (!trySymlink(targetPath, outputPath, "file")) {
    return;
  }
  assert.throws(
    () => writeJsonFile(outputPath, { status: "pass" }),
    new RegExp(OUTPUT_PATH_SYMLINK_ERROR),
  );
  assert.equal(readFileSync(targetPath, "utf8"), "keep");
});

withTempDir((tempDir) => {
  const targetDir = path.join(tempDir, "target-dir");
  mkdirSync(targetDir);
  const symlinkParent = path.join(tempDir, "linked-parent");
  if (!trySymlink(targetDir, symlinkParent, "dir")) {
    return;
  }
  assert.throws(
    () => writeJsonFile(path.join(symlinkParent, "evidence.json"), { status: "pass" }),
    new RegExp(OUTPUT_PATH_PARENT_SYMLINK_ERROR),
  );
  assert.deepEqual(readdirSync(targetDir), []);
});

console.log("runtime-evidence-output tests passed");
