// Per-statement parse/compile filter for leap-rust. Mirrors the
// classify+dispatch logic of lib_bench.rs but emits one line per
// statement to stdout: "OK" if all of parse + compile + execute
// succeed, "ERR" otherwise. Summary on stderr.
//
// Statements that classify outside {select,insert,create,noop} are
// treated as ERR (leap-rust does not implement them in lib_bench mode).
// PRAGMA/BEGIN/COMMIT/ROLLBACK ("noop") emit OK so they don't get
// stripped from the corpus (they're free for everyone).
// leaplint: runner

use std::env;
use std::fs;
use std::sync::atomic::{AtomicI64, AtomicUsize, Ordering};

use leap_sqlite::compiler::insert_compile::compile_insert_with_source;
use leap_sqlite::compiler::select_compile::{
    compile_select_with_db, ColumnSchema, TableSchema,
};
use leap_sqlite::compiler::Program;
use leap_sqlite::core::{HaltStatus, Register, Value};
use leap_sqlite::parser::create_table_stmt::{parse_create_table, ColumnConstraint};
use leap_sqlite::parser::insert_stmt::parse_insert;
use leap_sqlite::parser::select_stmt::parse_select;
use leap_sqlite::parser::tokenizer::tokenize;
use leap_sqlite::storage::{database_install_table_with_pk, database_new, Database};
use leap_sqlite::vdbe::{execute_program, VdbeState};

static SINK_ROWS: AtomicUsize = AtomicUsize::new(0);
static SINK_INT_XOR: AtomicI64 = AtomicI64::new(0);

fn sink(state: &VdbeState<'_>, start: Register, count: u32) {
    let Register(base) = start;
    let mut x: i64 = 0;
    for i in 0..count {
        if let Value::Integer { v } = state.get_register(Register(base + i)) {
            x ^= *v;
        }
    }
    SINK_ROWS.fetch_add(1, Ordering::Relaxed);
    SINK_INT_XOR.fetch_xor(x, Ordering::Relaxed);
}

struct TableEntry { schema: TableSchema }
struct Catalog { db: Database, tables: Vec<(String, TableEntry)> }

impl Catalog {
    fn new() -> Self { Self { db: database_new(), tables: Vec::new() } }
    fn install(&mut self, name: &str, columns: &[String], pk_col: Option<String>) {
        let column_schemas: Vec<ColumnSchema> = columns.iter().enumerate()
            .map(|(i, c)| ColumnSchema { name: c.clone(), index: i as u32 })
            .collect();
        self.tables.push((name.to_string(), TableEntry {
            schema: TableSchema { name: name.to_string(), columns: column_schemas }
        }));
        database_install_table_with_pk(
            &mut self.db, name.to_string(), columns.to_vec(),
            Vec::new(), pk_col,
        );
    }
    fn get_ci(&self, name: &str) -> Option<&TableEntry> {
        self.tables.iter().find(|(n, _)| n.eq_ignore_ascii_case(name)).map(|(_, e)| e)
    }
    fn lookup_first(&self) -> TableSchema {
        self.tables.first().map(|(_, e)| e.schema.clone())
            .unwrap_or(TableSchema { name: String::new(), columns: Vec::new() })
    }
}

fn run_create_table(cat: &mut Catalog, src: &str) -> Result<(), String> {
    let toks = tokenize(src).map_err(|e| format!("lex: {}", e.message))?;
    let parsed = parse_create_table(&toks, 0)
        .map_err(|e| format!("parse: {}", e.message))?;
    let cols: Vec<String> = parsed.stmt.columns.iter().map(|c| c.name.clone()).collect();
    let pk_col: Option<String> = parsed.stmt.columns.iter().find_map(|c| {
        let is_int = c.type_name.as_deref()
            .map(|s| s.eq_ignore_ascii_case("INTEGER")).unwrap_or(false);
        let has_pk = c.constraints.iter().any(|k| matches!(k, ColumnConstraint::PrimaryKey { .. }));
        if is_int && has_pk { Some(c.name.clone()) } else { None }
    });
    cat.install(&parsed.stmt.name, &cols, pk_col);
    Ok(())
}

