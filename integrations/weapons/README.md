# 武器数值和连段补丁

`build_patches(store, schemas, stats, movesets)` 返回两个字典。第一个把原始 cooked 资源路径映射到替换字节。第二个提供新增模型依赖后的有序 package ID，仅列出有变动的配置。构建容器需要把第二个字典的依赖写入对应的 package store entry。

`store` 从本机游戏 IoStore 读取原版资源。`schemas` 是 Steam build `26367565` 对应的 `.usmap`。两个分配参数使用 `接收武器ID → 来源武器ID`，由同型武器组产生。`read_weapons` 返回本版可用于数值验证的 ID、类型、基础配置和铸魂配置。 [对应的 USMAP 版本](https://openmods.nexus/mods/kintaromodding/phantombladezero_pbzusmap)

## 离线验证范围

- 38 件武器支持替换 `Weapon Attack Multipliers` 和 `Weapon Attack Multipliers Normalized` 里的物理伤害、失衡伤害和格挡失衡伤害倍率。同型分组来自原版 `WeaponType` 和 `ShaChiWeaponType`。如果接收方有铸魂配置，优先使用来源方铸魂配置的数值。属性积累、按招式设置的数值和其他成长属性应在游戏中另行识别和核验。
- 白影 `BaiYing` 和偃月刀 `RenOuYanYueDao` 支持整套配置对调。两者都是双手武器，使用同一组挂点，各有一个游戏中使用的武器 Actor。表中的 `WeaponConfig` 指向来源配置，来源配置的 `Display Data.WeaponClass` 则指向接收武器的原版 Actor。构建器读回模型包 ID、导出 hash、挂点和武器技能字段。其他连段配对仍需用对应配置和真实游戏行为验证。
- 数值与连段一起启用时，构建器把两个来源组合到接收武器使用的配置。动作单独启用时，接收武器带入本来的三项数值倍率。

这些验证基于本地 cooked 资产的读取、编辑和读回。动作实机中的技能条件、碰撞和特效，以及装备属性界面的行为仍需在游戏里确认。

```powershell
python -m unittest discover -s integrations/weapons -v
$env:PYTHONPATH = '.work'
$env:PBZ_TEST_WEAPON_ASSETS = '1'
python -m unittest discover -s integrations/weapons -v
```
