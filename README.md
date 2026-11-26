# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

在高通骁龙 8+ Gen 1（SM8475）的小米平板 6 Pro 上把 XNU（Darwin / iPadOS 内核）跑起来的移植仓库。

> ## ⚠️ 项目暂停中（大约于2026年12月底至2027年1月初恢复）；当前仍不能进入 iPadOS 界面
>
> **2026-11-25 状态：UFS 存储链、三卷 APFS、用户态 init 全部打通；launchd 的 dyld 启动被
> `fcntl(F_ADDFILESIGS)` 返回 85 (EBADEXEC) 拒绝——根因已定位到具体的数据块（见 §一/§四）。**
>
> 已验证链路：固件 → DarwinBoot → XNU → UFS 传输（`transport ready LUN=0 block=4096 blocks=30491648`）
> → GPT / SHNGROOT 清单 → **OS / SystemOS / Data 三卷 APFS 挂载** → **用户态 `/pong/init` 执行**
> → `execve(/sbin/launchd.ios)` 成功（PID 1 进入用户态）→ 触摸驱动 ready
> （`liuqin touch: ready: novatek_nt36532_m81_fw_csot.bin`）。
>
> **当前唯一阻塞**：dyld 加载共享缓存时 `check_signature fid:11: error = 85` → 共享缓存不加载 →
> libSystem 找不到 → launchd 退出。2026-11-24 已定位到 **dyld 主缓存（557,056 B）block 32
> （off 0x80000，code 区最后 16 KiB）**：内核实际算出的内容在 11 GB 镜像中 0 次命中，
> Apple 原版块 32 head 为 `lib/libchannel.d`、尾部全 0；生成链复制环节已排除（见 §四）。
> **下一轮第一件事：`fastboot boot boot-ai4-reread.img` 拍 `PONG native4K: reread` 行**（见 §十二）。
>
> **停摆归档**：完整交接见 [docs/status-2026-11-25.md](docs/status-2026-11-25.md)；
> 网盘资源见 [§十二.8](#十二后来人如何接手详细)。
>
> 设备保持 **Android 13 / MIUI 14 V14.0.3.0.TMYCNXM**；HyperOS 2/3 的引导实验已证明与当前
> BootShim/EDK2 链不兼容（UEFI 早期 `ArmCpuDxe` abort），不作为测试路线。

---

## 一、一句话现状

**已从"UFS 命令无法完成"推进到"三卷 APFS 挂载 + 用户态 launchd.ios 进程运行，卡在 dyld 共享缓存签名注册"。**

```text
启动链 → XNU → UFS 传输 → GPT/SHNGROOT → APFS 三卷挂载 → 用户态 init → launchd(dyld) → SpringBoard
  ✅      ✅        ✅            ✅              ✅              ✅          ⏳(85)          ⛔
```

证据等级：上述每一步均有 v134–v149 与 2026-11-24 诊断链（ah/ai/ai3/ai4）实机日志；
dyld 失败的**块级定位已完成**，剩最后一步"读取路径 vs 数据源"的判别（见 §四）。

## 二、里程碑总览

| # | 里程碑 | 状态 | 证据 / 说明 |
|---|--------|------|-------------|
| 0 | 构建链（固件 / prelink / payload / boot.img） | ✅ | 本地固件重建 + macOS CI 内核 + 本地组镜像；参见 [docs/ufs-bringup-2026-11-23.md](docs/ufs-bringup-2026-11-23.md) |
| 1 | 固件启动 → UniXNU 菜单 → payload 卷 | ✅ 实机 | 同源固件（document97/uefi-liuqin + 锁定 EDK2） |
| 2 | 菜单默认项修复（无输入设备时不轮换高亮） | ✅ 实机 | [docs/menu-default-entry.md](docs/menu-default-entry.md) |
| 3 | DarwinBoot → XNU → `VM bootstrap done` | ✅ 实机 | v112 起；prelink slide 修复见 [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) |
| 4 | IOKit / ArmDTPlatform / UFS nub / ArmCpu / APFS kext | ✅ 实机 | `apfs_module_start`、`ArmCpu: CPU 0 first boot completed` |
| 5 | Framebuffer 输出（1800×2880 / 7200 B/行） | ✅ 实机 | 软件绘制（非 GPU） |
| 6 | AppleARMCPU DT 校验绕过 | ✅ | `_validateConfiguration` → `mov w0,#1; ret` |
| 7 | **UFS 传输（query/wake/NOP/TUR/capacity）** | ✅ v134 起 | 之后所有版本均 `transport ready LUN=0 block=4096` |
| 8 | GPT / SHNGROOT 清单解析 | ✅ v135 | `SHNGROOT manifest ok windows=3`，OS/SystemOS 磁盘发布 |
| 9 | **APFS 三卷挂载（OS / SystemOS / Data）** | ✅ v136–v137 | OS 根挂载、SystemOS 挂载、Data `rw=1`（`/private/var`） |
| 10 | **用户态 init（`/pong/init`）执行** | ✅ v136 起 | `userland adapter / 18.7.10 22H374 / static arm64` |
| 11 | 触摸（NT36532） | ✅ v137 | 固件 245,760 B、16 分区、`ready: polling every 8 ms` |
| 12 | **launchd 的 dyld 共享缓存注册** | ⏳ **当前卡点** | `check_signature fid:11: error = 85`；块级定位见 §四 |
| 13 | launchd 服务栈 / backboardd / 软件 UI | ⛔ 未开始 | 等 dyld 通过 |
| 14 | 图形界面 / SpringBoard | ⛔ 未开始 | 软件 UI 路线优先（`libpong-ui`），GPU 后置（计划移植 zizhan 同 SM8475 的 PongAdreno） |

不提供没有测量依据的完成百分比；以实机里程碑为准。

## 三、两条技术栈（务必分清）

| | 旧栈：ShengUfs 路线（已暂停） | 当前主线：pong 栈（format 2） |
|---|---|---|
| 设备仓库 | `Fly116/UniXNU-liuqin`（sheng 派生） | `document97/UniXNU-liuqin@fe0e8d7`（上游最新） |
| iOS | iPadOS 17.7.11 / 21H461 | iPadOS 18.7.10 / 22H374（Darwin 24.6.0） |
| 存储驱动 | ShengUfs（历史路线） | NativeUfs + CI 变体（q–z、V–ac、ad–ai） |
| 构建 | Linux | GitHub Actions `macos-15-intel` |
| 状态 | 暂停（保留文档与补丁） | **主线** |

两条路线都需区分「固件链路接管」与「PHY 冷启动」；本轮 PHY 冷初始化是否真正成功仍未证明——
成功路径可能包含对固件现成链路的接管。

## 四、最近的关键进展

### 4.1 2026-11-24：85 根因锁定（本仓库最重要的一次定位）

| 版本 | 内容 | 结果 |
|---|---|---|
| ah（run 45351017816） | V..ac 全量 + native4K 5 点诊断（prepare / vn_rdwr / no-expected-hash / bad-hash / ready） | **首次命中**：`prepare base=0 limit=540672 hashsize=32` + `bad hash off=524288` |
| ai（run 45358303832） | 全块地图（33 块逐个 exp/got） | **`bad=1 good=32`**：只有 block 32 坏 |
| ai3（run 45366559692） | 坏块尾部 96 B dump（tail0/1/2） | 已构建，镜像在 Release |
| ai4（run 45372443297） | 坏块**单块重读**（同偏移小 I/O） | 已构建，**未实测——下一轮第一件事** |

**结论链**（完整版见 [docs/status-2026-11-25.md](docs/status-2026-11-25.md)）：

1. dyld 主缓存（`dyld_shared_cache_arm64`，557,056 B，codeLimit 540,672 = 33×16 KiB）**只有 block 32
   （文件偏移 0x80000–0x84000，code 区最后一块）哈希不匹配**；
2. 该块**内核算出的内容在 11 GB 镜像中 0 次命中**（镜像并未被改成"内核读到的那段数据"）；
3. **Apple 原版对照**（GitHub Actions 解密 IPSW 提取，cache-compare workflow）：
   原版主缓存 sha256 = `e901979f7f1c51ce31a9e7a68d218aa394bc7134aba2f474e9ae6daa50e1e4fc`，
   **原版 block 32 head = `6c69622f6c696263…`（ascii "lib/libchannel.d"），尾部 96 字节全 0**；
4. **生成链复制环节排除**：`ditto --rsrc --extattr --acl --nopreserveHFSCompression --nohfsCompression --noclone`
   复制原版到新 APFS 后 **sha256 与原版完全相同（IDENTICAL）**；
5. **最强假说**：UFS 驱动/APFS 对"最后不满 64 KiB 的 16 KiB I/O"处理有 bug → 块 32 数据未等待完成、
   buffer 保留内核内存旧内容（540,672 = 8×64 KiB + 16 KiB，坏块正好是最后 16 KiB）。

> **判别方法**：`boot-ai4-reread.img` 的 `PONG native4K: reread off=524288 err=… resid=… exp=… got=… data=…`：
> - `got == exp`（重读正确）→ 大 I/O 尾块丢失实锤 → 修 UFS 完成处理或把 native4k 读改小；
> - `reread data == 块读 data`（仍错）→ 16 KiB I/O 本身有问题；
> - 两者不同 → 数据不稳定（缓存/竞争）。

### 4.2 2026-11-23：UFS/APFS/用户态打通

| 版本 | 内容 | 结果 |
|---|---|---|
| v134 / V | GCC CBCR 位语义修正（bit0=ENABLE、bit31=CLK_OFF）、GDSC SW_COLLAPSE=bit0、v6 PHY reset、volatile 描述符 | **首次 `transport ready LUN=0 block=4096`**，GPT/userdata 可读 |
| v135 / W | liuqin GPT 几何校验改为动态 + SHNGROOT 诊断 | SHNGROOT 清单通过，OS/SystemOS 磁盘发布 |
| v136 / X | Data 窗口接受裸 APFS（`NXSB@32`）+ 坏窗口跳过不 panic | **用户态 `/pong/init` 运行** |
| v137 / Y | 恢复 `pong_ufs_readwrite` 写路径 + CI 注入 NT36532 固件 | **Data `rw=1`**、触摸 ready |
| v141 / Z | SystemOS union 配置（union=1 要求 CRYPTEX_FILES=0）+ init 诊断 | union 挂载成功 |
| v143 | 发现运行时参数真正来源是 payload `unixnu.toml` | 参数生效 |
| v144 | cryptex 内核 + 真实参数 | 缓存 probe `error=0` |
| v145 | union 内核 + 离线修补适配层 env | union 挂载成功 |
| v146 | 新根镜像（UUID 配对）+ 新布局内核 | 卷配对正确、Data 干净 |
| v147 | aa 变体（只含 init 路径改动，丢 UFS 修复） | **教训镜像**：UFS 读失败 → Failed to mount root device |
| v148 | ab：V..Z 全量 + 直接 launchd.ios + DYLD_PRINT_ERRORS | **打印出 dyld 真错**：`check_signature … error = 85` |
| v149 | ac：V..ac 全量 + CS errno 打印 | 85 稳定复现（基线） |

关键机制（已在文档中详述）：

- **运行时 boot args 来自 payload FAT 的 `EFI/UniXNU/unixnu.toml`**，不是 `board.toml`/ADT。
- UFS 电源：PHY `ldob5`(880 mV)/`ldoc10`(1200 mV)，设备 `ldob7`(2504 mV)/`ldob9`(1200 mV)，
  GDSC 父供电 CX 电平轨，全部通过 AOP cmd-db 投票。
- 传输使用固件 UTRL 页（device-mapped、16 KiB、volatile 描述符）。
- 触摸固件由 CI 私有仓库 `ci/firmware/` 注入（`LIUQIN_TOUCH_FW_DIR`），不进入公开仓库。
- cryptex 模式内核把 SystemOS 挂到 `/private/preboot` 并设置 `DYLD_SHARED_CACHE_DIR`；
  union 模式挂到 `/`（`MNT_UNION`）且不设置该 env——镜像/适配层与内核模式必须严格配对。
- **pong 树的 miniAMFI 无条件放行签名**（`miniamfi_vnode_check_signature`），85 与 AMFI/CS 参数无关
  （`cs_enforcement_disable=1`、`amfi_get_out_of_my_way=1` 早已在 args）。
- **变体补丁文件名必须是 `0001-*.patch`**：CI 的 workflow 只应用四位数字前缀的 patch；
  字母名（如 `ad-native4k-diag.patch`）会被**静默跳过** → 纯上游内核 → UFS 挂根失败（v147/ad/ag0 的教训）。

历史突破（2026-11-21/22）：prelink slide 修复、上游最新源码重编、AppleARMCPU 校验绕过、菜单默认项修复。
详见 §十 文档索引。

## 五、构建与验证

> 💾 **本节用到的脚本、补丁、payload、固件链与根镜像，网盘里都有现成备份**（见 §12.8）：
> `variant-tree-2026-11-25.tar.gz`（含全部脚本与 .git 历史）、`payloads-patches-2026-11-25.tar.gz`、
> `userdata-*.simg`、`boot-image(位于boot文件夹中，包含了所有生成过的的boot文件)`。不想从零搭环境时，先从网盘解包，再按 5.2/5.3 组装即可。

### 5.1 CI（GitHub Actions，仓库 `Fly116/liuqin-ipados18-ci`）

| 工作流 | 用途 |
|---|---|
| `kernel-upstream.yml` | **当前主线**：从 `document97/UniXNU-liuqin@fe0e8d7` 重编内核，`slide=auto`；`patch_dir` 选择变体补丁；含 ccache、触摸固件注入、SystemOS union 配置步骤 |
| `kernel.yml` | 旧主线（QPRS-6@38ca105d），已改正确 slide |
| `userdata.yml` | 从 22H374 IPSW 重建 userdata 根镜像（SHNGROOT：OS/SystemOS/Data 三窗口；QPRS_REF=38ca105d） |
| `metal.yml` | pong Metal（GPU）配套产物，当前 bring-up 未使用 |
| `cache-compare.yml` | **一次性诊断**（2026-11-24 新增）：解密 IPSW 原版 SystemOS，对比 ditto 复制是否改文件（结论：无损） |

```bash
# 触发（示例：变体 ai = 全块地图 + 重读诊断）
gh workflow run kernel-upstream.yml -R Fly116/liuqin-ipados18-ci \
  -f device_ref=fe0e8d790e24120970083e20c1a7d9c86cdbb87c \
  -f unique_chip_id=84750a0b -f prelink=true \
  -f patch_dir=ci/patches-variants/ai

# 取内核产物（直连，无需代理）
bash docs/ufs-bringup-scripts/ci_fetch_kernel_direct.sh <run-id> kernel-upstream-encrypted
```

### 5.2 本地：组装可引导镜像

```bash
# 经典脚本（菜单修复固件 + 原厂 Cape DTB）
bash docs/make-v112.sh <run-id> boot.img [kernel.macho]

# 可覆盖版本（FD / UEFI 树 / payload / DTB 均可换）
PAYLOAD_OVERRIDE=/path/payload.img \
FD_OVERRIDE=/path/SILICIUM_UEFI.fd \
UEFI_OVERRIDE=/path/uefi-liuqin-d97/repo \
CAPE_OVERRIDE=/path/liuqin.dtb \
bash docs/ufs-bringup-scripts/make_image_override.sh <run-id> boot.img kernel.macho
```

AppleARMCPU 校验补丁（固定 VA `0xfffffff00b80dad4`，文件偏移随构建变化）：

```bash
python3 docs/patch-armcpu-validate.py kernel.macho kernel-patched.macho
```

### 5.3 上机

```bash
adb reboot bootloader                      # 或关机后按住 音量减+电源
fastboot boot boot-ai4-reread.img           # 只在内存启动；重启即回 Android
```

## 六、已验证镜像（本轮）

| 版本 | 内容 | boot.img sha256 |
|---|---|---|
| v134 | V：存储链首次打通（重编译版） | `bec6810fb3fadeb3512482ec395dadd8ccc33931962853e79739dbe43bac7bbf` |
| v135 | W：SHNGROOT 清单 + 磁盘发布 | `d1b0a8a66e1d…`（完整校验见 Release SHA256SUMS） |
| v136 | X：用户态 init 首次运行 | `0db87f79caef…` |
| v137 | Y + 触摸固件：Data `rw=1`、触摸 ready | `6a200fbd4bf3…` |
| v141 | Z：union 挂载实验 | `c1c49152516f…` |
| v143 | payload 真参数生效（直接 launchd 被拒） | `5871befc8c6e…` |
| v144 | cryptex 内核 + 真参数（dyld `F:arr`） | `3a78ac04a8c8…` |
| v145 | union 内核 + 补丁 env（dyld `F:open`） | `2141dd597b6b…` |
| v146 | 新镜像 + 新布局内核 | `boot-v146-fresh.img` |
| v147 | aa 教训镜像 | `a68651ea7ece…` |
| v148 | ab：直接 launchd + DYLD_PRINT_ERRORS | `914cae5d2153…` |
| v149 | ac：85 基线 | `fe5570c37544…` |
| ah | native4K 5 点诊断（首次命中坏块） | `ab9a3af08ad0…` |
| ai | 33 块全块地图（`bad=1 good=32`） | `df5554959510…` |
| ai3 | 全块地图 + 尾部 96 B dump | `b2ef39532005…` |
| ai4 | 全块地图 + 尾部 + **单块重读（未实测）** | `8ded4de43d29…` |

完整校验和见各 Release（`SHA256SUMS-*.txt`）。

## 七、下载与使用（Release 现成文件）

| Release | 内容 |
|---|---|
| **`v149-2026-11-25`**（最新） <https://github.com/Fly116/UniXNU-liuqin/releases/tag/v149-2026-11-25> | v146–v149 + ah/ai/ai3/ai4 共 8 个 boot 镜像 + `SHA256SUMS-v149.txt`（含 Apple 原版 dyld 主缓存 sha256 `e901979f…`） |
| `v145-2026-11-23` <https://github.com/Fly116/UniXNU-liuqin/releases/tag/v145-2026-11-23> | v134–v145 共 12 个镜像、9 个内核、固件 FD、`unixnu.toml`、SHNGROOT/布局文件、校验和 |

> 32 GiB 的 `userdata.simg` 超过 GitHub 单文件 2 GiB 限制，未随 Release 上传；
> **2026-11-25 起已在网盘提供**（见 §十二.8），或用 `userdata.yml` 重建（见 §5.1）。

## 八、下一步路线（按优先级）

1. **判别并修复 85 的最后一跳**：boot `boot-ai4-reread.img` → 按 §4.1 的判据读 `reread` 行：
   - 若重读正确：把 `cs_native4k_prepare` 的读改为小 I/O（如逐 64 KiB/16 KiB），
     或修 NativeUfs 的完成处理（`drivers/ShengUfs/NativeUfs.cpp`）；再 boot 验证 85 消失；
   - 若重读仍错：查 16 KiB I/O 路径与 APFS 聚合，必要时对比 QPRS-6 的读实现。
2. 85 通过后：launchd 服务栈 → backboardd/CoreAnimation → 软件 UI（`libpong-ui`）→ SpringBoard。
3. USB CDC 实时日志（document97 的修复都在 fe0e8d79 树里；`pong_usb=1` 下不枚举的具体环节未查）。
4. 触摸输入在用户态验证；GPU/Metal 后置（移植 zizhan 的 PongAdreno + GMU）。
5. 镜像重建若需要：`userdata.yml`（QPRS_REF=38ca105d）→ 11 GB artifact；改镜像必须重建内核（UUID 配对）。

## 九、硬性规则（本仓库历史教训）

- **除已授权的 A2 方案（userdata 写入）外，不写任何 Android 分区**；所有实验默认 `fastboot boot`。
- 任何永久性/破坏性操作前先备份（`/sdcard` 与 GPT 均有备份件）。
- 上游仓库（`document97/*`、`QPRS-6/*`、`Project-Silicium/*` 等）只读，不改上游；
  本地修改只在构建沙箱或 `ci/patches*/` 中维护。
- 厂商固件（触摸等）只存于私有 CI 仓库，不进入公开仓库。
- 设备保持 Android 13；不要升级到 HyperOS 2/3（已证明引导链不兼容）。
- 结论区分「已验证」与「推测」，都附实机证据（屏上日志 / 诊断 / 寄存器）。
- **变体补丁必须 `0001-*.patch` 命名**，否则 CI 静默不应用（§4.2）。
- token / artifact 密码绝不入库、不打印、不上传。

## 十、文档索引

**最新（2026-11-25）**

- [docs/status-2026-11-25.md](docs/status-2026-11-25.md) —— **停摆交接（必读）**：85 根因链、实验矩阵、下一步
- [docs/scripts-2026-11-25/](docs/scripts-2026-11-25/) —— 诊断/构建脚本（含 cache-compare workflow）
- [docs/ufs-bringup-2026-11-23.md](docs/ufs-bringup-2026-11-23.md) —— v134–v145 完整记录
- [docs/ufs-bringup-scripts/](docs/ufs-bringup-scripts/) —— 本轮可复用脚本
- [docs/v134-ufs-readback-2026-11-23.md](docs/v134-ufs-readback-2026-11-23.md) —— v134 实机读取报告
- [docs/upstream-storage-sync-2026-11-23.md](docs/upstream-storage-sync-2026-11-23.md) —— 上游存储进度核对
- [docs/v134-build-review-2026-11-23.md](docs/v134-build-review-2026-11-23.md) —— V 构建/校验记录
- [docs/patches/v134-variant-v.patch](docs/patches/v134-variant-v.patch) —— V 完整补丁

**历史主线（2026-11-21/22）**

- [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) —— slide / DTB / ADT 容器排除
- [docs/v112-upstream-kernel-2026-11-21.md](docs/v112-upstream-kernel-2026-11-21.md) —— 上游源码重编内核
- [docs/v114-root-device-ufs-2026-11-22.md](docs/v114-root-device-ufs-2026-11-22.md) —— 到 root device；AppleARMCPU 补丁
- [docs/ufs-tur-analysis-2026-11-22.md](docs/ufs-tur-analysis-2026-11-22.md) —— 历史 UFS TUR 诊断（寄存器解释已修正）
- [docs/a2-partition-runbook.md](docs/a2-partition-runbook.md) —— A2 分区手册
- [docs/menu-default-entry.md](docs/menu-default-entry.md) —— 菜单默认项修复

**历史档案**

- [docs/liuqin-on-pong-stack.md](docs/liuqin-on-pong-stack.md)、[docs/route-b-qprs6.md](docs/route-b-qprs6.md)、
  [docs/route-yz-bootchain-log.md](docs/route-yz-bootchain-log.md)
- [docs/bringup-2026-11-19-session.md](docs/bringup-2026-11-19-session.md)、
  [docs/bringup-2026-11-19-v57-regwalk.md](docs/bringup-2026-11-19-v57-regwalk.md)
- [docs/b1-unixnu-partition-plan.md](docs/b1-unixnu-partition-plan.md)、
  [docs/userdata-build-plan.md](docs/userdata-build-plan.md)、[docs/userdata-carve-plan.md](docs/userdata-carve-plan.md)

**可复现脚本**

| 脚本 | 用途 |
|---|---|
| [docs/ci-fetch-kernel.sh](docs/ci-fetch-kernel.sh) | 下载/解密 CI 内核产物（旧版，走代理） |
| [docs/ufs-bringup-scripts/ci_fetch_kernel_direct.sh](docs/ufs-bringup-scripts/ci_fetch_kernel_direct.sh) | 直连下载/解密（无代理环境） |
| [docs/ufs-bringup-scripts/push_variant.py](docs/ufs-bringup-scripts/push_variant.py) | 推送变体补丁并触发 CI（**文件名必须 0001- 开头**） |
| [docs/ufs-bringup-scripts/make_image_override.sh](docs/ufs-bringup-scripts/make_image_override.sh) | 可覆盖 FD/UEFI/payload/DTB 的组镜像脚本 |
| [docs/scripts-2026-11-25/make_variant_ai.py](docs/scripts-2026-11-25/make_variant_ai.py) | 累积树 → native4K 诊断补丁（fullhash 版） |
| [docs/scripts-2026-11-25/verify_dyld_cache.py](docs/scripts-2026-11-25/verify_dyld_cache.py) | 镜像内 dyld 缓存块校验（磁盘级，压缩文件不可靠） |
| [docs/scripts-2026-11-25/ci-cache-compare.yml](docs/scripts-2026-11-25/ci-cache-compare.yml) | runner 侧原版 vs ditto 复制对照 workflow |
| [docs/make-v112.sh](docs/make-v112.sh) | 官方 finalize 组装可引导镜像（经典版） |
| [docs/make-boot-v4.py](docs/make-boot-v4.py) | 通用 Android boot v4 打包 |
| [docs/make-boot-native-kernel.py](docs/make-boot-native-kernel.py) | 换内核进 payload 的打包脚本 |
| [docs/build-firmware-from-upstream.sh](docs/build-firmware-from-upstream.sh) | 上游源码 + 锁定 EDK2 重编固件 |
| [docs/wrap-pongfat.py](docs/wrap-pongfat.py) | PONGFAT1 包装器 |
| [docs/patch-menu-no-rotate.patch](docs/patch-menu-no-rotate.patch) | 菜单默认项修复补丁 |

## 十一、免责声明

本项目仅用于在自有设备上进行操作系统移植研究，与 Apple、小米、高通均无关。
源码资料同步不包含 token、artifact 密码、IPSW、密钥或新的系统二进制（Release 资产为本地构建产物）。
历史 prelinked 内核/镜像可能包含从 Apple IPSW 提取的组件，不能笼统称为“完全不含 Apple 内容”；
使用、构建及分发前须自行核对适用许可和权利。
请自行承担在真机上实验的一切风险。

## 十二、后来人如何接手（详细）

### 12.1 五分钟了解项目
- 目标：liuqin（SM8475）跑 iPadOS 18.7.10（22H374）。当前 85/EBADEXEC 是唯一阻塞（§四）。
- 两条仓库：**本仓**（文档+脚本+Release）+ **`Fly116/liuqin-ipados18-ci`**（CI 工作流与变体补丁）。
- 必读顺序：[docs/status-2026-11-25.md](docs/status-2026-11-25.md) → 本 README §四/§五 → [docs/ufs-bringup-2026-11-23.md](docs/ufs-bringup-2026-11-23.md)。

### 12.2 环境准备
- **Windows + WSL2（Ubuntu）**：`/root/work` 是构建沙箱（变体树、payload、内核产物）。
- **网络**：GitHub API 直连可用；大文件（IPSW/artifact）可走代理
  `http://172.21.64.1:7897`（WSL 视角）或 `127.0.0.1:7897`（Windows 侧）。
- **凭据**（在 `_gh/`，**绝不外传**）：
  - `token.txt`：GitHub PAT（推送补丁、触发 CI、读 artifact）
  - `artifact_password.txt`：CI artifact 的 7z 密码（≥12 位）
- **工具**：`D:\PhoneTools\tool\fastboot.exe`（或 adb）；fastboot 设备 serial `a0b7e323`。

### 12.3 每轮实验 SOP（照做即可）
1. 改内核/驱动：在累积树 `/root/work/v134-variant-v` 上修改（**不要**在干净上游树生成补丁；
   v147/ad/ag0 三次挂根事故都是因为补丁丢了累积）。
2. 生成累积补丁：
   ```bash
   cd /root/work/v134-variant-v && git add -A && git diff --cached > /root/work/<letter>.patch
   ```
3. 推送并触发 CI（**文件名必须 `0001-` 开头**）：
   ```bash
   python3 docs/scripts-2026-11-25/push_variant.py <letter> /root/work/<letter>.patch \
       0001-<letter>-<desc>.patch "<说明>"
   ```
4. 等 15–20 分钟。抓内核：
   ```bash
   bash docs/ufs-bringup-scripts/ci_fetch_kernel_direct.sh <run-id> kernel-upstream-encrypted
   ```
5. 打 AppleARMCPU 补丁：
   ```bash
   python3 docs/patch-armcpu-validate.py /root/work/ci-kernel-<run-id>/products/products/kernel/kernel.macho
   ```
6. 组镜像（用当前 payload 与固件覆盖）：
   ```bash
   PAYLOAD_OVERRIDE=/root/work/payload-v147.img \
   FD_OVERRIDE=/root/work/uefi-liuqin-d97/repo/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
   UEFI_OVERRIDE=/root/work/uefi-liuqin-d97/repo \
   CAPE_OVERRIDE=/root/work/uefi-liuqin/Resources/DTBs/liuqin.dtb \
   bash docs/ufs-bringup-scripts/make_image_override.sh <run-id> /mnt/f/liuqin_ios/boot-<letter>.img
   ```
7. 设备进 fastboot（音量减+电源），**只 boot 不 flash**：
   ```bash
   fastboot boot F:\liuqin_ios\boot-<letter>.img
   ```
   屏上日志拍照判读；panic 后 WDT 自动重启（长按电源 10 秒可回 Android）。

### 12.4 常见坑（都踩过）
| 现象 | 原因 | 处理 |
|---|---|---|
| UFS `probe TUR result=e00002d6` → `no media published` → `Failed to mount root device` | 变体补丁未被 CI 应用（字母名）或丢了累积 | 检查文件名 `0001-`；确认 patch 内容含 UFS 修复 |
| 85 复现但诊断打印缺失 | 诊断补丁在 series 里的顺序/基线不对 | 诊断 hunk 的旧文本必须锚在"zz 补丁之后"的形态 |
| `board.toml` 改了没效果 | 运行时参数真源是 payload FAT 的 `unixnu.toml` | 改 payload，不是 board.toml |
| 内核构建产物与上次差 8 MB | 变体补丁内容差异（修复版 vs 纯上游），不是"构建非确定" | 用 `git diff` 确认补丁内容 |
| 挂根但 85 一直复现 | 见 §四：块 32 与 Apple 原版不符 | 跑 ai4 重读判别 |
| IPSW/artifact 下载超时 | 大文件直连不稳 | 走代理 7897，或让有带宽的人代下 |

### 12.5 判别 85 的完整命令清单（下一轮第一步）
```bash
# 1. 确认设备在 fastboot
fastboot devices                       # 期望 a0b7e323 fastboot
# 2. 启动 ai4 镜像
fastboot boot F:\liuqin_ios\boot-ai4-reread.img
# 3. 拍屏：搜索 "PONG native4K:" 行，重点看
#    prepare ... / block 32 ... / tail0..2 / scan done bad=.. / reread ...
# 4. 按 §4.1 判据决定修 UFS 还是改读策略
```

### 12.6 若 85 通过后的路线
launchd 服务栈（backboardd、CoreAnimation、libpong-ui）→ SpringBoard 首帧 → 触摸输入联调 → GPU（后置）。
每一步的参考实现见 QPRS-6（SpringBoard 已跑通）与 zizhan（锁屏/蓝牙/GPU 已跑通）。

### 12.7 构建/镜像与配对规则
- 内核与镜像必须配套：**volume UUID、cryptex/union 模式、dyld 路径**三者一致；重建镜像必须重建内核。
- 根镜像重建：`userdata.yml`（QPRS_REF=38ca105d）→ 约 30–40 分钟 → 11 GB artifact（7z 加密）。
- 设备侧写 userdata 前必须确认（会清 Android 数据）；恢复 Android：
  ```bash
  fastboot flash userdata H:\liuqin_images_V14.0.3.0.TMYCNXM_13.0\images\userdata.img
  fastboot reboot
  ```

### 12.8 网盘资源（GitHub 装不下的大文件）
> 百度网盘：<https://pan.baidu.com/s/1V1Gv6C-8MRO38GmQN9lOoQ?pwd=13r6>  提取码：**13r6**

| 文件 | 大小 | sha256 |
|---|---|---|
| `userdata-dyldprint.simg`（设备当前镜像，复现 85 用） | 11.3 GB | `c303ab307d52d5355a17f6a250939e3e5907aecd2b7bd57f0923d0d71e9bccf7` |
| `userdata-new.simg`（CI 原版根镜像） | 11.3 GB | `887e16bf26e1339ed2760e08f11729b2e3b59b37e533a121d04471cc7fcb3874` |
| `userdata-union-patched.simg`（union 实验） | 11.3 GB | `2194ad3f091f07d8fdccf8ed1b28cce5e2585dc346ce7534b9a278bb4b807869` |
| `variant-tree-2026-11-25.tar.gz`（累积树含 .git 历史，951 文件） | 4.6 MB | 见网盘同目录 |
| `payloads-patches-2026-11-25.tar.gz`（ac/ai 补丁 + payload） | 17.6 MB | 见网盘同目录 |
| `boot-images.tar.gz`（全部 boot 镜像，可选） | ~10 GB | 见网盘同目录 |

使用示例：把 `userdata-dyldprint.simg` 写入设备（**会清 Android 数据，先确认**）：
```bash
fastboot flash userdata F:\liuqin_ios\_dl\ci\img\userdata-dyldprint.simg
fastboot reboot
```
或直接解包对比（它 = CI 原版 + `/pong/init` 的 env 字符串 patch）。

### 12.9 排错速查（panic 对照）
| 屏上信息 | 含义 | 处理 |
|---|---|---|
| `transport ready LUN=0 block=4096` | UFS 传输成功 | 正常 |
| `probe TUR result=e00002d6` + `no media published` | 变体补丁缺失/纯上游内核 | 见 §12.4 |
| `rootvnode is not set` 刷屏 → `Failed to mount root device @IOKitBSDInit.cpp:996` | 根卷没挂上（UFS 读失败） | 同上 |
| `check_signature fid:11: error = 85` → `dyld cache not loaded` → `pid 1 exited` | 85（当前阻塞） | §四 |
| `PONG native4K: bad hash off=…` | 诊断输出（块级定位） | 看 off 与 exp/got |
| `Nested panic detected … pe_init.c:757` | pid 1 死后的次生 panic | 不单独处理 |

### 12.10 联系与接手
- 仓库所有者：Fly116（GitHub）邮箱：forrest.wong@foxmail.com。
- 本仓 Issue 可直接提问；接手前请先读 [docs/status-2026-11-25.md](docs/status-2026-11-25.md) 全文。
- 若你改进后要回馈：提 PR 到本仓（文档/脚本）或 CI 仓（工作流/变体），保持"上游只读"原则。

## 十三、致谢

本项目的每一步都建立在众多开源项目与移植者的工作之上。按贡献类型列出（如有遗漏，欢迎补充）：

**上游与同设备仓库**
- **hhyygg2009**（`hhyygg2009/UniXNU-liuqin`）—— **Sheng 栈的 liuqin 移植主栈；UFX/ShengUfs 驱动、AMFI execve 墙的结案分析、`amfi_get_out_of_my_way` 思路、大量实机日志与文档；本仓库主要构建于此仓库**
- **UniXNU**（[unixnu.com](https://unixnu.com/zh/porting/)）—— 内核构建工具链、设备仓库规范、4K/16K 签名机制文档（`native-4k-signature-hash-cache`），是整条路线的基础。
- **document97**（`document97/UniXNU-liuqin`）—— pong 栈的 liuqin 移植（本仓库当前主线的设备源）；NativeUfs/ShengUfs、UFS TUR/SMMU 诊断、USB CDC 修复、trust cache 脚本，以及 11-17/11-18 的 UFS 突破。
- **QPRS-6**（`QPRS-6/iPadOS18-liuqin`）—— 同设备同系统（22H374）**已跑到 SpringBoard** 的参考实现；PongPlatform24 组件、trustcache 进 payload 的配方、dyld 缓存与 systemos 重建的踩坑记录。
- **qiumochen**（`qiumochen/UniXNU-zizhan`）—— 小米 MIX Fold 2（同 SM8475）的完整移植；`launchd_unsecure_cache`、`/chosen zizhan-boot-args`（XNU patch 0035）、GPU/蓝牙/输入参考。
- **Chengdong-Yu**（`UniXNU-pong`）—— SM8475 pong 基线（PongPlatform24、NativeUfs 等组件的源头）。
- **Kalospacer**（`Kalospacer/liuqin-ipados18-ci`）—— 本仓库 CI 流水线的上游（macOS runner 内核/用户态构建）。
- **Y3d4**（`Y3d4/UniXNU-pong-clean`、`Y3d4/UniXNU-pong-build`）—— pong 保留树与带符号产物参考。
- **Emilelu、xtom、1696、doc97、young121、qprs6** 等 SM8475 社区移植者—— 设备树/配置/启动参数参考。
- **Redmi K60（mondrian）移植项目**—— `amfi_get_out_of_my_way=1` 三道门机制的实测注释（本仓库的 pong 树 miniAMFI 行为与其一致）。

**固件与工具**
- **Project-Silicium / Mu-Silicium**（`uefi-liuqin`）—— UEFI 固件基础（BootShim、EDK2、菜单）。
- **Apple 开源**（XNU、IOStorageFamily、libdispatch、AvailabilityVersions）—— 内核与用户态构建依赖。
- **Linux 内核**（ufs/phy/qcom 驱动）—— GCC/PHY/时钟位语义与 UFS 初始化序列的参考。
- **EDK2**、**DarwinBoot24** 社区—— 启动链。

**AI 协作**
- **DeepSeek**（本仓库的 AI 编程助手）—— 2026-11-23～25 的长程排查（UFS 诊断、85 块级定位、cache-compare、本文档）。
- **Claude**（QPRS-6/zizhan 仓库的 co-author）—— 其提交记录中的设计说明帮助理解了 trustcache/缓存重建的取舍。

**个人**
- **Fly116** —— 仓库维护者、设备（小米平板 6 Pro，serial a0b7e323）与全部实机实验的承担者。
- 所有在本 README/文档/Issue 中留下记录、照片与日志的参与者。
