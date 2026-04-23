#!/usr/bin/env node
// Lane 7 — WASM bench harness runner.
//
// One runner binary, three modes, three targets. Modes:
//   cold-start    — measure instantiate → first query ready (single run; timed
//                   in-process here so we capture only the WASM work, not
//                   node's own startup)
//   parse-speed   — stream the same 10 MiB corpus used by native lane 2,
//                   per-statement (mirrors the native leap driver path)
//   select        — replay the native lane 3 workload (10k inserts +
//                   100k point selects) per-statement
//
// Targets:
//   sqlite-leap-wasm    — our src-wasm/sqlite_leap.wasm via the leap_* FFI
//                         surface (spec/wasm-ffi.spec.md)
//   sql.js              — 1.13.0, via initSqlJs + Database.exec / .run
//   sqlite-wasm         — @sqlite.org/sqlite-wasm 3.51.2-build9, via
//                         sqlite3.oo1.DB + db.exec (rowMode:'array')
//
// Output shape: when invoked with --emit-csv the runner prints a single
// `lane,target,value,units,iso8601` line to stdout (the bench CSV
// convention). Otherwise it prints a human-readable summary. The shell
// wrapper at ./run.sh does the emit-csv path.

import { readFileSync, existsSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import initSqlJs from 'sql.js';
import sqliteInit from '@sqlite.org/sqlite-wasm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const REPO_ROOT = '/Users/stanislav/code/sqlite-leap';
const LEAP_WASM = `${REPO_ROOT}/src-wasm/sqlite_leap.wasm`;
const PARSE_CORPUS = `${REPO_ROOT}/bench/lanes/02-parse-speed/corpus.sql`;
const SELECT_WORKLOAD = `${REPO_ROOT}/bench/lanes/03-select-in-memory/workload.sql`;

// ---------------- statement splitter (JS port of bench/lanes/_wrap_sql.py) ----
// The corpora are template-generated; no embedded `;` inside string literals
// beyond single-quoted text, no comments, no double-quoted identifiers. A
// simple scanner suffices.
function splitStatements(src) {
  const stmts = [];
  let buf = '';
  let inStr = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === "'") {
      inStr = !inStr;
      buf += ch;
    } else if (ch === ';' && !inStr) {
      const t = buf.trim();
      if (t) stmts.push(t + ';');
      buf = '';
    } else {
      buf += ch;
    }
  }
  const tail = buf.trim();
  if (tail) stmts.push(tail);
  return stmts;
}

// ---------------- driver interface ----------------
// Every driver exposes:
//   async setup()      — fully instantiate the engine + open a DB. Returns the
//                        driver object (opaque to callers), times recorded
//                        on `this`: `.tInstantiateMs` (load+instantiate) and
//                        `.tFirstQueryMs` (time for first SELECT 1 query).
//   execOne(sql)       — execute one SQL statement (sync if possible,
//                        otherwise await). Throws on error. Discards rows.
//   close()            — release resources.
//
// Cold-start measures: setup() wall clock + single SELECT 1. The individual
// sub-timings are logged for transparency.

class LeapDriver {
  constructor() { this.name = 'sqlite-leap-wasm'; }
  async setup() {
    const t0 = performance.now();
    const bytes = readFileSync(LEAP_WASM);
    const { instance } = await WebAssembly.instantiate(bytes, {});
    this.x = instance.exports;
    this.mem = this.x.memory;
    this.handle = this.x.leap_db_new();
    if (this.handle === 0) throw new Error('leap_db_new returned 0');
    this.enc = new TextEncoder();
    this.dec = new TextDecoder('utf-8');
    this.tInstantiateMs = performance.now() - t0;

    const t1 = performance.now();
    this.execOne('SELECT 1;');
    this.tFirstQueryMs = performance.now() - t1;
    return this;
  }
  execOne(sql) {
    const b = this.enc.encode(sql);
    const p = this.x.leap_alloc(b.length);
    if (p === 0 && b.length > 0) throw new Error('leap_alloc failed');
    new Uint8Array(this.mem.buffer, p, b.length).set(b);
    const packed = this.x.leap_exec(this.handle, p, b.length);
    this.x.leap_free(p, b.length);
    const rp = Number(packed >> 32n);
    const rl = Number(packed & 0xFFFFFFFFn);
    // Important: consuming the JSON buffer. We `slice()` to copy out so the
    // free doesn't dangle a view (Node's WASM memory may grow; slice is
    // safer than decode-then-free).
    const view = new Uint8Array(this.mem.buffer, rp, rl).slice();
    this.x.leap_free(rp, rl);
    // Cheap validation: decode only on demand. For parse lane we only need
    // to advance past the call, not parse JSON on every statement. But the
    // free contract requires us to consume the buffer, so we still decode.
    // We only JSON.parse on demand (e.g., cold-start verification).
    return view; // raw bytes; caller decodes if needed
  }
  close() {
    if (this.handle) this.x.leap_db_close(this.handle);
    this.handle = 0;
  }
}

