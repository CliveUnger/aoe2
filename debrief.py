#!/usr/bin/env python3
"""Extract a full analysis dataset from an AoE2:DE .aoe2record replay.

Dumps one JSON object with match meta, per-player composition / age-ups /
key upgrades / eco+army timeseries / winner, and spatial data (build
footprints + your movement & attack trail). This is the data layer behind
the "after-action report" artifacts.

Usage:
    python debrief.py "<replay.aoe2record>" [--me NAME] > out.json

Needs the v68-patched mgz (editable clone at ./aoc-mgz, see README).
"""
import sys
import json
import argparse
import logging
from collections import Counter, defaultdict

logging.disable(logging.CRITICAL)
from mgz.model import parse_match  # noqa: E402

AGE_TECH = {101: "Feudal", 102: "Castle", 103: "Imperial"}
# military/eco upgrades worth putting on a timeline (extend as needed)
KEY_UPGRADES = {
    "Fletching", "Bodkin Arrow", "Bracer", "Padded Archer Armor",
    "Leather Archer Armor", "Ring Archer Armor", "Crossbowman", "Arbalester",
    "Elite Skirmisher", "Elite Longbowman", "Cavalier", "Paladin",
    "Bloodlines", "Husbandry", "Forging", "Iron Casting", "Blast Furnace",
    "Chemistry", "Hoardings", "Loom", "Wheelbarrow", "Hand Cart",
}


def sec(td):
    return round(td.total_seconds())


def pname(p):
    return p.name or f"{p.civilization} AI"


def ok_pos(pos, dim):
    return pos and not (pos.x == 0 and pos.y == 0) and 0 < pos.x <= dim and 0 < pos.y <= dim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--me", default="Olive", help="your in-game name (for the trail)")
    args = ap.parse_args()

    m = parse_match(open(args.replay, "rb"))
    dim = m.map.dimension

    prod = defaultdict(Counter)          # number -> unit -> count
    ages = defaultdict(dict)             # number -> {age: sec}
    upgrades = defaultdict(list)         # number -> [{t,name}]
    builds = defaultdict(list)           # number -> [[x,y,t]]
    trail = []                           # [[x,y,t,is_attack]] for --me

    me = next((p for p in m.players if p.name == args.me), None)

    for a in m.actions:
        if a.player is None:
            continue
        n = a.player.number
        ty = a.type.name
        pl = a.payload or {}
        if ty == "MAKE" and pl.get("unit"):
            prod[n][pl["unit"]] += 1
        elif ty == "DE_QUEUE" and pl.get("unit"):
            prod[n][pl["unit"]] += pl.get("amount", 1)
        elif ty == "RESEARCH":
            tid, tech = pl.get("technology_id"), pl.get("technology")
            if tid in AGE_TECH:
                ages[n].setdefault(AGE_TECH[tid], sec(a.timestamp))
            if tech in KEY_UPGRADES:
                upgrades[n].append({"t": sec(a.timestamp), "name": tech})
        elif ty == "BUILD" and ok_pos(a.position, dim):
            builds[n].append([round(a.position.x, 1), round(a.position.y, 1), sec(a.timestamp)])
        if me is not None and a.player is me and ty in ("MOVE", "ORDER") and ok_pos(a.position, dim):
            trail.append([round(a.position.x, 1), round(a.position.y, 1), sec(a.timestamp),
                          1 if ty == "ORDER" else 0])

    players = []
    for p in m.players:
        players.append({
            "number": p.number, "name": pname(p), "civ": p.civilization,
            "winner": p.winner, "team": p.team_id, "eapm": p.eapm,
            "is_me": p.name == args.me,
            "ages": ages[p.number],
            "prod": dict(prod[p.number].most_common()),
            "total_units": sum(prod[p.number].values()),
            "upgrades": upgrades[p.number],
            "peak_obj": max((r.total_objects for r in p.timeseries), default=0),
            "ts": [[sec(r.timestamp), r.total_objects, r.total_resources] for r in p.timeseries],
        })

    out = {
        "file": args.replay,
        "map": m.map.name, "dim": dim,
        "duration": sec(m.duration), "completed": m.completed,
        "type": str(m.type), "diplomacy": str(m.diplomacy_type),
        "save_version": m.save_version, "game_version": m.game_version,
        "players": players,
        "starts": {p.number: {"x": p.position.x, "y": p.position.y, "name": pname(p),
                              "civ": p.civilization, "me": p.name == args.me, "winner": p.winner}
                   for p in m.players},
        "builds": {k: v for k, v in builds.items()},
        "trail": trail,
    }
    json.dump(out, sys.stdout, separators=(",", ":"))


if __name__ == "__main__":
    main()
