# 在 Linux 上从零构建 liuqin 的 boot.img 并上机

目标：不依赖 macOS，在一台 x86_64 Linux（或 Windows + WSL2）上，
从官方线刷包里取厂商 UEFI 模块，构建出可以用 `fastboot boot` 启动的镜像。
本文对应 2026-11-18 的实机验证（内核进入 `startRoot`，v39 元类修复通过）。

> 所有步骤都只读设备：`fastboot boot` 把镜像加载进内存，不写任何分区。
> 唯一会写设备的操作在最后"上机"一节，且仍然只是 boot。

## 0. 前提

| 项 | 要求 |
|---|---|
| 主机 | x86_64 Linux（Debian/Ubuntu 推荐），或 Windows 10/11 + WSL2 |
| CPU / 内存 | 8 核以上、16 GB 以上（LLVM 编译吃满核） |
| 磁盘 | 约 40 GB（LLVM 15 GB + 源码 10 GB + 产物） |
| 设备 | 小米平板 6 Pro（liuqin），**BL 已解锁**，能进 fastboot |
| 官方包 | `liuqin_images_OS1.0.14.0.UMYCNXM_*.tgz`（或其它版本，用来抽 `uefi.elf`） |
| 网络 | 能访问 GitHub（大陆网络建议备好代理或镜像） |

## 1. 主机与网络

WSL2 用户先确认发行版已装好：

```bash
wsl -l -v
wsl -d Ubuntu-24.04 -u root -e bash
```

装依赖：

```bash
apt-get update
apt-get install -y build-essential git cmake ninja-build python3 python3-venv \
    unifdef libbsd-dev uuid-dev libssl-dev zlib1g-dev libclang-dev llvm-dev \
    clang lld mtools device-tree-compiler ccache pkg-config libzstd-dev rsync file sshpass
```

如果 `github.com` 被 hosts 指向 `127.0.0.1`，**不要改 hosts**，直接用代理：

```bash
export http_proxy=http://<Windows主机IP>:7897
export https_proxy=$http_proxy
git config --global http.proxy  $http_proxy
git config --global https.proxy $http_proxy
```

> WSL2 里 `<Windows主机IP>` 用 `ip route show default | awk '{print $3}'` 取，
> 通常是 `172.x.x.1`。Windows 侧需要放行防火墙（管理员）：
> `netsh advfirewall firewall add rule name="WSL proxy" dir=in action=allow protocol=TCP localport=7897 remoteip=172.16.0.0/12`

## 2. 仓库布局

工作目录（下文以 `/root/work` 为例）：

```
/root/work/
├── UniXNU/            # 构建驱动（必须用带 Linux 支持的分支）
├── device/            # 设备仓库 UniXNU-liuqin
└── uefi-liuqin/       # Mu-Silicium 固件树（含 Mu_Basecore）
```

拉取（用带 Linux 支持的 UniXNU 分支，2026-11 时是 `1696108518/UniXNU` 的 `liuqin` 分支）：

```bash
cd /root/work
git clone --depth 1 --branch liuqin https://github.com/1696108518/UniXNU.git UniXNU
git clone https://github.com/hhyygg2009/UniXNU-liuqin.git device
git clone --depth 1 https://github.com/hhyygg2009/uefi-liuqin.git uefi-liuqin
```

固件树的子模块（很大，约 1.2 GB）：

```bash
cd /root/work/uefi-liuqin
git submodule update --init --depth 1

# Mu_Basecore 自己的子模块（brotli/openssl 等）也必须初始化，否则 BaseTools 编译失败
cd Mu_Basecore
git submodule update --init --depth 1
```

设备仓库的 `drivers/ShengUfs` 子模块由 `unixnu fetch` 自动拉取。

## 3. Linux 工具链

UniXNU 的 Linux 内核构建需要一套带 XNU 内建函数的自有 clang：

```bash
cd /root/work/UniXNU
sudo scripts/linux/setup-toolchain.py -j $(nproc)
```

它会编译 LLVM，装到 `/opt/unixnu-linux`，同时装好 `lzfse`、`ld64`、`mig` 等。

