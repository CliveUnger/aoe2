#!/usr/bin/env python3
"""Analyze an AoE2:DE .aoe2record replay via mgz and print a game summary.

Usage: python analyze.py <replay.aoe2record>
"""
import sys
from collections import defaultdict

from replaylib import load_match


def fmt(td):
    return str(td).split(".")[0] if td is not None else "?"


def main(path):
    m = load_match(path)

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

    # Key everything by player NUMBER: AI players all have name == '', so
    # name-keyed dicts silently merge them (and their counts) into one row.
    def label(num):
        p = by_number.get(num)
        if p is None:
            return f"(p{num})"
        return p.name or f"(AI p{num} {p.civilization})"

    by_number = {p.number: p for p in m.players}

    # Age-up times per player (RESEARCH actions for feudal/castle/imperial).
    # Last click wins: a later re-click of the same age proves the earlier
    # click was cancelled (same rule as debrief.py uses for other techs).
    AGE_TECHS = {101: "Feudal", 102: "Castle", 103: "Imperial"}
    ages = defaultdict(dict)
    for a in m.actions:
        if a.type.name == "RESEARCH" and a.payload:
            tech = a.payload.get("technology_id") or a.payload.get("technology")
            if tech in AGE_TECHS and a.player:
                ages[a.player.number][AGE_TECHS[tech]] = a.timestamp

    if ages:
        print("Age-up times (last research click; re-clicks supersede):")
        for num, d in ages.items():
            times = "  ".join(f"{age} {fmt(t)}" for age, t in d.items())
            print(f"  {label(num):18} {times}")
        print()

    # Action volume per player. The DE recorder duplicates ~2-6% of the
    # recording player's own commands as byte-identical adjacent records —
    # skip those so the POV player's count isn't inflated.
    counts = defaultdict(int)
    prev = None
    for a in m.actions:
        key = (a.timestamp, a.type, a.player.number if a.player else None,
               str(a.payload), str(a.position))
        dup = key == prev
        prev = key
        if dup or not a.player:
            continue
        counts[a.player.number] += 1
    print("Total actions (POV-deduped):")
    for num, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {label(num):18} {c}")

    if m.chat:
        print(f"\nChat messages: {len(m.chat)}")


if __name__ == "__main__":
    main(sys.argv[1])
