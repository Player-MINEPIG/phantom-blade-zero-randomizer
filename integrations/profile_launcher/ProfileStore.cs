using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

[DataContract]
internal sealed class Campaign
{
    [DataMember] public int schema = 1;
    [DataMember] public string name;
    [DataMember] public string seed;
    [DataMember] public string layout;
    [DataMember] public string fingerprint;
}

[DataContract]
internal sealed class CampaignInfo
{
    [DataMember] public Campaign profile;
    [DataMember] public string metadataPath;
    [DataMember] public string savesPath;
    [DataMember] public string userDir;
}

[DataContract]
internal sealed class Layout
{
    [DataMember] public int schema { get; set; }
    [DataMember] public string baseSeed { get; set; }
    [DataMember] public string parentFingerprint { get; set; }
    [DataMember] public string parentLayout { get; set; }
    [DataMember] public string campaign { get; set; }
    [DataMember] public bool vanilla { get; set; }
}

internal sealed class ProfileStore
{
    internal readonly string Seeds;
    internal readonly string Campaigns;

    internal ProfileStore(string launcherDirectory, string applicationData)
    {
        Seeds = Path.GetFullPath(Path.Combine(launcherDirectory, "Seeds"));
        Campaigns = Path.GetFullPath(Path.Combine(applicationData, "PBZSeedRandomizer", "Campaigns"));
    }

