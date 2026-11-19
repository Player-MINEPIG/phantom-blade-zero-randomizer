# 站桩对白资源覆盖

此适配器适用于 Steam build `26367565`。它从本机资源读取对白节点、音频事件和字幕的对应关系，然后输出可打包的 Zen 覆盖文件。

每个游戏对白节点保存 `RowName` 和 `RowNameStr`。该键对应 `DT_LocTable` 中的 Wwise 事件，也对应 `Game.locres` 中的字幕。适配器一起替换两个键及其自定义音频时长和起点。候选节点需在同一对白图、具有相同播放元数据、拥有可定位的 Wwise 事件和中英文字幕。带序列引用的节点、音乐控制行以及疑似播片或回忆的图会被排除。

`zen_combat.py` 读取战斗能力 `GA_*_Subtitles` 里的 `MobTagSubtitlesData.Subtitles`。能力在各自的触发条件下使用 `FlowLocText.Key` 查找语音和字幕。战斗池只纳入同一能力、同一说话人、具有兼容播放元数据且能定位到战斗 Wwise 事件和中英文字幕的行。默认关闭，可通过生成设置 `combat_voices` 启用。

## 生成

准备本地 Oodle DLL 和 PBZ-Editor 的两个只读模块 `resources_reader.py`、`pak_reader.py`。游戏原始目录和 DLL 路径由调用者指定。工作目录用仓库根目录。[PBZ-Editor 源码](https://github.com/qry6868/PBZ-Editor/tree/main/pbz_editor)

```powershell
python -m integrations.voices.zen_dialogue "E:/Game/Steam/steam/steamapps/common/PBZ/ProjectPBZ/Content/Paks" ".work/voice-build" --reader-dir ".work" --oodle "D:/Epic Games/UE_5.7/Engine/Source/Programs/UnrealBuildTool/bin/Development/oo2core_9_win64.dll" --seed wei-2026
```

输出的 `zen/ProjectPBZ/...` 保留原始游戏包路径。 `voice-plan.json` 记录种子与节点分配。用现有 IoStore 打包流程处理 `zen/`。如需只检查一张图，可加 `--graph DDSD/DG_GuaiMian2.uasset`。

## 验证结果

本机目录检出 1,630 个兼容站桩节点和 48 个战斗对白槽位。种子 `wei-2026` 生成 134 个原尺寸站桩覆盖文件，并重新解析验证了写入的两个行键和时长字段。战斗种子 `battle-smoke` 生成 13 个原尺寸覆盖文件，回读验证了 32 个战斗对白槽位的新键。相同种子的输出逐字节一致。语音播放和字幕显示仍需游戏内验证。
