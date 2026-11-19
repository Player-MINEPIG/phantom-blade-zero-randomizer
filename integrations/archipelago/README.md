# Archipelago 奖励目录

`catalog.upstream-v0.9.2.json` 收录 648 个原版点位和 48 种物品。点位包括 19 个宝箱和 629 个地图拾取点。物品包括常规强化材料、重铸符和珍宝。目录可交给随机规划器生成指定种子的分配。

如需重建目录，从发布页下载 `phantom_blade_zero.apworld` 与 `PBZArchipelago.zip`。上游发布标题称 APWorld `0.5.0`，包内 `archipelago.json` 声明 `world_version: 0.5.3` 和 `minimum_ap_version: 0.5.0`。本目录按外层发布标记 `v0.9.2` 和两个 ZIP 的 SHA-256 固定输入。派生数据保留了上游的 MIT 许可。 [上游发布](https://github.com/DisasterPBZ/Phantom-Blade-Zero-APWorld-0.9.2-Alpha/releases/tag/v0.9.2) · [上游许可](https://github.com/DisasterPBZ/Phantom-Blade-Zero-APWorld-0.9.2-Alpha/blob/main/LICENSE)

```powershell
python integrations/archipelago/import_catalog.py phantom_blade_zero.apworld PBZArchipelago.zip integrations/archipelago
python -m unittest discover -s integrations/archipelago
```

转换器只读取 `phantom_blade_zero/data.json` 和 `PBZArchipelago/Scripts/locations_data.lua`。每个点位必须在两份表中使用同一个游戏 `saveId` 和同一种原版物品 `cid`，并且由独立宝箱或地图拾取 Actor 表示。上游记录物品种类，单个奖励堆叠的原版数量仍待核验。目录排除多物品包、融合碎片、传送符、任务物品、书籍、装备、任务流、Boss 和成就。上游的 75 条 Boss 记录包含阶段和占位的 AP 奖励，原版掉落和能力开放条件需要查阅其他游戏数据。

## 文件桥映射

`bridge-map.upstream-v0.9.2.json` 的 `checks` 将目录奖励 ID 映射到 AP 整数 check ID。`items` 将游戏 `cid` 映射到授予类别 `prop`、显示名和 AP 整数物品 ID。物品与点位的 AP ID 各自独立。

| 文件 | `PBZArchipelago` 0.9.2 约定 |
| --- | --- |
| `active.txt` | 当前会话启用的整数 check ID，每行一个。 |
| `session.txt` | 单行会话标识。上游 Mod 在它变化时读取 `active.txt`。 |
| `outbox.txt` | 已检测到的 check ID 快照，每行一个。 |
| `inbox.txt` | 首行为会话标识，其后每行依次为授予类别、游戏 `cid`、物品名和可选来源名，由 Tab 分隔。用稳定顺序保留已入队的行。 |
| `applied_<session>.txt` | 已处理行数。重试失败后跳过的条目也会计数。 |

上游运行时通过读取关卡 Actor 存档状态检测宝箱与拾取点。原版奖励先由游戏发放，上游 Mod 再尝试移除匹配物品。清理取决于近期背包变化和点位的时间窗口，启动后默认前 20 秒跳过清理。桥对 `prop` 每行发一个单位。保留原数量、精确替换和恢复已有周目仍需在游戏中验证。上游把所有区域直连到起点，能力锁与可达性需要独立核对。

## 离线桥命令

作为接入备用路径，`offline_bridge.py` 将目录生成的奖励分配通过 `PBZArchipelago` 0.9.2 的文件协议发给游戏。需要另外安装并启用该上游 Mod，使用它的专用 `bridge` 目录。该命令本身只改桥目录中的状态和文本文件。游戏端授予和清理奖励会改变当前游戏背包，随游戏保存进入当前存档。首次运行会拒绝有 `.sav` 文件的 Steam 存档目录。

关闭游戏后，在全新 Steam 存档目录上初始化。将以下路径换成从本机游戏目录确认的路径。`--run-id` 代表当前测试周目，后续启动使用同一个值和同一份赋值计划。

```powershell
python integrations/archipelago/offline_bridge.py plan.json '<上游 Mod 的 bridge 目录>' --run-id test1 --new-save-dir '<游戏目录>\ProjectPBZ\Saved\SaveGames\Steam\<SteamID64>'
```

新桥目录应为空，或者只含上游 `.keep`。看到命令已就绪后启动游戏并创建新档。留出至少 20 秒让上游的奖励清理基线结束，再拾取测试点位。恢复同一周目时使用同一目录、计划和 `--run-id`，省略 `--new-save-dir`。`Ctrl+C` 停止轮询，已排队项保存在该桥目录。

同一个 check 重复出现时只入队一次。重新启动后维持队列中每行的位置，供游戏端继续读取。读回较早的原版存档会让背包和文件桥进度错开。上游 `applied` 文件把授予成功与失败跳过都计为已处理。当前测试验证了文件协议、重复事件和脚本重启，实际游戏内奖励与存档表现待验证。

## 手动补发推进武装

补救会将玩家选定的一件影之武装加入当前存档的背包。遇到原版障碍时，按原版操作装备并使用对应武装。`PBZArchipelago` 0.9.2 的游戏端直接读取本地文件桥，本功能可以离线使用。 [上游 Mod 和 APWorld 发布包](https://github.com/DisasterPBZ/Phantom-Blade-Zero-APWorld-0.9.2-Alpha/releases/tag/v0.9.2)

| 武装 ID | 用途 |
| --- | --- |
| `BrutalAxe` | 破坏粗锁链 |
| `ShachiHook` | 钩索攀越 |
| `LionHead` | 烧掉荆棘 |
| `TigerCannon` | 轰开石墙 |

1. 安装适用当前 Steam 游戏版本的 UE4SS，将 `PBZArchipelago.zip` 中的 `PBZArchipelago` 文件夹放入 `<游戏根目录>\platform\steam\ue4ss\Mods`。解压后确认 `PBZArchipelago\enabled.txt` 和 `PBZArchipelago\Scripts\main.lua` 在位。 [适配版 UE4SS 的安装说明](https://www.nexusmods.com/phantombladezero/mods/13)
2. 关闭 Archipelago 客户端和本项目的离线奖励桥。默认桥是 `PBZArchipelago\bridge`。有既有会话或待处理文件时，保留原目录，创建一个空目录，在 `PBZArchipelago\Scripts\config.lua` 的 `bridge_dir` 填入该空目录的绝对路径（例如 `bridge_dir = "D:/PBZRescue/bridge",`）。启动游戏并进入要补救的存档，等待目标桥写出 `alive.txt`。可在 `ue4ss\UE4SS.log` 搜索 `PBZArchipelago` 核对实际桥路径和版本。
3. 在随机 Mod 项目根目录运行以下命令。将游戏根路径和武装 ID 换成实际值。使用自定义桥时，将 `--game '<游戏根目录>'` 换为 `--bridge '<自定义桥目录>'`。

```powershell
python -m integrations.archipelago.manual_rescue list
python -m integrations.archipelago.manual_rescue grant BrutalAxe --game '<游戏根目录>'
python -m integrations.archipelago.manual_rescue status --game '<游戏根目录>'
```

`grant` 仅在该桥有近期的 0.9.2 心跳且无活动会话时创建单件请求。`status` 报告上游是否确认新增武装。若只有「游戏端已处理」，请查看背包，结果可能是已持有或发放失败。请求记录会保留，下一次补发使用新的空桥目录。现已按固定发布包核对文件协议并测试了本地请求和回执，Steam 游戏内发放待实测。
