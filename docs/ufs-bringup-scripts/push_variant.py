#!/usr/bin/env python3
"""Push a variant patch to Fly116/liuqin-ipados18-ci and dispatch the kernel build.

usage: push_variant.py <letter> <patch file> <target file name> <message>
"""
import base64
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

TOKEN = Path('/mnt/f/liuqin_ios/_gh/token.txt').read_text().strip()
OWNER, REPO = 'Fly116', 'liuqin-ipados18-ci'
WORKFLOW = 'kernel-upstream.yml'
BRANCH = 'main'
API = 'https://api.github.com'
LETTER = sys.argv[1]
PATCH = Path(sys.argv[2])
FILENAME = sys.argv[3]
MESSAGE = sys.argv[4]
TARGET = f'ci/patches-variants/{LETTER}/{FILENAME}'


def api(method, path, body=None):
    url = f'{API}{path}'
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header('Authorization', f'Bearer {TOKEN}')
    request.add_header('Accept', 'application/vnd.github+json')
    request.add_header('User-Agent', 'dsh-liuqin')
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw.strip() else None


def put_file(path, content, message):
    body = {'message': message, 'content': base64.b64encode(content).decode(), 'branch': BRANCH}
    try:
        existing = api('GET', f'/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}')
        body['sha'] = existing['sha']
        print(f'updating existing {path}')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        print(f'creating new {path}')
    result = api('PUT', f'/repos/{OWNER}/{REPO}/contents/{path}', body)
    print('commit', result['commit']['sha'][:12])


def main():
    content = PATCH.read_bytes()
    print(f'patch {PATCH} ({len(content)} bytes)')
    put_file(TARGET, content, MESSAGE)
    api('POST', f'/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}/dispatches', {
        'ref': BRANCH,
        'inputs': {
            'device_ref': 'fe0e8d790e24120970083e20c1a7d9c86cdbb87c',
            'unique_chip_id': '84750a0b',
            'prelink': 'true',
            'patch_dir': f'ci/patches-variants/{LETTER}',
        },
    })
    print('dispatched', LETTER)


if __name__ == '__main__':
    main()
