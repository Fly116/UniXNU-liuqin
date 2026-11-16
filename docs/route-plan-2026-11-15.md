# liuqin 适配路线（Stage 6 存储/root 主线）— 2026-11-15，无机窗口期研究产出

## 0. TL;DR

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

## 1. 现状快照（对照官方 8 步）

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

## 2. 方案对比

### A. ShengUfs（官方，主选）
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

### B. PongUfs（mondrian，SM8475 实测同 SoC，备选+事实来源）
- 本地已有：UniXNU-mondrian/drivers/NativeUfs（11 文件）；dts/mondrian.dts 给出全套实测常量
  （hc/gcc 页 0x187000/smmu/stream-id 0xe0/context 78/spi 265）
- 代价：绑 PONG machine 配置 + iOS16 存储 ABI 推导脚本（bind/derive-ios16-storage-*.py）
  → 用于 21H461 要重做 ABI 推导；`pong_allow_unauthenticated_root=1` 语义在 17 上未验证
- 用法：**A 方案的每个寄存器改动都用 B 的实测值交叉验证**；A 受阻即切 B

### C. 过渡诊断（并行小工具，非产品路线）
- v32 已把「静默停 mountroot」变「可见 panic 文字」——拿到机器第一件事验证它
- QEMU native-user 线的 launchd SIGKILL（namespace 9 code 0x8）独立研究（不依赖硬件，
  属 exec-policy/签名问题，与 sheng 的 no-lc=1 线互通有无）

## 3. 硬件输入核对表（官方 /porting/ufs 的 9 项）

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

## 4. 无机窗口期作业清单（PC 闭环可验收）

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

## 4.5 M1 实机寄存器记录（v33e，2026-11-16 00:2x，IMG_6897-6900）

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

## 5. 上机后的最短验证链（八步证据流的后两步）

1. `fastboot boot` v33（H4 产物）→ 看 NativeUfs 里程碑：寄存器可读→GDSCR 过→adopt 列表→
   已知块读→root UUID 匹配→挂载（官方里程碑序：register→DMA→command→known-block read→
   root mount→persistence→performance，每步记 porting.toml）
2. userdata 刷入（阶段 4 计划内动作，`fastboot flash userdata`——**唯一允许写的数据分区**，
   persist/modemst/boot/vbmeta 仍禁）
3. v32→v33 两轮的 panic 文字/屏幕色带拍照归档

## 6. 风险表

| 风险 | 影响 | 缓解 |
|---|---|---|
| GccUfs 抄错/分支语义不同 | 时钟不开→控制器无应答 | adopt-first 设计本就少写时钟；对照 PongUfs 双源验证；驱动自带拒绝未测值 |
| liuqin ABL 不做 UFS init（adopt 失败） | 走不了 adopt 路径 | 退回全量 init（PongUfs 有完整序列可抄）；或固件开 UFSDxe |
| FVMAIN 99% 满 | UFSDxe 进不去 | H6 配平；或全量 init 不依赖固件 |
| iOS17 root 验证链（seal/trustcache/AKS） | 挂上 root 也起不了 launchd | 先保 root mount 里程碑；seal 问题与 mondrian「unauth root」思路做 AB 备胎 |
| 2GiB UFS 分支上限（K60 踩坑） | Data 窗口尺寸设计返工 | 镜像尺寸直接按 ≤2GiB 规划 Data；OS/SystemOS 只读无碍 |
| 卷 UUID 身份混淆 | 装错窗自检失败 | apfs.py 离线双哈希+安装脚本读回校验（照抄 mondrian 三重校验） |

## 7. 决策点（现在不用定，上机前定）

1. H4 编链若被 iOS17 存储 ABI 推导卡住 → 切 PongUfs+重推导(工作量↑) 还是等 sheng 组件更新(时间↑)？
2. adopt 失败 → 全量 init（代码多、风险高） vs 固件 UFSDxe（挤 FV）？
3. Data 放 userdata 窗口（liuqin 96GiB 已缩好） vs 照 K60 建独立 unixnu 分区（要改 GPT，动作大）？

——文档位置：UniXNU-liuqin/docs/route-plan-2026-11-15.md
