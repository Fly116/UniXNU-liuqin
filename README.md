# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

在**高通骁龙 8+ Gen 1（SM8475）的小米平板 6 Pro** 上，让 XNU（Darwin / iOS 内核）跑起来的不完整移植仓库。

> ## ⚠️ 请先读完这段，再决定要不要继续折腾
>
> **这个仓库目前无法启动 iOS 用户界面，也看不到任何 iOS 桌面。**
>
> 现状是：内核能启动、UFS 存储链路能跑通、能读取真实的 iOS 根镜像、能把镜像窗口发布成块设备；
> 但**根卷还没挂载成功**，更没有 `launchd`、没有图形界面。所有发布出去的镜像都只是
> **实验性 bring-up 镜像**，仅用于 `fastboot boot` 内存启动调试。
>
> 另外必须说明一个**硬件层面的现实**：iOS 的图形栈依赖 Apple 自己的 GPU（Metal 驱动）。
> 这台机器目前没有GPU驱动
>
> 本仓库**没有**任何写入 Android 分区的自动化脚本，所有实验默认 `fastboot boot`（只进内存）。
> 除非你清楚自己在做什么，**不要**照搬本仓库历史中的分区改造步骤。

---

## 一、这个项目是什么 / 不是什么

**是**：

- 一个「把 XNU 移植到非苹果 SoC」的工程实验记录：包含板级描述、内核补丁、UFS 块设备驱动、
  构建脚本、以及大量实机调试结论与踩坑档案；
- 一份**可复现的构建与调试方法**：从官方线刷包抽 UEFI、构建 XNU、打包 `boot.img`、
  在真机上用面板里程碑定位卡点。

**不是**：

- 不是能日常使用的系统，不是「刷完就能进 iOS」的一键包；
- 不是与苹果官方相关的项目；
- 不提供任何对 Android 分区的自动破坏性操作。

---

## 二、当前进展总览

| # | 里程碑 | 状态 | 说明 |
|---|--------|------|------|
| 0 | Linux 构建链（固件 / 内核 / prelink / payload / boot.img） | ✅ | 不需要 macOS |
| 1 | 固件启动 → UniXNU 菜单 → payload 卷挂载 | ✅ 实机 | Mu-Silicium UEFI |
| 2 | 内核启动 → `bsd_init` → `startRoot` | ✅ 实机 | |
| 3 | 元类（`OSMetaClass`）修复 | ✅ 实机 | 见 §3.5，后来的结论是"符号绑定少了一次 slide" |
| 4 | UFS 控制器初始化 / 链路启动 / LUN 就绪 | ✅ 实机 | v40 打通，READ(10) 可用 |
| 5 | 读 GPT / 解析 SHNGROOT 根清单 | ✅ 实机 | `root-layout-ok` / `root-manifest-ok` |
| 6 | 设备分区改造：`userdata` → 94 GiB + 新增 `unixnu` 11.79 GiB | ✅ 实机 | 见 §5，**会动分区表**，务必先备份 |
| 7 | 把 8.74 GiB iOS 根镜像写入 `unixnu` 并被内核接受 | ✅ 实机 | `root-plan-ok` / `root-iostart-ok` |
| 8 | 发布窗口为块设备（`IOBlockStorageDevice`） | 🟡 部分 | 构造函数、注册均已打通，但 **IOKit 迟迟不创建 `IOMedia`** |
| 9 | APFS 根卷挂载（T1） | ⛔ 未完成 | 卡在 #8 |
| 10 | 用户态 `launchd`（T2） | ⛔ 未开始 | |
| 11 | 图形界面 | ⛔ 未开始，且受 GPU 限制（见顶部警告） | |

一句话概括：**存储这一层（最难、最硬件相关）基本打通；根卷挂载还差一步；用户态与界面还没开始。**

### 进度参考（按工作量粗略估计）

- 硬件/存储 bring-up：约 100%
- 块设备发布：约 85–90%
- APFS 根卷挂载：约 10%
- 用户态：约 0%
- 图形界面：0%

综合约 **45–50%**（以"能看到某种界面/用户态输出"为目标）。

---

## 三、已经实机打通的硬骨头（技术档案）

这一节是本仓库最有价值的部分：每一条都是在这台真机上验证过的结论，能帮后来者少走几天弯路。

