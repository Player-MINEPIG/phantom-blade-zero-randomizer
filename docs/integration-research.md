# 《影之刃零》随机 Mod 接入调研

调研以 Windows Steam 版为基准。资产和工具结论注明公开资料或本机验证来源。[已完成的游戏内验证](architecture/index.html#validation)

## 目标版本和工具

Steam AppID 为 `4115450`。S-GAME 确认游戏使用 UE5，2026 年 11 月 4 日发布 `1.0302256` 补丁并说明部分第三方 Mod 与补丁不兼容。公开映射作者把该补丁对应到 Steam build `26367565`、游戏 changelist `CL-302256_JKS-17280` 和 S-GAME 定制的 UE `5.7.4`。首发 Steam build `26266538` 使用不同映射。 [Steam 商店](https://store.steampowered.com/app/4115450/Phantom_Blade_Zero/) · [S-GAME 更新公告](https://steamcommunity.com/app/4115450/announcements/?l=schinese) · [映射作者的版本记录](https://openmods.nexus/mods/kintaromodding/phantombladezero_pbzusmap)

| 工具 | 已有证据 |
| --- | --- |
| UnrealPak | 本机存在 `D:\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealPak.exe` 和 `UnrealEditor.exe`。同套安装的 `Engine\Build\Build.version` 为 `5.7.4`，changelist 为 `51494982`。 |
| CUE4Parse 和 FModel | 映射作者报告使用 CUE4Parse 成功读取 1,750 个玩法包的 31,772 个导出对象。build `26367565` 对应 v1.1 的 `ProjectPBZ-5.7.4-302256-full.usmap`。 [CUE4Parse](https://github.com/FabianFG/CUE4Parse) · [映射说明和测量结果](https://openmods.nexus/mods/kintaromodding/phantombladezero_pbzusmap) |
| UAssetGUI | 支持资产和 JSON 双向转换。映射作者用 UAssetGUI 1.1.0 的 `VER_UE5_6` 档读取了 78 张游戏数据表中的 77 张。写回保真度待用目标资产核验。 [UAssetGUI 命令行](https://github.com/atenfyr/UAssetGUI#command-line-arguments) · [映射兼容性](https://openmods.nexus/mods/kintaromodding/phantombladezero_pbzusmap) |
| retoc | 可在 IoStore Zen 格式与旧版 Unreal 包之间转换。上游有 `UE5_7` 测试，游戏的具体资产类型仍需往返核验。 [retoc](https://github.com/trumank/retoc) · [UE5.7 测试代码](https://github.com/trumank/retoc/blob/master/retoc/src/zen_asset_conversion.rs) |

首选从纯数据覆盖包验证接入。社区 `PBZHardMode` 1.0.2 在 `ProjectPBZ\Content\Paks\~mods` 下使用同名 `.pak`、`.utoc` 和 `.ucas`。作者报告 x2 配置两次进入游戏世界，实际伤害效果尚待验证。该补丁增加过敌人属性，旧版覆盖包曾让游戏误读移速和抗性。构建时应核对游戏 build、映射版本和所修改属性的布局。多个包覆盖同一资产时，游戏只能使用其中一份。 [PBZHardMode 作者说明](https://www.nexusmods.com/phantombladezero/mods/62?tab=description)

## 需求对应的真实数据入口

| 需求 | 已有证据与验证目标 |
| --- | --- |
| 武器与物品目录 | 从 `DT_WeaponData`、`DT_ShaqiWeaponData` 和 `DT_InventoryData` 核对原版稳定 ID。公开提取包含 31 条主武器行、25 条影之武装行、278 条物品行。原始行数包含剧情变体、测试和重复条目。白名单按具体可获得的 ID 建立。 [MetaBot 数据提取说明](https://metabot.gg/en/phantom-blade-zero/methodology) |
| 奖励位置 | 关卡文件包含宝箱、拾取物和记忆花点位。任务与剧情奖励来自 quest 和 dialogue flow graphs。`PBZDropMultiplier` 1.0 曾覆盖原版掉落表，后续版分别处理敌人、拾取物、宝箱和营地结算。每类来源各选一条记录，核对发放字段与一次性状态。 [MetaBot 数据提取说明](https://metabot.gg/en/phantom-blade-zero/methodology) · [PBZDropMultiplier 作者说明](https://www.nexusmods.com/phantombladezero/mods/109) |
| 能力锁 | 分别找出原遭遇的终局胜利状态、机关的通行条件和影之武装发放点。任务存档资料中已有 `NarrativeSavedQuests`、`QuestClass`、`ReachedStateNames` 等实测字段。Boss Phase Reset 的作者观察到，有些 Boss 在同一个 Actor 上换阶段，有些阶段则对应不同 Actor。具体机关谓词及其可修改性待验证。 [任务存档结构](https://github.com/Duucking/pbz-save-editing-guide#72-%E4%BB%BB%E5%8A%A1%E7%BB%93%E6%9E%84) · [Boss Phase Reset](https://www.nexusmods.com/phantombladezero/mods/71) |
| 武器数值与连段 | 从 `DT_WeaponData` 和 `DT_ShaqiWeaponData` 追踪数值和能力引用。Weapon Tuner、Moveset Editor 和 Weapon Transmog 分别提供可改数值、连段和外观的社区实证。核对同类两把武器的模型、技能引用和连段资产，验证模型保留、整套招式切换，以及命中、判定和消耗。完整动作组的资产边界待实测。 [武器目录来源](https://metabot.gg/en/phantom-blade-zero/methodology) · [Weapon Tuner](https://www.nexusmods.com/phantombladezero/mods/412) · [Moveset Editor](https://www.nexusmods.com/phantombladezero/mods/930) · [Weapon Transmog](https://www.nexusmods.com/phantombladezero/mods/316) |
| 怪物配置层级 | 敌人目录可从 `DT_CodexEnemyDataTable`、`DA_ActorConfig`、`ActorC_*` 查找。社区作者用原版 enemy spawner 数据查单位等级，Phantom Tower 报告自定义波次与按场地和阶段编排的 Boss 遭遇。先对照常规敌人位置、同一位置的成组刷新、包含多阶段的 Boss，确认原版关卡使用的最小单位和上级编组。 [敌人表来源](https://metabot.gg/en/phantom-blade-zero/methodology) · [Spawner 数据实例](https://www.nexusmods.com/phantombladezero/mods/363) · [Phantom Tower](https://www.nexusmods.com/phantombladezero/mods/636?tab=description) |
| 语音和字幕 | 双语字幕 Mod 使用纯资源覆盖包处理 4,497 个条目。英文语音替换作者把 Wwise 事件划为对白、战斗和播片三组。先在同一语言中找两条站桩对白的事件和字幕键，确认能成对换位，并检查对话状态和播放时长。 [双语字幕](https://www.nexusmods.com/phantombladezero/mods/291) · [语音事件分类](https://www.nexusmods.com/phantombladezero/mods/345?tab=description) |

公开获取来源可用于抽查。MetaBot 对 31 条主武器记录定位到 23 条、25 条影之武装记录定位到 23 条，对 75 条 Boss 奖励证实 39 条、70 条任务奖励证实 42 条。涉及流程解锁时，需要核对每个待随机点位及其前置条件。 [MetaBot 获取来源覆盖度](https://metabot.gg/en/phantom-blade-zero/methodology)

## Archipelago 点位目录

`PBZArchipelago` `v0.9.2` 的 APWorld 包含 474 条物品记录和 1,429 条点位记录。游戏端的 Lua 数据表使用同一组 check ID，关联游戏的 Actor `saveId`、任务节点 GUID、装备游戏 ID 或 Boss 类。游戏端脚本的配置记录七件受保护影之武装。`BrutalAxe`、`ShachiHook`、`LionHead` 与 `TigerCannon` 对应破链、攀越、烧荆棘与破石墙。`JinGua` 对应碎裂地板的说法，以及游龙相关的 `YouLongTou`、`YouLongCha` 对应关系，仍需实测。APWorld 把所有地区直连到起点，能力锁和任务可达性尚待建模。 [上游发布包](https://github.com/DisasterPBZ/Phantom-Blade-Zero-APWorld-0.9.2-Alpha/releases/tag/v0.9.2) · [本项目点位目录和桥协议](../integrations/archipelago/README.md)

后续本机原版数据已确认长柄金瓜对应松动地板、游龙头对应火焰屏障、游龙叉可作用于悬挂物。新增核查也涵盖铸魂形态、成套装备、材料数量和任务阶段。见[能力锁与任务条件清单](../integrations/gates/README.md)。

## ModCraft 与同类项目

2026-11-19 核查。ModCraft 官网将其介绍为 AI Mod 创作与分享平台，设有《影之刃零》专区。专区的《随机增援 MOD》（`PBZRandomEncounter`）由社区作者发布。据作者说明，它通过游戏专用 UE4SS 在运行时新增敌人，可选掉落由脚本发放。平台公开资料尚未提供对本游戏按种子重排原版奖励、验证通关条件并输出 IoStore 三件套的可复核实例。CurseForge 上的同名 ModCraft 整合包面向 Minecraft。 [ModCraft 官网](https://www.modcraft.games/) · [《影之刃零》专区](https://www.modcraft.games/games/phantom-blade-zero/mods) · [随机增援作者说明](https://www.modcraft.games/games/phantom-blade-zero/mods/88) · [Minecraft 同名整合包](https://www.curseforge.com/minecraft/modpacks/modcraft-by-malex97mc)

另外两项社区方案有各自明确的范围。Nexus 作者说明称，《肉鸽之影》（`RoguelikePBZ`）通过 UE4SS 在拾取时随机收集品，保护武器、影之武装和关键道具。 `PBZ Weapon Randomizer` 使用独立的 JS/TS 加载器 `PBZModLoader` 与附带的运行组件生成新武器。上文的 `PBZArchipelago` 提供点位目录和游戏端文件桥。本节社区行为来自作者说明，本项目的原生包读回与游戏内验收记录见架构页。 [肉鸽之影作者说明](https://www.nexusmods.com/phantombladezero/mods/1202?tab=description) · [武器随机作者说明](https://www.nexusmods.com/phantombladezero/mods/912?tab=description) · [PBZModLoader 上游](https://github.com/zoneoflkf/PBZModLoader) · [已有架构评估](architecture/index.html#modcraft) · [本项目验证记录](architecture/index.html#validation)

## 零售版启动与存档边界

本机零售版启动验证使用独立目录。Steam 启动的进程进入标题，`-UserDir` 指定的目录下有 `Saved/Paks`，游戏打开其中的 `.utoc` 和 `.ucas`。`-SaveGamesDir` 指定的目录收到游戏生成的测试存档。启动器以这两个参数选择独立战役的布局和档库。Steam 正常启动仍使用安装目录下的个人存档路径。 [Epic `-UserDir` 接口说明](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Core/FPaths/CustomUserDirArgument) · [Steam 云存档路径](https://steamdb.info/app/4115450/ufs/) · [玩家启动步骤](../README.md#游玩)

按档原型尝试在 `ProjectPBZ/Content/JavaScript/MainStart.js` 加载游戏内菜单和奖励切换脚本。UnrealPak 读回探针路径正确，实机启动后未产生探针 JSON。零售可执行文件含脚本校验报错，S-GAME 补丁公告也提示第三方 Mod 兼容变化。社区加载器的更新记录明确提到本版本的脚本内容校验。本地逻辑测试覆盖切换和奖励守恒，目标零售版的脚本入口尚未验证。 [S-GAME 1.0302256 更新](https://pbz.s-game.com/zh-CN/news/patch-notes-2026-11-03/) · [Puerts 默认文件加载器](https://github.com/Tencent/puerts/blob/master/unreal/Puerts/Source/JsEnv/Private/DefaultJSModuleLoader.cpp) · [社区加载器更新记录](https://www.nexusmods.com/phantombladezero/mods/113?tab=logs)

游戏生成和 Steam 云端同步的是 PBZS v3 `.sav` 文件。现有公开资料说明，点位记录位于加密并验证完整性的存档区块中。本次未找到面向玩家的官方逐点 JSON 导出接口。社区蓝图调研中，`LogicMods` 的可运行案例通过 UE4SS 加载。发行包使用原生 Pak 和 IoStore 覆盖，覆盖范围由启动的游戏进程决定。 [SaveSmith 格式说明](https://github.com/gundamff/SaveSmith/blob/main/docs/games/phantom-blade-zero.en.md) · [PBZ 蓝图加载记录](https://openmods.nexus/mods/kintaromodding/ue4ss)

## 地面武器拾取实测

2026-11-19，Steam build 26367565 使用独立测试档库和「白绿拾遗-113」的定位测试副本。测试副本只修改悲泣溪谷的四个关卡分区，将两处武器配置放到开端之地铃铛附近的两个同类 `BP_Rubbish_C` 实例上。两个实例沿用发行配置的奖励行、游戏原生拾取逻辑、Niagara 特效及其参数。掉落表 `DT_LevelLootDataTable` 的 SHA-256 与发行版一致。发行布局继续使用原点位。

游戏中两个测试点都显示钥匙色的橙红光。交互拾取后，游戏为两件物品分别展示 3D 模型。操偶铃铛面板显示「装备新的影之武装？」。玉双环面板显示「双持武器」、1 级、伤害能力 288、破防能力 114 和「装备新的武器？」。斧老大关押处和溪谷杀气塔一层两个发行点位的实地表现，以及 Boss 发奖仍待验证。

## 启动器切换验证

2026-11-19 的启动器验收使用空白测试档库的副本。先从原版布局切到随机，随后以一条模拟领取记录关闭，再以两条模拟记录开启。三次都沿用同一存档目录，9 个文件逐个核对 SHA-256 均相同。无领取记录时重建的随机 `.ucas` 与已验收的白绿种子逐字节一致。关闭时回读的 3 个游戏资产分别为掉落表、玉面死亡任务图和斧老大关押处的一块地图。玉面发放点继承了原光点的完整尘埃行；地图上的原光点保留玉双环所用的钥匙光效。这次领取为测试输入。

## 后续游戏内验证

1. 读取本机游戏 build，选择对应 `.usmap`，记录原容器与目标资产的身份。用现有读包入口导出同类两把武器的数据表行，确认数值来自同一字段。
2. 保持一次未修改的资产往返，并对照导出字段、引用和包路径。随后只交换一个能在装备页或战斗中观测的数值。读回生成包，确认改动落在目标行。
3. 使用测试存档装载三件套。核对标题加载、进入世界、武器界面、战斗效果、读档后效果，以及移除三件套后的基线。记录游戏 build、包哈希和所用存档条件。
4. 对两处普通一次性奖励做同样的换位验证。记录是否发放正确物品、领取后是否重复发放，以及重试和读档时是否沿用该周目的分配。再验证一场 Boss 的胜利条件能否独立开放对应机关。

静态包在游戏启动时载入，本次种子分配随独立战役使用。游戏内按档切换、旧档自动识别和独立通行能力仍待接入并实测。 [能力锁与任务条件](../integrations/gates/README.md)
