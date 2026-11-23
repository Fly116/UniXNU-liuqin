#!/usr/bin/env python3
"""Find the UFS PHY supply rails and the RPMh regulator nodes that back them."""
import struct
import sys
from pathlib import Path

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def parse(blob):
    strings_off = struct.unpack_from('>I', blob, 12)[0]
    struct_off = struct.unpack_from('>I', blob, 8)[0]
    nodes = []
    stack = []
    p = struct_off
    while True:
        tag = struct.unpack_from('>I', blob, p)[0]
        p += 4
        if tag == FDT_BEGIN_NODE:
            end = blob.index(b'\0', p)
            name = blob[p:end].decode(errors='replace')
            p = (end + 1 + 3) & ~3
            node = {'name': name, 'props': {}, 'path': '/'.join([s['name'] for s in stack] + [name])}
            stack.append(node)
            nodes.append(node)
        elif tag == FDT_END_NODE:
            stack.pop()
        elif tag == FDT_PROP:
            length, name_off = struct.unpack_from('>II', blob, p)
            p += 8
            value = blob[p:p + length]
            p = (p + length + 3) & ~3
            name = blob[strings_off + name_off:blob.index(b'\0', strings_off + name_off)].decode(errors='replace')
            if stack:
                stack[-1]['props'][name] = value
        elif tag == FDT_NOP:
            continue
        elif tag == FDT_END:
            break
        else:
            raise SystemExit(f'bad tag {tag:#x}')
    return nodes


def text(value):
    return value.decode(errors='replace').strip('\0')


def main():
    blob = Path(sys.argv[1]).read_bytes()
    nodes = parse(blob)
    by_handle = {}
    for node in nodes:
        ph = node['props'].get('phandle')
        if ph is not None and len(ph) == 4:
            by_handle[struct.unpack('>I', ph)[0]] = node

    print(f'{len(nodes)} nodes; {len(by_handle)} phandles')

    print('\n== nodes carrying vdda-*-supply ==')
    for node in nodes:
        for key in ('vdda-phy-supply', 'vdda-pll-supply', 'vdd-*-supply'):
            if key not in node['props'] or len(node['props'][key]) != 4:
                continue
            ph = struct.unpack('>I', node['props'][key])[0]
            target = by_handle.get(ph)
            print(f'- {node["path"]}')
            print(f'    {key} -> {target["path"] if target else "?"}')
            if target:
                for tk in ('compatible', 'regulator-name', 'reg'):
                    if tk in target['props']:
                        print(f'      {tk}: {text(target["props"][tk]) if tk != "reg" else target["props"][tk].hex()}')

    print('\n== rpmh regulator nodes ==')
    for node in nodes:
        comp = text(node['props'].get('compatible', b''))
        if 'rpmh-regulator' in comp:
            extra = []
            for key in ('regulator-name', 'regulator-min-microvolt', 'regulator-max-microvolt', 'reg'):
                if key in node['props']:
                    value = node['props'][key]
                    extra.append(f'{key}={text(value) if key != "reg" else value.hex()}')
            print(f'- {node["path"]} compatible="{comp}" ' + ' '.join(extra))


if __name__ == '__main__':
    main()
