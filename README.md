# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

把 iOS 17 的 XNU 内核移植到小米平板 6 Pro 的工程记录。
**所有测试都只 `fastboot boot`（纯内存运行），不写设备任何分区。**

当前里程碑：**v40 — UFS 存储链路打通**（2026-11-19 实机验证）。

---

## 一、现在到哪了

| # | 里程碑 | 状态 |
|---|---|---|
| 0 | Linux 构建链（固件 / 内核 / prelink / payload / boot.img） | ✅ 不需要 macOS |
| 1 | 固件启动 → UniXNU 菜单 → payload 卷挂载 | ✅ 实机 |
| 2 | 内核启动 → `bsd_init` → `startRoot` | ✅ 实机 |
| 3 | v39 元类修复（H16-F） | ✅ 实机通过 |
| 4 | **UFS 控制器初始化 + 链路启动 + LUN 就绪** | ✅ **实机打通（v40）** |
| 5 | **读 userdata GPT / 解析根布局** | ✅ **实机打通（v40）** |
| 6 | iOS 根卷挂载（T1） | ⛔ 需要 iOS userdata |
| 7 | `launchd` / 桌面（T2） | ⛔ 未开始 |

实机证据（`fastboot boot`，2026-11-19 最后一轮）：

```
NativeUfs: M:reg pre p=0xfffffff007adb6b0 link=0xfffffff007add1d0   ← 家族元类，不是毒值
U:meta-ok                                                          ← ABI 闸 + 链校验通过
U:72:h:pre-used                                                    ← STARTUP 阶段预留的 DMA 区
U:80:h:stopq-ok → U:81:h:NOP OUT → U:83:h:nop-ok                   ← UniPro 链路起来了
U:84:h:power mode query → U:85:h:LUN ready                          ← 设备应答
U:86:root-bring-up-ok → U:87:root-layout-ok                        ← READ(10) 读回 GPT，布局解析成功
UFS BOOT FAILURE: root manifest rejected                           ← 预期：设备上还没有 iOS 根镜像
```

诊断行同时给出控制器状态（`op=28` 即 READ(10)、`ocs=00`），说明**块设备读写路径本身是通的**，
只差一份合法的 iOS 根清单。

---

## 二、快速开始（测试已有镜像）