**已知坑**：`git fetch` 拉 llvm-project 时，经过镜像代理常常卡死（几十 KB 后不动）。
处理办法：让 `setup-toolchain.py` 的 `git_checkout()` 在 fetch 失败/超时后回退到 archive 镜像。
实测 `https://gh-proxy.com/https://github.com/<org>/<repo>/archive/<ref>.zip` 约 4 MB/s。
本仓库补丁：`patches/bringup-2026-11-18/` 不包含该主机侧脚本，按需要手工改。

验证：

```bash
ls /opt/unixnu-linux/bin/lzfse
/opt/unixnu-linux/llvm/bin/clang --version
```

## 4. 从官方线刷包取厂商输入

固件里 93 个 AArch64 模块 + 56 个 Raw 文件都来自官方 `uefi.elf`。

```bash
mkdir -p /root/work/rom && cd /root/work/rom
tar -xzf /path/to/liuqin_images_OS1.0.14.0.UMYCNXM_*.tgz \
    --wildcards '*/images/uefi.elf'
find . -name uefi.elf
```

> `tgz` 是流式压缩，抽一个文件也要解压整个包（约 1–2 分钟）。

导入（需要 `uefi_firmware` 这个 Python 包）：

```bash
pip install --break-system-packages uefi_firmware

cd /root/work/UniXNU
python3 ../device/scripts/import-liuqin-uefi.py \
    --uefi-file /root/work/rom/liuqin_images_*/images/uefi.elf \
    --out /root/work/uefi-liuqin/Binaries/liuqin \
    --version OS1.0.14.0.UMYCNXM
```

成功输出 `93 AArch64 modules, 56 raw files`，目录里有 `Modules/`、`RawFiles/`、`manifest.json`。

## 5. 设备仓库改造（bring-up 配置）

以下改动都在 `device/`（设备仓库）里，完整补丁见
`patches/bringup-2026-11-18/device-bringup.diff`。

### 5.1 `configs/liuqin_defconfig`

```diff
+CONFIG_XNU_BUILD_ARCHIVES=y            # 必须：否则 archives 一个都不构建
-CONFIG_XNU_BOOT_PROGRESS=y
+CONFIG_XNU_BOOT_PROGRESS=n             # 该分支缺 build-boot-progress.py
-CONFIG_XNU_NATIVE_UFS_VERIFIED=y
+CONFIG_XNU_NATIVE_UFS_VERIFIED=n       # VerifiedRoot 闭包未移植
-CONFIG_XNU_VERIFIED_ROOT_PROBE=y
+CONFIG_XNU_VERIFIED_ROOT_PROBE=n
...
+CONFIG_XNU_OWNER_ROOT_AUDIT=n          # 连同 ROOT_TRUST/DATA/CACHE/UNION/BOOT_MANIFEST
+CONFIG_XNU_NATIVE_AES=n
+CONFIG_XNU_NATIVE_RAM_BLOCK=n
+CONFIG_XNU_NATIVE_VIRTIO_BLOCK=n
+CONFIG_XNU_NATIVE_ADRENO=n
+CONFIG_XNU_NATIVE_LEGACY_DISPLAY=n
```

> defconfig 解析器**不接受行尾注释**：注释必须单独成行。

### 5.2 `board.toml`

```toml
# 新树要求 OS profile 的 root 卷 UUID；设备上还没有 iOS userdata，先用占位值
[root]
os_volume_uuid = "18AB5557-DC2D-469B-8758-855E60F5B0DF"

[kernel.prelink]
tool = "kits/XnuPrelink/emit_prelink.py"                  # 旧树是 NativePrelink
kernel = "build/xnu/ios-obj/.../mach.development.bcm2837.unstripped"   # 新树无 .noctf

# payload 参数里同时保留两个名字：驱动读 pmgr，新树校验 sheng-pmgr
"pmgr=2",
"sheng-pmgr=2",
```

如果固件预检因为 `overlapping descriptors: Kernel / Kernel` 报错，可以先跳过预检：
`preflight = []`（该重叠是已知的，生成器会拆成 gap）。

### 5.3 构建脚本

`scripts/build-arm-driver.py`：

