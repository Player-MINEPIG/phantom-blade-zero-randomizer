# 怪物分布资源覆盖

Steam build `26367565` 的生成单位是关卡中的 `AISpawner`。`AISpawner.Class` 指向要生成的 Blueprint 类，`MobGroup.Members` 记录分组的生成器成员。`DT_AIAreaLevel` 和所在分组参与原版等级计算。[Phantom Gladiator 原版等级与生成点核对](https://github.com/LingYi-Liang/PhantomGladiator/blob/main/docs/STATS_GUIDE.md)

| 地图 | 核验的关卡包 | 槽位 | 分组 |
| --- | --- | ---: | ---: |
| 悲泣溪谷 | `7MSFXHRARGNM96ALJRBMCW2AH`、`82OBM6ICJZS18QDOP03KXFZHY` | 88 | 34 |
| 正道大营 | `A4FPJ05LRWUTAQUUFRWC0WEJI` | 22 | 4 |
| 庞镇 | `9MNPQBUK8GIWDIWOAMGM1EYTR` | 23 | 12 |
| 后街 | `64Q0WR55YIK5YSQBU92NEAOS4` | 5 | 2 |

`catalog_monsters(read_file)` 返回可参与随机的槽位。`patch_monsters(read_file, assignments, mode)` 返回等长 Zen 覆盖及原资产路径。补丁按资产 SHA-256 检查输入，只重排同一包中同战斗角色的普通敌人类引用。组模式在相同人数与战斗角色构成的分组之间交换完整阵容。抽样范围由本机资产回读验证，游戏内生成仍待测试。
