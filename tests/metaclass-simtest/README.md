# OSMetaClass::postModLoad 主机侧仿真

不交叉编译、不上机就能跑：桩件复刻 XNU 的元类登记表和 `postModLoad` 的两条路径，
把实机照片上的崩溃形状在主机上重现，并验证驱动侧 gate 与 XNU 侧扫描护栏的行为。

    g++ -std=c++17 -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. sim.cpp -o sim
    ASAN_OPTIONS=detect_leaks=0 ./sim        # 期望最后一行 ALL SIM ASSERTIONS PASS

（那 4 字节的"泄漏"是场景 A 故意保留的中毒 `ExpansionData`，不是缺陷。）

| 场景 | 建模对象 | 期望 |
|---|---|---|
| A 无 gate | 重名 → iOS panic 分支读已释放 `orig->reserved` | 复现 v35 面板的 data abort |
| B 有 gate | `startRoot` 入口先查名字 | 拒绝发布 + `U:base-dup`，不分配 |
| C 闭世界 | 家族没进预链闭包 | gate 放行 |
| **D（v38）** | `classes[]` 干净，但某项 `superClassLink` 是 ASCII 毒值 `0x6131373030666666` | D1 用 v37 的裸走链复现 `postModLoad+0x2d4` abort；D2 用 v38 的链校验证明**只丢掉那一项**、其余照常登记、`sDeepestClass` 语义不变 |

`helper.inc` 是从 `drivers/ShengUfs/NativeUfs.cpp` 的 `liuqinBaseClassFree()` 原样抽出的生产代码，
`gate.inc` 是 `startRoot` 序言里调用它的那段；改了驱动必须同步这里。
