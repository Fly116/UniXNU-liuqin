# 相关上游存储进展同步（2026-11-23）

范围：用户指定入口与实际存储依赖的聚焦审阅；不是所有仓库逐文件/所有分支穷尽审计。代码存在、主机测试、设备测试分别记录。

## 版本与结论

| 项目 | 本轮核对头 | 对当前问题的作用 |
|---|---|---|
| [document97/liuqin](https://github.com/document97/UniXNU-liuqin/commit/fe0e8d790e24120970083e20c1a7d9c86cdbb87c) | fe0e8d790e24120970083e20c1a7d9c86cdbb87c | 当前基线，无默认分支更新的 PHY 修复 |
| [Fly116/liuqin](https://github.com/Fly116/UniXNU-liuqin/commit/515f887ac8b665514a55104d64f4415b83d8d73f) | 515f887ac8b665514a55104d64f4415b83d8d73f | 调查/发布档案；后续实验主要在 CI variant 中 |
| [hhyygg/liuqin](https://github.com/hhyygg2009/UniXNU-liuqin/commit/ba09bd2841d4a9470da22f5c3d9e09a02d30f756) | ba09bd2841d4a9470da22f5c3d9e09a02d30f756 | iPadOS17/ShengUfs 同型号另一设备有读取/根路径证据，到 launchd SIGKILL；不是当前物理机 |
| [Fly116/ShengUfs v56](https://github.com/Fly116/ShengUfs/commit/26ae865ea31492cb9f156621a04acc2effff1092) | 26ae865ea31492cb9f156621a04acc2effff1092 | SM8475 GCC 正确 enable 定义，正常路径接管固件链路，不冷启动 PHY |
| [zizhan](https://github.com/qiumochen/UniXNU-zizhan/commit/054a2f52a25e44754b1719c0465e3de226d99e06) | 054a2f52a25e44754b1719c0465e3de226d99e06 | 18.7.10 桌面/挂载与新鲜 UFS klog 设备证据；链路通后可复用文件根镜像、APFS 死锁修复 |
| [uefi-zizhan](https://github.com/qiumochen/uefi-zizhan/commit/c498ff26d438f818a2910e099dcf64c9ea036336) | c498ff26d438f818a2910e099dcf64c9ea036336 | 头提交 GUID 文本修正；未证明与本机 ExitBootServices 行为等价 |
| [Pong 保留树](https://github.com/Y3d4/UniXNU-pong-clean/commit/b2a9db7571bba44da3643a3dc8d21a4a8ed65476) | b2a9db7571bba44da3643a3dc8d21a4a8ed65476 | 16.6.1 主屏声明，不等于新 18.x 存储修复 |
| [Pong 符号产物](https://github.com/Y3d4/UniXNU-pong-build/commit/cc16920492981714f639c8aa976cb37b2f22a31d) | cc16920492981714f639c8aa976cb37b2f22a31d | 未剥离符号参考 |
| [UniXNU 核心](https://github.com/UniXNU/UniXNU/commit/8542980d02b4d2cc5c32ee3542de1760b2562aac) | 8542980d02b4d2cc5c32ee3542de1760b2562aac | 设备记录更新，不解决本机 PHY |
| [官方 ShengUfs](https://github.com/UniXNU/ShengUfs/commit/f020bd693c34790c04e97c52720af3cd842336fb) | f020bd693c34790c04e97c52720af3cd842336fb | SM8550，不能搬 GCC 地址 |
| [UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng/commit/c8f92b208068eeaa4cd2b0f592671f04ee70076e) | c8f92b208068eeaa4cd2b0f592671f04ee70076e | 触摸验证更新 |
| [DarwinBoot](https://github.com/UniXNU/DarwinBoot/commit/5243c68ec332a227fe3680cd5da6d5a0e127035c) | 5243c68ec332a227fe3680cd5da6d5a0e127035c | 窗口外内存列表，提交仅 host test，未进固件/上机 |

Chengdong-Yu/UniXNU-pong 本轮公开 API 404，不能断言删除或转私有。

## 关键对照

[Sheng GCC 定义](https://github.com/Fly116/ShengUfs/blob/26ae865ea31492cb9f156621a04acc2effff1092/GccUfs.h)：bit0=BRANCH_ENABLE；SM8475 UFS GCC page=0x187000，GDSC +4、AXI +18、AHB +20、TX +24、RX0 +28、RX1 +c0、UniPro +64、ICE +6c、AUX +a4、AGGR +d4（以上偏移十六进制）。

[hhyygg 设备记录](https://github.com/hhyygg2009/UniXNU-liuqin/blob/ba09bd2841d4a9470da22f5c3d9e09a02d30f756/porting.toml#L182-L266)：记录来自另一台同型号设备，不是本次实测物理机。UFS reads/capacity/GPT/window有设备证据；持久写入正确性不能单凭README宣称。部分历史驱动提交未公开，因此不能承诺公开pin重建所有历史结果。

[zizhan 存储实现](https://github.com/qiumochen/UniXNU-zizhan/blob/054a2f52a25e44754b1719c0465e3de226d99e06/drivers/NativeUfs/PongUfsTransport.cpp#L133-L194)：map HC、分配 DMA、quiesce、SMMU reuse/migrate、start queue、NOP、query、必要时SSU。无正常路径 PHY 冷启。

## 不能继承的误读

- [旧 TUR 文档](https://github.com/hhyygg2009/UniXNU-liuqin/blob/ba09bd2841d4a9470da22f5c3d9e09a02d30f756/docs/ufs-tur-analysis-2026-11-22.md) 把 IS bit2=UTRCS、UTRLRS 0=run 写反。应以 UFSHCI 和实现验证：UTRCS bit0、UE bit2、RSR bit0=1运行。
- [官方 UFS 指南](https://unixnu.com/zh/porting/ufs) 提醒 HWCG 时 idle CLK_OFF 可能为1，不能一概作为访问失败。
- 投票接受不等于电源稳定；answers=0不等于整窗口死；UERDL数值不是可证明链路工作的“dl状态”。
- 尚未完整审阅各 FD 的 UfsDxe ExitBootServices，不能宣称 ABL 关电是已证实根因。

## 审阅时点建议与后续结果

以下为 v134 测试前的审阅建议：修复已符号化的描述符合并访问；纠正 GCC/GDSC 位语义；去除无效/有副作用的全字 PHY scratch 测试。不要引入大包显示/用户态改动。

**后续 v134 已完成上述补丁并实机读取成功**，当前阻塞转为 pong 固定 userdata 边界与根布局适配。见 [实机报告](v134-ufs-readback-2026-11-23.md)。本表 SHA 是审阅时点快照，不代表永久最新。
