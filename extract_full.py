#!/usr/bin/env python3
"""Extended per-game extractor (superset of debrief.py's data layer).

Mirrors the audited debrief.py logic (POV dedup — tightened to use the
`sequence` field; last-click research; click->entered ages) and adds:
per-resource spending reconstruction (techtree costs by id), villager/eco
timeline, TC-idle proxy, all-player trails + build footprints, market
SELL/BUY, trade carts, command-rate curves, resign times, chat, fight
(gross-attrition) windows with capped merges + endgame exclusion.

Usage: extract_full.py <replay> <out.json>

Cost tables come from data/techtree.json (SiegeEngineers/aoe2techtree
data/data.json) — refresh it after game balance patches, never hand-edit.
"""
import sys, json, logging, os
from collections import Counter, defaultdict

logging.disable(logging.CRITICAL)
from mgz.model import parse_match

TECHTREE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'techtree.json')))
UNITS = {int(k): v for k, v in TECHTREE['data']['Unit'].items()}
TECHS = {int(k): v for k, v in TECHTREE['data']['Tech'].items()}
BUILDINGS = {int(k): v for k, v in TECHTREE['data']['Building'].items()}
CIV_OK = {c: {'Unit': set(v['Unit']), 'Tech': set(v['Tech']), 'Building': set(v['Building'])}
          for c, v in TECHTREE['civs'].items()}

AGE_TECH = {101: 'Feudal', 102: 'Castle', 103: 'Imperial'}
RES = ('Food', 'Wood', 'Gold', 'Stone')


def sec(td):
    return round(td.total_seconds())


def cost_of(table, oid):
    rec = table.get(oid)
    if not rec:
        return None
    c = rec.get('Cost', {})
    return {r: c.get(r, 0) for r in RES}


def ok_pos(pos, dim):
    return pos and not (pos.x == 0 and pos.y == 0) and 0 <= pos.x <= dim and 0 <= pos.y <= dim


