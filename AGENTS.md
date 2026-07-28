# AGENTS.md — AoE2:DE replay analysis workspace

Context for any future agent picking this up (e.g. Clive resuming from a new thread).

## What this is
Tools to parse and analyze Clive's Age of Empires II: Definitive Edition replays
(`.aoe2record`) and produce coaching "after-action reports". Clive's in-game name is
**Olive**; regular teammates **studiousmonkey1** (Mongols) and **rickyflows** (Franks).
He mains **Britons**. Replays live under the Feral (macOS) port:
`~/Library/Application Support/Feral Interactive/Age Of Empires II/VFS/User/Games/Age of Empires 2 DE/76561198081802645/savegame/`

## Setup / environment (uv-managed since 2026-07-27)
- `pyproject.toml` + `uv.lock` — declares deps; `mgz` resolves to the **editable clone**
  at `./aoc-mgz` via `[tool.uv.sources]`. Bootstrap: clone the fork into `./aoc-mgz`,
  then `uv sync` (creates `.venv/`, gitignored).
- `aoc-mgz/` — the editable clone (gitignored — it's its own git repo) of our **hard fork**
  `git@github.com:CliveUnger/aoc-mgz.git`.
- **One CLI fronts everything**: `aoe2 <analyze|parse|debrief|extract|ledger|audit|campaign|latest>`
  (entry point in `cli.py`; run via `.venv/bin/aoe2` or `uv run aoe2`). The word `latest`
  in place of a replay path expands to the newest replay in the savegame dir
  (`AOE2_SAVEGAME_DIR` overrides) — e.g. `aoe2 audit latest`. The per-tool
  `python analyze.py ...` invocations below still work identically.
- Shared helpers live in `replaylib.py` (`load_match`, `sec`, `mmss`, `hms`) — import from
  there, don't redefine per-script (consolidated 2026-07-27, outputs verified byte-identical).

### The mgz hard fork (decided 2026-07-27)
**CliveUnger/aoc-mgz is the canonical mgz** — no PRs to upstream, we develop in our own
direction. In the clone: remote `origin` = the fork, `upstream` = happyleavesaoc/aoc-mgz
(reference only; its author was unresponsive to PRs). **Work on `master`** — it has the
save_version 68 support merged (fork PRs #2/#3, incl. a v68 test replay + full-parser fix)
plus modernized tooling (uv/pyproject, ruff, pytest, CI). The old local branch
`support-save-version-68` is superseded by master.

The v68 delta, for reference (Clive's replays are DE save_version 68.0, build
101.103.48987/48086, `VER 9.4`; no upstream mgz release supports it): one trailing (empty)
`de_string` per player + 8 trailing bytes at the end of the `de` header block, gated
`save_version >= 67.5`, patched in **both** parser paths (`mgz/header/de.py` construct and
`mgz/fast/header.py` fast — the one `parse_match` actually uses). The full construct
`FullSummary` still fails later in `initial` object parsing for v68 (not reverse-engineered),
but that's unused — `mgz.model.parse_match` (fast path) fully works: header + body +
actions + timeseries.

## Tools in this repo
- `replaylib.py` — **shared replay loader (2026-07-26 optimization pass): ALWAYS use
  `from replaylib import load_match` instead of `mgz.model.parse_match` in new/scratch
  scripts.** Two effects, ~5–10x wall-clock: (1) pauses the cyclic GC around the parse —
  parse_match allocates ~1M surviving objects and threshold GC rescans them repeatedly
  (measured 3.5s → 0.6s on the 99-min G2); (2) pickle-caches the parsed Match in
  `data/match_cache/` (gitignored; keyed on replay mtime+size + aoc-mgz commit, so parser
  edits auto-invalidate; corrupt entries fall back to reparse; warm hit ~0.06–0.3s).
  Only difference vs raw parse: `m.hash` is normalized to the sha1 hexdigest str (raw
  fast-path leaves a live unpicklable hashlib object there; nothing reads it). All five
  tools + make_campaign go through it; vill_ledger no longer double-parses (it imports
  `extract_full.build_extract` in-process instead of a subprocess) and groups actions by
  player once instead of 3 full scans/player. Outputs verified byte-identical pre/post.
- `audit.py <replay> [--me NAME]` — **granular slip-up ledger** (added 2026-07-27 after the
  Celts coaching session): every idle/cancel/stall/absence in one report. Sections: ages +
  AI age proxies (TC2 + first Castle-unit queue), TC idle windows via queue sim w/ per-age
  uptime, military-building idle (k-server sim per building type, openings from BUILD times),
  housed-stall ONSETS (spawn-sim pop vs house cap — deaths invisible, so only onsets mean
  anything), Unqueue/SPECIAL cancels + tech re-clicks, GATHER_POINT rally audit (flags
  TC-rally-never-set — the #1 recurring finding, 5,471s birth idle in the 27min 1v1),
  market build-vs-first-use lag, food ledger by category ("food-military ≈ N Castle Ages" —
  the 2026-07-27 1v1 was FOOD-gated: 500f market-bought 4s before the Castle click),
  input silences, fight-window command density, and a ✓/✗ checklist (walls, towers, TC2,
  first farm ≤10:00, blacksmith ≤14:00, ≥4 smith techs by 20:00, TC rally). Reuses
  extract_full.build_extract in-process + the same POV dedup on raw actions.
- `analyze.py <replay>` — human-readable summary (map, duration, civs, teams, age-ups, eAPM).
- `parse.py <replay>` — JSON dump of header/summary fields.
- `debrief.py <replay> [--me NAME]` — **full analysis JSON** (per-player composition, age-ups,
  key upgrades, eco/army timeseries, winner, eAPM; plus spatial: build footprints + your
  movement/attack trail). This is the data layer behind the report artifacts. Default `--me Olive`.
- `extract_full.py <replay> <out.json>` — **superset extractor** (added 2026-07-25, 4-game day
  analysis). Everything debrief.py has plus: ALL research (not just KEY_UPGRADES, with click
  counts), all-building footprints with ids, ALL-player MOVE/ORDER trails, market SELL/BUY,
  resign/delete events, per-minute command counts, per-resource **spending reconstruction**
  (units/techs/buildings at `data/techtree.json` costs — refresh that file after balance
  patches), and fight windows (gross-attrition, ≤60s merge gap, 4-min cap, endgame-60s
  excluded) precomputed with per-player loss attribution. POV dedup: debrief.py and
  extract_full.py use the SAME full-identity key (sequence/unit_id/technology_id/building_id/
  object_ids, MAKE/DE_QUEUE/RESEARCH/BUILD) since the 2026-07-26 bug sweep; extract_full
  additionally drops byte-identical ADJACENT duplicates of all other types (MOVE/ORDER/...),
  and counts cmd_minutes only after dedup. NB `sequence` alone is NOT unique — same-tick
  different commands share it. Civ-invalid
  queue filter: only drops not-in-tree units with total ≤2 (client junk); larger counts are
  techtree line-listing misses (e.g. Hindustanis Camel Scout is listed under Camel Rider) and
  are kept. Derived-metric recipes that proved useful (see 2026-07-25 section): TC-uptime% =
  vills_queued×25s / TC-seconds; "readiness at 22:00"; AI Castle-arrival proxy = AI's 2nd TC
  build time; Feudal aggression = enemy-side attack orders before 20:00; TC-idle via
  **queue simulation** (vill queues + Loom 25s + Feudal 130s / Castle 160s as serial jobs on
  one TC — exact modulo cancels; also yields true trained-pop at age clicks, which beats raw
  queued counts for batch-queuers); housed-stall detection = sim pop vs 5+5×houses(+25s
  build). Villager idle/tasking is NOT recoverable (command stream, no unit state) — camp/
  mill build times are the eco-layout proxy. NB `chat` in replays is AI status spam
  ("-Villager Created--"), unattributed — no human comms recorded.
  Build-order findings (2026-07-25 games; bo.py in /tmp scratch, recipes above): Olive
  lumber camp 6:26–8:11 in 3 of 4 games (Huns start −100 wood!) + Loom never/~36:00 +
  Castle clicked at 38–47 pop (banks pop instead of clicking; could click ~30 pop ≈19:30);
  ricky textbook opening + fast Castle 16:50–19:18 @24–28 pop but no follow-through
  (Loom never/never/16:29/21:13; G4 militia-opening regression, 5 housed vills 13:33–21:25,
  Castle 27:42); studious best first 3 min (2 houses + Loom by 0:20) but Feudal click at
  12–19 pop then worst TC idle (461–654s to 25:00) and mining camp 17:13–20:07 every game.
  Unused civ synergy: Huns TEAM bonus stables +20% work rate (buffs ricky/studious cav),
  Franks mounted +20% HP, Mongols scout-line +20/30% HP Castle/Imp — a cavalry team comp
  playing trash-only armies.
- `vill_ledger.py [replay paths or G1..G4]` — **per-villager task ledger** to Castle click+120s
  (added 2026-07-25 evening; v4 2026-07-26 takes arbitrary replay paths, auto-generates its
  extract_full JSONs into `data/extracts/` — no more /tmp dependency; G1..G4 remain as
  shorthand for that day's session).
  KEY unlock: `m.gaia` WORKS on v68 (12k objects w/ instance_id+name+position: trees, Gold/
  Stone Mine, Forage Bush, herdables — these Arabia seeds use COWS) and `p.objects` gives
  starting vill/scout/TC ids, so every human right-click (ORDER) resolves to an actual
  resource. Humans task vills via ORDER, never WORK (WORK is AI-only). The command-addressable
  TC id = DE_QUEUE object_ids (NOT the multi-part p.objects Town Center entries). Model:
  build busy = BuildTime×3/(2+builders), builders auto-continue after dropsites/farms but
  IDLE after houses/military/walls; tree/mine/forage gathers indefinite; herdables indefinite
  (DE auto-continues in range — do NOT cap hunt, causes false idle); obj-target ORDERs within
  2.5 tiles of own Farm builds = farm tasks; birth idle = order-matched TC-sim births vs
  first commands, only meaningful when no TC resource rally exists. Research ledger: a later
  re-click of the same tech PROVES the earlier click was cancelled.
  **Death-vs-idle disambiguation (v3, 2026-07-26):** an idle window CLOSED by a later command
  on the same villager is death-proof (villager provably alive) — this certifies ALL birth
  idle and mid-timeline idle. Only "tail" windows (no command ever again) are ambiguous;
  classify those via total_objects delta around window start + fight-window overlap
  (in-fight or negative Δ → LIKELY DEAD; quiet+flat → likely idle). ORDER onto own TC id =
  garrison/drop-off, busy not idle. Residual limits: mid-window deaths in "likely idle"
  tails undetectable (Δ only sampled near start); objΔ is net (production masks deaths).
  Corrections this produced: G4 Olive's 3 range-builders at 22:25 DIED in the wall fight
  (objΔ=-16, in-fight) — he built a reactive forward range mid-attack and lost the builders;
  G1's +508s "after Stable" was also a death. G3's twin 1304s vills (5:00, objΔ=0, no fight)
  are genuinely forgotten villagers. Pre-Castle vill deaths ≈1-4/game/player (no Loom!).
  Confirmed-idle totals (death-proof): Olive 4965/1319/498/5400s, studious 6663/4793/1000/
  1699s, ricky 515/3583/171/474s — the rally-point finding stands untouched.
  Findings (all 4 games): **Olive & studious set a TC resource rally in ZERO games; ricky in
  3 of 4** — birth idle Olive 4938/757/0/4613s, studious 5965/4458/701/1365s, ricky ~0 when
  rallying but 3583s in G2 (the game he skipped it). Olive strands builder squads after
  military buildings (3 vills +350s each after a 22:25 Archery Range in G4 — during the wall
  fight; +508s after a G1 Stable) and has a TECH-CANCEL HABIT (Loom clk 3:31 G4 cancelled →
  redone 37:21; Wheelbarrow 12:37 G2 cancelled → 24:42; Wheelbarrow 24:41 G3 cancelled).
  ricky parks vills on ground and forgets them (726-834s "after move" idles every game).
  studious double-leaks at the TC (idle TC + untasked new vills). Research queue-waits are
  a non-problem (worst 47s) — upgrade lateness is absence, not queueing.

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
  produce duplicates. All extractors keep the LAST click per tech — **ages included** since
  the 2026-07-26 sweep ("Wheelbarrow 12:04" was a cancelled click; real 24:42) — and debrief
  emits `ages_entered` = click + research time
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

- `reports/make_campaign.py <out.html> <replays...>` — **reusable campaign-report generator**
  (added 2026-07-26): N-game squad report from `reports/templates/campaign.html` (the
  generalized "One Saturday" page — session tempo trend, eco/trade, aggression profile, day
  totals, auto advice cards, per-game tabs w/ animated map + combat log). Renders fully from
  computed defaults; `--editorial notes.json` overrides hero/tiles/per-game narrative/advice
  (see reports/README.md). Embeds the audited methodology (POV dedup, last-click research,
  click→entered, capped attrition windows).

### 2026-07-26 bug sweep (two-agent adversarial review, all findings fixed)
All extractors now agree by construction: shared full-identity dedup key (BUILD included),
last-click rule for AGE techs too, cmd_minutes counted post-dedup. analyze.py no longer
merges all AIs into one name-keyed row (keys by player number). parse.py emits real teams
(from get_teams) + civ names on the v68 path. vill_ledger v4: fixed dedup key (sequence
is not unique per command — 13 real same-tick commands were being dropped in G2), own-TC
garrison check moved ABOVE farm-proximity, (0,0) sentinel filter on farm positions, CLI
paths + data/extracts cache. Campaign template generalized: auto-scaled trend y-axis (was
hardcoded 15–32min — real 35:28/50:14 arrivals drew off-chart), data-driven legends (were
hardcoded to the 3 names → misattributed players in the 2v2), every ally() lookup guarded
(mixed team sizes no longer blank the page), color cycling for >3 allies, Scale Mail/
Barding added to KEY (smith counts now match the smith timeline), dealt/taken excl endgame
to match label, "attack orders" relabeled "targeted orders" (ORDER includes eco tasking —
proven by the vill ledger), :60 clock rounding, editorial "match" guard. G1-G4 headline
findings (rally points, float, late Castle) all reverified unchanged after the fixes.

## Published artifacts (claude.ai) — update in place with the Artifact tool's `url=` param
- **The Two-Hour War** (2026-07-26, the 12:19 2h08m Arabia 3v2 vs Maya+Spanish AI — PAUSED
  mid-game on the verge of winning, may be resumed; save-quit at 2:08:29 makes mgz mark the
  AIs "winners" — artifact, footnoted in the report): momentum (cumulative net attrition)
  hero chart w/ lead-flip annotation, four-act structure, last-session targets scorecard
  (0/5 hit — Olive 2 smith techs by 20:00 vs 0 all last week), 36-fight combat log,
  animated map, roster cards, franchise records wall (6 of 10 fell today: longest game,
  Olive 1,032 units + 147 vills, squad 1,936, 36 battles, ricky 33 trade carts + 2,029
  cmds). Data: `data/extracts/` (now covers ALL replays) via scratchpad build_stats.py →
  report_data.json; source two_hour_war.html in session scratchpad. Palette (validated,
  dark #171a20): Olive #b8871f, studious #1a9c8c, ricky #8873e8, enemy #d95040, squad-side
  blue #5b8fd9. If the game is RESUMED, the continuation is a NEW replay file — regenerate
  with both, or add a "Part II" to this page.
  `https://claude.ai/code/artifact/5e157fc6-b1b9-4759-8ee9-b771b2b5f6e0`
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

## Published: Squad Campaign Report — now "One Saturday, FOUR battles" (updated 2026-07-26)
Same URL as below; regenerated via `reports/make_campaign.py` with all 4 games (incl. G4 "The
Wall" 17:26) + `reports/editorial/2026-07-25.json`. Adds "The openings, under the microscope":
per-player build-order tables (first camps, Loom, smith built, smith-techs-by-20:00, vills
queued at Castle click) + villager-ledger notes (rally points, cancelled techs, stranded
builders). To update again: rerun the generator into the artifact path and republish.

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

## Deep-dive: the four 2026-07-25 3v2 losses (analysis session, evening 2026-07-25)
All four Arabia 3v2s vs AI that day (G1 14:49 29min, G2 15:10 99min, G3 16:52 47min,
G4 17:26 49min — G4 was played after the Squad Campaign report) analyzed with
`extract_full.py`. **One repeated loss**: the AI reaches Castle ~19–24 (TC2 proxy
21:51–26:46) and pushes; every game has an own-side attrition disaster starting 22:01–23:53
(G1 team −151 → 29-min resign; G4 −80). At 22:00 the team is in Feudal in 11 of 12
player-games. Readiness@22:00 patterns: **Olive** 0 blacksmith techs in ALL FOUR games
(even with smith built 13:59/12:43), army 21–30 unupgraded trash, but eco now fine
(35–47 vills, TC-uptime 59–80%, Castle clicks 24:11–28:05 still late); **ricky** fast
Castle (16:50–19:18, G4 regressed 27:42) but 6–13 army and 1.6–4.3k banked at 22:00
(peak bank 4.4–6.6k — now the team's biggest floater; G1: resigned with 4,496 banked
having made 16 army all game); **studious** TC-uptime 44–49% every game, 23–26 vills
@22:00 (total 29–48), scout-monospam 43–78 with ≤2 smith techs. Feudal aggression ~0
enemy-side attack orders before 20:00 (G4 slight improvement: Olive 14, ricky 6).
**G2 proves the formula**: ricky 29 trade carts + Imperial upgrades → 11W-11L-3T for an
hour; its two −270/−233 disasters were during Olive's late Imp transition (clicked 55:50).
G3 was conceded at 47min right after two crushing defensive wins (43:01 0 vs −30;
44:25 0 vs −90) — field record 5W-1L-3T at concession (caveat: gross attrition can't see
base/eco damage). Next-session targets set: Olive ≥4 smith techs clicked by 20:00;
ricky ≥30 army by 22:00 & <1,000 banked at 22:00; studious TC-uptime ≥80% (≈40 vills
by 22:00); team Castle click ≤19:30. Scratch analysis scripts: /tmp/aoe2-today/
(analyze_today.py, wall.py — recipes summarized in the extract_full.py bullet above).

## Open threads / next steps Clive may want
- Run `debrief.py` across his **other 4 replays** to find recurring patterns (Knights-alongside-archers
  gold split; late upgrades; defensive pinning). This is the highest-value next analysis.
- Pull **actual engagements** from the Arabia game (cluster attack orders; which fights were lost in
  the open vs a choke; where Huskarls broke the line).
- Consider committing the report/counter-card HTML generators into this repo if we keep iterating.
