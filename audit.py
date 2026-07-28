#!/usr/bin/env python3
"""Granular slip-up audit of one player's replay — every idle, cancel, stall,
and out-of-order decision we know how to detect (built from the 2026-07-27
coaching session; see AGENTS.md).

Usage: python audit.py <replay.aoe2record> [--me NAME]

Sections:
  1. Ages & tempo (click + entered, AI age proxies: TC2 + first Castle-age unit)
  2. TC idle windows (queue sim: vills + Loom + age research, per-age uptime)
  3. Military production idle per building type (k-server queue sim)
  4. Housed-stall suspects (spawn-sim pop vs house cap; heuristic, deaths unseen)
  5. Cancels & unqueues (SPECIAL Unqueue clusters, tech re-clicks)
  6. Rally-point audit (GATHER_POINT events; TC rally present at all?)
  7. Market usage (build time vs first use)
  8. Food ledger (spend by category; the "Castle fund" competition)
  9. Command silences (longest total-input gaps)
 10. Fight micro density (commands by type inside each fight window)
 11. Absences checklist (walls/towers, TC2, blacksmith timing, first farm)

Caveats inherited from AGENTS.md: queue events are requests (not spawns),
research clicks are clicks (not completions; last click wins), deaths are
invisible to the pop sim, and the resource bank is a single 4-resource sum.
"""
import argparse
from collections import defaultdict

from replaylib import load_match, sec, mmss
from extract_full import build_extract

AGE_DUR = {'Feudal': 130, 'Castle': 160, 'Imperial': 190}
TRAIN = {  # seconds; unlisted units default to 22
    'Villager': 25, 'Militia': 21, 'Spearman': 22, 'Skirmisher': 22,
    'Archer': 35, 'Crossbowman': 27, 'Cavalry Archer': 34, 'Scout Cavalry': 30,
    'Knight': 30, 'Camel Rider': 22, 'Battering Ram': 36, 'Mangonel': 46,
    'Scorpion': 30, 'Monk': 51, 'Trade Cart': 51, 'Eagle Scout': 60,
    'Hand Cannoneer': 34, 'Elephant Archer': 32, 'Long Swordsman': 21,
}
BUILDING_OF = {
    'Militia': 'Barracks', 'Man-at-Arms': 'Barracks', 'Long Swordsman': 'Barracks',
    'Spearman': 'Barracks', 'Pikeman': 'Barracks', 'Eagle Scout': 'Barracks',
    'Archer': 'Archery Range', 'Skirmisher': 'Archery Range',
    'Crossbowman': 'Archery Range', 'Cavalry Archer': 'Archery Range',
    'Hand Cannoneer': 'Archery Range', 'Elephant Archer': 'Archery Range',
    'Scout Cavalry': 'Stable', 'Knight': 'Stable', 'Camel Rider': 'Stable',
    'Camel Scout': 'Stable', 'Shrivamsha Rider': 'Stable', 'Battle Elephant': 'Stable',
    'Battering Ram': 'Siege Workshop', 'Mangonel': 'Siege Workshop',
    'Scorpion': 'Siege Workshop', 'Siege Tower': 'Siege Workshop',
    'Monk': 'Monastery', 'Trade Cart': 'Market',
}
BUILD_TIME = {'Barracks': 30, 'Archery Range': 35, 'Stable': 35,
              'Siege Workshop': 40, 'Monastery': 40, 'Market': 60,
              'Town Center': 100, 'House': 25, 'Blacksmith': 40}
FOOD_MILITARY = ('Militia', 'Spearman', 'Skirmisher', 'Scout Cavalry', 'Knight',
                 'Camel Rider', 'Eagle Scout', 'Long Swordsman', 'Pikeman')


def dedup_actions(m, number):
    """The player's actions with POV-duplicate records removed — same two-layer
    rule as extract_full (full-identity set for queue/research/build, adjacent
    byte-identity for everything else)."""
    out, seen, prev_adj = [], set(), None
    for a in m.actions:
        if a.player is None:
            prev_adj = None
            continue
        ty = a.type.name
        pl = a.payload or {}
        adj_key = (a.player.number, ty, a.timestamp, str(pl), str(a.position))
        if ty in ('MAKE', 'DE_QUEUE', 'RESEARCH', 'BUILD'):
            key = (a.player.number, ty, a.timestamp, pl.get('sequence'),
                   pl.get('unit_id'), pl.get('technology_id'),
                   pl.get('building_id'), str(pl.get('object_ids')))
            if key in seen:
                prev_adj = adj_key
                continue
            seen.add(key)
        elif adj_key == prev_adj:
            continue
        prev_adj = adj_key
        if a.player.number == number:
            out.append(a)
    return out


