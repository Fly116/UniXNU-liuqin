# UniXNU for Xiaomi Pad 6 Pro（liuqin / SM8475）

在高通骁龙 8+ Gen 1（SM8475）的小米平板 6 Pro 上把 XNU（Darwin / iPadOS 内核）跑起来的不完整移植仓库。

> ## ⚠️ 当前仍不能进入 iPadOS 界面
>
> **2026-11-23 · v145 实机进度：UFS 存储链已打通，用户态 init 已运行，卡在 launchd 的 dyld 启动。**
>
> 已验证链路：固件 → DarwinBoot → XNU → UFS 传输（`transport ready LUN=0 block=4096 blocks=30491648`）
> → GPT / SHNGROOT 清单 → **OS / SystemOS / Data 三卷 APFS 挂载** → **用户态 `/pong/init` 执行**
> → 触摸驱动 ready（`liuqin touch: ready: novatek_nt36532_m81_fw_csot.bin`）。
>
> 当前阻塞：pid 1 退出 `exit reason namespace 6`（= **OS_REASON_DYLD**）。cryptex 模式报
> `F:arr=…`，union 模式报 `F:open`；已确认内核能打开 `/private/preboot/.../dyld_shared_cache_arm64`
> （`shared cache path probe error=0`），正在通过重建根镜像与配置配对继续排查。
>
> **仍未完成**：launchd / 系统服务 / backboardd / SpringBoard。屏上文字来自 framebuffer 与 CPU
> 软件绘制，不代表 Adreno GPU 或系统桌面已工作。
>
> 设备保持 **Android 13 / MIUI 14 V14.0.3.0.TMYCNXM**；HyperOS 2/3 的引导实验已证明与当前
> BootShim/EDK2 链不兼容（UEFI 早期 `ArmCpuDxe` abort），不作为测试路线。

---

## 一、一句话现状

**已从“UFS 命令无法完成”推进到“三卷 APFS 挂载 + 用户态 init 运行，卡在 dyld”。**

```text
启动链 → XNU → UFS 传输 → GPT/SHNGROOT → APFS 三卷挂载 → 用户态 init → launchd → SpringBoard
  ✅      ✅        ✅            ✅              ✅              ✅           ⏳         ⛔
```

证据等级：上述每一步均有 v134–v145 实机日志；dyld 失败原因尚未解码，根镜像重建仍在进行。

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
| 12 | **launchd（dyld）** | ⏳ **当前卡点** | `pid 1 exited -- exit reason namespace 6`（OS_REASON_DYLD） |
| 13 | launchd 服务栈 / backboardd / 软件 UI | ⛔ 未开始 | 等 dyld 通过 |
| 14 | 图形界面 / SpringBoard | ⛔ 未开始 | 软件 UI 路线优先（`libpong-ui`），GPU 后置（计划移植 zizhan 同 SM8475 的 PongAdreno） |

不提供没有测量依据的完成百分比；以实机里程碑为准。

## 三、两条技术栈（务必分清）

| | 旧栈：ShengUfs 路线（已暂停） | 当前主线：pong 栈（format 2） |
|---|---|---|
| 设备仓库 | `Fly116/UniXNU-liuqin`（sheng 派生） | `document97/UniXNU-liuqin@fe0e8d7`（上游最新） |
| iOS | iPadOS 17.7.11 / 21H461 | iPadOS 18.7.10 / 22H374（Darwin 24.6.0） |
| 存储驱动 | ShengUfs（历史路线） | NativeUfs + CI 变体（q–z） |
| 构建 | Linux | GitHub Actions `macos-15-intel` |
| 状态 | 暂停（保留文档与补丁） | **主线** |

两条路线都需区分「固件链路接管」与「PHY 冷启动」；本轮 PHY 冷初始化是否真正成功仍未证明——
成功路径可能包含对固件现成链路的接管。

## 四、最近的关键突破（2026-11-23）

