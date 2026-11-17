#!/usr/bin/env python3
"""Reproduce the README's "AI 用量统计" table from the local DeepSeek Harness logs.

Scans every session of the two local workspaces and sums the provider usage the
harness recorded on each assistant turn (and on compaction summaries). Records
are counted once per (session, seq, turn, step), so re-runs are stable and
spliced/replayed history does not double count.

    python3 scripts/token-stats.py

Usage fields are the provider's own: inputTokens is the NON-cached input,
cacheReadTokens and outputTokens are separate, and
totalTokens == inputTokens + cacheReadTokens + outputTokens.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

SESSIONS_ROOT = os.path.expanduser('~/.dsh/sessions')
# The two workspaces this port lives in; both are counted, matching the README.
WORKSPACES = [
    '--home-hhyygg-Documents-deepseek-harness-default-workspace--',
    '--home-hhyygg-.dsh-qqbot-workspace--',
]
USAGE_RECORD_TYPES = ('assistant/message', 'compaction/summary')


def records(path):
    """Yield parsed JSONL records from a (zstd-compressed) session log."""
    if path.endswith('.zstd'):
        raw = subprocess.run(['zstd', '-dc', path], capture_output=True).stdout
    else:
        raw = open(path, 'rb').read()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def main():
    dirs = []
    for ws in WORKSPACES:
        root = os.path.join(SESSIONS_ROOT, ws)
        if not os.path.isdir(root):
            print(f'warning: no such session root: {root}', file=sys.stderr)
            continue
        dirs += [d for d in sorted(glob.glob(os.path.join(root, '*'))) if os.path.isdir(d)]

    used = set()
    turns = usage_records = sessions = subagent_sessions = 0
    noncached = cached = output = 0

    for d in dirs:
        logs = glob.glob(os.path.join(d, 'session.v*.jsonl*'))
        if not logs:
            continue
        sessions += 1
        origin = ''
        for log in logs:
            for r in records(log):
                if r.get('type') == 'session':
                    origin = r.get('origin', '')
                if r.get('type') == 'assistant/message':
                    turns += 1
                data = r.get('data') or {}
                usage = data.get('usage') if isinstance(data, dict) else None
                if r.get('type') not in USAGE_RECORD_TYPES or not usage:
                    continue
                key = (log, r.get('seq'), data.get('turn'), data.get('step'))
                if key in used:
                    continue
                used.add(key)
                usage_records += 1
                noncached += usage.get('inputTokens', 0) or 0
                cached += usage.get('cacheReadTokens', 0) or 0
                output += usage.get('outputTokens', 0) or 0
        if origin == 'subagent':
            subagent_sessions += 1

    total = noncached + cached + output
    print(f'sessions            : {sessions} '
          f'({subagent_sessions} subagent-spawned, {sessions - subagent_sessions} top-level)')
    print(f'assistant turns     : {turns:,}')
    print(f'usage records       : {usage_records:,}')
    print(f'non-cached input    : {noncached:,}')
    print(f'cache read          : {cached:,}')
    print(f'output              : {output:,}')
    print(f'TOTAL               : {total:,}')
    print(f'cache share         : {cached * 100 // total if total else 0}%')


if __name__ == '__main__':
    main()
