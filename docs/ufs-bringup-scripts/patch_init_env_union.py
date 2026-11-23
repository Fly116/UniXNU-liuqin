#!/usr/bin/env python3
"""Stream-patch the init adapter's dyld environment inside the sparse userdata image.

See patch_init_env_union.py for the rationale. This version never loads the whole
11 GiB image: it walks sparse chunks, patches raw chunk payloads, writes them out.
"""
import struct
from pathlib import Path

SRC = Path('/mnt/f/liuqin_ios/_dl/ci/img/userdata.simg')
DST = Path('/root/work/userdata-union-patched.simg')
REPLACEMENTS = [
    (b'DYLD_SHARED_CACHE_DIR=/private/preboot/System/Library/Caches/com.apple.dyld/',
     b'DYLD_SHARED_CACHE_DIR=/System/Library/Caches/com.apple.dyld/'),
    (b'DYLD_FALLBACK_LIBRARY_PATH=/private/preboot/usr/lib',
     b'DYLD_FALLBACK_LIBRARY_PATH=/usr/lib'),
]
MAGIC = 0xED26FF3A


def main():
    patched = {}
    with SRC.open('rb') as source, DST.open('wb') as target:
        header = source.read(28)
        magic, major, minor, file_hdr, chunk_hdr, blk, total_blks, total_chunks, _ = \
            struct.unpack('<IHHHHIIII', header)
        if magic != MAGIC:
            raise SystemExit('not sparse')
        target.write(header)
        target.write(source.read(file_hdr - 28))
        for _ in range(total_chunks):
            chunk_header = source.read(chunk_hdr)
            target.write(chunk_header)
            if chunk_hdr == 12:
                ctype, _, count, size = struct.unpack('<HHII', chunk_header)
            else:
                ctype, count, size = struct.unpack('<HHI', chunk_header)
            if ctype == 0xCAC1:
                remaining = count
                while remaining:
                    take = min(remaining, 8192)
                    payload = bytearray(source.read(take * blk))
                    for old, new in REPLACEMENTS:
                        start = 0
                        while True:
                            index = payload.find(old, start)
                            if index < 0:
                                break
                            payload[index:index + len(old)] = new + b'\0' * (len(old) - len(new))
                            patched[old] = patched.get(old, 0) + 1
                            start = index + len(old)
                    target.write(payload)
                    remaining -= take
            elif ctype == 0xCAC2:
                target.write(source.read(4))
            elif ctype == 0xCAC3:
                pass
            elif ctype == 0xCAC4:
                target.write(source.read(4))
            else:
                raise SystemExit(f'bad chunk {ctype:#x}')
    print('patched occurrences:', {k[:35].decode(): v for k, v in patched.items()})
    print('wrote', DST, DST.stat().st_size)


if __name__ == '__main__':
    main()