```diff
-source = ROOT / 'drivers' / (... else component) / ...
+source = ROOT / 'drivers' / ('ShengUfs' if component == 'NativeUfs' else ...) / ...
-      'NativeUfs':'native-ufs',
+      'NativeUfs':'sheng-ufs',
+      'NativeRamBlock':'ram-block',
-archive = out / ('lib' + component + '.a')
+archive = out / ('libShengUfs.a' if component == 'NativeUfs' else
+                 'libRamBlock.a' if component == 'NativeRamBlock' else 'lib' + component + '.a')
```

`scripts/build-sheng-platform-power.py`：允许从新树路径取 `native_prelink`，
并在缺少作者本机 prelink 基线时回退到 `out/ipsw/<build>/kernelcache.decompressed`
（这是**原始 kernelcache**，按 board.toml 的 sha256 校验，属于真校验而非绕过）。

新增 `scripts/kernel_target.py`（新树才有）：提供 `TRIPLE` / `DEPLOYMENT`。

### 5.4 驱动侧

`drivers/ShengUfs/NativeUfs.cpp` 的 v39 修复见
`patches/driver/liuqin-v39-metaclass-repair.diff`；
本轮额外加了 bring-up 里程牌与 DMA 小尺寸优先，见
`patches/bringup-2026-11-18/nativeufs-bringup.diff`。

其中一处必须的编译修复：

```diff
+#if !defined(NATIVE_VERIFIED_BLOCK) || !NATIVE_VERIFIED_BLOCK
 static bool rootUnauthGateOpen () { ... }
+#endif
```

（`NATIVE_VERIFIED_BLOCK=1` 时该函数没人调用，`-Werror` 会直接失败。）

## 6. XNU 源码与 kernelcache

```bash
cd /root/work/UniXNU
export GITHUB_TOKEN=<你的 token>          # 拉 Apple 头文件时用，避免匿名 API 限流
python3 ./unixnu fetch -D /root/work/device
```

`unixnu fetch` 会把 `xnu`、`libplatform`、`libdispatch`、`corecrypto` 等拉到 `out/feeds/`，
并初始化设备仓库子模块。

取原始 kernelcache（会按 board.toml 的 sha256 校验）：

```bash
python3 ./unixnu ipsw fetch -D /root/work/device
# 产物：out/ipsw/<build>/kernelcache.decompressed
```

## 7. 构建内核

这一步有两个必踩的坑：

1. **补丁幂等**：构建脚本会在 bootstrap 和正式链接两遍都套补丁，
   第二次在已打补丁的树上重打会冲突（`osfmk/arm64/start.s:697`）。
   做法：先手工把补丁一次性打好，然后设 `UNIXNU_PATCH_LIST=manual` 让脚本跳过它自己的循环。

```bash
cd /root/work/UniXNU/out/liuqin/tree/.cache/xnu-work
git checkout -q -- . && git clean -qfd
for p in ../../patches/xnu/*.patch ../../kits/XnuPrelink/patches/*.patch; do
    git apply "$p" || echo "FAIL $p"
done
rm -rf ../../build/xnu          # 强制全量编译，避免半途状态
```

2. **`[root]` 环境变量**：新树要求 `XNU_OWNER_ROOT_VOLUME_UUID`，显式导出最省事。

```bash
cd /root/work/UniXNU
export http_proxy=... https_proxy=...
export GITHUB_TOKEN=<你的 token>
export XNU_OWNER_ROOT_VOLUME_UUID=18AB5557-DC2D-469B-8758-855E60F5B0DF
export UNIXNU_PATCH_LIST=manual
python3 ./unixnu build kernel -D /root/work/device
```

产物 `out/liuqin/kernel/kernel.macho`（约 51 MB）。检查 v39 是否在内核里：

```bash
strings -a out/liuqin/kernel/kernel.macho | grep -m3 "M:reg\|meta-ok"
```

## 8. payload 与 boot.img

```bash
cd /root/work/UniXNU
python3 ./unixnu build payload \
    --kernel out/liuqin/kernel/kernel.macho \
    --unique-chip-id 0x84750A0B0C0D0001 -D /root/work/device

python3 ../device/scripts/wrap-payload-mbr.py \
    out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
```

## 9. 构建固件（关键一步）

```bash
cd /root/work/UniXNU
python3 ./unixnu build firmware \
    --uefi /root/work/uefi-liuqin \
    --edk2 /root/work/uefi-liuqin/Mu_Basecore \
    -D /root/work/device
```