### 3.1 非苹果平台没人初始化 `IOMapper`

IOKit 的 DMA 路径默认依赖 `IOMapper::gSystem`，而它在苹果平台上由特定驱动设置。
非苹果平台永远保持 `kUnknown`，导致所有需要映射的分配路径不可用。
**处理**：驱动里显式 `IOMapper::gSystem = 0`，并用 `kmem_alloc_contig` + `ml_vtophys` 自建 DMA 缓冲。

### 3.2 wired（不可分页）描述符的 `prepare()` 永不返回

`IOBufferMemoryDescriptor` 走 `kIOMemoryAutoPrepare → prepare() → wireVirtual()` 时挂死。
**处理**：不使用 wired 描述符，改用可分页路径 + 自己管理物理地址。

### 3.3 早期连续页分配不可靠 / `mach_absolute_time()` 不前进

- `kmem_alloc_contig` 在驱动启动阶段约有一半概率卡死在 `vfc-locked`；
  **解决**：把连续页分配提前到 `STARTUP (EARLY_BOOT, STARTUP_RANK_FIRST, ...)` 阶段做一次，之后复用。
- 早期 `mach_absolute_time()` 不前进，所有**基于 deadline 的等待都会挂死**；
  **解决**：UFS 等待改成忙等 + 计数上限，不用时间。

### 3.4 `IOSleep()` 在本平台永不返回（重要）

这不是"睡得久"，而是**永远醒不过来**。凡是 `IOSleep` 参与的等待都会变成永久挂起，
而且因为它是忙等实现，还会饿死其它线程。
**处理**：等待逻辑一律改成「忙等 + `thread_yield_to_preemption()` 让出 CPU」，
必要时主动调用 `IOService::startDeferredMatches()` 推动 IOKit 匹配。
（本仓库 v45 镜像就是靠这条才把"卡住不动"变成"能报超时错误"。）

### 3.5 预链接 kext 的符号绑定漏了 slide（也解释了"元类被涂鸦"）

`emit_prelink.py` 把 IOStorageFamily 放在 `原始 kernelcache VA + slide`（本板 `-0x1000000`），
但 `build-liuqin-ufs-bindings.py` 早期版本按**原始 VA** 写绝对符号。
结果 `new NativeUfsBlock` 会跳到 16 MiB 之外的零填充区，执行 `UDF #0`（未定义指令）——
构造函数根本没跑，块设备发布自然无法开始。
同一个 stale 值也是历史上"元类 `superClassLink` 被涂鸦成 ASCII 字符"的真正原因。
**处理**：绑定生成时套用 board 的 slide（`scripts/build-liuqin-ufs-bindings.py`）。

### 3.6 device-tree 父节点无法发布服务

`IOService::registerService()` 在服务于 `gIOServicePlane` 中找不到通往 registry root 的路径时，
会**静默返回**（连日志都不打）：

```c
while (parent && (parent != root))
	parent = parent->getParentEntry(gIOServicePlane);
if (parent != root) { IOLog("... not registry member ..."); return; }
```

而本驱动是挂在**设备树节点**（`xiaomi,liuqin`）上的，该节点在 service plane 里没有父节点，
于是窗口设备从未真正注册（`state=0x0`），存储家族驱动自然看不到它。
**处理**：发布前把窗口 attach 到 **platform expert（`ArmDTPlatform`）**，链路可达 root，
之后能看到 `REGPUBLISH ok`。

---

## 四、当前卡点与已知问题

**卡点**：`NativeUfsBlock::start()` 成功、`registerService()` 也真正发布了（`REGPUBLISH ok`），
但之后 **没有 `IOBlockStorageDriver` 认领该设备**，因此没有 `IOMedia`，
媒体等待超时 → `UFS ROOT FAILURE: SystemOS window media not found`。

**已排除**的假设（省得后来者重查）：

| 假设 | 结论 |
|------|------|
| 元类链断裂（历史 H16） | ❌ 已排除，`metaCast("IOBlockStorageDevice")` 正常 |
| 服务没注册 | ❌ 已修（改挂 platform expert） |
| `startRoot` 被调用两次 | ❌ 已排除，`PUBSTATE entries=1` |
| 发布太早、IOKit 匹配未就绪 | ❌ 已排除（加了延迟门仍无 IOMedia） |
| `IOService::getMatchingServices()` 计数为 0 | ⚠️ 该方法在此阶段不可信，不能作为证据 |