class SqlJsDriver {
  constructor() { this.name = 'sql.js'; }
  async setup() {
    const t0 = performance.now();
    const SQL = await initSqlJs({});
    this.db = new SQL.Database();
    this.tInstantiateMs = performance.now() - t0;

    const t1 = performance.now();
    this.execOne('SELECT 1;');
    this.tFirstQueryMs = performance.now() - t1;
    return this;
  }
  execOne(sql) {
    // `.run()` executes a statement and discards the result object, which
    // is the closest analogue to leap's execOne (no row materialisation
    // beyond whatever the engine internally produced). We use `.run` for
    // non-SELECT and `.exec` for SELECT to actually drive the VDBE through
    // all rows — but for the bench we use `.exec` uniformly because sql.js
    // `.run` silently no-ops on SELECT (doesn't iterate the cursor).
    this.db.exec(sql);
  }
  close() {
    if (this.db) this.db.close();
    this.db = null;
  }
}

class SqliteWasmDriver {
  constructor() { this.name = 'sqlite-wasm'; }
  async setup() {
    const t0 = performance.now();
    this.sqlite3 = await sqliteInit();
    // Silence the noisy per-error console.warn emitted by `sqlite3_step`
    // on CONSTRAINT failures. Lane 2's corpus produces occasional
    // PRIMARY KEY collisions (random INT ids into an INTEGER PK column);
    // leap also errors on those (lane 2 counts errors-but-continues as
    // legitimate parse-lane work). We want apples-to-apples wall clock,
    // not stderr pollution.
    if (this.sqlite3.config) {
      this.sqlite3.config.warn = () => {};
      this.sqlite3.config.error = () => {};
      this.sqlite3.config.log = () => {};
    }
    this.db = new this.sqlite3.oo1.DB(':memory:', 'c');
    this.tInstantiateMs = performance.now() - t0;

    const t1 = performance.now();
    this.execOne('SELECT 1;');
    this.tFirstQueryMs = performance.now() - t1;
    return this;
  }
  execOne(sql) {
    // Use rowMode:'array' to force result-set materialisation (fair to leap
    // which serialises every row into JSON). returnValue:'resultRows' keeps
    // the hot path predictable.
    this.db.exec({ sql, rowMode: 'array', returnValue: 'resultRows' });
  }
  close() {
    if (this.db) this.db.close();
    this.db = null;
  }
}

function driverFor(target) {
  switch (target) {
    case 'sqlite-leap-wasm': return new LeapDriver();
    case 'sql.js':           return new SqlJsDriver();
    case 'sqlite-wasm':      return new SqliteWasmDriver();
    default: throw new Error(`unknown target: ${target}`);
  }
}

// ---------------- lanes ----------------

