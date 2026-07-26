#!/usr/bin/env python3
"""Per-villager task ledger v2 — validated model.

Fixes over v1: TC id from DE_QUEUE object_ids; rally = GATHER_POINT on that
TC with a resource target; herdable/hunt gather = indefinite (DE auto-
continues to next carcass/herdable in range); obj-target ORDERs within 2.5
tiles of an own Farm build = farm task (villager); birth idle = order-
preserving match of villager first-command times to TC-sim birth times
(only for players with no resource rally — rally'd vills auto-task);
research ledger applies the last-click cancel rule (a later re-click of the
same tech proves the earlier click was cancelled).
Idle numbers are LOWER-BOUND estimates; cancels/garrisons invisible.
"""
import sys, json, logging, os
from collections import defaultdict, Counter

logging.disable(logging.CRITICAL)
from mgz.model import parse_match

TT = json.load(open(os.path.expanduser('~/dev/aoe2/data/techtree.json')))
BUILD_TIME = {int(k): v.get('TrainTime', 30) for k, v in TT['data']['Building'].items()}
TECH_TIME = {int(k): v.get('ResearchTime', 30) for k, v in TT['data']['Tech'].items()}
DROPSITES = {'Lumber Camp', 'Mill', 'Mining Camp', 'Dock', 'Farm'}
VILL_T = 25


def res_type(name):
    if not name:
        return None
    if name.startswith(('Tree', 'Stump')):
        return 'wood'
    if name == 'Gold Mine':
        return 'gold'
    if name == 'Stone Mine':
        return 'stone'
    if 'Forage' in name or name.startswith('Bush'):
        return 'forage'
    if any(a in name for a in ('Cow', 'Boar', 'Deer', 'Sheep', 'Goat', 'Ostrich', 'Zebra')):
        return 'hunt'
    return None


def sec(td):
    return round(td.total_seconds())


def mmss(s):
    return f'{int(s)//60}:{int(s)%60:02d}'