**下一步优先级**：

1. 用**注册表迭代器**（`IORegistryIterator`）遍历 platform expert 下的服务，确认到底有没有
   `IOBlockStorageDriver` / `IOMedia`；**注意把结果拼进 panic 文本**，因为面板普通输出行会丢失；
2. 若没有驱动 → 查 IOStorageFamily 的 personality 是否注册、匹配是否真的在跑；
3. 若有驱动无媒体 → 查驱动的 start 路径，以及 **`bsd_init` 之后 UFS 读是否仍可靠**
   （UFS 写在 `bsd_init` 缓冲缓存初始化之后会挂死，读共用同一套传输槽位，这是真实风险）。

---

## 五、设备分区改造（`unixnu`）说明

> ⚠️ **这是本仓库唯一动过分区的部分，且不可"一键回滚"。做之前必须完整备份。**
> 本人（@Fly116）的设备已经改造完成；如果你只是来复现内核部分，**不需要**做这一步。

原因：Android 的 `/data` 位于 f2fs + metadata 加密（dm-default-key）之上，
XNU 的裸读拿不到明文，所以 iOS 根镜像必须放在一块**内核能裸读写**的独立分区里。
而 128 GB 设备原本排满，于是做了：

1. 完整备份 GPT（主/备两份，CRC 校验）与 `/sdcard`；
2. 改写 **primary GPT**：`userdata` 105.79 GiB → **94 GiB**，尾部新增 **`unixnu`** 11.79 GiB；
3. `fastboot erase userdata metadata` → Android 重新格式化为 94 GiB（**应用数据会清空，文件已备份**）；
4. 用 `unixnu userdata` 从 iPad7,1 17.7.11 (21H461) IPSW 构建 9,382,658,048 B 的根镜像；
5. sparse 化后写入 `unixnu`；
6. 内核用 `native-ufs-root-partition=unixnu` 启动。

**保数据缩容（原地缩 f2fs）试过两版，都不可行**：Android 13 的 `/data` 有大量 bind mount，
卸载时触发 `reboot,vold-failed` 保护，已放弃。

相关工具与文档：

- `scripts/install-liuqin-ufs-data.py`（镜像切分/写入，含 `--partition-offset`、自检）
- `docs/userdata-carve-plan.md`、`docs/userdata-build-plan.md`
- `docs/bringup-2026-11-19-session.md`（那一轮的全部结论）

---

## 六、快速开始（测试已有镜像）

> 只做 `fastboot boot`（加载进内存），**不要** `fastboot flash`。
> 前提：设备已完成 §5 的分区改造，否则会在解析根布局处停止。

```bash
adb reboot bootloader
fastboot boot boot-v41-unixnu.img          # 或 Releases 中最新的实验镜像
```

观察面板里程碑（U/B/K 开头的编号行）。预期会看到：

```
U86:root-bringup-ok → U87:root-layout-ok
U88:root-manifest-ok → U89:root-plan-ok → U90:root-iostart-ok
...
U139:probe-nub → U140:start-enter → U141:start-root
U142:blk-registered → U143:blk-matched → U146:root-pub-SystemOS
U147:root-media-timeout        ← 当前卡在这里
```

排障：`docs/` 下有本轮全部调试记录；`docs/bringup-2026-11-19-session.md` 是最新的一份。

---

## 七、从零构建

需要：Linux x86_64、Python 3、约 60 GB 磁盘、能下载 IPSW。

```bash
# 1) 代码
git clone https://github.com/Fly116/UniXNU-liuqin      # 设备仓库（含 board.toml / patches / drivers）
git clone https://github.com/Fly116/UniXNU-new         # 构建驱动（unixnu CLI）
git clone https://github.com/UniXNU/Mu-Silicium        # UEFI（仓库内称 uefi-liuqin）

# 2) 工具链（装到 /opt/unixnu-linux）
python3 UniXNU-new/scripts/linux/setup-toolchain.py

# 3) 从官方线刷包抽厂商 UEFI 模块（需要 V14.0.9.0 之类的线刷包）

# 4) 准备 IPSW（iPad7,1 17.7.11 / 21H461）
#    放到 F:\\liuqin_ios\\_dl\\ 或任意路径，用 --ipsw 指定

# 5) 构建
python3 UniXNU-new/unixnu build kernel  -D device-new
python3 UniXNU-new/unixnu build payload --kernel out/liuqin/kernel/kernel.macho \
        --unique-chip-id 0x84750A0B0C0D0001 -D device-new
python3 device-new/scripts/wrap-payload-mbr.py out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
python3 UniXNU-new/unixnu bootimg --uefi uefi-liuqin --fd .../SILICIUM_UEFI.fd \
        --dtb .../liuqin.dtb --ramdisk out/liuqin/payload/payload-mbr.img -D device-new
```

