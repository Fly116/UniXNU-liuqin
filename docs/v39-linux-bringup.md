# v39：Linux 构建链与实机状态（2026-11-18）

## 结果

| 项 | 状态 |
|---|---|
| 无 macOS 构建链（固件 / 内核 / prelink / payload / boot.img） | ✅ 本地产出 |
| 固件启动 → UniXNU 菜单 → payload 卷挂载 | ✅ 实机 |
| 内核跑到 `bsd_init` → `startRoot` | ✅ 实机 |
| v39 元类修复 | ✅ **实机通过** |
| UFS 控制器 bring-up | ⚠️ 卡在 DMA 分配 |
| iOS 根卷 / 用户态 | ⛔ 未开始 |

实机证据（`fastboot boot`，纯内存运行）：

```
NativeUfs: M:reg pre p=0xfffffff007adb6b0 link=0xfffffff007add1d0   ← 家族元类，不是毒值
NativeUfs: M:reg pre fixed link=0xfffffff007add1d0
U:meta-ok                                                          ← ABI 闸 + 链校验通过
M:stalled post cnt=1 … M:stalled scan ok …                         ← 本类正常登记
```

**当前卡点**：`hostBringUp()` 里 `IOBufferMemoryDescriptor::inTaskWithOptions(...)` 调用不返回；
改成最小 1 槽（`h:alloc1`）**同样挂住**，与尺寸/连续性无关。下一步换 `IOMallocContiguous` /
不带 `kIOMemoryPhysicallyContiguous` 的 `withOptions` + 手工取物理段。

本轮的设备仓库与驱动改动：`patches/bringup-2026-11-18/`。

## 复现

### 1. 环境

x86_64 Linux（或 WSL2 Ubuntu 24.04），8 核 / 16 GB / 40 GB 磁盘；设备 BL 已解锁；
准备一个官方线刷包（以 `OS1.0.14.0.UMYCNXM` 为例）用来抽 `uefi.elf`。

```bash
apt-get install -y build-essential git cmake ninja-build python3 unifdef libbsd-dev \
    uuid-dev libssl-dev zlib1g-dev libclang-dev llvm-dev clang lld mtools \
    device-tree-compiler ccache pkg-config libzstd-dev rsync
```

GitHub 不通就用代理（WSL2 里指向 Windows 主机 IP，通常是 `172.x.x.1`，Windows 侧需放行端口）：

```bash
export http_proxy=http://172.21.64.1:7897 https_proxy=$http_proxy
git config --global http.proxy $http_proxy && git config --global https.proxy $http_proxy
```

### 2. 代码

```bash
cd /root/work
git clone --depth 1 --branch liuqin https://github.com/1696108518/UniXNU.git UniXNU   # 带 Linux 支持的分支
git clone https://github.com/hhyygg2009/UniXNU-liuqin.git device
git clone --depth 1 https://github.com/hhyygg2009/uefi-liuqin.git uefi-liuqin
cd uefi-liuqin && git submodule update --init --depth 1
cd Mu_Basecore && git submodule update --init --depth 1    # 漏了会 BaseTools 编译失败
```

### 3. 工具链（LLVM，一次性约 30–60 分钟）

```bash
cd /root/work/UniXNU
sudo scripts/linux/setup-toolchain.py -j $(nproc)      # 装到 /opt/unixnu-linux
```

> 拉 llvm-project 时若走镜像卡死，改让 `git_checkout()` 回退到
> `https://gh-proxy.com/https://github.com/<org>/<repo>/archive/<ref>.zip`（实测约 4 MB/s）。

### 4. 厂商输入（固件模块来源）

```bash
cd /root/work/rom && tar -xzf liuqin_images_OS1.0.14.0.UMYCNXM_*.tgz --wildcards '*/images/uefi.elf'
pip install --break-system-packages uefi_firmware
cd /root/work/UniXNU
python3 ../device/scripts/import-liuqin-uefi.py \
    --uefi-file /root/work/rom/liuqin_images_*/images/uefi.elf \
    --out /root/work/uefi-liuqin/Binaries/liuqin --version OS1.0.14.0.UMYCNXM
```

输出应为 `93 AArch64 modules, 56 raw files`。

### 5. 应用本轮配置改动

设备仓库四改一加（完整 diff 在 `patches/bringup-2026-11-18/device-bringup.diff`）：

```bash
cd /root/work/device
git apply /path/to/patches/bringup-2026-11-18/device-bringup.diff
```

内容包括：

- `configs/liuqin_defconfig`：开 `CONFIG_XNU_BUILD_ARCHIVES=y`；关
  `BOOT_PROGRESS`、`NATIVE_UFS_VERIFIED`、`VERIFIED_ROOT_PROBE`、`OWNER_*`、`NATIVE_AES`、
  `NATIVE_RAM_BLOCK`、`NATIVE_VIRTIO_BLOCK`、`NATIVE_ADRENO`、`NATIVE_LEGACY_DISPLAY`。
  （这些关闭项都依赖作者本机归档，Linux 树里没有；面板里程碑不受影响。）
- `board.toml`：`[root] os_volume_uuid` 占位；prelink 用 `kits/XnuPrelink`、内核用 `.unstripped`；
  payload 参数同时带 `pmgr=2` 与 `sheng-pmgr=2`。
- `scripts/build-arm-driver.py`：`NativeUfs → drivers/ShengUfs`、归档 `libShengUfs.a` / `libRamBlock.a`。
- `scripts/build-sheng-platform-power.py`：新树路径 + 缺 prelink 基线时回退原始 kernelcache。

驱动侧打 v39 补丁与 bring-up 补丁：

