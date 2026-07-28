# AoE2:DE Replay Analysis Workspace

Parses `.aoe2record` replays (Feral macOS port, under
`~/Library/Application Support/Feral Interactive/.../Age of Empires 2 DE/<steamid>/savegame/`)
and produces coaching after-action reports.

The parser is our **hard fork** of mgz: [CliveUnger/aoc-mgz](https://github.com/CliveUnger/aoc-mgz)
(canonical as of 2026-07-27; upstream happyleavesaoc/aoc-mgz is kept only as a
reference remote). The fork's `master` carries save_version 68 support and the
modernized tooling (uv/pyproject, ruff, pytest).

## Setup
Dependencies are declared in `pyproject.toml`; `mgz` resolves to an **editable
clone** of the fork at `./aoc-mgz` (gitignored — it's its own repo):
```bash
git clone git@github.com:CliveUnger/aoc-mgz.git
uv sync        # creates .venv/ with editable mgz + the `aoe2` CLI
```

## Usage — the `aoe2` CLI
One front door (`.venv/bin/aoe2`, or `uv run aoe2`). The word `latest` in place
of a replay path means "the newest replay in the savegame dir"
(`AOE2_SAVEGAME_DIR` overrides the default):
```bash
aoe2 latest   [N]                   # print newest replay path(s)
aoe2 analyze  <replay|latest>             # human-readable game summary
aoe2 parse    <replay|latest>             # JSON header dump
aoe2 debrief  <replay|latest> [--me NAME] # full analysis JSON (data layer for reports)
aoe2 extract  <replay|latest> <out.json>  # superset extractor (spend, trails, fights)
aoe2 ledger   <replays...>                # per-villager task/idle ledger
aoe2 audit    <replay|latest> [--me NAME] # granular slip-up ledger (idles, cancels,
                                          #   stalls, rally/market audit, checklist)
aoe2 campaign out.html <replays...>       # N-game squad report
```
Each subcommand runs the matching module (`analyze.py`, `audit.py`, …), which
all remain directly runnable with `python <tool>.py` as before. Shared helpers
(`load_match`, `sec`, `mmss`, `hms`) live in `replaylib.py`.
See `AGENTS.md` for the full handoff: model API cheatsheet, metric gotchas
(read these before quoting any number), and session-by-session findings.

## Performance: `replaylib.load_match`
All tools load replays through `replaylib.py`, which does two things
(~5–10x wall-clock vs calling `mgz.model.parse_match` directly):

1. **Pauses the cyclic GC during the parse.** `parse_match` allocates ~1M
   objects that all survive; Python's threshold GC rescans that growing heap
   over and over (measured 3.5s → 0.6s on a 99-min replay). A `gc.collect()`
   afterwards costs ~0.04s, so nothing is lost.
2. **Caches the parsed `Match` as a pickle** in `data/match_cache/`
   (gitignored, ~2–20 MB/replay). Keyed on replay mtime+size **and the
   `aoc-mgz` checkout commit**, so editing the parser or the replay file
   auto-invalidates; corrupt/stale entries fall back to a fresh parse.
   Delete the directory freely to reclaim space.

New scripts should use `from replaylib import load_match` instead of
`parse_match`. The only difference from a raw parse: `m.hash` is the sha1
hexdigest string (the declared type) instead of a live hashlib object.

## History: the save_version 68 fix (mid-2026 DE patch)
Our replays are DE **save_version 68.0** (build v101.103.48987/48086, `VER 9.4`),
which no released mgz supported (PyPI 1.8.51 reaches ~66.3/67). We
reverse-engineered the delta — one trailing empty `de_string` per player plus
8 trailing bytes at the end of the `de` header block, gated `save_version >= 67.5`
— and patched both parser paths (`mgz/header/de.py` construct and
`mgz/fast/header.py` fast). The fix is merged on the fork's `master` with a
v68 test replay; `git -C aoc-mgz log` has the details. The full construct
`FullSummary` still fails later in `initial` object parsing for v68 (unused);
`parse_match` (fast path) fully works: header + body + actions + timeseries.
