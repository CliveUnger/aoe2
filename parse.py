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

    players = []
    for p in s.get_players():
        players.append({
            "name": p.get("name"),
            "civ": p.get("civilization"),
            "color_id": p.get("color_id"),
            "team": p.get("team"),
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
