# sqlite-leap — methodology findings for LEAP

**Status:** living document. Last updated 2026-04-26.
**Purpose:** capture what sqlite-leap (the most ambitious LEAP project to date) taught us about the LEAP methodology itself, in a form that can be folded back into the LEAP repo (MANIFESTO.md, SPEC.md, AGENTS.md), the LEAP skill, and the repo template — so other projects benefit before sqlite-leap is done.

This is **not a sqlite-leap report.** It's a meta-document about LEAP-the-method, with sqlite-leap as the case study.

---

## TL;DR — what sqlite-leap proved

1. **Multi-language emission from one spec works at non-trivial scale.** 5 idiomatic implementations (Rust, C, Zig, Go, Python) of a SQL engine, ~50% of mainline SQLite's feature surface, ~99.9% pass on the SQLite project's own correctness corpus, in approximately one week of LEAP-paced work. Spec reaches ~50-80 leaves; behavior cross-checks across all 5 targets.

2. **The hardest single discipline is language-neutrality of the spec.** First idiom leak = hardest failure mode. Most spec gaps surface as cross-target divergence; once seen they're easy to fix; the trick is seeing them.

3. **Regen-debt accumulates silently and is never zero in practice.** Even with discipline, target-local fixes accumulate at ~50% rate (~one emission leak per leaf when probed). Continuous probing is the only defense; it must be a scheduled discipline, not ad-hoc.

4. **Universal brief (auto-generated from spec) is sufficient.** Hand-crafted prompts are a smell. When the spec is clean, `leapgen.py --part X --target Y` produces enough context that the agent emits cleanly. Intelligence belongs in the spec, not the prompt.

5. **Cross-target divergence is the strongest signal.** When 2+ targets independently invent the same workaround, the spec has a gap. When all 5 produce identical bytes from the same input, the spec is correct. This is a stronger correctness proof than any unit test.

6. **Test selection pressure shapes the engine.** sqllogictest measures SQL correctness, not durability or concurrency. We built a v1 that's strong on the first and weak on the others *because that's what got tested*. The diversity of your test surfaces is the diversity of your engine. Include perf, concurrency, fault tolerance from day 1.

---

## I. Spec discipline

### 1.1 Language-neutrality is the hardest single rule

Concrete idiom-leak categories observed and the resolution patterns:

| Idiom-leaky concept | Bad spec form | Neutral spec form |
|---|---|---|
| Optionality | "field is `Option<T>`" | "field is present or absent" + JSON Schema `nullable: true` |
| Errors | "returns `Result<T, E>`" | "raises named condition `INVALID_OPCODE`" |
| Memory ownership | "field holds `Rc<RefCell<T>>`" | "field holds a value; if shared, behavior under shared mutation is implementation-defined for v1" |
| Concurrency primitives | "use `thread_local!`" | "compile-call-scoped lookup" — each target picks idiomatic mechanism |
| Iteration | "for-each into `Vec<X>`" | "yields a sequence of X; ordering is preserved" |
| Stringly typed | "field is `String`" | "field is a UTF-8 character sequence; ownership transfers on assignment" |
| Numeric width | "u32" | "non-negative integer; representable in 32 bits" — tighten only when wire-format demands |

**Fold into LEAP SPEC.md:** add a "language-neutrality checklist" section with these patterns. The patterns are universal; the table can serve any LEAP project.

### 1.2 Tagged-union targets pay a coupling tax

