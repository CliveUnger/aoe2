#!/usr/bin/env python3
"""One front door for the toolkit: `aoe2 <command> [args...]`.

Thin dispatcher — each subcommand runs the corresponding module unchanged
(they all remain directly runnable too). Anywhere a replay path is expected,
the literal word `latest` expands to the newest .aoe2record in the savegame
directory (override with AOE2_SAVEGAME_DIR).

  aoe2 analyze  <replay>              human-readable game summary
  aoe2 parse    <replay>              JSON header dump
  aoe2 debrief  <replay> [--me NAME]  full analysis JSON
  aoe2 extract  <replay> <out.json>   superset extractor
  aoe2 ledger   <replays...>          per-villager task/idle ledger
  aoe2 audit    <replay> [--me NAME]  granular slip-up ledger
  aoe2 campaign <out.html> <replays...> [opts]   N-game squad report
  aoe2 latest   [N]                   print newest replay path(s)
"""
import glob
import os
import runpy
import sys

SAVEGAME_DIR = os.environ.get('AOE2_SAVEGAME_DIR', os.path.expanduser(
    '~/Library/Application Support/Feral Interactive/Age Of Empires II/VFS/'
    'User/Games/Age of Empires 2 DE/76561198081802645/savegame'))

COMMANDS = {'analyze': 'analyze', 'parse': 'parse', 'debrief': 'debrief',
            'extract': 'extract_full', 'ledger': 'vill_ledger', 'audit': 'audit'}


def latest(n=1):
    recs = glob.glob(os.path.join(SAVEGAME_DIR, '*.aoe2record'))
    recs.sort(key=os.path.getmtime, reverse=True)
    return recs[:n]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.strip())
        return
    cmd, rest = args[0], args[1:]

    if cmd == 'latest':
        found = latest(int(rest[0]) if rest else 1)
        if not found:
            sys.exit(f'no replays under {SAVEGAME_DIR}')
        print('\n'.join(found))
        return

    rest = [latest()[0] if a == 'latest' else a for a in rest]

    if cmd == 'campaign':
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'reports', 'make_campaign.py')
        sys.argv = [path] + rest
        runpy.run_path(path, run_name='__main__')
        return

    mod = COMMANDS.get(cmd)
    if not mod:
        sys.exit(f"unknown command {cmd!r} — try one of: "
                 f"{', '.join([*COMMANDS, 'campaign', 'latest'])}")
    sys.argv = [mod] + rest
    runpy.run_module(mod, run_name='__main__')


if __name__ == '__main__':
    main()