    internal static string Name(string value)
    {
        if (value == null || value != value.Trim() ||
            !Regex.IsMatch(value, @"\A[\p{L}\p{N}][\p{L}\p{M}\p{N} _-]{0,59}\z") ||
            Regex.IsMatch(value, @"\A(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])\z",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            throw new ArgumentException("名称可使用汉字、字母、数字、空格、下划线或短横线，最多 60 字。");
        return value;
    }

    internal static bool IsArchive(string path)
    {
        var suffix = Path.GetExtension(path).ToLowerInvariant();
        return suffix == ".pak" || suffix == ".utoc" || suffix == ".ucas";
    }

    internal static void RejectRedirect(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("路径必须是实际文件或目录，不能是链接：" + path);
    }

    private static void ExistingDirectory(string path)
    {
        if (!Directory.Exists(path))
            throw new DirectoryNotFoundException("找不到目录：" + path);
        RejectRedirect(path);
    }

    private static string[] NamesIn(string root)
    {
        if (!Directory.Exists(root))
            return new string[0];
        RejectRedirect(root);
        return Directory.EnumerateDirectories(root).Select(Path.GetFileName).Where(name =>
        {
            try { return Name(name) == name; }
            catch (ArgumentException) { return false; }
        }).OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase).ToArray();
    }

    internal string[] SeedNames()
    {
        return NamesIn(Seeds).Where(seed =>
        {
            try
            {
                var layout = ReadLayout(seed);
                return !layout.vanilla && IsInitial(layout) &&
                    layout.baseSeed.Equals(seed, StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception error)
            {
                if (error is IOException || error is SerializationException || error is ArgumentException)
                    return false;
                throw;
            }
        }).ToArray();
    }

    internal string[] CampaignNames()
    {
        if (Directory.Exists(Campaigns))
            RejectRedirect(Path.GetDirectoryName(Campaigns));
        return NamesIn(Campaigns).Where(name =>
        {
            var directory = Path.Combine(Campaigns, name);
            var metadata = Path.Combine(directory, "campaign.json");
            var saves = Path.Combine(directory, "Saves");
            return IsLocalEntry(directory) && File.Exists(metadata) && IsLocalEntry(metadata) &&
                Directory.Exists(saves) && IsLocalEntry(saves);
        }).ToArray();
    }

    private static bool IsLocalEntry(string path)
    {
        return (File.Exists(path) || Directory.Exists(path)) &&
            (File.GetAttributes(path) & FileAttributes.ReparsePoint) == 0;
    }

    internal string SeedDirectory(string name)
    {
        return Path.Combine(Seeds, Name(name));
    }

    private Layout ReadLayout(string name)
    {
        var directory = SeedDirectory(name);
        ExistingDirectory(Seeds);
        ExistingDirectory(directory);
        var metadata = Path.Combine(directory, "layout.json");
        if (!File.Exists(metadata))
            throw new IOException("种子缺少 layout.json：" + name);
        RejectRedirect(metadata);
        Layout value;
        using (var stream = File.OpenRead(metadata))
        {
            if (stream.Length > 4096)
                throw new IOException("布局元数据过大：" + metadata);
            value = (Layout)new DataContractJsonSerializer(typeof(Layout)).ReadObject(stream);
        }
        if (value == null || value.schema != 1)
            throw new IOException("布局元数据无效：" + metadata);
        Name(value.baseSeed);
        if (value.parentFingerprint != null && !Regex.IsMatch(value.parentFingerprint, @"\A[a-f0-9]{64}\z"))
            throw new IOException("布局的上一个指纹无效：" + metadata);
        return value;
    }

    internal string Fingerprint(string name)
    {
        var seed = SeedDirectory(name);
        var saved = Path.Combine(seed, "Saved");
        var paks = Path.Combine(saved, "Paks");
        foreach (var directory in new[] { Seeds, seed, saved, paks })
            ExistingDirectory(directory);
        var subdirs = Directory.GetDirectories(paks);
        if (subdirs.Length != 0)
            throw new IOException("种子 Saved/Paks 内应直接放置一套归档：" + paks);
        var files = Directory.GetFiles(paks).Where(IsArchive).ToArray();
        var ordered = new[] { ".pak", ".utoc", ".ucas" }.Select(extension =>
            files.SingleOrDefault(file => Path.GetExtension(file).Equals(extension, StringComparison.OrdinalIgnoreCase)))
            .ToArray();
        if (files.Length != 3 || ordered.Any(file => file == null) ||
            files.Select(Path.GetFileNameWithoutExtension).Distinct(StringComparer.OrdinalIgnoreCase).Count() != 1)
            throw new IOException("种子必须包含文件名一致的 .pak、.utoc、.ucas 三件套：" + paks);
        var digests = new StringBuilder();
        using (var sha = SHA256.Create())
        {
            foreach (var file in ordered)
            {
                RejectRedirect(file);
                using (var stream = File.OpenRead(file))
                {
                    if (stream.Length == 0)
                        throw new IOException("归档文件为空：" + file);
                    digests.Append(Path.GetFileName(file).ToLowerInvariant()).Append(' ')
                        .Append(Hex(sha.ComputeHash(stream))).Append('\n');
                }
            }
            return Hex(sha.ComputeHash(Encoding.UTF8.GetBytes(digests.ToString())));
        }
    }

    private static string Hex(byte[] bytes)
    {
        return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
    }

    internal CampaignInfo Read(string name)
    {
        var directory = Path.Combine(Campaigns, Name(name));
        var saves = Path.Combine(directory, "Saves");
        foreach (var item in new[] { Path.GetDirectoryName(Campaigns), Campaigns, directory, saves })
            ExistingDirectory(item);
        var metadata = Path.Combine(directory, "campaign.json");
        RejectRedirect(metadata);
        Campaign campaign;
        using (var stream = File.OpenRead(metadata))
        {
            if (stream.Length > 4096)
                throw new IOException("战役元数据过大：" + metadata);
            campaign = (Campaign)new DataContractJsonSerializer(typeof(Campaign)).ReadObject(stream);
        }
        if (campaign == null || campaign.schema != 1 ||
            !Name(campaign.name).Equals(name, StringComparison.OrdinalIgnoreCase) ||
            campaign.fingerprint == null || !Regex.IsMatch(campaign.fingerprint, @"\A[a-f0-9]{64}\z"))
            throw new IOException("战役元数据无效：" + metadata);
        Name(campaign.seed);
        return new CampaignInfo
        {
            profile = campaign, metadataPath = metadata, savesPath = saves,
            userDir = SeedDirectory(campaign.layout)
        };
    }

    internal CampaignInfo Create(string name, string seed)
    {
        RequireBaseSeed(seed);
        return Publish(new Campaign { name = Name(name), seed = seed, layout = seed, fingerprint = Fingerprint(seed) }, null);
    }

    private static bool IsInitial(Layout layout)
    {
        return layout.parentFingerprint == null && layout.parentLayout == null && layout.campaign == null;
    }

    private void RequireBaseSeed(string seed)
    {
        var layout = ReadLayout(seed);
        if (layout.vanilla || !IsInitial(layout) || !layout.baseSeed.Equals(seed, StringComparison.OrdinalIgnoreCase))
            throw new IOException("新战役必须使用完整的初始种子。");
    }

    private static bool ContainsPath(string directory, string path)
    {
        var normalized = directory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        return path.Equals(normalized, StringComparison.OrdinalIgnoreCase) ||
            path.StartsWith(normalized + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    internal static string NormalizeDirectory(string path)
    {
        var full = Path.GetFullPath(path);
        return full.Length == Path.GetPathRoot(full).Length
            ? full : full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    internal CampaignInfo ImportVanilla(string name, string seed, string source)
    {
        if (SteamGame.Running())
            throw new IOException("请退出游戏后再复制存档。");
        new PendingLaunchStore(this).RequireClear();
        Name(name);
        RequireBaseSeed(seed);
        source = NormalizeDirectory(source);
        if (ContainsPath(Campaigns, source) || ContainsPath(source, Campaigns))
            throw new IOException("原版存档目录与战役目录必须相互独立。");
        for (var directory = new DirectoryInfo(source); directory != null; directory = directory.Parent)
            ExistingDirectory(directory.FullName);
        var folderName = Path.GetFileName(source);
        string prefix;
        if (IsSteamSaveAccount(source))
            prefix = Path.Combine("Steam", folderName);
        else if (folderName.Equals("Steam", StringComparison.OrdinalIgnoreCase) && ContainsSteamSaveAccount(source))
            prefix = "Steam";
        else if (ContainsSteamSaveAccount(Path.Combine(source, "Steam")))
            prefix = "";
        else
            throw new IOException("请选择原版 SaveGames 目录、其中的 Steam 目录，或直接包含 PBZSaveGame.sav 的 17 位 Steam 账号目录。");
        var vanilla = seed + "-vanilla";
        var layout = ReadLayout(vanilla);
        if (!layout.vanilla || !IsInitial(layout) || !layout.baseSeed.Equals(seed, StringComparison.OrdinalIgnoreCase))
            throw new IOException("找不到与所选种子配套的初始原版布局。");
        var profile = new Campaign { name = name, seed = seed, layout = vanilla, fingerprint = Fingerprint(vanilla) };
        return Publish(profile, saves =>
        {
            if (CopySaves(source, Path.Combine(saves, prefix)) == 0)
                throw new IOException("所选目录中没有 .sav 文件。");
        });
    }

    private static bool IsSteamSaveAccount(string source)
    {
        return Regex.IsMatch(Path.GetFileName(source), @"\A[0-9]{17}\z") &&
            File.Exists(Path.Combine(source, "PBZSaveGame.sav"));
    }

    private static bool ContainsSteamSaveAccount(string source)
    {
        if (!Directory.Exists(source)) return false;
        RejectRedirect(source);
        return Directory.EnumerateDirectories(source).Any(IsSteamSaveAccount);
    }

    private static int CopySaves(string source, string target)
    {
        ExistingDirectory(source);
        var count = 0;
        foreach (var file in Directory.EnumerateFiles(source))
        {
            RejectRedirect(file);
            if (!Path.GetExtension(file).Equals(".sav", StringComparison.OrdinalIgnoreCase)) continue;
            Directory.CreateDirectory(target);
            File.Copy(file, Path.Combine(target, Path.GetFileName(file)));
            count++;
        }
        foreach (var child in Directory.EnumerateDirectories(source))
            count += CopySaves(child, Path.Combine(target, Path.GetFileName(child)));
        return count;
    }

    private CampaignInfo Publish(Campaign campaign, Action<string> populate)
    {
        var name = campaign.name;
        var target = Path.Combine(Campaigns, name);
        if (Directory.Exists(target) || File.Exists(target))
            throw new IOException("战役已存在。请使用新名称。");
        var root = Path.GetDirectoryName(Campaigns);
        Directory.CreateDirectory(root);
        RejectRedirect(root);
        Directory.CreateDirectory(Campaigns);
        RejectRedirect(Campaigns);
        var stage = Path.Combine(Campaigns, ".create-" + Guid.NewGuid().ToString("N"));
        var writes = Path.Combine(stage, "campaign.json");
        var saves = Path.Combine(stage, "Saves");
        try
        {
            Directory.CreateDirectory(saves);
            if (populate != null) populate(saves);
            Write(writes, campaign);
            Directory.Move(stage, target);
        }
        finally
        {
            if (Directory.Exists(stage) && Path.GetDirectoryName(Path.GetFullPath(stage)) == Campaigns)
            {
                RejectRedirect(stage);
                Directory.Delete(stage, true);
            }
        }
        return Read(name);
    }

    internal CampaignInfo SwitchLayout(string name, string layout)
    {
        new PendingLaunchStore(this).RequireClear(Name(name));
        var info = Read(name);
        var target = ReadLayout(layout);
        if (!target.baseSeed.Equals(info.profile.seed, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(target.parentLayout, info.profile.layout, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(target.campaign, info.profile.name, StringComparison.OrdinalIgnoreCase) ||
            target.parentFingerprint != info.profile.fingerprint)
            throw new IOException("目标布局必须根据本战役的当前布局生成。");
        if (Fingerprint(info.profile.layout) != info.profile.fingerprint)
            throw new IOException("当前布局归档已修改，恢复当前布局后再切换。");
        info.profile.layout = Name(layout);
        info.profile.fingerprint = Fingerprint(layout);
        var stage = Path.Combine(Path.GetDirectoryName(info.metadataPath), ".layout-" + Guid.NewGuid().ToString("N"));
        try
        {
            Write(stage, info.profile);
            File.Replace(stage, info.metadataPath, null);
        }
        finally
        {
            if (File.Exists(stage)) File.Delete(stage);
        }
        return Read(name);
    }

    private static void Write(string path, Campaign value)
    {
        using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            new DataContractJsonSerializer(typeof(Campaign)).WriteObject(stream, value);
            stream.Flush(true);
        }
    }
}
