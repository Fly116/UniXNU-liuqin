# UFS 存储链打通记录（2026-11-23）

> 设备：Xiaomi Pad 6 Pro（liuqin，SM8475），Android 13 V14.0.3.0.TMYCNXM，bootloader 解锁。
> 目标：iPadOS 18.7.10（Darwin 24.6.0）从 `fastboot boot` 启动 → UFS 挂载 → 用户态 → SpringBoard。
> 本日范围：v134 → v145，以及配套 CI/镜像/日志工具。

## 0. 一句话结论

今天跨过了整条存储链：**UFS 传输（transport ready）→ GPT/SHNGROOT 清单 → OS/SystemOS/Data 三卷 APFS 挂载 → 用户态 `/pong/init` 执行 → 触摸驱动 ready**。
唯一硬阻塞是 **launchd 的 dyld 启动失败（OS_REASON_DYLD：cryptex 模式 `F:arr`，union 模式 `F:open`）**；另有 USB CDC 控制台未枚举、union 实验导致 Data 卷 APFS 对象校验错误（离线改镜像的副作用，已改为用 CI `userdata` workflow 重建镜像）。

## 1. 关键事实（已验证，均有实机日志）

### 1.1 UFS 电源与 PHY（v129–v134）
- UFS PHY 供电（liuqin 板级 DTB）：`vdda-phy` = **ldob5**（880 mV），`vdda-pll` = **ldoc10**（1200 mV）。
- UFS 设备供电：`vcc` = **ldob7**（2504 mV），`vccq` + `vddp-ref-clk` = **ldob9**（1200 mV）。
- PHY GDSC（`qcom,gdsc@187004`）的父供电 = **CX 电平轨 `cx.lvl`**；另有 `mx.lvl`、`xo.lvl`。
- RPMh 投票格式（抄 `PongUsbPhy.h`）：`qcom_cmd_db_find(cmd-db@0x80860000 副本)`；非电平轨 `vote(res+8, 7)` / `vote(res, mV)` / `vote(res+4, 1)`；电平轨用 `qcom_rpmh_level_index(res, 0xffffffff)` 取最高档；`xo.lvl` 投 3。
- 投票被 AOP 接受（ldob5 addr=00440180、ldoc10 addr=00042200、ldob7 addr=00042180、ldob9 addr=000421c0、lcx.lvl arc=7、lmx.lvl arc=5、xo.lvl addr=00030080=3）。
- GCC 位语义修正（变体 V 的关键）：**CBCR bit0 = ENABLE，bit31 = CLK_OFF（只读状态）**；之前把 bit31 当"要清的 CLK_OFF"、把 bit0 当状态，是 PHY 一直不工作的根因之一。GDSC 为 **bit31 = PWR_ON，bit0 = SW_COLLAPSE**。
- QMP PHY 按 v6 布局 + SW_RESET 后 READY；PHY 窗口 0x1d80000（v6）与 0x1d87000（v5）双窗口检测。

### 1.2 UFS 传输与根镜像（v134–v136）
- 传输已打通：`transport ready LUN=0 block=4096 blocks=30491648`；GPT 可读，SHNGROOT 清单可解析（3 个窗口）。
- 传输使用**固件 UTRL 页**（`0x50/0x54` 读取 UTRLBA，16 KiB 设备映射）+ **volatile 描述符**（否则编译器合并 32-bit 写入产生 +4 处 8 字节未对齐存储 → data abort）。
- 写路径需要 `pong_ufs_readwrite=1`；变体 V 曾把写路径硬编码关闭（read-only 诊断），导致 Data 卷只读、`/private/var` 建不起来、init 退出。
- 窗口签名：OS 窗口带 `EFI PART@512`（GPT 盘）；SystemOS/Data 在本次镜像里是**裸 APFS 容器（`NXSB@32`）**，变体 X 让 Data 也接受裸 APFS，并在无法识别的窗口上"跳过发布"而不是 panic。

### 1.3 APFS 与用户态（v135–v145）
- 日志证据：
  - `PONG APFS: UUID B07DF049… bound to OS UFS window /dev/disk2s1`
  - `PONG APFS: SystemOS mounted dev=… ro=1 union=0`、`SystemOS mount complete`
  - `PONG UFS: Data mount PRSS path=/private/var device=/dev/disk5s1 rw=1 bytes=8589934592`
  - `PONG APFS: launchd shared cache directory=/private/preboot/System/Library/Caches/com.apple.dyld/`
  - `Pong init: loading helper /pong/init` → `helper exec result=0` → `userland adapter / 18.7.10 22H374 / static arm64`
- 触摸：CI 注入厂商固件后 `liuqin touch: novatek_nt36532_m81_fw_csot.bin: 245760 bytes, 16 partitions … firmware running … ready: … polling every 8 ms`。