**必须确认的开关**：`uefi-liuqin/Platforms/Xiaomi/liuqinPkg/liuqin.dsc` 的 `[Defines]` 里：

```
DEFINE LIUQIN_INITRD_DISK_ENABLED = 1
```

没有这个开关，`Include/DXE.inc` 与 `Include/APRIORI.inc` 里的
`UniXNURamDiskDxe` 会被整段跳过——**它不会进 FV，ramdisk 永远不会被发布成块设备**，
表现就是 UniXNU 菜单 `no boot entry found` / `fs=0`。这是本轮最隐蔽的一个坑。

验证驱动真的进了 FV：

```bash
ls /root/work/uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/Ffs | grep -i ramdisk
# 75CA63AD-FBAE-4A06-92A0-F937C671251DUniXNURamDiskDxe
```

产物：`Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`（3 MiB）。

## 10. 拼 boot.img

```bash
python3 ./unixnu bootimg \
    --uefi /root/work/uefi-liuqin \
    --fd /root/work/uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --dtb /root/work/uefi-liuqin/Resources/DTBs/liuqin.dtb \
    --ramdisk out/liuqin/payload/payload-mbr.img \
    -D /root/work/device
```

产出 `out/liuqin/boot/boot.img`（约 69.5 MB）。

> `unixnu` 末尾可能报 `boot image header does not match the requested parameters`：
> 这是它对 **v4 header** 按 v0 偏移做校验的误报（镜像本身正确，
> 可核对 `header_size=1584`、`ramdisk_size=68157440`）。镜像照常可用。

## 11. 上机

```bash
adb reboot bootloader
fastboot devices
fastboot boot boot.img       # 注意是 boot，不是 flash
```

屏幕会依次出现：Mu-Silicium 启动日志 → UniXNU 菜单（`xnu` 条目，15 秒自动启动）
→ 内核里程碑（`K…` / `B…` / `U…` / `M:`）。

## 12. 排错表

| 现象 | 原因 | 处理 |
|---|---|---|
| `can't open file scripts/build-boot-progress.py` | 分支缺脚本 | `CONFIG_XNU_BOOT_PROGRESS=n` |
| `defconfig line N: value must be y, n…` | 行尾注释 | 注释独立成行 |
| `test -f "$CRYPTO_ARCHIVE" failed` | archives 未构建 | `CONFIG_XNU_BUILD_ARCHIVES=y` |
| `ModuleNotFoundError: native_prelink` | 找 `kits/XnuPrelink`，旧树是 `NativePrelink` | 改脚本按内容探测；补 `kernel_target.py` |
| `No reference candidate available` | 缺作者本机 prelink 基线 | 回退到原始 `kernelcache.decompressed` |
| `llvm-objcopy: not supported for MachO` | Mach-O 不支持 `--globalize-symbol` | 改 nlist `n_type` 字节 |
| `dwarfdump: not found` | Linux 工具链没有 | 垫片到 `llvm-dwarfdump` |
| 缺 `armcpu_spi_mask` / 多 `arm64_platform_sleep_hook` | ArmCpu 版本不匹配 | 钉 `a823383` |
| `osfmk/arm64/start.s:697 patch does not apply` | 二次套补丁 | 预打补丁 + `UNIXNU_PATCH_LIST` |
| UniXNU 菜单没有条目、红字 `fs=0` | `LIUQIN_INITRD_DISK_ENABLED` 未开 | DSC 里 `DEFINE …= 1` |
| 菜单有 `xnu` 条目但启动后停住 | 内核侧问题 | 看最后一行 `U:h:*` 里程碑定位 |

## 13. 当前状态与后续

本轮实机到达 `U:72:h:alloc1`，卡在 `hostBringUp()` 里
`IOBufferMemoryDescriptor::inTaskWithOptions` 的分配**调用本身**（改成最小 1 槽同样挂住，
与尺寸无关）。详见
[`boot-round-v39-2026-11-18.md`](boot-round-v39-2026-11-18.md)。

再往后（根卷、userdata、用户态）不在本文范围；注意 **写 iOS userdata 会清空 Android 数据**。
