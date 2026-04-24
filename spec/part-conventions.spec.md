# Part conventions — language-neutral

Universal rules about what a LEAP part's `master.md` means and what
can be derived vs what must be declared. This spec binds every part
in the `/parts/` tree. Individual parts do NOT re-inherit this file;
inclusion is implicit.

## Identity

A part is identified by its path from `/parts/`. The directory at
`/parts/vdbe/parts/opcodes-control/` is the part whose name is
`vdbe/opcodes-control`. A part must contain a `master.md`; it may
contain a sibling `shapes.json`; if it contains a `parts/`
subdirectory, it is an **inner** part composing those children.

## Front-matter — the minimum

The canonical minimum front-matter for a LEAP part is a single
field:

```yaml
---
name: vdbe/opcodes-control
---
```

`name:` MUST match the part's path in the tree. The delimiters make
the file self-identifying as a LEAP part.

## Derived fields

Everything below is derived by convention. A part only sets these
fields to OVERRIDE a default, not to declare it.

### `kind: leaf | inner`

Derived from directory shape:

- If the part's directory contains a `parts/` subdirectory → **inner**.
- Otherwise → **leaf**.

A part that wants the opposite of its directory shape (rare) may
declare `kind:` explicitly.

### `shapes: ./shapes.json`

If a `shapes.json` sibling exists, it is this part's shape file. No
declaration needed. A part without a `shapes.json` emits no types
or functions (it may still emit prose / composition glue).

### `emits: ...`

Derived per target from the name, using each target mapping's
**file-layout strategy** (see `/parts/targets/<target>/mapping.md`).
No per-leaf declaration of paths or file counts.

Name → path conversion for all targets: hyphens in `name` become
underscores in path segments. Other characters pass through.

### `inherits:` (cross-cutting specs)

The following specs are **implicitly inherited by every part** and
do not need to be listed:

- `/spec/type-system.spec.md` — neutral type vocabulary for
  `shapes.json`
- `/spec/memory-discipline.spec.md` — ownership/borrow rules
- `/spec/part-conventions.spec.md` — this file
- `/schema/shape.schema.json` — meta-schema validating `shapes.json`

Other cross-cutting specs (durability, sqllogictest-runner, etc.)
are **not** universal; parts that need them list them in their own
`inherits:` block.

### Dependencies on other parts (type references)

Cross-part type references are declared in `shapes.json` under the
`imports` map, not in `inherits:`. A part only lists another part
in `inherits:` if it inherits its SEMANTICS (rare — usually only
inner parents of a sub-part chain).

## Override blocks

When a leaf genuinely deviates from the convention, front-matter
may declare:

```yaml
---
name: storage/btree
emits:
  c:
    extra_headers: [src-c/storage/btree_internal.h]
kind: inner               # explicit override when derivation is wrong
shapes: ./custom-shapes.json
---
```

Override blocks are ADDITIVE to the mapping's default unless a field
is explicitly redeclared. The generator walks: (1) derive defaults,
(2) apply per-leaf override.

## What front-matter is NOT for

- Prose semantics — live in the body of `master.md`.
- Type definitions — live in `shapes.json`.
- Dependencies — live in `shapes.json` `imports`.
- Target-specific code — lives in generated `src-<target>/` output,
  nowhere in `parts/`.

## Regeneration contract

A generator reads:

1. Root `/master.md` (for project orchestration).
2. This file + the other universal inherits (implicit).
3. The target mapping (`/parts/targets/<target>/mapping.md`).
4. The leaf's own `master.md` + `shapes.json`.
5. Any transitive shape imports resolved via `shapes.json.imports`.

From those inputs alone, it produces the target file(s) at paths
derived by the mapping. No other config source is consulted.

## Generation scope — emission contents

A target emission contains **only**:

1. The types declared in the part's `shapes.json` (aggregates, type
   aliases, opaque handles).
2. The functions declared in the part's `shapes.json` (free
   functions) and the methods declared on its types.
3. Import/include lines, module/package headers, and whatever small
   amount of target-language boilerplate the mapping prescribes.
4. Per-opcode / per-function semantics as described in `master.md`.

A target emission MUST NOT contain:

- **Inline tests.** No `#[test]`, no `test { ... }` blocks, no
  `unittest.TestCase` subclasses, no `func Test...`, no `main()`
  test drivers, no `__main__` blocks. Tests live under `tests/` and
  are language-neutral at that layer.
- **Stub types or stub free functions** that simulate siblings /
  imports not yet emitted. Cross-part imports resolve at compile /
  link / module-load time; they are declared in `shapes.json.imports`
  and referenced by name. Never invent a placeholder.
- **Test-only constructors** (`new_for_test`, `make_test_state`,
  etc.) on opaque types. Constructors that appear in the emission
  must be declared in `shapes.json` and must be real.
- **Methods, constants, or helpers not declared in the shape.** If
  the semantics in `master.md` appear to need a helper the shape
  does not provide, STOP and report the gap. Do not invent.

Ambiguity handling: if `master.md` + `shapes.json` + the mapping
cannot be composed into a correct emission without adding something
not in the shape, the correct action is to stop and surface the
ambiguity, not to silently extend the surface area.

## Future language additions

Adding a new target language consists of exactly one act: write
`/parts/targets/<new-target>/mapping.md` declaring:

- Primitive table
- Constructor table
- Aggregate rendering rules
- Function/method rendering rules
- Naming conventions
- **File-layout strategy** (how `name` maps to paths; 1 file, 2
  files, package dir, etc.)
- Ownership + error conventions for the target

Zero changes to any existing leaf are required.

## Rationale

Convention over configuration. The leaf declares **what it is**
(a name). The mapping declares **how that target renders**. The
generator composes. Front-matter shrinks to the cases that
genuinely deviate, not the cases that follow the rules.