### 1.4 运行参数来源（重要发现，v142/v143）
**运行时 boot args 来自 payload FAT 内的 `EFI/UniXNU/unixnu.toml`**（菜单启动项 `args=`），不是 `board.toml`，也不是 ADT 的 boot-args。修改方式：`mcopy` 替换 payload.img 里的 unixnu.toml。此前所有 board.toml 的 kernel_args 修改对内核无效。

### 1.5 union 与 cryptex 两种 SystemOS 模式（v141/v143/v144/v145）
- **cryptex 模式**（`CONFIG_XNU_OWNER_CRYPTEX_FILES=1`, `UNION_SYSTEMOS=0`）：内核把 SystemOS 挂到 `/private/preboot`，并给 init 设置 `DYLD_SHARED_CACHE_DIR=/private/preboot/System/Library/Caches/com.apple.dyld/`；本镜像的 cryptex 链接与预编译 `/pong/init` 均按此路径设计。dyld 失败描述 `F:arr=ffffffffffffff:A:ID:IC:1`。
- **union 模式**（`UNION_SYSTEMOS=1`，构建要求 `CRYPTEX_FILES=0`）：内核把 SystemOS 以 `MNT_UNION` 挂到 `/`，**不再设置** `DYLD_SHARED_CACHE_DIR`；预编译适配层仍硬编码 `/private/preboot` → dyld `F:open`。
- 结论：当前镜像/适配层是为 cryptex 模式构建的；union 模式需要**用 union 配置重新构建根镜像**（或同步修改适配层），不能只靠离线字符串 patch（还会导致 Data APFS 对象校验错误）。

### 1.6 USB CDC 日志控制台
- 树内已自带：`drivers/PongUsb/PongUsbDevice.h`（DWC3 CDC-ACM 控制台）+ 主机脚本 `scripts/capture-pong-usb-console.py`；需要 boot arg `pong_usb=1`，并且 UEFI/DarwinBoot 需要提供 `/chosen/pong-usb-dma`（32 KiB reserved DMA）、`pong-usb-handoff`、`pong-usb-status`。
- 已把工作树里的 `UsbOwnership.h`（AddUsbSlots/QuiesceUsb）移植进本地 d97 固件树的 DarwinBoot.c/inf 并重编 FD（sha `341fe1ad…`）；`pong_usb=1` 已生效，但 PC 侧尚未出现 CDC 串口，需要继续查 PongUsb 早期日志。
- 注意：`fastboot boot` 的缓冲区限制约 96 MB；100 MB 的 TWRP 镜像无法 boot（`Bad Buffer Size`）。`twrp-boot-*.img` 实测启动后是 MIUI Recovery，不能用于读 pstore。

## 2. 本日变体时间线

| 版本 | 内核/补丁 | 镜像 sha | 结果 |
|---|---|---|---|
| v134 | 变体 V（GCC 位语义/GDSC/v6 PHY/volatile/SMMU） | — | **首次 transport ready**，读 GPT/userdata，板级 userdata 边界校验失败 |
| v135 | 变体 W（liuqin GPT 几何 + SHNGROOT 诊断） | `d1b0a8a6…` | OS/SystemOS 磁盘发布，Data 窗口签名不识别 panic |
| v136 | 变体 X（Data 接受裸 APFS + 跳过坏窗口） | `0db87f79…` | **用户态 /pong/init 运行**，缺可写 Data → init 退出 |
| v137 | 变体 Y（恢复写路径）+ 触摸固件注入 | `6a200fbd…` | Data `rw=1`、触摸 ready；dyld `F:arr` |
| v141 | 变体 Z（union=1/cryptex=0 + init 诊断） | `c1c49152…` | SystemOS union 挂载成功；dyld `F:open` |
| v142 | 直接 launchd（改 board.toml，无效） | `201e72c2…` | 参数未生效，仍 /pong/init |
| v143 | payload toml 真参数（direct launchd + usb + quiet） | `5871befc…` | 参数生效；`Unsupported Pong init path` panic（内核白名单只允许 /pong/init） |
| v144 | cryptex 内核 + payload 真参数 | `3a78ac04…` | cryptex 缓存路径 probe `error=0`；dyld `F:arr` |
| v145 | union 内核 + 离线 patch 适配层 env | `2141dd59…` | union 挂载成功；Data APFS 对象校验错误；dyld `F:open` |

CI run：V=45114535819、W=45118677224、X=45121063417、Y=45124309515、Z=45130125090、U=45110077013。

## 3. 当前产物