### 构建的三个大坑（必读）

1. **`patches/xnu/*.patch` 不会自动应用**。构建脚本只编译 `.cache/xnu-work` 里已有的源码，
   补丁需要**手动** `patch -p1 <` 到 `out/liuqin/tree/.cache/xnu-work/` 再构建。
   漏应用或在错误顺序下应用，会出现 `start.s: patch does not apply` 或
   `Native kernel lacks sparse-prelink index ABI` 之类的报错。
2. **`XNU_SHENG_PMGR` 默认 0**，`sheng_pmgr_run()` 根本不会被编译进去
   （`board.toml` 里 `sheng-pmgr=2` 只是 boot arg 门禁，不代表代码在）。
3. 环境变量至少要设：`UNIXNU_PATCH_LIST=manual`、
   `XNU_OWNER_ROOT_VOLUME_UUID=18AB5557-DC2D-469B-8758-855E60F5B0DF`。

---

## 八、实机调试方法论（血泪经验）

本平台的调试手段有限，**用错通道会得出错误结论**（我们在这上面浪费了很久）：

| 通道 | 可靠性 | 说明 |
|------|--------|------|
| 面板里程碑 `liuqin_milestone(tag,msg)` | 🟡 内容可信、**顺序不可信** | 直接写 framebuffer，最早可用；但缓冲区会覆盖/回绕，照片里会出现编号倒序 |
| 持久日志扇区（`unixnu` LBA 2400000） | 🟡 **仅早期可用** | `bsd_init` 缓冲缓存初始化之后 UFS 写会挂死，日志探针会反过来阻塞被测路径 |
| `IOLog` / `printf` | 🔴 基本不可见 | 该阶段控制台未接到面板 |
| **panic 文本块** | 🟢 最可靠 | 完整显示在最显眼位置，适合放关键状态汇总（如 `PUBSTATE ...`） |
| `IOService::getMatchingServices()` | 🔴 不可信 | 该阶段对已有实例也返回 0 |

**结论**：要判断"走到哪一步"，用里程碑；要判断"状态是什么"，把状态塞进 panic 文本。

---

## 九、给 AI / 新手的继续开发指南

### 9.1 代码地图（按重要性排序）

| 路径 | 作用 |
|------|------|
| `drivers/ShengUfs/NativeUfs.cpp` | **主战场**：UFS 主机控制器、`startRoot`、块设备类 `NativeUfsBlock`、发布流程、绝大多数里程碑与诊断 |
| `drivers/ShengUfs/RootCommands.h` | 传输层：SCSI 命令、PRD、槽位池、store/log 写窗口（`hostWrite4k` 是唯一写入口） |
| `drivers/ShengUfs/RootLayout.h` | GPT 解析 + SHNGROOT 清单解析（含 `native-ufs-root-partition` / `-offset`） |
| `drivers/ShengUfs/RootPublication.h` | prepare → validate → schedule → start/wait 的发布状态机 |
| `drivers/ShengUfs/RootWindowRead.h` | 窗口读（bounce buffer、校验、并发） |
| `scripts/build-liuqin-ufs-bindings.py` | **prelink 符号绑定**生成（§3.5 的战场，改动风险高） |
| `package/ShengPlatformPower.cpp` | 平台电源 nub（默认不参与编译） |
| `board.toml` | 板级描述 + 内核启动参数（改行为优先从这里下手） |
| `scripts/install-liuqin-ufs-data.py` | 镜像切分/写入工具 |

### 9.2 按顺序推进的建议

1. **先解决 IOMedia 不出现**（§4）。不要跳到 APFS 或用户态，没有 `/dev/diskNsM` 什么都做不了。
2. 拿到 IOMedia 之后，先验证**读**是否可靠：用 `doAsyncReadWrite` 读第 0 块并校验签名。
   （UFS 写在 `bsd_init` 后会挂死，读共用同一套槽位，必须实测。）
