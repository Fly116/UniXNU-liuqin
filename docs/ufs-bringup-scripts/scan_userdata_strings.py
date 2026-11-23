#!/usr/bin/env python3
"""Scan raw sparse chunks of the userdata image for dyld/launchd strings inside the
OS/SystemOS/Data windows, streaming sequentially (no 32 GiB materialisation)."""
import struct
from pathlib import Path

IMG = Path('/mnt/f/liuqin_ios/_dl/ci/img/userdata.simg')
WINDOWS = {
    'OS': (1048576, 6845104128),
    'SystemOS': (6846152704, 5368709120),
    'Data': (12231639040, 8589934592),
}
NEEDLES = [b'dyld_shared_cache_arm64e', b'com.apple.dyld', b'libSystem.B.dylib',
           b'/sbin/launchd', b'launchd.ios', b'systemos', b'SystemOS']
MAGIC = 0xED26FF3A


def main():
    with IMG.open('rb') as handle:
        magic, major, minor, file_hdr, chunk_hdr, blk, total_blks, total_chunks, _ = \
            struct.unpack('<IHHHHIIII', handle.read(28))
        if magic != MAGIC:
            raise SystemExit('not sparse')
        print(f'sparse blk={blk} chunks={total_chunks}')
        handle.seek(file_hdr)
        block = 0
        hits = {}
        max_chunk = 0
        for _ in range(total_chunks):
            header = handle.read(chunk_hdr)
            if len(header) < chunk_hdr:
                break
            if chunk_hdr == 12:
                ctype, _, count, size = struct.unpack('<HHII', header)
            else:
                ctype, count, size = struct.unpack('<HHI', header)
            first, last = block, block + count
            if ctype == 0xCAC1:
                max_chunk = max(max_chunk, count * blk)
                remaining = count
                while remaining:
                    take = min(remaining, 8192)
                    payload = handle.read(take * blk)
                    for name, (start, length) in WINDOWS.items():
                        start_block = start // blk
                        end_block = (start + length) // blk
                        if first + take <= start_block or first >= end_block:
                            continue
                        for needle in NEEDLES:
                            index = payload.find(needle)
                            if index >= 0:
                                hits.setdefault((name, needle), []).append(first + index // blk)
                    first += take
                    remaining -= take
            elif ctype == 0xCAC2:
                handle.read(4)
            elif ctype == 0xCAC3:
                pass
            elif ctype == 0xCAC4:
                handle.read(4)
            else:
                raise SystemExit(f'bad chunk {ctype:#x}')
            block = last
        print('largest raw chunk', max_chunk, 'bytes')
        for (name, needle), blocks in sorted(hits.items()):
            print(f'{name}: {needle.decode()} in {len(blocks)} chunk(s), first block {blocks[0]}')
        if not hits:
            print('no needles found')


if __name__ == '__main__':
    main()