从 [Releases](https://github.com/Fly116/UniXNU-liuqin/releases) 下载最新 `boot-v40-*.img`：

```bash
adb reboot bootloader
fastboot boot boot-v40-prealloc.img
```

菜单 15 秒后自动启动 `xnu`，屏幕会一路走到
`U:87:root-layout-ok`，并以 `UFS BOOT FAILURE: root manifest rejected` 结束——
这就是**没有 iOS 数据时**这台设备能达到的最远位置。

> 只用 `fastboot boot`，不要 `flash`。重启即回 Android。

---

## 三、v40 打通了哪些技术难点

原作者 fork 卡在"驱动一碰存储就挂死"。这一轮在真机上逐层定位，确认是三个叠加的问题：

### 3.1 非苹果平台没人初始化 `IOMapper`

```cpp
IOMapper * IOMapper::gSystem = (IOMapper *) IOMapper::kUnknown;   // 1，带等待位
void IOMapper::setMapperRequired(bool hasMapper) { ... gSystem = kNoMapper; }  // 只有苹果 platform expert 调
```

`waitForSystemMapper()` 会一直 `sleep` 在 `gSystem` 上，直到它从 `kUnknown` 变成
`kNoMapper(0)`/`kHasMapper(2)`。非苹果平台没有代码调用 `setMapperRequired()`，
于是**任何 `IOBufferMemoryDescriptor` 创建都可能永久睡眠**。

修复：驱动里在任何描述符创建前显式 `IOMapper::gSystem = (IOMapper *) 0;`。

### 3.2 wired（不可分页）描述符的 `prepare()` 永不返回

用金丝雀实验逐层缩小：

```
h:t1-kalloc     → ok     普通 kalloc 正常
h:t2-contig4k   → 挂     4K 连续分配
h:t3-plain4k    → 挂     普通描述符
h:c2-pageable   → ok     pageable 描述符正常
h:c3-wired      → 挂     非分页（wired）描述符
```

挂点在 `kIOMemoryAutoPrepare → prepare() → wireVirtual()`。而驱动真正需要的只是
"一块物理连续内存 + 它的物理地址"，于是**完全绕开 IOKit 描述符**：

```cpp
kmem_alloc_contig(kernel_map, &va, bytes, 4095, 0, 0, KMA_ZERO, VM_KERN_MEMORY_IOKIT);
phys = ml_vtophys(va);
```

### 3.3 早期连续页分配不可靠 + `mach_absolute_time()` 不前进

在驱动 `start()` 阶段做 `kmem_alloc_contig`，十次里约五次会卡在
`vm_page_find_contiguous` 的页队列扫描里；而且该阶段的 `mach_absolute_time()`
不前进，导致所有基于 deadline 的等待（`IODelay`、`WFE` + 定时器）永不返回。

修复两件事：

1. **在 `STARTUP_SUB_EARLY_BOOT` 阶段预留 DMA 区**（内存几乎全空，扫描必成功），
   `hostBringUp()` 直接复用（`h:pre-used`）；
2. 完成等待的 `IODelay(2)` 换成**固定次数忙循环**，并给轮询循环加固定上限，
   不依赖时间与中断。

### 3.4 效果

`hostBringUp()` 从"第一步分配就挂死"变成完整跑完：

```
controller map → DMA → slot geometry → civac → SMMU 配置 → 停队列
→ 启动请求列表 → NOP OUT → 电源模式查询 → LUN 就绪
```

随后 `startRoot()` 通过真实 `READ(10)` 读回 userdata 的 GPT 并解析根布局
（`root-layout-ok`），最后在根清单校验处按预期拒绝。

---

## 四、从零构建

完整步骤与排错表见 [`patches/`](https://github.com/Fly116/UniXNU-liuqin/tree/main/patches)
以及本 README 的历史章节。核心命令：

```bash
# 1. 代码
git clone --depth 1 --branch liuqin https://github.com/1696108518/UniXNU.git UniXNU
git clone https://github.com/hhyygg2009/UniXNU-liuqin.git device
git clone --depth 1 https://github.com/hhyygg2009/uefi-liuqin.git uefi-liuqin
cd uefi-liuqin && git submodule update --init --depth 1
cd Mu_Basecore && git submodule update --init --depth 1

# 2. 工具链（装到 /opt/unixnu-linux）
cd ../UniXNU && sudo scripts/linux/setup-toolchain.py -j $(nproc)

# 3. 从官方线刷包抽厂商 UEFI 模块
tar -xzf liuqin_images_OS1.0.14.0.UMYCNXM_*.tgz --wildcards '*/images/uefi.elf'
python3 ../device/scripts/import-liuqin-uefi.py --uefi-file .../uefi.elf \
    --out ../uefi-liuqin/Binaries/liuqin --version OS1.0.14.0.UMYCNXM

# 4. 打补丁（设备仓库 + 驱动），然后构建
cd /root/work/device && git apply .../device-bringup.diff
cd drivers/ShengUfs && git apply .../liuqin-v39-metaclass-repair.diff && git apply .../shengufs-prealloc.diff

export XNU_OWNER_ROOT_VOLUME_UUID=18AB5557-DC2D-469B-8758-855E60F5B0DF
export UNIXNU_PATCH_LIST=manual
python3 ./unixnu build kernel -D /root/work/device
python3 ./unixnu build payload --kernel out/liuqin/kernel/kernel.macho \
    --unique-chip-id 0x84750A0B0C0D0001 -D /root/work/device
python3 ../device/scripts/wrap-payload-mbr.py out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
python3 ./unixnu build firmware --uefi ../uefi-liuqin --edk2 ../uefi-liuqin/Mu_Basecore -D /root/work/device
python3 ./unixnu bootimg --uefi ../uefi-liuqin \
    --fd ../uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --dtb ../uefi-liuqin/Resources/DTBs/liuqin.dtb \
    --ramdisk out/liuqin/payload/payload-mbr.img -D /root/work/device
```

**固件必须打开的一个开关**（`uefi-liuqin/Platforms/Xiaomi/liuqinPkg/liuqin.dsc`）：

```
DEFINE LIUQIN_INITRD_DISK_ENABLED = 1
```

没有它，`UniXNURamDiskDxe` 不会进 FV，ramdisk 永远发布不成块设备，
UniXNU 菜单会报 `no boot entry found`（红字 `fs=0`）。这是最隐蔽的坑。

### 常见构建问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `test -f "$CRYPTO_ARCHIVE" failed` | archives 未构建 | `CONFIG_XNU_BUILD_ARCHIVES=y` |
| `ModuleNotFoundError: native_prelink` | 找 `kits/XnuPrelink`，旧树叫 `NativePrelink` | 用 `patches/bringup-2026-11-18/device-bringup.diff` |
| `patch does not apply osfmk/arm64/start.s` | 补丁被套两遍 | 预打补丁 + `UNIXNU_PATCH_LIST=manual` |
| `Native kernel lacks sparse-prelink index ABI` | 漏了 `kits/XnuPrelink/patches/*` | 两个 kit 补丁也要打 |
| 菜单 `no boot entry found` / `fs=0` | `LIUQIN_INITRD_DISK_ENABLED` 未开 | DSC 加 `DEFINE … = 1` |

---

## 五、实机调试方法

### 5.1 面板里程碑

内核通过 `liuqin_milestone(tag, msg)` 把里程碑直接画到屏幕（`liuqin_fb_putc`），
不依赖串口/中断。编号是**全局递增**的，所以能精确看出"最后一条"：

| 前缀 | 含义 |
|---|---|
| `K` | 内核早期（PE / lockdown） |
| `B` | BSD 初始化 |
| `U` | 驱动 / 存储 bring-up |
| `I` | IOKit |
| `M` | 元类登记（v38/v39 的诊断） |

存储 bring-up 的里程碑序列：

```
h:controller map → h:DMA allocation → h:lock → h:pre-used → h:lock-ok
→ h:geom → h:slots → h:civac → h:SMMU and request list → h:stopq
→ h:stopq-ok → h:NOP OUT → h:nop-wait → h:nop-ok
→ h:power mode query → h:LUN ready → root-bring-up-ok → root-layout-ok
```

### 5.2 USB 调试口（可选）

内核内置 USB CDC-ACM 调试口（`1209:0002`，伪序列号 `LIQDBG001`），
用 payload 参数 `liuqin_usb=1` 打开；注意其初始化会**挡住启动**，仅在系统稳定后启用。

---

## 六、历史（v35 → v39）

### v35–v38：元类登记问题

- v37 否证了"脏数组"假设；
- v38 点名成功：`M:bad[170] bad-chain n=NativeUfsBlock`，同时推翻了两个前提；
- 结论：不是驱动静态量踩的，而是 `NativeUfsBlock::gMetaClass + 0x10`（`superClassLink`）
  在登记批次里被污染，导致 `postModLoad` 链校验失败并被丢弃。

### v39：受控修复（H16-F）

在 `startRoot` 序言里用运行时查到的家族元类把 `superClassLink` 写回：

- 幂等写 + `M:reg pre/prep` 快照 + `getClassSize()` ABI 闸 + 有界链校验；
- 删除 v36 的假阳性 gate；
- 补丁：`patches/driver/liuqin-v39-metaclass-repair.diff`。

实机结果：`M:reg pre` 显示正确的家族元类、`meta-ok`、`M:stalled post cnt=1` 且扫描保留本类。
**元类问题在 v39 解决。**

（为什么不能照搬 whyred 的 `__GLOBAL__sub_I_*` 重注册：本 TU 里还有 `NativeUfs` 自身的元类，
重跑 TU 初始化器会二次登记直接 panic。）

---

## 七、路线图

### T1：根卷挂载（下一步）

需要给设备一份 **iOS 根镜像**：把 userdata 尾部切出 APFS 窗口、写入根清单与卷。
这一步**会改分区表**（可逆：缩 f2fs + 新建分区，Android 数据保留），但必须：

1. 先用 TWRP 等做完整 Android 备份；
2. 确认设备容量与现有布局（`userdata` 当前边界可从 GPT 读）；
3. 用共存方案切分，写入 iOS 根镜像。

**在完成 T1 之前，所有实验仍然零写入。**

### T2：用户态与桌面

`launchd` 需要可写的 `/private/var`：

- 方案 A：内存盘当可写卷（零分区写入，但重启即丢；mondrian 记录显示 APFS on memory 可能挂死）；
- 方案 B：UFS 数据窗口（持久，需要 T1 的切分）。

之后还有显示、触控、GPU 合成器等工作（当前 defconfig 里这些特性是关闭的）。

同 SoC 的参考实现：[Emilelu/UniXNU-mondrian](https://github.com/Emilelu/UniXNU-mondrian)
（红米 K60 / SM8475，存储/显示/触控/GPU/USB 均已实机打通，目标 iOS 16.6.1）。

---

## 八、仓库结构

```
patches/
  driver/              NativeUfs 的 v39 元类修复补丁
  bringup-2026-11-18/  11-18 轮：设备仓库与驱动改动
  bringup-2026-11-19/  11-19 轮：存储链路打通（含最终驱动 diff 与 VM 诊断补丁）
tests/metaclass-simtest/  元类场景主机仿真（A–E）
drivers/ShengUfs/     UFS 驱动（子模块，fork 分支 liuqin-sm8475-v39）
```

构建产物不入库，走 Releases（每个镜像约 66 MB）。

---

## 九、致谢

- 上游主线：[hhyygg2009/UniXNU-liuqin](https://github.com/hhyygg2009/UniXNU-liuqin)；
- 同 SoC 参考：Emilelu/UniXNU-mondrian（SM8475）；
- 设备与实机验证：**@Fly116**；
- UniXNU 官方与各社区机型仓。
