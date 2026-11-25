#!/usr/bin/env python3
"""ai variant v2: full per-block reporting, with every overlay hunk anchored on
the exact old text that the ad/ah overlay already proved matches on the CI tree
(ah built with these anchors). Additions only, no old-text drift:

  A) static cs_native4k_badblocks next to the native4k counters (zz hunk1 ctx)
  B) reset + entry line before the per-chunk loop        (ad hunk2 anchor)
  C) bad-hash branch becomes a full map: print + count,
     good blocks still derive 4K digests                 (ad hunk4 anchor)
  D) summary before publishing: bad!=0 => EBADEXEC       (ad hunk5 anchor)
"""
import difflib
import shutil
import subprocess
from pathlib import Path

WORK = Path('/root/work/ai-work')
TREE = Path('/root/work/v134-variant-v')
SERIES = TREE / 'patches/xnu-ipados18/series'
NEW_NAME = 'zzzzzzzzzzzzzzzzzz-liuqin-native4k-fullhash.patch'
NEW = TREE / 'patches/xnu-ipados18' / NEW_NAME
OUT = Path('/root/work/ai.patch')
SRC = Path('/root/work/UniXNU-new/out/liuqin/tree/.cache/xnu-work/bsd/kern/ubc_subr.c')
RELPATH = 'bsd/kern/ubc_subr.c'

