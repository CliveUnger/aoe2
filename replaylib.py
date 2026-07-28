#!/usr/bin/env python3
"""Shared replay loading for the analysis tools (analyze/debrief/extract_full/
vill_ledger/make_campaign).

Two speedups over calling mgz.model.parse_match directly:

1. gc_paused(): Python's cyclic GC makes a cold parse ~6x slower (measured
   3.5s -> 0.6s on a 99-min replay). parse_match allocates ~1M objects that
   all survive, so every threshold-triggered collection rescans a growing
   heap for garbage that isn't there. One gc.collect() afterwards costs
   ~0.04s, so pausing loses nothing.

2. load_match(): pickle cache of the parsed Match in data/match_cache/,
   keyed on replay identity (mtime+size) AND the aoc-mgz checkout commit —
   editing the parser invalidates every cached parse. Warm loads are ~0.3s
   vs ~0.6s gc-paused parse (vs ~3.5s status quo ante).

The cached Match is bit-for-bit the parse_match result except m.hash, which
is normalized from a live _hashlib.HASH (unpicklable) to its hexdigest —
the str the Match dataclass declares anyway. No repo tool reads m.hash.
"""
import gc
import logging
import os
import pickle
from contextlib import contextmanager
from hashlib import sha1


def sec(td):
    """Whole seconds from a timedelta."""
    return round(td.total_seconds())


def mmss(x):
    """M:SS from seconds (int/float) or a timedelta."""
    s = round(x.total_seconds()) if hasattr(x, 'total_seconds') else int(x)
    return f'{s // 60}:{s % 60:02d}'


def hms(td, none='?'):
    """H:MM:SS from a timedelta, `none` when td is None."""
    return str(td).split('.')[0] if td is not None else none

logging.disable(logging.CRITICAL)
from mgz.model import parse_match  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, 'data', 'match_cache')
CACHE_VER = 1


@contextmanager
def gc_paused():
    """Cyclic GC off for a bulk-allocation phase (parse or unpickle)."""
    was = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was:
            gc.enable()


def _mgz_commit():
    """Current aoc-mgz commit, read from .git without spawning a process.
    Part of the cache key: a parser change must invalidate cached parses."""
    git = os.path.join(HERE, 'aoc-mgz', '.git')
    try:
        head = open(os.path.join(git, 'HEAD')).read().strip()
        if not head.startswith('ref:'):
            return head  # detached
        ref = head.split(None, 1)[1]
        loose = os.path.join(git, *ref.split('/'))
        if os.path.exists(loose):
            return open(loose).read().strip()
        for line in open(os.path.join(git, 'packed-refs')):
            if not line.startswith(('#', '^')) and line.strip().endswith(ref):
                return line.split()[0]
    except OSError:
        pass
    return 'unknown'


def _cache_path(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    # abspath in the name so same-named replays in different dirs don't collide
    return os.path.join(CACHE_DIR, f'{stem}.{sha1(os.path.abspath(path).encode()).hexdigest()[:8]}.pkl')


def load_match(path, cache=True):
    """Parse an .aoe2record (or load its cached parse). Returns the mgz Match."""
    st = os.stat(path)
    key = (CACHE_VER, _mgz_commit(), st.st_mtime_ns, st.st_size)
    cpath = _cache_path(path)
    if cache and os.path.exists(cpath):
        try:
            with open(cpath, 'rb') as f, gc_paused():
                stored_key, m = pickle.load(f)
            if stored_key == key:
                return m
        except Exception:
            pass  # stale or corrupt cache entry: fall through to a fresh parse
    with open(path, 'rb') as f, gc_paused():
        m = parse_match(f)
    if not isinstance(m.hash, str):
        m.hash = m.hash.hexdigest()
    if cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = cpath + f'.tmp{os.getpid()}'
        try:
            with open(tmp, 'wb') as f:
                pickle.dump((key, m), f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, cpath)  # atomic: concurrent runs never see a partial file
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return m
