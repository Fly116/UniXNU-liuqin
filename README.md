# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

把 iOS 17 的 XNU 内核移植到小米平板 6 Pro 的工程记录。
**所有测试都只 `fastboot boot`（纯内存），不写设备任何分区。**

## 当前状态（2026-11-19）

| 项 | 状态 |
|---|---|
| Linux 构建链（固件 / 内核 / prelink / payload / boot.img） | ✅ 全部本地产出，不需要 macOS |
| 固件启动 → UniXNU 菜单 → payload 卷挂载 | ✅ 实机 |
| 内核跑到 `bsd_init` → `startRoot` | ✅ 实机 |
| v39 元类修复（H16-F） | ✅ **实机通过** |
| UFS 控制器初始化 + 链路启动 + LUN 就绪 | ✅ **实机打通** |
| 读 userdata GPT / 解析根布局 | ✅ **实机打通** |
| iOS 根卷（需要 iOS userdata） | ⛔ 卡在 `root manifest rejected`（预期） |
| 用户态 / 桌面 | ⛔ 未开始 |

实机证据（`fastboot boot`，2026-11-19 最后一轮）：

```
NativeUfs: M:reg pre p=0xfffffff007adb6b0 link=0xfffffff007add1d0   ← 家族元类，不是毒值
U:meta-ok                                                          ← ABI 闸 + 链校验通过
U:72:h:pre-used                                                    ← STARTUP 阶段预留的 DMA 区
U:80:h:stopq-ok → U:81:h:NOP OUT → U:83:h:nop-ok                   ← UniPro 链路起来了
U:84:h:power mode query → U:85:h:LUN ready                          ← 设备应答
U:86:root-bring-up-ok → U:87:root-layout-ok                        ← 读到 GPT，布局解析成功
UFS BOOT FAILURE: root manifest rejected                           ← 预期：设备上还没有 iOS 根镜像
```

诊断行同时给出控制器状态（`op=28` 即 READ(10) 已成功执行、`ocs=00`），
说明**块设备读写路径本身是通的**，只差一份合法的 iOS 根清单。

### 2026-11-19 的根因链（全部实机证实）

1. **`IOMapper` 从未被初始化**：`IOMapper::gSystem` 初始是 `kUnknown`（带等待位），
   只有 `IOMapper::setMapperRequired()` 会把它推到 `kNoMapper`/`kHasMapper`，
   而苹果平台的 platform expert 才会调用它。非苹果平台没人调，
   任何 `IOBufferMemoryDescriptor` 创建都可能在 `waitForSystemMapper()` 里永久睡眠。
   → 驱动里显式把 `gSystem` 置 0。
2. **wired（不可分页）描述符的 `prepare()` 挂死**（`h:c3-wired`）；pageable 正常。
   → 不走 IOKit 描述符，直接 `kmem_alloc_contig()` + `ml_vtophys()`。
3. **早期运行时连续页分配不可靠**（10 次里约半数卡在页队列扫描），
   且等待基元依赖的 `mach_absolute_time()` 在该阶段不前进。
   → 在 `STARTUP_SUB_EARLY_BOOT` 阶段预先分配 DMA 区（`h:pre-used`），
   并把完成等待的 `IODelay` 换成固定次数忙循环。

## 快速开始（测试已有镜像）

