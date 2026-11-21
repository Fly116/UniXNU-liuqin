#!/bin/bash
# Assemble the flashable liuqin boot image from one kernel-upstream run:
#   * kernel slot: gzip(BootShim + UEFI FD) + the stock Cape SoC DTB, FD from the
#     local sandbox build (menu patch applied);
#   * ramdisk: the run's payload.img in the PONGFAT1 envelope;
#   * ADT/manifest: official finalize-pong-adt.py, the parameters upstream's
#     package.yml passes (liuqin board, --ufs-probe, 8 GiB DRAM, 4 GiB window, 1 CPU).
# usage: make_v112.sh <run-id> <out.img>
set -euo pipefail

RUN="${1:?usage: make_v112.sh <run-id> <out.img>}"
OUT="${2:?usage: make_v112.sh <run-id> <out.img>}"

FD=/root/work/uefi-liuqin-d97/repo/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
UEFI_D97=/root/work/uefi-liuqin-d97/repo
CAPE=/root/work/uefi-liuqin/Resources/DTBs/liuqin.dtb
HW_DTB=/root/work/up-liuqin/build/liuqin/liuqin.dtb
LAYOUT=/mnt/f/liuqin_ios/_dl/ci/meta/volume-layout.json
WORK=/root/work/v112-${RUN}

bash /mnt/f/liuqin_ios/scratch/ci_fetch_kernel.sh "$RUN" kernel-upstream-encrypted
PRODUCTS="/root/work/ci-kernel-${RUN}/products"

PAYLOAD="$(find "$PRODUCTS" -maxdepth 4 -type f -name payload.img | head -1)"
KERNEL="$(find "$PRODUCTS" -maxdepth 4 -type f -name kernel.macho | head -1)"
[ -n "$PAYLOAD" ] || { echo "no payload.img in ${PRODUCTS}" >&2; exit 1; }
echo "payload: ${PAYLOAD} ($(stat -c%s "$PAYLOAD") B)"
echo "kernel:  ${KERNEL:-none}"
sha256sum "$PAYLOAD" "$KERNEL" 2>/dev/null || true

rm -rf "$WORK"
mkdir -p "$WORK/payload" "$WORK/boot"
cp "$PAYLOAD" "$WORK/payload/payload.img"

# The release boot.img only has to carry the firmware in its kernel slot: finalize
# replaces the appended DTB with the stock Cape DTB and the ramdisk with the
# PONGFAT1 payload, so it is built with an empty ramdisk.
cd /root/work/UniXNU-new
python3 ./unixnu bootimg --uefi "$UEFI_D97" --fd "$FD" --dtb "$CAPE" \
  --ramdisk /dev/null -D /root/work/device-new 2>&1 | tail -3 || true
BUILT=/root/work/UniXNU-new/out/liuqin/boot/boot.img
if [ ! -s "$BUILT" ]; then
  echo "bootimg produced nothing; falling back to the v106 kernel slot" >&2
  cp /mnt/f/liuqin_ios/boot-v109-cape.img "$WORK/boot/boot.img"
else
  cp "$BUILT" "$WORK/boot/boot.img"
fi

cd /root/work/up-liuqin
PONG_HARDWARE_DTB="$HW_DTB" UNIXNU_UEFI="$UEFI_D97" \
python3 scripts/finalize-pong-adt.py \
  --work-dir "$WORK" \
  --uefi "$UEFI_D97" \
  --board liuqin \
  --abl-dtb "$CAPE" \
  --unique-chip-id 84750a0b \
  --ufs-probe \
  --volume-layout "$LAYOUT" \
  --hardware-dtb "$HW_DTB"

cp "$WORK/boot/liuqin-xnu-initial.img" "$OUT"
ls -l "$OUT"
sha256sum "$OUT"
