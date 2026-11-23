# liuqin v133 → 下一版：复核记录

日期：2026-11-23（Asia/Shanghai）。状态：CI 45114535819 成功，v134 已校验并临时启动；实机读取通过，停在 pong userdata 边界校验。详见 [实机报告](v134-ufs-readback-2026-11-23.md)。

## v134 产物

- 镜像：`F:\liuqin_ios\boot-v134-ufs-v.img`，69,009,408字节。
- 镜像SHA256：`bec6810fb3fadeb3512482ec395dadd8ccc33931962853e79739dbe43bac7bbf`。
- patched kernel SHA256：`9aaf588d03774eb331dce8b69333f2b9f9a5cf8141ac65d606548008e2a1cf1b`。
- ARMCPU VA仍`0xfffffff00b80dad4`，新文件偏移`0x1942ad4`；校验仅这8字节被后处理修改。
- V `hostSubmit`反汇编：UTRD clear/field stores全为`str w...`逐32位访问；旧`stur d0,[descriptor,#4]`不再出现。正常RAM中的diagnostic仍可能有宽store，不与device描述符混淆。
- 独立镜像校验：boot-v4、固定FD完整字节、Cape完整哈希、PONGFAT1、64MiB FAT内嵌kernel与patched kernel逐字节一致全部通过。
- 组装脚本现有`unixnu bootimg --ramdisk /dev/null`内部失败（脚本用`|| true`继续），实际finalizer复用既有base boot。没有把脚本exit0当作完整证据；上述独立封装校验证明本轮最终镜像确实含指定固定FD/Cape与新内核。未改该脚本语义。
- boot args沿用旧参数含`pong_ufs_readwrite=1`，但V内核强制writable=false，启动应打印`V diagnostic forces storage writes OFF`。

## 本轮已复核

- WSL Ubuntu24 可用；本轮首次 `fastboot devices` 无设备输出。
- `/root/work/up-liuqin` HEAD 为 `fe0e8d790e24120970083e20c1a7d9c86cdbb87c`，已有 U 变体工作树改动。未 reset/checkout 清除它。
- 固定 FD SHA256：`44485ef0ca1e61d714115957cab3e6d5b53746bffae1e1f05090a077d7ab47d5`。
- boot-v133-ufs-u.img SHA256：`80745417bead4ad4ac69531192103aa570630b863ebd22f52762cd2d3f0b9aa1`。
- CI 45110077013 的 `products/products/kernel/mach.development.pong` 反汇编：
  - `hostSubmit` 起点 `0xfffffff007aa78d0`。
  - 照片 panic PC `0xfffffff007aa7a30` 精确对应 `stur d0, [x9, #0x4]`。
  - 前后是 UTRD 字段写入；在 +4 合并 8 字节写入，和 device 映射的 unaligned data abort 一致。
  - 当前 U 工作树 RootCommands.h 的 UTRD/PRDT/clear 指针仍非 volatile，O 变体的四处处理确实未组合进来。

## 已交叉核准的修复依据

- [Linux gcc-sm8450.c](https://github.com/torvalds/linux/blob/v6.17/drivers/clk/qcom/gcc-sm8450.c)：CBCR bit0=ENABLE，应置1；bit31=CLK_OFF只读状态。reference 在 GCC+0x9c000。AXI/AHB/AGGR/UniPro/ICE/AUX 六项均 hwcg_bit=1，TX/RX 是 BRANCH_HALT_DELAY。
- [Linux clk-branch.c](https://github.com/torvalds/linux/blob/v6.17/drivers/clk/qcom/clk-branch.c)：HWCG开启时不以idle CLK_OFF拒绝；无HWCG接受CLK_OFF=0或NoC FSM=2。V按此判断，TX/RX仅检查enable与延时。
- [Linux gdsc.c](https://github.com/torvalds/linux/blob/v6.17/drivers/clk/qcom/gdsc.c)：SW_COLLAPSE bit0、PWR_ON bit31。旧代码bit30错误。
- [Linux QMP UFS](https://github.com/torvalds/linux/blob/master/drivers/phy/qualcomm/phy-qcom-qmp-ufs.c)：SM8475为v6，0x1d80000布局SerDes0/PCS400/TX1000/RX1200/TX2 1800/RX2 1a00。不是盲试v5窗口。
- [Linux ufs-qcom.h](https://github.com/torvalds/linux/blob/v6.17/drivers/ufs/host/ufs-qcom.h)：HOST+0xdc bit1是PHY_SOFT_RESET；V按PHY power→assert reset→base/G4/HS-B表→deassert→PCS reset/start→READY顺序。HS-B补一项SerDes+0x140=0x44，未改表生成器解析。
- SerDes offset0不是scratch，旧完整32位0x5a5a5a5a回显测试无效且有副作用；V已移除。因此此前answers=0不能证明PHY物理无响应。
- [Linux unipro.h](https://github.com/torvalds/linux/blob/v6.17/include/ufs/unipro.h)：Available TX为0x1520，旧0x1540为RX；lane数非法回退2而非0xf。
- 不再向0x38..0x48错误码寄存器写假定W1C；只读并对IS确认。
- 强制gHost.writable=false，即使旧boot args带pong_ufs_readwrite=1也不能开启本轮写入。

## 提交与验证

- 隔离沙箱 `/root/work/v134-variant-v`；原U工作树未清理，保存在 scratch/v133-u-preserved.patch。
- V完整补丁 scratch/variant-v-draft.patch；SHA256 `dd14de1e4cbc68c651d4fdbd1a7950f374af88de8ae5fc76af5c230f1a634d35`。
- 提交 `4abc00d2dd8b0fc71b19807a180bc582bed1ad16`，只推允许的Fly116/liuqin-ipados18-ci。
- [CI 45114535819](https://github.com/Fly116/liuqin-ipados18-ci/actions/runs/45114535819)。
- CI 后已检查 volatile 访问实际反汇编、应用并验证唯一 AppleARMCPU 修改、固定 FD/DTB 组镜像并独立核验封装。后续实机见报告。

## 剩余不确定性

本次实机已观察 PCS READY、传输初始化完成与实际 GPT/userdata 读取；实际模拟供电稳定性、完整 PHY 冷启、长时间与多次启动稳定性仍未证明。V保留失败后的有界UIC/transport诊断，不把命令完成等同链路成功。旧“dl”日志实际来自UERDL错误码，不能当作链路状态寄存器。未完成所有上游分支/PR/Issue、所有FD退出行为审计。

## 安全边界

只 fastboot boot；不 flash、不改 GPT、不写 userdata。保留当前 Android13、固定 FD/DTB 和 ARMCPU 校验补丁。只向允许的 Fly116 仓库推送。敏感凭据不写入报告。
