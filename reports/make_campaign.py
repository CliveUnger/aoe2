#!/usr/bin/env python3
"""Generate a multi-game squad campaign report (self-contained HTML).

Runs the audited extraction (POV dedup, last-click research, click->entered
ages, capped gross-attrition fight windows with endgame exclusion) over N
replays and injects the data into reports/templates/campaign.html.

Usage:
    python reports/make_campaign.py out.html replay1.aoe2record [replay2 ...] \
        [--allies studiousmonkey1 rickyflows Olive] \
        [--editorial notes.json] [--title "One Saturday, Three Battles"] \
        [--castle-target 22]

The page renders fully with computed defaults; --editorial overrides any of:
  {"eyebrow","title","sub","tiles":[{cls,k,v,s}],"order":[names],
   "castle_target_min":22,
   "games":{"g1":{"title","foes","sum","moments":[["7:32","..."],...],
                  "match":"substring of g1's replay filename (warns on mismatch)"}, ...},
   "bo":{"player name":"note under their build-order table"},
   "advice":[{name,ci,role,ally,ev,n3:[[k,v]..],fx:[..]}, ...]}
Editorial games bind to g1..gN by replay ARGUMENT POSITION — use "match".

Needs the v68-patched mgz (see AGENTS.md). See AGENTS.md "Metric gotchas"
for what these numbers do and don't mean.
"""
import sys
import json
import math
import argparse
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for replaylib
from replaylib import load_match, sec  # noqa: E402

AGE_ID = {101: "Feudal", 102: "Castle", 103: "Imperial"}
AGE_RS = {"Feudal": 130, "Castle": 160, "Imperial": 190}
KEY = {"Fletching", "Bodkin Arrow", "Bracer", "Padded Archer Armor",
       "Leather Archer Armor", "Ring Archer Armor", "Crossbowman", "Arbalester",
       "Elite Skirmisher", "Cavalier", "Bloodlines", "Husbandry", "Forging",
       "Iron Casting", "Blast Furnace", "Chemistry", "Loom", "Wheelbarrow",
       "Hand Cart", "Pikeman", "Man-at-Arms", "Ballistics", "Thumb Ring",
       "Parthian Tactics",
       # keep in sync with SMITH1 below and SMITHSET in campaign.html —
       # a smith tech missing here is invisible to the upgrade timeline
       "Scale Mail Armor", "Scale Barding Armor"}
BUCKET = 600          # villager-timeline bucket (s)
FIGHT_B = 40          # attrition bucket (s)
FIGHT_TH = 12         # combined gross losses to open a window
FIGHT_CAP = 8         # max merged buckets (~5 min) — longer is a campaign
ENDGAME_S = 60        # windows ending within this of game end are wipes


