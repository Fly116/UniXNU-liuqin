#!/usr/bin/env python3
"""Stream the userdata sparse image, locate dyld shared cache files inside the
SystemOS window, and re-hash every code block of the main cache against its own
embedded Apple CodeDirectory. Reports the exact mismatching blocks."""
import struct, hashlib
from pathlib import Path

SIMG = Path('/root/work/userdata-dyldprint.simg')
SYSOS_OFF = 6846152704
SYSOS_END = SYSOS_OFF + 5368709120
MAGIC = 0xED26FF3A
HEAD = 0xA0000          # bytes to pull per candidate (main cache is 0x88000)
CD_MAGIC = b'\xfa\xde\x0c\x02'


def chunks(path):
    with path.open('rb') as f:
        header = f.read(28)
        magic, major, minor, file_hdr, chunk_hdr, blk, total_blks, total_chunks, _ = struct.unpack('<IHHHHIIII', header)
        assert magic == MAGIC, 'not a sparse image'
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


def scan_offsets():
    hits = []
    for pos, data in chunks(SIMG):
        for i in range(0, len(data) - 8, 0x1000):
            g = pos + i
            if g < SYSOS_OFF or g >= SYSOS_END:
                continue
            if data[i:i + 7] == b"dyld_v1" and (g & 0xFFF) == 0:
                hits.append(g)
    return hits


def read_at(offset, length):
    buf = bytearray(length)
    for pos, data in chunks(SIMG):
        s, e = pos, pos + len(data)
        lo, hi = max(s, offset), min(e, offset + length)
        if lo < hi:
            buf[lo - offset:hi - offset] = data[lo - s:hi - s]
    return bytes(buf)


def parse_cache(blob):
    # dyld cache embedded signature is a bare CodeDirectory, not a SuperBlob.
    cd_off = blob.find(CD_MAGIC)
    if cd_off < 0:
        return None
    version, flags, hash_off, ident_off, n_special, n_code, code_limit = \
        struct.unpack_from('>IIIIIII', blob, cd_off + 8)
    hsize, htype, platform, page = struct.unpack_from('BBBB', blob, cd_off + 36)
    hname = {1: 'sha1', 2: 'sha256', 3: 'sha256', 4: 'sha384'}.get(htype, str(htype))
    if hname == 'sha1':
        hname = 'sha1'
    actual = 1 << page
    bad = []
    slots = (code_limit + actual - 1) // actual
    for i in range(min(slots, n_code)):
        off = i * actual
        length = min(actual, code_limit - off)
        d = hashlib.new(hname)
        d.update(blob[off:off + length])
        exp_off = cd_off + hash_off + (n_special + i) * hsize
        exp = blob[exp_off:exp_off + hsize]
        if d.digest()[:hsize] != exp:
            bad.append((off, exp[:8].hex(), d.digest()[:hsize][:8].hex(),
                        blob[off:off + 16].hex()))
    return dict(so=cd_off, hash_off=hash_off, n_special=n_special, n_code=n_code,
                code_limit=code_limit, hname=hname, hsize=hsize, page=actual, bad=bad,
                version=version)


def main():
    hits = scan_offsets()
    print('dyld cache candidate offsets in SystemOS window:', len(hits))
    main_cache = None
    for g in hits:
        blob = read_at(g, HEAD)
        info = parse_cache(blob)
        if not info:
            print(f'  off={g:#x} no CodeDirectory in first {HEAD} bytes')
            continue
        print(f"  off={g:#x} codeLimit={info['code_limit']} hash={info['hname']} "
              f"slots={info['n_code']} bad={len(info['bad'])} cdver={info['version']:#x}")
        if info['code_limit'] == 540672:
            main_cache = (g, blob, info)
    if not main_cache:
        print('main cache (codeLimit 540672) not found')
        return
    g, blob, info = main_cache
    print(f'\n== main cache at {g:#x}: {len(info["bad"])} bad blocks of {info["n_code"]} ==')
    for off, exp, got, dat in info['bad']:
        print(f'  block off={off} ({off:#x}) exp={exp} got={got} data16={dat}')
    if info['bad']:
        off = info['bad'][0][0]
        blk = blob[off:off + info['page']]
        tail = blk[-64:]
        print('  failing block tail64:', tail.hex())
        print('  all-zero tail:', all(b == 0 for b in tail),
              ' all-ff tail:', all(b == 0xff for b in tail))
        print('  ascii tail:', ''.join(chr(b) if 32 <= b < 127 else '.' for b in tail))
        head = blk[:64]
        print('  ascii head:', ''.join(chr(b) if 32 <= b < 127 else '.' for b in head))


if __name__ == '__main__':
    main()