ZZ_TRANS = [
    (
        " * derived array readonly before its owning RO cs_blob can become visible.\n"
        " * VM fault validation consequently performs no vnode I/O under object locks.\n"
        " */\n"
        "__attribute__((noinline))",
        " * derived array readonly before its owning RO cs_blob can become visible.\n"
        " * VM fault validation consequently performs no vnode I/O under object locks.\n"
        " */\n"
        "/* The boot cost, for a board's diagnostics: mach_absolute_time ticks in vn_rdwr (the storage driver's work included) and in the\n"
        " * hashing, and the bytes read. */\n"
        "uint64_t cs_native4k_read_ticks = 0, cs_native4k_hash_ticks = 0, cs_native4k_bytes = 0;\n"
        "extern uint64_t mach_absolute_time(void);\n"
        "\n"
        "/* One read covers 64 original blocks. Files above 32 MiB (the 3 GB dyld shared cache, read whole by launchd at every boot) are read\n"
        " * uncached: through the page cache they left almost no free memory when the first daemons started. */\n"
        "#define CS_NATIVE4K_CHUNK       (1024 * 1024)\n"
        "#define CS_NATIVE4K_UNCACHED    (32 * 1024 * 1024)\n"
        "\n"
        "__attribute__((noinline))",
    ),
    (
        "	uint8_t *buffer = NULL;\n"
        "	uint64_t limit, offset;\n"
        "	int error = EBADEXEC;\n"
        "	kern_return_t kr;",
        "	uint8_t *buffer = NULL;\n"
        "	uint64_t limit, offset, chunk;\n"
        "	int error = EBADEXEC, ioflags;\n"
        "	kern_return_t kr;",
    ),
    (
        "	kr = kmem_alloc(kernel_map, &storage, allocation,\n"
        "	    KMA_KOBJECT | KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_SECURITY);\n"
        "	if (kr != KERN_SUCCESS) {\n"
        "		return ENOMEM;\n"
        "	}\n"
        "	buffer = kalloc_data(16384, Z_WAITOK);\n"
        "	for (offset = 0; offset < limit; offset += 16384) {\n"
        "		union cs_hash_union ctx;\n"
        "		uint8_t digest[CS_HASH_MAX_SIZE];\n"
        "		const uint8_t *expected;\n"
        "		const char *lower = blob->csb_mem_kaddr;\n"
        "		const char *upper = lower + blob->csb_mem_size;\n"
        "		size_t length = MIN((uint64_t)16384, limit - offset);\n"
        "		int resid = 0;\n"
        "		off_t position;\n"
        "		if (os_add_overflow(blob->csb_base_offset, (off_t)offset, &position)) {\n"
        "			error = EOVERFLOW;\n"
        "			goto out;\n"
        "		}\n"
        "		error = vn_rdwr(UIO_READ, vp, (caddr_t)buffer, (int)length, position,\n"
        "		    UIO_SYSSPACE, 0, vfs_context_ucred(vfs_context_current()),\n"
        "		    &resid, current_proc());\n"
        "		if (error || resid) {\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		expected = hashes(cd, (uint32_t)(offset >> 14), md->cs_size, lower, upper);\n"
        "		if (expected == NULL) {\n"
        "			error = EBADEXEC;\n"
        "			goto out;\n"
        "		}\n"
        "		md->cs_init(&ctx);\n"
        "		md->cs_update(&ctx, buffer, length);\n"
        "		md->cs_final(digest, &ctx);\n"
        "		if (bcmp(expected, digest, md->cs_size)) {\n"
        "			os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "			error = EBADEXEC;\n"
        "			goto out;\n"
        "		}\n"
        "		os_atomic_inc(&cs_native4k_full_blocks, relaxed);\n"
        "		for (size_t sub = 0; sub < length; sub += PAGE_SIZE) {\n"
        "			size_t bytes = MIN((size_t)PAGE_SIZE, length - sub);\n"
        "			vm_size_t index = (offset + sub) >> PAGE_SHIFT;\n"
        "			md->cs_init(&ctx);\n"
        "			md->cs_update(&ctx, buffer + sub, bytes);\n"
        "			md->cs_final(digest, &ctx);\n"
        "			memcpy((void *)(storage + index * md->cs_size), digest, md->cs_size);\n"
        "		}\n"
        "	}\n"
        "	kr = vm_map_protect(kernel_map, storage, storage + allocation, VM_PROT_READ, TRUE);",
        "	kr = kmem_alloc(kernel_map, &storage, allocation,\n"
        "	    KMA_KOBJECT | KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_SECURITY);\n"
        "	if (kr != KERN_SUCCESS) {\n"
        "		printf(\"Pong native4K: digest allocation failed bytes=%lu kr=%d\\n\", (unsigned long)allocation, kr);\n"
        "		return ENOMEM;\n"
        "	}\n"
        "	buffer = kalloc_data(CS_NATIVE4K_CHUNK, Z_WAITOK);\n"
        "	if (buffer == NULL) {\n"
        "		error = ENOMEM;\n"
        "		goto out;\n"
        "	}\n"
        "	/* Executables are faulted in right after their signature is added and stay cached. */\n"
        "	ioflags = limit > CS_NATIVE4K_UNCACHED ? IO_NOCACHE : 0;\n"
        "	for (chunk = 0; chunk < limit; chunk += CS_NATIVE4K_CHUNK) {\n"
        "		size_t chunk_length = MIN((uint64_t)CS_NATIVE4K_CHUNK, limit - chunk);\n"
        "		int resid = 0;\n"
        "		off_t position;\n"
        "		if (os_add_overflow(blob->csb_base_offset, (off_t)chunk, &position)) {\n"
        "			error = EOVERFLOW;\n"
        "			goto out;\n"
        "		}\n"
        "		const uint64_t read_start = mach_absolute_time();\n"
        "		error = vn_rdwr(UIO_READ, vp, (caddr_t)buffer, (int)chunk_length, position,\n"
        "		    UIO_SYSSPACE, ioflags, vfs_context_ucred(vfs_context_current()),\n"
        "		    &resid, current_proc());\n"
        "		const uint64_t hash_start = mach_absolute_time();\n"
        "		os_atomic_add(&cs_native4k_read_ticks, hash_start - read_start, relaxed);\n"
        "		os_atomic_add(&cs_native4k_bytes, (uint64_t)chunk_length, relaxed);\n"
        "		if (error || resid) {\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		for (size_t block = 0; block < chunk_length; block += 16384) {\n"
        "			union cs_hash_union ctx;\n"
        "			uint8_t digest[CS_HASH_MAX_SIZE];\n"
        "			const uint8_t *expected;\n"
        "			const uint8_t *data = buffer + block;\n"
        "			const char *lower = blob->csb_mem_kaddr;\n"
        "			const char *upper = lower + blob->csb_mem_size;\n"
        "			size_t length = MIN((size_t)16384, chunk_length - block);\n"
        "			offset = chunk + block;\n"
        "			expected = hashes(cd, (uint32_t)(offset >> 14), md->cs_size, lower, upper);\n"
        "			if (expected == NULL) {\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}\n"
        "			md->cs_init(&ctx);\n"
        "			md->cs_update(&ctx, data, length);\n"
        "			md->cs_final(digest, &ctx);\n"
        "			if (bcmp(expected, digest, md->cs_size)) {\n"
        "				os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}\n"
        "			os_atomic_inc(&cs_native4k_full_blocks, relaxed);\n"
        "			for (size_t sub = 0; sub < length; sub += PAGE_SIZE) {\n"
        "				size_t bytes = MIN((size_t)PAGE_SIZE, length - sub);\n"
        "				vm_size_t index = (offset + sub) >> PAGE_SHIFT;\n"
        "				md->cs_init(&ctx);\n"
        "				md->cs_update(&ctx, data + sub, bytes);\n"
        "				md->cs_final(digest, &ctx);\n"
        "				memcpy((void *)(storage + index * md->cs_size), digest, md->cs_size);\n"
        "			}\n"
        "		}\n"
        "		os_atomic_add(&cs_native4k_hash_ticks, mach_absolute_time() - hash_start, relaxed);\n"
        "	}\n"
        "	kr = vm_map_protect(kernel_map, storage, storage + allocation, VM_PROT_READ, TRUE);",
    ),
    (
        "	kfree_data(buffer, 16384);",
        "	kfree_data(buffer, CS_NATIVE4K_CHUNK);",
    ),
]

