# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

在高通骁龙 8+ Gen 1（SM8475）的小米平板 6 Pro 上把 XNU（Darwin / iPadOS 内核）跑起来的不完整移植仓库。

> ## ⚠️ 当前仍不能进入 iPadOS 界面
>
> **2026-11-23 · v134 实机进度：UFS 已可读取，当前卡在根镜像布局适配。**
> 固件 → DarwinBoot → XNU → UFS query / wake / NOP / TUR / READ CAPACITY → GPT / userdata 首块读取，已通过。
> 最新日志：`transport ready LUN=0 block=4096 blocks=30491648`。
> 随后驱动因沿用 pong 的固定 userdata 边界，主动 panic：`Pong userdata geometry changed`。
>
> **尚未完成根介质发布、APFS 根挂载、用户态或 SpringBoard。** 不要为通过旧校验而重分区。
> v134 内核强制关闭存储写入；本轮仅使用 `fastboot boot`，未 flash、未改 GPT / userdata。
> 详见 [v134 实机报告](docs/v134-ufs-readback-2026-11-23.md) 与 [相关上游同步](docs/upstream-storage-sync-2026-11-23.md)。
>
> 屏上文字来自 framebuffer / CPU 软件绘制，不代表 Adreno GPU 或系统桌面已工作。
> 保持 Android 13 / MIUI 14 V14.0.3.0.TMYCNXM；HyperOS 2/3 的引导实验未通过，不作为当前测试路线。

---

## 一、一句话现状

**已从“UFS 命令无法完成”推进到“能读取 GPT 和 userdata，开始根布局适配”。**

```text
启动链 → XNU → UFS 读取 → GPT / userdata → 根镜像识别 → APFS 挂载 → 用户态 → SpringBoard
  ✅      ✅       ✅             ✅             当前卡点          未完成     未完成     未完成
```

证据等级：一次 v134 实机测试成功读取，不代表冷启动覆盖率、长期稳定性或写入持久性已验证。

## 二、里程碑总览

| # | 里程碑 | 状态 | 证据 / 说明 |
|---|--------|------|-------------|
| 0 | 构建链（固件 / prelink / payload / boot.img） | ✅ 已构建并校验；完整复现待补齐 | Linux 固件、macOS CI 内核；本地组装复用既有 base boot，[限制与校验](docs/v134-build-review-2026-11-23.md) |
| 1 | 固件启动 → UniXNU 菜单 → payload 卷 | ✅ 实机 | 同源固件（document97/uefi-liuqin + 锁定 EDK2） |
| 2 | 菜单默认项修复（无输入设备时不再轮换高亮） | ✅ 实机 | 见 [docs/menu-default-entry.md](docs/menu-default-entry.md) |
| 3 | DarwinBoot → XNU → `VM bootstrap done` | ✅ 实机 | v112 起通过；v106 及之前的崩溃根因见 [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) |
| 4 | IOKit 初始化、ArmDTPlatform、UFS nub、ArmCpu、APFS kext | ✅ 实机 | v114 日志：`apfs_module_start`、`ArmCpu: CPU 0 first boot completed` |
| 5 | Framebuffer 输出（1800×2880 / 7200 B/行） | ✅ 实机 | `MiniIOFramebuffer: Pong fixed refresh 120 Hz`（软件绘制，非 GPU） |
| 6 | AppleARMCPU 的 DT 校验 | ✅ 绕过 | 其要求 Apple 私有 CPU 属性；用二进制补丁 `_validateConfiguration` 返回 true |
| 7 | **UFS 读取传输** | ✅ v134 实机 | query / wake / NOP / TUR / capacity、GPT 和 userdata 首块读取通过；写入关闭 |
| 8 | 根镜像布局识别 | 🔧 当前卡点 | 先修 pong 固定边界校验，再确认 SHNGROOT / 文件根镜像；旧 A2 手册仅历史参考，不自动执行 |
| 9 | APFS 根卷挂载（T1 的前半） | ⛔ 未完成 | 等根布局适配与文件系统验证 |
| 10 | 用户态（pong init / launchd） | ⛔ 未开始 | 上游 pong 上已实现，liuqin 待调 |
| 11 | 图形界面 / SpringBoard | ⛔ 未开始 | 走软件 UI 路线（`libpong-ui`）；GPU 后置 |

