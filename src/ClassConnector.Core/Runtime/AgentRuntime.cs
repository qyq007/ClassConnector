using System.Collections.Concurrent;
using System.Diagnostics;
using ClassConnector.Core.Configuration;

namespace ClassConnector.Core.Runtime;

public sealed class LogEntry
{
    public double ts { get; set; }
    public string level { get; set; } = "info";
    public string message { get; set; } = "";
}

/// <summary>Connection counters, idle sleep/wake and the in-memory log ring.</summary>
public sealed class AgentRuntime
{
    private const int MaxLogs = 300;
    private readonly AppConfigStore _store;
    private readonly ConcurrentQueue<LogEntry> _logs = new();
    private readonly object _sync = new();
    private readonly long _startedAt = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    private int _clients;
    private int _streams;
    private long _lastActive = Stopwatch.GetTimestamp();

    public AgentRuntime(AppConfigStore store) => _store = store;

    public bool Sleeping { get; private set; }
    public Action? OnSleep { get; set; }
    public Action? OnWake { get; set; }

    public int ActiveCount { get { lock (_sync) return _clients + _streams; } }

    public void Touch()
    {
        Interlocked.Exchange(ref _lastActive, Stopwatch.GetTimestamp());
        if (Sleeping)
        {
            Sleeping = false;
            OnWake?.Invoke();
            Log("info", "管理端接入，采集已唤醒");
        }
    }

    public void AddClient() { lock (_sync) _clients++; Touch(); Log("info", $"管理端接入（当前 {ActiveCount} 路）"); }
    public void RemoveClient() { lock (_sync) _clients = Math.Max(0, _clients - 1); Interlocked.Exchange(ref _lastActive, Stopwatch.GetTimestamp()); }
    public void AddStream() { lock (_sync) _streams++; Touch(); }
    public void RemoveStream() { lock (_sync) _streams = Math.Max(0, _streams - 1); Interlocked.Exchange(ref _lastActive, Stopwatch.GetTimestamp()); }

    public void CheckIdle()
    {
        var timeout = _store.Snapshot().IdleTimeoutSeconds;
        if (timeout <= 0 || Sleeping || ActiveCount != 0) return;
        var elapsed = (Stopwatch.GetTimestamp() - Interlocked.Read(ref _lastActive))
                      / (double)Stopwatch.Frequency;
        if (elapsed < timeout) return;
        Sleeping = true;
        OnSleep?.Invoke();
        Log("info", "无管理端连接，采集端进入休眠");
    }

    public void Log(string level, string message)
    {
        _logs.Enqueue(new LogEntry
        {
            ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
            level = level,
            message = message,
        });
        while (_logs.Count > MaxLogs && _logs.TryDequeue(out _)) { }
    }

    public List<LogEntry> RecentLogs(int limit)
    {
        var all = _logs.ToArray();
        return all.Skip(Math.Max(0, all.Length - Math.Clamp(limit, 1, 500))).ToList();
    }

    public object Snapshot()
    {
        lock (_sync)
        {
            return new
            {
                active = _clients + _streams,
                clients = _clients,
                streams = _streams,
                sleeping = Sleeping,
                talk_mode = false,
                uptime = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - _startedAt,
            };
        }
    }
}
