// Cross-target behavioral smoke test.
//
// Program: reset a CountStar accumulator, step it 3 times, finalize
// into reg[0], emit reg[0] as a result row, halt. Sink captures the
// emitted Integer and prints it.
//
// Same logical program lives in src-python/smoke_count.py.
// If both print `3`, we have behavioral parity across Rust and Python
// for the composed VDBE.
use leap_sqlite::compiler::Program;
use leap_sqlite::core::{Register, Value};
use leap_sqlite::storage::Database;
use leap_sqlite::vdbe::opcodes_agg::OpcodeAgg;
use leap_sqlite::vdbe::opcodes_core::OpcodeCore;
use leap_sqlite::vdbe::{execute_program, AggFuncKind, Opcode, VdbeState};

static mut SINK_CAPTURED: Option<i64> = None;

fn sink(state: &VdbeState<'_>, start: Register, _count: u32) {
    if let Value::Integer { v } = state.get_register(start) {
        unsafe { SINK_CAPTURED = Some(*v) };
    }
}

fn main() {
    let db = Database;
    let opcodes = vec![
        Opcode::Agg  { op: OpcodeAgg::AggReset { acc_slot: 0, kind: AggFuncKind::CountStar } },
        Opcode::Agg  { op: OpcodeAgg::AggStep  { acc_slot: 0, kind: AggFuncKind::CountStar, arg_reg: Register(0), separator_reg: None } },
        Opcode::Agg  { op: OpcodeAgg::AggStep  { acc_slot: 0, kind: AggFuncKind::CountStar, arg_reg: Register(0), separator_reg: None } },
        Opcode::Agg  { op: OpcodeAgg::AggStep  { acc_slot: 0, kind: AggFuncKind::CountStar, arg_reg: Register(0), separator_reg: None } },
        Opcode::Agg  { op: OpcodeAgg::AggFinal { acc_slot: 0, kind: AggFuncKind::CountStar, dest_reg: Register(0) } },
        Opcode::Core { op: OpcodeCore::ResultRow { start_reg: Register(0), count: 1 } },
        Opcode::Core { op: OpcodeCore::Halt },
    ];
    let program = Program {
        num_registers: 1,
        num_cursors: 0,
        num_aggregates: 1,
        num_windows: 0,
        opcode_count: opcodes.len() as u32,
        opcodes,
        row_sink: sink,
    };
    let mut state = VdbeState::new(
        program.num_registers,
        program.num_cursors,
        program.num_aggregates,
        program.num_windows,
        &db,
    );
    let halt = execute_program(&program, &mut state);
    let captured = unsafe { SINK_CAPTURED };
    println!("halt={:?} captured={:?}", halt, captured);
    assert!(captured == Some(3), "expected Integer(3), got {:?}", captured);
    println!("OK: rust smoke CountStar×3 = 3");
}
