using System.Collections.Concurrent;
using System.Security.Cryptography;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using ClassConnector.Core.Runtime;

namespace ClassConnector.Core.Hosting;

public sealed class BannerRecord
{
    public string id { get; set; } = "";
    public string title { get; set; } = "";
    public string markdown { get; set; } = "";
    public bool urgent { get; set; }
    public bool need_ack { get; set; }
    public bool tts { get; set; }
    public string status { get; set; } = "showing";
    public string? ack_by { get; set; }
    public double ts { get; set; }
}

/// <summary>In-memory banner history (the web UI renders and acknowledges it).</summary>
public sealed class BannerState
{
    private readonly object _sync = new();
    private readonly List<BannerRecord> _history = new();
    private BannerRecord? _current;
    private int _seq;

    public BannerRecord Send(string title, string markdown, bool urgent, bool needAck, bool tts)
    {
        var record = new BannerRecord
        {
            id = $"b{Interlocked.Increment(ref _seq)}_{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}",
            title = title,
            markdown = markdown,
            urgent = urgent,
            need_ack = needAck,
            tts = tts,
            status = "showing",
            ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
        };
        lock (_sync) { _current = record; _history.Add(record); }
        return record;
    }

    public BannerRecord? Current { get { lock (_sync) return _current; } }
    public List<BannerRecord> History(int limit) { lock (_sync) return _history.TakeLast(Math.Clamp(limit, 1, 200)).ToList(); }

    public BannerRecord? Ack(string id, string by)
    {
        lock (_sync)
        {
            var record = _history.FirstOrDefault(b => b.id == id);
            if (record is null) return null;
            record.status = "acked";
            record.ack_by = by;
            if (_current?.id == id) _current = null;
            return record;
        }
    }

    public void Dismiss(string? id, string reason)
    {
        lock (_sync)
        {
            var target = string.IsNullOrEmpty(id) ? _current : _history.FirstOrDefault(b => b.id == id);
            if (target is null) return;
            target.status = "dismissed";
            if (_current?.id == target.id) _current = null;
        }
    }
}

/// <summary>Everything the embedded web server needs, injected as one singleton.</summary>
public sealed class ServerContext
{
    private readonly ConcurrentDictionary<string, DateTime> _tokens = new();

    public required AppConfigStore Store { get; init; }
    public required CameraService Camera { get; init; }
    public required AgentRuntime Runtime { get; init; }
    public required CameraNameResolver Names { get; init; }

    /// <summary>Camera indices that the capture backend can actually open.</summary>
    public required Func<IReadOnlyList<int>> DeviceIndices { get; init; }
    public Func<int, (int Width, int Height)>? DeviceSize { get; init; }

    public Func<int>? DisplayCount { get; init; }
    public Func<int, float, (byte[] Bytes, bool Fallback, object Meta)>? ScreenCapture { get; init; }

    /// <summary>Called after a password-verified exit request from the web UI.</summary>
    public Action? RequestExit { get; init; }

    /// <summary>Windows startup-folder / Run-key integration, provided by the desktop app.</summary>
    public Func<bool>? AutoStartEnabled { get; init; }
    public Action<bool>? SetAutoStart { get; init; }

    public string Version { get; init; } = "2.0.0";
    private int _spoken;
    public int SpokenCount => Volatile.Read(ref _spoken);

    public BannerState Banner { get; } = new();

    public int CountSpeak() => Interlocked.Increment(ref _spoken);

    public string IssueToken()
    {
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
        _tokens[token] = DateTime.UtcNow.AddHours(8);
        return token;
    }

    public bool ValidToken(string? token)
    {
        if (string.IsNullOrEmpty(token)) return false;
        if (!_tokens.TryGetValue(token, out var expires)) return false;
        if (expires < DateTime.UtcNow) { _tokens.TryRemove(token, out _); return false; }
        return true;
    }

    public void RevokeTokens() => _tokens.Clear();
}