fn run_insert(cat: &mut Catalog, src: &str) -> Result<(), String> {
    let toks = tokenize(src).map_err(|e| format!("lex: {}", e.message))?;
    let parsed = parse_insert(&toks, 0)
        .map_err(|e| format!("parse: {}", e.message))?;
    let entry = cat.get_ci(&parsed.stmt.table)
        .ok_or_else(|| format!("unknown table {:?}", parsed.stmt.table))?;
    let schema = entry.schema.clone();
    let ok = compile_insert_with_source(&parsed.stmt, &schema, None)
        .map_err(|e| format!("compile: {}", e.message))?;
    let opcode_count = ok.opcodes.len() as u32;
    let program = Program {
        opcodes: ok.opcodes, opcode_count,
        num_registers: ok.num_registers, num_cursors: ok.num_cursors,
        num_aggregates: 0, num_windows: 0, row_sink: sink,
    };
    let mut state = VdbeState::new(
        program.num_registers, program.num_cursors,
        program.num_aggregates, program.num_windows, &cat.db,
    );
    match execute_program(&program, &mut state) {
        HaltStatus::Ok => Ok(()),
        HaltStatus::Error { condition } => Err(format!("execute: {:?}", condition)),
    }
}

fn run_select(cat: &mut Catalog, src: &str) -> Result<(), String> {
    let toks = tokenize(src).map_err(|e| format!("lex: {}", e.message))?;
    let parsed = parse_select(&toks, 0)
        .map_err(|e| format!("parse: {}", e.message))?;
    let schema = cat.lookup_first();
    let extras: Vec<TableSchema> = Vec::new();
    let ok = compile_select_with_db(&parsed.stmt, &schema, &cat.db, &extras)
        .map_err(|e| format!("compile: {}", e.message))?;
    let opcode_count = ok.opcodes.len() as u32;
    let program = Program {
        opcodes: ok.opcodes, opcode_count,
        num_registers: ok.num_registers, num_cursors: ok.num_cursors,
        num_aggregates: ok.num_aggregates, num_windows: ok.num_windows,
        row_sink: sink,
    };
    let mut state = VdbeState::new(
        program.num_registers, program.num_cursors,
        program.num_aggregates, program.num_windows, &cat.db,
    );
    match execute_program(&program, &mut state) {
        HaltStatus::Ok => Ok(()),
        HaltStatus::Error { condition } => Err(format!("execute: {:?}", condition)),
    }
}

fn split_stmts(src: &str) -> Vec<String> {
    let mut out = Vec::with_capacity(1 << 14);
    let mut buf = String::new();
    let mut in_str = false;
    for c in src.chars() {
        if c == '\'' { in_str = !in_str; }
        if c == ';' && !in_str {
            let s = buf.trim().to_string();
            if !s.is_empty() { out.push(s); }
            buf.clear();
        } else { buf.push(c); }
    }
    let s = buf.trim().to_string();
    if !s.is_empty() { out.push(s); }
    out
}

fn classify(s: &str) -> &'static str {
    let t = s.trim_start();
    let upto = t.split_whitespace().next().unwrap_or("");
    match upto.to_ascii_uppercase().as_str() {
        "SELECT" => "select",
        "INSERT" => "insert",
        "CREATE" => "create",
        "BEGIN" | "COMMIT" | "PRAGMA" | "ROLLBACK" => "noop",
        _ => "other",
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: parse_filter <workload.sql>");
        std::process::exit(2);
    }
    let src = fs::read_to_string(&args[1]).expect("read workload");
    let stmts = split_stmts(&src);
    let mut cat = Catalog::new();
    let mut kept: u64 = 0;
    let mut dropped: u64 = 0;
    let stdout = std::io::stdout();
    let mut handle = stdout.lock();
    use std::io::Write;
    for s in &stmts {
        let kind = classify(s);
        let r: Result<(), String> = match kind {
            "select" => run_select(&mut cat, s),
            "insert" => run_insert(&mut cat, s),
            "create" => run_create_table(&mut cat, s),
            "noop"   => Ok(()),
            _        => Err("unsupported".to_string()),
        };
        if r.is_ok() {
            writeln!(handle, "OK").unwrap();
            kept += 1;
        } else {
            writeln!(handle, "ERR").unwrap();
            dropped += 1;
        }
    }
    eprintln!("kept={} dropped={} total={}", kept, dropped, stmts.len());
    let _ = SINK_ROWS.load(Ordering::Relaxed);
    let _ = SINK_INT_XOR.load(Ordering::Relaxed);
}
