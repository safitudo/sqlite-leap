//! WASM wrapper for sqlite-leap.
//!
//! Minimal C-ABI surface compiled to wasm32-unknown-unknown as a cdylib. JS
//! callers use `WebAssembly.instantiate` and the exported memory directly —
//! no `wasm-bindgen`, no `wasm-pack`, no glue toolchain. Mirrors the
//! embedding pattern of `sql.js` / `sqlite-wasm`.
//!
//! The engine crate `leap_sqlite` (in `../../src-rust/`) exposes its
//! components directly (parser, compiler, vdbe, storage, core). This wrapper
//! composes the SELECT-expression path — tokenize → parse → compile →
//! execute — and serialises the resulting `Value` to a UTF-8 buffer the
//! caller can read out of linear memory.
//!
//! ## Exports
//!
//! | Symbol                              | Returns        | Notes |
//! |-------------------------------------|----------------|-------|
//! | `sqlite_leap_alloc(len: u32)`       | ptr (u32)      | Allocate `len` bytes; 0 on failure. |
//! | `sqlite_leap_free(ptr: u32, len: u32)` | void        | `len` MUST match the original alloc. |
//! | `sqlite_leap_eval(ptr: u32, len: u32)` | packed u64  | Evaluate `SELECT <expr>` (or bare expr). High 32 = result ptr, low 32 = result len. UTF-8. Caller frees. |
//! | `sqlite_leap_version()`             | version (u32) | Packed `major<<24 \| minor<<16 \| patch<<8 \| build`. |
//!
//! ## Result format
//!
//! `sqlite_leap_eval` returns a single canonical-text rendering of the
//! evaluated expression. On error it returns `error:<short message>`. This is
//! deliberately minimal — the WASM target is a feasibility proof for
//! CLAUDE.md's "third build" promise, not a full library API. JSON shaping is
//! tracked as a follow-up gap (see README "Gaps").
//!
//! DO NOT CHEAT: everything here is composed from `leap_sqlite`'s public
//! Rust API. No mainline SQLite, Turso, sql.js, sqlite-wasm, or rusqlite code
//! is borrowed.

use leap_sqlite::compiler::expr_compile::compile_expr;
use leap_sqlite::compiler::Program;
use leap_sqlite::core::{Register, Value};
use leap_sqlite::parser::expr::parse_expr;
use leap_sqlite::parser::tokenizer::tokenize;
use leap_sqlite::storage::database_new;
use leap_sqlite::vdbe::opcodes_core::OpcodeCore;
use leap_sqlite::vdbe::{execute_program, Opcode, VdbeState};

// ---------- Linear-memory allocation -----------------------------------
//
// We hand JS a stable allocator: `sqlite_leap_alloc` reserves `len` bytes,
// `sqlite_leap_free` releases them. Implementation: lean on Rust's `Vec<u8>`
// and `mem::forget` so the buffer is owned by the caller until they hand it
// back. On free we reconstruct the `Vec` from (ptr, len, len) and let it
// drop.

/// Allocate `len` bytes in linear memory. Returns the pointer, or 0 on
/// failure (including `len == 0`).
#[no_mangle]
pub extern "C" fn sqlite_leap_alloc(len: u32) -> u32 {
    if len == 0 {
        return 0;
    }
    let mut buf: Vec<u8> = Vec::with_capacity(len as usize);
    // SAFETY: capacity == len, and u8 has no Drop; setting len is safe.
    unsafe { buf.set_len(len as usize) };
    let ptr = buf.as_mut_ptr() as u32;
    core::mem::forget(buf);
    ptr
}

/// Free a buffer previously returned by `sqlite_leap_alloc` (or the upper 32
/// bits of `sqlite_leap_eval`'s packed return). `len` MUST match the
/// original allocation.
#[no_mangle]
pub extern "C" fn sqlite_leap_free(ptr: u32, len: u32) {
    if ptr == 0 || len == 0 {
        return;
    }
    // SAFETY: the (ptr, len) was produced by `sqlite_leap_alloc` (or one of
    // the result-returning paths below) which forgot a Vec<u8> with
    // capacity == len. Reconstructing the Vec lets it drop normally.
    unsafe {
        let _ = Vec::from_raw_parts(ptr as *mut u8, len as usize, len as usize);
    }
}

/// Engine version. Packed `major<<24 | minor<<16 | patch<<8 | build`.
/// Hard-coded to 0.1.0+0 — there is no version constant in the engine yet.
#[no_mangle]
pub extern "C" fn sqlite_leap_version() -> u32 {
    (0u32 << 24) | (1u32 << 16) | (0u32 << 8)
}

