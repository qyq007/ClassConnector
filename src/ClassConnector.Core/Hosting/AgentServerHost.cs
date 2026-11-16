using ClassConnector.Core.Configuration;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.Hosting;

namespace ClassConnector.Core.Hosting;

/// <summary>
/// Owns the embedded Kestrel host. Unlike a fire-and-forget thread, StartAsync
/// awaits the real bind and then performs an HTTP health probe, so the desktop
/// UI can never claim "running" while the service is actually dead.
/// </summary>
public sealed class AgentServerHost : IAsyncDisposable
{
    private readonly ServerContext _context;
    private WebApplication? _app;
    private Task? _shutdownTask;
    private CancellationTokenSource? _idleCts;
    private Task? _idleTask;
    private volatile bool _stopping;

    public AgentServerHost(ServerContext context) => _context = context;

    public string LastError { get; private set; } = "";
    public string Url { get; private set; } = "";
    public string BindAddress { get; private set; } = "";
    public bool IsRunning => _app is not null && !_stopping && string.IsNullOrEmpty(LastError)
                             && !(_shutdownTask?.IsCompleted ?? false);

    public async Task<bool> StartAsync(string host, int port, CancellationToken ct = default)
    {
        await StopAsync();
        LastError = "";
        _stopping = false;
        var listenHost = AppConfig.NormalizeHost(host);
        BindAddress = $"{listenHost}:{port}";
        Url = $"http://{listenHost}:{port}";

        try
        {
            _app = AgentServer.CreateApp(_context, listenHost, port);
            await _app.StartAsync(ct);              // throws e.g. when the port is occupied
            _shutdownTask = _app.WaitForShutdownAsync(ct);
            StartIdleWatch(ct);

            var probeHost = host is "0.0.0.0" or "*" or "+" ? "127.0.0.1" : host;
            if (!await ProbeAsync(probeHost, port, ct))
            {
                await StopAsync();
                LastError = "服务已绑定端口，但本机健康检查未通过";
                _context.Runtime.Log("error", LastError);
                return false;
            }
            _context.Runtime.Log("info", $"采集端服务可访问：{Url}");
            return true;
        }
        catch (Exception ex)
        {
            await StopAsync();
            LastError = $"服务启动失败：{ex.Message}";
            _context.Runtime.Log("error", LastError);
            return false;
        }
    }

    private async Task<bool> ProbeAsync(string host, int port, CancellationToken ct)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        for (var attempt = 0; attempt < 12; attempt++)
        {
            try
            {
                using var response = await client.GetAsync($"http://{host}:{port}/api/health", ct);
                if (response.IsSuccessStatusCode) return true;
            }
            catch (Exception) { /* Kestrel may still be warming up */ }
            try { await Task.Delay(200, ct); }
            catch (OperationCanceledException) { return false; }
        }
        return false;
    }

    private void StartIdleWatch(CancellationToken ct)
    {
        _idleCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var token = _idleCts.Token;
        _idleTask = Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try { _context.Runtime.CheckIdle(); }
                catch (Exception) { /* watchdog must survive */ }
                try { await Task.Delay(1000, token); }
                catch (OperationCanceledException) { break; }
            }
        }, token);
    }

    public async Task StopAsync()
    {
        _stopping = true;
        try { _idleCts?.Cancel(); } catch (Exception) { /* already cancelled */ }
        if (_app is not null)
        {
            try { await _app.StopAsync(); } catch (Exception) { /* host already gone */ }
            try
            {
                if (_shutdownTask is not null)
                    await _shutdownTask.WaitAsync(TimeSpan.FromSeconds(3));
            }
            catch (Exception) { /* shutdown task may throw on abrupt stop */ }
            try { await _app.DisposeAsync(); } catch (Exception) { /* best effort */ }
        }
        _app = null;
        _shutdownTask = null;
        _idleTask = null;
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _idleCts?.Dispose();
        _idleCts = null;
    }
}
