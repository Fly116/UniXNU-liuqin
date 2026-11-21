# A2 分区方案执行手册（GPT 已校验）

用户已于 2026-11-21 授权 A2（备份 + 重建 userdata），除此之外不碰 Android 系统分区。
本手册只涉及 `unixnu`（自建 iOS 分区）与 `userdata` 的表项。

## 1. 目标布局（从 `scratch/gpt-new-head.bin` 实测解析）

| # | 分区 | first LBA | last LBA | 大小 |
|---|---|---|---|---|
| 35 | userdata | 2,758,144 | 24,986,618 | 84.79 GiB（原 105.79 GiB，缩小 21 GiB） |
| 36 | **unixnu** | 24,986,619 | 30,491,642 | **21.00 GiB**（新） |

- 4 KiB 逻辑扇区；`first_usable=6`、`last_usable=30,491,642`、entries 128 × 128 B。
- 主 GPT：`scratch/gpt-new-head.bin`（135,168 B = LBA1..LBA33，sha256 `a85268dd380389d4b5c67edc82552dbc7474f85e181b9d11ceb155f37cb702ff`）
- 备份 GPT：`scratch/gpt-new-tail.bin`（20,480 B，sha256 `9b0d164e8f549197a26ce4238390683a6fe303dacdaefc331af5894a722485af`）
- 改动前 GPT 备份：`scratch/gpt_now.bin`（17,408 B）

## 2. 前置条件

- `/sdcard` 已备份：`F:\liuqin_ios\_dl\backup\sdcard-20261121\files`（5,875 文件 / 228.9 MiB）✓
- 用户 A2 授权 ✓；执行前确认电量 > 50%。
- 需要 root（Magisk）或 TWRP 才能写 LBA1；`fastboot flash` 只能写分区，不能写 GPT 扇区。

## 3. 步骤

```bash
# 0) 记录现状
adb shell su -c 'sgdisk --print /dev/block/sda' > gpt-before.txt

# 1) 写主 GPT（LBA1 起）与备份 GPT
adb push gpt-new-head.bin /data/local/tmp/
adb shell su -c 'dd if=/data/local/tmp/gpt-new-head.bin of=/dev/block/sda bs=4096 seek=1 conv=fsync'
adb push gpt-new-tail.bin /data/local/tmp/
# 备份表紧接 last_usable 之后：30491 642 + 1 = 30,491,643
adb shell su -c 'dd if=/data/local/tmp/gpt-new-tail.bin of=/dev/block/sda bs=4096 seek=30491643 conv=fsync'
adb shell su -c 'sync'
adb shell su -c 'sgdisk --verify /dev/block/sda'    # 必须无错误

# 2) 进 fastboot，写根镜像到 unixnu（Android sparse，自动跳过 DONT_CARE）
adb reboot bootloader
fastboot flash unixnu userdata.simg                 # 11.33 GB 传输，约 20–40 分钟
fastboot reboot

# 3) Android 会因 userdata 几何变化走一次恢复出厂/格式化
```

## 4. 回滚

```bash
# 用 gpt_now.bin 恢复主表；备份表按原 last_usable+1 写回
adb shell su -c 'dd if=/data/local/tmp/gpt_now.bin of=/dev/block/sda bs=4096 seek=1'
```
回滚后 Android 需要重新格式化 userdata（可用之前的备份恢复 /sdcard 之外的数据没有备份）。

## 5. 顺序建议

**先修 UFS 传输层（TUR 能完成）再执行本手册**：否则根镜像写进去也读不出来，
而且 A2 之后再排查会把"读不到"与"没数据"混在一起。若想先验证写入流程，
可在 UFS 修好后把 A2 与写镜像一次性完成。
