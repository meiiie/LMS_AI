import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";

export const OUTPUT_PATH_DIRECTORY_ERROR =
  "runtime evidence output path must not be a directory";
export const OUTPUT_PATH_SYMLINK_ERROR =
  "runtime evidence output path must not be a symlink";
export const OUTPUT_PATH_PARENT_SYMLINK_ERROR =
  "runtime evidence output path parent must not be a symlink";

export function validateOutputPath(outputPath) {
  const resolved = path.resolve(outputPath);
  if (existsSync(resolved)) {
    const stat = lstatSync(resolved);
    if (stat.isSymbolicLink()) {
      throw new Error(OUTPUT_PATH_SYMLINK_ERROR);
    }
    if (stat.isDirectory()) {
      throw new Error(OUTPUT_PATH_DIRECTORY_ERROR);
    }
  }
  for (const parent of parentPaths(resolved)) {
    if (existsSync(parent) && lstatSync(parent).isSymbolicLink()) {
      throw new Error(`${OUTPUT_PATH_PARENT_SYMLINK_ERROR}: ${parent}`);
    }
  }
}

export function writeJsonFile(outputPath, payload) {
  const resolved = path.resolve(outputPath);
  validateOutputPath(resolved);
  mkdirSync(path.dirname(resolved), { recursive: true });
  validateOutputPath(resolved);
  let tempPath = path.join(
    path.dirname(resolved),
    `.${path.basename(resolved)}.${process.pid}.${Date.now()}.${randomUUID()}.tmp`,
  );
  try {
    const fd = openSync(tempPath, "wx", 0o600);
    try {
      writeFileSync(fd, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    validateOutputPath(resolved);
    renameSync(tempPath, resolved);
    tempPath = null;
  } finally {
    if (tempPath && existsSync(tempPath)) {
      rmSync(tempPath, { force: true });
    }
  }
}

function parentPaths(resolvedPath) {
  const parents = [];
  let current = path.dirname(resolvedPath);
  while (current && current !== path.dirname(current)) {
    parents.push(current);
    current = path.dirname(current);
  }
  if (current) {
    parents.push(current);
  }
  return parents;
}