```bash
cd /root/work/device/drivers/ShengUfs
git apply /path/to/patches/driver/liuqin-v39-metaclass-repair.diff
git apply /path/to/patches/bringup-2026-11-18/nativeufs-bringup.diff
```

### 6. 构建内核

```bash
cd /root/work/UniXNU
export GITHUB_TOKEN=<token>                      # 拉 Apple 头文件
export XNU_OWNER_ROOT_VOLUME_UUID=18AB5557-DC2D-469B-8758-855E60F5B0DF
export UNIXNU_PATCH_LIST=manual                  # 补丁已手工打好，跳过脚本自己的循环

# 一次性把补丁打全（脚本会在两遍构建里重复套补丁，不预处理必然冲突）
cd out/liuqin/tree/.cache/xnu-work
git checkout -q -- . && git clean -qfd
for p in ../../patches/xnu/*.patch ../../kits/XnuPrelink/patches/*.patch; do git apply "$p"; done
rm -rf ../../build/xnu

cd /root/work/UniXNU
python3 ./unixnu build kernel -D /root/work/device
strings -a out/liuqin/kernel/kernel.macho | grep -m2 "M:reg\|meta-ok"   # 确认 v39 在内核里
```

### 7. payload 与 boot.img

```bash
python3 ./unixnu build payload --kernel out/liuqin/kernel/kernel.macho \
    --unique-chip-id 0x84750A0B0C0D0001 -D /root/work/device
python3 ../device/scripts/wrap-payload-mbr.py \
    out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
```

### 8. 固件（有一个必须打开的开关）

```bash
python3 ./unixnu build firmware --uefi /root/work/uefi-liuqin \
    --edk2 /root/work/uefi-liuqin/Mu_Basecore -D /root/work/device
```

**先确认** `uefi-liuqin/Platforms/Xiaomi/liuqinPkg/liuqin.dsc` 的 `[Defines]` 里有：

```
DEFINE LIUQIN_INITRD_DISK_ENABLED = 1
```

没有它，`DXE.inc` / `APRIORI.inc` 里的 `UniXNURamDiskDxe` 不会打包进 FV，
ramdisk 永远不会成为块设备，菜单会报 `no boot entry found`（红字 `fs=0`）。
这是本轮最隐蔽的坑。

验证并拼镜像：

```bash
ls uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/Ffs | grep -i ramdisk
python3 ./unixnu bootimg --uefi /root/work/uefi-liuqin \
    --fd uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --dtb uefi-liuqin/Resources/DTBs/liuqin.dtb \
    --ramdisk out/liuqin/payload/payload-mbr.img -D /root/work/device
```

> `bootimg` 末尾报 `boot image header does not match...` 是它对 v4 header 的误报，镜像可用。

### 9. 上机

```bash
adb reboot bootloader && fastboot boot out/liuqin/boot/boot.img
```

菜单 15 秒后自动启动 `xnu`。看到的里程牌顺序：

```
K49:PE_init_iokit → … → B68:bsd_init → … → M:stalled scan ok →
U:60:start-root → U:61:r0-enter → U:62:r1-base → U:64:r2-abi →
M:reg pre … → U:65:r3-adopt → U:66:meta-ok → U:67:r4-host →
U:68:h:controller map → U:69:h:DMA allocation → U:72:h:alloc1   ← 当前终点
```

## 排错（按出现频率）

| 现象 | 原因 | 处理 |
|---|---|---|
| `test -f "$CRYPTO_ARCHIVE" failed` | archives 没构建 | `CONFIG_XNU_BUILD_ARCHIVES=y` |
| `ModuleNotFoundError: native_prelink` | 找 `kits/XnuPrelink`，旧树叫 `NativePrelink` | 用本页的 device diff；补 `kernel_target.py` |
| `No reference candidate available` | 缺作者本机 prelink 基线 | 回退原始 `kernelcache.decompressed`（本页 diff 已含） |
| `patch does not apply osfmk/arm64/start.s:697` | 补丁被套两遍 | 预打补丁 + `UNIXNU_PATCH_LIST=manual` |
| `llvm-objcopy: not supported for MachO` | 不支持 `--globalize-symbol` | 改 nlist `n_type \|= N_EXT` |
| `dwarfdump: not found` | Linux 工具链没有 | 垫片到 `llvm-dwarfdump` |
| 菜单 `no boot entry found` / `fs=0` | `LIUQIN_INITRD_DISK_ENABLED` 未开 | DSC 加 `DEFINE … = 1` |
| 菜单有条目但启动卡住 | 内核侧 | 看最后一行 `U:h:*` |

## 产物

`boot.img` 一个文件即可测试（固件 + DTB + payload 全在里面），**不要**在设备上 `flash`：

```bash
fastboot boot boot-v39-2026-11-18.img
```

| 文件 | 大小 | sha256 |
|---|---|---|
| `boot-v39-2026-11-18.img` | 69,529,600 | `2f40926049479ec824c0717d39bf51e2ae173e38c2f42fcf53d42ffb8a136dfd` |
| `SILICIUM_UEFI.fd` | 3,145,728 | `1cb68658a887df07809bed823630c6cb53374a1183cb3d5264fa82140934a5e6` |
| `kernel.macho` | 51,126,272 | `2dfbe41694b74934e21c9eb6622a4deb5d463a6a389d0a5e8f9a5b4e3427b32e` |
| `payload-mbr.img` | 68,157,440 | `a10c7c78d9c6ddaea5e62508cf1ed882fb0c15d3470e87018d44978fd27c2be9` |

下载见本仓库的 Release **`v39-linux-2026-11-18`**。

## 注意

- 全部操作只 `fastboot boot`，不写任何分区；重启即回 Android。
- 后续若挂 iOS 根卷需要 `fastboot flash userdata`，**会清空 Android 数据**，务必先备份。
