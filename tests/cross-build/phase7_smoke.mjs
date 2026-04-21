#!/usr/bin/env node
// Phase 7 smoke test — the executable specification for `spec/wasm-ffi.spec.md`.
//
// Loads the wasm32-unknown-unknown build of the Rust target via the standard
// WebAssembly.instantiate API, drives it through leap_version / leap_db_new /
// leap_exec / leap_db_close, and asserts the JSON result shape exactly matches
// what the native cross-build harness would expect.
//
// Exit 0 = GREEN, exit 1 = first mismatch.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const WASM_PATH = resolve(
  __dirname,
  '../../src-rust/target/wasm32-unknown-unknown/release/sqlite_leap.wasm',
);

// Expected version constant from the spec: 0x030b0000.
const EXPECTED_VERSION = 0x030b0000;

let failures = 0;
function check(label, cond, detail) {
  if (cond) {
    console.log(`PASS ${label}`);
  } else {
    console.log(`FAIL ${label}${detail ? ` — ${detail}` : ''}`);
    failures++;
  }
}
function checkEqual(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  check(label, g === w, `got ${g}, want ${w}`);
}

async function main() {
  const wasmBytes = readFileSync(WASM_PATH);
  const { instance } = await WebAssembly.instantiate(wasmBytes, {});
  const x = instance.exports;

  // -------- 1. version sanity --------
  const v = x.leap_version();
  check(
    'leap_version constant',
    v === EXPECTED_VERSION,
    `got 0x${(v >>> 0).toString(16)}, want 0x${EXPECTED_VERSION.toString(16)}`,
  );

  const memory = x.memory;

  // Helper: write a UTF-8 string into linear memory via leap_alloc, return [ptr, len].
  function writeStr(s) {
    const bytes = new TextEncoder().encode(s);
    const ptr = x.leap_alloc(bytes.length);
    if (ptr === 0 && bytes.length > 0) {
      throw new Error('leap_alloc returned 0');
    }
    new Uint8Array(memory.buffer, ptr, bytes.length).set(bytes);
    return [ptr, bytes.length];
  }

  // Helper: read a UTF-8 JSON buffer, free it, return parsed JSON.
  // Packed result: upper 32 bits = ptr, lower 32 = len.
  function unpackAndReadJson(packed) {
    const ptr = Number(packed >> 32n);
    const len = Number(packed & 0xFFFFFFFFn);
    if (ptr === 0 || len === 0) {
      // Not supposed to happen — both success and error responses emit a buffer.
      throw new Error(`leap_exec returned empty buffer: ptr=${ptr} len=${len}`);
    }
    const view = new Uint8Array(memory.buffer, ptr, len).slice();
    x.leap_free(ptr, len);
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(view));
  }

  function exec(handle, sql) {
    const [sPtr, sLen] = writeStr(sql);
    // leap_exec returns u64 — WebAssembly exports BigInt u64 automatically.
    const packed = x.leap_exec(handle, sPtr, sLen);
    x.leap_free(sPtr, sLen);
    return unpackAndReadJson(packed);
  }

  // -------- 2. open a fresh DB --------
  const handle = x.leap_db_new();
  check('leap_db_new returned non-zero handle', handle !== 0);

  // -------- 3. CREATE TABLE --------
  checkEqual(
    'CREATE TABLE t (a INTEGER, b TEXT)',
    exec(handle, 'CREATE TABLE t (a INTEGER, b TEXT);'),
    { rows: [] },
  );

  // -------- 4. INSERTs --------
  checkEqual(
    "INSERT INTO t VALUES (1, 'hello')",
    exec(handle, "INSERT INTO t VALUES (1, 'hello');"),
    { rows: [] },
  );
  checkEqual(
    "INSERT INTO t VALUES (2, 'world')",
    exec(handle, "INSERT INTO t VALUES (2, 'world');"),
    { rows: [] },
  );
  checkEqual(
    'INSERT INTO t VALUES (3, NULL)',
    exec(handle, 'INSERT INTO t VALUES (3, NULL);'),
    { rows: [] },
  );

  // -------- 5. SELECT * --------
  checkEqual(
    'SELECT * FROM t returns all three rows',
    exec(handle, 'SELECT * FROM t;'),
    { rows: [[1, 'hello'], [2, 'world'], [3, null]] },
  );

  // -------- 6. SELECT with projection + WHERE --------
  checkEqual(
    'SELECT a FROM t WHERE a > 1',
    exec(handle, 'SELECT a FROM t WHERE a > 1;'),
    { rows: [[2], [3]] },
  );

  // -------- 7. Error shape: unknown table --------
  checkEqual(
    'SELECT * FROM missing — STORAGE_TABLE_NOT_FOUND',
    exec(handle, 'SELECT * FROM nosuch;'),
    { error: { name: 'STORAGE_TABLE_NOT_FOUND', fields: { table: 'nosuch' } } },
  );

  // -------- 8. Error shape: parse error --------
  const parseResult = exec(handle, 'SELECT FROM t;');
  check(
    'SELECT FROM t — PARSE_UNEXPECTED_TOKEN',
    parseResult.error && parseResult.error.name === 'PARSE_UNEXPECTED_TOKEN',
    `got ${JSON.stringify(parseResult)}`,
  );

  // -------- 9. Close the DB, then verify invalid handle --------
  x.leap_db_close(handle);

  const invalid = exec(0, 'SELECT 1;');
  check(
    'exec on invalid handle returns STORAGE-shaped error',
    invalid.error && invalid.error.name === 'STORAGE_TABLE_NOT_FOUND',
    `got ${JSON.stringify(invalid)}`,
  );

  // -------- 10. Allocator round-trip --------
  const p = x.leap_alloc(16);
  check('leap_alloc(16) returned non-zero', p !== 0);
  x.leap_free(p, 16);
  check('leap_alloc(0) returns 0', x.leap_alloc(0) === 0);

  console.log(
    `SUMMARY phase=7 target=wasm passed=${
      (failures === 0 ? 'ALL' : `?`)
    } failed=${failures}`,
  );
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error('phase7_smoke error:', e);
  process.exit(1);
});
