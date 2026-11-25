#!/usr/bin/env python3
"""ad variant: layer diagnostics into the pong native4K signature-hash-cache.

Base = cached xnu source (.cache/xnu-work/bsd/kern/ubc_subr.c, which is the
0001-pong-darwin24 form) with zz-pong-main-native4k-cache-io.patch applied,
i.e. exactly what CI builds for V..ac. The new overlay patch adds printf at
the five decision points of cs_native4k_prepare so the on-screen log can tell
apart: vn_rdwr failure / missing expected hash slot / block-hash mismatch
(with expected vs computed digest vs raw bytes read back) / success.
"""
import difflib
import shutil
import subprocess
from pathlib import Path

WORK = Path('/root/work/ad-work')
TREE = Path('/root/work/v134-variant-v')
ZZ = TREE / 'patches/xnu-ipados18/zz-pong-main-native4k-cache-io.patch'
SERIES = TREE / 'patches/xnu-ipados18/series'
NEW_NAME = 'zzzzzzzzzzzzzzzzz-liuqin-native4k-diag.patch'
NEW = TREE / 'patches/xnu-ipados18' / NEW_NAME
OUT = Path('/root/work/ad.patch')
SRC = Path('/root/work/UniXNU-new/out/liuqin/tree/.cache/xnu-work/bsd/kern/ubc_subr.c')
RELPATH = 'bsd/kern/ubc_subr.c'

ZZ_TRANS = [
    # zz-pong-main-native4k-cache-io.patch hunk 1: boot-cost counters
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
    # hunk 2: chunk + ioflags locals
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
    # hunk 3: the 16384-block loop becomes the 1 MiB chunk loop
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
    # hunk 4: buffer free size follows the chunk size
    (
        "	kfree_data(buffer, 16384);",
        "	kfree_data(buffer, CS_NATIVE4K_CHUNK);",
    ),
]

REPL = [
    # 1) after the codeLimit gate: one line per blob being prepared
    (
        "	limit = ntohl(cd->codeLimit);\n"
        "	if (!limit || ((ntohl(cd->version) >= CS_SUPPORTSCODELIMIT64) &&",
        "	limit = ntohl(cd->codeLimit);\n"
        "	printf(\"PONG native4K: prepare base=%lld limit=%llu mem=%llu hashsize=%u\\n\",\n"
        "	    (long long)blob->csb_base_offset, (unsigned long long)limit,\n"
        "	    (unsigned long long)blob->csb_mem_size, (unsigned)md->cs_size);\n"
        "	if (!limit || ((ntohl(cd->version) >= CS_SUPPORTSCODELIMIT64) &&",
    ),
    # 2) vn_rdwr failure
    (
        "		if (error || resid) {\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		for (size_t block = 0; block < chunk_length; block += 16384) {",
        "		if (error || resid) {\n"
        "			printf(\"PONG native4K: vn_rdwr fail pos=%lld len=%zu err=%d resid=%d\\n\",\n"
        "			    (long long)position, chunk_length, error, resid);\n"
        "			error = error ? error : EIO;\n"
        "			goto out;\n"
        "		}\n"
        "		for (size_t block = 0; block < chunk_length; block += 16384) {",
    ),
    # 3) expected hash slot missing
    (
        "			if (expected == NULL) {\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}",
        "			if (expected == NULL) {\n"
        "				printf(\"PONG native4K: no expected hash off=%llu slots=%u\\n\",\n"
        "				    (unsigned long long)offset, ntohl(cd->nCodeSlots));\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}",
    ),
    # 4) block hash mismatch: expected vs computed vs the bytes we read back
    (
        "			if (bcmp(expected, digest, md->cs_size)) {\n"
        "				os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}",
        "			if (bcmp(expected, digest, md->cs_size)) {\n"
        "				os_atomic_inc(&cs_validate_page_bad_hash, relaxed);\n"
        "				printf(\"PONG native4K: bad hash off=%llu len=%zu \"\n"
        "				    \"exp=%02x%02x%02x%02x%02x%02x%02x%02x \"\n"
        "				    \"got=%02x%02x%02x%02x%02x%02x%02x%02x \"\n"
        "				    \"data=%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\\n\",\n"
        "				    (unsigned long long)offset, length,\n"
        "				    expected[0], expected[1], expected[2], expected[3],\n"
        "				    expected[4], expected[5], expected[6], expected[7],\n"
        "				    digest[0], digest[1], digest[2], digest[3],\n"
        "				    digest[4], digest[5], digest[6], digest[7],\n"
        "				    data[0], data[1], data[2], data[3], data[4], data[5],\n"
        "				    data[6], data[7], data[8], data[9], data[10], data[11],\n"
        "				    data[12], data[13], data[14], data[15]);\n"
        "				error = EBADEXEC;\n"
        "				goto out;\n"
        "			}",
    ),
    # 5) success
    (
        "	os_atomic_inc(&cs_native4k_ready_blobs, relaxed);\n"
        "	error = 0;\n"
        "out:",
        "	os_atomic_inc(&cs_native4k_ready_blobs, relaxed);\n"
        "	printf(\"PONG native4K: blob ready limit=%llu total_blocks=%lu\\n\",\n"
        "	    (unsigned long long)limit, cs_native4k_full_blocks);\n"
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
