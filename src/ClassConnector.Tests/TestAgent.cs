using System.Net;
using System.Net.Sockets;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using ClassConnector.Core.Hosting;
using ClassConnector.Core.Runtime;

namespace ClassConnector.Tests;

internal sealed class StaticNames : ICameraNameProvider
{
    private readonly IReadOnlyList<string> _names;
    public StaticNames(IReadOnlyList<string> names) => _names = names;
    public IReadOnlyList<string> GetFriendlyNames() => _names;
}

internal sealed class CountingNames : ICameraNameProvider
{
    public int Calls;
    public IReadOnlyList<string> GetFriendlyNames()
    {
        Interlocked.Increment(ref Calls);
        return new[] { "Integrated Camera", "USB HD Webcam" };
    }
}

/// <summary>Fully working in-process agent used by the HTTP integration tests.</summary>
internal sealed class TestAgent : IDisposable
{
    public AppConfigStore Store { get; }
    public ServerContext Context { get; }
    public AgentServerHost Host { get; }
    public int Port { get; }
    public string BaseUrl => $"http://127.0.0.1:{Port}";
    private readonly string _configPath;

    public TestAgent(
        IReadOnlyList<string>? names = null,
        Func<bool>? autoStartEnabled = null,
        Action<bool>? setAutoStart = null)
    {
        _configPath = Path.Combine(Path.GetTempPath(),
            "cc-test-" + Guid.NewGuid().ToString("N") + ".json");
        Store = new AppConfigStore(_configPath);
        var list = names ?? new[] { "Integrated Camera", "USB HD Webcam" };
        var resolver = new CameraNameResolver(new StaticNames(list));
        var camera = new CameraService(Store.Snapshot().Camera);
        var runtime = new AgentRuntime(Store);
        Context = new ServerContext
        {
            Store = Store,
            Camera = camera,
            Runtime = runtime,
            Names = resolver,
            DeviceIndices = () => Enumerable.Range(0, Math.Max(1, list.Count)).ToArray(),
            DeviceSize = _ => (0, 0),
            DisplayCount = () => 1,
            Version = "2.0.0",
            AutoStartEnabled = autoStartEnabled,
            SetAutoStart = setAutoStart,
        };
        Host = new AgentServerHost(Context);
        Port = FreePort();
        Store.Update(cfg => cfg.Port = Port);
    }

    public Task<bool> StartAsync() => Host.StartAsync("127.0.0.1", Port);

    public static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    public void Dispose()
    {
        try { Host.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        catch (Exception) { /* best effort */ }
        Context.Camera.Dispose();
        try { if (File.Exists(_configPath)) File.Delete(_configPath); }
        catch (Exception) { /* temp file */ }
    }
}
