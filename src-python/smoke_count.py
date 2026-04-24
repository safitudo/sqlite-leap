"""Cross-target behavioral smoke test — Python twin of
src-rust/examples/smoke_count.rs.

Program: reset a CountStar accumulator, step it 3 times, finalize into
reg[0], emit reg[0] as a result row, halt. Sink captures the emitted
Integer and prints it. Expected output: `OK: python smoke CountStar x3 = 3`.

Run with src-python/ on sys.path, e.g.:
    PYTHONPATH=src-python python3 src-python/smoke_count.py
"""
from __future__ import annotations

import sys

from leap_sqlite.core import Register, ValueInteger
from leap_sqlite.storage import Database
from leap_sqlite.vdbe import (
    AggFuncKindCountStar,
    Program,
    VdbeState,
    execute_program,
    OpcodeCoreCase,
    OpcodeAggCase,
)
from leap_sqlite.vdbe.opcodes_agg import (
    OpcodeAggReset,
    OpcodeAggStep,
    OpcodeAggFinal,
)
from leap_sqlite.vdbe.opcodes_core import (
    OpcodeCoreHalt,
    OpcodeCoreResultRow,
)

_captured: int | None = None


def sink(state: VdbeState, start: Register, count: int) -> None:
    global _captured
    v = state.get_register(start)
    if isinstance(v, ValueInteger):
        _captured = v.v


def main() -> int:
    cs = AggFuncKindCountStar()
    r0 = Register(0)
    opcodes = (
        OpcodeAggCase(OpcodeAggReset(acc_slot=0, kind=cs)),
        OpcodeAggCase(OpcodeAggStep(acc_slot=0, kind=cs, arg_reg=r0, separator_reg=None)),
        OpcodeAggCase(OpcodeAggStep(acc_slot=0, kind=cs, arg_reg=r0, separator_reg=None)),
        OpcodeAggCase(OpcodeAggStep(acc_slot=0, kind=cs, arg_reg=r0, separator_reg=None)),
        OpcodeAggCase(OpcodeAggFinal(acc_slot=0, kind=cs, dest_reg=r0)),
        OpcodeCoreCase(OpcodeCoreResultRow(start_reg=r0, count=1)),
        OpcodeCoreCase(OpcodeCoreHalt()),
    )
    program = Program(
        opcodes=opcodes,
        num_registers=1,
        num_cursors=0,
        num_aggregates=1,
        num_windows=0,
        row_sink=sink,
    )
    state = VdbeState(
        num_registers=program.num_registers,
        num_cursors=program.num_cursors,
        num_aggregates=program.num_aggregates,
        num_windows=program.num_windows,
        db=Database(),
    )
    halt = execute_program(program, state)
    print(f"halt={halt!r} captured={_captured!r}")
    assert _captured == 3, f"expected 3, got {_captured!r}"
    print("OK: python smoke CountStar x3 = 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
