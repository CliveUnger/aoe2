# AoE2:DE Replay Analysis Workspace

Parses `.aoe2record` replays (Feral macOS port, under
`~/Library/Application Support/Feral Interactive/.../Age of Empires 2 DE/<steamid>/savegame/`)
and produces coaching after-action reports.

The parser is our **hard fork** of mgz: [CliveUnger/aoc-mgz](https://github.com/CliveUnger/aoc-mgz)
(canonical as of 2026-07-27; upstream happyleavesaoc/aoc-mgz is kept only as a
reference remote). The fork's `master` carries save_version 68 support and the
modernized tooling (uv/pyproject, ruff, pytest).

## Setup
mgz is an **editable clone** at `./aoc-mgz` (gitignored — it's its own repo):
```bash
git clone git@github.com:CliveUnger/aoc-mgz.git
python3 -m venv venv
source venv/bin/activate
pip install -e ./aoc-mgz        # editable: parser edits are live immediately
```

## Tools
```bash
source venv/bin/activate
python analyze.py      "<replay>"             # human-readable game summary
python parse.py        "<replay>"             # JSON header dump
python debrief.py      "<replay>" [--me NAME] # full analysis JSON (data layer for reports)
python extract_full.py "<replay>" <out.json>  # superset extractor (spend, trails, fights)
python vill_ledger.py  "<replay>"...          # per-villager task/idle ledger
python audit.py        "<replay>" [--me NAME] # granular slip-up ledger (idles, cancels,
                                              #   stalls, rally/market audit, checklist)
python reports/make_campaign.py out.html "<replays>"...   # N-game squad report
```
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