def main():
    replay, outpath = sys.argv[1], sys.argv[2]
    m = parse_match(open(replay, 'rb'))
    dim = m.map.dimension
    dur = sec(m.duration)

    civ_by_n = {p.number: p.civilization for p in m.players}
    name_by_n = {p.number: (p.name or f'{p.civilization} AI') for p in m.players}
    human = {p.number for p in m.players if p.name}

    prod = defaultdict(Counter)            # n -> unit name -> count (civ-valid only)
    prod_events = defaultdict(list)        # n -> [[t, unit_id, unit, amount]]
    civ_invalid = defaultdict(Counter)     # dropped queue requests
    ages = defaultdict(dict)
    research_clicks = defaultdict(dict)    # n -> tech name -> {'t': last click, 'id': id, 'clicks': k}
    builds = defaultdict(list)             # n -> [[x,y,t,building_id,building]]
    trails = defaultdict(list)             # n -> [[x,y,t,is_attack]]  (all players, humans matter)
    market = defaultdict(list)             # n -> [[t, 'SELL'/'BUY', resource, amount]]
    resigns = {}
    deletes = defaultdict(int)
    cmd_minutes = defaultdict(Counter)     # n -> minute -> command count (human-attributable, excl AI_ORDER/GAME)
    seen = set()

    for a in m.actions:
        if a.player is None:
            continue
        n = a.player.number
        ty = a.type.name
        pl = a.payload or {}
        if ty not in ('AI_ORDER', 'GAME'):
            cmd_minutes[n][sec(a.timestamp) // 60] += 1
        if ty in ('MAKE', 'DE_QUEUE', 'RESEARCH', 'BUILD'):
            key = (n, ty, a.timestamp, pl.get('sequence'), pl.get('unit_id'),
                   pl.get('technology_id'), pl.get('building_id'), str(pl.get('object_ids')))
            if key in seen:
                continue
            seen.add(key)
        t = sec(a.timestamp)
        if ty in ('MAKE', 'DE_QUEUE') and pl.get('unit'):
            uid = pl.get('unit_id')
            amt = pl.get('amount', 1) if ty == 'DE_QUEUE' else 1
            prod[n][pl['unit']] += amt
            prod_events[n].append([t, uid, pl['unit'], amt])
        elif ty == 'RESEARCH':
            tid, tech = pl.get('technology_id'), pl.get('technology')
            if tid in AGE_TECH:
                ages[n].setdefault(AGE_TECH[tid], t)
            elif tech:
                rec = research_clicks[n].setdefault(tech, {'id': tid, 'clicks': 0})
                rec['t'] = t
                rec['clicks'] += 1
        elif ty == 'BUILD' and pl.get('building'):
            x = round(a.position.x, 1) if ok_pos(a.position, dim) else None
            y = round(a.position.y, 1) if ok_pos(a.position, dim) else None
            builds[n].append([x, y, t, pl.get('building_id'), pl['building']])
        elif ty in ('SELL', 'BUY') and pl.get('resource'):
            market[n].append([t, ty, pl['resource'], pl.get('amount', 0)])
        elif ty == 'RESIGN':
            resigns.setdefault(n, t)
        elif ty == 'DELETE':
            deletes[n] += 1
        if ty in ('MOVE', 'ORDER') and ok_pos(a.position, dim):
            trails[n].append([round(a.position.x, 1), round(a.position.y, 1), t,
                              1 if ty == 'ORDER' else 0])

    # civ-invalid junk queues: unit not in the civ's techtree list AND queued
    # <=2 total (the known client-side quirk, e.g. a Mongol Camel Scout).
    # Larger not-in-list counts are line units the techtree lists under a
    # later id (e.g. Hindustanis Camel Scout) — kept, flagged, not dropped.
    for n in list(prod.keys()):
        civ = civ_by_n[n]
        if civ not in CIV_OK:
            continue
        for uname in list(prod[n]):
            uids = {e[1] for e in prod_events[n] if e[2] == uname}
            if uids and all(u is not None and u in UNITS and u not in CIV_OK[civ]['Unit'] for u in uids):
                if prod[n][uname] <= 2:
                    civ_invalid[n][uname] += prod[n].pop(uname)
                    prod_events[n] = [e for e in prod_events[n] if e[2] != uname]

    # ---- spending reconstruction (per-resource, cumulative events) ----
    # units at queue time, buildings at build-command time, techs at LAST click.
    # Estimate: cancels invisible; queue requests can exceed spawns.
    spend_events = defaultdict(list)  # n -> [[t, kind, name, F, W, G, S]]
    for n in prod_events:
        for t, uid, uname, amt in prod_events[n]:
            c = cost_of(UNITS, uid)
            if c:
                spend_events[n].append([t, 'unit', uname,
                                        c['Food'] * amt, c['Wood'] * amt, c['Gold'] * amt, c['Stone'] * amt])
    for n in builds:
        for x, y, t, bid, bname in builds[n]:
            c = cost_of(BUILDINGS, bid)
            if c:
                spend_events[n].append([t, 'building', bname, c['Food'], c['Wood'], c['Gold'], c['Stone']])
    for n in research_clicks:
        for tech, rec in research_clicks[n].items():
            c = cost_of(TECHS, rec.get('id'))
            if c:
                spend_events[n].append([rec['t'], 'tech', tech, c['Food'], c['Wood'], c['Gold'], c['Stone']])
    for n in ages:
        for age, t in ages[n].items():
            tid = {v: k for k, v in AGE_TECH.items()}[age]
            c = cost_of(TECHS, tid)
            if c:
                spend_events[n].append([t, 'age', age, c['Food'], c['Wood'], c['Gold'], c['Stone']])
    for n in spend_events:
        spend_events[n].sort()

    # ---- fight (gross-attrition) windows from total_objects deltas ----
    # per-sample negative deltas -> events; merge gaps<=60s; cap window 240s;
    # drop windows ending within 60s of game end (base-razing wipe).
    loss_events = []  # [t, n, delta]
    for p in m.players:
        rows = [[sec(r.timestamp), r.total_objects] for r in p.timeseries]
        for (t0, o0), (t1, o1) in zip(rows, rows[1:]):
            d = o1 - o0
            if d <= -3:
                loss_events.append([t1, p.number, d])
    loss_events.sort()
    windows = []
    for t, n, d in loss_events:
        if windows and t - windows[-1]['t1'] <= 60 and t - windows[-1]['t0'] <= 240:
            w = windows[-1]
            w['t1'] = t
            w['losses'][str(n)] = w['losses'].get(str(n), 0) + d
        else:
            windows.append({'t0': t, 't1': t, 'losses': {str(n): d}})
    windows = [w for w in windows if w['t1'] < dur - 60]

    players = []
    for p in m.players:
        n = p.number
        players.append({
            'number': n, 'name': name_by_n[n], 'civ': p.civilization,
            'winner': p.winner, 'team': p.team_id, 'eapm': p.eapm,
            'human': n in human,
            'start': {'x': p.position.x, 'y': p.position.y},
            'ages': ages[n],
            'prod': dict(prod[n].most_common()),
            'prod_events': prod_events[n],
            'civ_invalid_dropped': dict(civ_invalid[n]),
            'research': {k: v for k, v in sorted(research_clicks[n].items(), key=lambda kv: kv[1]['t'])},
            'builds': builds[n],
            'market': market[n],
            'deletes': deletes[n],
            'resign': resigns.get(n),
            'cmd_minutes': dict(cmd_minutes[n]),
            'spend_events': spend_events[n],
            'ts': [[sec(r.timestamp), r.total_objects, r.total_resources] for r in p.timeseries],
        })

    out = {
        'file': replay, 'map': m.map.name, 'dim': dim, 'duration': dur,
        'completed': m.completed,
        'players': players,
        'trails': {str(k): v for k, v in trails.items() if k in human},
        'fight_windows': windows,
        'chat': [{'t': sec(c.timestamp) if c.timestamp else None,
                  'player': getattr(c.player, 'name', None) or str(c.player), 'msg': c.message}
                 for c in m.chat],
    }
    json.dump(out, open(outpath, 'w'), separators=(',', ':'))
    print(f'{outpath}: {dur//60}min, windows={len(windows)}, '
          f'civ_invalid={ {name_by_n[n]: dict(c) for n, c in civ_invalid.items()} }')


if __name__ == '__main__':
    main()
