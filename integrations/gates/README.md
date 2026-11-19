# 能力锁、任务条件与随机周目

已从 Steam build `26367565` 的本地原版资产核对。此处提供只读验证，首版保留关键奖励位置。

## 地图交互

原版 `BP_GameplayBlocker_Base.CheckNeedShaChiWeapons` 调用背包的 `FindValidAbilityTag`。`OnInteract` 会设置交互用装备并发送能力事件。普通探索交互允许玩家继续使用自己的战斗配装。表中列的是已核对的武器与机关类，具体点位还可能有独立剧情条件。

| 机关或动作 | 原版资格 | 额外处理 |
| --- | --- | --- |
| 铁链、松动地板、松动石墙 | 巨凶斧、长柄金瓜、虎炮各对应一种 | 命中后该点才破坏。锁链还要同步障碍子 Actor 与读档状态。 |
| 潮湿荆棘、火焰屏障 | 烈焰狮头烧荆棘，游龙头灭火 | 两者触发不同能力事件。 |
| 飞渡锚点、连弩、荒行子机关 | 追命锁镰飞渡、拙壁盾挡箭、血滴子转动机关 | 保留位移、格挡或机关动作。锚点可以反复使用。 |
| 悬挂物 | 羽弓和独眼弓共用普通射击标签；妙手飞刀、黄金火铳、游龙叉另有对应标签 | 原版类可以选择多种有效工具，按照该实例的条件选取交互动作。 |
| 幻术屏障与通往枷笼山的幻境之门 | 普通催心琵琶 `CuiXinPiPa` 的破障标签为空。其铸魂形态幻术琵琶有 `Lute.Activate` | 幻鬼任务检查琴头 `I_05001`、琴弦 `I_08002`、背板 `I_04001` 的取得记录，并处理组装与铸魂。门还用到组装、弹奏相关任务标签和传送流程。 |
| 雷霆枪 | 武器表写有 `ThunderDoor.Activate` | 在核查的能力锁类和引用它们的地图分块中未确认对应门，暂不作为主线必需能力。 |

## 任务及库存条件

| 原版实例 | 实际检查 | 随机化要保留的行为 |
| --- | --- | --- |
| 三面混沌，玉琮二阶段结束 | `BPF_SanTouMoOuDeath` 的 `IsEquipWeapon_C` 同时要求已装备主武器类别的 `Long`，且 `IsWeaponSnapSouled` 为真，即炽刃。节点未传入当前手位参数。 | 成功进入第三阶段，失败走另一条结算及存档分支。两边均可发放刺骨混沌，因此该武器入包无法证明第三阶段完成。 |
| 玉妖铁鬼切磋 | `BPF_YuYao` 要求主武器栏只有妖锯 `YuuBlade`，影之武装栏只有铁拳套 `TieGongZhuQuanTao`。原版移除空槽、排序后分别比较整组装备。 | 匹配才进切磋；多带一件也会走未匹配对话，玩家可以调整装备后重试。 |
| 第二件影之武装 | `HasJustObtainedSecondShaChiWeapon` 比较已获得的影之武装数量是否恰好等于 2，在老弓手、追命、炼邪相关图中有实例。 | 若随机发奖，仍需在真正发生获得事件时处理教学或提示的时序，避免错过或重复触发。 |
| 钥匙与材料门 | 西谷龙珠铁门查 `K_01001 ×1`，飞贼密道的反向门查双生金属 `Weapon_Material_04 ×1`。有的门从宿主配置读取条件。 | 分别登记检查数量、是否实际扣除、开门方向及其他入口。仅看到数量检查不足以判定物品会消耗。 |
| 剧情碰撞门 | 白山秘闻掌门门按 `bsmw.掌门本体.已解脱1` 设置碰撞。 | 保留原任务选择和先后顺序。到场、进战与完成该剧情是不同事件。 |

在发布种子「白绿拾遗-113」中，双生金属进入了随机池，原版也还有固定来源。正式目录没有记录飞贼密道门的前置边，不能据此断言该种子必定卡关或已经通过全流程验证。

`CheckDoorLockItems_C` 的 16 个直接实例中，以下 12 个在节点上写有固定物品，数量均为 1。西谷小地洞取 `K_01003`，龙珠铁门取 `K_01001`，白蛇屋取 `K_06005`，`Doo_Cellar` 取 `K_05001`，正道大营 Door1、2、4、5 分别取 `K_03001`、`K_03002`、`K_03004`、`K_03005`，宗祠山门取 `K_10002`，飞贼密道取双生金属，救人飞贼图的两个实例均取 `K_05006`。其余四个（普通门 V1、`ZhoupingziDoor`、`HengDaoDoor`、飞贼小院门）的节点没有固定物品，另有门预制体子类从宿主取条件。

## 通用实现方案（待实现）