下载 [Release `v39-2026-11-19`](https://github.com/Fly116/UniXNU-liuqin/releases/tag/v39-2026-11-19)，
然后：

```bash
adb reboot bootloader
fastboot boot boot-v39-prealloc.img
```

菜单 15 秒后自动启动 `xnu`，屏幕会一路走到
`U:87:root-layout-ok` 并以 `UFS BOOT FAILURE: root manifest rejected` 结束——
这就是当前这台设备能达到的最远位置。

从零构建见下文[「v39：Linux 构建链与实机状态」](#v39linux-构建链与实机状态2026-11-18)。

## 目录

- [v39：Linux 构建链与实机状态（2026-11-18）](#v39linux-构建链与实机状态2026-11-18)
- [v39：元类 superClassLink 的受控修复（H16-F）](#v39元类-superclasslink-的受控修复h16-f)
- [liuqin (Xiaomi Pad 6 Pro / SM8475) UniXNU 启动进展](#liuqin-xiaomi-pad-6-pro--sm8475-unixnu-启动进展)
- [实机逐轮判读：v35 → v38（2026-11-16 → 2026-11-17）](#实机逐轮判读v35--v382026-11-16--2026-11-17)
- [liuqin 适配路线（Stage 6 存储/root 主线）— 2026-11-15，无机窗口期研究产出](#liuqin-适配路线stage-6-存储root-主线-2026-11-15无机窗口期研究产出)
- [liuqin 移植计划](#liuqin-移植计划)
- [liuqin 硬件底账](#liuqin-硬件底账)
- [liuqin stock UEFI 厂商输入（已抽出）](#liuqin-stock-uefi-厂商输入已抽出)
- [内核 USB 调试口（liuqin）](#内核-usb-调试口liuqin)

## 仓库结构

```
patches/
  driver/              NativeUfs 的 v39 补丁
  bringup-2026-11-18/  本轮设备仓库与驱动的实际 diff
tests/metaclass-simtest/  元类场景主机仿真（A–E）
drivers/ShengUfs/      UFS 驱动（子模块指向 fork 分支 liuqin-sm8475-v39）
```

## 注意

- 全程只用 `fastboot boot`，不 `flash`；重启即回 Android。
- 后续挂 iOS 根卷需要 `fastboot flash userdata`，**会清空 Android 数据**，务必先备份。
- 上游主线是 [hhyygg2009/UniXNU-liuqin](https://github.com/hhyygg2009/UniXNU-liuqin)；
  本仓库是其 fork 上的实机验证与 Linux 构建链记录。


---

## v39：Linux 构建链与实机状态（2026-11-18）

### 结果

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

### 复现

#### 1. 环境

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

#### 2. 代码

```bash
cd /root/work
git clone --depth 1 --branch liuqin https://github.com/1696108518/UniXNU.git UniXNU   # 带 Linux 支持的分支
git clone https://github.com/hhyygg2009/UniXNU-liuqin.git device
git clone --depth 1 https://github.com/hhyygg2009/uefi-liuqin.git uefi-liuqin
cd uefi-liuqin && git submodule update --init --depth 1
cd Mu_Basecore && git submodule update --init --depth 1    # 漏了会 BaseTools 编译失败
```

#### 3. 工具链（LLVM，一次性约 30–60 分钟）

```bash
cd /root/work/UniXNU
sudo scripts/linux/setup-toolchain.py -j $(nproc)      # 装到 /opt/unixnu-linux
```

> 拉 llvm-project 时若走镜像卡死，改让 `git_checkout()` 回退到
> `https://gh-proxy.com/https://github.com/<org>/<repo>/archive/<ref>.zip`（实测约 4 MB/s）。

#### 4. 厂商输入（固件模块来源）

```bash
cd /root/work/rom && tar -xzf liuqin_images_OS1.0.14.0.UMYCNXM_*.tgz --wildcards '*/images/uefi.elf'
pip install --break-system-packages uefi_firmware
cd /root/work/UniXNU
python3 ../device/scripts/import-liuqin-uefi.py \
    --uefi-file /root/work/rom/liuqin_images_*/images/uefi.elf \
    --out /root/work/uefi-liuqin/Binaries/liuqin --version OS1.0.14.0.UMYCNXM
```

输出应为 `93 AArch64 modules, 56 raw files`。

#### 5. 应用本轮配置改动

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

#### 6. 构建内核

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

#### 7. payload 与 boot.img

```bash
python3 ./unixnu build payload --kernel out/liuqin/kernel/kernel.macho \
    --unique-chip-id 0x84750A0B0C0D0001 -D /root/work/device
python3 ../device/scripts/wrap-payload-mbr.py \
    out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
```

#### 8. 固件（有一个必须打开的开关）

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

#### 9. 上机

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

### 排错（按出现频率）

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

### 产物

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

### 注意

- 全部操作只 `fastboot boot`，不写任何分区；重启即回 Android。
- 后续若挂 iOS 根卷需要 `fastboot flash userdata`，**会清空 Android 数据**，务必先备份。


---

## v39：元类 superClassLink 的受控修复（H16-F）

状态：**已上机验证（2026-11-18）**：`M:reg pre` 显示链接是正确的家族元类、`meta-ok` 通过、
`M:stalled scan ok`（本类正常登记），内核进到 `bsd_init` 之后的 `startRoot` 与 UFS bring-up。
当前阻塞点已不再是元类，而是 `hostBringUp()` 的 DMA 分配（见
`boot-round-v39-2026-11-18.md`）。  
基线：v38（内核 `49247f07`，`M:stalled post … cnt=172` / `M:bad[170] bad-chain n=NativeUfsBlock`）。  
改动：`patches/driver/liuqin-v39-metaclass-repair.diff`（对 pristine `drivers/ShengUfs/NativeUfs.cpp`）。

### v38 之后确定的事实

1. 崩溃不是重名。`getObject("NativeUfsBlock")` 返回 NULL，类登记在自己的唯一名字下。
2. v36 的 gate 是假阳性。家族预链合法持有 `IOBlockStorageDevice`，gate 见名就拒绝，所以 v36c/v37/v38
   必然走到 `I60:base-dup` + 挂载失败。
3. 被涂的是 `NativeUfsBlock::gMetaClass + 0x10`（`superClassLink`），值是 8 字节控制台文本
   `0x3135205b0a293061`；`v38` 的扫描护栏把这一槽丢掉，于是**这个类没有进 `sAllClassesDict`**。
4. 涂写发生在 boot 的 C++ 初始化期：v37 的深度遍历（`postModLoad+0x2d4`）读的就是这个字段，
   说明构造器写入的链接当时已经坏了。

### 为什么先选"受控修复"，不直接照搬 whyred 的重注册

社区形态（N1709/UniXNU-whyred r117–r145）是手写 `class MetaClass : public OSMetaClass` + 运行时
`superClass` + 显式 `preModLoad` → 静态初始化 → `postModLoad`。它在本仓库**不能原样移植**，原因已从
XNU 源码核实：

- whyred 的 `whyred_block_static_init` 是 `__asm__("__GLOBAL__sub_I_WhyredBlock.cpp")`，即整个 TU 的
  全局构造器。liuqin 的 `NativeUfs.cpp` 里还有 `OSDefineMetaClassAndStructors (NativeUfs, IOService)`，
  再跑一次这个 TU 构造器会**连 `NativeUfs` 的元类一起重建并再次入 stalled 批次**，第二次
  `postModLoad` 必然撞重名 panic。
- 对内置进 `kernel.macho` 的 TU（`CONFIG_XNU_NATIVE_UFS=y`），要在运行时构造元类就得
  placement-new 到静态存储，绕开全局构造器；这一步没有编译环境无法验证。

而受控修复只需要一次写入，且这个写入的**目标值本来就是运行时才知道的**（家族注册的那个元类）。
所以 v39 先做这一层；若上机后 `M:reg` 快照证明字段会再次被涂，再升级到手写元类形态。

### 改动（三处）

| 位置 | 内容 |
|---|---|
| `startRoot` 序言 | 取家族元类 `IOBlockStorageDevice` → ABI 闸 `metaClass->getClassSize() == sizeof(NativeUfsBlock)` → `liuqinBlockAdoptSuperClass(base, "pre")` → 有界链校验；失败各有独立里程碑 |
| 元类定义之后 | `LiqMetaShim`（布局与 H16-E 诊断一致：`+0x00` vtable / `+0x08` reserved / `+0x10` superClassLink / `+0x18` className / `+0x20` classSize）、`liuqinBlockSuperClass()`、`liuqinBlockChainOk()`、`liuqinBlockAdoptSuperClass()` |
| `prepare()` 分配前 | `prep` 再校准一次：发布线程比 `startRoot` 晚，字段若被重新涂写，在这里抓在实例化之前 |

`liuqinBlockAdoptSuperClass` **只在值不同时写**，重复调用是 no-op（这是 H16 重入教训的对应物），
并且两个状态都上屏。

**v36 的 gate 必须删掉**（作者工作区里的那段 `if (!liuqinBaseClassFree ()) …`）。仓库里的
`drivers/ShengUfs` 分支本来就没有这段，所以本补丁不含删除动作。

### 面板判读

正常应看到（顺序）：

```
U:59:start-root_init
NativeUfs: M:reg pre p=0xfffffff007ae36b0 link=0x3135205b0a293061   ← 若仍是 boot 期的涂写值
NativeUfs: M:reg pre fixed link=0xfffffff007add1d0                  ← 家族元类
U:meta-ok
U:root-bringup-ok … U:root-manifest-ok … U:root-plan-ok … U:root-prepared
NativeUfs: M:reg prep p=… link=0xfffffff007add1d0                    ← 每窗口一次，值不变
U:root-pub-<window>                                                  ← 发布线程的既有里程碑
→ 挂载决策越过 IOKitBSDInit.cpp:989
```

判读规则：

| 看到 | 含义 | 下一步 |
|---|---|---|
| `U:base-missing` | 家族元类还没注册 | 说明 `startRoot` 时机太早，需要提前触发或换查找方式 |
| `U:abi` | `getClassSize()` 不等于 `sizeof(NativeUfsBlock)` | 元类布局/编译单元不一致，停手查编译产物 |
| `M:reg pre` 的 `link=` 仍是 `0x3135205b…` | 涂写发生在 boot 期，且只发生一次 | 修复有效 |
| `M:reg pre` 的 `link=` 已是家族元类 | v38 之后字段没被涂（或编译产物已变） | 记录，v39 仍是无害的幂等写入 |
| `M:reg prep` 又打印 `fixed` | **字段在运行期被再次涂写** | 升级到手写元类形态，并开始定位写者 |
| 过了 `U:root-prepared` 但仍 `Failed to mount root device` | 块设备发布成功，问题在根卷/文件系统层 | 换到 FS 侧判读（不是 H16 了） |

### 主机侧回归

`tests/metaclass-simtest` 新增场景 E（`./run.sh` 或 Windows 的 `run-win.ps1`）：

| 场景 | 断言 |
|---|---|
| E0 只删 gate、字段仍是毒值 | 实例不是 `IOBlockStorageDevice` ⇒ 媒体不会匹配（证明"删 gate 不够"） |
| E1 `startRoot` 修复 | `kindOfBlockDevice=1`、`kindOfIOService=1`、链深 3 |
| E2 重复调用 | no-op，不重写、不重复注册 |
| E3 修复后再次被涂 | 修复前能被检测到，`rearm` 幂等修好 |

当前结果：`ALL SIM ASSERTIONS PASS`（A/B/C/D/E）。

### 构建链实测：`liuqin-build` 分支无法从公开状态复现（2026-11-18）

用 fork（`Fly116/UniXNU-liuqin`）触发 `.github/workflows/macos.yml` 连续 6 轮，每轮都往前走一步，
最后停在同一个根因上：

| run | 失败点 | 根因 | 处理 |
|---|---|---|---|
| 44230597889 | bootstrap 链接 | `scripts/build-boot-progress.py` 不在任何分支 | 关掉 `CONFIG_XNU_BOOT_PROGRESS`（面板输出走 `liuqin_fb_putc`，不受影响） |
| 44231994493 | defconfig | 行尾注释不被解析器接受（我方引入） | 注释独立成行 |
| 44232733235 | `line 745: test -f $CRYPTO_ARCHIVE` | `CONFIG_XNU_BUILD_ARCHIVES` 未开，archives 全没跑 | defconfig 加 `=y` |
| 44233836115 | archive 7 | 设备脚本按新树找 `kits/XnuPrelink`，旧树叫 `kits/NativePrelink`；且缺 `scripts/kernel_target.py` | 两处脚本改为按内容探测路径；补 `kernel_target.py` |
| 44235213748 | archive 7 审计 | `audit-amfi-pmgr-contract.py` 要 `build/native-prelink/*-candidate.macho` | 审计改为"缺基线则警告"（生成物不变） |
| 44236975692 | archive 7 自身不变式 | `build-sheng-platform-power.py:106` 自己也要同一个 reference | **不可绕**：这是校验输入 |

**根因**：`build/xnu-prelink/native-owner-ufs-rootauth3-candidate.macho`（以及
`native-owner-ufs-cpu-desktop-*-candidate.macho`）是上一次 prelink 的产物，只存在于作者本机的
`build/` 里；公开分支里没有任何途径生成它（prelink 必须在链接之后）。作者仓库里成功的
`ci-parts`（run 40085476418）已不可访问，其产物分支只有 `kernel.macho`。

**结论**：这条路要么拿到作者的 `build/xnu-prelink/` 基线，要么整体迁到带 Linux 支持的新树
（`1696108518/UniXNU` 的 `liuqin` 分支）。后者已实测：`./unixnu defconfig liuqin_defconfig -D <本仓库>`
能正常解析，但 `board.toml` 的 `[kernel.prelink].tool` 仍指向 `kits/NativePrelink`，prelink 步骤需要迁移。

### 构建链现状（2026-11-18 在本机核实）

- `macOS 12 (Monterey)` 最高只能装 Xcode 14.2（iPhoneOS 16.2 SDK），而本仓库目标是
  `-miphoneos-version-min=17.0` + XNU 10063；直接用 Monterey 编内核不可行（除非把 iPhoneOS17
  SDK 硬塞进 Xcode 14，属偏方）。
- UniXNU 主线已经支持 **Linux 编内核**（`scripts/linux/setup-toolchain.py`，上游 clang +
  cctools-port），但本设备仓库对应的是**旧一代构建树**：`board.toml` 指向
  `kits/NativePrelink/emit_prelink.py`，而带 Linux 支持的树用的是 `kits/XnuPrelink`。
  两条线不兼容，设备仓库需要迁移才能本地 Linux 构建。
- 作者自己用的是 `.github/workflows/macos.yml`（`macos-latest`，固定 fork
  `1696108518/UniXNU` 分支 `liuqin-build`），产物推到 `ci-out` / `ci-parts` 分支；
  这两个分支里能直接看到 `kernel/kernel.macho`（约 51 MB）和构建日志。
- `uefi-liuqin` 仓库自带预编译 DTB（`Resources/DTBs/liuqin.dtb`，480,704 B），但**没有**构建好的
  `SILICIUM_UEFI.fd`；FD 需要用 EDK2 现编（Linux/macOS 都能编）。

结论：v39 的内核和 payload 走作者那条 CI 最省事；固件与 `bootimg` 可以在 Linux/Windows 侧完成。

### 上机步骤（需要构建机 + 真机）

构建侧（macOS + Xcode，按 README 的 `quick start`）：

```sh
cd ../UniXNU
export UNIXNU_DEVICE=$PWD/../UniXNU-liuqin UNIXNU_UEFI=$PWD/../uefi-liuqin \
       UNIXNU_EDK2=$PWD/../uefi-liuqin/Mu_Basecore UNIXNU_TOOLCHAIN=$PWD/../toolchain
./unixnu build kernel
./unixnu build payload --kernel out/liuqin/kernel/kernel.macho --unique-chip-id 0x84750A0B0C0D0001
python3 ../UniXNU-liuqin/scripts/wrap-payload-mbr.py \
    out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
./unixnu bootimg --fd ../uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --dtb ../uefi-liuqin/Resources/DTBs/liuqin.dtb --ramdisk out/liuqin/payload/payload-mbr.img
```

对账：`out/liuqin/boot/boot.img` 必须是 **69,525,504 B**（漏 `wrap-payload-mbr.py` 会是
68,476,928 B）。

设备侧（纯内存，不写分区）：

```sh
fastboot devices
fastboot boot out/liuqin/boot/boot.img
```

然后按 `docs/liuqin-usb-debug.md` 抓 USB CDC-ACM 日志，并拍照记录面板 `U:*` / `M:reg` 行。

### 需要构建机才能确认的两件事

1. `NativeUfsBlock::metaClass` 在真实 SDK 头里是 `OSDeclareCommonStructors` 的 public 静态成员
   （本补丁据此取址）。若编译报 `metaClass` 不可访问，改用
   `const OSMetaClass *base = NativeUfsBlock::metaClass;` 所在作用域的替代取址方式。
2. 新增的 `<libkern/c++/OSSymbol.h>` / `<libkern/c++/OSMetaClass.h>` 在该 SDK 下可包含
   （`helper.inc` 里 `OSSymbol::withCString` 已被 v36 gate 用过，风险低）。

### 若上机后字段再被涂：升级路线（whyred 形态，已核实的前提）

- `OSMetaClass::preModLoad` 里有 `assert(sStalled == NULL)`：只能在 boot 批次结束后调用，
  `startRoot` 时机满足。
- `postModLoad` 返回 `OSReturn`（0 = 成功），内部用 `OSKext::lookupKextWithIdentifier(kextID)`；
  `g_kernel_kmod_info.name == kOSKextKernelIdentifier == "__kernel__"`，且该 kext 在
  `OSKext.cpp:1069` 被放进 `sKextsByID`，所以 `"__kernel__"` 能查到，不会 `kOSMetaClassNoKext`。
- **不要**照抄 `__GLOBAL__sub_I_*.cpp`：本 TU 里还有 `NativeUfs` 的元类。必须 placement-new 到
  静态存储，且 `getMetaClass()` 返回该对象。


---

## liuqin (Xiaomi Pad 6 Pro / SM8475) UniXNU 启动进展

最后更新：2026-10-23 09:05 本地时间

### 目标

让 UniXNU (XNU) 在 liuqin 上启动，并最终枚举出 CDC-ACM USB 调试口（内核参数 `liuqin_usb=1`）。

### 阶段色带（当前进度定位手段）

`liuqin_stage(n)` 除了记 `lq_rec[]`，还通过 identity 映射往 `0xb8000000` 画一条 44 行高的带子，
行号 `1200 + 70*n`、颜色按 8 色循环：绿黄蓝洋红橙白红青。

- 1 `arm_init` 进入 / 2 过了 `PE_init_platform` / 3 即将 `arm_vm_init` / 4 `arm_vm_init` 返回后（不该出现）
- 5 `arm_vm_init` 入口 / 8 内存配置检查后 / 9 取到 bootstrap 页表 / 10 `init_ptpages` 后
- 11 `arm_vm_prot_init` 后 / 12 `arm_vm_physmap_init` 后
- 13 `kva_active = TRUE` 后 / 14 内核镜像段登记前 / 15 `pmap_bootstrap` 前（这三条走「临时 KVA 映射」）
- `bsd_init`：240 行洋红大块（`liuqin_fb_bigband(2400,…)`）+ 原有的青色带

**TTBR0 陷阱**：`arm_vm_init` 里 `set_mmu_ttb(invalid_ttep)` 之后 identity 映射失效，任何往
`0xb8000000` 的写都会 fault（曾把 6/7 号标记放在这里，等于自己把内核打死，且「没出带」完全
不能说明问题）。现在在切换前用一条 2 MiB 块把显存映射到内核窗口的空闲槽
（`gVirtBase + 0xF000000`），把该 KVA 交给标记用，`pmap_bootstrap` 之后立刻 `liuqin_late_unbind()`。

### 当前状态（一句话）

**MMU 已通、C 代码在跑**：`boot-liuqin-2.img` 实拍确认 青黄蓝洋红**橙白**+绿灯（`MSR SCTLR_EL1` 成功、`ret` 完成）。
`boot-liuqin-4.img` 实拍确认阶段带 **1,2,3,5,8,9,10,11,12** 全出：`arm_init` 走到 `arm_vm_init`，
`arm_vm_init` 内部一路走到 `arm_vm_physmap_init()`（第 12 条），之后没有信号 —— 死点在
`arm_vm_physmap_init` 之后到 `pmap_bootstrap` 之前（含 `set_mmu_ttb(invalid_ttep)` 这一段）。

上一版为什么必挂（已修，留档）：手填映射块模板写成 `0x4c1`，`AP[2:1]=11` 只读，MMU 一开第一笔写显存就 fault —— 那一版**不可能**出橙带。

### 已证实的事实（含源码级证据）

1. 顶部绿带是 **DarwinBoot 的 EL1 交接桩**画的（`drivers/DarwinBoot/DarwinBootPkg/Driver/Entry.S`，`DarwinEnter`）。它只证明固件 `br x1` 跳过去了。
2. `DarwinEnter` 在跳转前还会 **`bic SCTLR.M` + `bic SCTLR.C` + `bic SCTLR.I`**，并对整个 owned 窗口 `dc civac` 清到 PoC。所以内核入口处 **cache 全关、MMU 关**，此后所有页表/显存写入都是直写 DRAM（无 cache 一致性问题）。
3. DarwinBoot 的交接摘要实测值（`Print`）：
   - `kernel va=0xfffffff00427c000`（最小段 `__PRELINK_TEXT`）、`pa≈0x84527c000`（注意：进度文档里早先抄成了 9 位，实际是低 DRAM 里的 ~2.2 GiB 处，对应 args/video 都在 `0x8..`-`0xb..` 段）
   - `entry pa≈0x847652000`，entry words `d2b7031a 529ffffb 72bfe01b d2a0003c`（正是我们插入的青色打点代码）
   - `args pa=0x8f516000`（窗口内 +177 MiB）、`window=0x10000000`（256 MiB；ADT 可给 ≥256 MiB，`DarwinWindowSizeValid` 要求 ≥0x10000000 且 2 MiB 对齐）
   - `video base=0xb8000000 1800x2880 row=7200 32bpp`，framebuffer 在加载窗口**外**
   - `tcr=0x20080351b`（固件值，T1SZ=0，XNU 会覆盖）、`sctlr=0x3009193d`、`parange=2`
4. **XNU 自己装的 TCR_EL1 是对的**（从编好的 `kernel.macho` 里读出静态初值）：`sysreg_restore.tcr_el1 = 0x00000022a51a251a` → T0SZ=T1SZ=26、TG0=TG1=4 KiB、IPS=40 位 PA、TBI0=1。不是 TCR 的锅。
5. **XNU 的 bootstrap 块模板 = `0x601`**（`kernel.macho` 反汇编 `mov x11, #0x601`；= `ARM_TTE_BOOT_BLOCK` = valid|block|SH(outer)|AttrIndx(writeback)|AF）。我们之前手填的 `0x4c1` 是 `AP[2:1]=11`（只读），开 MMU 后第一次 `str` 到显存就权限 fault。
6. 打点带（base/7200 = 屏幕行号）：青 `0xb8180000`（`_start`）、黄 `0xb81c0000`（`common_start`）、蓝 `0xb8200000`（MAIR 写完）、洋红 `0xb8240000`（写 SCTLR 前）、**橙 `0xb8280000`（MSR SCTLR + isb 之后）**、白 `0xb82c0000`（`ret` 前）。
   - 历史实测：只到洋红 → 死在开 MMU。
   - 本轮新增 **灯 `0xb8380000`**（洋红之后）：读出 PC 那条 L2 项 → **绿**=有效块且映射的正是这个 2 MiB；**红**=其它。
7. 跨启动 DRAM 不保留（固定地址 probe 读回全 0，且每次启动窗口前 `Used` 被 `ZeroMem`）→ 只能用 framebuffer 当场打点。
8. framebuffer 是 BGRA：`0xFF00FF00`=绿、`0xFF0000FF`=蓝、`0xFFFF0000`=红、`0xFFFFA500`=橙、`0xFFFF00FF`=洋红。

### 本轮的改动（`patches/xnu/zzz-liuqin-usb-debug.patch` 的 start.s 段，已重写）

1. 手填映射改用 **`0x601`**（XNU 自己的 `ARM_TTE_BOOT_BLOCK`）。
2. 覆盖范围：`max(BA_MEM_SIZE, 256 MiB)`，并且**把条数钳在单个 L2 页剩余项内**（`512 - L2索引`）。上一版不钳，遇到大 `BA_MEM_SIZE` 会顺次写穿到后面的 KVA 页表。
3. 辅助函数**不再用栈**（`sp` 还是 KVA，MMU 没开时只能靠地址截断侥幸）。
4. **SCTLR 改成读-改-写**：`mrs x0,SCTLR_EL1; orr x0,x0,#1; msr`，只加 M。`mov x0,#1` 会清掉 RES1（EOS/IESB）和固件给的 `nTWI/nTWE`；`#if !VMAPPLE` 的回读比较同步改成 `mov x1,x0`，不会再 `b.ne .` 自锁。
5. 新增 `0xb8380000` 灯：填完后按 PC 反查 L1→L2，校验 `bits[1:0]==0b01` 且块地址与 PC 的 2 MiB 对齐值相同。
6. 不再调用 `create_bootstrap_mapping` 建显存映射（它会**改写 V=P L1 的整条槽**，把 XNU 建好的窗口 L2 表换掉）；改成同一个 `LiqinFill` 往已有 L2 表里填。

### 下一步（按优先级）

1. 刷阶段色带版，看屏幕 1200/1290/1380/1470/1560/1650/1740 行的七条带**最后一条是哪个颜色**：
   - 绿 `arm_init` 进 / 黄 过了签名设置 / 蓝 `machine_startup` 前 / 洋红 `machine_startup` 后
   - 橙 `arm_vm_init` 进 / 白 `pmap_bootstrap` 前 / 红 `pmap_bootstrap` 后
   - 只有绿 → 死在 arm_init 开头（很可能踩到 `arm_setup_pre_sign`/tunables）
   - 到洋红没了 → 死在 `machine_startup` 里
   - 到白没了 → 死在 `pmap_bootstrap`
   - 到红全齐 → pmap 起来了，接着指望 `kernel_map` + console 镜像滚字
2. 阶段定位后按对应函数继续加带/查寄存器；`panic` 路径也要能上屏（console 镜像 + `liuqin_fb_marker_boot`）
3. 之后回主线：`bsd_init` → console 出字 → DWC3 四道门 → CDC-ACM 枚举

### CI 现状（换过路）

GitHub 上 `1696108518/UniXNU` 这个 fork 的 Actions 被禁用（dispatch 一律 422 `Actions has been disabled for this repository`，`PUT actions/permissions` 也救不回来），所以现在改在**设备仓库** `1696108518/UniXNU-liuqin` 里跑同一条 workflow：它不再 `actions/checkout` 自己，而是匿名 `git clone --depth 1 --branch liuqin-build https://github.com/1696108518/UniXNU.git .` 取固定基线。用 `tools/gh-build-via-device.py` 上传+dispatch。

产物下载有坑：本机网络对单个响应在 ~30 MB 处截断，而 `kernel.macho` 有 51.8 MB，`api.github.com` 又不支持 Range。解法：`.github/workflows/split.yml`（workflow_dispatch）在 runner 上把文件切成 11 MB 分片推到 `ci-parts` 分支，再用 `tools/fetch-liuqin-kernel.py` 拼回来并按 ci-out 的 git blob sha 校验。

### 工具与命令

- 构建：`cd ~/port/UniXNU-liuqin && GITHUB_TOKEN=<PAT> python3 tools/gh-build-liuqin.py --steps kernel --defconfig liuqin_boot_defconfig --timeout 9000`
- 拉内核（artifact 的 302 到 blob 被墙，走 ci-out 分支）：`GET /repos/1696108518/UniXNU/git/trees/ci-out` → `git/blobs/<sha>`
- 重新生成 start.s 段：`python3 /mnt/c/Users/ASUS/Desktop/unixnu-port/gen-start-patch.py`（先用 GitHub API 取 pinned 的 `osfmk/arm64/start.s` 存到 `Desktop/unixnu-port/start_orig.s`）
- 汇编语法自检（不需要 macOS）：把补丁里 start.s 的 `+` 行抽出来加个头，`clang --target=aarch64-none-elf -c` 过一遍
- 打包：`unixnu build payload` → `scripts/wrap-payload-mbr.py` → `unixnu bootimg --uefi ../uefi-liuqin --fd .../SILICIUM_UEFI.fd --dtb ../liuqin-cape.dtb --ramdisk ...`
- 刷机：`C:\Users\ASUS\AppData\Local\PreloadTool\1.0_9daba3050879\fastboot.exe boot <img>`（序列号 `87d1de07`）
- 补丁自检：`python3 tools/check-debug-patch.py`；可应用性：`/tmp/sim` 合成树里先打 `architectural-timer-entry.patch`，再 `git apply --check`
- 从编好的内核取常量：`llvm-objdump --macho -d ~/liuqin-gh/kernel.macho`（`_start_first_cpu` 在 `0xfffffff0073ee05c`），`_sysreg_restore` 静态初值在文件偏移可见

### 踩过的坑（务必记住）

1. **补丁上下文要按「已打补丁的树」生成**：`architectural-timer-entry.patch` 把 `#if defined(BCM2837)` 改成带 `&&` 的形式且顶格无 tab；`native-4k-bootstrap-capacity.patch` 在 KVA `create_bootstrap_mapping` 之后插了 `b Lbootstrap_tables_ready` 一段——我们的插入点正好在它前面，必须靠结尾的 `b LiqinFillDone` 跳过辅助函数。
2. 同一文件内相邻 hunk 不能重叠上下文；相邻插入合并成一个 hunk。
3. 手改 patch 后必须 `tools/check-debug-patch.py` + 合成树 `git apply --check`，再花 1 分钟用 clang 汇编自检，否则 16 分钟一轮的 CI 白跑。
4. 块模板 `0x4c1` 是只读（AP[2:1]=11）；要 `0x601`。**这类错误会让「映射对不对」的实验完全失去意义。**
5. 不要相信跨启动内存，也不要相信 C 侧 `lq_rec`（每次启动被 `ZeroMem` 清掉）。
6. `0xFF0000FF` 在这块屏上是蓝色。
7. `x23` 已被 slide 修正过，不能当加载地址用；要读 `[x20, BA_PHYS_BASE]`。
8. 写文档/脚本不要用未加引号的 shell heredoc，也别依赖 `write_file` 写 WSL 路径（会走 bash 失败）——用 `execute_code` 落到 Windows 路径再 `cp`。
9. `bootstrap_pagetables` 只有 `BOOTSTRAP_TABLE_SIZE`（本配置 16 页）可用，`native-4k-bootstrap-capacity.patch` 让超限时原地自锁；自己填表时绝不能越过 L2 页边界。


---

## 实机逐轮判读：v35 → v38（2026-11-16 → 2026-11-17）

K49:PE_init_iokit 处的 `Kernel data abort` 从 v35 第一次可读，到 v38 被彻底消掉并点名。
这一页记录每一轮改了什么、照片看到什么、以及被证伪的假设——避免以后走回头路。

诊断通道：面板里程碑控制台（前缀 `K` 内核 / `B` BSD / `U` 驱动 / `I` 挂载 / `M:` 元类扫描）
+ 1 MiB 环形缓冲；v35 起 panic 直接上屏（`patch-xnu-entry-probe.py --panic-screen --panic-only`）。
所有轮次都用 `fastboot boot` 纯内存运行，不写任何分区。

### 版本线

| 轮 | 内核 sha | 改动 | 实机结果 |
|---|---|---|---|
| v35 panic-screen | `ecc3508b`（源同 v34b） | 只动 payload：SCTLR/ISB 与 MOVZ/CPACR 两对锚点独立定位（liuqin 17.7.11 的 CPACR 对在 MMU 写后 +0x34，非固定 +0x20）；新增 `--panic-only`（4K 基线的 `_start` 是内联序言，不是可搬移的单条 `b`，故只装 panic 漏斗不装彩色条）；`panic_screen_only=true` | panic 第一次上屏。`K49:PE_init_iokit` → `K31/K32` 后 `Kernel data abort pc 0xfffffff00789287c` = **OSMetaClass::postModLoad+0x288** |
| v36 gate | `5687393d` | 驱动侧 `driver-H16.diff`：`startRoot` 入口 `getMetaClassWithName("IOBlockStorageDevice")`，名字被占就在任何分配前拒绝发布，输出 `U:base-dup` | 同一 pc。`U:*` 一行都没出现 ⇒ 崩在 `startRoot` 之前，gate 根本没机会跑 |
| v36b | `5687393d` | 与 v36 同一内核，重打包/回归轮，无新代码 | 同上 |
| v36c | `e53fc818` | probe 抗内联（gate 调用不被优化掉） | 仍崩同一 pc，但 far 从 typed-free 毒化变成 `'ffffff'` 型 ASCII |
| v37 stalled-diag | `6b3a208c` | 转到 **XNU 侧**：`M:stalled pre/post` 里程碑 + 第一遍循环对 `classes[i] < 0xfffffff000000000` 的脏槽位护栏 | 崩点后移到 **postModLoad+0x2d4**；面板出现 `M:stalled pre … cnt=0 c0=0 c1=0`，且没有 `M:stalled dirty!` |
| v38 chain-dump | `49247f07` | 逐槽命名 + 祖先链校验 + **跳过坏槽而非整批拒绝**；结论行放最后 | **崩溃消失**，第一次走完 IOKit 引导到挂载决策 |

### v37 判读：脏数组假设被否证

反汇编 v37 镜像（`postModLoad` 基址 `0xfffffff0078926a0`）+ 符号表 + 照片 IMG_7051–7054：

- pc `0xfffffff007892974` = **+0x2d4** = `ldr x24,[x24,#0x10]`，是 `while ((me = me->superClassLink)) depth++;`
  的**第一次跳转**，从 +0x2ac 的 `cbz x0` 进入 ⇒ `getObject` 返回 NULL，**根本没进重名分支**；
- lr `0xfffffff00789294c` 正是那次 `blr getObject` 的返回地址 ⇒ `classes[i]` 是合法元类、`className` 可读；
- x24 = `0x6131373030666666`（小端字节 `f f f f 0 0 7 a`），far = x24 + 0x10 ✓ 自洽；
- x22 = `0xfffffff2c33c3140` = 面板 `M:stalled pre` 的那个 handle ✓ 同一次调用。

⇒ stalled 数组本身是干净的（零填充有效），**H16-D 的"脏数组"假设被否证**；被涂的是某个合法元类对象的
`superClassLink` 字段（偏移 +0x10）。H16-D 的护栏只查 `classes[i]` 本身，所以拦不住，崩溃只往后挪了 0x4c。

链接期绑定也排除掉了：驱动 `NativeUfsBlock::MetaClass` 构造器是 `ldr x2,[0xfffffff007a0c008]`（GOT 槽），
该槽在镜像里的内容 = `0xfffffff007add1d0` = `__ZN20IOBlockStorageDevice10gMetaClassE` ✓ 正确。
所以是**运行时涂写**，必须先知道涂的是哪个类。

### v38 判读：点名成功，两个前提被推翻

启动线（v35–v37 从未越过 K49）：

```
K49:PE_init_iokit → K50 early_boot … K57:PE_lockdown_iokit → U58:probe-expert_init
→ B01:bsd_init … B101:at_parse_rd  B102:at_from_chosen  B103:at_di_ramfile
→ U59:start-root_init → NativeUfs: IOBlockStorageDevice is already registered as
   IOBlockStorageDevice; root publication refused → I60:base-dup
→ Failed to mount root device @IOKitBSDInit.cpp:989      ← 可读 panic，不再是 data abort
```

关键三行（IMG_7061，`vt` 已放大复核）：

```
M:stalled post h=0xfffffff568caffe0 cnt=172 c0=0xfffffff007c1c130 c1=0xfffffff007adfcd8
M:bad[170] bad-chain p=0xfffffff007ae36b0 vt=0xfffffff0072086d0 sz=248 n=NativeUfsBlock bad=0x3135205b0a293061
M:stalled scan BAD h=0xfffffff568caffe0 cnt=1 c0=0xac c1=0x6
```

| 面板 | 独立验证 |
|---|---|
| `p=0xfffffff007ae36b0` | nm 里 `__ZN14NativeUfsBlock10gMetaClassE` **逐位相同** |
| `vt=0xfffffff0072086d0` | 构造器 `adrp 0xfffffff007208000 + add #0x6d0` ✓ |
| `sz=248` | 构造器 `mov w3, #0xf8` = `sizeof(NativeUfsBlock)` ✓ |
| `c0=0xfffffff007c1c130`（classes[0]） | nm 里 `sOSMetaClassMeta` ✓ 数组确实干净且语义正确 |
| `cnt=1` / `c0=0xac`(=172) / `c1=0x6` | 172 项里只有第 170 项坏；depth 统计未被破坏 |

`bad=0x3135205b0a293061` 的小端字节 = `a 0 ) \n [ 5 1` —— **含换行的控制台文本**。
驱动自己的静态量已排除：`native_ufs_extra_atos[8]` / `dpu_smmu[24]` / `dpu_state` / `dpu_check[8]`
与 gMetaClass 在 `__common` 里首尾精确相接（`0x7ae360c→0x7ae362c→0x7ae368c→0x7ae3690→0x7ae36b0→0x7ae36d8`），
且全是 uint32 数值，不是文本源。

**被推翻的两个前提**

1. 崩溃**不是**元类重名 panic。`getObject` 返回 NULL，我们的类登记在自己的唯一名字 `NativeUfsBlock` 下
   （v35 时把它读成"重名 → panic → 解引用已释放 `orig->reserved`"，是因为当时还没有逐槽命名）。
2. 因此 v36 的 gate 是**假阳性**：家族预链就必然合法持有 `IOBlockStorageDevice` 这个名字，
   gate 见就拒绝 ⇒ v36c/v37/v38 必然走到 `base-dup` + 挂载失败。它保住了命，但也永久挡住了根。

### v39 计划（社区实机证明过的形态）

来自 **N1709/UniXNU-whyred** 的 round 117–145 复盘（它踩的是同一个函数）：

1. 手写 `class MetaClass : public OSMetaClass`，超类指针用 `static const OSMetaClass *superClass`
   **运行时填**——直接取 gate 已经查到的家族 `IOBlockStorageDevice` gMetaClass，
   把 gate 从拦路石变成指针来源；
2. 显式 `preModLoad(g_kernel_kmod_info.name)` → 构造 → `postModLoad(handle)`，
   我们的类**不再进那 172 项批次**；
3. **重入闩**：`gIOResources` 的 `doServiceMatch` 每次 `publishResource()` 都会重新触发通知且
   **忽略返回值**，`return false` 不退订 ⇒ 第二次跑就进重名 panic 分支；
4. ABI 闸 `base->getClassSize() == sizeof(NativeUfsBlock)`（面板已给 248，正好对表）；
5. 注册前后各打一行 `M:reg`（对象地址 + `superClassLink` 值）——涂写若再现，就能区分
   是**注册前就有**还是**注册期间被写**。

副作用正好治本：运行时填 `superClass` 会在受控时刻把被涂的字段改回正确值。
H16-E 的扫描护栏保留（它是这次救命的东西）。

### 主机侧回归

- `simtest`（ASan/UBSan）：A 无 gate→复现面板崩溃形状；B 有 gate→拒绝且 `U:base-dup`；
  C 闭世界（无家族）→放行；**D（v38 新增）→复现 v37 的 `postModLoad+0x2d4` abort，
  并证明 v38 的扫描只丢掉那个中毒槽、其余照常登记、depth 语义不变**。
- 上游 descriptor oracle `drivers/ShengUfs/tests/check_legacy_descriptors.py`：**PASS 14/14**。

### 交付物

- 内核 `49247f07`；`boot-liuqin-v38-chain-dump.img` 69,525,504 B
  sha256 `08a01ee150dd0979f99905b278d9b5c66434c1352d7e5b9b23f6e3de0efd2068`
- 提交：`57b2d3c`（v35 payload）→ `6e006a3`（H16 gate）→ `c9065af`（probe 抗内联）→
  `cd0f12b`（H16-D）→ `1db66fc`（H16-E）
- 打包对账：v36c/v37/v38 均 69,525,504 B；漏掉 `wrap-payload-mbr.py` 会打成 68,476,928 B


---

## liuqin 适配路线（Stage 6 存储/root 主线）— 2026-11-15，无机窗口期研究产出

### 0. TL;DR

- **根因明确**：当前卡 mountroot 是最小配置的必然结果（UFS/APFS 全关，无根设备）。
- **主方案**：移植**官方 ShengUfs** 组件（其目录锁定 ABI 恰好就是 `ipados-17.7.11-21H461`），
  把 GccUfs.h 时钟常量从 SM8550 改抄 SM8475；**PongUfs（mondrian，同 SM8475）作为
  寄存器事实来源和备选**（它已在同 SoC 上跑通过 root，但绑 iOS 16 ABI）。
- **关键发现**：SM8550(sheng) 与 SM8475(mondrian 实测 DTS) 的 UFS 硬件窗口几乎完全一致：
  HC `0x1d84000/0x3000`、SMMU `0x15000000/0x100000`、完成中断 **GIC SPI 265**（ShengUfs
  源码 `kUfsIrq = 265+32` 与 pong,ufs-spi=265 相同）。真正的芯片差异集中在
  **GCC 时钟分支偏移**（`GccUfs.h` 0x770xx → SM8475 值可从 Linux gcc-sm8450/8475.c
  与 mondrian 实测交叉核对）。
- **userdata 镜像不需要 Mac**：官方 #110 已合并（Linux 用纯 Python `udif.py` 读 IPSW dmg）；
  iPadOS 17 的 OS 成员非 AEA 加密（#229 只卡 27）。IPSW 正在本机下载。
- 本文件 §4 是「无机窗口期」的完整作业清单（H1–H8），全部可在 PC 闭环验收。

### 1. 现状快照（对照官方 8 步）

| 官方步骤 | 状态 | 证据 |
|---|---|---|
| 1 收集设备输入 | ✅ 基本完成 | vendor-inputs.md 154 项、board.toml 实测 GPT |
| 2 选共享支持 | ✅ | ArmCpu/ArmDTPlatform/corecrypto14 已接 |
| 3 设备仓库 | ✅ | UniXNU-liuqin + 49+5 补丁序列（sim 58/58 通过） |
| 4 构建解析 | ✅ | Linux 工具链跑通；内核+payload 全本地构建（11-15） |
| 5 硬件描述 | 🟡 ADT 已有 ufshc/intc 节点 | make-liuqin-adt.py；UEFI 固件 SILICIUM_UEFI.fd 已出 |
| 6 **驱动适配** | 🔴 **当前主战场**：CPU✅→**存储⬅**→显示✅(GOP)→触摸/按键(固件有导入,内核侧未做)→GPU→Wi-Fi→BT→USB→… | 卡点=无块设备→无根 |
| 7 构建与上机 | 🟡 v31 跑到 B97/B98；v32(panic 可见化)已备好 | releases/v32-NOTES.md |
| 8 发布 | ⬜ | |

### 2. 方案对比

#### A. ShengUfs（官方，主选）
- 仓库 `UniXNU/ShengUfs`（目录 pin rev 99d8bcd），**os_abi 就是 ipados-17.7.11-21H461**
- 依赖链（components.toml）：`ShengUfs → {VirtioMmioBlock, VerifiedRoot}`；sheng 完整链还带
  `SoftwareAES`（官方 drivers）、`AppleKeyStoreState`、`RamBlock`
- **接管方式=adopt**：复用 UEFI 固件已初始化的控制器（"adopt: no usable firmware list"
  路径）→ 对 liuqin 的要求是 uefi-liuqin 的 UFSDxe 需在 FV 里启用（当前 DXE.inc 注释掉了；
  ⚠️ FVMAIN 99% 满，启用要配平裁撤项）
- 中断模式优雅降级：attach 失败自动回退纯轮询（bring-up/panic 路径恒轮询）→ 第一轮可先不管中断
- 移植改动面：GccUfs.h 常量（SM8475）、Info.plist 匹配、（可能）PHY/GDSCR 时序、root 策略 args
- boot-args：`native-ufs-root=1`（+ 视需要 `native-source-storage=1`、root_policies——
  **iOS 17 profile 是否要 source-storage 策略待证**：sheng 三个 profile 中只有 26.5/27 带
  `build-sheng-source-storage.py --policy-dir …`，17 profile 的 archives 需按本机再核对）

#### B. PongUfs（mondrian，SM8475 实测同 SoC，备选+事实来源）
- 本地已有：UniXNU-mondrian/drivers/NativeUfs（11 文件）；dts/mondrian.dts 给出全套实测常量
  （hc/gcc 页 0x187000/smmu/stream-id 0xe0/context 78/spi 265）
- 代价：绑 PONG machine 配置 + iOS16 存储 ABI 推导脚本（bind/derive-ios16-storage-*.py）
  → 用于 21H461 要重做 ABI 推导；`pong_allow_unauthenticated_root=1` 语义在 17 上未验证
- 用法：**A 方案的每个寄存器改动都用 B 的实测值交叉验证**；A 受阻即切 B

#### C. 过渡诊断（并行小工具，非产品路线）
- v32 已把「静默停 mountroot」变「可见 panic 文字」——拿到机器第一件事验证它
- QEMU native-user 线的 launchd SIGKILL（namespace 9 code 0x8）独立研究（不依赖硬件，
  属 exec-policy/签名问题，与 sheng 的 no-lc=1 线互通有无）

### 3. 硬件输入核对表（官方 /porting/ufs 的 9 项）

| 输入 | SM8550(sheng 源码) | SM8475(mondrian 实测) | liuqin 取值 | 来源/状态 |
|---|---|---|---|---|
| Controller base | 0x1d84000/0x3000 | 0x1d84000/0x3000 | **同值** ✅ | 两方一致 |
| 中断 | SPI 265 (kUfsIrq=265+32) | pong,ufs-spi=265 | **同值** ✅ | 两方一致 |
| SMMU | 0x15000000 (代码内) | 0x15000000/0x100000, sid 0xe0, ctx 78 | **同值** ✅ | 待 liuqin 上机读确认 |
| GCC/UFSCC 时钟页 | 0x00100000 + 0x77xxx 分支 | gcc-ufs-page=0x187000 | **需移植** 🔴 | Linux gcc-sm8450.c/8475 + K60 实测；liuqin 上机核 |
| PHY | adopt 自固件 | adopt 自固件 | 同策略 ✅ | uefi-liuqin UFSDxe 启用与否是前置 |
| Reset/电源 | GDSCR 0x77004 等 | PMIC 家族 pm8350/8450 同套 | **需逐条核** 🟡 | vendor DTS + PMIC 文档 |
| DMA | 物理连续+可达性检查 | gDmaLimit 检查 | 同架构 ✅ | ARM64 va/pa |
| 存储布局 | sheng userdata 窗口 | LUN+GPT→OS/SystemOS/Data | liuqin GPT **已实测**（board.toml 96GiB）| 需刷 SHNGROOT 镜像 |
| OS 接口 | 21H461 ABI | 20G81(16) ABI | 21H461 ✅ | sheng 目录即此 ABI |

### 4. 无机窗口期作业清单（PC 闭环可验收）

- **H1 userdata 镜像** ✅ **完成（2026-11-15 20:06，Linux 全程无 Mac）**：
  `out/liuqin/userdata/userdata-root.img` 9,382,658,048 B，SHNGROOT v1，OS 窗口 6,077,580,800 B @0x100000
  （sha e5634d04…，GPT→APFS→卷 `DawnUpdate21H461.J120J121J207J208OS`，**卷 UUID
  04769D26-2CA0-4825-B443-E2E5F88300F2 与 board.toml pin 逐字节一致**，apfs.py 校验和 13/13）；
  SystemOS 3,303,014,400 B @0x16a600000（sha b4908cde… **= [ipsw.sha256] pin**）。
  刷写命令在 `userdata-root.json`（等机器，属 D 级动作）。IPSW sha256 c84ad24b…（6,835,124,840 B）。
- **H2 组件落地** ✅：submodule `drivers/ShengUfs` @ catalog pin 99d8bcd，fork 分支
  `liuqin-sm8475`（提交 2b03381 + 修复 c1b2ce5）；tree 自动出 `drivers/NativeUfs` legacy 别名 ✓。
- **H3 GccUfs SM8475 移植** ✅（fork 内，均有出处注释）：页 0x187000（mondrian dts 实测，K60
  2026-11 真机）；分支 GDSCR+0x004/AXI+0x018/AHB+0x020/TX+0x024/RX0+0x028/UNIPRO+0x064/
  ICE+0x06C/AUX+0x0A4/RX1+0x0C0/AGG+0x0D4；**SMMU stream 0x60→0xe0**（关键差异，两处）；
  probe 匹配加 `qcom,sm8475-ufshc`；SM8550 mem-PHY 页(0x9e000) SM8475 未实测 → 显式 0 跳过。
  NativeUfs archive 已编译通过 ✓。
- **H4 内核配置与链接** ✅ **v33 链接通过（2026-11-15 22:41）**：
  ① transport 编译过；② vr_* 依赖经 NATIVE_VERIFIED_BLOCK 环境门清零；
  ③ IOBlockStorageDevice base 类 = **离线 derive 解决**（scripts/build-liuqin-ufs-bindings.py，
  从 board pin 的 21H461 缓存 f18b4df8 + refer/IOStorageFamily e45fbe30 + 内核编译记录，
  推 18 项导入注入 libShengUfs.a；slide 语义查明=整缓存统一 slide，用 raw 缓存 VA，非 mondrian
  的 auto-slide repack）。新内核 sha 18a2a351，v33 boot.img sha ab159477。
  旧「链停在 base 类」记录：
  ① `XNU_NATIVE_UFS_VERIFIED` 开关落地（build-arm-driver.py 环境门 + boot defconfig=n，
  official defconfig=y）——=0 模式暴露两处上游从未编译过的错误，fork 已修（Operations::read 计时）；
  ② vr_* 依赖清零 ✓；③ 新缺口：`IOBlockStorageDevice` base 类符号（gMetaClass/vtable/ctor/dtor）
  不在最小内核链里。官方机制查明 = **bindings 审计链**（见 H9），非 .o 编译而是
  **地址绑定**（audit 从原始 21H461 缓存取地址→original-bindings.S→force_load）。
  v33 打包因此暂缓。
- **H9（新）bindings 审计链 Linux 化** 🟡 输入全部清点完毕，本机可闭环：
  ① `xcrun` shim 已写（`toolchain/bin/xcrun` → llvm-* + `toolchain/fake-sdk`，
     TargetConditionals.h 已就位）；② refer/IOStorageFamily @ e45fbe30 ✓；
  ③ candidate_sha256=51212c58（kernel.json，已内嵌 IOStorageFamily 组件）✓；
  ④ 快照缺口：需 `probe-darwinboot-xnu.py --kernel out/liuqin/kernel/kernel.macho`
     在 QEMU 跑 liuqin 候选缓存到 panic，产出
     `build/darwinboot-storage-native-metadata/gdb-stop.json`（要求 kernel_sha256 匹配、
     native-4K TCR/SCTLR/TTBR、metaclass 实存 0x90/IOService 0x88）；
  ⑤ `audit-aes-interface.py` 需 kdk IOCryptoAcceleratorFamily——可从 21H461 缓存用 np 提取，
     或核实 sheng 是否本就用 iOS 提取件（下一步先跑 ①-④ 再定）；
  ⑥ 审计过后 archives += `build-arm-driver.py NativeRamBlock` +
     `build-virtio-mmio-bindings.py --component RamBlock --directory build/ram-block` +
     `CONFIG_XNU_NATIVE_RAM_BLOCK=y` → libRamBlock.a 带 bindings 进链 → v33 可链。
- （并行）**v32 刷机包**：等机器，watch 重挂即可
- **H10（新坑，已修）**：personality 宏门控的 `KernelConfigTables.cpo` 不随 CONFIG 变化重编
  （make 不感知 CFLAGS_ADD）→ 驱动链接进内核但 IOKit 从不 probe，症状 = "K49 无 panic 直接过"。
  基座已加 personality-mode stamp（UniXNU@d883995）；v33b 起生效。
  教训入档：**链接成功 ≠ 驱动会被实例化**，personality 表要单独验证（strings 查 "= NativeUfs;"）。
- **H11（新坑，实机证实）**：v33c 显示 personality+boot-arg+start 全通，但 **panic() 文字不上屏**
  ——本机 panic 进 KDB 静默等待（"configuring debugging over serial" 在场，无调试器应答）。
  结论：**实机诊断报告一律走 liuqin_debug_puts 里程碑控制台，不得依赖 panic 屏**；
  v33d 的 inspect 已改控制台版。此规则同样适用于未来 root 失败报告（v34 起）。
  `./unixnu build userdata --ipsw <本地> --dry-run` 核成员/大小 → 正式构建
  → 用 apfs.py（copy 自 mondrian）离线核 SHNGROOT 头、GPT、卷 UUID（应=04769D26-…）
  ✅验收：userdata.img 出成+report 三项 sha 全、UUID 匹配 board.toml
- **H2 组件落地**：liuqin 加 submodule `drivers/ShengUfs`(99d8bcd)、`SoftwareAES`、
  `AppleKeyStoreState`、`RamBlock`、`VerifiedRoot`(974f043)（照 sheng/.gitmodules + 目录 pin）
  ✅验收：`./unixnu tree -D ../UniXNU-liuqin` 后 kits/drivers 齐、check 脚本过
- **H3 GccUfs SM8475 移植**：fork 内改 GccUfs.h（对照 mondrian 常量 + Linux 公开时钟驱动
  gcc-sm8450.c 系；每项标来源），列 diff 表存档；**不猜值**，未测项显式 0+拒绝启动
  ✅验收：编译过 + 常量-来源对照表进 porting.toml
- **H4 内核配置与链接**：liuqin_boot_defconfig 分批开
  `CONFIG_XNU_NATIVE_UFS/NATIVE_AES/VERIFIED_ROOT_PROBE/OWNER_ROOT_AUDIT/OWNER_ROOT_TRUST`
  + board.toml `[kernel] archives += component:…`（顺序照 sheng）；`./unixnu build kernel`
  ✅验收：Linux 全量编链过（含 UFS archive）+ prelink roots 数>0；这是**最大风险缓冲**——
  把「编不过/链接不过/ABI 推导缺输入」这类问题全部在无窗期消灭
- **H5 ADT 补齐**：make-liuqin-adt.py 检查 ufshc 子节点属性（compatible 已有）；
  若 NativeUfs adopt 需要 memory window/owned-range 声明则一并加
  ✅验收：adt 体积/节点 diff 审查 + qemu 线回归不劣化
- **H6 固件侧预案**：uefi-liuqin 启用 UFSDxe 的 FVMAIN 配平方案（候选裁撤：
  BootloaderLogging/NT_DeviceInfo/DisplayDxe，bringup-notes §7 已列）——先出 patch 不刷
  ✅验收：本地重编 fd 出成、FV 占用<99%
- **H7 chip_id TODO**：board.toml `[adt] chip_id "207"`（SM8550）→ SM8475；
  mondrian 用 8015 → liuqin 同 SoC 大概率 8015，但按纪律标注「上机 SMEM 实测确认」
  ✅验收：改值+注释+重编 ADT
- **H8 QEMU SIGKILL 支线**：launchd 签名/exec-policy 研究继续（host-only，独立于存储）
- （并行）**v32 刷机包**：等机器，watch 重挂即可

- **H13（无机窗口期地雷，v34c 排除）**：复查发现 liuqin 的未验证构建
  （`CONFIG_XNU_NATIVE_UFS_VERIFIED=n`）下 ShengUfs `startRoot` 的 `validate()` **无条件
  return false**（"Root publication requires owner verification in every build."，fork
  上游行为）——即使 v34c 之后 adopt/GPT/manifest 全过、userdata 也刷好，root 也**永远
  发布不出块设备**，白白烧掉一个"刷根窗口"。修复（fork b9c020a，仅未验证编译单元生效）：
  ① 显式 boot 门 `native-ufs-unauth-root=1`（不带=上游 fail-closed）；
  ② 媒体等待在 unauth 模式降级为"窗口下出现任意 IOMedia"（依据：21H461 缓存
  IOStorageFamily 有通用 personality `{IOClass=IOBlockStorageDriver; device-type=Generic;
  IOProviderClass=IOBlockStorageDevice}`，且 `IOBlockStorageDevice::init` 自带
  device-type=Generic——已在本机缓存 f18b4df8 二进制里逐字节核实）；
  ③ startRoot 全程 U: 步进标记（root-bringup/layout/manifest/plan/iostart/prepared +
  每窗口 pub/media）。命令行换掉 sheng-disable-jobs（128B，launchd 阶段再换回）。
  **教训入档：判读表要按"最远可达路径"而不是"最可能失败点"核对一遍代码——
  v34b 的"预期屏幕"其实到不了 ext4 报告那行之后。**
- **H14（无机窗口期地雷，v34d 排除）**：代码复查 bsd_init.c 挂载后的验证链：iOS 目标
  `require_rootauth=TRUE` → `VNOP_IOCTL(FSIOC_KERNEL_ROOTAUTH)` 在无密封 restore-image 根上
  必返错，且未验证构建里 owner_authorized 恒 0 —— 即 **根挂上也会立刻
  panic("rootvp not authenticated after mounting")**，v34c 的 B 线剧本到不了 launchd。
  修复：z-z-z-liuqin-development-root-policy.patch（DEVELOPMENT && !SECURE_KERNEL 限定，
  opt-in boot 门 `liuqin_allow_unsealed_root=1`，只放行**只读**根，照 mondrian
  pong_allow_unauthenticated_root 的已验证设计；rootauth 错误值照打印、不谎报已认证），
  里程碑 `B:rootauth-unsealed`（H11 规则：上控制台，不上 panic 屏）。
- **H15（基座坑，连踩两次）**：build-xnu-4k-baseline.sh 在 stamp 失配时先反打 5 个 late 补丁、
  再逐补丁「可反打则跳过」——但 liuqin 系列在 osfmk/arm64/start.s 互相重叠，late 补丁的
  hunk 撑开早补丁的反打上下文后，早补丁既反打不动也正向打不进，构建死在 apply --check，
  只能手工重置 .cache/xnu-work。**基座修复 UniXNU@21fa272：stamp 失配 = reset --hard 到
  pinned rev + clean + 按名字序全量重放**（重放序即系列定序序，已在干净树上全量验证 61 补丁
  零失败）。无机窗口期两次把半死树留给自己踩，教训入档：改补丁=先跑一次干净重放再睡。
- **v34c（2026-11-16 17:32）**：H13 修复版，纯 fastboot boot；窗口剧本 A（安卓
  userdata 上验证诊断链）→ B（刷根）见 releases/v34c-NOTES.md。
- **v34d（2026-11-16 21:22）**：H14 修复版（liuqin_allow_unsealed_root 只读未认证根门 +
  B:rootauth-unsealed 里程碑）；H15 基座修复后首次全量重放产出内核 ecc3508b；
  剧本与判读见 releases/v34d-NOTES.md（相对 v34c 只加一段 rootauth 判读）。

### 4.5 M1 实机寄存器记录（v33e，2026-11-16 00:2x，IMG_6897-6900）

```
UFSCLK gdsc=f022f000 axi=00000221 ahb=00000001 unipro=00000221
UFSCLK tx=00000001 rx=00000001 aux=00000001 memgdsc=00000000(跳过)
UFSHC  rd=1 cap=1587031f ver=00000300 is=00000400
UFSHC  hcs=0000010f hce=00000001 utrlba=ff130000
```
判读：gdsc bit31=1（GDSC 上电）；全部分支 enable bit0=1；axi bit31=0（运行）；
hce=1（控制器由固件保持启用）；utrlba=ff130000（固件请求表基址在场）→ **adopt 路径前提成立**。
里程碑链 U58 probe-expert → U59 start-probe → U60..U63 + 四行值 → 启动继续到 B102-B106
（mountroot 区，正常）。附带确认：mapPhys 换 withPhysicalAddress 后不再挂（H12 修复实机验证）。

### 5. 上机后的最短验证链（八步证据流的后两步）

1. `fastboot boot` v33（H4 产物）→ 看 NativeUfs 里程碑：寄存器可读→GDSCR 过→adopt 列表→
   已知块读→root UUID 匹配→挂载（官方里程碑序：register→DMA→command→known-block read→
   root mount→persistence→performance，每步记 porting.toml）
2. userdata 刷入（阶段 4 计划内动作，`fastboot flash userdata`——**唯一允许写的数据分区**，
   persist/modemst/boot/vbmeta 仍禁）
3. v32→v33 两轮的 panic 文字/屏幕色带拍照归档

### 6. 风险表

| 风险 | 影响 | 缓解 |
|---|---|---|
| GccUfs 抄错/分支语义不同 | 时钟不开→控制器无应答 | adopt-first 设计本就少写时钟；对照 PongUfs 双源验证；驱动自带拒绝未测值 |
| liuqin ABL 不做 UFS init（adopt 失败） | 走不了 adopt 路径 | 退回全量 init（PongUfs 有完整序列可抄）；或固件开 UFSDxe |
| FVMAIN 99% 满 | UFSDxe 进不去 | H6 配平；或全量 init 不依赖固件 |
| iOS17 root 验证链（seal/trustcache/AKS） | 挂上 root 也起不了 launchd | 先保 root mount 里程碑；seal 问题与 mondrian「unauth root」思路做 AB 备胎 |
| 2GiB UFS 分支上限（K60 踩坑） | Data 窗口尺寸设计返工 | 镜像尺寸直接按 ≤2GiB 规划 Data；OS/SystemOS 只读无碍 |
| 卷 UUID 身份混淆 | 装错窗自检失败 | apfs.py 离线双哈希+安装脚本读回校验（照抄 mondrian 三重校验） |

### 7. 决策点（现在不用定，上机前定）

1. H4 编链若被 iOS17 存储 ABI 推导卡住 → 切 PongUfs+重推导(工作量↑) 还是等 sheng 组件更新(时间↑)？
2. adopt 失败 → 全量 init（代码多、风险高） vs 固件 UFSDxe（挤 FV）？
3. Data 放 userdata 窗口（liuqin 96GiB 已缩好） vs 照 K60 建独立 unixnu 分区（要改 GPT，动作大）？

——文档位置：UniXNU-liuqin/docs/route-plan-2026-11-15.md


---

## liuqin 移植计划

四阶段，每阶段都有"在屏幕上能看见"的通过标准。前一阶段不过，不进下一阶段。
全部启动都是 `fastboot boot`（内存运行，不写 boot 分区），失败复位就回原系统。

### 阶段 1：UEFI 固件（Windows/WSL 可编译，不需要 Mac）

要做的事
1. fork Mu-Silicium -> uefi-liuqin。底座用 `Silicon/Qualcomm/WaipioPkg`（SM8450）。
   SM8475 的 PMIC 家族（pm8350/8450/...）和 UFS PHY v4-cape 都在这一套里。
2. 新建 `Platforms/Xiaomi/liuqinPkg/`：liuqin.dsc / liuqin.fdf / liuqin.dec /
   DeviceBuild.py / Include/{APRIORI,DXE,RAW}.inc / Library/{ConfigurationMapLib,MemoryMapLib}。
   骨架照 `UniXNU/uefi-sheng` 分支的 shengPkg 抄，数值换 liuqin 的。
3. `Resources/Configs/liuqin.toml`：uefi_fd.base/size（未知，必须先从固件确认）、
   boot_image.*（header v0 / base 0 / kernel_offset 0x8000 / tags_offset 0x1e00000 / pagesize 4096）。
4. 厂商输入：从 HyperOS liuqin 整包抽 DisplayDxe、面板 XML、Clock、TLMM、I2C、PMIC 等，
   用 sheng 的 `extract-sheng-firmware.py` + `import-sheng-uefi.py` 当管线。
5. 补丁：先带 `Resources/MuPatches/Gic-Spurious.patch`。
6. 显示：sheng 的第一版是 `SHENG_VENDOR_HW=0`（只用 Mu 驱动 + SimpleFbDxe 在 ABL
   splash framebuffer 0xb8000000 上发布 GOP），这个思路 liuqin 直接可用 —— 同一块
   framebuffer，同样 45 MiB。

通过标准
- `fastboot boot` 后不复位，屏幕有输出或串口有 UEFI 日志。
- 能枚举 UFS 块设备，能读 FAT 负载卷。

### 阶段 2：UniXNU 启动管理器（不需要 Mac）

    ./unixnu build package           # EDK II，Linux 可编
    ./unixnu bootimg --uefi ../uefi-liuqin --dtb liuqin.dtb --ramdisk none

通过标准：串口出现 `UNIXNU:` 行、菜单出现、配置摘要打印。

### 阶段 3：内核（必须 macOS + Xcode）

- patches/xnu + NativePrelink，iOS 17 / ARM64 / BCM2837 / DEVELOPMENT。
- IPSW 沿用 iPad7,1 17.7.11（board.toml 已填好，与机型无关）。
- 通过标准：`DARWINBOOT:` 交接日志、内核到平台专家、打出 /cpus /arm-io。

### 阶段 4：存储与用户态（macOS）

- `build userdata`（要 hdiutil），窗口 = userdata 分区（96 GiB 或恢复 stock 后 940 GiB）。
- `fastboot flash userdata` 后启动，根卷 UUID 对上，launchd 起来。

### 进度（2026-10-20）

已经写完的东西

| 产物 | 位置 | 状态 |
| --- | --- | --- |
| liuqinPkg 平台包 | uefi-liuqin/Platforms/Xiaomi/liuqinPkg | 16 个文件：dsc/fdf/dec/DeviceBuild.py + Include/{APRIORI,DXE,RAW}.inc + 2 个 Library + 3 个驱动 |
| 厂商模块导入 | UniXNU-liuqin/scripts/import-liuqin-uefi.py | 跑通：93 个 AArch64 模块 + 56 个 raw，带 GUID/DEPEX/sha256 清单 |
| 内存表生成 | UniXNU-liuqin/scripts/gen-liuqin-memory-map.py | 跑通：43 个描述符（来自 uefiplat.cfg，一个重叠已按先到先得拆成 gap） |
| 配置表生成 | 同上 | 38 个数值项 + 单核 headless 覆盖 |
| 预检 | UniXNU-liuqin/scripts/check-liuqin.py | 跑通：93+56 个文件 sha256 校验、FD 窗口校验、面板 1800x2880 校验、描述符对齐/重叠校验 |
| 设备配置 | uefi-liuqin/Resources/Configs/liuqin.toml | uefi_fd = 0xA7100000 / 0x300000 |

从 sheng 改过来的地方（都有据可查）
- `!include KailuaPkg/KailuaPkg.dsc.inc` → `WaipioPkg/WaipioPkg.dsc.inc`（SM8475 的 PMIC/UFS PHY 属于 waipio 家族）
- 删掉 SOC_TYPE（那是 Kailua 的 AB/AC 区分）
- FrameBuffer 3048x2032 → 1800x2880
- SMBIOS 型号 sheng → liuqin
- 板级驱动改名 Liqin{BootMemory,DisplayDepex,GopLog}Dxe
- 52 条 vendor INF 从 `Binaries/sheng/QcomPkg/Drivers/...` 映射到 `Binaries/liuqin/Modules/<UI>/<UI>.inf`
  （TLMMDxe→DALTLMM、SPMIDxe→SPMI、I2CDxe→I2C、SPIDxe→SPI 这类按 UI 名对齐；全部 52 条都能落地）
- SecParti.cfg 的 FFS GUID 双向核对通过：liuqin 与 sheng 都是 A1E235DE-E825-4591-9623-C43175811826

### 还差什么才能出 boot.img

1. 整棵 Mu-Silicium 树（Silicon/、BootShim、Resources/Scripts/mkbootimg.py）+ 子模块
   Common/Mu、Common/Mu_OEM_Sample、Silicium-ACPI；以及 Mu_Basecore（edk2）。
2. 构建工具：clang / lld / make（WSL 里还没有，正在装）。
3. EDK II BaseTools 自举（unixnu 会自动做）。
4. 然后 `./unixnu build firmware --uefi ../uefi-liuqin` 出 SILICIUM_UEFI.fd，
   `./unixnu bootimg --uefi ../uefi-liuqin --dtb <liuqin.dtb>`（DTB 可以先从
   vendor_boot.img 里那个 Cape DTB 取，ABL 会自己套 dtbo）。

### 上机风险（静态无法排除的）

1. ABL 可能不接受 header v0（stock boot.img 是 v4）。失败就改打包 v4。
2. 单核 headless 配置下 SEC/DXE 是否接受 43 个描述符（sheng 是 72 个，硬件验证过）。
3. ~~DisplayDxe 的 DEPEX 依赖~~ —— 已核实：liuqin 的 DisplayDxe.depex（180B）推 10 个
   GUID，其中正好包含 sheng 胶水驱动装的那两个孤儿 GUID，所以 LiqinDisplayDepexDxe 照搬正确。
4. 3 MiB 的 FD 是否装得下 93 个厂商模块（PE32 合计 6.29 MiB，FV 是 LZMA 压缩的；
   sheng 的 107 个 FFS 能压进 3 MiB）。放不下就把窗口扩到 0xA7000000 / 0x600000。

### 已知的坑（从 sheng 抄来的经验）

- 缺 `splash_region` 节点 → ABL 直接 `DisableDisplay()` 关屏。liuqin 的节点已确认：0xb8000000 / 0x2b00000。
- SEC 必须先选 SP_ELx（上一级用 SPSel=0 进来，否则异常全跑在失效的 SP_EL1 上）。
- GIC 有未处理的 IPCC 中断（INTID 0x105）会死循环，Gic-Spurious.patch 要带。
- sheng 的 stock DisplayDxe 依赖两个全镜像找不到的协议 GUID，它用
  ShengDisplayDepexDxe 装空 flag 协议绕过。liuqin 的 DisplayDxe 依赖可能不同，
  要照这个办法重做一遍。


---

## liuqin 硬件底账

设备：Xiaomi Pad 6 Pro，代号 liuqin，SoC SM8475（骁龙 8+ Gen 1，Qualcomm 内部代号 cape），
1TB UFS（SK Hynix HN8T35DZHKX079），4096 字节逻辑/物理扇区。
本文件只写核实过的值，每条带来源。"未核实"另列。

### A. 已核实（可直接用）

| 项 | 值 | 来源 |
| --- | --- | --- |
| SoC | SM8475 / cape；compatible = "xiaomi,liuqin","qcom,sm8450" | liuqin-nixos sm8450-xiaomi-liuqin.dts |
| 主线归类 | 归到 sm8450 家族（含 alsa-ucm2 路径 Qualcomm/sm8450/Xiaomi-Pad-6-Pro） | liuqin-nixos |
| vendor_boot 里的 base DTB | 9 个 SoC 的 DTB，其中 Cape = 第 2 个（msm-id 0x212=530、0x21C? 见下） | 本地解包，见 D 节 |
| msm-id / board-id | msm-id = 531/540/530 各带 0x10000；board-id = <0x10008 0>；xiaomi,miboard-id = <0x10 0>（hwid.project=16 → 第 15 个 stock DTBO 条目） | liuqin-abl-boot-overlay.dts |
| 面板 | DSI `xiaomi,pipa-nt36532`，CSOT 模组 m81_42_02_0b，1800x2880，video mode，双 DSI | PORTING-NOTES |
| 背光 | KTZ8866 | PORTING-NOTES |
| 触控 | Novatek NT36532（笔、磁吸键盘、触控板） | PORTING-NOTES |
| ABL splash framebuffer | 0xb8000000，长 0x2b00000（45 MiB），1800x2880，a8r8g8b8，stride 1800*4 | sm8450-xiaomi-liuqin.dts chosen/framebuffer + reserved-memory/splash_region |
| ramoops | 0xa7000000，长 0x400000（4 MiB，console 2M + pmsg 2M） | 同上 |
| xbl_ramdump / xbl_sc | 0xa6b80000 +0x280000 / 0xa6e00000 +0x40000 | 同上 |
| adsp | 0x9fd00000 +0x3100000 | 同上 |
| PMIC 家族 | pm8350 / pm8350b / pm8350c / pm8450 / pmk8350 / pmr735a（= SM8450 waipio 那套，不是 SM8550 的） | 同上 include 列表 |
| UFS PHY | 0x1d80000（SM8450 是 0x1d87000），qcom,ufs-phy-qmp-v4-cape，v6 窗口 COM0/PCS 0x400/TX 0x1000/RX 0x1200 | 同上注释（对着 stock bootloader DTB 核过） |
| 按键 | 音量上、音量下、电源（无其它物理键） | golden 三键，BOOT-ARCHITECTURE |
| 音频 | 4 扬声器 CS35L41，mic WCD9385；vendor 无 AP 可见 DMIC | PORTING-NOTES |
| 指纹 | FPC1264 | PORTING-NOTES |
| 存储 | UFS，root ext4 | PORTING-NOTES（verified） |
| 现存系统 | Android 12 基线 + HyperOS（fingerprint liuqin:12/OS3.0.7.0.VMYCNXM），并已装 KernelSU + Ubuntu 双系统 | vendor_boot cmdline + E:\liuqin |
| 磁盘布局 | 见 E 节（userdata 起点 0x2A1600，被缩到 96 GiB，后面有 linux_root/linux_home） | E:\liuqin 备份 |
| stock 备份 | boot_a.img / boot_b.img（各 201MB）、vendor_boot_stock.img（100.6MB）、persist.img、GPT 头尾 | E:\liuqin-backup, ...\resize-backup-20261009 |

### B. 已核实（2026-10-20 第二轮，从 stock 固件抽出）

| 项 | 值 | 来源 |
| --- | --- | --- |
| UEFI FD 窗口 | 0xA7000000 +0x400000 "UEFI FD"，紧跟 0xA7400000 +0x200000 "UEFI FD Reserved" | uefi.elf → uefiplat.cfg |
| 固件内存表 | MaxMemoryRegions = 74，UnusableDDR 0x80000000+0x600000 | 同上 |
| ABL splash | 0xB8000000 +0x2B00000（Display Reserved） | uefiplat.cfg + 主线 DTS |
| Kernel 预留 | 0xA8000000 +0x10000000 | uefiplat.cfg |
| DXE Heap | 0xF8000000 +0x7C00000 | uefiplat.cfg |
| NumCpus | 8 / NumActiveCores 8，SecPagePoolCount 0x800 | uefiplat.cfg |
| UFS | EnableUfsIOC = 1，UfsSmmuConfigForOtherBootDev = 1 | uefiplat.cfg |
| 共享 IMEM | 0x146AA000，UefiMemUseThreshold 0x1900 | uefiplat.cfg |
| 面板模块 XML | Panel_M81_42_02_0b_dualdsi_dsc_lcd_video.xml（1800x2880，双 DSI，DSC，video） | uefi.elf RawFiles |
| 厂商 UEFI 模块 | 154 个文件（93 个 AArch64 PE32 + 58 个 Raw），含 DisplayDxe/UFSDxe/ClockDxe/PmicDxe/QcomBds | uefi.elf 递归解包 |
| DisplayDxe | 有效 PE32，machine 0xAA64，372,736 B | 直接校验 |
| stock boot.img | header_version = 4，header_size 1584，kernel 46.8 MB，ramdisk 1.38 MB | images/boot.img |

细节见 docs/vendor-inputs.md。

### B2. 仍然未知（上机才能定）

- SMEM chip_id（sheng=207 只对 SM8550 有效）与 SMEM RAM 表（dram_size）。
- ABL 是否接受 header v0 包装（stock 是 v4）。这是唯一"静态看不出来、必须试一次"的项。
- 触控 NT36532 的 I2C 地址/中断号（写 Native 触控驱动要用；主线 touchscreen@0 节点可参考）。
- stock 内存表 74 个区间与主线 DTS reserved-memory 的完整对齐（sheng 做了 72 个描述符，liuqin 还没做）。

### C. 关键结论

SM8475 与 SM8450 在 PMIC、UFS PHY 版本、整体内存布局上高度同族，
Mu-Silicium 的 `Silicon/Qualcomm/WaipioPkg` 是正确底座；
但 Mu-Silicium 上游没有 liuqin 平台包、没有 SM8475 设备配置，平台层全部要新写。

### D. 我已经做过的解包（可复现）

vendor_boot_stock.img：header v4，page 4096，vendor_ramdisk 23615663 B，
dtb 段在偏移 23621632，长 6443739 B，里面是 9 个拼接 FDT：

    00 Qualcomm Technologies, Inc. Cape LTE Only SoC
    01 Qualcomm Technologies, Inc. Cape SoC          <- liuqin 的底座
    02 Qualcomm Technologies, Inc. CapeP SoC
    03-06 Diwali 系列                                  (不是这台)
    07 Ukee SoC                                        (不是这台)
    08 Waipio LE                                       (不是这台)

Cape 那个 DTB 里 memory 节点是空的（reg = 0,0,0,0），reserved-memory 只有通用区，
板级区（splash、ramoops 等）由 dtbo 分区在 ABL 阶段叠加 —— 所以 splash 地址只能从
dtbo 或主线 DTS 里拿，不能从这个 DTB 里拿。

### E. 磁盘布局（实测）

```
# 当前布局（2026-10，userdata 已缩小）
 34 rescue       2725376 .. 2758143   0.12 GiB
 35 userdata     2758144 .. 27924479  96.00 GiB   0x2A1600 .. 0x1AA17FF
 36 linux_root  27924480 .. 36313087  32.00 GiB
 37 linux_home  36313088 .. 249179130 812.00 GiB

# stock 布局（GPT 备份 sda-head.bin）
 35 userdata     2758144 .. 249179130 940.02 GiB  0x2A1600 .. 0xEDA2BFA
```


---

## liuqin stock UEFI 厂商输入（已抽出）

来源：`E:\5555\liuqin_images_OS3.0.7.0.VMYCNXM_20260514.0000.00_15.0_cn_f57d372b08\...\images\uefi.elf`
（2,760,024 B，sha256 47785680513a7da753344dc86d3267a9…，固件版本 OS3.0.7.0.VMYCNXM）

抽法：ELF 里只有一个 FV（`_FVH` 在 0x1000，长 0x2A0000）→ 5 个 FFS → 其中 2 个是
GUID 定义压缩段（解出两个嵌套 FV，3.87 MB 和 3.10 MB）→ 递归展开后 159 个 FFS 文件。
其中 151 个带 UI 名。共抽出 **154 个文件**：58 个 Raw、93 个 PE32 模块。

产物：
- `liuqin-firmware/RawFiles/`（58 个：cfg、bmp、面板 XML）
- `liuqin-firmware/Modules/`（93 个 AArch64 PE32：DXE 驱动与应用）
- `liuqin-firmware/manifest.json`（每个文件的 GUID / FFS 类型 / sha256）
- `liuqin-modules.json`、`liuqin-uefi-tree.txt`（结构清单）

### 关键文件

| 文件 | 字节 | 段 | sha256 前 16 |
| --- | --- | --- | --- |
| RawFiles/uefiplat.cfg | 8050 | 0x19 | `5116faca4329b3b9…` |
| Modules/DxeCore | 196608 | 0x10 | `3ba8ead12f3ae067…` |
| Modules/ArmCpuDxe | 53248 | 0x10 | `32cd8b783aa72d6c…` |
| Modules/ArmGicDxe | 36864 | 0x10 | `7adc78a950e91a40…` |
| Modules/ChipInfo | 49152 | 0x10 | `a5e82f79034ac268…` |
| Modules/IPCCDxe | 45056 | 0x10 | `e91f717f5a3a3e73…` |
| Modules/GlinkDxe | 61440 | 0x10 | `9fbbf72bc75995c0…` |
| Modules/PlatformInfoDxeDriver | 32768 | 0x10 | `3f145b99b08d5181…` |
| Modules/ProjectInfoDxe | 57344 | 0x10 | `88121f2f5e4b99d6…` |
| Modules/HWIODxeDriver | 36864 | 0x10 | `32cbee375305035e…` |
| Modules/I2C | 49152 | 0x10 | `3b2904198c63bfce…` |
| Modules/DALTLMM | 49152 | 0x10 | `9233f83a9c8756bf…` |
| Modules/PmicDxe | 204800 | 0x10 | `44f40a685f7ce7f7…` |
| Modules/DiskIoDxe | 45056 | 0x10 | `be382ac80d1cd1d2…` |
| Modules/PartitionDxe | 53248 | 0x10 | `f421503ce47c2542…` |
| Modules/Fat | 65536 | 0x10 | `39af831ac8692db7…` |
| Modules/FvSimpleFileSystem | 45056 | 0x10 | `39d7888e0dd2432a…` |
| Modules/UFSDxe | 131072 | 0x10 | `c76d6f7522dcf69c…` |
| Modules/CmdDbDxe | 32768 | 0x10 | `8adac8f156c67da8…` |
| Modules/RpmhDxe | 65536 | 0x10 | `7f917c9e9c64ba11…` |
| Modules/NpaDxe | 81920 | 0x10 | `9ced898ce160f69a…` |
| Modules/ULogDxe | 77824 | 0x10 | `7472b6fca3e979dc…` |
| Modules/VcsDxe | 49152 | 0x10 | `bbf9e0e6e3534a2d…` |
| Modules/ClockDxe | 200704 | 0x10 | `f855406a63e42546…` |
| Modules/SmemDxe | 40960 | 0x10 | `b0843f6a7b918bd6…` |
| Modules/QcomBds | 122880 | 0x10 | `d3cffcba15a68731…` |
| RawFiles/BDS_Menu.cfg | 2944 | 0x19 | `1786bfcb2616efed…` |
| RawFiles/SecParti.cfg | 5150 | 0x19 | `fec3e97db6b6ffcc…` |
| Modules/GraphicsConsoleDxe | 49152 | 0x10 | `610bede37c247e86…` |
| Modules/SPI | 57344 | 0x10 | `59ecebb5a662aedc…` |
| Modules/FeatureEnablerDxe | 32768 | 0x10 | `ef9effb68f191eb7…` |
| Modules/DisplayDxe | 372736 | 0x10 | `d6a934cc70f37310…` |
| Modules/ButtonsDxe | 40960 | 0x10 | `4393f4a580ae5abd…` |
| Modules/IPCCDxe | 45056 | 0x10 | `e91f717f5a3a3e73…` |
| Modules/GlinkDxe | 61440 | 0x10 | `9fbbf72bc75995c0…` |
| Modules/PmicGlinkDxe | 49152 | 0x10 | `666af3296312ba9c…` |
| Modules/TsensDxe | 32768 | 0x10 | `8b1d6d0aa58ddea5…` |
| Modules/DDRInfoDxe | 45056 | 0x10 | `3964e347fe39369b…` |
| Modules/UsbfnDwc3Dxe | 98304 | 0x10 | `696a6a9065fec315…` |
| Modules/XhciDxe | 94208 | 0x10 | `39f5f0e90ae1da68…` |
| Modules/PILDxe | 118784 | 0x10 | `1cac0e5c3e73c2dd…` |
| RawFiles/logo1.bmp | 31318 | 0x19 | `abc0de5542c46d0d…` |
| RawFiles/PanelSimConfig.csv | 3081 | 0x19 | `71fe6237584883fd…` |
| RawFiles/Panel_M81_36_02_0a_dualdsi_dsc_lcd_video.xml | 6434 | 0x19 | `d8fb21cb7452966b…` |
| RawFiles/Panel_M81_42_02_0b_dualdsi_dsc_lcd_video.xml | 6195 | 0x19 | `a3e7649ab12793d1…` |
| RawFiles/uefipil.cfg | 5263 | 0x19 | `dfa8b53c737ef54d…` |
| RawFiles/QcomChargerCfg.cfg | 21075 | 0x19 | `c3b10d1bb9766dae…` |

### uefiplat.cfg 里的硬数据

```
MaxMemoryRegions = 74         UnusableDDRMemory 0x80000000 +0x600000
0x80000000 0x00600000  HYP
0x85200000 0x1DC00000  PIL Reserved
0xA1400000 0x02B00000  Display Demura
0xA7000000 0x00400000  UEFI FD            <-- 我们的固件卷窗口
0xA7400000 0x00200000  UEFI FD Reserved
0xA7AD9000 0x00400000  FV Region
0xA8000000 0x10000000  Kernel
0xB8000000 0x02B00000  Display Reserved  <-- ABL 连续 splash framebuffer
0xF8000000 0x07C00000  DXE Heap
NumCpus = 8   NumActiveCores = 8   SecPagePoolCount = 0x800
SharedIMEMBaseAddr = 0x146AA000   UefiMemUseThreshold = 0x1900
EnableUfsIOC = 1  UfsSmmuConfigForOtherBootDev = 1
```

### 面板

liuqin 的面板模块 XML 就在固件里，名字是
`Panel_M81_42_02_0b_dualdsi_dsc_lcd_video.xml`（正是主线记录的 CSOT 模组 m81_42_02_0b）：
HorizontalActive = 1800、VerticalActive = 2880、双 DSI、DSC、video mode。
（同族 `Panel_M81_36_02_0a_...` 是另一块屏，别选错。）

### DisplayDxe 已核验

`Modules/DisplayDxe` 是有效 PE32，machine = 0xAA64（AArch64），372,736 B。
这是后面接 GOP / 点屏的关键模块，sheng 的做法是把它的 DEPEX 依赖补齐
（它 original DEPEX 要求 9 个协议，其中 7 个由厂商驱动提供，另外 2 个
全镜像里找不到，就用一个自建 Dxe 装空 flag 协议绕过）。liuqin 要走同一条路。


---

## 内核 USB 调试口（liuqin）

从 vermeer 实验室仓库（github.com/xyyyds0106/ios-vermeer-lab 的 USB-DEBUG.md 与
xnu/vermeer/vermeer_usb_debug.c）移植到 Xiaomi Pad 6 Pro / liuqin / SM8475。

### 是什么

内核里一个 opt-in 的 USB CDC-ACM 串口，把内核 console 输出（1 MiB 环形缓冲）流给主机，
并提供四条只读命令。没有 shell、没有任意内存读、没有存储/重启操作。

    VID:PID      1209:0002   （实验室 ID；vermeer 用 1209:0001，用 PID 区分两台机器）
    伪序列号      LIQDBG001   （Windows 靠它认出正确的 COM，不会误选别的串口）
    波特率        115200 8N1  （对 USB 只是名义值）
    端点          EP0 控制 / EP1 IN 应答 / EP2 OUT 命令 / EP3 IN 日志流 / EP5 IN CDC notify

命令（每条一行）：`help` `status` `ping` `replay`

### 开关

board.toml 的 `[payload] kernel_args` 里加 `liuqin_usb=1`（默认已加）。
一次性覆盖：

    ./unixnu build payload --kernel-arg liuqin_usb=1

打开 COM 口必须置 DTR，否则内核一个字节都不会发（transmit() 里的 u.dtr 检查）。

### 移植时换掉的常量（都是 SM8475 的实测/文档值）

| 项 | vermeer (SM8550) | liuqin (SM8475) | 依据 |
| --- | --- | --- | --- |
| DWC3 基址 | 0xa600000 | 0xa600000（wrapper 窗口 0xfc100） | linux sm8450.dtsi usb@a600000 |
| QSCRATCH | base+0xf8800 | base+0xf8800 = 0xa6f8800 | 落在同一 wrapper 窗口内 |
| GCC 块 | 0x139000 (gcc+0x39000) | 0x149000 (gcc+0x49000) | linux sm8450.dtsi clock-controller@100000 |
| USB30_PRIM GDSC | +0x04 | +0x04 → 0x149004 | gcc-sm8450.c usb30_prim_gdsc |
| master halt | +0x18 | +0x18 → 0x149018 | gcc-sm8450.c gcc_usb30_prim_master_clk |
| cfg_noc halt | +0x88 | **+0x84** → 0x149084 | gcc-sm8450.c gcc_cfg_noc_usb3_prim_axi_clk |
| aggre halt | +0x8c | **+0x88** → 0x149088 | gcc-sm8450.c gcc_aggre_usb3_prim_axi_clk |
| APPS SMMU | 0x15000000 | 0x15000000（窗口 0x100000） | linux sm8450.dtsi iommu@15000000 |
| USB stream ID | 0x40 | **0x00** | linux sm8450.dtsi usb_1 的 iommus |
| DMA 窗口 | 0x8c0000000..0x940000000 | 0x80000000..0x100000000（可覆盖） | liuqin DDR 底 0x80000000 |

注意 cfg/aggre 的偏移和 SM8550 差 4 字节：照抄 vermeer 会读到错的寄存器。

### 四道自检门（任一不过就完全不碰控制器，系统照常启动）

1. **GCC**：GDSC bit31 必须为 1（power domain 已开），master/cfg/aggre 三个 halt 寄存器 bit31 必须为 0。
   本驱动从不写 GCC。
2. **控制器身份**：GSNPSID 高位必须是 0x5533/0x3331，GCTL 的 mode 必须是 2（device）。
3. **SMMU**：要求恰好有一条 SMR 匹配 USB stream ID，且路由是 identity/bypass
   （S2CR type=1，或 type=0 + CBAR type=1 + SCTLR 未使能）。绝不新建映射、绝不放宽隔离。
   bring-up 阶段如果板上 SID 与预期不同，日志会打印 `SIDx matches N`，
   可临时用 `liuqin_usb_sid=0xNN` 改 SID、`liuqin_usb_smmu=0` 跳过这道门（仅诊断用）。
4. **DMA**：16 KiB 永久连续块，必须整个落在窗口内、16 KiB 对齐、不超过控制器地址宽度。
   窗口可用 `liuqin_usb_dma=0x80000000,0x100000000` 覆盖；被拒时日志打印实际 PA。

通过后：停 RUN → 等 HALTED → 软复位 → 装 4 KiB event ring → DCFG 只跑 high speed →
epcmd(START_CONFIG/SET_CONFIG/SET_RESOURCE) → 写 QSCRATCH 的 VBUS-valid 覆盖位 → RUN → 1 ms 轮询线程。

### 代码落点

    补丁  patches/xnu/zzz-liuqin-usb-debug.patch   （必须排在内核补丁最后：zzz-boot-progress 之后）
    新增  bsd/dev/liuqin_usb_debug.c    传输层（DWC3 寄存器直操）
          bsd/dev/liuqin_debug.c        RAM 环形缓冲
          bsd/dev/liuqin_log_ring.h     1 MiB 环形缓冲
          bsd/dev/liuqin_usb_protocol.h 描述符 + 控制请求白名单
    挂点  osfmk/console/serial_console.c  _cnputc() 里做镜像（在 boot_progress 抢走之前）
          pexpert/arm/pe_kprintf.c       serial_putc_crlf() 里镜像早期 PE 输出
          bsd/kern/bsd_init.c            bsd_init() 里启动（load_init_program 之前）
          bsd/conf/files.arm64           注册两个目标文件

`patches/xnu/` 在设备仓库里是完整的一份（49 个 UniXNU 基础补丁 + 本补丁），
因为模块是按目录覆盖的：设备仓库一旦提供 patches/xnu，就会替换基础仓库的同名模块。
升级 UniXNU 基础补丁后要重新同步（见下）。

### 主机侧抓取（Windows）

    powershell -File tools/capture-liuqin-debug.ps1 -Seconds 600

脚本按 VID_1209&PID_0002 + 序列号 LIQDBG001 精确定位 COM，置 DTR/RTS，115200 8N1，
滚动写 32 MiB 一个文件；`-ObserveFrames` 这类 GUI 计数在 liuqin 上不适用（没有 GUI 采样器）。

### 已验证 / 未验证

已验证：补丁在 xnu-10063.141.1 + 49 个 UniXNU 补丁的树上 `git apply` 干净通过；
`tests/liuqin_usb_host_test.c` 覆盖环形缓冲、控制请求白名单、DMA 窗口判定、SMMU 流匹配，
gcc 全绿；两个新增 C 文件用 XNU 桩头文件 `gcc -fsyntax-only` 干净通过。

未验证（需要真机）：控制器是否真的停在 ABL 留下的 device mode、SMMU 是否给 USB SID 建了
identity 路由、DMA 落在哪个 PA。第一轮上机的判读方法：屏幕（boot-progress）或串口会打印
`LIUQIN USB: GCC .../ id=.../ SIDx matches .../ DMA ...`，其中任何一行被拒就说明卡在哪道门。

### 已知限制（沿用 vermeer 的设计）

- 拔线、主机发总线复位、event ring 溢出 → 端口停下并保留 DMA，必须重启内核才能重连；没有 panic 时轮询。
- 只有日志和四条只读命令，不是交互式调试器。
- `boot-progress=2` 时屏幕仍归 boot_progress 所有，USB 镜像的是同一份字节流，两边不冲突。

### 在 GitHub Actions 的 macOS runner 上编内核（不用租 Mac）

UniXNU 自带 `.github/workflows/macos.yml`（runs-on: macos-latest），输入里可以指定
设备仓库、分支、defconfig 和步骤。这台机器直连不了 github.com 但 api.github.com 通，
所以建仓/上传/dispatch/取产物全部走 REST API：

    GITHUB_TOKEN=<PAT> python3 tools/gh-build-liuqin.py --dry-run   # 先看要做什么
    GITHUB_TOKEN=<PAT> python3 tools/gh-build-liuqin.py --steps kernel

它做四件事：
1. 建 `<账号>/UniXNU-liuqin` 仓库，用 Git Data API 上传本仓库 68 个文件（不需要 git push）；
2. fork UniXNU，把分支 `liuqin-build` 钉在 `7b52e7968c76453cdc18b5aa174fc368d5293b91`
   —— 补丁就是对着这个提交验证的，避免 main 漂移；
3. 用输入 `device_repository / device_ref / defconfig=liuqin_defconfig / steps=kernel` dispatch；
4. 等跑完，把 `unixnu-liuqin_defconfig.zip` 下到 `~/liuqin-gh/`。

跑完的内核在本机打包（payload 要 unique-chip-id，留在这边做）：

    mkdir -p ~/port/UniXNU/out/liuqin/kernel && unzip -j ~/liuqin-gh/unixnu-liuqin_defconfig.zip '*/kernel.macho' -d ~/port/UniXNU/out/liuqin/kernel/
    scripts/pack-bootimg-liuqin.sh
    fastboot boot ~/port/UniXNU/out/liuqin/boot/boot.img

设备仓库默认建成 **public**：workflow 用 `github.token` 去 checkout 设备仓库，
默认 token 只能读 workflow 所在仓库，public 才免配置。要 private 就得在 fork 里加
`UNIXNU_DEVICE_TOKEN` secret（脚本没有替你设，需要的话手动加或告诉我）。
fork 的 Actions 默认是关闭的，脚本会尝试用 API 打开；如果 dispatch 报
"workflows are disabled"，在 fork 的 Actions 页面点一次 Enable 即可。
