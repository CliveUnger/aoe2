# reports/ — reusable report generators

## make_campaign.py — squad campaign report

Self-contained, theme-aware HTML report over N replays: session tempo trend
(Castle arrivals vs target), economy/trade chart, aggression profile, day
totals, per-player advice cards, and per-game tabs (tempo strip, forces,
villager pulse, upgrade timeline, animated battlefield map, combat log,
engagement table).

```bash
source venv/bin/activate
python reports/make_campaign.py out.html game1.aoe2record game2.aoe2record \
    [--allies studiousmonkey1 rickyflows Olive] \
    [--title "Four Battles"] [--castle-target 22] [--editorial notes.json] \
    [--template path/to/campaign.html]
```

Works with 1..N games, any team size, and sessions that mix team sizes (an
ally missing from a game is simply skipped in that game's panels). Everything
renders from computed defaults; pass `--editorial notes.json` to override any
narrative surface:

```jsonc
{
  "title": "One Saturday, three battles.",       // hero <h1> (HTML ok)
  "sub": "...",                                   // hero paragraph
  "eyebrow": "...",
  "castle_target_min": 22,
  "tiles": [{"cls":"red","k":"...","v":"...","s":"..."}],
  "order": ["name1","name2"],                     // display order
  "games": {                                      // per-game overrides (partial ok)
    "g1": {"title":"The Collapse", "foes":"Khitans + Hindustanis",
            "sum":"...", "moments":[["7:32","<b>...</b> ..."]],
            "match":"144944"}                     // optional guard: warn if g1's
                                                  // replay filename doesn't contain this
  },
  "bo": {"name1": "per-player note under the build-order table (HTML ok)"},
  "advice": [ /* full advice cards; omit to use the auto-coach */ ]
}
```

NB editorial `games` entries bind to `g1..gN` by **replay argument position**
— use the `match` key so a re-ordered replay list warns instead of silently
attaching the wrong narrative.

The extraction embeds the audited methodology (see AGENTS.md "Metric
gotchas"): POV-duplication dedup, cancelled-research collapse (last click
wins), ages as click + research time ("entered" is a lower bound), fight
windows as capped gross-attrition buckets with endgame wipes excluded from
records, unit counts as cumulative production.

Template: `templates/campaign.html` (placeholders `__DATA__`, `__TITLE__`).
Design follows the tactical-debrief system (light+dark, validated palette).
