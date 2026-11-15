# UniXNU-liuqin（骨架 + 已核实的板级数据）

Xiaomi Pad 6 Pro / liuqin / SM8475 的 UniXNU 设备仓库，由 UniXNU-sheng 派生。

状态：**内核、UEFI 固件、payload、boot.img 都能在 Linux 主机上构建**（2026-11-13 验证）；
实机 `fastboot boot` 尚未验证。板级关键数值已经从 stock 固件里核实完了，
board.toml 里每个 TODO 都有明确的取值方法和当前状态。

    board.toml                 板级描述（userdata LBA、splash、FD 窗口已填实测值）
    configs/liuqin_defconfig   内核配置（从 sheng 派生，PMGR/Adreno/UUID 标了 TODO）
    docs/liuqin-hardware.md    硬件底账：已核实 / 仍未知，每条带来源
    docs/vendor-inputs.md      stock UEFI 抽出的 154 个厂商输入 + uefiplat.cfg 硬数据
    docs/porting-plan.md       四阶段计划、通过标准、当前阻塞、立刻可做的事
    docs/liuqin-usb-debug.md   内核 USB CDC-ACM 调试口（LIQDBG001）：开关、四道自检门、移植对照表
    patches/xnu/               基础补丁 + zzz-liuqin-usb-debug*.patch（USB 调试口、bsd_init 里程碑）
    tests/liuqin_usb_host_test.c  调试口逻辑的主机侧测试（gcc，不需要内核）
    tools/capture-liuqin-debug.ps1  主机侧抓取脚本（按 VID/PID+序列号定位 COM，置 DTR）

配套（同级目录）
    ../UniXNU-sheng            设备仓库模板
    ../UniXNU                  构建驱动
    ../uefi-liuqin-seed        Mu-Silicium 设备配置种子（Resources/Configs/liuqin.toml）
    ../liuqin-firmware         从 uefi.elf 抽出的 93 个 PE32 + 58 个 Raw
    ../liuqin-nixos            主线 Linux 侧参考（面板/触控/ABL 身份/DTBO 资料）
    ../xiaomipad-6pro-mainline 主线内核与设备脚本参考

## 构建与打包（Linux，2026-11-13 验证）

    cd ../UniXNU
    export UNIXNU_DEVICE=$PWD/../UniXNU-liuqin UNIXNU_UEFI=$PWD/../uefi-liuqin \
           UNIXNU_EDK2=$PWD/../uefi-liuqin/Mu_Basecore UNIXNU_TOOLCHAIN=$PWD/../toolchain

    ./unixnu build kernel                 # out/liuqin/kernel/kernel.macho（含 prelink）
    ./unixnu build firmware               # uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
    ./unixnu build payload --kernel out/liuqin/kernel/kernel.macho \
        --unique-chip-id 0x84750A0B0C0D0001
    python3 ../UniXNU-liuqin/scripts/wrap-payload-mbr.py \
        out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
    ./unixnu bootimg --uefi ../uefi-liuqin \
        --dtb ../uefi-liuqin/Resources/DTBs/liuqin.dtb \
        --ramdisk out/liuqin/payload/payload-mbr.img

产物 `out/liuqin/boot/boot.img`（约 70 MiB = `gzip(BootShim+UEFI FD)` + Cape DTB +
68 MiB payload ramdisk）。`fastboot boot` 这个镜像即可，内存运行，不写分区。

内核补丁套用：schema 1 的补丁序列现在由 `xnu-work/.patches.sha256` 戳保证只套一次
（补丁互相重叠，第二遍既不能 apply 也不能 reverse-check）；删掉 `.cache/xnu-work`
或改动任一补丁才会重新套用。

下一步：上机看 `liuqin_milestone()` 的 `B<n>:` 里程碑（面板 + 1 MiB 环形缓冲，USB 调试口
`liuqin_usb=1` 时同时流出），定位 bsd_init 的停点。

## 致谢 / Acknowledgments

- **qwen3.8-flash** — 本移植的自动化工程会话由驱动该模型的 DeepSeek Harness agent 完成：
  Linux 工具链搭建、板级数据核实、ShengUfs SM8475 移植（fork 分支 `liuqin-sm8475`）、
  21H461 storage-bindings 离线推导、userdata Linux 构建、实机里程碑诊断与
  panic 可见化修复等系列迭代。
- UniXNU 官方与各社区机型仓（尤其 sheng 模板与 mondrian 的 SM8475 实测数据）。

特别感谢：

- 感谢朋友提供 token
- 感谢喵喵乖乖睡觉
- 感谢自己狠狠鞭策 AI
- 感谢小米平板

### AI 用量统计（截至 2026-11-16）

| 指标 | 数值 |
|---|---|
| 会话数 | 53 |
| assistant 回合 | 10,676 |
| 非缓存输入 | 30,596,484 tokens |
| 缓存读取 | 1,652,993,405 tokens |
| 输出 | 4,653,231 tokens |
| **合计** | **1,688,243,120 tokens（约 16.9 亿）** |

统计口径：本机两个工作区目录全部会话的 provider usage 记录之和（绝大部分为
本移植；含少量同工作区的群聊问答回合）。缓存读取占 98%，是长会话上下文复用的结果。
