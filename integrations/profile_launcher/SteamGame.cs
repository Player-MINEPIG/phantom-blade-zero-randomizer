using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;

internal sealed class SteamGame
{
    internal const string AppId = "4115450";
    internal const string Build = "26367565";
    private const string Paks = @"ProjectPBZ\Content\Paks";
    private static readonly string[] ProcessNames =
        { "PBZ", "ProjectPBZ", "PBZ-Win64-Shipping", "ProjectPBZ-Win64-Shipping" };
    private static readonly Regex SharedRandomizer = new Regex(
        @"\A(?:z_)?PBZ(?:SeedRandomizer|SlotExtras)(?:_[a-z0-9-]+)*\.(?:pak|utoc|ucas)\z",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    internal readonly string Exe;
    internal readonly string Root;
    internal readonly string BuildId;

    private SteamGame(string exe, string root, string buildId)
    {
        Exe = exe;
        Root = root;
        BuildId = buildId;
    }

    private static IEnumerable<string> Vdf(string path, string key)
    {
        if (!File.Exists(path)) yield break;
        var pattern = "\"" + Regex.Escape(key) + "\"\\s+\"((?:\\\\.|[^\"\\\\])*)\"";
        foreach (Match match in Regex.Matches(File.ReadAllText(path), pattern, RegexOptions.IgnoreCase))
            yield return match.Groups[1].Value.Replace("\\\\", "\\").Replace("\\\"", "\"");
    }

    internal static SteamGame Find(string steam, string requestedGame)
    {
        if (string.IsNullOrWhiteSpace(steam))
            steam = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamExe", null) as string;
        if (string.IsNullOrWhiteSpace(steam))
            steam = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam", "steam.exe");
        steam = Path.GetFullPath(steam);
        if (!File.Exists(steam) || !Path.GetFileName(steam).Equals("steam.exe", StringComparison.OrdinalIgnoreCase))
            throw new IOException("找不到 Steam。可以用 --steam 指定 steam.exe。");
        var steamRoot = Path.GetDirectoryName(steam);
        var roots = new[] { steamRoot }
            .Concat(Vdf(Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf"), "path"))
            .Concat(Vdf(Path.Combine(steamRoot, "config", "libraryfolders.vdf"), "path"))
            .Select(ProfileStore.NormalizeDirectory)
            .Distinct(StringComparer.OrdinalIgnoreCase);
        var matches = new List<SteamGame>();
        foreach (var root in roots)
        {
            var steamApps = Path.Combine(root, "steamapps");
            var manifest = Path.Combine(steamApps, "appmanifest_" + AppId + ".acf");
            var name = Vdf(manifest, "installdir").FirstOrDefault();
            if (string.IsNullOrWhiteSpace(name) || name == "." || name == ".." ||
                name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                continue;
            var game = Path.Combine(steamApps, "common", name);
            if (File.Exists(Path.Combine(game, Paks, "ProjectPBZ-Windows.pak")))
                matches.Add(new SteamGame(steam, game, Vdf(manifest, "buildid").FirstOrDefault()));
        }
        if (matches.Count != 1)
            throw new IOException("Steam 库中必须有一个可读取的《影之刃零》安装。");
        var matchGame = matches[0];
        if (requestedGame != null &&
            !matchGame.Root.Equals(ProfileStore.NormalizeDirectory(requestedGame), StringComparison.OrdinalIgnoreCase))
            throw new IOException("--game 必须与 Steam 记录的游戏安装目录一致。");
        return matchGame;
    }

    internal static bool Running()
    {
        foreach (var name in ProcessNames)
        {
            var processes = Process.GetProcessesByName(name);
            foreach (var process in processes) process.Dispose();
            if (processes.Length != 0) return true;
        }
        return false;
    }

    private static IEnumerable<string> Archives(string path)
    {
        if (!Directory.Exists(path)) yield break;
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            yield break;
        foreach (var file in Directory.EnumerateFiles(path).Where(file => SharedRandomizer.IsMatch(Path.GetFileName(file))))
            yield return file;
        foreach (var directory in Directory.EnumerateDirectories(path))
            foreach (var file in Archives(directory))
                yield return file;
    }

    internal void ValidateIsolation(string applicationData = null)
    {
        var content = Path.Combine(Root, Paks);
        var global = Archives(content).FirstOrDefault() ??
            Archives(Path.Combine(Root, @"ProjectPBZ\Saved\Paks")).FirstOrDefault() ??
            Archives(Path.Combine(applicationData ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                @"ProjectPBZ\Saved\Paks")).FirstOrDefault();
        if (global != null)
            throw new IOException("发现会影响所有战役的本随机器旧包。请先移出游戏 Pak 目录：" + Environment.NewLine + global);
    }

    internal static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        var slashes = 0;
        foreach (var letter in value)
        {
            if (letter == '\\') { slashes++; continue; }
            result.Append('\\', letter == '"' ? slashes * 2 + 1 : slashes);
            result.Append(letter);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }

    internal static string Arguments(CampaignInfo campaign)
    {
        var arguments = "-applaunch " + AppId;
        if (campaign != null)
            arguments += " -UserDir=" + Quote(campaign.userDir) + " -SaveGamesDir=" + Quote(campaign.savesPath);
        return arguments;
    }

    internal void ValidateLaunch(ProfileStore store, CampaignInfo campaign)
    {
        if (Running())
            throw new IOException("请先退出正在运行的《影之刃零》。");
        new PendingLaunchStore(store).RequireClear();
        ValidateIsolation();
        if (campaign == null) return;
        if (!string.Equals(BuildId, Build, StringComparison.Ordinal))
            throw new IOException("随机种子仅支持 Steam build " + Build + "。当前版本：" + BuildId);
        if (store.Fingerprint(campaign.profile.layout) != campaign.profile.fingerprint)
            throw new IOException("归档与战役绑定的布局不同。请恢复该布局后继续。");
    }

    internal bool Launch(ProfileStore store, CampaignInfo campaign)
    {
        ValidateLaunch(store, campaign);
        return new PendingLaunchStore(store).Dispatch(campaign == null ? null : campaign.profile.name, () =>
        {
            using (Process.Start(new ProcessStartInfo(Exe, Arguments(campaign))
            {
                UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(Exe)
            })) { }
        });
    }
}