async function laneColdStart(target, runs, warmup) {
  // Cold-start must measure a FRESH WASM instantiation each time, not a
  // cached module. Both `initSqlJs` (sql.js) and `sqliteInit`
  // (@sqlite.org/sqlite-wasm) memoise their module load on first call
  // within a process — running N iterations in one process would measure
  // "first one cold, remaining N-1 hot," and the median would lie.
  //
  // Fix: spawn a child Node process per iteration, with `--mode=setup-only`.
  // The child times its own instantiate+first-query via performance.now()
  // and prints the elapsed seconds on stdout. This matches native lane 1's
  // convention of timing per-process.
  //
  // We deliberately measure ONLY the in-process WASM work — not Node
  // startup — because Node startup is identical across targets (same
  // binary, same version) and adds ~30 ms of constant overhead that would
  // swamp the microsecond signal we care about. If you want
  // Node-startup-inclusive numbers, wrap `run.sh` with hyperfine.
  const samples = [];
  const selfPath = __filename;
  for (let i = 0; i < warmup + runs; i++) {
    const r = spawnSync(process.execPath, [selfPath, '--mode=setup-only', `--target=${target}`], {
      cwd: __dirname,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (r.status !== 0) {
      throw new Error(`child exit ${r.status} for target=${target}\nstdout: ${r.stdout}\nstderr: ${r.stderr}`);
    }
    const lines = r.stdout.trim().split('\n');
    const last = lines[lines.length - 1];
    const m = last.match(/^SETUP_SECONDS\s+([\d.eE+-]+)$/);
    if (!m) throw new Error(`child did not emit SETUP_SECONDS line; got: ${r.stdout}`);
    const seconds = parseFloat(m[1]);
    if (i >= warmup) samples.push(seconds);
  }
  samples.sort((a, b) => a - b);
  const median = samples[Math.floor(samples.length / 2)];
  return { value: median, units: 'seconds', extra: { runs, warmup, samples } };
}

async function setupOnly(target) {
  // Child process path for laneColdStart. Prints SETUP_SECONDS <float> on
  // stdout and exits 0.
  const d = driverFor(target);
  const t0 = performance.now();
  await d.setup();
  const t1 = performance.now();
  d.close();
  process.stdout.write(`SETUP_SECONDS ${((t1 - t0) / 1000).toFixed(9)}\n`);
}

async function laneParseSpeed(target, runs, warmup) {
  if (!existsSync(PARSE_CORPUS)) {
    throw new Error(`parse corpus missing: ${PARSE_CORPUS} (run bench/lanes/02-parse-speed/generate-corpus.sh)`);
  }
  const corpusText = readFileSync(PARSE_CORPUS, 'utf8');
  const stmts = splitStatements(corpusText);
  const bytes = Buffer.byteLength(corpusText, 'utf8');

  const samples = [];
  for (let i = 0; i < warmup + runs; i++) {
    const d = driverFor(target);
    await d.setup();
    const t0 = performance.now();
    // Per-statement loop. We swallow per-statement errors (e.g., leap's
    // GROUP BY residuals, sql.js's strict SQL dialect quirks) — exactly
    // mirrors the native lane-2 _wrap_sql.py path, which wraps every stmt
    // as `statement ok` and the sqllogictest runner continues past FAILs.
    let errs = 0;
    for (const s of stmts) {
      try { d.execOne(s); } catch (_e) { errs++; }
    }
    const t1 = performance.now();
    d.close();
    if (i >= warmup) samples.push({ seconds: (t1 - t0) / 1000, errs });
  }
  samples.sort((a, b) => a.seconds - b.seconds);
  const medianSeconds = samples[Math.floor(samples.length / 2)].seconds;
  const medianErrs = samples[Math.floor(samples.length / 2)].errs;
  // Mirror native lane 2's 2026-04-21 CSV convention: when runs === 1, the
  // unit string explicitly flags single-run methodology so downstream
  // consumers can distinguish it from medianed values.
  const units = runs === 1 ? 'bytes_per_second_single_run' : 'bytes_per_second';
  return {
    value: Math.floor(bytes / medianSeconds),
    units,
    extra: { statements: stmts.length, bytes, runs, warmup, medianErrs, allSamples: samples },
  };
}

async function laneSelect(target, runs, warmup) {
  if (!existsSync(SELECT_WORKLOAD)) {
    throw new Error(`select workload missing: ${SELECT_WORKLOAD} (run bench/lanes/03-select-in-memory/generate-corpus.sh)`);
  }
  const workloadText = readFileSync(SELECT_WORKLOAD, 'utf8');
  const stmts = splitStatements(workloadText);
  // The workload file structure: PRAGMA, CREATE, BEGIN, 10k INSERT, COMMIT,
  // then 100k SELECTs. Count the SELECTs precisely.
  const nSelects = stmts.filter((s) => /^\s*SELECT\b/i.test(s)).length;

  const samples = [];
  for (let i = 0; i < warmup + runs; i++) {
    const d = driverFor(target);
    await d.setup();
    const t0 = performance.now();
    let errs = 0;
    for (const s of stmts) {
      try { d.execOne(s); } catch (_e) { errs++; }
    }
    const t1 = performance.now();
    d.close();
    if (i >= warmup) samples.push({ seconds: (t1 - t0) / 1000, errs });
  }
  samples.sort((a, b) => a.seconds - b.seconds);
  const medianSeconds = samples[Math.floor(samples.length / 2)].seconds;
  const medianErrs = samples[Math.floor(samples.length / 2)].errs;
  return {
    value: Math.floor(nSelects / medianSeconds),
    units: 'selects_per_second',
    extra: { nSelects, totalStatements: stmts.length, runs, warmup, medianErrs, allSamples: samples },
  };
}

// ---------------- CLI ----------------

function parseArgs(argv) {
  const out = { lane: '', target: '', runs: null, warmup: null, emitCsv: false, verbose: false, mode: '' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--lane' || a === '-l') out.lane = argv[++i];
    else if (a.startsWith('--lane=')) out.lane = a.slice(7);
    else if (a === '--target' || a === '-t') out.target = argv[++i];
    else if (a.startsWith('--target=')) out.target = a.slice(9);
    else if (a === '--runs') out.runs = parseInt(argv[++i], 10);
    else if (a.startsWith('--runs=')) out.runs = parseInt(a.slice(7), 10);
    else if (a === '--warmup') out.warmup = parseInt(argv[++i], 10);
    else if (a.startsWith('--warmup=')) out.warmup = parseInt(a.slice(9), 10);
    else if (a === '--emit-csv') out.emitCsv = true;
    else if (a === '--verbose' || a === '-v') out.verbose = true;
    else if (a === '--mode') out.mode = argv[++i];
    else if (a.startsWith('--mode=')) out.mode = a.slice(7);
    else if (a === '-h' || a === '--help') {
      console.error(
        'Usage: node runner.mjs --lane <cold-start|parse-speed|select-in-memory> --target <sqlite-leap-wasm|sql.js|sqlite-wasm> [--runs N] [--warmup N] [--emit-csv]',
      );
      process.exit(2);
    }
    else {
      console.error(`unknown arg: ${a}`);
      process.exit(2);
    }
  }
  if (out.mode === 'setup-only') {
    if (!out.target) { console.error('--mode=setup-only requires --target'); process.exit(2); }
    return out;
  }
  if (!out.lane || !out.target) {
    console.error('--lane and --target are required');
    process.exit(2);
  }
  // Lane defaults — match native conventions where possible.
  //   cold-start: 30×3 (matches native lane 1 exactly).
  //   parse-speed: 1×0 (single-run, matches native lane 2's methodology
  //     as documented in DASHBOARD.md "single-run (not median-of-5) given
  //     leap's 6-minute per-target runtime"). sql.js/sqlite-wasm could
  //     comfortably do more, but fairness trumps variance reduction when
  //     one target can't match the other's run budget.
  //   select-in-memory: 3×1 (compromise: leap takes ~80s, the others ~1s,
  //     3 runs gives us a credible median without a 10-minute leap loop).
  if (out.runs === null) {
    if (out.lane === 'cold-start') out.runs = 30;
    else if (out.lane === 'parse-speed') out.runs = 1;
    else /* select-in-memory */ out.runs = 3;
  }
  if (out.warmup === null) {
    if (out.lane === 'cold-start') out.warmup = 3;
    else if (out.lane === 'parse-speed') out.warmup = 0;
    else out.warmup = 1;
  }
  return out;
}

async function main() {
  const a = parseArgs(process.argv);
  if (a.mode === 'setup-only') {
    await setupOnly(a.target);
    return;
  }
  let result;
  switch (a.lane) {
    case 'cold-start':        result = await laneColdStart(a.target, a.runs, a.warmup); break;
    case 'parse-speed':       result = await laneParseSpeed(a.target, a.runs, a.warmup); break;
    case 'select-in-memory':  result = await laneSelect(a.target, a.runs, a.warmup); break;
    default:
      console.error(`unknown lane: ${a.lane}`);
      process.exit(2);
  }

  const ts = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  // Lane names in CSV get a `wasm-` prefix to disambiguate from native lanes
  // on the same chart. The target name stays as-is so the "sqlite-leap-wasm"
  // row pairs up readably with "sqlite-leap-c" / "sqlite-leap-rust".
  const csvLane = `wasm-${a.lane}`;
  const valueStr = typeof result.value === 'number' && !Number.isInteger(result.value)
    ? result.value.toFixed(9)
    : String(result.value);

  if (a.emitCsv) {
    // Exactly 5 columns, no header — matches emit_csv() in _lib.sh.
    console.log(`${csvLane},${a.target},${valueStr},${result.units},${ts}`);
  } else {
    console.log(`lane=${csvLane} target=${a.target} value=${valueStr} units=${result.units} at=${ts}`);
    if (a.verbose) console.log('extra:', JSON.stringify(result.extra, null, 2));
  }
}

main().catch((e) => {
  console.error('runner error:', e && e.stack ? e.stack : e);
  process.exit(1);
});