| 版本 | 内容 | 结果 |
|---|---|---|
| v134 / V | GCC CBCR 位语义修正（bit0=ENABLE、bit31=CLK_OFF）、GDSC SW_COLLAPSE=bit0、v6 PHY reset、volatile 描述符 | **首次 `transport ready LUN=0 block=4096`**，GPT/userdata 可读；停在 pong 固定边界校验 |
| v135 / W | liuqin GPT 几何校验改为动态 + SHNGROOT 诊断 | SHNGROOT 清单通过，OS/SystemOS 磁盘发布；Data 窗口签名不识别 |
| v136 / X | Data 窗口接受裸 APFS（`NXSB@32`）+ 坏窗口跳过不 panic | **用户态 `/pong/init` 运行**；Data 只读 → init 退出 |
| v137 / Y | 恢复 `pong_ufs_readwrite` 写路径 + CI 注入 NT36532 固件 | **Data `rw=1`**、触摸 ready；dyld `F:arr` |
| v141 / Z | SystemOS union 配置（union=1 要求 CRYPTEX_FILES=0）+ init 诊断 | union 挂载成功；dyld `F:open` |
| v143 | 发现运行时参数真正来源是 payload `unixnu.toml` | 参数生效；`Unsupported Pong init path`（内核白名单） |
| v144 | cryptex 内核 + 真实参数 | 缓存 probe `error=0`；dyld `F:arr` |
| v145 | union 内核 + 离线修补适配层 env | union 挂载成功；Data APFS 对象校验错误；dyld `F:open` |

关键机制（已在文档中详述）：

- **运行时 boot args 来自 payload FAT 的 `EFI/UniXNU/unixnu.toml`**，不是 `board.toml`/ADT。
- UFS 电源：PHY `ldob5`(880 mV)/`ldoc10`(1200 mV)，设备 `ldob7`(2504 mV)/`ldob9`(1200 mV)，
  GDSC 父供电 CX 电平轨，全部通过 AOP cmd-db 投票。
- 传输使用固件 UTRL 页（device-mapped、16 KiB、volatile 描述符）。
- 触摸固件由 CI 私有仓库 `ci/firmware/` 注入（`LIUQIN_TOUCH_FW_DIR`），不进入公开仓库。
- cryptex 模式内核把 SystemOS 挂到 `/private/preboot` 并设置 `DYLD_SHARED_CACHE_DIR`；
  union 模式挂到 `/`（`MNT_UNION`）且不设置该 env——镜像/适配层与内核模式必须严格配对。

历史突破（2026-11-21/22）：prelink slide 修复、上游最新源码重编、AppleARMCPU 校验绕过、
菜单默认项修复。详见 §十 文档索引。

## 五、构建与验证

### 5.1 CI（GitHub Actions，仓库 `Fly116/liuqin-ipados18-ci`）

| 工作流 | 用途 |
|---|---|
| `kernel-upstream.yml` | **当前主线**：从 `document97/UniXNU-liuqin@fe0e8d7` 重编内核，`slide=auto`；`patch_dir` 选择变体补丁；含 ccache、触摸固件注入、SystemOS union 配置步骤 |
| `kernel.yml` | 旧主线（QPRS-6@38ca105d），已改正确 slide |
| `userdata.yml` | 从 22H374 IPSW 重建 userdata 根镜像（SHNGROOT：OS/SystemOS/Data 三窗口） |
| `metal.yml` | pong Metal（GPU）配套产物，当前 bring-up 未使用 |

