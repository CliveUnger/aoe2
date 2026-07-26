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
The fix is **committed** on the `support-save-version-68` branch (commit `b5930a2` "Add support
for DE save_version 68") and **pushed to Clive's fork**: remote `clive` →
`git@github.com:CliveUnger/aoc-mgz.git` (branch tracks `clive/support-save-version-68`). `origin`
still points at upstream happyleavesaoc/aoc-mgz. The **PR is not yet opened** (Clive deferred it,
2026-07-25) — open with `gh pr create --repo happyleavesaoc/aoc-mgz --head CliveUnger:support-save-version-68`
when ready; upstream author has been unresponsive to recent PRs (#139/#142). If mgz gets
reinstalled/reset, re-checkout that branch or reapply from `README.md`.

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

### ⚠️ Metric gotchas (Clive has caught all three — always caveat these)
- `total_resources` is a **single sum of food+wood+gold+stone** (verified against raw sync
  values, 2026-07-25: the 4 unknown sync fields are checksum-like, no per-resource split
  exists in the file). A high sum may be unspendable wood/stone — NEVER claim "could afford
  X age at time T" from it. A LOW sum does prove nothing was floating. Per-resource
  **spending** can be reconstructed from DE_QUEUE/RESEARCH/BUILD at known base costs
  (estimate: cancels invisible, elite-upgrade costs approximate).
- Production counts (`prod`) are units **trained (queued), not alive/peak — for EVERY unit
  type, army included** (Clive: "same logic applies to any unit"). A big count can be a big
  force OR heavy churn (waves dying + being replaced). Peak concurrent army is NOT
  recoverable (`peak_obj`/`total_objects` conflates villagers+army+buildings). Frame
  compositions as cumulative production, and use the production **timeline** to tell the
  stories apart: front-loaded+tapering = boom/standing force; bursts synced to fights or
  re-built TCs = replacement waves. (e.g. Olive's 293 Spearmen = 3 waves of ~80.)
- Unit-loss deltas from `total_objects` conflate villagers, military, buildings, expiring
  farms, and deletions — and production inside the same ~26s sample offsets losses (net vs
  gross). Fight windows built from them are gross-attrition windows, not battles; cap merge
  length (a 15-min merged window is a campaign) and exclude windows ending at game end
  (base-razing wipe, not a field fight).
- **POV duplication (2026-07-25 audit):** the DE recorder duplicates ~2-6% of the RECORDING
  player's own commands (byte-identical adjacent records; teammates ~0%). Inflated every
  "Olive" count until fixed. debrief.py now dedups on full action identity. Corrected:
  293 Spearmen → **258** (still 3 waves), 164 Longbowmen → **153**, latest-game total 693 → 640.
- **RESEARCH actions are CLICKS, not completions**, and re-clicks (= earlier click cancelled)
  produce duplicates. debrief.py keeps the LAST click per non-age tech ("Wheelbarrow 12:04"
  was a cancelled click; real 24:42) and emits `ages_entered` = click + research time
  (130/160/190s) as a lower bound — TC queue wait adds up to ~75s more (measured vs
  `m.uptimes`, whose own player attribution is buggy in TGs). Quoted tempo: "Castle 32:48"
  = entered 35:28; "46:00" = entered ~50:14.
- "Tiles traveled" from consecutive command positions = **command spread**, not movement
  (an AI clocked 181k tiles = 30 tiles/sec). Don't present as distance.
- mgz `eapm` = raw attributed commands/min excluding only AI_ORDER — fine for human
  idle-rate arguments, invalid vs AI numbers (dominated by WORK micro ops humans never emit).
- DE_QUEUE records **requests, not spawns** — the client can queue civ-impossible units the
  server rejects (a Mongol player queued 1 Camel Scout). Filter civ-invalid units; the
  unit-id mapping itself audit-checked clean.
- Spending cost tables: regenerate from live game data (aoe2techtree data.json), NOT memory —
  2024-25 patches changed militia-line 50f/20g, Crossbowman-upg 175f/100g, Arbalester-upg
  450f/350g, Pikeman-upg 160f/90g, Arson 75f/25g (Feudal), Thumb Ring 300f/250**w**, Magyar
  Huszar 35f/45g, Watch Tower 35w, Palisade 3w; **Supplies no longer exists**. Never smear
  costs across a curve — UUs/trebs appear in DE_QUEUE at real timestamps.
- Coaching-claim errata: DE default AI never cheats resources at ANY difficulty (incl.
  Extreme); Franks bonus is all mounted units +20% HP, Castles -15%/-25% by age; community
  age benchmarks (e.g. "16:30 Castle") are ARRIVAL times — state click + arrival.
- The save_version 68 patch itself **fully survived** an adversarial audit (2026-07-25):
  both parser paths consistent, validated end-to-end on all 9 replays.
- `m.duration .map.name .map.dimension .chat .diplomacy_type .type`.
- Positions are on the tile grid (0..dimension). ~60% of Olive's commands carry real coords.

## Published artifacts (claude.ai) — update in place with the Artifact tool's `url=` param
- **After-action report** (Arabia 2v2 loss): force curve, composition matchup, upgrade tempo,
  animated + heatmap map-control view. `https://claude.ai/code/artifact/16f89f0c-c92c-44ed-b288-2567a4b06704`
- **Counter card** (combined-arms "what beats what", Britons-specific, audited):
  `https://claude.ai/code/artifact/56c44c4f-0279-4b40-ab50-e8307fbd5720`
- **The Float** (resource-tempo debrief, 2 Huns games 2026-07-24): banked-resources-over-time
  area charts w/ "stalled on Castle money" window + lost-fight markers.
  `https://claude.ai/code/artifact/49889864-e537-4e19-a862-3a4570337bfb`
  Source in scratchpad `float.html`; data from `debrief.py` timeseries (banked = total_resources).
- **Squad Debrief** (the 3v2, 2026-07-24 18:11 game — the "everything" artifact, shareable w/ friends):
  tempo race (all 3 allies' age-ups vs benchmark), per-teammate cards (tempo/float sparkline/comp/
  1-fix each), animated battlefield map (all 5 players over the clock + engagement heatmap toggle),
  a fight-by-fight combat log (diverging casualties timeline; record 1W-4L-2T, 6/7 fights on Olive's
  own side — the pinning pattern), squad superlatives, enemy comp.
  `https://claude.ai/code/artifact/f57c5449-01e4-4527-af84-071977bb1be5`
  Source `team.html`; spatial data extracted ad-hoc (all-player MOVE/ORDER trails + builds, `/tmp/map.json`);
  per-ally tempo/float from `debrief.py` (`/tmp/team.json`). Allies: studiousmonkey1/Mongols,
  rickyflows/Franks, Olive/Huns. Friends' fixes: studious=more vills; ricky=make Knights (off-civ
  skirms) + keep teching; Olive=age up (the float). Reminder to Clive: Artifacts are private —
  use the page Share menu to send to friends.
Source HTML for these was built in the session scratchpad (not committed here); regenerate data
with `debrief.py`. Design followed the `dataviz` + `artifact-design` skills (tactical-debrief
look: slate ground, bronze/gold accent, serif display, team-blue vs enemy-red).

## Coaching context (the Arabia game we analyzed, 2026-07-22)
2v2 on Arabia, 94 min, **Olive+studiousmonkey1 LOST** to 2 AI (Vikings+Goths). Diagnosis:
- **Gold-split army**: 153 Longbowmen **+ 95 Knights** (trained; POV-dedup corrected). Britons have no cav bonus; Knights and
  Arbalest both need gold, so neither line maxed. Olive agreed halbs (gold-free) were the right call.
- **Late upgrades**: Elite Longbowman/Bracer 54–57 min, Arbalester 69 min — archers under-upgraded all game.
- **No siege / no gunpowder** vs enemy 58 Mangonels + 8 BBC + 21 Hand Cannoneers.
- **Goths hard-counter Britons**: 55 Huskarls (high pierce armor) shrug off archers; answer is
  Siege Onager + Skirms/Halbs + cav, never more archers.
- **Positional**: 144/197 of Olive's attack orders were on his own (west) side; 0 attacks on
  their side in the whole first half — pinned defending, only pushed out after halftime.
- Britons fix: one gold sink (Arbalest, which out-ranges at ~9), gold-free Skirm/Halb screen,
  Siege Onager for what arrows can't kill.

## Published: Squad Campaign Report (2026-07-25, "One Saturday, three battles")
`https://claude.ai/code/artifact/b3b05fc6-228c-4ef2-a087-e8ce6fceed7e` — source `trilogy.html`
in session scratchpad; data extractor logic mirrors the audited debrief.py (POV dedup, last-click
research, click→entered ages, capped attrition windows w/ endgame exclusion). Covers the three
2026-07-25 Arabia TG losses vs Hard AI (14:49 "Collapse" 29min, 15:10 "War" 99min, 16:52
"Concession" 47min quit). Holistic: Castle-arrival trend vs 22:00 target, eco/trade chart, day
attrition 1652/1913. Advice cards: studious=The Scalpel (29/48/36 vills — eco), ricky=The
Pacesetter (fastest Castle ×3, only Imperial ×2; needs upgrades+trade every game, veto early GG),
Olive=The Engine (float fixed, Castle trend improving; needs gold engine/trade, blacksmith by
14:00, Pikeman). Key facts: G3 quit at 2W-0L-2T +203/−65 field record; G1 studious Castle arrived
29:11, 2s after game end; G2 fights flipped when Imperial upgrades landed, lost base race ~2min.

## Tempo finding (2 Huns games, 2026-07-24) — the big one
Both Arabia team-game losses. **Root cause = economic tempo, not army comp.** Feudal times
fine (~9:40 click) but **Castle Age clicked 32:48 / 46:00 = entered 35:28 / ~50:14** (arrival
target ~16:30), Imperial never. Fighting Castle/Imp AI armies with Feudal units
(Skirms/Spears/Militia/Scouts). The mechanism, proven from timeseries: he **floats
1,000–2,340 unspent resources** (sum of all 4 — see gotchas) the whole mid-game (low command
rate → idle TC, unclicked upgrades: Loom 28min; NB "Wheelbarrow 12min" was a cancelled
click, real 24:42). Big army losses (−21, −67,
−64…) all land at 19–27min = when he SHOULD be in Castle. Causality he *felt* ("losing Feudal
fights wrecks my Castle") is **backwards**: the float delayed Castle; the delay made the fights
unwinnable. Prescription given: (1) floor rule — 800f+200g on hand → click next age immediately;
(2) 200 rule — any resource past ~250 = idle production, add vills + a military building.

## Open threads / next steps Clive may want
- Run `debrief.py` across his **other 4 replays** to find recurring patterns (Knights-alongside-archers
  gold split; late upgrades; defensive pinning). This is the highest-value next analysis.
- Pull **actual engagements** from the Arabia game (cluster attack orders; which fights were lost in
  the open vs a choke; where Huskarls broke the line).
- **Upstream** the v68 fix (push branch to a fork, open PR extending #139/#142) — needs `gh` auth + fork.
- Consider committing the report/counter-card HTML generators into this repo if we keep iterating.
