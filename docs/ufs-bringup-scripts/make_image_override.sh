#!/bin/bash
# Assemble a liuqin boot image with overridable firmware + DTB (new-firmware test).
#
#   FD_OVERRIDE    path to SILICIUM_UEFI.fd   (default: the d97 sandbox build)
#   UEFI_OVERRIDE  path to the UEFI source tree used by unixnu bootimg/finalize
#   CAPE_OVERRIDE  path to the Cape SoC DTB appended to the kernel slot
#
# usage: make_image_override.sh <run-id> <out.img> [kernel.macho path]
set -euo pipefail

RUN="${1:?usage: make_image_override.sh <run-id> <out.img> [kernel]}"
OUT="${2:?usage: make_image_override.sh <run-id> <out.img> [kernel]}"
KERNEL="${3:-}"

FD="${FD_OVERRIDE:-/root/work/uefi-liuqin-d97/repo/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd}"
UEFI_D97="${UEFI_OVERRIDE:-/root/work/uefi-liuqin-d97/repo}"
CAPE="${CAPE_OVERRIDE:-/root/work/uefi-liuqin/Resources/DTBs/liuqin.dtb}"
HW_DTB=/root/work/up-liuqin/build/liuqin/liuqin.dtb
LAYOUT=/mnt/f/liuqin_ios/_dl/ci/meta/volume-layout.json
BASE_PAYLOAD="${PAYLOAD_OVERRIDE:-/root/work/UniXNU-new/out/liuqin/payload/payload.img}"
WORK=/root/work/v112-${RUN}-override

PRODUCTS="/root/work/ci-kernel-${RUN}/products/products"
if [ ! -d "$PRODUCTS" ]; then
  bash /mnt/f/liuqin_ios/scratch/ci_fetch_kernel.sh "$RUN" kernel-upstream-encrypted
fi
if [ -z "$KERNEL" ]; then
  KERNEL="$(find "$PRODUCTS" -maxdepth 3 -type f -name kernel.macho | head -1)"
fi
[ -f "$KERNEL" ] || { echo "no kernel.macho found" >&2; exit 1; }
echo "FD:     $FD"
echo "UEFI:   $UEFI_D97"
echo "CAPE:   $CAPE"
echo "kernel: $KERNEL ($(stat -c%s "$KERNEL") B)"

rm -rf "$WORK"
mkdir -p "$WORK/payload" "$WORK/boot"
cp "$BASE_PAYLOAD" "$WORK/payload/payload.img"
echo "replacing kernel.macho inside the payload FAT"
MTOOLS_SKIP_CHECK=1 mdel -i "$WORK/payload/payload.img" ::/EFI/UniXNU/Payloads/kernel.macho 2>/dev/null || true
MTOOLS_SKIP_CHECK=1 mcopy -o -i "$WORK/payload/payload.img" "$KERNEL" ::/EFI/UniXNU/Payloads/kernel.macho

cd /root/work/UniXNU-new
python3 ./unixnu bootimg --uefi "$UEFI_D97" --fd "$FD" --dtb "$CAPE" \
  --ramdisk /dev/null -D /root/work/device-new 2>&1 | tail -3 || true
cp /root/work/UniXNU-new/out/liuqin/boot/boot.img "$WORK/boot/boot.img"

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
  --hardware-dtb "$HW_DTB" 2>&1 | tail -6

cp "$WORK/boot/liuqin-xnu-initial.img" "$OUT"
echo "== result =="
ls -l "$OUT"
sha256sum "$OUT"
