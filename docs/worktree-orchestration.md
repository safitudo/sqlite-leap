# Worktree-based agent orchestration

**Status:** operational pattern, validated 2026-04-26 after the JSON1/PRAGMA/storage_wal collision wave.

## Why worktrees

`src-*` trees are gitignored (LEAP convention — generated code is not tracked). Multiple agents working in the same shared filesystem on `src-rust` (or any `src-<lang>`) have three failure modes:

1. **Cargo build cache races.** Two agents running `cargo build` simultaneously can corrupt `target/` or produce inconsistent compilations.
2. **File-level interference.** Agent A writes `src-rust/foo.rs`; agent B does `cargo clean` or moves `src-rust/foo.rs` and breaks A's build mid-flight.
3. **Silent loss of generated files.** Because `src-*` is gitignored, files can vanish (cleaned, overwritten) without git noticing. Confirmed lost: `src-rust/storage_wal.rs` (329 lines, claimed by commit dd0835a, gone from working tree).

## The pattern

For any agent that touches `src-<target>/`:

```
Agent({
  isolation: "worktree",
  prompt: "...",
  ...
})
```

`isolation: "worktree"` instructs the Agent tool to create an isolated git worktree. Each agent gets:

- Its own copy of the working directory (under `.claude/worktrees/<name>/`)
- Its own `target/` (cargo build cache)
- Its own `src-*/` initial state (seeded by a copy hook — see below)
- A new branch based on HEAD

The agent emits into its own tree. When done, its result either lands cleanly back in main (via merge or copy-back) or is rejected and discarded.

## Seeding gitignored src-* into a worktree

Default `git worktree add` doesn't copy gitignored files. We need a seed hook that copies `src-rust/`, `src-c/`, etc. into the worktree at creation time.

Two options:

### Option 1 — global pre-agent hook

Use `.claude/settings.json` hook for `WorktreeCreate`:

```json
{
  "hooks": {
    "WorktreeCreate": "rsync -a --exclude target/ src-rust/ src-c/ src-zig/ src-go/ src-python/ {{worktree}}/"
  }
}
```

(Verify exact hook event name and template syntax.)

### Option 2 — explicit prompt instruction

Each prompt that needs src-rust seeded begins with:

```
First, copy current src-rust state into your worktree:
rsync -a /Users/stanislav/code/sqlite-leap/src-rust/ ./src-rust/
(or equivalent for src-c, src-zig, etc.)
```

Less elegant, more explicit, no global config required. Use this until the hook approach is validated.

## Merge-back — staged output (corrected 2026-04-26)

**Critical bug in v1 of this doc:** the original merge-back recipe assumed I could rsync from `.claude/worktrees/<name>/src-rust/` after the agent finished. **It can't.** The Agent tool auto-cleans the worktree when git sees no committed changes, and `src-*` is gitignored — so from git's perspective the agent did nothing, and the entire worktree (including 599 lines of regenerated WAL writer) gets deleted before the main thread can copy back.

**The fix: agents stage their output to `.claude/agent-output/<task-name>/` in the main repo (absolute path), which survives worktree cleanup.**

Staging is non-gitignored (`.claude/` is committed metadata) but `.claude/agent-output/` should be added to `.gitignore` so review artifacts aren't committed.

### Agent-side recipe (bake into every src-touching prompt)

```
# 1. Seed gitignored sources into your worktree
rsync -a /Users/stanislav/code/sqlite-leap/src-rust/ ./src-rust/

# 2. ... do work, build, validate inside worktree ...

# 3. Stage results to main repo's agent-output dir
mkdir -p /Users/stanislav/code/sqlite-leap/.claude/agent-output/<task-name>/
rsync -a --delete ./src-rust/ /Users/stanislav/code/sqlite-leap/.claude/agent-output/<task-name>/src-rust/
# (or only the changed files — list them in the prompt)

# 4. Report task-name + file list to coordinator
```