def queue_sim(jobs, opened, end, min_gap=20):
    """Serial single-server queue: jobs = sorted [(t, duration)]. Returns
    (idle_windows, total_idle, busy)."""
    free, windows, idle, busy = opened, [], 0.0, 0.0
    for t, dur in jobs:
        if t > free:
            gap = t - free
            idle += gap
            if gap >= min_gap:
                windows.append((free, t, gap))
            free = t + dur
        else:
            free += dur
        busy += dur
    if free < end:
        idle += end - free
        windows.append((free, end, end - free))
    return windows, idle, busy


def kserver_sim(jobs, openings, end):
    """k parallel servers opening at given times. Returns (idle, capacity)."""
    free = sorted(openings)
    for t, dur in jobs:
        i = min(range(len(free)), key=lambda j: free[j])
        free[i] = max(free[i], t) + dur
    capacity = sum(end - o for o in openings if o < end)
    busy = sum(dur for _, dur in jobs)
    return max(0.0, capacity - busy), capacity


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('replay')
    ap.add_argument('--me', default='Olive')
    args = ap.parse_args()

    m = load_match(args.replay)
    ext = build_extract(m, args.replay)
    me = next(p for p in ext['players'] if p['name'] == args.me)
    n = me['number']
    acts = dedup_actions(m, n)
    end = me['resign'] or ext['duration']
    names = {p['number']: p['name'] for p in ext['players']}

    print(f"AUDIT: {args.me} ({me['civ']}) — {ext['map']}, {mmss(ext['duration'])}, "
          f"{'WON' if me['winner'] else 'lost'}"
          f"{' (resigned ' + mmss(me['resign']) + ')' if me['resign'] else ''}")

    # 1 ─ ages & tempo
    print("\n[1] AGES (click → entered)")
    for k, t in me['ages'].items():
        print(f"  {k:9} {mmss(t)} → {mmss(t + AGE_DUR[k])}")
    for p in ext['players']:
        if p['human']:
            continue
        tcs = [b[2] for b in p['builds'] if b[4] == 'Town Center']
        firsts = {}
        for t, uid, u, amt in p['prod_events']:
            firsts.setdefault(u, t)
        castle_units = [(u, t) for u, t in firsts.items() if BUILDING_OF.get(u) in
                        ('Stable', 'Siege Workshop', 'Monastery') or
                        u in ('Knight', 'Shrivamsha Rider', 'Battering Ram', 'Monk')]
        proxy = min([t for _, t in castle_units] + tcs[:1] or [0])
        print(f"  AI {p['name']}: TC2 {mmss(tcs[0]) if tcs else '—'}, "
              f"Castle proxy ≈{mmss(proxy) if proxy else '—'} "
              f"({', '.join(f'{u} {mmss(t)}' for u, t in sorted(castle_units, key=lambda x: x[1])[:3])})")

    # 2 ─ TC idle
    jobs = []
    for a in acts:
        t = sec(a.timestamp)
        if a.type.name == 'DE_QUEUE' and (a.payload or {}).get('unit') == 'Villager':
            jobs += [(t, 25)] * a.payload.get('amount', 1)
    for tech, dur in [('Loom', 25)] + list(AGE_DUR.items()):
        rec = me['research'].get(tech)
        t = rec['t'] if rec else me['ages'].get(tech)
        if t is not None:
            jobs.append((t, dur))
    jobs.sort()
    windows, idle, _ = queue_sim(jobs, 0, end)
    print(f"\n[2] TC IDLE (queue sim incl. Loom+ages): {int(idle)}s = {100 * idle / end:.0f}% of game")
    for a_, b_, g in windows:
        print(f"  {mmss(a_)} → {mmss(b_)}  ({int(g)}s)")
    marks = [(0, me['ages'].get('Feudal'), 'Dark'),
             (me['ages'].get('Feudal'), me['ages'].get('Castle'), 'Feudal'),
             (me['ages'].get('Castle'), me['ages'].get('Imperial') or end, 'Castle')]
    for a_, b_, label in marks:
        if a_ is None or b_ is None or b_ <= a_:
            continue
        vq = sum(1 for t, d in jobs if d == 25 and a_ < t <= b_)
        print(f"  uptime {label:7}: {vq} vills / {int(b_ - a_)}s = {100 * vq * 25 / (b_ - a_):.0f}%")

    # 3 ─ military production idle
    built = defaultdict(list)
    for x, y, t, bid, b in me['builds']:
        built[b].append(t + BUILD_TIME.get(b, 35))
    byb = defaultdict(list)
    for a in acts:
        if a.type.name in ('DE_QUEUE', 'MAKE'):
            u = (a.payload or {}).get('unit')
            b = BUILDING_OF.get(u)
            if b:
                byb[b] += [(sec(a.timestamp), TRAIN.get(u, 22))] * a.payload.get('amount', 1)
    print("\n[3] MILITARY PRODUCTION IDLE")
    for b, jobs_b in sorted(byb.items()):
        openings = built.get(b, [])
        if not openings:
            print(f"  {b}: {len(jobs_b)} units queued but no build recorded (pre-game/converted?)")
            continue
        jobs_b.sort()
        if len(openings) == 1:
            w, idle_b, _ = queue_sim(jobs_b, openings[0], end, min_gap=45)
            pct = 100 * idle_b / (end - openings[0])
            print(f"  {b} (x1, up {mmss(openings[0])}): idle {int(idle_b)}s = {pct:.0f}%")
            for a_, b_, g in w:
                print(f"    {mmss(a_)} → {mmss(b_)}  ({int(g)}s)")
        else:
            idle_b, cap = kserver_sim(jobs_b, openings, end)
            print(f"  {b} (x{len(openings)}, up {', '.join(mmss(o) for o in openings)}): "
                  f"combined idle {int(idle_b)}s = {100 * idle_b / cap:.0f}% of capacity")

    # 4 ─ housed suspects (heuristic: spawn-sim pop vs cap; deaths invisible)
    houses = sorted(t for x, y, t, bid, b in me['builds'] if b == 'House')
    tc_done = sorted(t for x, y, t, bid, b in me['builds'] if b == 'Town Center')
    spawns = sorted((t, 1) for t, d in jobs if d == 25)
    army = sorted((sec(a.timestamp), a.payload.get('amount', 1)) for a in acts
                  if a.type.name in ('DE_QUEUE', 'MAKE')
                  and (a.payload or {}).get('unit') not in (None, 'Villager'))
    print("\n[4] HOUSED-STALL SUSPECTS (queued pop ≥ cap; deaths invisible, so only "
          "ONSETS are meaningful — late-game flags just mean units have died)")
    over, onset = False, None
    for t in range(60, int(end), 30):
        cap = 5 + 5 * sum(1 for h in houses if h + 25 <= t) + 5 * sum(1 for h in tc_done if h + 100 <= t)
        pop = sum(a for tt, a in spawns if tt <= t) + sum(a for tt, a in army if tt <= t) + 4
        if pop >= cap and not over:
            over, onset = True, (t, pop, cap)
        elif pop < cap and over:
            print(f"  ~{mmss(onset[0])} → ~{mmss(t)}: queued-pop {onset[1]} ≥ cap {onset[2]}")
            over = False
    if over:
        print(f"  ~{mmss(onset[0])} → end: queued-pop {onset[1]} ≥ cap {onset[2]}")
    elif onset is None:
        print("  none")

    # 5 ─ cancels & unqueues
    print("\n[5] CANCELS")
    unq = [a for a in acts if a.type.name == 'SPECIAL' and (a.payload or {}).get('order') == 'Unqueue']
    for a in unq:
        print(f"  {mmss(sec(a.timestamp))} Unqueue (slot {a.payload.get('slot_id')})")
    reclicks = {k: v for k, v in me['research'].items() if v['clicks'] > 1}
    for k, v in reclicks.items():
        print(f"  tech re-clicked: {k} x{v['clicks']} (earlier click was cancelled), last {mmss(v['t'])}")
    if not unq and not reclicks:
        print("  none")

    # 6 ─ rally audit
    print("\n[6] RALLY POINTS (GATHER_POINT)")
    gps = [a for a in acts if a.type.name == 'GATHER_POINT']
    tc_ids = set()
    for a in acts:
        if a.type.name == 'DE_QUEUE' and (a.payload or {}).get('unit') == 'Villager':
            tc_ids.update(a.payload.get('object_ids') or [])
    tc_rallies = [a for a in gps if set((a.payload or {}).get('object_ids') or []) & tc_ids]
    for a in gps:
        src = 'TC' if set((a.payload or {}).get('object_ids') or []) & tc_ids else 'other bld'
        tgt = (a.payload or {}).get('target_id', -1)
        where = f"onto object {tgt}" if tgt != -1 else (f"to ground {a.position}" if a.position else "cleared")
        print(f"  {mmss(sec(a.timestamp))} {src} rally {where}")
    print(f"  TC rally events: {len(tc_rallies)}" + ("  ⚠ NEVER SET" if not tc_rallies else ""))

    # 7 ─ market
    mkt_built = [t for x, y, t, bid, b in me['builds'] if b == 'Market']
    print("\n[7] MARKET")
    if me['market']:
        first = me['market'][0]
        for t, ty, res, amt in me['market']:
            print(f"  {mmss(t)} {ty} {amt} {res}")
        if mkt_built:
            print(f"  built {mmss(mkt_built[0])}; first use {mmss(first[0])} "
                  f"({int((first[0] - mkt_built[0]) / 60)}min later)")
    else:
        print(f"  built {mmss(mkt_built[0])} but NEVER USED" if mkt_built else "  no market")

    # 8 ─ food ledger
    cats = defaultdict(int)
    for t, kind, name, f, w, g, s in me['spend_events']:
        if f:
            key = ('Villagers' if name == 'Villager'
                   else 'Ages' if name in AGE_DUR or name == 'Feudal Age'
                   else 'Military' if kind == 'unit' else 'Techs')
            cats[key] += f
    print("\n[8] FOOD LEDGER (where the Castle fund went)")
    for k, v in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {k:10} {v}")
    milf = sum(f for t, k, u, f, w, g, s in me['spend_events'] if u in FOOD_MILITARY and f)
    print(f"  (food-military detail: {milf}f ≈ {milf / 800:.1f} Castle Ages)")

    # 9 ─ command silences
    ts = sorted(sec(a.timestamp) for a in acts)
    gaps = sorted(((ts[i], ts[i + 1] - ts[i]) for i in range(len(ts) - 1)),
                  key=lambda g: -g[1])[:6]
    print("\n[9] LONGEST INPUT SILENCES")
    for t, g in gaps:
        print(f"  {mmss(t)} → {mmss(t + g)}  ({int(g)}s)")

    # 10 ─ fight micro
    print("\n[10] FIGHT MICRO (commands inside each fight window)")
    for w in ext['fight_windows']:
        inside = [a for a in acts if w['t0'] - 15 <= sec(a.timestamp) <= w['t1'] + 15]
        byty = defaultdict(int)
        for a in inside:
            byty[a.type.name] += 1
        losses = {names[int(k)]: v for k, v in w['losses'].items()}
        print(f"  {mmss(w['t0'])}–{mmss(w['t1'])} {losses}: {len(inside)} cmds {dict(byty)}")

    # 11 ─ absences checklist
    print("\n[11] CHECKLIST")
    bcount = defaultdict(int)
    for x, y, t, bid, b in me['builds']:
        bcount[b] += 1
    walls = sum(v for k, v in bcount.items() if 'Wall' in k or 'Gate' in k)
    towers = sum(v for k, v in bcount.items() if 'Tower' in k)
    farms = sorted(t for x, y, t, bid, b in me['builds'] if b == 'Farm')
    smith = [t for x, y, t, bid, b in me['builds'] if b == 'Blacksmith']
    smith20 = sum(1 for k, v in me['research'].items()
                  if v['t'] <= 1200 and k not in ('Loom', 'Wheelbarrow', 'Town Watch')
                  and any(w in k for w in ('Forging', 'Casting', 'Furnace', 'Armor', 'Fletching',
                                           'Bodkin', 'Bracer', 'Mail', 'Plate', 'Scale', 'Barding',
                                           'Padded', 'Leather', 'Ring')))
    checks = [
        (walls > 0, f"walls/gates built: {walls}"),
        (towers > 0, f"towers built: {towers}"),
        (bcount.get('Town Center', 0) > 0, f"extra TCs: {bcount.get('Town Center', 0)}"),
        (bool(farms) and farms[0] <= 600, f"first farm: {mmss(farms[0]) if farms else '—'} (target ≤10:00)"),
        (bool(smith) and smith[0] <= 840, f"blacksmith: {mmss(smith[0]) if smith else '—'} (target ≤14:00)"),
        (smith20 >= 4, f"smith-type techs by 20:00: {smith20} (target ≥4)"),
        (bool(tc_rallies), "TC rally point set"),
    ]
    for ok, txt in checks:
        print(f"  {'✓' if ok else '✗'} {txt}")


if __name__ == '__main__':
    main()
