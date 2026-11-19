# 武器直发奖励

`scan(store)` 返回七个已核对的 `AddWeaponItem_C` 节点，以游戏 FlowNode GUID 作为点位 ID。每条 `Grant` 提供 `item`、`category`、`encounter` 和 `reward()`。将 `reward()` 的输出加入现有目录，并为 `encounter` 提供对应的遭遇条目。`apply(store, grants, plan['rewards'])` 返回改动的原始 cooked 资产路径和替换字节。

已确认的主武器为玉双环、荡寇凶刃、白影、痴者残剑、偃月刀。影之武装为操偶铃铛和铁狂拳套。操偶铃铛的内部武器 ID 为 `CaoOuSiXian`，简体中文本地化键为 `PhantomEdges_025`。目录排除了通行武器、教程、剧情发放、未证实分支和可能与 `DT_LevelLootDataTable` 重复的奖励。每个所选图只有一处武器直发节点。图中的其他物品或剧情节点继续使用原版数据。

r2 的七个 Boss 奖励与货币、文献、材料和其他原版来源共享同一掉落表。生成器为七个节点各扩展一行原生 LevelLoot 记录。每行沿用原版普通武器或影之武装的结构，保存实际武器 ID。全随机可以把这条记录派给白色货币点或绿色文本点，也可以把附带尘埃的整页文献派给 Boss。

当 Boss 的奖励有变化，`pooled.rewrite_changed` 使用原版玉儿任务中的 `LootItems_C` 类与默认对象引用替换原武器直发节点，并写入分配后的表行键。节点保留原始 GUID、触发连接及后续执行连接。导出大小、包导入和容器依赖同步更新。分配与原版相同的 Boss 继续使用原生直发节点。武器模式和白名单仍在分配前筛选点位。

```powershell
python -m unittest discover -s integrations/grants -v
$env:PYTHONPATH = '.work'
$env:PBZ_TEST_GRANT_ASSETS = '1'
python -m unittest discover -s integrations/grants -v
```

静态扫描和实资产测试覆盖 Steam `26367565`。点位的实际触发、拾取提示和读档后的发放状态仍需进游戏核对。

## 地面光点与普通宝箱的发放

原生 `BP_Rubbish.OnInteract` 调用 `Pickup`，在发放前清空旧物品集合并执行 `Collect Items`。普通宝箱的 `BP_Chest` 原生类默认对象绑定 `LS_Interact_Chest`，序列的事件轨调用 `Pickup Items`，该函数也先执行 `Collect Items`。两条路径在 `RubbishType == 1` 时以 `LootLevel` 和 `Loot Item ID` 调用 `GetCombatLootData`，再把计算出的物品和魂尘发给玩家。光点的 `TryToAddDust` 在调用 `AddDustNum` 前会按相同字段再查询一次。

这两个查表入口允许掉落表替换在拾取或开箱时生效。地图扫描要求普通查表模式，并排除使用自定义开箱序列或附带条件的点位。以上调用链来自 Steam `26367565` 的已烘焙蓝图与开箱序列。实资产回归核对默认宝箱序列绑定和调用指令。游戏里入包数量、发放时机与读档行为仍需实机核对。
