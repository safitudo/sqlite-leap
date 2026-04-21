// Minimal WASM harness for sqlite-leap.
//
// Loads sqlite_leap.wasm, drives the C-ABI, and prints results. This is a
// browser-side equivalent of sqllogictest lite — enough to demo that the
// engine runs in a browser. Deliberately zero dependencies, zero bundler.
//
// Wire protocol:
//   sqlite_leap_open(0) -> handle (u32)
//   sqlite_leap_exec(handle, sql_ptr, sql_len) -> packed u64
//     high 32 bits: result buffer ptr (UTF-8 JSON)
//     low  32 bits: result buffer length
//   sqlite_leap_free(ptr, len)
//   sqlite_leap_close(handle)
//
// The JSON shape mirrors the native cross-build harness exactly (by design —
// that's the whole point of the FFI's success_json / error_json writers):
//   success: {"rows":[[...], [...]]}
//   error:   {"error":{"name":"...","fields":{...}}}

const WASM_URL = new URL('../../../src-wasm/sqlite_leap.wasm', import.meta.url);

const status = document.getElementById('status');
const out = document.getElementById('out');
const runBtn = document.getElementById('run');
const smokeBtn = document.getElementById('smoke');
const sqlBox = document.getElementById('sql');

function log(kind, text) {
  out.className = kind;
  out.textContent = text;
}

// Read a UTF-8 string out of wasm linear memory given (ptr, len).
function readUtf8(memory, ptr, len) {
  if (len === 0) return '';
  const bytes = new Uint8Array(memory.buffer, ptr, len);
  return new TextDecoder('utf-8').decode(bytes);
}

// Write a UTF-8 string into wasm memory using sqlite_leap_alloc. Returns
// {ptr, len}; caller is responsible for freeing with sqlite_leap_free.
function writeUtf8(exports, memory, str) {
  const bytes = new TextEncoder().encode(str);
  const len = bytes.length;
  const ptr = exports.sqlite_leap_alloc(len);
  if (ptr === 0 && len > 0) {
    throw new Error('sqlite_leap_alloc returned 0 (OOM?)');
  }
  new Uint8Array(memory.buffer, ptr, len).set(bytes);
  return { ptr, len };
}

// Execute SQL and return the parsed JSON result. Packs/unpacks the u64 return
// via BigInt since JS numbers can't represent all 64-bit values losslessly.
function exec(exports, memory, handle, sql) {
  const { ptr: sqlPtr, len: sqlLen } = writeUtf8(exports, memory, sql);
  try {
    const packed = exports.sqlite_leap_exec(handle, sqlPtr, sqlLen);
    // packed is a BigInt (WebAssembly i64 -> BigInt on the JS side).
    const resultPtr = Number(packed >> 32n);
    const resultLen = Number(packed & 0xffffffffn);
    try {
      const json = readUtf8(memory, resultPtr, resultLen);
      return JSON.parse(json);
    } finally {
      exports.sqlite_leap_free(resultPtr, resultLen);
    }
  } finally {
    exports.sqlite_leap_free(sqlPtr, sqlLen);
  }
}

async function main() {
  let exports, memory, handle;
  try {
    status.textContent = 'fetching ' + WASM_URL.pathname + ' \u2026';
    // instantiateStreaming requires application/wasm MIME; python's
    // http.server sends it correctly on recent versions. Fall back to
    // ArrayBuffer form if the browser rejects the MIME.
    let wasmModule;
    try {
      wasmModule = await WebAssembly.instantiateStreaming(fetch(WASM_URL), {});
    } catch (_e) {
      const buf = await (await fetch(WASM_URL)).arrayBuffer();
      wasmModule = await WebAssembly.instantiate(buf, {});
    }
    exports = wasmModule.instance.exports;
    memory = exports.memory;

    const version = exports.sqlite_leap_version();
    const major = (version >>> 24) & 0xff;
    const minor = (version >>> 16) & 0xff;
    const patch = (version >>> 8) & 0xff;
    status.textContent = `loaded. engine version ${major}.${minor.toString(16)}.${patch} (0x${version.toString(16).padStart(8, '0')})`;

    handle = exports.sqlite_leap_open(0);
    if (handle === 0) throw new Error('sqlite_leap_open returned 0');

    runBtn.disabled = false;
    smokeBtn.disabled = false;

    runBtn.addEventListener('click', () => {
      try {
        const r = exec(exports, memory, handle, sqlBox.value);
        log(r.error ? 'err' : 'ok', JSON.stringify(r, null, 2));
      } catch (e) {
        log('err', String(e));
      }
    });

    smokeBtn.addEventListener('click', () => {
      const suite = [
        'SELECT 1;',
        "SELECT 'hello';",
        'SELECT 1 + 2 * 3;',
        'CREATE TABLE t (a INTEGER, b TEXT);',
        "INSERT INTO t VALUES (1, 'one'), (2, 'two'), (3, 'three');",
        'SELECT COUNT(*) FROM t;',
        'SELECT a, b FROM t ORDER BY a DESC;',
      ];
      const lines = [];
      for (const sql of suite) {
        try {
          const r = exec(exports, memory, handle, sql);
          lines.push(`>> ${sql}\n${JSON.stringify(r)}`);
        } catch (e) {
          lines.push(`>> ${sql}\nJS ERROR: ${e}`);
          break;
        }
      }
      log('ok', lines.join('\n\n'));
    });

    // Auto-run the default SELECT 1; so page load is self-demonstrating.
    runBtn.click();
  } catch (e) {
    status.textContent = 'failed to load wasm: ' + e;
    status.style.color = '#f99';
    log('err', String(e) + '\n\nIs src-wasm/sqlite_leap.wasm present? Run generators/wasm/build.sh first.');
    throw e;
  }
}

main();
