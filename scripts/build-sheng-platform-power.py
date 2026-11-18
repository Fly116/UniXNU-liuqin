#!/usr/bin/env python3
"""Build the opt-in, guarded sheng original-PMGR integration instrument."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/sheng-platform-power'
OUT.mkdir(parents=True, exist_ok=True)
# The liuqin-build tree still carries the native prelink kit as kits/NativePrelink;
# the newer tree renamed it to kits/XnuPrelink. Pick whichever one holds the module.
_KIT = next((ROOT / 'kits' / _name for _name in ('XnuPrelink', 'NativePrelink')
             if (ROOT / 'kits' / _name / 'native_prelink.py').is_file()),
            ROOT / 'kits' / 'NativePrelink')
sys.path.insert(0, str(_KIT))
from native_prelink import macho, backed_offset, exports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel_target import DEPLOYMENT, TRIPLE


def run(command, **kwargs):
    return subprocess.check_output([str(v) for v in command], timeout=90, **kwargs)


def require(value, message):
    if not value:
        raise SystemExit(message)


kernel_candidate = ROOT.parent / 'kernel/kernel.macho'   # liuqin: the built candidate cache
# The audit compares against a native prelink candidate that only exists after a
# previous native build. The ABI generated below is fixed text in this script, so a
# missing reference changes the verification, not the code: say so and continue.
try:
    print(run(['python3', ROOT / 'scripts/audit-amfi-pmgr-contract.py',
               '--candidate', str(kernel_candidate)], text=True), end='')
except subprocess.CalledProcessError:
    print('build-sheng-platform-power: AMFI/PMGR audit unavailable '
          '(no native prelink candidate in this tree); generated ABI unchanged')
header = '''// Generated exact storage/slot ABI; private fields stay opaque.
#pragma once
#include <IOKit/IOPMGR.h>
class ApplePMGR : public IOPMGR {
 OSDeclareAbstractStructors(ApplePMGR)
 unsigned char originalPrivate[0x4b8a8-sizeof(IOPMGR)];
public:
'''
guards = ''
for i in range(177, 340):
    if i == 320:
        header += ' virtual uint32_t readAon();\n'
    elif i == 321:
        header += ' virtual void writeAon(uint64_t);\n'
    else:
        header += f' virtual void opaque{i}() = 0;\n'
        guards += f' void opaque{i}() override {{ unavailable({i}); }}\n'
header += '};\nstatic_assert(sizeof(ApplePMGR)==0x4b8a8,"Original provider storage");\n'
(OUT / 'OriginalPMGRABI.h').write_text(header)
(OUT / 'GuardedPMGRSlots.inc').write_text(guards)
source_kit = ROOT / 'kits/liuqin/ShengPlatformPower.cpp'
source = source_kit if source_kit.is_file() else ROOT / 'kits/sheng/ShengPlatformPower.cpp'
obj = OUT / 'ShengPlatformPower.o'
record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
command, i = [], 0
arguments = record['arguments']
while i < len(arguments):
    arg = arguments[i]
    if arg == record['file']:
        command.append(source)
    elif arg == '-o':
        command += ['-o', obj]
        i += 1
    elif arg == '-Xclang' and arguments[i + 1].startswith('-W'):
        i += 1
    elif not arg.startswith('-W'):
        command.append(arg)
    i += 1
command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-c99-designator',
            '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
            '-Wno-unnecessary-virtual-specifier', '-I', OUT, '-I', ROOT / '.cache/xnu-work/osfmk']
run(command, cwd=record['directory'])
raw = obj.read_bytes()
info = macho(raw)
require(info['kind'] == 1, 'Require actual ARM64 subtype-0 Mach-O object')
build_version = [struct.unpack_from('<2I', raw, at + 8) for cmd, at, _ in info['commands'] if cmd == 0x32]
require(build_version == [DEPLOYMENT], 'Require the kernel deployment target')
sym_at = next(at for cmd, at, _ in info['commands'] if cmd == 2)
at, count, strings, _ = struct.unpack_from('<4I', raw, sym_at + 8)
symbols = []
for i in range(count):
    ix, kind, _, _, address = struct.unpack_from('<IBBHQ', raw, at + i * 16)
    symbols.append((raw[strings + ix:raw.index(b'\0', strings + ix)].decode(), address, kind))
vtable = next(va for name, va, _ in symbols if name == '__ZTV18ShengPlatformPower')
relocations = {}
for segment in info['segments']:
    for section in segment['sections']:
        if section['va'] <= vtable < section['va'] + section['size']:
            at, count = struct.unpack_from('<2I', raw, section['command_offset'] + 56)
            for i in range(count):
                offset, bits = struct.unpack_from('<2I', raw, at + i * 8)
                if bits >> 27 & 1 and bits >> 28 == 0 and bits >> 25 & 3 == 3:
                    relocations[section['va'] + offset] = symbols[bits & 0xffffff][0]
entries = [relocations.get(vtable + 16 + i * 8) for i in range(340)]
require(all(entries) and vtable + 16 + 340 * 8 not in relocations, 'Exact 340-entry provider table')
reference = ROOT / 'build/xnu-prelink/native-owner-ufs-rootauth3-candidate.macho'
if not reference.exists():
    # Build products are pruned: a later candidate built from the same original kernelcache has the identical original
    # ApplePMGR class and inherited native IOPMGR slots; every slot/pointer check below still runs against it.
    later = sorted((ROOT / 'build/xnu-prelink').glob('native-owner-ufs-cpu-desktop-*-candidate.macho'), key=lambda f: f.stat().st_mtime)
    if later:
        reference = later[-1]
    else:
        # liuqin schema-1: the built candidate is the reference (same pinned original cache).
        reference = kernel_candidate
    require(reference.exists(), 'No reference candidate available')
candidate = reference.read_bytes()
meta = macho(candidate)
native_names = {n: va for va, names in exports(candidate, meta).items() for n in names}


def ptr(va):
    return struct.unpack_from('<Q', candidate, backed_offset(meta['segments'], va, 8, len(candidate)))[0]


bindings = {'__ZN9ApplePMGRC2EPK11OSMetaClass': 0xfffffff0049f003c,
            '__ZN9ApplePMGRD2Ev': 0xfffffff0049f019c,
            '__ZN9ApplePMGR10gMetaClassE': 0xfffffff006adf490}
for slot, name in enumerate(entries):
    if slot in (0, 1, 7) or 168 <= slot < 340 and slot not in (320, 321):
        require('18ShengPlatformPower' in name, f'Own guard/lifecycle required at slot {slot}')
    elif slot in (320, 321):
        require('9ApplePMGR' in name, 'Only actual original AON implementations inherited')
        bindings[name] = ptr(0xfffffff005ce26d8 + slot * 8)
    else:
        require(native_names.get(name) == ptr(native_names['__ZTV6IOPMGR'] + 16 + slot * 8),
                f'Native IOPMGR/IOService entry differs at {slot}')
undefined = {n for n, _, k in symbols if k == 1 and 'ApplePMGR' in n}
require(undefined == set(bindings), 'All and only audited original base imports')
bindings.update({'_sheng_original_pmgr_nub_create': 0xfffffff004a22568,
                 '_sheng_original_pmgr_nub_read': 0xfffffff004a24adc,
                 '_sheng_original_pmgr_nub_write': 0xfffffff004a230ec})
asm = OUT / 'original-bindings.S'
asm.write_text(''.join(f'.globl {name}\n.set {name}, {va:#x}\n' for name, va in bindings.items()))
sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
run(['xcrun', 'clang', '-target', TRIPLE, '-isysroot', sdk, '-c', asm, '-o', OUT / 'original-bindings.o'])
late = OUT / 'ShengPlatformPower.late.o'
run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func',
     '--globalize-symbol=__GLOBAL__sub_I_ShengPlatformPower.cpp', obj, late])


def text_section(blob):
    section = next(s for seg in macho(blob)['segments'] for s in seg['sections'] if s['name'] == '__text')
    return blob[section['fileoff']:section['fileoff'] + section['size']]


require(text_section(raw) == text_section(late.read_bytes()), 'Late registration cannot change instructions')
archive = OUT / 'libShengPlatformPower.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, late, OUT / 'original-bindings.o'])
report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
          'bindings': {name: hex(va) for name, va in bindings.items()}, 'virtual_entries': 340,
          'mode': 'opt-in lifecycle/publication/refusal instrument; not a functional power backend',
          'runtime_qualified': False, 'original_executable_modified': False}
(OUT / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS: ordinary ARM64/iOS17 build; exact native and original bindings; unimplemented power slots stop')