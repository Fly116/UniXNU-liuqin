#!/usr/bin/env python3
"""Search the userdata sparse image for the 16-byte sequence the kernel read at
'bad hash off=524288' (ascii 'leb/lib/libange,.d'), and report where it sits
relative to each dyld-cache candidate start."""
import struct
from pathlib import Path

SIMG = Path('/root/work/userdata-dyldprint.simg')
SYSOS_OFF = 6846152704
SYSOS_END = SYSOS_OFF + 5368709120
MAGIC = 0xED26FF3A
NEEDLE = bytes.fromhex('6c65622f6c69622f6c6962616e67652c2e64')


def chunks(path):
    with path.open('rb') as f:
        header = f.read(28)
        magic, major, minor, file_hdr, chunk_hdr, blk, total_blks, total_chunks, _ = struct.unpack('<IHHHHIIII', header)
        assert magic == MAGIC
        f.seek(file_hdr)
        pos = 0
        for _ in range(total_chunks):
            ch = f.read(chunk_hdr)
            if chunk_hdr == 12:
                ctype, _, count, size = struct.unpack('<HHII', ch)
            else:
                ctype, count, size = struct.unpack('<HHI', ch)
            if ctype == 0xCAC1:
                data = f.read(count * blk)
                yield pos, data
                pos += count * blk
            elif ctype == 0xCAC2:
                val = f.read(4)
                yield pos, val * blk
                pos += blk
            elif ctype == 0xCAC3:
                pos += count * blk
            elif ctype == 0xCAC4:
                val = f.read(4)
                yield pos, val * blk
                pos += blk
            else:
                raise SystemExit(f'bad chunk {ctype:#x}')


def main():
    hits = []
    for pos, data in chunks(SIMG):
        s, e = pos, pos + len(data)
        if e <= SYSOS_OFF or s >= SYSOS_END:
            continue
        base = max(s, SYSOS_OFF)
        seg = data[max(0, SYSOS_OFF - s):max(0, min(len(data), SYSOS_END - s))]
        start = 0
        while True:
            i = seg.find(NEEDLE, start)
            if i < 0:
                break
            hits.append(base + i)
            start = i + 1
    print('needle hits in SystemOS window:', len(hits))
    for h in hits[:12]:
        print(f'  abs={h:#x}  abs_rel_win={h - SYSOS_OFF:#x}')


if __name__ == '__main__':
    main()