REPL = [
    # A) static counter next to the zz counters (anchor: the exact zz hunk1 result)
    (
        ZZ_TRANS[0][1],
        " * derived array readonly before its owning RO cs_blob can become visible.\n"
        " * VM fault validation consequently performs no vnode I/O under object locks.\n"
        " */\n"
        "/* The boot cost, for a board's diagnostics: mach_absolute_time ticks in vn_rdwr (the storage driver's work included) and in the\n"
        " * hashing, and the bytes read. */\n"
        "uint64_t cs_native4k_read_ticks = 0, cs_native4k_hash_ticks = 0, cs_native4k_bytes = 0;\n"
        "extern uint64_t mach_absolute_time(void);\n"
        "\n"
        "/* One read covers 64 original blocks. Files above 32 MiB (the 3 GB dyld shared cache, read whole by launchd at every boot) are read\n"
        " * uncached: through the page cache they left almost no free memory when the first daemons started. */\n"
        "#define CS_NATIVE4K_CHUNK       (1024 * 1024)\n"
        "#define CS_NATIVE4K_UNCACHED    (32 * 1024 * 1024)\n"
        "\n"
        "/* Full-block map state for the failure scan, reset per cs_native4k_prepare. */\n"
        "static unsigned cs_native4k_badblocks;\n"
        "\n"
        "__attribute__((noinline))",
    ),
    # B) reset + entry line before the per-chunk loop (anchor: ad hunk2)
    (
        "		if (error || resid) {\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		for (size_t block = 0; block < chunk_length; block += 16384) {",
        "		if (error || resid) {\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		if (chunk == 0) {\n"
        "			cs_native4k_badblocks = 0;\n"
        "			printf(\"PONG native4K: prepare base=%lld limit=%llu mem=%llu hashsize=%u\\n\",\n"
        "			    (long long)blob->csb_base_offset, (unsigned long long)limit,\n"
        "			    (unsigned long long)blob->csb_mem_size, (unsigned)md->cs_size);\n"
        "		}\n"
        "		for (size_t block = 0; block < chunk_length; block += 16384) {",
    ),
    # C) full map: bad blocks print+count, good blocks still derive 4K digests
    (
        "			if (bcmp(expected, digest, md->cs_size)) {\n"
        "				os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}\n"
        "			os_atomic_inc(&cs_native4k_full_blocks, relaxed);\n"
        "			for (size_t sub = 0; sub < length; sub += PAGE_SIZE) {\n"
        "				size_t bytes = MIN((size_t)PAGE_SIZE, length - sub);\n"
        "				vm_size_t index = (offset + sub) >> PAGE_SHIFT;\n"
        "				md->cs_init(&ctx);\n"
        "				md->cs_update(&ctx, data + sub, bytes);\n"
        "				md->cs_final(digest, &ctx);\n"
        "				memcpy((void *)(storage + index * md->cs_size), digest, md->cs_size);\n"
        "			}",
        "			if (bcmp(expected, digest, md->cs_size)) {\n"
        "				os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "				cs_native4k_badblocks++;\n"
        "				printf(\"PONG native4K: block %u off=%llu exp=%02x%02x%02x%02x got=%02x%02x%02x%02x data=%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "				    (unsigned)(offset >> 14), (unsigned long long)offset,\n"
        "				    expected[0], expected[1], expected[2], expected[3],\n"
        "				    digest[0], digest[1], digest[2], digest[3],\n"
        "				    data[0], data[1], data[2], data[3], data[4], data[5],\n"
        "				    data[6], data[7]);\n"
        "				if (length >= 128) {\n"
        "					printf(\"PONG native4K: tail0 %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "					    data[length-128], data[length-127], data[length-126], data[length-125],\n"
        "					    data[length-124], data[length-123], data[length-122], data[length-121],\n"
        "					    data[length-120], data[length-119], data[length-118], data[length-117],\n"
        "					    data[length-116], data[length-115], data[length-114], data[length-113],\n"
        "					    data[length-112], data[length-111], data[length-110], data[length-109],\n"
        "					    data[length-108], data[length-107], data[length-106], data[length-105],\n"
        "					    data[length-104], data[length-103], data[length-102], data[length-101],\n"
        "					    data[length-100], data[length-99], data[length-98], data[length-97]);\n"
        "					printf(\"PONG native4K: tail1 %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "					    data[length-96], data[length-95], data[length-94], data[length-93],\n"
        "					    data[length-92], data[length-91], data[length-90], data[length-89],\n"
        "					    data[length-88], data[length-87], data[length-86], data[length-85],\n"
        "					    data[length-84], data[length-83], data[length-82], data[length-81],\n"
        "					    data[length-80], data[length-79], data[length-78], data[length-77],\n"
        "					    data[length-76], data[length-75], data[length-74], data[length-73],\n"
        "					    data[length-72], data[length-71], data[length-70], data[length-69],\n"
        "					    data[length-68], data[length-67], data[length-66], data[length-65]);\n"
        "					printf(\"PONG native4K: tail2 %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "					    data[length-64], data[length-63], data[length-62], data[length-61],\n"
        "					    data[length-60], data[length-59], data[length-58], data[length-57],\n"
        "					    data[length-56], data[length-55], data[length-54], data[length-53],\n"
        "					    data[length-52], data[length-51], data[length-50], data[length-49],\n"
        "					    data[length-48], data[length-47], data[length-46], data[length-45],\n"
        "					    data[length-44], data[length-43], data[length-42], data[length-41],\n"
        "					    data[length-40], data[length-39], data[length-38], data[length-37],\n"
        "					    data[length-36], data[length-35], data[length-34], data[length-33]);\n"
        "				}\n"
        "				if (length >= 16384) {\n"
        "					/* Same offset, one small read: separates a broken large I/O from bad data on disk. */\n"
        "					int resid2 = 0;\n"
        "					uint8_t *tmp = kalloc_data((vm_size_t)length, Z_WAITOK);\n"
        "					if (tmp != NULL) {\n"
        "						uint8_t digest2[CS_HASH_MAX_SIZE];\n"
        "						union cs_hash_union ctx2;\n"
        "						int err2 = vn_rdwr(UIO_READ, vp, (caddr_t)tmp, (int)length,\n"
        "						    blob->csb_base_offset + (off_t)offset,\n"
        "						    UIO_SYSSPACE, 0, vfs_context_ucred(vfs_context_current()),\n"
        "						    &resid2, current_proc());\n"
        "						md->cs_init(&ctx2);\n"
        "						md->cs_update(&ctx2, tmp, length);\n"
        "						md->cs_final(digest2, &ctx2);\n"
        "						printf(\"PONG native4K: reread off=%llu err=%d resid=%d exp=%02x%02x%02x%02x got=%02x%02x%02x%02x data=%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "						    (unsigned long long)offset, err2, resid2,\n"
        "						    expected[0], expected[1], expected[2], expected[3],\n"
        "						    digest2[0], digest2[1], digest2[2], digest2[3],\n"
        "						    tmp[0], tmp[1], tmp[2], tmp[3], tmp[4], tmp[5], tmp[6], tmp[7]);\n"
        "						kfree_data(tmp, length);\n"
        "					}\n"
        "				}\n"
        "			} else {\n"
        "				os_atomic_inc(&cs_native4k_full_blocks, relaxed);\n"
        "				for (size_t sub = 0; sub < length; sub += PAGE_SIZE) {\n"
        "					size_t bytes = MIN((size_t)PAGE_SIZE, length - sub);\n"
        "					vm_size_t index = (offset + sub) >> PAGE_SHIFT;\n"
        "					md->cs_init(&ctx);\n"
        "					md->cs_update(&ctx, data + sub, bytes);\n"
        "					md->cs_final(digest, &ctx);\n"
        "					memcpy((void *)(storage + index * md->cs_size), digest, md->cs_size);\n"
        "				}\n"
        "			}",
    ),
    # D) summary before publishing (anchor: ad hunk5 ready block)
    (
        "	os_atomic_inc(&cs_native4k_ready_blobs, relaxed);\n"
        "	error = 0;\n"
        "out:",
        "	printf(\"PONG native4K: scan done bad=%u good=%lu\\n\", cs_native4k_badblocks, cs_native4k_full_blocks);\n"
        "	if (cs_native4k_badblocks != 0) {\n"
        "		error = EBADEXEC;\n"
        "		goto out;\n"
        "	}\n"
        "	os_atomic_inc(&cs_native4k_ready_blobs, relaxed);\n"
        "	printf(\"PONG native4K: blob ready limit=%llu\\n\", (unsigned long long)limit);\n"
        "	error = 0;\n"
        "out:",
    ),
]


