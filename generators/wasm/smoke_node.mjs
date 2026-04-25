// WASM smoke for sqlite-leap.
//
// Loads ../../src-wasm/sqlite_leap.wasm, runs `SELECT 1+1` (and a few more
// constant-expression cases) through `sqlite_leap_eval`, prints results, and
// exits 0 iff every case matches the expected value.
//
// Usage:  node generators/wasm/smoke_node.mjs
//
// No npm deps; standard library only. Pairs with build.sh.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..");
const WASM_PATH = join(REPO, "src-wasm", "sqlite_leap.wasm");

const bytes = readFileSync(WASM_PATH);
const { instance } = await WebAssembly.instantiate(bytes, {});
const {
    sqlite_leap_alloc,
    sqlite_leap_free,
    sqlite_leap_eval,
    sqlite_leap_version,
    memory,
} = instance.exports;

const enc = new TextEncoder();
const dec = new TextDecoder();

function evalSql(src) {
    const buf = enc.encode(src);
    const inPtr = sqlite_leap_alloc(buf.length);
    if (inPtr === 0 && buf.length > 0) throw new Error("alloc failed");
    new Uint8Array(memory.buffer, inPtr, buf.length).set(buf);

    const packed = sqlite_leap_eval(inPtr, buf.length);
    // packed is BigInt because the FFI return is u64.
    const ptr = Number(packed >> 32n);
    const len = Number(packed & 0xffffffffn);

    sqlite_leap_free(inPtr, buf.length);

    if (ptr === 0 || len === 0) return "";
    const view = new Uint8Array(memory.buffer, ptr, len).slice();
    sqlite_leap_free(ptr, len);
    return dec.decode(view);
}

const cases = [
    ["SELECT 1+1",              "2"],
    ["1+1",                     "2"],
    ["SELECT 2 * 3 + 4",        "10"],
    ["SELECT (1 + 2) * 3",      "9"],
    ["SELECT -5 + 1",           "-4"],
    ["SELECT 'ab' || 'cd'",     "abcd"],
];

const v = sqlite_leap_version();
console.log(`engine version: 0x${v.toString(16)} (major=${(v>>>24)&0xff} minor=${(v>>>16)&0xff} patch=${(v>>>8)&0xff})`);
console.log(`wasm size: ${bytes.length} bytes (${(bytes.length/1024).toFixed(1)} KB)`);
console.log("");

let allOk = true;
for (const [src, expect] of cases) {
    let got;
    try { got = evalSql(src); } catch (e) { got = `throw:${e.message}`; }
    const ok = got === expect;
    if (!ok) allOk = false;
    console.log(`  ${ok ? "OK  " : "FAIL"}  ${src.padEnd(28)}  ->  ${JSON.stringify(got)}${ok ? "" : `  (expected ${JSON.stringify(expect)})`}`);
}

if (allOk) {
    console.log("\nOK: all cases passed");
    process.exit(0);
} else {
    console.log("\nFAIL: one or more cases failed");
    process.exit(1);
}
