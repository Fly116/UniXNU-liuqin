#!/usr/bin/env python3
"""Verify ARMCPU patch at VA, and assert it is the only kernel modification."""
import hashlib, struct, sys, json
from pathlib import Path
original, patched = map(Path, sys.argv[1:3])
a, b = original.read_bytes(), patched.read_bytes()
assert len(a) == len(b)
assert struct.unpack_from('<I', b)[0] == 0xfeedfacf
ncmds = struct.unpack_from('<I', b, 16)[0]
off = 32
va = 0xfffffff00b80dad4
target = None
for _ in range(ncmds):
 cmd, size = struct.unpack_from('<II', b, off)
 assert size >= 8
 if cmd == 0x19:
  vm, vs, fo, fs = struct.unpack_from('<QQQQ', b, off + 24)
  if vm <= va < vm + fs: target = fo + va - vm
 off += size
assert target is not None
assert a[target:target+8] == bytes.fromhex('ff0303d1fc6f06a9')
assert b[target:target+8] == bytes.fromhex('20008052c0035fd6')
assert a[:target] == b[:target] and a[target+8:] == b[target+8:]
print(json.dumps({'armcpu_va':hex(va), 'file_offset':hex(target), 'only_change_is_armcpu_patch':True,
 'original_sha256':hashlib.sha256(a).hexdigest(), 'patched_sha256':hashlib.sha256(b).hexdigest()},indent=2))
