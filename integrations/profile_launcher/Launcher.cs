using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class Launcher
{
    internal const string Title = "影之刃零 · 随机战役";
    private const string LockName = @"Local\PBZSeedRandomizer.CampaignLauncher";

    [DllImport("kernel32.dll")] private static extern bool AttachConsole(int parent);
    [DllImport("kernel32.dll")] private static extern IntPtr GetStdHandle(int number);

    internal static T Exclusive<T>(Func<T> action)
    {
        using (var gate = new Mutex(false, LockName))
        {
            var held = false;
            try
            {
                try { held = gate.WaitOne(0); }
                catch (AbandonedMutexException) { held = true; }
                if (!held) throw new IOException("另一窗口正在启动游戏或更新战役，请稍后再试。");
                return action();
            }
            finally { if (held) gate.ReleaseMutex(); }
        }
    }

    private static void Json(object value)
    {
        var output = Console.OpenStandardOutput();
        new DataContractJsonSerializer(value.GetType()).WriteObject(output, value);
        output.WriteByte(10);
        output.Flush();
    }

    [STAThread]
    internal static int Main(string[] args)
    {
        var isCli = args.Length > 0;
        try
        {
            if (isCli && (GetStdHandle(-11) == IntPtr.Zero || GetStdHandle(-11) == new IntPtr(-1)))
                AttachConsole(-1);
            if (isCli)
            {
                var utf8 = new UTF8Encoding(false);
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), utf8) { AutoFlush = true });
                Console.SetError(new StreamWriter(Console.OpenStandardError(), utf8) { AutoFlush = true });
            }
            var root = AppDomain.CurrentDomain.BaseDirectory;
            var store = new ProfileStore(root, Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData));
            string steam = null, game = null;
            var command = new List<string>();
            for (var i = 0; i < args.Length; i++)
            {
                if (args[i] == "--steam" || args[i] == "--game")
                {
                    var option = args[i];
                    if (++i == args.Length) throw new ArgumentException(option + " 需要路径。");
                    if (option == "--steam") steam = args[i]; else game = args[i];
                }
                else command.Add(args[i]);
            }
            if (command.Count > 0)
                return Command(store, steam, game, command);
            isCli = false;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new CampaignWindow(root, store, SteamGame.Find(steam, game)));
            return 0;
        }
        catch (Exception error)
        {
            if (isCli) Console.Error.WriteLine(error.Message);
            else MessageBox.Show(error.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    private static int Command(ProfileStore store, string steam, string game, List<string> args)
    {
        if (args[0] == "--help" && args.Count == 1)
        {
            Console.WriteLine("PBZRandomizer.exe [--steam PATH] [--game PATH]");
            Console.WriteLine("  --list | --profile-info NAME | --layout-fingerprint LAYOUT");
            Console.WriteLine("  --create NAME BASE_SEED | --switch-layout NAME LAYOUT");
            Console.WriteLine("  --import-vanilla NAME BASE_SEED SOURCE_DIRECTORY");
            Console.WriteLine("  --dry-run [NAME] | --launch [NAME]");
            Console.WriteLine("  --pending | --confirm-launch-ended");
            return 0;
        }
        if (args[0] == "--list" && args.Count == 1)
        {
            foreach (var seed in store.SeedNames()) Console.WriteLine("seed\t" + seed);
            foreach (var campaign in store.CampaignNames()) Console.WriteLine("campaign\t" + campaign);
            return 0;
        }
        if (args[0] == "--profile-info" && args.Count == 2)
        {
            Json(store.Read(args[1]));
            return 0;
        }
        if (args[0] == "--layout-fingerprint" && args.Count == 2)
        {
            Console.WriteLine(store.Fingerprint(args[1]));
            return 0;
        }
        if (args[0] == "--pending" && args.Count == 1)
        {
            var pending = Exclusive(() => new PendingLaunchStore(store).Observe());
            if (pending == null) Console.WriteLine("null"); else Json(pending);
            return 0;
        }
        if (args[0] == "--confirm-launch-ended" && args.Count == 1)
        {
            return Exclusive(() =>
            {
                new PendingLaunchStore(store).ConfirmEnded();
                return 0;
            });
        }
        if (args[0] == "--create" && args.Count == 3)
        {
            Json(Exclusive(() => store.Create(args[1], args[2])));
            return 0;
        }
        if (args[0] == "--import-vanilla" && args.Count == 4)
        {
            Json(Exclusive(() => store.ImportVanilla(args[1], args[2], args[3])));
            return 0;
        }
        if (args[0] == "--switch-layout" && args.Count == 3)
        {
            Json(Exclusive(() =>
            {
                if (SteamGame.Running()) throw new IOException("请退出游戏后再切换布局。");
                return store.SwitchLayout(args[1], args[2]);
            }));
            return 0;
        }
        if ((args[0] == "--launch" || args[0] == "--dry-run") && args.Count <= 2)
        {
            var steamGame = SteamGame.Find(steam, game);
            return Exclusive(() =>
            {
                var info = args.Count == 2 ? store.Read(args[1]) : null;
                if (args[0] == "--dry-run")
                {
                    steamGame.ValidateLaunch(store, info);
                    Console.WriteLine(steamGame.Exe);
                    Console.WriteLine(SteamGame.Arguments(info));
                }
                else if (!steamGame.Launch(store, info))
                {
                    Console.Error.WriteLine(PendingLaunch.Message + " 确认请求结束后可使用 --confirm-launch-ended。");
                    return 2;
                }
                else Console.WriteLine("已观察到《影之刃零》进程启动。");
                return 0;
            });
        }
        throw new ArgumentException("参数无效。用 --help 查看可用命令。");
    }

    internal static void OpenSwitchTool(string root, ProfileStore store, string name)
    {
        if (SteamGame.Running()) throw new IOException("请退出游戏后再切换布局。");
        Exclusive(() =>
        {
            new PendingLaunchStore(store).RequireClear(name);
            return 0;
        });
        var script = Path.Combine(root, "Tools", "switch_mode.pyw");
        if (!File.Exists(script)) throw new IOException("找不到 Tools\\switch_mode.pyw，请检查压缩包是否完整。");
        var python = Path.Combine(root, "Tools", "Python", "pythonw.exe");
        if (!File.Exists(python))
        {
            python = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator)
                .Where(directory => !string.IsNullOrWhiteSpace(directory))
                .Select(directory => Path.Combine(directory.Trim('"'), "pythonw.exe"))
                .FirstOrDefault(File.Exists);
        }
        if (python == null)
            throw new IOException("找不到包内的 Tools\\Python\\pythonw.exe。开发环境可将 Python 3.10 或更高版本的 pythonw.exe 加入 PATH。");
        var launch = new ProcessStartInfo(python, "-E -s " + SteamGame.Quote(script) + " " + SteamGame.Quote(name))
        {
            UseShellExecute = false, WorkingDirectory = root
        };
        foreach (var variable in new[] { "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY" })
            launch.EnvironmentVariables.Remove(variable);
        using (Process.Start(launch)) { }
    }
}