// ---------- The eval path ----------------------------------------------
//
// `sqlite_leap_eval(ptr, len)` reads `len` bytes of UTF-8 starting at `ptr`,
// treats them as a SQL expression source, and returns the evaluated value's
// canonical text rendering in a freshly-allocated buffer.
//
// The string `SELECT <expr>` is also accepted: we strip a leading
// case-insensitive `SELECT ` prefix so callers can pass full statements for
// the trivial constant-expression smoke. No FROM clause is supported in this
// wrapper — that path requires the storage / cursor machinery and is the
// next layer of WASM scope (see README "Gaps").

fn pack(ptr: u32, len: u32) -> u64 {
    ((ptr as u64) << 32) | (len as u64)
}

fn alloc_and_copy(s: &str) -> u64 {
    let bytes = s.as_bytes();
    let len = bytes.len() as u32;
    if len == 0 {
        return 0;
    }
    let mut buf: Vec<u8> = Vec::with_capacity(len as usize);
    buf.extend_from_slice(bytes);
    let ptr = buf.as_mut_ptr() as u32;
    debug_assert_eq!(buf.capacity(), buf.len());
    core::mem::forget(buf);
    pack(ptr, len)
}

fn fmt_value(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Integer { v } => format!("{}", v),
        Value::Real { v } => format!("{}", v),
        Value::Text { v } => v.clone(),
        Value::Blob { v } => format!("blob[{}]", v.len()),
    }
}

fn strip_select_prefix(src: &str) -> &str {
    let trimmed = src.trim_start();
    // Case-insensitive `SELECT` followed by whitespace.
    if trimmed.len() >= 7 {
        let head = &trimmed.as_bytes()[..6];
        let after = trimmed.as_bytes()[6];
        if head.eq_ignore_ascii_case(b"SELECT") && (after == b' ' || after == b'\t') {
            return trimmed[7..].trim_start_matches(';').trim();
        }
    }
    trimmed.trim_end_matches(';').trim()
}

fn sink(_state: &VdbeState<'_>, _start: Register, _count: u32) {}

fn eval_expr_src(src: &str) -> Result<Value, String> {
    let toks = tokenize(src).map_err(|e| format!("lex: {}", e.message))?;
    let parsed = parse_expr(&toks, 0).map_err(|e| format!("parse: {}", e.message))?;
    let compiled = compile_expr(&parsed.expr, Register(0))
        .map_err(|e| format!("compile: {}", e.message))?;

    let result_reg = compiled.result_reg;
    let num_registers = compiled.next_reg.0;

    let mut opcodes: Vec<Opcode<'static>> = compiled.code;
    opcodes.push(Opcode::Core { op: OpcodeCore::Halt });
    let opcode_count = opcodes.len() as u32;

    let program = Program {
        num_registers,
        num_cursors: 0,
        num_aggregates: 0,
        num_windows: 0,
        opcode_count,
        opcodes,
        row_sink: sink,
    };

    let db = database_new();
    let mut state = VdbeState::new(
        program.num_registers,
        program.num_cursors,
        program.num_aggregates,
        program.num_windows,
        &db,
    );
    let _halt = execute_program(&program, &mut state);
    Ok(state.get_register(result_reg).clone())
}

/// Evaluate a SQL constant expression (or `SELECT <expr>`). Returns
/// packed `(ptr<<32) | len`. The buffer holds canonical UTF-8 text. The
/// caller MUST `sqlite_leap_free(ptr, len)` when done.
///
/// On error the buffer contains `error:<short message>` — there is no
/// out-of-band signal in this minimal surface.
#[no_mangle]
pub extern "C" fn sqlite_leap_eval(ptr: u32, len: u32) -> u64 {
    if ptr == 0 || len == 0 {
        return alloc_and_copy("error:empty input");
    }
    // SAFETY: the caller asserts (ptr, len) is a valid UTF-8 buffer in our
    // linear memory. We borrow it only for the duration of this call; we do
    // not free it (the caller owns the input buffer separately).
    let src_bytes = unsafe { core::slice::from_raw_parts(ptr as *const u8, len as usize) };
    let src = match core::str::from_utf8(src_bytes) {
        Ok(s) => s,
        Err(_) => return alloc_and_copy("error:input not utf-8"),
    };
    let stripped = strip_select_prefix(src);
    match eval_expr_src(stripped) {
        Ok(v) => alloc_and_copy(&fmt_value(&v)),
        Err(msg) => alloc_and_copy(&format!("error:{}", msg)),
    }
}