```bash
# 触发（示例：变体 y = 恢复写路径）
gh workflow run kernel-upstream.yml -R Fly116/liuqin-ipados18-ci \
  -f device_ref=fe0e8d790e24120970083e20c1a7d9c86cdbb87c \
  -f unique_chip_id=84750a0b -f prelink=true \
  -f patch_dir=ci/patches-variants/y

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
fastboot boot boot-v145-union-env.img       # 只在内存启动；重启即回 Android
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

完整 12 个镜像、9 个内核、固件 FD 与校验和见 §七 Release 资产（`SHA256SUMS-v134-v145.txt`）。

## 七、下载与使用（Release 现成文件）

**最新 Release：`v145-2026-11-23`**
<https://github.com/Fly116/UniXNU-liuqin/releases/tag/v145-2026-11-23>

| 资产 | 说明 |
|---|---|
| `boot-v134-…` → `boot-v145-…`（12 个） | 本轮每个里程碑的 `fastboot boot` 镜像（69,009,408 B） |
| `kernel-v130-…` → `kernel-v141-…`（9 个） | 已打 AppleARMCPU 补丁的内核，可直接替换 payload 内 `kernel.macho` |
| `SILICIUM_UEFI-usb-ownership.fd` | 本地重编固件（含 DarwinBoot USB ownership + 菜单修正），sha `341fe1ad…` |
| `unixnu-v143.toml` / `unixnu-v144.toml` | payload FAT 内 `unixnu.toml`（真正生效的运行时 boot args） |
| `shngroot-ipados18.bin`、`ufs-layout.json`、`sparse-report.json`、`volume-layout.json` | SHNGROOT 清单与镜像布局 |
| `SHA256SUMS-v134-v145.txt` | 上述全部资产的校验和 |

> 32 GiB 的 `userdata.simg` 超过 GitHub 单文件 2 GiB 限制，未随 Release 上传；
> 用 `userdata.yml` 重建（见 §5.1）或按 [docs/ufs-bringup-2026-11-23.md](docs/ufs-bringup-2026-11-23.md) §4 流程。

```bash
fastboot boot boot-v145-union-env.img   # 需设备 userdata 已写入 SHNGROOT 根镜像
# 历史基线（不需要根镜像）：
fastboot boot boot-v114.img             # v112–v114 在 Release v114-2026-11-22
```

> 注意：v114 会停在 `Failed to mount root device` panic；v134–v145 会停在 dyld 退出 panic。
> 都需长按电源 10 秒重启。

## 八、下一步路线

1. **重建根镜像**（`userdata.yml`）→ 得到干净、完整的 SHNGROOT 镜像，排除镜像完整性与 Data 卷
   APFS 对象校验问题。
2. **内核模式与镜像配对**：cryptex 镜像 + cryptex 内核（v134–v137），或 union 镜像 + union 内核
   （v141/v145）；不再用“离线改镜像字符串”的临时办法。
3. **解码 dyld 失败**（`F:arr` / `F:open`）：核对 `dyld_shared_cache_arm64` 主缓存引用的 subcache
   列表与镜像内分片是否齐全；必要时给 dyld 加打印（`DYLD_PRINT_*`）。
4. dyld 通过后：launchd → 服务栈 → backboardd/CoreAnimation → 软件 UI → SpringBoard。
5. 触摸已 ready；输入事件链路需在用户态验证。
6. GPU（Metal）作为后置项：从 zizhan（同 SM8475）移植 PongAdreno（约 4800 行 + GMU 栈）。

## 九、硬性规则（本仓库历史教训）

- **除已授权的 A2 方案（userdata 写入）外，不写任何 Android 分区**；所有实验默认 `fastboot boot`。
- 任何永久性/破坏性操作前先备份（`/sdcard` 与 GPT 均有备份件）。
- 上游仓库（`document97/*`、`QPRS-6/*`、`Project-Silicium/*` 等）只读，不改上游；
  本地修改只在构建沙箱或 `ci/patches*/` 中维护。
- 厂商固件（触摸等）只存于私有 CI 仓库，不进入公开仓库。
- 设备保持 Android 13；不要升级到 HyperOS 2/3（已证明引导链不兼容）。
- 结论区分「已验证」与「推测」，都附实机证据（屏上日志 / 诊断 / 寄存器）。

## 十、文档索引

**最新（2026-11-23）**

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
| [docs/ufs-bringup-scripts/push_variant.py](docs/ufs-bringup-scripts/push_variant.py) | 推送变体补丁并触发 CI |
| [docs/ufs-bringup-scripts/make_image_override.sh](docs/ufs-bringup-scripts/make_image_override.sh) | 可覆盖 FD/UEFI/payload/DTB 的组镜像脚本 |
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


---

## 2026-11-25 停摆交接（项目暂停约一个月）

- 完整状态与 85 根因诊断链：[docs/status-2026-11-25.md](docs/status-2026-11-25.md)
- 诊断脚本：[docs/scripts-2026-11-25/](docs/scripts-2026-11-25/)
- 关键结论：dyld 主缓存 block 32（off 0x80000）内核算出的数据在镜像中不存在；原版对照（sha256 e901979f…）与 ditto 复制（完全无损）已排除生成链；当前假说 UFS 尾块小 I/O，判据是 `boot-ai4-reread.img` 的 reread 行（Release v149-2026-11-25）。
- 下一轮第一件事：`fastboot boot boot-ai4-reread.img` 拍 `PONG native4K: reread` 行。