Adding a single new variant to an enum-like type (e.g., `Expr::Param`) forces edits in N exhaustive-switch sites. Observed: Rust 7 sites (`match expr { ... }`), C 42 sites (`switch(LeapExprKind)` with zero `default:` arms), Go 8 sites (Go's switch is more forgiving), Zig 6 sites, Python 0 (dynamic dispatch).

**Mitigations, ordered by preference:**

1. **Parser-level desugar.** When the new construct can be lowered to existing primitives at parse time (BETWEEN → AND, NOT BETWEEN → OR, IN-list → OR-chain), do that. Avoids new variants entirely. Memory: `feedback_parser_level_desugar`.
2. **Default arm with runtime-error fallback.** Mandate in spec that every switch on a tagged-union enum has a `default:` arm that errors. Linter enforces.
3. **AST design that minimizes variant churn.** Group related constructs under a single variant with a payload kind field, when semantics permit.
4. **Accept the coupling tax as a one-time cost** when the variant is genuinely new. Document the N-site cost in master.md so future emitters know.

**Fold into LEAP:** new linter rule `enum-default-arm-required`. Document the tax in SPEC.md §"AST evolution."

### 1.3 Generation-scope discipline must be enforced by linter, not convention

Observed: agents silently invented inline `#[cfg(test)]` modules, scratch helpers, debug-print stubs, and "convenience" wrappers when the spec was ambiguous. Convention alone doesn't hold under load. Memory: `feedback_agents_auto_invent_helpers`.

The `parts/conventions.spec.md §"Generation scope"` clause + the `leaplint --check-generation-scope` mode (Phase A from 2026-04-23) was a turning point. Every fresh emission since then catches these auto-invented artifacts at lint time.

**Fold into LEAP:** ship the linter config in the LEAP repo template. Make `leaplint --check-generation-scope` a default CI gate.

### 1.4 Toolchain pinning is non-optional

Observed: Zig 0.16 silently changed `ArrayList.init`, `std.crypto.random`, `std.time.timestamp`. Generated code built clean against 0.15 but failed against 0.16. Without a pin, regen against a different toolchain version produces silent semantic drift.

**Mandatory section in every `parts/<part>/parts/<leaf>/parts/targets/<lang>/mapping.md`:**

```markdown
## Toolchain
- Compiler: <name> <version-pin>
- Stdlib API surface relied on: <list of types/functions>
- Build flags required: <list>
```

`leaplint --check-toolchain` validates pins are present and parseable. Memory: `feedback_target_toolchain_pin`.

**Fold into LEAP:** template the Toolchain section into the agent system prompt for new emissions. Linter enforces presence.

### 1.5 Release-flag mandate

C target broke once because release flags weren't pinned: `-O3 -march=native -lm` are essential. Same applies to Rust release profile, Go ldflags, Python `-O`. Spec must mandate.

**Fold into LEAP:** mapping.md template includes a "Build flags" subsection under Toolchain.

---

## II. Methodology mechanics

### 2.1 Universal brief replaces hand-crafted prompts

`leapgen.py --part X --target Y` produces:
- The relevant master.md
- Transitive imports of ancestor master.md (compose tree)
- shapes.json schema
- target-specific mapping.md
- Existing src tree paths (so the agent knows where to write)

When the spec is clean, this is enough. Hand-crafted "do this, then this" prompts add brittleness without value.

**Anti-pattern to remove from LEAP:** anywhere AGENTS.md says "write a detailed prompt" — change to "use leapgen brief, add only escape-hatch language and validation criteria."

**Fold into LEAP:** AGENTS.md gets a "Prompting fresh-leaf agents" section codifying this. The LEAP skill's example prompts reference leapgen invocations.

### 2.2 Parallel-agent collision discipline

Two agents editing the same target tree race. Three patterns observed:

1. **Disjoint target trees** — Phase 2 (5-target fan-out) emits to `src-rust/`, `src-c/`, `src-zig/`, `src-go/`, `src-python/` — no collision possible. Always parallelize this shape.
2. **Same target tree, disjoint files with hard contract** — Lane 3 v2 owned `select_compile.rs` + `storage.rs`; Lane 4 v2 owned `prepared.rs` + `lib_bench.rs`. Hard contract in prompts kept them apart.
3. **Same target, overlapping files** — must serialize. Memory: `feedback_parallel_same_target_agents`.

**Fold into LEAP:** AGENTS.md gets an "Orchestration patterns" section with these three modes. The LEAP skill prompts the orchestrator to pick a mode explicitly before spawning.

### 2.3 Brief subagents like a colleague, not with a recipe

Long, prescriptive prompts produce shallow work. Effective prompts:

- State the goal (1-2 sentences)
- Define strict scope (in / out)
- Include validation commands
- Provide an explicit escape hatch ("if you hit a structural wall, STOP and report")

The "STOP and report" hatch is critical. Without it, agents force broken solutions when the right answer is "the architecture doesn't support what you asked." Observed: C Lane 3+4 escape was correct and surfaced a useful split (Task A / Task B).

**Fold into LEAP:** AGENTS.md "Prompting" section includes the escape-hatch language as a default pattern.

### 2.4 Iterative spec-first beats coded-first

When tests fail or sibling targets diverge, the impulse is to fix the code. The discipline is: **fix the spec, then regenerate.**

Concrete examples from sqlite-leap:
- AVG int-rendering divergence (Rust→Real, C→Integer): fixed in spec, regen 5 targets, divergence gone.
- NOT precedence ambiguity: fixed in spec (`NOT_PREFIX_BP=4`), regen 4 targets, behavior aligned.
- CRLF normalization: spec pin, regen, gone.

**The cost of fixing in code instead of spec is paid every regeneration.** It's a debt that compounds.

**Fold into LEAP:** add to MANIFESTO.md as a top-level rule. Add to AGENTS.md as a step in the failure-triage flow.

---

## III. Quality controls

### 3.1 Cross-corroboration as test

When 5 targets are emitted from the same spec, they should produce identical observable behavior on the same input. When they don't, that's the strongest possible signal of a spec gap.

Three signal strengths observed:
- **5/5 byte-identical output** on file-format writes: spec is unambiguous, target-neutrality holds.
- **5/5 same record output** on sqllogictest: spec covers semantics; target-specific value-encoding differences are absent.
- **2-3/5 invent the same workaround**: spec has a gap exactly there. Memory: `feedback_cross_corroboration_signal`.

**Fold into LEAP:** ship `parts/eq-harness/` as a template part in the LEAP repo. Cross-target equivalence runner is a methodology primitive.

### 3.2 Probe regen-debt continuously

Once-and-forget regen doesn't work. Target-local fixes accumulate as:
- Inline workarounds for spec ambiguity
- Performance optimizations that didn't promote
- Bug fixes applied only to the target where the bug surfaced
- Auto-invented helpers (despite linter, some slip through)

**Probe pattern** (validated 2x on sqlite-leap):
1. Pick a leaf at random.
2. `cp -r src-<lang>/<files-from-leaf>/ /tmp/baseline/`
3. Regenerate from current spec.
4. Build + run smoke.
5. Diff `/tmp/baseline/` vs new emission.
6. Classify each diff: spec-faithful (good) | emission-leak (bad) | target-local-promotion-pending (debt).

Probe rate observed: ~50% of leaves have at least one emission leak (small sample, n=2). Plan for one probe per N emissions.

**Fold into LEAP:** template script `leap probe-leaf <part>/<leaf> <target>` in the LEAP repo. Probe results recorded in `regen-debt.log` per project.

### 3.3 Always dump full FAIL preview, never truncate

The slt_runner truncated FAIL output to 8 cells (`got=[...] expected=[]`). Memory: `feedback_truncated_fail_preview_misleads`. When the actual gap was at cell 1000, hours got spent debugging cell 5.

**Fold into LEAP:** test-runner spec template mandates full diff capture (with size limits configured per workload, not hardcoded).

### 3.4 File-level vs record-level pass rate

A test file is binary pass/fail. A test record is one assertion. If file 3 has 10,000 records and one fails, file-level pass rate is 0/1 (terrible) but record-level is 9999/10000 (excellent). Both must be reported.

**Fold into LEAP:** test-runner spec template includes both metrics by default. Memory: `feedback_file_vs_record_pass_rate`.

---

## IV. Anti-patterns observed (to add to LEAP MANIFESTO §"Anti-patterns")

1. **Auto-inventing helpers.** Agent adds `fn helper_X() { ... }` not in any spec. Linter catches; spec gets a Generation-scope rule.
2. **Fixing in code instead of spec.** Test fails, agent edits the generated file. Wasted on next regen.
3. **Hand-crafting prompts when leapgen suffices.** Indicator that spec is missing context the prompt is supplying.
4. **Skipping toolchain pin.** Looks fine until next minor version.
5. **Truncating FAIL preview.** Looks fine until the bug is at index >truncation.
6. **Single test surface.** Build the engine that passes the test you have. Add diverse test surfaces from day 1.
7. **Touching multiple targets in one agent.** Race-prone. Use disjoint orchestration.
8. **Promoting target-local fix to spec without sibling regen.** All 5 must regen, or you've added drift.
9. **Beating one workload as headline.** Cherry-picked benchmarks invite critique. Always lead with methodology, ship perf as supporting.
10. **Conflating stunt-grade with production.** Different test bars; don't promote without re-validating.

---

## V. Findings specific to "multi-language stunts"

These are the lessons most directly applicable when LEAP is asked to produce N implementations from one spec.

### 5.1 The N-target proof is the headline

Single-target LEAP is "code generation from spec" — interesting but not unique. N-target LEAP where all N pass the same correctness corpus is genuinely novel. Position the methodology around it.

### 5.2 "Stunt criterion" — speed + demonstrability

At design crossroads, privilege raw demonstrability over engineering elegance. A 5-target byte-identical demo aggregator (`bash demo_5target_stunt.sh` running 7 proofs in 94s, all green) is more persuasive than a thoughtful architecture diagram. Memory: `feedback_decision_criterion_speed_stuntability`.

**Fold into LEAP:** SPEC.md gets a "Demo-first checkpoint" subsection — every milestone must have a single command that produces a green demo.

### 5.3 Cost of a target

Adding a target to a project that has 5 already costs less than adding the second target. Why: the spec hardens with each target's friction. After Rust + C, the spec is language-neutral enough that Zig/Go/Python emit nearly clean. Stack-rank target order by:
1. Whichever has the most idiom-friction first (forces spec discipline)
2. Whichever has the cleanest tooling for testing (validates the spec early)

For sqlite-leap: Rust first (idiom-friction high, tooling clean), then C (idiom-friction maximum, forces spec discipline), then Zig/Go/Python (relatively clean).

### 5.4 Performance perception is target-dependent

Three of five targets beat mainline on Lane 4 prepared. Two of five matched mainline on Lane 3. **Same spec, different idioms, different performance characteristics.** This is a feature, not a bug — users pick the target that fits their workload.

**Fold into LEAP:** publication template includes per-target perf matrix as default presentation, not a single "the LEAP build does X" number.

---

## VI. Findings on LEAP repo / skill / prompt updates

Concrete things to change in `safitudo/leap` and the LEAP skill before the next project starts:

### 6.1 MANIFESTO.md additions

- Top-level rule: "Fix the spec, regenerate. Never fix the code."
- Anti-patterns section (per §IV above)
- "N-target as the headline" framing for multi-language projects.

### 6.2 SPEC.md additions

- Language-neutrality checklist (per §1.1 table)
- AST evolution section (default-arm rule, parser-level desugar preference)
- Toolchain pin section template
- Demo-first checkpoint requirement per milestone

### 6.3 AGENTS.md additions

- Prompting section: leapgen brief + escape hatch + validation commands as the default pattern. No long prescriptive prompts.
- Orchestration patterns: disjoint targets / hard-contract files / serialize. Pick before spawning.
- Failure-triage flow: divergence observed → spec gap suspected → fix spec → regen → verify across all targets.

### 6.4 LEAP repo template additions

- `parts/eq-harness/` as a default part for cross-target equivalence
- `leaplint --check-generation-scope` and `leaplint --check-toolchain` as default CI gates
- `leap probe-leaf` script
- `regen-debt.log` template
- Test runner spec template with both file-level + record-level metrics, full FAIL diff capture

### 6.5 LEAP skill prompt additions

- Reference to leapgen-driven brief generation (don't hand-craft)
- Default escape-hatch language for subagent prompts
- Default toolchain-pin requirement when emitting new targets
- Cross-target divergence treated as primary debugging signal, not a side note

### 6.6 New artifacts to add to LEAP

- **regen-debt.log** template — every project tracks accumulating debt explicitly
- **methodology-findings.md** template — every project keeps one of these (this doc is the prototype)
- **demo-aggregator template** — `bash demo_<N>target.sh` runs all proofs, prints green/red
- **probe-leaf script** — automated regen-debt detection per leaf

---

## VII. Open questions / unresolved tensions

These are things sqlite-leap surfaced that we haven't resolved. Other LEAP projects will hit them.

### 7.1 Spec promotion cost vs target-local lift cost

When is a target-local fix worth promoting to spec immediately, vs leaving as debt? sqlite-leap has accumulated ~25+ leaplint comments. Some are clearly target-local (Zig deinit walker pattern); some are clearly spec-worthy (predicate-pushdown rule). Many are ambiguous.

**Open:** rules of thumb for when to promote-now vs defer.

### 7.2 Concurrency model in the spec

Mainline SQLite has a complex multi-process locking protocol. Our spec describes it but the multi-process WAL emission (Phase 4c) has been deferred for two reasons: scope, and uncertainty about whether the spec genuinely captures the semantics in language-neutral form (some primitives are POSIX-specific).

**Open:** how does LEAP describe concurrency primitives without leaking POSIX/Win32 idioms?

### 7.3 ABI stability vs regen freedom

If users depend on a generated C ABI (`libsqliteleap.so`), regenerating breaks them unless the ABI is stable. ABI stability constrains spec evolution. There's tension.

**Open:** does LEAP need an "ABI freeze" concept on top of "spec freeze"?

### 7.4 Test corpus selection bias

We passed 99.9% of sqllogictest because we built to pass it. Real-world workloads may surface different gaps. The methodology is at risk of overfitting to its own correctness suite.

**Open:** how does LEAP guard against test-suite overfit? Probably by requiring multiple test surfaces (correctness + perf + concurrency + fault injection) but the discipline isn't codified.

### 7.5 When does multi-target stop adding value?

Adding the 6th, 7th, 8th target costs less per target but provides diminishing differentiation. At what point does it become noise?

**Open:** N-target sweet spot guidance in MANIFESTO.md. Probably: pick the targets your users actually want, not "as many as we can emit."

---

## Appendix A — concrete artifacts from sqlite-leap to copy

These files / patterns are usable as templates in other LEAP projects:

- `parts/conventions.spec.md §"Generation scope"` — generation-scope rule text
- `tools/leaplint.py --check-generation-scope` mode
- `tools/leaplint.py --check-toolchain` mode
- `parts/eq-harness/` — cross-target equivalence runner (per-target shims + golden corpus)
- `parts/<part>/parts/<leaf>/parts/targets/<lang>/mapping.md` Toolchain section template
- `bash demo_5target_stunt.sh` aggregator pattern
- The "5-target perf matrix" table format from `bench/results/2026-04-26-FINAL-REPORT.md`
- Subagent prompt template: goal + scope + validation + escape hatch (any of the Phase 1A/1B/2 prompts)

## Appendix B — what didn't work / dead ends

- **Hand-crafted long prompts** — produced shallower work than leapgen brief + minimal language.
- **Ad-hoc regen sweeps** — get skipped under deadline pressure. Must be scheduled, not opportunistic.
- **Single-target benchmarks as headline** — invites methodology critique. Lead with N-target proof.
- **"Beats mainline" framing** — defensive position; "matches mainline with different angle" is stronger.
- **Param-binding via LoadConst rewrite** — clever but brittle. Real `Expr::Param` opcode was 1-day work and eliminates the brittleness.

---

This doc is the methodology distillation. The sqlite-leap project itself can be considered the case study; this doc is what other LEAP projects should read first.