不提供没有测量依据的完成百分比；以实机里程碑为准。

## 三、两条技术栈（务必分清）

| | 旧栈：ShengUfs 路线（已暂停） | 当前主线：pong 栈（format 2） |
|---|---|---|
| 设备仓库 | `Fly116/UniXNU-liuqin`（sheng 派生） | `document97/UniXNU-liuqin@fe0e8d7`（上游最新） |
| iOS | iPadOS 17.7.11 / 21H461 | iPadOS 18.7.10 / 22H374（Darwin 24.6.0） |
| 存储驱动 | ShengUfs（历史路线；读取/根路径证据与写入正确性需分别核实） | NativeUfs + CI 变体 V（当前 UFS 读取通过，根布局待适配） |
| 构建 | Linux | GitHub Actions `macos-15-intel` |
| 状态 | 暂停（保留文档与补丁） | **主线** |

ShengUfs 是有价值的实现对照，但本轮核对的 hhyygg 实测来自另一台同型号设备，不能等同本机/同固件；持久写入正确性不能仅凭 README 宣称。两条路线均需区分固件链路接管与 PHY 冷启动。

## 四、最近的关键突破

### 2026-11-23：v134 / V

- 修复 v133 描述符在 device 映射上偏移 +4 的 8 字节合并写；新产物反汇编确认为逐 32 位访问。
- 纠正 CBCR：bit0 是 ENABLE（应置1）、bit31 是 CLK_OFF；GDSC SW_COLLAPSE 是 bit0，不是 bit30。兼顾 HWCG / NoC FSM，避免误挡正常空闲时钟。
- 移除不合法的 SerDes scratch 写回测试，准备 SM8475 v6 PHY 初始化、外部 reset 与 HS-B 补项；**本次日志没有执行该完整冷启动分支，不能宣称冷启验证成功**。
- 实机已有 `transport ready LUN=0` 与 GPT/userdata 读取；终点为 pong 专属边界检查 panic。
- [CI 45114535819](https://github.com/Fly116/liuqin-ipados18-ci/actions/runs/45114535819)，[变体补丁](https://github.com/Fly116/liuqin-ipados18-ci/blob/4abc00d2dd8b0fc71b19807a180bc582bed1ad16/ci/patches-variants/v/0001-ufs-volatile-refclk.patch)。

### 2026-11-21 → 11-22 历史突破

1. **prelink slide 用错导致 VM bootstrap panic**
   CI 原来用 `--slide=-0x1000000`（21H461 的数字），把 kexts 放到内核 text 之下，与内核内建绑定基址
   `0xfffffff00b000000` 错位。改用上游 `slide = "auto"`（由 22H374 kernelcache 派生，实际为
   `0x5ed0000`）后该 panic 消失。详见 [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md)。
2. **上游最新源码重编**：`document97/UniXNU-liuqin@fe0e8d7`（2026-11-21 drop）比原先 pin 的
   QPRS-6 版本新，含 UFS/SMMU 修复与 PRNG/crypto 兜底补丁。CI 工作流见
   [docs/v112-upstream-kernel-2026-11-21.md](docs/v112-upstream-kernel-2026-11-21.md)。
3. **AppleARMCPU 的 DT 校验绕过**：`AppleARMCPU::_validateConfiguration()` 要求 Apple 私有
   `/cpus` 属性（`max_cpus`、`cpu-id`、`interrupts`、`function-ipi_*`），我们的非 Apple 设备树
   永远满足不了。二进制补丁把该函数入口改成 `mov w0,#1; ret` 后，内核越过该 panic。
   详见 [docs/v114-root-device-ufs-2026-11-22.md](docs/v114-root-device-ufs-2026-11-22.md)。
4. **菜单默认项**：无输入设备时菜单每 2 秒轮换高亮，看起来"默认停在 2: Restart"，实际超时会启动
   第 1 项。已改固件 `Menu.c` 去掉强制轮换，高亮固定在默认项。
5. **历史卡点（v134 已越过）**：NativeUfs TUR 无完成中断；旧调查中关于 CLK_OFF、UERDL 和 PHY 不响应的部分解释已被更正。

## 五、构建与验证

### 5.1 CI（GitHub Actions，仓库 `Fly116/liuqin-ipados18-ci`）

| 工作流 | 用途 |
|---|---|
| `kernel-upstream.yml` | **当前主线**：从 `document97/UniXNU-liuqin@fe0e8d7` 重编内核，`slide=auto`；`prelink=true/false` 可选；通过 `patch_dir` 选择补丁集；v134 使用 `ci/patches-variants/v` |
| `kernel.yml` | 旧主线（QPRS-6@38ca105d），已改成正确 slide `0x5ed0000` |
| `userdata.yml` | 生成 22H374 userdata 镜像（OS/SystemOS/Data 三窗口） |
| `metal.yml` | pong Metal（GPU）配套产物，当前 bring-up 未使用 |

触发与取产物：

```bash
# 触发（示例：prelink=true）
gh workflow run kernel-upstream.yml -R Fly116/liuqin-ipados18-ci \
  -f device_ref=fe0e8d790e24120970083e20c1a7d9c86cdbb87c \
  -f unique_chip_id=84750a0b -f prelink=true \
  -f patch_dir=ci/patches-variants/v

# 取内核产物（解密 + 解压）
bash docs/ci-fetch-kernel.sh <run-id> kernel-upstream-encrypted
```

### 5.2 本地：组装可引导镜像

```bash
# 官方 finalize（ADT/容器/PONGFAT1 ramdisk）+ 我们的菜单修复固件 + 原厂 Cape DTB
bash docs/make-v112.sh <run-id> boot.img [可选的内核 kernel.macho]

# 变体：
#  - 用 native 内核：<run-id> 来自 prelink=false 的构建
#  - 二进制补丁内核：先 patch，再作为第 3 个参数传入
```

补丁技巧（AppleARMCPU 校验）：

```bash
# 按 VA 定位并检查原始指令，不能复用旧构建的硬编码文件偏移
python3 docs/patch-armcpu-validate.py kernel.macho kernel-patched.macho
```

v134 固定 VA 为 `0xfffffff00b80dad4`，对应文件偏移为 `0x1942ad4`；不同构建文件偏移可能变化。

### 5.3 上机

```bash
adb reboot bootloader
fastboot boot boot-v134-ufs-v.img  # 仅在已取得并核对上述SHA256后使用；目前未上传v134 Release资产
```

## 六、已验证镜像

| 版本 | 内容 | sha256 |
|---|---|---|
| v106 | 旧 CI prelink（slide=-0x1000000）→ VM bootstrap panic | `5bc4f5d8…` |
| v107 | native 内核 → 越过 VM bootstrap，停在 `read_random` NULL 表 | — |
| v108 | 正确 slide `0x5ed0000` → 仍 VM bootstrap panic | — |
| v109 | + 原厂 Cape DTB → 同一 panic | — |
| v110 | 官方 finalize ADT/容器 → 同一 panic | `e96fb53b…` |
| v111 | 菜单修复固件 | `10ccca01…` |
| **v112** | 上游最新 prelinked 内核 → 撞 AppleARMCPU 校验 | `5f6d1bcc…` |
| v113 | 上游最新 native 内核 → 60 s 内崩（缺 kext 函数表） | `ac1a2428…` |
| **v114** | 历史基线：v112 + AppleARMCPU 校验补丁 → 到 root device 阶段 | `0213013f678733b8c059ef132bb55217c0ca29659eaeeea0858dd3b36352437b` |
| **v134 / V** | **UFS 读取通过；GPT/userdata 可读；停在 pong 固定边界校验** | `bec6810fb3fadeb3512482ec395dadd8ccc33931962853e79739dbe43bac7bbf` |

## 七、下载与使用（Release 现成文件）

**最新实测版本是 v134，但本次资料同步未上传 v134 二进制 Release 资产。**
内核来自上述 CI，镜像完整校验见 [v134 报告](docs/v134-ufs-readback-2026-11-23.md)。不要把下面的 v114 历史下载当成最新进度。

历史 v112–v114 产物在 **Release `v114-2026-11-22`**：
<https://github.com/Fly116/UniXNU-liuqin/releases/tag/v114-2026-11-22>

### 7.1 只想看内核能跑到哪：直接用现成镜像（推荐，零构建）

| 文件 | 说明 |
|---|---|
| `boot-v114.img` | **历史基线**（到 root device）。含：菜单修复固件 + 上游最新 prelinked 内核 + AppleARMCPU 校验补丁 + 官方 ADT/容器 + 原厂 Cape DTB |
| `boot-v112.img` | 同 v114 但没有 AppleARMCPU 补丁（会在 CPU 校验处 panic，用于对照） |
| `boot-v113.img` | 同源 native 内核（缺 kext 函数表，约 60 s 崩，用于对照） |

```bash
adb reboot bootloader
fastboot boot boot-v114.img     # 只进内存；重启即恢复 Android，不写任何分区
```

> 注意：v114 会停在 panic 画面，需要长按电源 10 秒重启。

### 7.2 想自己打包：内核与固件（Release 资产）

| 文件 | 大小 | sha256 |
|---|---|---|
| `kernel-prelinked-upstream.macho` | 51,982,336 B | `ba5aad5aebca365f3c717d9da83f1acdda224865fb4ef3a331d78f2d512ffc0b`（v112 用，未打 CPU 校验补丁） |
| `kernel-prelinked-upstream-armcpu-patch.macho` | 51,982,336 B | `157641daf9a0479b633d0bfc47f1046340d6dfac333fba594bc7839d15447039`（**v114 用**，已绕过 AppleARMCPU DT 校验） |
| `kernel-native-upstream.macho` | 18,038,896 B | `0be638156074cc8592d680788c63ce38f0457c0ddaebee41ac341fa56d7a45a4`（native，未 prelink） |
| `SILICIUM_UEFI-menu-patched.fd` | 3,145,728 B | `44485ef0ca1e61d714115957cab3e6d5b53746bffae1e1f05090a077d7ab47d5`（同源固件，含菜单默认项修复） |
| `SHA256SUMS-kernel-fd.txt` | 400 B | 以上四项的校验和 |

重新打包示例（复用仓库里的脚本）：

```bash
# 官方 finalize 组装：需要 document97/UniXNU-liuqin 的 scripts/ 与 dtc
bash docs/make-v112.sh <CI-run-id> my-boot.img kernel-prelinked-upstream-armcpu-patch.macho
```

### 7.3 各镜像实际启动结果

见 §六 表格。v114 的屏上日志终点：
`Still waiting for root device` → `panic: Failed to mount root device @IOKitBSDInit.cpp:996`

## 八、下一步路线

1. 修正 NativeUfs 的 pong 固定 userdata 边界检查：按本机实际 GPT / 设备描述进行有界验证，不能直接删安全检查，也不能重分区来迎合旧常量。
2. 只读确认 userdata 当前布局、SHNGROOT manifest 状态及 `pong_shngroot_4k` 文件根方案是否适用；不假定根镜像已经正确部署。
3. 根介质发布 → APFS 挂载 → init / launchd → 软件 UI → SpringBoard。
4. 保留 v134 已验证的读取接管路径、强制禁写和回退镜像。根布局修复版本尚未构建。

## 九、硬性规则（本仓库历史教训）

- **除已授权的 A2 方案外，不写任何 Android 分区**；所有实验默认 `fastboot boot`。
- 任何永久性/破坏性操作前先备份（`/sdcard` 与 GPT 均有备份件）。
- 上游仓库（`document97/*`、`QPRS-6/*`、`Project-Silicium/*` 等）只读，不改上游；
  所有本地修改只在构建沙箱或 `ci/patches/` 中维护。
- 结论区分「已验证」与「推测」，都附实机证据（屏上日志/诊断/寄存器）。

## 十、文档索引

**最新资料（2026-11-23）**

- [v134 UFS 实机读取与当前阻塞](docs/v134-ufs-readback-2026-11-23.md)
- [相关上游存储进度核对与可复用范围](docs/upstream-storage-sync-2026-11-23.md)
- [V 构建/校验记录](docs/v134-build-review-2026-11-23.md)
- [V 完整补丁副本](docs/patches/v134-variant-v.patch)

**历史主线（2026-11-21/22；结论以最新报告为准）**

| 文档 | 内容 |
|---|---|
| [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) | v106–v110 变量排除：slide / DTB / ADT 容器 |
| [docs/v112-upstream-kernel-2026-11-21.md](docs/v112-upstream-kernel-2026-11-21.md) | 用上游最新源码重编内核；CI 踩坑记录 |
| [docs/v114-root-device-ufs-2026-11-22.md](docs/v114-root-device-ufs-2026-11-22.md) | 到达 root device；AppleARMCPU 补丁 |
| [docs/ufs-tur-analysis-2026-11-22.md](docs/ufs-tur-analysis-2026-11-22.md) | 历史 UFS TUR 失败诊断（寄存器解释有纠正，见最新报告） |
| [docs/a2-partition-runbook.md](docs/a2-partition-runbook.md) | A2 分区执行手册（已校验 GPT） |
| [docs/menu-default-entry.md](docs/menu-default-entry.md) | 菜单默认项修复 |

**历史档案（旧栈 / 早期 bring-up）**

- [docs/liuqin-on-pong-stack.md](docs/liuqin-on-pong-stack.md)、[docs/route-b-qprs6.md](docs/route-b-qprs6.md)、[docs/route-yz-bootchain-log.md](docs/route-yz-bootchain-log.md)
- [docs/bringup-2026-11-19-session.md](docs/bringup-2026-11-19-session.md)、[docs/bringup-2026-11-19-v57-regwalk.md](docs/bringup-2026-11-19-v57-regwalk.md)
- [docs/b1-unixnu-partition-plan.md](docs/b1-unixnu-partition-plan.md)、[docs/userdata-build-plan.md](docs/userdata-build-plan.md)、[docs/userdata-carve-plan.md](docs/userdata-carve-plan.md)

**可复现脚本**

| 脚本 | 用途 |
|---|---|
| [docs/ci-fetch-kernel.sh](docs/ci-fetch-kernel.sh) | 下载/解密 CI 内核产物 |
| [docs/make-v112.sh](docs/make-v112.sh) | 官方 finalize 组装可引导镜像 |
| [docs/make-boot-v4.py](docs/make-boot-v4.py) | 通用 Android boot v4 打包 |
| [docs/make-boot-native-kernel.py](docs/make-boot-native-kernel.py) | 换内核进 payload 的打包脚本 |
| [docs/build-firmware-from-upstream.sh](docs/build-firmware-from-upstream.sh) | 用上游源码 + 锁定 EDK2 重编固件 |
| [docs/wrap-pongfat.py](docs/wrap-pongfat.py) | PONGFAT1 包装器 |
| [docs/patch-menu-no-rotate.patch](docs/patch-menu-no-rotate.patch) | 菜单默认项修复补丁 |

## 十一、免责声明

本项目仅用于在自有设备上进行操作系统移植研究，与 Apple、小米、高通均无关。
源码资料同步不包含 token、artifact 密码、IPSW、密钥或新的系统二进制。
历史 prelinked 内核/镜像可能包含从 Apple IPSW 提取的组件，不能笼统称为“完全不含 Apple 内容”；
使用、构建及分发前须自行核对适用许可和权利。本次仅同步源码补丁、工具、文档和日志照片，不新增二进制 Release 资产。
请自行承担在真机上实验的一切风险。


## 2026-11-23：UFS 存储链打通

- 记录文档：[docs/ufs-bringup-2026-11-23.md](docs/ufs-bringup-2026-11-23.md)
- 本轮从 v134 推进到 v145：UFS transport ready、GPT/SHNGROOT、OS/SystemOS/Data APFS 挂载、用户态 `/pong/init`、触摸 ready。
- 当前阻塞：launchd 的 dyld 启动失败（OS_REASON_DYLD）。
- 辅助脚本：[docs/ufs-bringup-scripts/](docs/ufs-bringup-scripts/)