def extract(path, ally_names):
    m = load_match(path)
    dim, dur = m.map.dimension, sec(m.duration)
    ally_idx = {nm: i for i, nm in enumerate(ally_names)}

    def okp(p):
        return p and not (p.x == 0 and p.y == 0) and 0 <= p.x <= dim and 0 <= p.y <= dim

    P = {}
    for p in m.players:
        P[p.number] = {"number": p.number, "name": p.name or f"{p.civilization} AI",
                       "civ": p.civilization, "ally": ally_idx.get(p.name, -1),
                       "winner": p.winner,
                       "start": [round(p.position.x, 1), round(p.position.y, 1)] if okp(p.position) else None}

    seen = set()
    prev_adj = None
    prod = defaultdict(Counter)
    ages = defaultdict(dict)
    rc = defaultdict(dict)        # last research click per tech (re-click = cancel)
    NV = dur // BUCKET + 1        # villager buckets sized to the game, no 2h clamp
    vil = defaultdict(lambda: [0] * NV)
    vqe = defaultdict(list)       # villager queue events (t, amount)
    firstb = defaultdict(dict)    # first placement of key eco buildings
    builds, moves = defaultdict(list), defaultdict(list)
    BO_BLDG = {"Lumber Camp", "Mining Camp", "Mill", "Blacksmith", "Market"}
    for a in m.actions:
        if a.player is None:
            prev_adj = None
            continue
        n, ty, pl, t = a.player.number, a.type.name, a.payload or {}, sec(a.timestamp)
        # DE recorder duplicates ~2-6% of the POV player's own commands as
        # byte-identical ADJACENT records. Set-based dedup (full identity, same
        # key as debrief/extract_full) for the typed commands; adjacent-dup
        # skip for everything else (MOVE/ORDER/...), so maps, aggression and
        # build counts aren't inflated either.
        adj = (n, ty, a.timestamp, str(pl), str(a.position))
        if ty in ("MAKE", "DE_QUEUE", "RESEARCH", "BUILD"):
            key = (n, ty, a.timestamp, pl.get("sequence"), pl.get("unit_id"),
                   pl.get("technology_id"), pl.get("building_id"), str(pl.get("object_ids")))
            if key in seen:
                prev_adj = adj
                continue
            seen.add(key)
        elif adj == prev_adj:
            continue
        prev_adj = adj
        if ty in ("MAKE", "DE_QUEUE") and pl.get("unit"):
            amt = pl.get("amount", 1) if ty == "DE_QUEUE" else 1
            prod[n][pl["unit"]] += amt
            if pl["unit"] == "Villager":
                vil[n][min(t // BUCKET, NV - 1)] += amt
                vqe[n].append((t, amt))
        elif ty == "RESEARCH":
            tid, tech = pl.get("technology_id"), pl.get("technology")
            if tid in AGE_ID:
                # LAST click wins, ages included: a re-click proves a cancel
                ages[n][AGE_ID[tid]] = t
            elif tech:
                rc[n][tech] = t
        elif ty == "BUILD":
            b = pl.get("building")
            if b in BO_BLDG:
                firstb[n].setdefault(b, t)
            if okp(a.position):
                builds[n].append([round(a.position.x, 1), round(a.position.y, 1), t])
        if ty in ("MOVE", "ORDER") and okp(a.position):
            moves[n].append([round(a.position.x, 1), round(a.position.y, 1), t,
                             1 if ty == "ORDER" else 0])

    # gross-attrition windows from per-player object-count drops
    nb = dur // FIGHT_B + 2
    aL, fL = [0] * nb, [0] * nb
    for p in m.players:
        ts = [[sec(r.timestamp), r.total_objects] for r in p.timeseries]
        is_ally = P[p.number]["ally"] >= 0
        for i in range(1, len(ts)):
            d = ts[i][1] - ts[i - 1][1]
            if d < 0:
                k = min(ts[i][0] // FIGHT_B, nb - 1)
                (aL if is_ally else fL)[k] += -d
    aS = [p["start"] for p in P.values() if p["ally"] >= 0 and p["start"]]
    fS = [p["start"] for p in P.values() if p["ally"] < 0 and p["start"]]
    aC = [sum(s[i] for s in aS) / len(aS) for i in (0, 1)] if aS else [0, 0]
    fC = [sum(s[i] for s in fS) / len(fS) for i in (0, 1)] if fS else [dim, dim]
    fights, k = [], 0
    while k < nb:
        if aL[k] + fL[k] >= FIGHT_TH:
            j = k
            while (j + 1 < nb and j - k < FIGHT_CAP and
                   (aL[j + 1] + fL[j + 1] >= FIGHT_TH or
                    (j + 2 < nb and aL[j + 2] + fL[j + 2] >= FIGHT_TH))):
                j += 1
            us, them = sum(aL[k:j + 1]), sum(fL[k:j + 1])
            pk = max(range(k, j + 1), key=lambda x: aL[x] + fL[x])
            xs, ys = [], []
            for n, mv in moves.items():
                for x, y, t, at in mv:
                    if at and k * FIGHT_B <= t <= (j + 1) * FIGHT_B:
                        xs.append(x)
                        ys.append(y)
            c = [round(sum(xs) / len(xs), 1), round(sum(ys) / len(ys), 1)] if xs else None
            side = "—"
            if c:
                da, df = math.dist(c, aC), math.dist(c, fC)
                side = "our side" if da < df * 0.75 else ("their side" if df < da * 0.75 else "midmap")
            net = them - us
            fights.append({"start": k * FIGHT_B, "end": (j + 1) * FIGHT_B,
                           "peak": pk * FIGHT_B + FIGHT_B // 2, "us": us, "them": them,
                           "pos": c, "side": side,
                           "endgame": (j + 1) * FIGHT_B >= dur - ENDGAME_S,
                           "outcome": "won" if net >= 8 else ("lost" if net <= -8 else "trade")})
            k = j + 1
        else:
            k += 1

    SMITH1 = {"Fletching", "Forging", "Padded Archer Armor",
              "Scale Mail Armor", "Scale Barding Armor"}
    roster = []
    for n, p in sorted(P.items()):
        e = {k2: v + AGE_RS[k2] for k2, v in ages[n].items()}
        cc = ages[n].get("Castle")
        bo = {"lumber": firstb[n].get("Lumber Camp"), "mine": firstb[n].get("Mining Camp"),
              "mill": firstb[n].get("Mill"), "smith": firstb[n].get("Blacksmith"),
              "market": firstb[n].get("Market"),
              "smith20": sum(1 for x, t2 in rc[n].items() if x in SMITH1 and t2 <= 1200),
              "vq_castle": sum(a2 for t2, a2 in vqe[n] if t2 <= cc) if cc is not None else None}
        roster.append({**p, "ages": ages[n], "entered": e, "bo": bo,
                       "prod": dict(prod[n].most_common(8)),
                       "total": sum(prod[n].values()),
                       "vills": sum(vil[n]),
                       "vilbuckets": vil[n],
                       "tradecarts": prod[n].get("Trade Cart", 0),
                       "upgrades": sorted(({"t": t, "name": x} for x, t in rc[n].items()
                                           if x in KEY), key=lambda u: u["t"]),
                       "attacks": sum(1 for q in moves[n] if q[3] == 1),
                       "nbuilds": len(builds[n])})
    real = [x for x in fights if not x["endgame"]]
    # dealt/taken over field windows only, matching the page's
    # "(field, excl. endgame)" labeling
    rec = {"w": sum(1 for x in real if x["outcome"] == "won"),
           "l": sum(1 for x in real if x["outcome"] == "lost"),
           "t": sum(1 for x in real if x["outcome"] == "trade"),
           "dealt": sum(x["them"] for x in real),
           "taken": sum(x["us"] for x in real)}
    return {"label": Path(path).stem, "map": m.map.name, "dim": dim, "dur": dur,
            "fights": fights, "record": rec, "roster": roster,
            "moves": {str(n): (mv if P[n]["ally"] >= 0 else mv[::4]) for n, mv in moves.items()},
            "builds": {str(n): v for n, v in builds.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("replays", nargs="+")
    ap.add_argument("--allies", nargs="+", default=["studiousmonkey1", "rickyflows", "Olive"],
                    help="ally names in display order")
    ap.add_argument("--editorial", help="JSON file of editorial overrides")
    ap.add_argument("--title", default="Squad Campaign Report")
    ap.add_argument("--castle-target", type=int, default=22)
    ap.add_argument("--template", default=str(Path(__file__).parent / "templates" / "campaign.html"))
    args = ap.parse_args()

    games = []
    for i, r in enumerate(args.replays):
        g = extract(r, args.allies)
        g["id"] = f"g{i+1}"
        games.append(g)
        print(f"  {g['id']}: {g['map']} {g['dur']//60}:{g['dur']%60:02d} "
              f"{g['record']['w']}W-{g['record']['l']}L-{g['record']['t']}T", file=sys.stderr)

    editorial = {}
    if args.editorial:
        editorial = json.load(open(args.editorial))
    editorial.setdefault("castle_target_min", args.castle_target)

    # editorial games bind to g1..gN by ARGUMENT POSITION — an optional
    # "match" substring per game entry catches a mis-ordered replay list
    for g in games:
        ge = (editorial.get("games") or {}).get(g["id"]) or {}
        if ge.get("match") and ge["match"] not in g["label"]:
            print(f"WARNING: editorial {g['id']} expects a replay matching "
                  f"{ge['match']!r} but got {g['label']!r} — check replay order",
                  file=sys.stderr)

    html = open(args.template).read()
    html = html.replace("__TITLE__", args.title)
    # <-escape so a player name containing </script> can't break the page
    html = html.replace("__DATA__", json.dumps({"games": games, "editorial": editorial},
                                               separators=(",", ":")).replace("<", "\\u003c"))
    open(args.out, "w").write(html)
    print(f"wrote {args.out} ({len(html)//1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
