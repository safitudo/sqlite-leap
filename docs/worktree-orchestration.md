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

## Merge-back

When an agent finishes and we want to keep its src-* edits:

1. Agent's worktree path is at `.claude/worktrees/<name>/`
2. Copy back: `rsync -a .claude/worktrees/<name>/src-rust/ /Users/stanislav/code/sqlite-leap/src-rust/`
3. Validate: `cargo build && cargo test` in main tree
4. If clean: keep. If broken: revert via git stash + drop worktree.

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
