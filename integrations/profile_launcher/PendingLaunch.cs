using System;
using System.IO;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Threading;

[DataContract]
internal sealed class PendingLaunch
{
    [DataMember] public int schema = 1;
    [DataMember] public string campaign;
    [DataMember] public DateTime requestedUtc;

    internal const string Message = "启动请求已发给 Steam，但尚未观察到《影之刃零》进程启动。请处理 Steam 的启动请求。确认请求已取消，或游戏启动后已退出，再解除等待。";
}

internal sealed class PendingLaunchStore
{
    private readonly string root;
    private readonly string path;
    private readonly Func<bool> running;

    internal PendingLaunchStore(ProfileStore store, Func<bool> running = null)
    {
        root = Path.GetDirectoryName(store.Campaigns);
        path = Path.Combine(root, "pending-launch.json");
        this.running = running ?? new Func<bool>(SteamGame.Running);
    }

    internal PendingLaunch Read()
    {
        if (!Directory.Exists(root)) return null;
        ProfileStore.RejectRedirect(root);
        if (!File.Exists(path)) return null;
        ProfileStore.RejectRedirect(path);
        using (var stream = File.OpenRead(path))
        {
            if (stream.Length > 4096) throw new IOException("Steam 启动请求记录无效。");
            var value = (PendingLaunch)new DataContractJsonSerializer(typeof(PendingLaunch)).ReadObject(stream);
            if (value == null || value.schema != 1 || value.requestedUtc == DateTime.MinValue)
                throw new IOException("Steam 启动请求记录无效。");
            if (value.campaign != null) ProfileStore.Name(value.campaign);
            return value;
        }
    }

    private void Clear()
    {
        ProfileStore.RejectRedirect(path);
        File.Delete(path);
    }

    internal PendingLaunch Observe()
    {
        var pending = Read();
        if (pending == null || !running()) return pending;
        Clear();
        return null;
    }

    internal void ConfirmEnded()
    {
        if (Read() == null) return;
        if (running()) throw new IOException("请先退出《影之刃零》。");
        Clear();
    }

    internal void RequireClear(string campaign = null)
    {
        var pending = Read();
        if (pending != null && (campaign == null ||
            campaign.Equals(pending.campaign, StringComparison.OrdinalIgnoreCase)))
            throw new IOException(PendingLaunch.Message);
    }

    internal bool Dispatch(string campaign, Action request, Action wait = null)
    {
        RequireClear();
        Directory.CreateDirectory(root);
        ProfileStore.RejectRedirect(root);
        var stage = Path.Combine(root, ".pending-" + Guid.NewGuid().ToString("N"));
        try
        {
            var pending = new PendingLaunch { campaign = campaign, requestedUtc = DateTime.UtcNow };
            using (var stream = new FileStream(stage, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                new DataContractJsonSerializer(typeof(PendingLaunch)).WriteObject(stream, pending);
                stream.Flush(true);
            }
            File.Move(stage, path);
        }
        finally
        {
            if (File.Exists(stage)) File.Delete(stage);
        }
        try { request(); }
        catch { Clear(); throw; }
        if (wait == null) wait = () => Thread.Sleep(500);
        for (var i = 0; i <= 24; i++)
        {
            if (running())
            {
                Clear();
                return true;
            }
            if (i < 24) wait();
        }
        return false;
    }
}