3. 再做 APFS 根卷挂载（T1）。
4. 最后才是用户态。

### 9.3 一定要避开的坑

- **不要用 `IOSleep`**，也不要用任何基于 deadline 的等待（§3.4）。
- **不要在 `bsd_init` 之后写 UFS**（日志探针也不行），会挂死。
- **不要相信面板的行序**，也不要相信 `getMatchingServices` 的计数（§8）。
- **不要改 `board.toml` 里的 `sheng-pmgr`**：`native-ufs-root=1` 的 payload 门禁要求恰好一个
  `sheng-pmgr=2`，改了会直接构建失败（"AMFI otherwise panics with No PMGR"）。
- **不要打开 `liuqin_usb=1`**：USB CDC 调试口初始化会挂在 `bsd_init:usb_start`。
- **不要用 `fastboot flash`** 测试实验镜像；一律 `fastboot boot`。
- 改驱动后如出现"行为完全没变化"，先确认改动真的进了 **tree 副本**
  （`out/liuqin/tree/drivers/ShengUfs/...`），并用
  `strings kernel.macho | grep <你的记号>` 验证。

### 9.4 验证清单（每轮改动的自检）

```bash
# 1) 构建成功且 kernel sha 变化
tail -1 out/liuqin/kernel/../liuqin/logs/../  # 见构建日志最后一行
# 2) 关键记号进了内核
strings out/liuqin/kernel/kernel.macho | grep -c "<新增的里程碑文本>"
# 3) 镜像回读校验通过（bootimg 会自己做 head/hash 检查）
# 4) 真机：fastboot boot → 面板读数 → 回 Android 读日志/看 panic
```

---

## 十、路线图与可行性

- **T1 根卷挂载**：只差 IOMedia → BSD disk → APFS 挂载。这是当前唯一真正的工作面。
- **T2 用户态**：`launchd` 需要可写 `/private/var`（内存盘或数据窗口）。
- **图形界面**：受 GPU 限制，**不建议作为目标**（见顶部警告）。

同 SoC 参考实现：[Emilelu/UniXNU-mondrian](https://github.com/Emilelu/UniXNU-mondrian)（红米 K60 / SM8475）。

---

## 十一、仓库结构

```
docs/                        本轮及历次调试记录（含 bringup-2026-11-19-session.md）
patches/
  driver/                    NativeUfs 早期元类修复补丁
  xnu/                       XNU 侧补丁（**需手动应用**，见 §7）
  bringup-2026-11-18/        11-18 轮改动
  bringup-2026-11-19/        11-19 轮改动（含最终驱动 diff：shengufs-v50-publish.diff / v52）
drivers/ShengUfs/            UFS 驱动（子模块 / fork）
scripts/
  build-liuqin-ufs-bindings.py   prelink 符号绑定生成
  install-liuqin-ufs-data.py     iOS 根镜像切分/写入
  wrap-payload-mbr.py            payload 打包
tests/metaclass-simtest/     元类场景主机仿真
board.toml                   板级描述与内核启动参数
```

构建产物不入库，走 Releases（每个镜像约 66 MB）。

---

## 十二、致谢

- 上游主线：[hhyygg2009/UniXNU-liuqin](https://github.com/hhyygg2009/UniXNU-liuqin)
- 同 SoC 参考：Emilelu/UniXNU-mondrian（SM8475）
- 前人记录：[1696108518/UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin)、
  [document97/UniXNU-liuqin](https://github.com/document97/UniXNU-liuqin)
- UEFI 层：UniXNU / Mu-Silicium
- 设备与实机验证：**@Fly116**
- **DeepSeek**：本仓库 2026-11-19 之后的存储链路定位（prelink slide、`IOSleep`、
  `registerService` 链路）与大量调试脚本、文档整理，由 DeepSeek 模型驱动完成
- UniXNU 官方与各社区机型仓

---


## 十三、声明

- 本项目与 Apple、小米、高通均无关联；
- 所有实验均可能使设备无法启动，**请自行承担风险**，并提前完整备份；
- 仓库内历史性的分区改造步骤**不可一键回滚**，请勿在主力设备上照做；
- 代码与文档按现状提供。
