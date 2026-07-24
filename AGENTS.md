# AGENTS.md — AoE2:DE replay analysis workspace

Context for any future agent picking this up (e.g. Clive resuming from a new thread).

## What this is
Tools to parse and analyze Clive's Age of Empires II: Definitive Edition replays
(`.aoe2record`) and produce coaching "after-action reports". Clive's in-game name is
**Olive**; regular teammates **studiousmonkey1** (Mongols) and **rickyflows** (Franks).
He mains **Britons**. Replays live under the Feral (macOS) port:
`~/Library/Application Support/Feral Interactive/Age Of Empires II/VFS/User/Games/Age of Empires 2 DE/76561198081802645/savegame/`

## Setup / environment
- `venv/` — Python 3.14 virtualenv (gitignored).
- `aoc-mgz/` — an **editable clone** of happyleavesaoc/aoc-mgz (gitignored), on branch
  **`support-save-version-68`**. Installed with `pip install -e ./aoc-mgz`.
- Activate with `source venv/bin/activate` before running anything.

### ⚠️ The save_version 68 patch (critical)
Clive's replays are DE **save_version 68.0** (build 101.103.48987/48086, `VER 9.4`), which
**no released mgz supports** (PyPI 1.8.51 == upstream HEAD only reach ~66.3/67; open PRs
#139/#142 stop at 67). We reverse-engineered the delta and patched it. v68 adds exactly:
1. one trailing (empty) `de_string` per player, and
2. 8 trailing bytes at the end of the `de` header block (before the `ai` section).
Patched in **both** parser paths — `mgz/header/de.py` (construct) and `mgz/fast/header.py`
(fast; this is the one `parse_match`/`ModelSummary` actually use) — gated on `save_version >= 67.5`.
The fix is **committed** on the `support-save-version-68` branch (commit `Add support for DE
save_version 68`). It is **PR-ready but not yet upstreamed** — the repo author has been
unresponsive to recent PRs. If mgz gets reinstalled/reset, re-checkout that branch or reapply
from `README.md` / `patches/`.

Note: the full construct `FullSummary` still fails later in `initial` object parsing for v68
(not yet reverse-engineered), but that's unused — `mgz.model.parse_match` (fast path) fully
works: header + body + actions + timeseries.

## Tools in this repo
- `analyze.py <replay>` — human-readable summary (map, duration, civs, teams, age-ups, eAPM).
- `parse.py <replay>` — JSON dump of header/summary fields.
- `debrief.py <replay> [--me NAME]` — **full analysis JSON** (per-player composition, age-ups,
  key upgrades, eco/army timeseries, winner, eAPM; plus spatial: build footprints + your
  movement/attack trail). This is the data layer behind the report artifacts. Default `--me Olive`.

### mgz model API cheatsheet (`from mgz.model import parse_match`)
- `m.players[i]`: `.name .civilization .civilization_id .winner .team_id .eapm .timeseries
  .position .number` (AI players have empty `.name`; identify by `.number`/`.civilization`).
- `m.actions`: list of `.timestamp .type .player .position .payload`. Useful types:
  `DE_QUEUE`/`MAKE` (production; payload has `unit`,`amount`), `RESEARCH` (payload
  `technology`,`technology_id`; ages = 101/102/103 Feudal/Castle/Imperial), `BUILD` (`building`),
  `MOVE`/`ORDER` (carry map `position`). AI uses `AI_ORDER` heavily.
- `p.timeseries`: rows `.timestamp .total_objects .total_resources` (~256 samples/game).
- `m.duration .map.name .map.dimension .chat .diplomacy_type .type`.
- Positions are on the tile grid (0..dimension). ~60% of Olive's commands carry real coords.

## Published artifacts (claude.ai) — update in place with the Artifact tool's `url=` param
- **After-action report** (Arabia 2v2 loss): force curve, composition matchup, upgrade tempo,
  animated + heatmap map-control view. `https://claude.ai/code/artifact/16f89f0c-c92c-44ed-b288-2567a4b06704`
- **Counter card** (combined-arms "what beats what", Britons-specific, audited):
  `https://claude.ai/code/artifact/56c44c4f-0279-4b40-ab50-e8307fbd5720`
Source HTML for these was built in the session scratchpad (not committed here); regenerate data
with `debrief.py`. Design followed the `dataviz` + `artifact-design` skills (tactical-debrief
look: slate ground, bronze/gold accent, serif display, team-blue vs enemy-red).

## Coaching context (the Arabia game we analyzed, 2026-07-22)
2v2 on Arabia, 94 min, **Olive+studiousmonkey1 LOST** to 2 AI (Vikings+Goths). Diagnosis:
- **Gold-split army**: 164 Longbowmen **+ 95 Knights**. Britons have no cav bonus; Knights and
  Arbalest both need gold, so neither line maxed. Olive agreed halbs (gold-free) were the right call.
- **Late upgrades**: Elite Longbowman/Bracer 54–57 min, Arbalester 69 min — archers under-upgraded all game.
- **No siege / no gunpowder** vs enemy 58 Mangonels + 8 BBC + 21 Hand Cannoneers.
- **Goths hard-counter Britons**: 55 Huskarls (high pierce armor) shrug off archers; answer is
  Siege Onager + Skirms/Halbs + cav, never more archers.
- **Positional**: 144/197 of Olive's attack orders were on his own (west) side; 0 attacks on
  their side in the whole first half — pinned defending, only pushed out after halftime.
- Britons fix: one gold sink (Arbalest, which out-ranges at ~9), gold-free Skirm/Halb screen,
  Siege Onager for what arrows can't kill.

## Open threads / next steps Clive may want
- Run `debrief.py` across his **other 4 replays** to find recurring patterns (Knights-alongside-archers
  gold split; late upgrades; defensive pinning). This is the highest-value next analysis.
- Pull **actual engagements** from the Arabia game (cluster attack orders; which fights were lost in
  the open vs a choke; where Huskarls broke the line).
- **Upstream** the v68 fix (push branch to a fork, open PR extending #139/#142) — needs `gh` auth + fork.
- Consider committing the report/counter-card HTML generators into this repo if we keep iterating.