1. 将每条规则记录为“授权来源、检查发生时机、条件、成功动作、存档范围”。普通 Boss 破障资格随原遭遇的终局胜利发放。NPC、任务组装等资格取各自原版里程碑。随机对手、随机物品和通行资格各自保有独立身份。
2. 只在启用随机的存档与当前周目读取这些资格。用原版可持久验证的进度重建资格，并让额外状态与存档快照同步回滚。现有发行路线以进程隔离种子包、以独立战役隔离存档。游戏内按档切换尚待通过零售版验证。 [启动与存档边界](../../docs/integration-research.md#零售版启动与存档边界)
3. 探索机关在互动时用资格选择原版动作与临时交互装备，随后让原版负责命中、动画、碰撞、剧情通知与存档。对永久破坏物按实例记完成；对锚点等可重复能力只记使用资格。
4. 为任务挑战、库存数量、铸魂和成套装备分别保留条件。生成时把固定来源、商店、配方、可消费数量、单向通道和剧情截止点纳入可达性检查。要求保持原版可完成的目标在种子里仍有一条实际可行路径。证据不齐时固定至少一条及时可达的原版来源。
5. 最小验收从彭猛与一处锁链开始。随机档在胜利前不可破链，胜利后即使未领斧也能互动。换图和读档后复核已破、未破两处链，并检查普通存档和更早的随机存档保留各自状态。再覆盖飞渡复用、琵琶组装、玉琮两个结算分支和双生金属反向门。

## 彭猛遭遇与锁链通行

| 环节 | 原版资产证据 |
| --- | --- |
| 原遭遇 | 西谷分块 `82OBM6ICJZS18QDOP03KXFZHY.umap` 的 `PengMeng_Seq014` 刷怪器使用 `BP_Monster_PengMeng_Axe_C`，并绑定导出索引 1690 的 `MobGroup`。 |
| 胜利事件 | 该组的 `MobGroupScript_ClearGroup_C.EventTag` 发出 `xg.击杀.斧老大`。`BPF_FuLaoDaDeath` 的 `FlowNode_HasWithSourceTag.ObserveTags` 监听同一个标签。 |
| 武装发放 | 已按 `NodeGuid` 解码正向连线。监听器的 `Match` 经 `SetExcuteType_C`、两个 `SetTag_C` 和定时器进入 `FlowNode_ExecutionSequence`。序列的输出 `1` 指向 `AddWeaponItem_C`，其 `WeaponID` 是 `BrutalAxe`。 |
| 障碍判断 | `BP_ChainBlocker` 类默认对象的 `NeedAbilityContainer` 需要 `GameplayEvent.BreakBlocker.Chain.Activate`，与巨凶斧数据行的 `BrokenBlockerTag` 相同。父蓝图已有 `CheckNeedShaChiWeapons` 和 `FindValidAbilityTag` 分支。 |
| 能力状态 | 原生 `PBZBackPackSubsystem` 有 `BrokenBlockerTag`、`OnBlockerAbilityTagChanged` 和 `GetCurrentBlockerAbilityTag`。当前反射符号提供了查询及武器发放入口。 |

沿用原版破链互动时，需要找到从遭遇胜利标签授予背包通行能力的入口，并证明读档后恢复该能力。现有证据证实了这两个标签所属的资产链路，持久授予和读档链路仍待确认。障碍还会通过通行标签选择交互武器与能力事件，直接换入胜利标签可能破坏动作分发。

## 直接用 Flow 标签打开障碍

- 白山秘闻的 `BPF_ZhangMenOpenDoorCollision_1a` 将 `bsmw.掌门本体.已解脱1` 的存在和缺失分别接到关闭和开启碰撞的 `SetCollision_C` 节点。地图分块 `CRYJ2YKNBFB2V3GK33Z2ENIPM.umap` 的实际宿主是 `StaticMeshActor_UAID_30C5995A1E558CD202`。`SetCollision_C` 的原版导入包括 `PBZFlowNodeBase.GetOwnerActor` 和 `Actor.SetActorEnableCollision`。
- `BPF_FuLaoDa_ChainInvisible` 的两个监听器使用 `xg.斧老大.出场`。分块 `A0BAJ1X5PW31GAJLZWLYF0NAH.umap` 的五个挂载组件均属于 `SkeletalMeshActor`。这是彭猛出场相关的场景布置。
- 西谷找到六个 `BP_ChainBlocker_C` 实例，其中两处有 `BP_PBZFlow`。`5X07PNCSMVMV2XOT13VCHZU9L.umap` 的实例加载 `BPF_XiGuHouYuanBlocker`，含 `xg.村庄.破坏铁链` 的发出节点。`DA9HKJOG4NGNPXE01ZDZJW7YD.umap` 的实例加载 `BPF_FuLaoDa_HexingLingdangNoLeave2`。后者监听彭猛击杀标签，用于交互引导及设置 `xg.斧老大.劈开铁链`。两处皆有 `Obstacle` 子 Actor 组件。
- `BP_ChainBlocker_C.RefreshVisual` 给独立的 `BP_Roadblocker_I` 子 Actor 调用其读档状态接口。`BP_Roadblocker_I` 自己定义 `SetBlockCollision` 和 `SetBlockStateOnLoadGame`。直接复用只修改 Flow 宿主碰撞的节点，缺少锁链子 Actor 与 `bBroken` 同步的证据。其余四处链还需要核对如何挂载 Flow。首版保持原版通行机制。

## 复核

从项目根目录运行。脚本校验原版资产摘要，再解码固定字段及组与脚本的链接。

```powershell
python -m integrations.gates.inspect_pengmeng "E:/Game/Steam/steam/steamapps/common/PBZ/ProjectPBZ/Content/Paks" --reader-dir ".work" --oodle "D:/Epic Games/UE_5.7/Engine/Source/Programs/UnrealBuildTool/bin/Development/oo2core_9_win64.dll"
```
