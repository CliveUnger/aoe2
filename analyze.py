#!/usr/bin/env python3
"""Analyze an AoE2:DE .aoe2record replay via mgz and print a game summary.

Usage: python analyze.py <replay.aoe2record>
"""
import sys
import logging
from collections import defaultdict

logging.disable(logging.CRITICAL)
from mgz.model import parse_match  # noqa: E402


def fmt(td):
    return str(td).split(".")[0] if td is not None else "?"


def main(path):
    m = parse_match(open(path, "rb"))

    print(f"Map:       {m.map.name} ({m.map.dimension}x{m.map.dimension})")
    print(f"Duration:  {fmt(m.duration)}   Completed: {m.completed}")
    print(f"Type:      {m.type}   Diplomacy: {m.diplomacy_type}   Speed: {m.speed}")
    print(f"Dataset:   {m.dataset}   Version: {m.game_version} (save {m.save_version})")
    print()

    # Teams
    print("Players:")
    for p in m.players:
        team_mates = ", ".join(tp.name for tp in p.team if tp.name and tp.name != p.name) or "-"
        result = "WON " if p.winner else "lost"
        print(f"  [{result}] {p.name or '(AI)':18} {p.civilization:14} "
              f"eAPM={p.eapm or '?':<5} team=[{team_mates}]")
    print()

    # Age-up times per player (RESEARCH actions for feudal/castle/imperial)
    AGE_TECHS = {101: "Feudal", 102: "Castle", 103: "Imperial"}
    ages = defaultdict(dict)
    for a in m.actions:
        if a.type.name == "RESEARCH" and a.payload:
            tech = a.payload.get("technology_id") or a.payload.get("technology")
            if tech in AGE_TECHS and a.player:
                ages[a.player.name].setdefault(AGE_TECHS[tech], a.timestamp)

    if ages:
        print("Age-up times (research started):")
        for name, d in ages.items():
            times = "  ".join(f"{age} {fmt(t)}" for age, t in d.items())
            print(f"  {name or '(AI)':18} {times}")
        print()

    # Action volume per player
    counts = defaultdict(int)
    for a in m.actions:
        if a.player:
            counts[a.player.name] += 1
    print("Total actions:")
    for name, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name or '(AI)':18} {c}")

    if m.chat:
        print(f"\nChat messages: {len(m.chat)}")


if __name__ == "__main__":
    main(sys.argv[1])
