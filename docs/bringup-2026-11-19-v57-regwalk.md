# 2026-11-19 晚场：v57 registry walk 与 IOStorageFamily 结论

本文记录 v57 这一轮的改动、实机看到的事实，以及从 IOStorageFamily 源码得到的结论。
所有真机结论都来自 `fastboot boot` 的内存镜像，未写任何分区。

## 本轮改了什么

1. `captureRegistryWalk()` 不再只打面板：结果写进 `gRootRegistryText`，由
   `rootDiagnosticFailure()` 追加进 panic 文本（面板会丢行/乱序，panic 块是唯一可靠通道）。
   内容包括：service plane 遍历计数、`dev/drv/media/bsd` 精确类名计数、
   `mc=XYZ`（三个类是否已注册元类）、平台专家下的直接子级类名、窗口自身 state/matched/busy，
   以及末尾一行 `V57 ...` 摘要。
2. 修掉 v56 遗留的两处编译错误：`gLatePublishGate` 在 `probe()` 里先于定义被使用；
   late-gate 的 `liuqin_milestone()` 调用少了一个 tag 参数。

## 构建链的坑（必须记住）

`unixnu` 在构建前会 `git submodule update --init --recursive`，把**工作树干净**的子模块
检出到**主仓库记录的 SHA**。v57 的驱动提交因此被静默回退成 v56，第一次/第二次构建出来的
镜像里根本没有新代码（`strings kernel.macho | grep REGWALK` 为 0 才发现）。

规则：改完驱动后必须**同时提交主仓库的 submodule 指针**，否则构建用的是旧代码。
每次构建后用 `strings -a out/liuqin/kernel/kernel.macho | grep <新记号>` 验证。

## 实机事实（2026-11-19 19:31，boot-v57-regwalk.img）

照片可读部分（面板小字层）：

```
U143:start-root
REGPUBLISH ok
U146:root-pub-SystemOS
REGPROBE class=NativeUfsBlock castsDevice=1 castsService=1 state=0x0 busy=1
CHAINPROBE devParent=ArmDTPlatform provParent=xiaomi,liuqin provPath=1 devAttached=1
CHAINPROBE path=IOService:/ArmDTPlatform/...
MEDIA start IOBlockStorageDevice=0 IOBlockStorageDriver=0 IOMedia=0 IOMediaBSDClient=0
```

解读：

- 窗口确实挂在 platform expert（`ArmDTPlatform`）下，provider 是 DT 节点 `xiaomi,liuqin` 下的
  `NativeUfs`，且 provider 在 service plane 里有完整路径 —— 之前 H13/H16 的链路问题不是当前卡点。
- `castsDevice=1 castsService=1`：元类链正确，`IOBlockStorageDevice` 类型识别通过。
- `state=0x0`：这只是**等待开始那一刻**的状态（匹配刚交给异步 job，还没跑），不能当结论。
- `MEDIA ...=0`：`capturePlaneCounts` 用的是 `IOService::getMatchingServices()`，而它按
  `kIOServiceMatchedState` 过滤 —— 未完成匹配的实例天然不在结果里。**这条不能证明"没有 driver"**。

未读到：`REGWALK` / `V57` 行。面板是"里程碑小字 + 内核控制台大字"两层叠加，且拍照时媒体
等待（300 tick 自旋）大概率还没走完，panic 尚未发生。

## IOStorageFamily 源码结论

源码在 `out/feeds/IOStorageFamily-ad2e13e0/`（不在 `xnu-work` 里，是预链接二进制对应的源码）。

1. **认领条件**：personality = `IOProviderClass IOBlockStorageDevice` +
   `IOPropertyMatch {device-type: Generic}`。而 `device-type=Generic` 是
   `IOBlockStorageDevice::init()` 自己 `setProperty` 的（`IOBlockStorageDevice.cpp:30-42`），
   只要我们的 `init()` 链走到基类，该属性就在。
2. **`IOBlockStorageDriver` 没有 `probe()`**，门槛在 `start()`：
   `open(this)` → `handleStart(provider)` → `PMinit()` → `provider->joinPMtree(this)` → `close` → `registerService()`。
   `handleStart` 的硬失败点是 `reportRemovability` / `reportEjectability` / `checkForMedia`
   （→`reportMediaState`→`recordMediaParameters`）。
3. **不依赖 `IOWorkLoop`**：IOStorageFamily 四个类里没有任何 workloop 使用。
4. **personality 早于任何 matching 就进了 catalogue**（`readStartupExtensions` →
   `sendAllKextPersonalitiesToCatalog`），所以"发布太早导致够不到 personality"不成立。
   真正的时序风险是"类是否已注册"（kext 是否已 start）；但 `startRoot` 里
   `getMetaClassWithName("IOBlockStorageDevice")` 非空，说明 IOStorageFamily 至少 start 过一次。
5. **`kIOServiceMatchedState` ≠ 被认领**：它表示"这一轮匹配处理完了"。没有 driver 认领也会有；
   只有 module-stall 或还没跑完才没有。`getMatchingServices()` 只挑带该位的实例，
   所以"它对已存在实例返回 0"是预期现象。
6. **`REGPUBLISH ok` 打在 `startMatching()` 之前**（本项目补丁在 `IOService.cpp:1089`），
   只证明"路径能到 registry root + `platformAdjustService` 通过"，不证明已注册、更不证明匹配发生。
7. 匹配是**异步**的：`startMatching` → `_IOServiceJob` → `_IOConfigThread` 现开内核线程 →
   `doServiceMatch`。`kernel_thread_start` 失败是静默 `continue`，没有日志。
   驱动里紧跟其后的第二次 `startMatching()` 是空操作（`needConfig` 已为 false）。

## 下一步（v58）

一行摘要，确保能在面板上读全，并且**在媒体等待结束后**再取值：

```
V58 st=<state> busy=<n> drv=<n> med=<n> mc=<XYZ> n=<n> dt=<device-type>
```

- `st`/`busy`：等待结束后重新取一次窗口状态（区分 `0x0` 没跑 / `0x2` 跑一半 / `0x6` 跑完）。
- `drv`/`med`：用 `IORegistryIterator` 遍历 service plane 并按类名过滤计数，**不要**用
  `getMatchingServices`。
- `dt`：`copyProperty("device-type")`，确认是 `Generic`。
- 把媒体等待的 tick 数降下来，确保几十秒内能走到 panic，否则又拍不到。
- 若 `st` 仍是 `0x0` → `doServiceMatch` 从未运行 → 试 `registerService(kIOServiceSynchronous)`。
