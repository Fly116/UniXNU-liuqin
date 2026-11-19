# 2026-11-19 bring-up session: what was found and fixed

This file records the engineering conclusions of one long on-device session. Every
claim below was observed on the tablet (Xiaomi Pad 6 Pro, `liuqin`, SM8475) via
`fastboot boot` of an in-memory image; nothing here was written to any partition.

## Boot progress that was reached

```
U139:probe-nub            IOKit matches NativeUfs a second time, after bsd_init
U140:start-enter          NativeUfs::start() entered
U141:start-root
U142:blk-registered       NativeUfsBlock::start(): registerService() returned
U143:blk-matched          startMatching() returned
U146:root-pub-SystemOS    the SystemOS window was started as a block device
U147:root-media-timeout   no IOMedia appeared for it -> UFS ROOT FAILURE
```

Before this session the boot never got past the storage bring-up; now it runs the
whole of `bsd_init` up to the buffer cache and then publishes block devices.

## Fixes that are confirmed on hardware

1. **`liuqin_usb=1` blocked the boot at `bsd_init.c:usb_start`.**
   `liuqin_usb_debug_start()` hangs on this platform; the boot arg is now removed.
   Milestone counter went 114 -> 136 once it was off.

2. **`IOSleep()` never returns on this platform.**
   The publisher waited for IOMedia with `300 x IOSleep(100)`. The first sleep never
   woke, so the wait neither succeeded nor timed out and the panel showed no further
   progress at all. Replaced with a spin + `thread_yield_to_preemption()` loop, with
   `IOService::startDeferredMatches()` poked between passes. The wait now terminates
   and reports `root-media-timeout` instead of hanging forever.

3. **`IOBlockStorageDevice` relocations needed the prelink slide.**
   `scripts/build-liuqin-ufs-bindings.py` bound the storage-family symbols to the raw
   21H461 kernelcache VAs, while `emit_prelink.py` places the kext at `cache VA + slide`
   (`-0x1000000`). `new NativeUfsBlock` therefore branched 16 MiB above the real
   constructor, into zero-filled `__PLK_TEXT_EXEC` padding (`UDF #0`). The constructor
   never ran and block publication could not start. Fixed by applying the board-pinned
   slide to the bindings; the same stale value is what the H16 metaclass "scribble" was.

4. **A device-tree parent cannot publish services.**
   `IOService::registerService()` silently returns when the service has no path to the
   registry root in `gIOServicePlane`. The windows were attached to `NativeUfs`, which is
   attached to the device-tree node `xiaomi,liuqin` — that node has no service-plane
   parent, so nothing was ever registered (`state=0x0`, plane counts all zero).
   The windows are now attached to, and started with, the platform expert
   (`ArmDTPlatform`), which does reach the root: `REGPUBLISH ok` is printed for both
   windows.

## Instrumentation that proved useful (and one that lies)

* `liuqin_milestone(tag, msg)` writes the panel directly. It is the only reliable
  console very early, and its counter makes the last reached step unambiguous.
* A persistent journal page in the unused tail of the `unixnu` partition works, but
  **only during early boot**: UFS writes start to hang after `bsd_init`'s buffer-cache
  setup, so journal probes placed later block the very path they are meant to observe.
  Milestone journaling was implemented, then removed again for this reason.
* `IOService::getMatchingServices()` returns zero even for classes that definitely have
  registered instances at this point, so plane counts are **not** a valid signal here.

## Open problem at the end of the session

`startRoot()` runs twice: once from the early root-device match (before `bsd_init`),
once again after `probe-nub`. The early pass publishes and registers both windows
(`REGPUBLISH ok` twice). The second pass rebuilds them, never gets IOMedia and reports
`UFS ROOT FAILURE`, which aborts the root flow.

An idempotence guard (`gRootPublicationDone`) was added and is present in the kernel
image (the `root-already-published` string is in the binary) but did not fire on the
second call, so the early pass apparently does not reach the same code path that sets
it. Next step: print the flag value at `startRoot()` entry, and if the two calls really
belong to different driver instances, move the state out of a translation-unit static
(e.g. a kernel global keyed by provider) or make publication a property of the
`NativeUfs` instance that owns the windows.
