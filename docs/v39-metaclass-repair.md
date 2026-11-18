# v39：元类 superClassLink 的受控修复（H16-F）

状态：**主机侧已实现并回归通过；未上机**。  
基线：v38（内核 `49247f07`，`M:stalled post … cnt=172` / `M:bad[170] bad-chain n=NativeUfsBlock`）。  
改动：`patches/driver/liuqin-v39-metaclass-repair.diff`（对 pristine `drivers/ShengUfs/NativeUfs.cpp`）。

## v38 之后确定的事实

1. 崩溃不是重名。`getObject("NativeUfsBlock")` 返回 NULL，类登记在自己的唯一名字下。
2. v36 的 gate 是假阳性。家族预链合法持有 `IOBlockStorageDevice`，gate 见名就拒绝，所以 v36c/v37/v38
   必然走到 `I60:base-dup` + 挂载失败。
3. 被涂的是 `NativeUfsBlock::gMetaClass + 0x10`（`superClassLink`），值是 8 字节控制台文本
   `0x3135205b0a293061`；`v38` 的扫描护栏把这一槽丢掉，于是**这个类没有进 `sAllClassesDict`**。
4. 涂写发生在 boot 的 C++ 初始化期：v37 的深度遍历（`postModLoad+0x2d4`）读的就是这个字段，
   说明构造器写入的链接当时已经坏了。

## 为什么先选"受控修复"，不直接照搬 whyred 的重注册

社区形态（N1709/UniXNU-whyred r117–r145）是手写 `class MetaClass : public OSMetaClass` + 运行时
`superClass` + 显式 `preModLoad` → 静态初始化 → `postModLoad`。它在本仓库**不能原样移植**，原因已从
XNU 源码核实：

- whyred 的 `whyred_block_static_init` 是 `__asm__("__GLOBAL__sub_I_WhyredBlock.cpp")`，即整个 TU 的
  全局构造器。liuqin 的 `NativeUfs.cpp` 里还有 `OSDefineMetaClassAndStructors (NativeUfs, IOService)`，
  再跑一次这个 TU 构造器会**连 `NativeUfs` 的元类一起重建并再次入 stalled 批次**，第二次
  `postModLoad` 必然撞重名 panic。
- 对内置进 `kernel.macho` 的 TU（`CONFIG_XNU_NATIVE_UFS=y`），要在运行时构造元类就得
  placement-new 到静态存储，绕开全局构造器；这一步没有编译环境无法验证。

而受控修复只需要一次写入，且这个写入的**目标值本来就是运行时才知道的**（家族注册的那个元类）。
所以 v39 先做这一层；若上机后 `M:reg` 快照证明字段会再次被涂，再升级到手写元类形态。

## 改动（三处）

| 位置 | 内容 |
|---|---|
| `startRoot` 序言 | 取家族元类 `IOBlockStorageDevice` → ABI 闸 `metaClass->getClassSize() == sizeof(NativeUfsBlock)` → `liuqinBlockAdoptSuperClass(base, "pre")` → 有界链校验；失败各有独立里程碑 |
| 元类定义之后 | `LiqMetaShim`（布局与 H16-E 诊断一致：`+0x00` vtable / `+0x08` reserved / `+0x10` superClassLink / `+0x18` className / `+0x20` classSize）、`liuqinBlockSuperClass()`、`liuqinBlockChainOk()`、`liuqinBlockAdoptSuperClass()` |
| `prepare()` 分配前 | `prep` 再校准一次：发布线程比 `startRoot` 晚，字段若被重新涂写，在这里抓在实例化之前 |

`liuqinBlockAdoptSuperClass` **只在值不同时写**，重复调用是 no-op（这是 H16 重入教训的对应物），
并且两个状态都上屏。

**v36 的 gate 必须删掉**（作者工作区里的那段 `if (!liuqinBaseClassFree ()) …`）。仓库里的
`drivers/ShengUfs` 分支本来就没有这段，所以本补丁不含删除动作。

## 面板判读

正常应看到（顺序）：

```
U:59:start-root_init
NativeUfs: M:reg pre p=0xfffffff007ae36b0 link=0x3135205b0a293061   ← 若仍是 boot 期的涂写值
NativeUfs: M:reg pre fixed link=0xfffffff007add1d0                  ← 家族元类
U:meta-ok
U:root-bringup-ok … U:root-manifest-ok … U:root-plan-ok … U:root-prepared
NativeUfs: M:reg prep p=… link=0xfffffff007add1d0                    ← 每窗口一次，值不变
U:root-pub-<window>                                                  ← 发布线程的既有里程碑
→ 挂载决策越过 IOKitBSDInit.cpp:989
```

判读规则：

| 看到 | 含义 | 下一步 |
|---|---|---|
| `U:base-missing` | 家族元类还没注册 | 说明 `startRoot` 时机太早，需要提前触发或换查找方式 |
| `U:abi` | `getClassSize()` 不等于 `sizeof(NativeUfsBlock)` | 元类布局/编译单元不一致，停手查编译产物 |
| `M:reg pre` 的 `link=` 仍是 `0x3135205b…` | 涂写发生在 boot 期，且只发生一次 | 修复有效 |
| `M:reg pre` 的 `link=` 已是家族元类 | v38 之后字段没被涂（或编译产物已变） | 记录，v39 仍是无害的幂等写入 |
| `M:reg prep` 又打印 `fixed` | **字段在运行期被再次涂写** | 升级到手写元类形态，并开始定位写者 |
| 过了 `U:root-prepared` 但仍 `Failed to mount root device` | 块设备发布成功，问题在根卷/文件系统层 | 换到 FS 侧判读（不是 H16 了） |

