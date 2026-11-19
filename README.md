# 影之刃零 · 随机周目 | Phantom Blade Zero Randomizer

[中文](#中文) · [English](#english) · [下载玩家版 / Download for Windows](https://github.com/Player-MINEPIG/phantom-blade-zero-randomizer/releases/latest/download/PBZ-Randomizer.zip)

## 中文

用同一个种子可以玩到相同的奖励分布。这一版附带「白绿拾遗-113」，会打乱地图拾取、宝箱和部分任务及 Boss 奖励，也会调整部分武器数值与连段、普通敌人和对白。启动器为每个战役单独保存进度，从 Steam 正常启动仍可继续个人原版档。

**适用版本**　Windows x64，Steam build **26367565**，标题画面 **302256-17280**。玩家版包含启动器和离线切换工具，解压即可使用。完整通关和 Boss 发奖仍待实机验证。

<a id="游玩"></a>

### 安装与游玩

1. 退出游戏。从上方下载 **PBZ-Randomizer.zip**，完整解压到游戏安装目录以外的可写文件夹。保持 `PBZRandomizer.exe`、`Seeds` 和 `Tools` 在同一目录。
2. 如果装过静态 r1 或 r2，把 `ProjectPBZ/Content/Paks` 及其子目录下旧的 `z_PBZSeedRandomizer_P.pak`、`.utoc`、`.ucas` 三个同名配套文件一起移出游戏目录。继续旧测试档时还需要原来的包，可以单独保存。
3. 打开 `PBZRandomizer.exe`，输入战役名，选「白绿拾遗-113」，点 **新建空档战役**。选中这个战役，点 **继续战役**，在游戏主菜单选择 **新游戏**。
4. 下次游玩时，在启动器里点同一战役的 **继续战役**，进游戏后选 **继续游戏** 或 **载入游戏**。每个战役固定使用一个游戏槽位。
5. 要玩个人原版档，退出游戏，再从 Steam 正常启动。

### 导入旧档、切换与备份

- **从已有进度开始**　关闭游戏，填写新战役名并选种子，点 **导入原版档库…**，选择含原版存档的目录。启动器会复制整套档库。选定要玩的一个槽位，副本以原版布局开始。
- **中途启用或关闭随机**　用该槽位保存并退出，选中战役，点 **切换此战役模式…**。按当前进度勾选已领点，包括用掉的材料和读过的文献。旧档首次开启时，把确定还能回去领取的点标为「仍可领」，拿不准的点保留原位。清单由玩家确认。关闭随机后，已领取的奖励会保留，其余奖励尽量回到原处。
- **备份**　退出游戏后，同时复制 `%LOCALAPPDATA%\PBZSeedRandomizer\Campaigns\<战役名>` 和启动器旁的 `Seeds` 文件夹。恢复进度时使用配套的存档和布局。

更多点位说明和验证记录见[游玩说明](https://github.com/Player-MINEPIG/phantom-blade-zero-randomizer/blob/main/docs/游玩说明.md)与[静态 r2 实测及种子构建](https://github.com/Player-MINEPIG/phantom-blade-zero-randomizer/blob/main/docs/seed-notes.zh-CN.md)。

## English

Play a repeatable campaign with shuffled rewards. The included seed, **白绿拾遗-113**, shuffles map pickups, chests, and selected quest and boss rewards. It also changes some weapon stats and movesets, regular enemies, and dialogue. Each campaign has its own saves. Launching the game normally through Steam opens your personal vanilla saves.

**Supported version**　Windows x64, Steam build **26367565**, title-screen version **302256-17280**. The download includes the launcher and the tools for switching modes offline. A full playthrough and boss reward delivery still need in-game verification. The launcher uses Chinese labels, reproduced below.

### Install and play

1. Quit the game. Download **PBZ-Randomizer.zip** above and extract the entire archive to a writable folder outside the game installation. Keep `PBZRandomizer.exe`, `Seeds`, and `Tools` together.
2. If you installed static r1 or r2, move the old `z_PBZSeedRandomizer_P.pak`, `.utoc`, and `.ucas` files out of the game directory. Check `ProjectPBZ/Content/Paks` and its subfolders. Keep those files together if you plan to resume an old test save.
3. Run `PBZRandomizer.exe`, enter a campaign name, select **白绿拾遗-113**, and click **新建空档战役** (Create empty campaign). Select that campaign, click **继续战役** (Resume campaign), then select **New Game** in the game.
4. Next time, select the same campaign and click **继续战役**, then **Continue** or **Load Game** in the game. Use one in-game save slot per campaign.
5. To play your personal vanilla save, quit the game and start it normally from Steam.

### Import a save, switch modes, or back up

- **Start from an existing save.** With the game closed, enter a new campaign name, select a seed, and click **导入原版档库…** (Import vanilla saves). Select the folder containing your vanilla saves. The launcher copies the save library and starts the copy with its vanilla layout. Pick one slot to continue.
- **Switch mid-campaign.** Save in that slot and quit. Select the campaign and click **切换此战役模式…** (Switch campaign mode). Mark every reward already claimed, including materials you spent and documents you read. The first time you enable randomization on an imported save, mark locations you know you can revisit as **仍可领** (still available). Leave uncertain locations in place. The checklist depends on your input. Switching off keeps collected rewards and returns the remaining rewards to their original locations where possible.
- **Back up.** With the game closed, copy both `%LOCALAPPDATA%\PBZSeedRandomizer\Campaigns\<campaign name>` and the `Seeds` folder next to the launcher. Restore the matching save and layout together.

## 构建自定义种子 / Build a custom seed

在仓库根目录运行以下命令。构建需要受支持的游戏版本、Windows、Python 3.10+、.NET Framework 的 C# 编译器及 UE 5.7.4 的 UnrealPak 和 Oodle。编辑 `config.json` 设置种子和模块。输出目录须为新目录。

Run these commands from the repository root. Building requires the supported game build, Windows, Python 3.10+, the .NET Framework C# compiler, and UnrealPak and Oodle from UE 5.7.4. Edit `config.json` to choose the seed and modules. Use a new output directory.

```powershell
python -m pip install cryptography
python tools/prepare_tools.py
python -m pbzmod --config config.json --out build/my-seed --player-runtime "C:\Mods\PBZ-Randomizer\Tools\Python"
```

将示例路径替换为已解压玩家包中的 `Tools\Python` 目录。生成的玩家包位于 `build/my-seed/PBZ-Randomizer.zip`。

Replace the example runtime path with `Tools\Python` from your extracted player download. The generated package is `build/my-seed/PBZ-Randomizer.zip`.

<a id="creator-permission"></a>

## 创作者授权 / Creator permission

就作者拥有并有权授权的 Mod 原创部分，作者允许任何创作者使用本 Mod 录制、剪辑、发布和直播自己的游玩内容，并通过平台广告分成、创作激励、订阅、观众打赏和品牌赞助获得收入，无需逐次申请。这项额外授权也适用于已发布的 v0.1.0，以及随附本授权的各版本。

出售 Mod 或其修改版、将其放入付费整合包，或把 Mod 下载作为付费订阅或付费群福利，均须另行取得授权。创作者可以在视频简介或直播间分享本项目的公开下载链接。游戏画面、音乐及其他第三方内容的使用须遵守相应权利人的规则。

For the original parts of the mod that the author owns and can license, the author grants any creator permission to use the mod to record, edit, publish, and livestream their own gameplay. Creators may earn revenue from platform ads, creator incentive programs, subscriptions, viewer tips, and sponsorships without asking for permission each time. This additional permission covers the previously released v0.1.0 and every version that includes this notice.

Selling the mod or a modified version, bundling either in a paid modpack, or offering the download as a paid subscriber or group perk requires separate permission. Creators are welcome to share the project's public download link in a video description or livestream. Use of game footage, music, and other third-party content is subject to the respective rights holders' terms.

## 许可 / License

本项目的原创代码和文档采用 **PolyForm Noncommercial 1.0.0**，允许依条款非商业使用、修改和分发。游戏资产的权利归各自权利人，第三方组件沿用各自许可。

Original project code and documentation use **PolyForm Noncommercial 1.0.0**, which permits noncommercial use, modification, and distribution under its terms. Game assets belong to their respective rights holders. Third-party components retain their own licenses. [项目许可 / Project license](LICENSE) · [Archipelago catalog](https://github.com/Player-MINEPIG/phantom-blade-zero-randomizer/blob/main/integrations/archipelago/LICENSE-upstream.txt) · [retoc](https://github.com/Player-MINEPIG/phantom-blade-zero-randomizer/blob/main/integrations/profile_launcher/retoc-LICENSE.txt)