internal sealed class CampaignWindow : Form
{
    private readonly string root;
    private readonly ProfileStore store;
    private readonly SteamGame game;
    private readonly ListBox campaigns = new ListBox();
    private readonly ComboBox seeds = new ComboBox();
    private readonly TextBox campaignName = new TextBox();
    private readonly Label status = new Label();
    private readonly Button resume;
    private readonly Button switchMode;
    private readonly Button original;
    private readonly Button create;
    private readonly Button import;
    private readonly Button clearPending;
    private PendingLaunch pending;
    private bool busy;

    internal CampaignWindow(string root, ProfileStore store, SteamGame game)
    {
        this.root = root;
        this.store = store;
        this.game = game;
        Text = Launcher.Title;
        ClientSize = new Size(640, 465);
        MinimumSize = new Size(590, 455);
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(249, 247, 242);
        ForeColor = Color.FromArgb(34, 34, 31);
        Font = new Font("Microsoft YaHei UI", 10);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7, Padding = new Padding(20) };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 27));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 47));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 35));
        Controls.Add(layout);
        var heading = Label("影之刃零随机战役");
        heading.Font = new Font(Font.FontFamily, 17, FontStyle.Bold);
        layout.Controls.Add(heading);
        layout.Controls.Add(Label("已有战役"));
        campaigns.Dock = DockStyle.Fill;
        campaigns.AccessibleName = "已有战役";
        campaigns.SelectedIndexChanged += (s, e) => UpdateButtons();
        campaigns.DoubleClick += (s, e) => { if (resume.Enabled) resume.PerformClick(); };
        layout.Controls.Add(campaigns);
        var actions = Row();
        resume = Button("继续战役", () => Launch(Selected));
        switchMode = Button("切换此战役模式…", () => Run(() => Launcher.OpenSwitchTool(root, store, Selected)));
        original = Button("启动原版", () => Launch(null));
        clearPending = Button("确认 Steam 请求已结束…", ConfirmPendingEnded);
        actions.Controls.AddRange(new Control[] { resume, switchMode, original, clearPending });
        layout.Controls.Add(actions);
        layout.Controls.Add(Label("新战役名称与初始种子"));
        var creation = Row();
        campaignName.Width = 135;
        campaignName.MaxLength = 60;
        campaignName.AccessibleName = "新战役名称";
        campaignName.TextChanged += (s, e) => UpdateButtons();
        seeds.Width = 143;
        seeds.AccessibleName = "初始种子";
        seeds.DropDownStyle = ComboBoxStyle.DropDownList;
        seeds.SelectedIndexChanged += (s, e) => UpdateButtons();
        create = Button("新建空档战役", Create);
        import = Button("导入原版档库…", Import);
        creation.Controls.AddRange(new Control[] { campaignName, seeds, create, import });
        layout.Controls.Add(creation);
        status.Dock = DockStyle.Fill;
        status.AutoEllipsis = true;
        status.TextAlign = ContentAlignment.MiddleLeft;
        layout.Controls.Add(status);
        RefreshLists(null);
        SetStatus("Steam build " + game.BuildId + "。启动原版会使用游戏现有存档。");
        RefreshPending();
        var timer = new System.Windows.Forms.Timer { Interval = 1000 };
        timer.Tick += (s, e) =>
        {
            if (busy) return;
            try { RefreshPending(); }
            catch (Exception error) { SetStatus(error.Message); }
        };
        timer.Start();
        FormClosed += (s, e) => timer.Dispose();
    }

    private string Selected { get { return campaigns.SelectedItem as string; } }

    private static Label Label(string text)
    {
        return new Label { Text = text, TextAlign = ContentAlignment.MiddleLeft, Dock = DockStyle.Fill };
    }

    private static FlowLayoutPanel Row()
    {
        return new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false, FlowDirection = FlowDirection.LeftToRight };
    }

    private static Button Button(string text, Action action)
    {
        var button = new Button { Text = text, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Height = 35, Padding = new Padding(4, 2, 4, 2) };
        button.Click += (s, e) => action();
        return button;
    }

    private void RefreshLists(string selected)
    {
        campaigns.Items.Clear();
        campaigns.Items.AddRange(store.CampaignNames());
        if (selected != null) campaigns.SelectedItem = selected;
        if (campaigns.SelectedIndex < 0 && campaigns.Items.Count > 0) campaigns.SelectedIndex = 0;
        seeds.Items.Clear();
        seeds.Items.AddRange(store.SeedNames());
        if (seeds.Items.Count > 0) seeds.SelectedIndex = 0;
        UpdateButtons();
    }

    private void UpdateButtons()
    {
        if (create == null) return;
        resume.Enabled = !busy && Selected != null && pending == null;
        switchMode.Enabled = !busy && Selected != null &&
            (pending == null || !string.Equals(pending.campaign, Selected, StringComparison.OrdinalIgnoreCase));
        original.Enabled = !busy && pending == null;
        create.Enabled = !busy && seeds.SelectedItem != null && campaignName.TextLength > 0;
        import.Enabled = create.Enabled && pending == null;
        clearPending.Visible = pending != null;
        clearPending.Enabled = !busy;
    }

    private void SetStatus(string message)
    {
        status.Text = message;
    }

    private void RefreshPending()
    {
        var previous = pending;
        var status = new PendingLaunchStore(store);
        pending = status.Read();
        if (pending != null && SteamGame.Running())
        {
            try { pending = Launcher.Exclusive(status.Observe); }
            catch (IOException) { return; }
            if (pending == null) SetStatus("已观察到《影之刃零》进程启动。");
        }
        else if (previous == null && pending != null)
            SetStatus(PendingLaunch.Message);
        else if (previous != null && pending == null)
            SetStatus("Steam 启动等待已解除。");
        UpdateButtons();
    }

    private void ConfirmPendingEnded()
    {
        if (pending == null) return;
        if (MessageBox.Show(this, "请先处理并关闭 Steam 的启动提示。确认请求已取消，或《影之刃零》启动后已退出，再继续。",
            Launcher.Title, MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK) return;
        Run(() =>
        {
            Launcher.Exclusive(() =>
            {
                new PendingLaunchStore(store).ConfirmEnded();
                return 0;
            });
            RefreshPending();
        });
    }

    private void Run(Action action)
    {
        try { action(); }
        catch (Exception error) { MessageBox.Show(this, error.Message, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private void Create()
    {
        var name = campaignName.Text.Trim();
        var seed = (string)seeds.SelectedItem;
        Publish(name, () => store.Create(name, seed),
            "空档战役已创建。选「继续战役」，在游戏内开始新游戏。");
    }

    private void Import()
    {
        var name = campaignName.Text.Trim();
        var seed = (string)seeds.SelectedItem;
        using (var folder = new FolderBrowserDialog
        {
            Description = "选择 SaveGames、Steam 或包含 PBZSaveGame.sav 的 17 位 Steam 账号目录。",
            ShowNewFolderButton = false
        })
        {
            if (folder.ShowDialog(this) != DialogResult.OK) return;
            var source = folder.SelectedPath;
            Publish(name, () => store.ImportVanilla(name, seed, source),
                "原版档库副本已创建。打开此战役并选定一个游戏槽继续。");
        }
    }

    private async void Publish(string name, Func<CampaignInfo> createCampaign, string success)
    {
        busy = true;
        UpdateButtons();
        SetStatus("正在准备战役…");
        try
        {
            await Task.Run(() => Launcher.Exclusive(createCampaign));
            RefreshLists(name);
            campaignName.Clear();
            SetStatus(success);
        }
        catch (Exception error)
        {
            SetStatus(error.Message);
            MessageBox.Show(this, error.Message, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { busy = false; UpdateButtons(); }
    }

    private async void Launch(string name)
    {
        busy = true;
        UpdateButtons();
        SetStatus("正在检查隔离并请求 Steam 启动…");
        try
        {
            var started = await Task.Run(() => Launcher.Exclusive(() =>
                game.Launch(store, name == null ? null : store.Read(name))));
            if (started)
                SetStatus("已观察到《影之刃零》进程启动。");
            else
                MessageBox.Show(this, PendingLaunch.Message, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception error)
        {
            SetStatus(error.Message);
            MessageBox.Show(this, error.Message, Launcher.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { busy = false; Run(RefreshPending); UpdateButtons(); }
    }
}