## 主机侧回归

`tests/metaclass-simtest` 新增场景 E（`./run.sh` 或 Windows 的 `run-win.ps1`）：

| 场景 | 断言 |
|---|---|
| E0 只删 gate、字段仍是毒值 | 实例不是 `IOBlockStorageDevice` ⇒ 媒体不会匹配（证明"删 gate 不够"） |
| E1 `startRoot` 修复 | `kindOfBlockDevice=1`、`kindOfIOService=1`、链深 3 |
| E2 重复调用 | no-op，不重写、不重复注册 |
| E3 修复后再次被涂 | 修复前能被检测到，`rearm` 幂等修好 |

当前结果：`ALL SIM ASSERTIONS PASS`（A/B/C/D/E）。

## 构建链现状（2026-11-18 在本机核实）

- `macOS 12 (Monterey)` 最高只能装 Xcode 14.2（iPhoneOS 16.2 SDK），而本仓库目标是
  `-miphoneos-version-min=17.0` + XNU 10063；直接用 Monterey 编内核不可行（除非把 iPhoneOS17
  SDK 硬塞进 Xcode 14，属偏方）。
- UniXNU 主线已经支持 **Linux 编内核**（`scripts/linux/setup-toolchain.py`，上游 clang +
  cctools-port），但本设备仓库对应的是**旧一代构建树**：`board.toml` 指向
  `kits/NativePrelink/emit_prelink.py`，而带 Linux 支持的树用的是 `kits/XnuPrelink`。
  两条线不兼容，设备仓库需要迁移才能本地 Linux 构建。
- 作者自己用的是 `.github/workflows/macos.yml`（`macos-latest`，固定 fork
  `1696108518/UniXNU` 分支 `liuqin-build`），产物推到 `ci-out` / `ci-parts` 分支；
  这两个分支里能直接看到 `kernel/kernel.macho`（约 51 MB）和构建日志。
- `uefi-liuqin` 仓库自带预编译 DTB（`Resources/DTBs/liuqin.dtb`，480,704 B），但**没有**构建好的
  `SILICIUM_UEFI.fd`；FD 需要用 EDK2 现编（Linux/macOS 都能编）。

结论：v39 的内核和 payload 走作者那条 CI 最省事；固件与 `bootimg` 可以在 Linux/Windows 侧完成。

## 上机步骤（需要构建机 + 真机）

构建侧（macOS + Xcode，按 README 的 `quick start`）：

```sh
cd ../UniXNU
export UNIXNU_DEVICE=$PWD/../UniXNU-liuqin UNIXNU_UEFI=$PWD/../uefi-liuqin \
       UNIXNU_EDK2=$PWD/../uefi-liuqin/Mu_Basecore UNIXNU_TOOLCHAIN=$PWD/../toolchain
./unixnu build kernel
./unixnu build payload --kernel out/liuqin/kernel/kernel.macho --unique-chip-id 0x84750A0B0C0D0001
python3 ../UniXNU-liuqin/scripts/wrap-payload-mbr.py \
    out/liuqin/payload/payload.img out/liuqin/payload/payload-mbr.img
./unixnu bootimg --fd ../uefi-liuqin/Build/liuqinPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd \
    --dtb ../uefi-liuqin/Resources/DTBs/liuqin.dtb --ramdisk out/liuqin/payload/payload-mbr.img
```

对账：`out/liuqin/boot/boot.img` 必须是 **69,525,504 B**（漏 `wrap-payload-mbr.py` 会是
68,476,928 B）。

设备侧（纯内存，不写分区）：

```sh
fastboot devices
fastboot boot out/liuqin/boot/boot.img
```

然后按 `docs/liuqin-usb-debug.md` 抓 USB CDC-ACM 日志，并拍照记录面板 `U:*` / `M:reg` 行。

## 需要构建机才能确认的两件事

1. `NativeUfsBlock::metaClass` 在真实 SDK 头里是 `OSDeclareCommonStructors` 的 public 静态成员
   （本补丁据此取址）。若编译报 `metaClass` 不可访问，改用
   `const OSMetaClass *base = NativeUfsBlock::metaClass;` 所在作用域的替代取址方式。
2. 新增的 `<libkern/c++/OSSymbol.h>` / `<libkern/c++/OSMetaClass.h>` 在该 SDK 下可包含
   （`helper.inc` 里 `OSSymbol::withCString` 已被 v36 gate 用过，风险低）。

## 若上机后字段再被涂：升级路线（whyred 形态，已核实的前提）

- `OSMetaClass::preModLoad` 里有 `assert(sStalled == NULL)`：只能在 boot 批次结束后调用，
  `startRoot` 时机满足。
- `postModLoad` 返回 `OSReturn`（0 = 成功），内部用 `OSKext::lookupKextWithIdentifier(kextID)`；
  `g_kernel_kmod_info.name == kOSKextKernelIdentifier == "__kernel__"`，且该 kext 在
  `OSKext.cpp:1069` 被放进 `sKextsByID`，所以 `"__kernel__"` 能查到，不会 `kOSMetaClassNoKext`。
- **不要**照抄 `__GLOBAL__sub_I_*.cpp`：本 TU 里还有 `NativeUfs` 的元类。必须 placement-new 到
  静态存储，且 `getMetaClass()` 返回该对象。