def analyze(replay, out_label, extract_json):
    m = parse_match(open(replay, 'rb'))
    gaia = {o.instance_id: (o.name, o.position) for o in m.gaia}
    ex = json.load(open(extract_json))
    ts_by_name = {q['name']: q['ts'] for q in ex['players']}
    fights = ex['fight_windows']
    print(f'\n{"="*94}\n{out_label}')

    for p in m.players:
        if not p.name:
            continue
        start_vills = [o.instance_id for o in p.objects if o.name and 'Villager' in o.name]
        scout_ids = {o.instance_id for o in p.objects if o.name and 'Scout' in o.name}

        ages = {}
        all_research = defaultdict(list)  # (bld,tech) full-game clicks for cancel rule
        for a in m.actions:
            if a.player is p and a.type.name == 'RESEARCH':
                pl = a.payload or {}
                tid = pl.get('technology_id')
                if tid in (101, 102, 103):
                    ages.setdefault({101: 'Feudal', 102: 'Castle', 103: 'Imperial'}[tid], sec(a.timestamp))
                elif pl.get('object_ids'):
                    all_research[tid].append((sec(a.timestamp), pl['object_ids'][0], pl.get('technology')))
        H = ages.get('Castle', 30 * 60) + 120

        # pass 1: TC ids + farm positions
        tc_ids, farm_pos = set(), []
        for a in m.actions:
            if a.player is not p:
                continue
            ty, pl, t = a.type.name, a.payload or {}, sec(a.timestamp)
            if ty == 'DE_QUEUE' and pl.get('unit') == 'Villager':
                tc_ids.update(pl.get('object_ids') or [])
            if ty == 'BUILD' and pl.get('building') == 'Farm' and a.position and t <= H:
                farm_pos.append((a.position.x, a.position.y))

        def near_farm(pos):
            return pos and any((pos.x - x) ** 2 + (pos.y - y) ** 2 <= 6.25 for x, y in farm_pos)

        # pass 2: commands
        seen = set()
        cmds = defaultdict(list)
        rallies = []
        vq = []
        for a in m.actions:
            if a.player is not p or sec(a.timestamp) > H:
                continue
            ty, pl, t = a.type.name, a.payload or {}, sec(a.timestamp)
            if ty in ('MAKE', 'DE_QUEUE', 'RESEARCH', 'BUILD'):
                key = (ty, a.timestamp, pl.get('sequence'), str(pl.get('object_ids')))
                if key in seen:
                    continue
                seen.add(key)
            if ty == 'DE_QUEUE' and pl.get('unit') == 'Villager':
                vq.append((t, pl.get('amount', 1)))
            elif ty == 'BUILD' and pl.get('building'):
                oids = pl.get('object_ids') or []
                for o in oids:
                    cmds[o].append((t, 'build', pl['building'], (len(oids), pl.get('building_id'))))
            elif ty == 'ORDER':
                tid = pl.get('target_id')
                oids = pl.get('object_ids') or []
                g = gaia.get(tid)
                r = res_type(g[0]) if g else None
                if r:
                    for o in oids:
                        if o not in scout_ids:
                            cmds[o].append((t, 'gather', r, None))
                elif tid not in (4294967295, -1, None) and near_farm(a.position):
                    for o in oids:
                        cmds[o].append((t, 'gather', 'farm', None))
                elif tid in (4294967295, -1, None) and a.position:
                    for o in oids:
                        cmds[o].append((t, 'ground', None, None))
                elif tid in tc_ids:
                    for o in oids:
                        cmds[o].append((t, 'tc', None, None))  # garrison/drop-off: busy, not idle
                else:
                    for o in oids:
                        cmds[o].append((t, 'obj', None, None))
            elif ty == 'MOVE':
                for o in (pl.get('object_ids') or []):
                    cmds[o].append((t, 'move', None, None))
            elif ty == 'GATHER_POINT' and set(pl.get('object_ids') or []) & tc_ids:
                g = gaia.get(pl.get('target_id'))
                rallies.append((t, res_type(g[0]) if g else None))

        vill_ids = set(start_vills)
        for o, cl in cmds.items():
            if any(k in ('build', 'gather') for _, k, _, _ in cl):
                vill_ids.add(o)
        new_ids = sorted(v for v in vill_ids if v not in start_vills)

        # births via TC sim (vills + loom + ages serial)
        blockers = []
        loom_clicks = all_research.get(22, [])
        if loom_clicks:
            lt = max(t for t, b, n in loom_clicks)  # last click = the real one
            if lt <= H:
                blockers.append((lt, TECH_TIME.get(22, 25)))
        for ag, tid in (('Feudal', 101), ('Castle', 102)):
            if ag in ages:
                blockers.append((ages[ag], TECH_TIME[tid]))
        allj = sorted([(t, VILL_T, 'v') for t, n in sorted(vq) for _ in range(n)] +
                      [(t, d, 'b') for t, d in blockers])
        tf, births = 0, []
        for arr, d, k in allj:
            tf = max(tf, arr) + d
            if k == 'v':
                births.append(tf)

        res_rally = any(r for _, r in rallies)
        # birth idle: only meaningful with no resource rally
        birth_idle, first_cmds = 0, sorted(min(t for t, *_ in cmds[v]) for v in new_ids)
        if not res_rally:
            for b, f in zip(births, first_cmds):
                if f > b + 5:
                    birth_idle += min(f, H) - b - 5

        # timeseries lookup for tail corroboration
        ts = ts_by_name.get(p.name, [])

        def obj_delta(t0, t1):
            a = [r[1] for r in ts if r[0] <= t0]
            b = [r[1] for r in ts if r[0] <= t1]
            return (b[-1] - a[-1]) if a and b else None

        def in_fight(t):
            return any(w['t0'] - 30 <= t <= w['t1'] + 30 for w in fights)

        idle = Counter()
        stories, tails = [], []
        census = Counter()
        for v in sorted(vill_ids):
            cl = sorted(cmds.get(v, []))
            vidle, busy_end, details = 0, None, []

            def window(end, nxt, reason):
                nonlocal vidle
                gap = nxt[0] - end
                if gap <= 20:
                    return
                if nxt[1] == 'END':
                    # tail: villager never commanded again — idle OR dead
                    d = obj_delta(end - 30, end + 90)
                    tails.append((v, end, gap - 20, reason,
                                  'in-fight' if in_fight(end) else '',
                                  d))
                else:
                    vidle += gap - 20
                    details.append(f'{mmss(end)} +{int(gap-20)}s after {reason}')

            for (t, kind, d1, d2), nxt in zip(cl, cl[1:] + [(H, 'END', None, None)]):
                start = t if busy_end in (None, 'inf') else max(t, busy_end)
                if kind == 'build':
                    n, bid = d2
                    dur = BUILD_TIME.get(bid, 30) * 3 / (2 + n)
                    end = start + dur
                    census['build'] += 1
                    if d1 in DROPSITES:
                        busy_end = 'inf'
                    else:
                        busy_end = end
                        window(end, nxt, d1)
                elif kind == 'gather':
                    census[d1] += 1
                    busy_end = 'inf'
                elif kind in ('ground', 'move'):
                    end = start + 20
                    window(end, nxt, 'move')
                    busy_end = end
                else:
                    busy_end = 'inf'  # tc/obj/unknown: assume busy
            if vidle > 0:
                idle['task'] += vidle
                stories.append((vidle, v, details[:3]))

        queued = sum(n for _, n in vq)
        unacc = queued + len(start_vills) - len(vill_ids) - sum(1 for o, cl in cmds.items()
                    if o not in vill_ids and any(k == 'obj' for _, k, _, _ in cl))
        cc = ages.get('Castle')
        print(f'\n--- {p.name}  (to {mmss(H)}; Castle click {mmss(cc) if cc else "none"})')
        print(f'  villagers: {queued} queued +{len(start_vills)} start; {len(vill_ids)} task-classified ids; '
              f'obj-only ids (military/untracked): {sum(1 for o,cl in cmds.items() if o not in vill_ids and any(k=="obj" for _,k,_,_ in cl))}')
        print(f'  TC rally: {"YES — " + str(sum(1 for _, r in rallies if r)) + " resource rallies" if res_rally else "NEVER set to a resource"}')
        print(f'  CONFIRMED idle (villager provably alive after window): birth {int(birth_idle)}s' +
              (' (n/a — rally covers births)' if res_rally else '') +
              f' + mid-timeline {int(idle["task"])}s = {int(birth_idle + idle["task"])}s')
        tail_tot = sum(g for _, _, g, _, _, _ in tails)
        print(f'  UNRESOLVED tails (no command ever again): {len(tails)} windows, {int(tail_tot)}s')
        for v, end, gap, reason, fight, d in sorted(tails, key=lambda x: -x[2])[:6]:
            verdict = 'LIKELY DEAD' if (fight or (d is not None and d < 0)) else 'likely idle'
            print(f'    vill {v} silent from {mmss(end)} ({int(gap)}s, after {reason}) '
                  f'{fight} objΔ={d} -> {verdict}')
        print(f'  task census: ' + ', '.join(f'{k}:{v}' for k, v in census.most_common()))
        for vidle, v, det in sorted(stories, reverse=True)[:4]:
            print(f'    vill {v}: {int(vidle)}s — ' + '; '.join(det))
        # research ledger w/ cancel rule, per building
        by_bld = defaultdict(list)
        for tid, clicks in all_research.items():
            last_t = max(t for t, b, n in clicks)
            for t, b, n in clicks:
                if t <= H:
                    by_bld[b].append((t, tid, n, t < last_t))
        for bid, lst in sorted(by_bld.items(), key=lambda kv: min(x[0] for x in kv[1])):
            lab = 'TC' if bid in tc_ids else f'b{bid}'
            end, parts = 0, []
            for t, tid, n, cancelled in sorted(lst):
                if cancelled:
                    parts.append(f'{n} clk {mmss(t)} CANCELLED')
                    continue
                st = max(t, end)
                end = st + TECH_TIME.get(tid, 30)
                parts.append(f'{n} {mmss(t)}' + (f'→{mmss(st)}' if st - t > 20 else '') + f' done {mmss(end)}')
            print(f'  research @{lab}: ' + ' | '.join(parts))


SAVE = os.path.expanduser('~/Library/Application Support/Feral Interactive/Age Of Empires II/VFS/User/Games/Age of Empires 2 DE/76561198081802645/savegame')
FILES = [('G1', '144944', 'g1'), ('G2', '151015', 'g2'), ('G3', '165218', 'g3'), ('G4', '172654', 'g4')]
which = sys.argv[1:] or ['G1', 'G2', 'G3', 'G4']
for gl, ts, gj in FILES:
    if gl in which:
        analyze(f'{SAVE}/MP Replay v101.103.48987.0 @2026.07.25 {ts} (1).aoe2record', gl,
                f'/tmp/aoe2-today/{gj}.json')
