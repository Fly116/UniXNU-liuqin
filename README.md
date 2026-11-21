# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

在高通骁龙 8+ Gen 1（SM8475）的小米平板 6 Pro 上把 XNU（Darwin / iPadOS 内核）跑起来的不完整移植仓库。

> ## ⚠️ 先读这段：当前不能进 iOS 界面
>
> **2026-11-22 现状**：引导链已经完整打通到「等待根设备」——
> 固件 → UniXNU 菜单 → DarwinBoot → **prelinked XNU** → IOKit → APFS kext → CPU 调频 → framebuffer
> 全部起来，最后停在 `Still waiting for root device` / `panic: Failed to mount root device`。
>
> 唯一剩余阻塞：**NativeUfs 的 TUR 探测命令提交后拿不到完成中断**，UFS 媒体未发布。
> 详细诊断见 [docs/ufs-tur-analysis-2026-11-22.md](docs/ufs-tur-analysis-2026-11-22.md)。
>
> 图形界面还没开始，而且当前构建**没有启用 Adreno GPU 驱动**：屏幕上的文字是
> `MiniIOFramebuffer` + CPU 软件绘制（`pong_software_ui=1`），不是 GPU。
>
> 所有镜像都是**实验性 bring-up 镜像**，只用于 `fastboot boot`（纯内存启动）。
> 除用户在 2026-11-21 明确授权的 A2 分区方案（备份 + 重建 `userdata` + 新增 `unixnu`）外，
> 本仓库**不写任何 Android 分区**。

---

## 一、一句话现状

**从"块设备注册了但没有 IOMedia"推进到"内核跑完 IOKit 初始化、等待根设备"**：
外围变量（固件/ADT/CPU 数/窗口/参数/DTB/prelink slide/ADT 容器）已逐项实机排除，
剩余卡点收敛到 **UFS 传输层**一处。

## 二、里程碑总览

| # | 里程碑 | 状态 | 证据 / 说明 |
|---|--------|------|-------------|
| 0 | 可复现构建链（固件 / prelink / payload / boot.img） | ✅ | Linux 可编固件；内核/prelink 走 GitHub Actions（macOS） |
| 1 | 固件启动 → UniXNU 菜单 → payload 卷 | ✅ 实机 | 同源固件（document97/uefi-liuqin + 锁定 EDK2） |
| 2 | 菜单默认项修复（无输入设备时不再轮换高亮） | ✅ 实机 | 见 [docs/menu-default-entry.md](docs/menu-default-entry.md) |
| 3 | DarwinBoot → XNU → `VM bootstrap done` | ✅ 实机 | v112 起通过；v106 及之前的崩溃根因见 [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) |
| 4 | IOKit 初始化、ArmDTPlatform、UFS nub、ArmCpu、APFS kext | ✅ 实机 | v114 日志：`apfs_module_start`、`ArmCpu: CPU 0 first boot completed` |
| 5 | Framebuffer 输出（1800×2880 / 7200 B/行） | ✅ 实机 | `MiniIOFramebuffer: Pong fixed refresh 120 Hz`（软件绘制，非 GPU） |
| 6 | AppleARMCPU 的 DT 校验 | ✅ 绕过 | 其要求 Apple 私有 CPU 属性；用二进制补丁 `_validateConfiguration` 返回 true |
| 7 | **UFS 传输层（TUR 完成）** | ❌ **当前卡点** | TUR 提交后无完成中断：`ocs=0f`、`scsi=ffff`、`db=1` 未清、`polls=1589` |
| 8 | 根镜像写入（A2 + `userdata.simg`） | ⏸ 已备好 | GPT 双表校验、写镜像命令、回滚步骤见 [docs/a2-partition-runbook.md](docs/a2-partition-runbook.md) |
| 9 | APFS 根卷挂载（T1 的前半） | ⛔ 未完成 | 等 #7 |
| 10 | 用户态（pong init / launchd） | ⛔ 未开始 | 上游 pong 上已实现，liuqin 待调 |
| 11 | 图形界面 / SpringBoard | ⛔ 未开始 | 走软件 UI 路线（`libpong-ui`）；GPU 后置 |

粗略工作量估计（以"进系统界面"为目标）：**引导链 70%，UFS 传输 15%，根卷/用户态/UI 15%**。

## 三、两条技术栈（务必分清）

| | 旧栈：ShengUfs 路线（已暂停） | 当前主线：pong 栈（format 2） |
|---|---|---|
| 设备仓库 | `Fly116/UniXNU-liuqin`（sheng 派生） | `document97/UniXNU-liuqin@fe0e8d7`（上游最新） |
| iOS | iPadOS 17.7.11 / 21H461 | iPadOS 18.7.10 / 22H374（Darwin 24.6.0） |
| 存储驱动 | ShengUfs（我们维护；本机可读写 UFS，但 IOKit 同步匹配死锁） | NativeUfs（上游，当前 TUR 卡点） |
| 构建 | Linux | GitHub Actions `macos-15-intel` |
| 状态 | 暂停（保留文档与补丁） | **主线** |

旧栈的 UFS 实现（`drivers/ShengUfs`）在**同一台设备上能完成 UFS 命令**，是当前 UFS 问题最有价值的对照物。

## 四、最近的关键突破（2026-11-21 → 11-22）

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
5. **当前唯一卡点**：NativeUfs TUR 无完成中断（详见下一页文档）。

## 五、构建与验证

### 5.1 CI（GitHub Actions，仓库 `Fly116/liuqin-ipados18-ci`）