- 镜像：`F:\liuqin_ios\boot-v134..v145-*.img`（69,009,408 B 常规；v142..v145 为 69,009,408 B）。
- 内核：`/root/work/patched/kernel-v1xx-*.macho`（均已打 AppleARMCPU 补丁 `0xfffffff00b80dad4 -> mov w0,#1; ret`）。
- 固件 FD：本地 d97 树 `SILICIUM_UEFI.fd`（含 USB 交接 + 菜单修正）sha `341fe1ad5c1d…`；已验证 FD `44485ef0…`（无 USB 交接）。
- 根镜像：`F:\liuqin_ios\_dl\ci\img\userdata.simg`（32 GiB sparse，SHNGROOT 三窗口，OS/SystemOS/Data 裸 APFS）。
- CI 变体补丁：`ci/patches-variants/{q,r,s,t,u,v,w,x,y,z}/`（q–z 为本轮），workflow `kernel-upstream.yml` 已加 ccache、触摸固件注入（`LIUQIN_TOUCH_FW_DIR`）、SystemOS union 配置步骤。
- `userdata.yml`：根镜像重建 workflow（从 IPSW 准备 userland → SHNGROOT sparse 镜像），本轮已触发 run 45165352240。

## 4. 复现命令（当前工作流）

```bash
# 1) 生成/推送变体补丁（设备树根 = document97/UniXNU-liuqin @fe0e8d7）
cd /root/work/up-liuqin && git reset -q && git checkout -- . && rm -f drivers/NativeUfs/PongUfsPhyTables.h
python3 /mnt/f/liuqin_ios/scratch/make_variant_<x>.py
git diff > /root/work/<x>.patch
python3 /mnt/f/liuqin_ios/scratch/push_variant.py <letter> /root/work/<x>.patch 0001-<name>.patch "ci: <msg>"

# 2) 等待 CI 完成并取内核（直连，无代理）
bash /mnt/f/liuqin_ios/scratch/ci_fetch_kernel_direct.sh <run-id> kernel-upstream-encrypted
cp .../kernel.macho /root/work/patched/kernel-vNNN.macho
python3 /mnt/f/liuqin_ios/scratch/patch-armcpu-validate.py /root/work/patched/kernel-vNNN.macho

# 3) 组镜像（FD/UEFI/CAPE/payload 均可覆盖）
PAYLOAD_OVERRIDE=/root/work/payload-vNNN.img \
FD_OVERRIDE=/root/work/uefi-liuqin-d97/repo/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
UEFI_OVERRIDE=/root/work/uefi-liuqin-d97/repo \
CAPE_OVERRIDE=/root/work/uefi-liuqin/Resources/DTBs/liuqin.dtb \
bash /mnt/f/liuqin_ios/scratch/make_image_override.sh <run-id> /mnt/f/liuqin_ios/boot-vNNN.img /root/work/patched/kernel-vNNN.macho

# 4) 刷机（只写内存；userdata 写入为 A2 授权）
D:\PhoneTools\tool\fastboot.exe boot F:\liuqin_ios\boot-vNNN.img
```

## 5. 当前阻塞与下一步

1. **launchd 的 dyld 失败**（namespace 6）：
   - cryptex 模式 `F:arr=ffffffffffffff:A:ID:IC:1`（缓存存在：内核 probe `error=0`）；
   - union 模式 `F:open`（适配层 env 指向 `/private/preboot`，union 下该路径不存在）。
   - 下一步：用 `userdata.yml` 重建**干净根镜像**（排除镜像完整性与 Data 损坏），再按构建配置与内核模式严格配对（cryptex 镜像 + cryptex 内核，或 union 镜像 + union 内核）；若仍失败，核对 `dyld_shared_cache_arm64` 主缓存引用的 subcache 列表与镜像内分片是否齐全，并解码 `F:arr`。
2. **USB CDC 日志未枚举**：PongUsb 早期日志被 `CONFIG_XNU_PONG_APFS_DEBUG` 刷屏顶掉；下一步在 CI 关闭 APFS debug 或让 PongUsb 失败原因上屏，再验证 `pong_usb=1` + UsbOwnership 链路。
3. **union 模式 Data APFS 对象校验错误**：离线 patch 镜像的副作用，不再采用；改由 CI 重建镜像。
4. 后续（dyld 通过后）：launchd 服务栈 → backboardd/CoreAnimation → SpringBoard；GPU（PongAdreno 4800 行 + GMU 栈，可从 zizhan 同 SM8475 移植）是长尾。

## 6. 未验证/推测（不要当事实）
- `F:arr` 具体含义（推测与 dyld 缓存数组/subcache 完整性有关）。
- 新 ABL（Android 15）与 BootShim/EDK2 不兼容的具体原因（ArmCpuDxe `FAR=0xC717008`），已放弃新固件路线。
- USB CDC 未枚举的具体失败阶段（需要早期日志）。
- 根镜像重建后 dyld 是否直接通过（乐观但未验证）。
