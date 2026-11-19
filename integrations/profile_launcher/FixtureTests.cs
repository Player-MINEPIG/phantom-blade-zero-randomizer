using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using System.Text;

internal static class FixtureTests
{
    [DllImport("kernel32.dll")] private static extern uint SetErrorMode(uint mode);

    private static void Check(bool condition, string description)
    {
        if (!condition) throw new Exception(description);
    }

    private static void Reject(Action action, string reason)
    {
        try { action(); }
        catch (Exception error)
        {
            Check(error is IOException || error is ArgumentException, "Wrong failure for " + reason + ": " + error);
            return;
        }
        throw new Exception("Unexpectedly allowed " + reason);
    }

    private static void Write(string path, string content)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllText(path, content, new UTF8Encoding(false));
    }

    private static void MakeLayout(ProfileStore store, string id, Layout data)
    {
        var root = store.SeedDirectory(id);
        var paks = Path.Combine(root, "Saved", "Paks");
        Directory.CreateDirectory(paks);
        using (var writer = File.Create(Path.Combine(root, "layout.json")))
            new DataContractJsonSerializer(typeof(Layout)).WriteObject(writer, data);
        foreach (var suffix in new[] { ".pak", ".utoc", ".ucas" })
            Write(Path.Combine(paks, "z_Fixture_P" + suffix), id + suffix);
    }

    internal static int Main(string[] args)
    {
        SetErrorMode(0x0001 | 0x0002);
        try
        {
            Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
            return Run(args);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL: " + error.Message);
            return 1;
        }
    }

    private static int Run(string[] args)
    {
        var root = Path.GetFullPath(args[0]);
        var appData = Path.Combine(root, "AppData");
        var store = new ProfileStore(root, appData);
        const string seed = "江湖 测试";
        MakeLayout(store, seed, new Layout { schema = 1, baseSeed = seed });
        MakeLayout(store, seed + "-vanilla", new Layout { schema = 1, baseSeed = seed, vanilla = true });
        Check(store.SeedNames().SequenceEqual(new[] { seed }), "Only base seeds should appear.");

        var first = store.Create("第一战役", seed);
        var second = store.Create("第二战役", seed);
        Check(!Directory.EnumerateFileSystemEntries(first.savesPath).Any(), "New campaign starts empty.");
        Check(first.savesPath != second.savesPath && first.userDir == second.userDir, "Campaigns have separate saves and share a layout.");
        Reject(() => store.Create("第一战役", seed), "duplicate campaign name");
        Reject(() => store.Create("..\\other", seed), "path traversal");
        Reject(() => store.Create("CON", seed), "reserved Windows path");
        Reject(() => store.Create("非基础布局", seed + "-vanilla"), "original-only layout as a new seed");
        Check(SteamGame.Arguments(null) == "-applaunch 4115450", "Original launch should have no game overrides.");
        Check(SteamGame.Arguments(first).Contains("-UserDir=\"" + first.userDir + "\" -SaveGamesDir=\"" + first.savesPath + "\""),
            "Flags must quote both absolute paths independently.");
        Check(SteamGame.Quote("D:\\with space\\") == "\"D:\\with space\\\\\"", "Trailing directory delimiter must remain inside the quoted argument.");

        var stock = Path.Combine(root, "Stock Fixture");
        var account = Path.Combine("Steam", "76561198000000123");
        Write(Path.Combine(stock, account, "PBZSaveGame.sav"), "main fixture");
        Write(Path.Combine(stock, account, "backup", "archive.SAV"), "backup fixture");
        Write(Path.Combine(stock, account, "settings.ini"), "not a save");
        var imported = store.ImportVanilla("导入战役", seed, stock);
        Check(imported.profile.layout == seed + "-vanilla", "Imported stock runs use the original layout.");
        Check(imported.profile.fingerprint != first.profile.fingerprint, "Original and randomized have different fingerprints.");
        Check(File.ReadAllText(Path.Combine(imported.savesPath, account, "PBZSaveGame.sav")) == "main fixture",
            "The nested main save must be copied.");
        Check(File.ReadAllText(Path.Combine(imported.savesPath, account, "backup", "archive.SAV")) == "backup fixture",
            "Nested backup saves must be copied.");
        Check(File.ReadAllText(Path.Combine(stock, account, "PBZSaveGame.sav")) == "main fixture", "Source must remain intact.");
        Check(!File.Exists(Path.Combine(imported.savesPath, account, "settings.ini")), "Only saves may be copied.");
        var accountImport = store.ImportVanilla("直接账号", seed, Path.Combine(stock, account));
        Check(File.Exists(Path.Combine(accountImport.savesPath, account, "PBZSaveGame.sav")), "Account-only import must restore the Steam hierarchy.");
        var steamImport = store.ImportVanilla("直接Steam", seed, Path.Combine(stock, "Steam"));
        Check(File.Exists(Path.Combine(steamImport.savesPath, account, "PBZSaveGame.sav")), "Steam folder import must restore the hierarchy.");
        Reject(() => store.ImportVanilla("仅备份", seed, Path.Combine(stock, account, "backup")), "backup without primary account save");
        Reject(() => store.ImportVanilla("交叠", seed, second.savesPath), "overlapping save trees");
        var empty = Path.Combine(root, "Empty Source");
        Directory.CreateDirectory(empty);
        Reject(() => store.ImportVanilla("没有存档", seed, empty), "an empty import");
        Check(!store.CampaignNames().Contains("没有存档"), "A failed import must be unpublished.");

        var derived = new Layout
        {
            schema = 1, baseSeed = seed, campaign = first.profile.name,
            parentLayout = first.profile.layout, parentFingerprint = first.profile.fingerprint
        };
        MakeLayout(store, "WrongCampaign", new Layout
        {
            schema = 1, baseSeed = seed, campaign = second.profile.name,
            parentLayout = first.profile.layout, parentFingerprint = first.profile.fingerprint
        });
        MakeLayout(store, "WrongParent", new Layout
        {
            schema = 1, baseSeed = seed, campaign = first.profile.name,
            parentLayout = "Other", parentFingerprint = first.profile.fingerprint
        });
        MakeLayout(store, "新布局", derived);
        Reject(() => store.SwitchLayout(first.profile.name, seed), "base seed as a replacement layout");
        Reject(() => store.SwitchLayout(first.profile.name, "WrongCampaign"), "different campaign with matching fingerprint");
        Reject(() => store.SwitchLayout(first.profile.name, "WrongParent"), "different previous layout with matching fingerprint");
        Write(Path.Combine(first.savesPath, "untouched.sav"), "active fixture");
        var switched = store.SwitchLayout(first.profile.name, "新布局");
        Check(switched.savesPath == first.savesPath && switched.profile.seed == seed && switched.profile.layout == "新布局",
            "Switching must only change the layout binding.");
        Check(File.ReadAllText(Path.Combine(switched.savesPath, "untouched.sav")) == "active fixture", "Switch must preserve saves.");
        Reject(() => store.SwitchLayout(first.profile.name, "新布局"), "stale derived layout");

        var steam = Path.Combine(root, "Steam Fixture", "steam.exe");
        var library = Path.Combine(root, "Other Steam Library");
        var game = Path.Combine(library, "steamapps", "common", "PBZ Fixture");
        var paks = Path.Combine(game, "ProjectPBZ", "Content", "Paks");
        Write(steam, "executable marker");
        Write(Path.Combine(Path.GetDirectoryName(steam), "steamapps", "libraryfolders.vdf"),
            "\"libraryfolders\" { \"1\" { \"path\" \"" + library.Replace("\\", "\\\\") + "\" } }");
        Write(Path.Combine(library, "steamapps", "appmanifest_4115450.acf"),
            "\"AppState\" { \"installdir\" \"PBZ Fixture\" \"buildid\" \"26367565\" }");
        Write(Path.Combine(paks, "ProjectPBZ-Windows.pak"), "stock");
        Write(Path.Combine(paks, "ProjectPBZ-Windows_s65.ucas"), "stock");
        Write(Path.Combine(paks, "pakchunkMoviesUIAlphaMp4-Windows.utoc"), "stock");
        var candidate = SteamGame.Find(steam, game);
        Reject(() => SteamGame.Find(steam, root), "game path differing from Steam manifest");
        Check(candidate.Root == game && candidate.BuildId == "26367565", "Find the correct Steam library and game.");
        candidate.ValidateIsolation(appData);
        Write(Path.Combine(paks, "~mods", "CustomArmor.pak"), "unrelated installed mod");
        candidate.ValidateIsolation(appData);
        var old = Path.Combine(paks, "~mods", "z_PBZSeedRandomizer_P.pak");
        Write(old, "shared static version");
        Reject(() => candidate.ValidateIsolation(appData), "shared legacy Pak");
        File.Delete(old);
        var defaultUserPak = Path.Combine(appData, "ProjectPBZ", "Saved", "Paks", "z_PBZSlotExtras_2_P.utoc");
        Write(defaultUserPak, "shared default user version");
        Reject(() => candidate.ValidateIsolation(appData), "shared default UserDir Pak");
        var requests = 0;
        var waits = 0;
        var observed = false;
        var launch = new PendingLaunchStore(store, () => observed);
        Check(!launch.Dispatch(first.profile.name, () => requests++, () => waits++), "Unobserved Steam request must return pending.");
        Check(requests == 1 && waits == 24, "Waiting is bounded and submits one Steam request.");
        var anotherInstance = new PendingLaunchStore(new ProfileStore(root, appData), () => observed);
        Check(anotherInstance.Read().campaign == first.profile.name, "A different launcher instance sees the same pending request.");
        Reject(() => anotherInstance.RequireClear(), "a second Steam request while pending");
        Reject(() => store.SwitchLayout(first.profile.name, "新布局"), "a layout switch during that campaign's pending launch");
        anotherInstance.RequireClear(second.profile.name);
        Reject(() => store.ImportVanilla("待请求", seed, stock), "copying while Steam can still start the game");
        anotherInstance.ConfirmEnded();
        Check(launch.Read() == null, "Explicit confirmation clears the pending Steam request.");
        Check(launch.Dispatch(null, () => requests++, () => observed = true), "An observed game process resolves the request.");
        Check(launch.Read() == null, "An observed launch leaves no pending record.");
        observed = false;
        Reject(() => launch.Dispatch(null, () => { throw new IOException("fake dispatch failure"); }, () => { }),
            "submission failure");
        Check(launch.Read() == null, "Steam submission exceptions clear the pending record.");
        Check(!launch.Dispatch(null, () => {}, () => {}), "The stock entry can also be pending.");
        observed = true;
        Reject(anotherInstance.ConfirmEnded, "confirming an ended request while the game is running");
        Check(anotherInstance.Observe() == null, "A later observation also clears the persistent request.");
        Directory.CreateDirectory(Path.Combine(store.Campaigns, "未发布战役"));
        Check(!store.CampaignNames().Contains("未发布战役"), "Unpublished directories should not appear as campaigns.");
        File.Move(second.metadataPath, Path.Combine(Path.GetDirectoryName(second.metadataPath), "archived.json"));
        Check(!store.CampaignNames().Contains(second.profile.name) && Directory.Exists(second.savesPath),
            "Archiving metadata hides the campaign while retaining its saves.");
        Console.WriteLine("PASS: isolated campaigns, save import, layout switching, Steam discovery, bounded pending launches and launch safeguards.");
        return 0;
    }
}