### Coordinator-side merge-back (main thread)

For each finished agent, in dispatch-determined order:

1. Inspect `.claude/agent-output/<task-name>/src-rust/` — diff against current `src-rust/`
2. Validate the staged delta is what the agent claimed (file count, line counts, public API)
3. `rsync -a .claude/agent-output/<task-name>/src-rust/ src-rust/` — only the files that agent owned this wave
4. Build: `cd src-rust && cargo build --release --example lib_bench --example slt_runner`
5. If clean: continue to next agent. If broken: revert that file set, mark agent's wave as failed, do not block other agents whose merges already landed.
6. After all merges land, run a consolidated build + smoke test before committing.

### Why this changes parallelism economics

Original assumption: collisions at write-time inside src-rust → use worktrees to isolate.
Reality: with staged output, writes never collide at all (each agent writes to a unique `agent-output/<task>/` path). Collisions only emerge at *merge-back time* — a serialized step the coordinator controls.

This means **agents can have overlapping file write sets safely**. Two agents both editing `src-rust/pager.rs` no longer corrupt each other's work — coordinator picks one merge to apply first, validates, then applies the second (with manual conflict resolution if needed).

Trade-off: more agents in flight increases coordinator review burden. Net: throughput up, careful-review-load up, build-corruption risk down.

## What to dispatch with worktrees vs without

**Always with worktree:**
- Agents touching `src-<target>/` (Rust/C/Zig/Go/Python emission)
- Agents that run `cargo build` / `gcc` / `zig build` / `go build` / `python -m`
- Multiple-agent fan-outs to the same target

**Without worktree (default ok):**
- Spec-only agents (`parts/`, `spec/`, `schema/` only)
- Read-only probing agents (regen-debt sweep)
- Test-suite-only agents (`tests/`)
- Bench-harness-only agents (`bench/`)
- Documentation agents (`docs/`)

These touch only git-tracked files; collisions are visible (git status shows them) and resolvable via normal git merge.

## Ordering still matters

Worktrees prevent filesystem races but don't prevent semantic conflicts. If two agents both want to add a variant to `parts/parser/parts/expr/shapes.json` (a tracked file), both worktrees succeed but the merge has a conflict.

Discipline: **for each tracked file, only one agent edits it per wave.** Worktrees make filesystem corruption impossible; coordination prevents merge headaches.

## Dispatch checklist

Before launching N parallel agents:

1. List the file domains each touches (parts/, src-rust/, src-c/, tests/, bench/, docs/).
2. Find collisions:
   - Two agents touching the same `src-<lang>/` → both need worktrees.
   - Two agents touching the same tracked file → serialize one, or split scope.
3. For each src-touching agent, set `isolation: "worktree"` and include src-* seed instruction in prompt.
4. After completion: copy-back per-agent, then validate consolidated build.

## Lessons from 2026-04-26 wave

1. **JSON1 finished cleanly** before sibling agents could corrupt it — got lucky.
2. **storage_wal.rs vanished** between commit and "now" — gitignored file lost silently. Worktree wouldn't have prevented this in retrospect, but the LEAP discipline is: regen target code from spec rather than hand-edit and rely on the tree.
3. **Authorizer agent escaped correctly** when it saw "VdbeState collision risk" — the escape hatch worked.
4. **Triggers spec was a parts-only agent**, completed safely without worktree (it didn't touch src-*).
5. **PRAGMA agent was about to wire into slt_runner** when killed — would have collided with JSON1's expr_compile changes. Worktrees would have isolated this.

## Validation

Test the pattern with one agent before fanning out:

```python
# Test: dispatch one src-rust agent in worktree, verify clean merge-back
Agent({
  description: "Worktree test",
  isolation: "worktree",
  prompt: "Add a single noop function to src-rust/lib.rs. Build clean. Report worktree path."
})

# Then: copy back, validate, document
```

If the test passes, fan out. If it fails, fix the seed hook before launching real work.