| 工作流 | 用途 |
|---|---|
| `kernel-upstream.yml` | **当前主线**：从 `document97/UniXNU-liuqin@fe0e8d7` 重编内核，`slide=auto`；`prelink=true/false` 可选；会把 `ci/patches/*.patch` 注入 device 树 |
| `kernel.yml` | 旧主线（QPRS-6@38ca105d），已改成正确 slide `0x5ed0000` |
| `userdata.yml` | 生成 22H374 userdata 镜像（OS/SystemOS/Data 三窗口） |
| `metal.yml` | pong Metal（GPU）配套产物，当前 bring-up 未使用 |

触发与取产物：

```bash
# 触发（示例：prelink=true）
gh workflow run kernel-upstream.yml -R Fly116/liuqin-ipados18-ci \
  -f device_ref=fe0e8d790e24120970083e20c1a7d9c86cdbb87c \
  -f unique_chip_id=84750a0b -f prelink=true

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

```python
d = bytearray(open("kernel.macho","rb").read())
fo = 0x18dd000 + (0xfffffff00b80dad4 - 0xfffffff00b7a8000)  # __PLK_TEXT_EXEC
d[fo:fo+8] = bytes.fromhex("20008052c0035fd6")              # mov w0,#1 ; ret
open("kernel-patched.macho","wb").write(d)
```

### 5.3 上机

```bash
adb reboot bootloader
fastboot boot boot-v114-nocpuvalidate.img     # 只进内存，不写分区
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
| **v114** | v112 + AppleARMCPU 校验补丁 → **到 root device 阶段** | `0213013f678733b8c059ef132bb55217c0ca29659eaeeea0858dd3b36352437b` |

## 七、下一步路线

1. **修 UFS 传输层**（当前唯一硬阻塞）：对照 `drivers/ShengUfs`（本机可完成 UFS 命令）与
   UEFI `UfsDxe` 的 UIC 初始化顺序，逐项排查队列启动/门铃/中断/cache 维护。
   分析文档：[docs/ufs-tur-analysis-2026-11-22.md](docs/ufs-tur-analysis-2026-11-22.md)。
2. **A2 分区 + 写根镜像**（UFS 通了之后再做）：[docs/a2-partition-runbook.md](docs/a2-partition-runbook.md)。
3. APFS 根卷挂载 → 用户态 init（pong `/pong/init`）→ 软件 UI → SpringBoard。

## 八、硬性规则（本仓库历史教训）

- **除已授权的 A2 方案外，不写任何 Android 分区**；所有实验默认 `fastboot boot`。
- 任何永久性/破坏性操作前先备份（`/sdcard` 与 GPT 均有备份件）。
- 上游仓库（`document97/*`、`QPRS-6/*`、`Project-Silicium/*` 等）只读，不改上游；
  所有本地修改只在构建沙箱或 `ci/patches/` 中维护。
- 结论区分「已验证」与「推测」，都附实机证据（屏上日志/诊断/寄存器）。

## 九、文档索引

**当前主线（2026-11-21/22）**

| 文档 | 内容 |
|---|---|
| [docs/prelink-slide-exclusion-2026-11-21.md](docs/prelink-slide-exclusion-2026-11-21.md) | v106–v110 变量排除：slide / DTB / ADT 容器 |
| [docs/v112-upstream-kernel-2026-11-21.md](docs/v112-upstream-kernel-2026-11-21.md) | 用上游最新源码重编内核；CI 踩坑记录 |
| [docs/v114-root-device-ufs-2026-11-22.md](docs/v114-root-device-ufs-2026-11-22.md) | 到达 root device；AppleARMCPU 补丁 |
| [docs/ufs-tur-analysis-2026-11-22.md](docs/ufs-tur-analysis-2026-11-22.md) | 当前 UFS TUR 失败的诊断与实验计划 |
| [docs/a2-partition-runbook.md](docs/a2-partition-runbook.md) | A2 分区执行手册（已校验 GPT） |
| [docs/menu-default-entry.md](docs/menu-default-entry.md) | 菜单默认项修复 |

**历史档案（旧栈 / 早期 bring-up）**

- [docs/liuqin-on-pong-stack.md](docs/liuqin-on-pong-stack.md)、[docs/route-b-qprs6.md](docs/route-b-qprs6.md)、[docs/route-yz-bootchain-log.md](docs/route-yz-bootchain-log.md)
- [docs/bringup-2026-11-19-session.md](docs/bringup-2026-11-19-session.md)、[docs/bringup-2026-11-19-v57-regwalk.md](docs/bringup-2026-11-19-v57-regwalk.md)
- [docs/b1-unixnu-partition-plan.md](docs/b1-unixnu-partition-plan.md)、[docs/userdata-build-plan.md](docs/userdata-build-plan.md)、[docs/userdata-carve-plan.md](docs/userdata-carve-plan.md)
- [docs/porting-plan.md](docs/porting-plan.md)、[docs/route-plan-2026-11-15.md](docs/route-plan-2026-11-15.md)、[docs/linux-bringup-tutorial.md](docs/linux-bringup-tutorial.md)
- [docs/v39-linux-bringup.md](docs/v39-linux-bringup.md)、[docs/v39-metaclass-repair.md](docs/v39-metaclass-repair.md)
- [docs/liuqin-hardware.md](docs/liuqin-hardware.md)、[docs/liuqin-usb-debug.md](docs/liuqin-usb-debug.md)、[docs/vendor-inputs.md](docs/vendor-inputs.md)、[docs/liuqin-boot-progress.md](docs/liuqin-boot-progress.md)

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

## 十、免责声明

本项目仅用于在自有设备上进行操作系统移植研究，与 Apple、小米、高通均无关。
仓库不包含任何 Apple 专有二进制（IPSW 内容、密钥等）；镜像产物只在本地生成、不上传。
请自行承担在真机上实验的一切风险。
