# 路线 Y/Z 的引导链试验记录（2026-11-21）

目标：把 pong 栈（QPRS-6，iPadOS 18.7.10 / Darwin 24）的内核跑到我们这台 liuqin 上。
每一条都是真机 `fastboot boot` 的实测结果，按时间顺序。

## 已确认的资产

| 资产 | 来源 | 状态 |
|---|---|---|
| `kernel.macho`（52,686,848 B，arm64 MH_EXECUTE） | 我们 fork 的 CI `kernel-encrypted` | ✅ 取出并验证 |
| `volume-layout` / 真实卷 UUID | 同上 | ✅ OS `B07DF049-…`、SystemOS `5D08420A-…`、Data `5DF4DC0A-…` |
| pong 版 `DarwinBoot24.efi`（GUID `D6112048`） | 在 Linux 上编出（29,696 B） | ✅ |
| 他们的 `liuqinPkg`（含 `MemoryMapLib`、`PongBootMemoryDxe`） | `document97/uefi-liuqin` | ✅ 能在我们树里编过 |
| PONGFAT1 payload 包装器 | 自写 | ✅ CRC32 校验通过 |
| ADT 生成器 | 他们的 `make-pong-adt-ipados18.py` | ✅ Linux 可跑；窗口 256/192 MiB 两版 |

## 试验序列与结果

| # | 组合 | 结果 | 说明 |
|---|---|---|---|
| 1 | 我们固件（原版）+ pong DarwinBoot + 4 GiB 窗口 | `Out of Resources` | 窗口太大，分配不到 |
| 2 | 同上 + 256 MiB 窗口 | **进内核**，`pmap_map_bd @pmap.c:1967` | 窗口被 DXE 挤到 `0xBB000000`（显示保留区） |
| 3 | 固件把 `0xBB000000` 标保留、加 5 GiB 大块 | **进内核**，`zone_init: kmem_suballoc` + 栈指针无效 | 窗口落到 33 GiB，超出 `dram-size` 覆盖范围 |
| 4 | 固件把 `0xA8000000 + 256 MiB` 标可分配 | `Out of Resources` | 诊断画面：`BIG RUN CDC0000`（220 MiB）< 256 MiB |
| 5 | 窗口区扩到 384 MiB | 固件自检拒绝 | `Kernel Window 与 Display Reserved 重叠` |
| 6 | 窗口缩到 **192 MiB**（改 DarwinBoot 下限 128 MiB） | **进内核**，仍 `pmap_map_bd` | 分配成功，但启动数据映射失败 |

## 第 6 次的关键结论

`pmap_map_bd` 的 panic 条件是：

```c
pt_entry_t *ptep = pmap_pte(kernel_pmap, vaddr);
if (ptep == PT_ENTRY_NULL) { panic("pmap_map_bd"); }
```

**是虚拟地址没有页表项**，不是物理内存不可用。也就是说：内核在 bootstrap 阶段给"启动数据"建映射时，
用的 KVA 不在它预留的范围里 —— 说明**引导环境（boot_args 的布局/位置）与这个内核的期望不一致**。

他们用 `BootShim` 的根本原因就在这里。但把他们的 FD 直接塞进我们的 kernel 槽，他们的 PEI 会在
`0xA7104A04` 直接崩溃（`Synchronous Exception`），因为 PEI 还依赖 XBL HOB 等 BootShim 之外的东西。

## 还没试过的两条

1. **完整复刻 `build_uefi.py`**：他们的仓库有官方构建入口，但 `Common/Mu`、`Mu_Basecore`、
   `Binaries` 都是空子模块。用我们已展开的 `Mu_Basecore`（280 MB）+ 他们的 `Platforms` 组合，
   让 `build_uefi.py` 自己算定义，而不是我们手写 `unixnu build firmware` 的参数。
2. **改用他们 FD 的 PEI 入口条件**：先在他们的 PEI 里加串口/屏幕打印，确认它到底在 `+0x4A04` 做什么
   （我们有他们的源码，可以加诊断）。

## 未完成

- 根镜像：用户重下中（第一次被后台 curl 覆盖损坏，`userdata.7z.001` CRC 失败）
- 分区改造（A2：userdata 84.79 GiB / unixnu 21.00 GiB）：GPT 已算好并双重校验，未执行
- Metal 链：CI 已产出（9.2 MB），从未在真机验证
