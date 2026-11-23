#!/usr/bin/env python3
"""Verify v134 boot-v4 chain, fixed FD/Cape, FAT envelope and embedded kernel.
Read only. Extract only to a caller-selected NEW verification directory.
"""
import gzip, hashlib, json, struct, subprocess, sys
from pathlib import Path
image, kernel, fd, cape, output = map(Path, sys.argv[1:6])
assert not output.exists(), 'verification output must be new'
output.mkdir()
b = image.read_bytes()
sha=lambda x:hashlib.sha256(x).hexdigest()
assert b[:8] == b'ANDROID!'
ks, rs = struct.unpack_from('<II', b, 8)
version=struct.unpack_from('<I', b, 40)[0]
assert version == 4, version
align=lambda n:(n+4095)//4096*4096
firm=b[4096:4096+ks]
ram=b[4096+align(ks):4096+align(ks)+rs]
assert firm.endswith(cape.read_bytes()), 'wrong appended Cape'
gz=firm[:-len(cape.read_bytes())]
raw=gzip.decompress(gz)
assert fd.read_bytes() in raw, 'fixed FD not present in decompressed kernel slot'
assert sha(fd.read_bytes())=='44485ef0ca1e61d714115957cab3e6d5b53746bffae1e1f05090a077d7ab47d5'
assert sha(cape.read_bytes())=='ce90f88b645ffdcc844ede7b0c57162c082079c4ee162f6b6e262389066b2d31'
idx=ram.find(b'PONGFAT1')
assert idx >= 0, 'missing FAT envelope'
# Existing chain uses a 4KiB envelope followed by 64MiB FAT.
payload=ram[idx+4096:]
assert len(payload)==67108864, len(payload)
fat=output/'payload.img'
fat.write_bytes(payload)
embedded=output/'kernel.macho'
subprocess.run(['mcopy','-i',str(fat),'::/EFI/UniXNU/Payloads/kernel.macho',str(embedded)],check=True)
assert embedded.read_bytes()==kernel.read_bytes(), 'FAT kernel mismatch'
result={'image':str(image),'image_sha256':sha(b),'image_bytes':len(b),'version':version,
 'kernel_slot_bytes':ks,'ramdisk_bytes':rs,'envelope_offset':idx,'firmware_bytes':len(raw),
 'fixed_fd_verified':True,'cape_verified':True,'payload_kernel_verified':True,
 'patched_kernel_sha256':sha(kernel.read_bytes()),'hardware_tested':False}
(output/'verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
