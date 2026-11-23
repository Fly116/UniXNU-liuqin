#!/usr/bin/env python3
"""Locate the init adapter's environment strings inside the sparse userdata image
and report every matching sparse chunk plus whether CRC chunks exist."""
import struct
from pathlib import Path

IMG = Path('/mnt/f/liuqin_ios/_dl/ci/img/userdata.simg')
NEEDLES = [
    b'DYLD_SHARED_CACHE_DIR=/private/preboot/System/Library/Caches/com.apple.dyld/',
    b'DYLD_FALLBACK_LIBRARY_PATH=/private/preboot/usr/lib',
]
MAGIC = 0xED26FF3A


def main():
    with IMG.open('rb') as handle:
        magic, major, minor, file_hdr, chunk_hdr, blk, total_blks, total_chunks, _ = \
            struct.unpack('<IHHHHIIII', handle.read(28))
        if magic != MAGIC:
            raise SystemExit('not sparse')
        handle.seek(file_hdr)
        block = 0
        crc_chunks = 0
        found = {}
        for _ in range(total_chunks):
            header = handle.read(chunk_hdr)
            if len(header) < chunk_hdr:
                break
            if chunk_hdr == 12:
                ctype, _, count, size = struct.unpack('<HHII', header)
            else:
                ctype, count, size = struct.unpack('<HHI', header)
            first = block
            if ctype == 0xCAC4:
                crc_chunks += 1
            if ctype == 0xCAC1:
                remaining = count
                while remaining:
                    take = min(remaining, 8192)
                    payload = handle.read(take * blk)
                    for needle in NEEDLES:
                        start = 0
                        while True:
                            index = payload.find(needle, start)
                            if index < 0:
                                break
                            found.setdefault(needle, []).append((first + index // blk, index % blk, first, take))
                            start = index + 1
                    first += take
                    remaining -= take
            elif ctype == 0xCAC2:
                handle.read(4)
            elif ctype == 0xCAC3:
                pass
            block += count
        print('crc chunks:', crc_chunks)
        for needle, hits in found.items():
            print(f'{needle[:40].decode()}... hits={len(hits)}')
            for hit in hits[:5]:
                print('   block', hit[0], 'offset-in-chunk', hit[1])


if __name__ == '__main__':
    main()
