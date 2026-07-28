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

## Tool reference

Rough division of labor: **analyze** identifies a game, **audit** critiques
your play in it, **debrief/extract** dump machine-readable data for reports
and ad-hoc analysis, **ledger** zooms into villager management, **campaign**
renders a multi-game HTML report. All numbers inherit the caveats at the
bottom of this section.

### `aoe2 analyze` — 10-second game summary
Human-readable one-screener: map/duration/type/save version, players with
civ + winner + eAPM + teams, age-up **clicks** per human, POV-deduped action
counts, chat count. Use it to identify which replay is which and to sanity-
check that a replay parses at all. AI players have empty names (shown by
civ); AI eAPM is not comparable to human eAPM (it's dominated by micro
commands humans never emit).

### `aoe2 parse` — raw JSON header dump
Everything the header/summary layer knows (players, teams, civs, map,
version fields) as one large JSON (~1.4 MB). For debugging parser/format
issues and feeding external scripts — not for reading.

### `aoe2 debrief` — one-player analysis JSON (the report data layer)
POV-focused (`--me`, default Olive) JSON: per player `ages` (last click) and
`ages_entered` (click + research time — a lower bound; TC queue wait can add
up to ~75s), cumulative production `prod`, key `upgrades`, banked-resources +
object-count timeseries `ts`, `eapm`, `peak_obj`; plus spatial data — every
player's build footprints and *your* movement/attack trail. This is what the
after-action-report artifacts are generated from.

### `aoe2 extract` — superset extractor (feeds ledger/audit/campaign)
Everything debrief has, for **all** players, plus: every research click
(with click counts — a re-click proves the earlier one was cancelled), all
building footprints with ids, all-player MOVE/ORDER trails, market SELL/BUY,
resigns/deletes, per-minute command counts, per-resource **spending
reconstruction** (units/techs/buildings priced from `data/techtree.json` —
refresh that file after balance patches), and precomputed **fight windows**
(gross-attrition windows from object-count drops: ≤60s merge gap, 4-min cap,
endgame excluded) with per-player loss attribution. Writes one JSON;
`vill_ledger`/`audit` call it in-process.

### `aoe2 ledger` — per-villager task ledger (to Castle click +120s)
Resolves every villager right-click to an actual resource (gaia objects +
starting-unit ids work on v68) and reconstructs each villager's task
history: **birth idle** (the TC-rally-point check), stranded builder squads,
a research done-at estimate per tech, and a task census. Distinguishes death
from idleness: an idle window closed by a later command proves the villager
was alive; only "never commanded again" tails are ambiguous, and those are
classified via object-count deltas + fight overlap (LIKELY DEAD vs idle).
Caveat: villager *state* isn't in the stream — humans task via ORDER, so
mid-window deaths inside "likely idle" tails are undetectable.

### `aoe2 audit` — granular slip-up ledger (the post-game coach)
Eleven sections, one per failure mode. What each means:
1. **Ages** — your clicks→entered vs AI age *proxies* (2nd TC build, first
   Castle-age unit queued). The AI never emits RESEARCH, hence proxies.
2. **TC idle** — queue simulation (villagers + Loom + age research as serial
   jobs); idle windows ≥20s and per-age uptime%. The single best tempo stat.
3. **Military production idle** — same simulation per building type
   (k parallel servers when you have several). High idle% + rising bank =
   income was the bottleneck, not capacity.
4. **Housed-stall suspects** — spawn-sim pop vs house capacity. Deaths are
   invisible, so only the *onset* of a flag means anything.
5. **Cancels** — Unqueue clusters (each queued unit locks its cost) and
   re-clicked techs (proof of an earlier cancel).
6. **Rally points** — every GATHER_POINT, and whether the TC ever got one.
7. **Market** — build time vs first use; unused markets are unspent options.
8. **Food ledger** — food spend by category; "military ≈ N Castle Ages"
   shows what competed with the age-up fund.
9. **Input silences** — longest zero-command gaps (attention audit).
10. **Fight micro** — command count/type inside each fight window.
11. **Checklist** — walls/towers/2nd TC/first farm ≤10:00/blacksmith ≤14:00/
    ≥4 smith techs by 20:00/TC rally. The standing next-game targets.

### `aoe2 campaign` — N-game HTML squad report
Self-contained themed page from `reports/templates/campaign.html`: session
tempo trend (Castle arrivals vs target), eco/trade, aggression profile, day
totals, advice cards, per-game tabs with animated battlefield map + combat
log. Fully data-driven; `--editorial notes.json` overrides hero text, tiles,
and per-game narrative (see `reports/README.md`). Works for 1..N games and
mixed team sizes.

### Caveats that apply everywhere (details in AGENTS.md)
- Queue events are **requests, not spawns**; production counts are units
  **trained, not alive/peak** — a big count can be a big force *or* heavy
  replacement churn. Peak concurrent army is not recoverable.
- RESEARCH actions are **clicks, not completions**; the last click per tech
  wins (earlier ones were cancelled).
- The banked-resources timeseries is a **single food+wood+gold+stone sum** —
  never claim "could afford X" from it; reconstruct spending instead.
- Fight windows are **gross attrition** (villagers, army, buildings, expiring
  farms all conflated), not battles.
- The recorder duplicates ~2–6% of the recording player's own commands; all
  tools share one POV dedup. Never compare human command counts to AI ones.
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
