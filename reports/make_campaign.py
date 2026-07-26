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
   "games":{"g1":{"title","foes","sum","moments":[["7:32","..."],...]}, ...},
   "advice":[{name,ci,role,ally,ev,n3:[[k,v]..],fx:[..]}, ...]}

Needs the v68-patched mgz (see AGENTS.md). See AGENTS.md "Metric gotchas"
for what these numbers do and don't mean.
"""
import sys
import json
import math
import argparse
import logging
from pathlib import Path
from collections import defaultdict, Counter

logging.disable(logging.CRITICAL)
from mgz.model import parse_match  # noqa: E402

AGE_ID = {101: "Feudal", 102: "Castle", 103: "Imperial"}
AGE_RS = {"Feudal": 130, "Castle": 160, "Imperial": 190}
KEY = {"Fletching", "Bodkin Arrow", "Bracer", "Padded Archer Armor",
       "Leather Archer Armor", "Ring Archer Armor", "Crossbowman", "Arbalester",
       "Elite Skirmisher", "Cavalier", "Bloodlines", "Husbandry", "Forging",
       "Iron Casting", "Blast Furnace", "Chemistry", "Loom", "Wheelbarrow",
       "Hand Cart", "Pikeman", "Man-at-Arms", "Ballistics", "Thumb Ring",
       "Parthian Tactics"}
BUCKET = 600          # villager-timeline bucket (s)
FIGHT_B = 40          # attrition bucket (s)
FIGHT_TH = 12         # combined gross losses to open a window
FIGHT_CAP = 8         # max merged buckets (~5 min) — longer is a campaign
ENDGAME_S = 60        # windows ending within this of game end are wipes


def sec(td):
    return round(td.total_seconds())


def extract(path, ally_names):
    m = parse_match(open(path, "rb"))
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
    prod = defaultdict(Counter)
    ages = defaultdict(dict)
    rc = defaultdict(dict)        # last research click per tech (re-click = cancel)
    vil = defaultdict(lambda: [0] * 12)
    builds, moves = defaultdict(list), defaultdict(list)
    for a in m.actions:
        if a.player is None:
            continue
        n, ty, pl, t = a.player.number, a.type.name, a.payload or {}, sec(a.timestamp)
        if ty in ("MAKE", "DE_QUEUE", "RESEARCH"):
            # DE recorder duplicates ~2-6% of the POV player's own commands
            key = (n, ty, a.timestamp, pl.get("unit"), pl.get("technology_id"),
                   pl.get("amount"), str(pl.get("object_ids")))
            if key in seen:
                continue
            seen.add(key)
        if ty in ("MAKE", "DE_QUEUE") and pl.get("unit"):
            amt = pl.get("amount", 1) if ty == "DE_QUEUE" else 1
            prod[n][pl["unit"]] += amt
            if pl["unit"] == "Villager":
                vil[n][min(t // BUCKET, 11)] += amt
        elif ty == "RESEARCH":
            tid, tech = pl.get("technology_id"), pl.get("technology")
            if tid in AGE_ID:
                ages[n].setdefault(AGE_ID[tid], t)
            elif tech:
                rc[n][tech] = t
        elif ty == "BUILD" and okp(a.position):
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

    roster = []
    for n, p in sorted(P.items()):
        e = {k2: v + AGE_RS[k2] for k2, v in ages[n].items()}
        roster.append({**p, "ages": ages[n], "entered": e,
                       "prod": dict(prod[n].most_common(8)),
                       "total": sum(prod[n].values()),
                       "vills": sum(vil[n]),
                       "vilbuckets": vil[n][:max(1, dur // BUCKET + 1)],
                       "tradecarts": prod[n].get("Trade Cart", 0),
                       "upgrades": sorted(({"t": t, "name": x} for x, t in rc[n].items()
                                           if x in KEY), key=lambda u: u["t"]),
                       "attacks": sum(1 for q in moves[n] if q[3] == 1),
                       "nbuilds": len(builds[n])})
    real = [x for x in fights if not x["endgame"]]
    rec = {"w": sum(1 for x in real if x["outcome"] == "won"),
           "l": sum(1 for x in real if x["outcome"] == "lost"),
           "t": sum(1 for x in real if x["outcome"] == "trade"),
           "dealt": sum(x["them"] for x in fights),
           "taken": sum(x["us"] for x in fights)}
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

    html = open(args.template).read()
    html = html.replace("__TITLE__", args.title)
    html = html.replace("__DATA__", json.dumps({"games": games, "editorial": editorial},
                                               separators=(",", ":")))
    open(args.out, "w").write(html)
    print(f"wrote {args.out} ({len(html)//1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