def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    base_dir = WORK / 'base'
    (base_dir / 'bsd/kern').mkdir(parents=True)
    (base_dir / RELPATH).write_bytes(SRC.read_bytes())
    final = (base_dir / RELPATH).read_text()
    for i, (old, new) in enumerate(ZZ_TRANS, 1):
        n = final.count(old)
        if n != 1:
            raise SystemExit(f'zz transform {i}: anchor occurs {n} times, need exactly 1')
        final = final.replace(old, new)
    print('zz transforms applied: 4')

    modified = final
    for i, (old, new) in enumerate(REPL, 1):
        n = modified.count(old)
        if n != 1:
            raise SystemExit(f'replacement {i}: anchor occurs {n} times, need exactly 1')
        modified = modified.replace(old, new)

    diff = list(difflib.unified_diff(
        final.splitlines(keepends=True), modified.splitlines(keepends=True),
        fromfile='a/' + RELPATH, tofile='b/' + RELPATH, n=3))
    NEW.write_text(''.join(diff))
    print('overlay hunks:', sum(1 for l in diff if l.startswith('@@')))

    series = SERIES.read_text()
    line = NEW_NAME + '\n'
    if line not in series:
        if not series.endswith('\n'):
            series += '\n'
        SERIES.write_text(series + line)

    check = WORK / 'check'
    (check / 'bsd/kern').mkdir(parents=True)
    (check / RELPATH).write_text(final)
    result = subprocess.run(['patch', '-p1', '--dry-run', '-i', str(NEW)],
                            cwd=check, capture_output=True, text=True)
    print(result.stdout.strip(), result.stderr.strip())
    if result.returncode != 0:
        raise SystemExit('overlay does not apply')

    subprocess.run(['git', 'add', '-A'], cwd=TREE, check=True)
    data = subprocess.run(['git', 'diff', '--cached'], cwd=TREE, check=True,
                          capture_output=True).stdout
    OUT.write_bytes(data)
    subprocess.run(['git', 'reset', '-q'], cwd=TREE, check=True)
    print('wrote', OUT, OUT.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
