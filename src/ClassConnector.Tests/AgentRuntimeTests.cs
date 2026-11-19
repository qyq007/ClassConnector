using ClassConnector.Core.Configuration;
using ClassConnector.Core.Runtime;
using Xunit;

namespace ClassConnector.Tests;

public class AgentRuntimeTests : IDisposable
{
    private readonly string _path = Path.Combine(Path.GetTempPath(),
        "cc-rt-" + Guid.NewGuid().ToString("N") + ".json");

    public void Dispose()
    {
        try { if (File.Exists(_path)) File.Delete(_path); }
        catch (Exception) { /* temp file */ }
    }

    [Fact]
    public void Connections_AreCountedIndependently()
    {
        var runtime = new AgentRuntime(new AppConfigStore(_path));
        runtime.AddClient();
        runtime.AddStream();
        Assert.Equal(2, runtime.ActiveCount);
        runtime.RemoveStream();
        Assert.Equal(1, runtime.ActiveCount);
        runtime.RemoveClient();
        Assert.Equal(0, runtime.ActiveCount);
    }

    [Fact]
    public async Task IdleTimeout_PausesAndWakesCapture()
    {
        var store = new AppConfigStore(_path);
        var runtime = new AgentRuntime(store);
        var sleeps = 0;
        var wakes = 0;
        runtime.OnSleep = () => sleeps++;
        runtime.OnWake = () => wakes++;

        store.Update(cfg => cfg.IdleTimeoutSeconds = 0);
        runtime.CheckIdle();
        Assert.False(runtime.Sleeping);

        store.Update(cfg => cfg.IdleTimeoutSeconds = 1);
        runtime.AddClient();
        runtime.RemoveClient();
        await Task.Delay(1200);
        runtime.CheckIdle();
        Assert.True(runtime.Sleeping);
        Assert.Equal(1, sleeps);

        runtime.Touch();
        Assert.False(runtime.Sleeping);
        Assert.Equal(1, wakes);
    }

    [Fact]
    public void Logs_AreKeptAndLimited()
    {
        var runtime = new AgentRuntime(new AppConfigStore(_path));
        for (var i = 0; i < 10; i++) runtime.Log("info", $"line {i}");
        var logs = runtime.RecentLogs(3);
        Assert.Equal(3, logs.Count);
        Assert.Equal("line 9", logs[^1].message);
        Assert.Equal("info", logs[0].level);
    }
}
