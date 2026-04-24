// Cross-target behavioral smoke test — Go twin of
// src-rust/examples/smoke_count.rs and src-python/smoke_count.py.
//
// Program: reset a CountStar accumulator, step it 3 times, finalize
// into reg[0], emit reg[0] as a result row, halt. Sink captures the
// emitted Integer. Expected: captured=3.
package main

import (
	"fmt"
	"os"

	"github.com/safitudo/leap-sqlite/core"
	"github.com/safitudo/leap-sqlite/storage"
	"github.com/safitudo/leap-sqlite/vdbe"
	"github.com/safitudo/leap-sqlite/vdbe/exec"
	"github.com/safitudo/leap-sqlite/vdbe/opcodes_agg"
	"github.com/safitudo/leap-sqlite/vdbe/opcodes_core"
)

var captured int64 = -1
var capturedOk = false

func sink(state *vdbe.VdbeState, start core.Register, count uint32) {
	v := state.GetRegister(start)
	if iv, ok := v.(core.ValueInteger); ok {
		captured = iv.V
		capturedOk = true
	}
}

func main() {
	r0 := core.Register(0)
	cs := vdbe.AggFuncKindCountStar
	ops := []exec.Opcode{
		exec.OpcodeAgg{Op: opcodes_agg.OpcodeAggReset{AccSlot: 0, Kind: cs}},
		exec.OpcodeAgg{Op: opcodes_agg.OpcodeAggStep{AccSlot: 0, Kind: cs, ArgReg: r0}},
		exec.OpcodeAgg{Op: opcodes_agg.OpcodeAggStep{AccSlot: 0, Kind: cs, ArgReg: r0}},
		exec.OpcodeAgg{Op: opcodes_agg.OpcodeAggStep{AccSlot: 0, Kind: cs, ArgReg: r0}},
		exec.OpcodeAgg{Op: opcodes_agg.OpcodeAggFinal{AccSlot: 0, Kind: cs, DestReg: r0}},
		exec.OpcodeCore{Op: opcodes_core.OpcodeCoreResultRow{StartReg: r0, Count: 1}},
		exec.OpcodeCore{Op: opcodes_core.OpcodeCoreHalt{}},
	}
	program := &exec.Program{
		Opcodes:       ops,
		NumRegisters:  1,
		NumCursors:    0,
		NumAggregates: 1,
		NumWindows:    0,
		RowSink:       sink,
	}
	db := &storage.Database{}
	state := vdbe.NewVdbeState(
		program.NumRegisters,
		program.NumCursors,
		program.NumAggregates,
		program.NumWindows,
		db,
	)
	halt := exec.ExecuteProgram(program, state)
	fmt.Printf("halt=%#v captured=%d (ok=%t)\n", halt, captured, capturedOk)
	if !capturedOk || captured != 3 {
		fmt.Println("FAIL: expected Integer(3)")
		os.Exit(1)
	}
	fmt.Println("OK: go smoke CountStar x3 = 3")
}
