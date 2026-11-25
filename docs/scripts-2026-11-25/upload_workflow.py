#!/usr/bin/env python3
"""Upload a workflow file to Fly116/liuqin-ipados18-ci and dispatch it."""
import base64, json, sys, urllib.request, urllib.error
from pathlib import Path

TOKEN = Path('/mnt/f/liuqin_ios/_gh/token.txt').read_text().strip()
OWNER, REPO = 'Fly116', 'liuqin-ipados18-ci'
BRANCH = 'main'
API = 'https://api.github.com'
SRC = Path('/mnt/f/liuqin_ios/scratch/ci-cache-compare.yml')
TARGET = '.github/workflows/cache-compare.yml'


def api(method, path, body=None):
    url = f'{API}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'dsh-liuqin')
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw.strip() else None


def main():
    content = SRC.read_bytes()
    body = {'message': 'ci: one-shot cache-compare (original vs ditto-copied dyld main cache)',
            'content': base64.b64encode(content).decode(), 'branch': BRANCH}
    try:
        existing = api('GET', f'/repos/{OWNER}/{REPO}/contents/{TARGET}?ref={BRANCH}')
        body['sha'] = existing['sha']
        print('updating existing workflow')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        print('creating new workflow')
    result = api('PUT', f'/repos/{OWNER}/{REPO}/contents/{TARGET}', body)
    print('commit', result['commit']['sha'][:12])
    api('POST', f'/repos/{OWNER}/{REPO}/actions/workflows/cache-compare.yml/dispatches',
        {'ref': BRANCH})
    print('dispatched cache-compare')


if __name__ == '__main__':
    main()
