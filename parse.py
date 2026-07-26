#!/usr/bin/env python3
"""Parse an AoE2:DE .aoe2record replay with mgz and emit a JSON summary."""
import sys
import json
from datetime import timedelta
from mgz.summary import Summary


def fmt(ms):
    if ms is None:
        return None
    return str(timedelta(milliseconds=ms)).split(".")[0]


def main(path):
    with open(path, "rb") as f:
        s = Summary(f)

    # get_players() has no team field on the v68 (ModelSummary) path and its
    # "civilization" is a numeric id — derive team from get_teams() and the
    # civ name from the parsed match when available.
    team_of = {}
    for i, team in enumerate(s.get_teams() or [], 1):
        for num in team:
            team_of[num] = i
    civ_name = {}
    match = getattr(s, "match", None)  # ModelSummary keeps the parsed match
    if match is not None:
        civ_name = {p.number: p.civilization for p in match.players}

    players = []
    for p in s.get_players():
        num = p.get("number")
        players.append({
            "name": p.get("name"),
            "number": num,
            "civ": civ_name.get(num, p.get("civilization")),
            "civ_id": p.get("civilization"),
            "color_id": p.get("color_id"),
            "team": p.get("team") if p.get("team") is not None else team_of.get(num),
            "winner": p.get("winner"),
            "user_id": p.get("user_id"),
            "position": p.get("position"),
            "rate_snapshot": p.get("rate_snapshot"),
        })

    dur = s.get_duration()
    settings = s.get_settings()
    out = {
        "file": path,
        "duration": fmt(dur),
        "duration_ms": dur,
        "completed": s.get_completed(),
        "version": str(s.get_version()),
        "dataset": s.get_dataset(),
        "map": s.get_map(),
        "settings": settings,
        "diplomacy": s.get_diplomacy(),
        "players": players,
        "chat_count": len(s.get_chat() or []),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
