using System.Diagnostics;
using System.Threading.Channels;
using ClassConnector.Core.Configuration;
using ClassConnector.Core.Imaging;

namespace ClassConnector.Core.Camera;

/// <summary>A capture backend. Implemented by .App with OpenCV on Windows.</summary>
public interface ICameraFrameSource : IDisposable
{
    bool Open(CameraConfig config);
    byte[]? ReadJpeg(int quality);
    (int Width, int Height) Size { get; }

    /// <summary>False when the source is producing a test pattern instead of a real device.</summary>
    bool IsRealDevice { get; }
}

/// <summary>
/// Single capture loop + fan-out to every watching browser. Falls back to a
/// built-in test image when no device is available, so the LAN manager always
/// has a live MJPEG stream (instead of failing to start the whole service).
/// </summary>
public sealed class CameraService : IDisposable
{
    private readonly object _sync = new();
    private readonly List<Channel<byte[]>> _subscribers = new();
    private readonly Func<CameraConfig, ICameraFrameSource>? _factory;
    private readonly CancellationTokenSource _cts = new();
    private readonly Task _loop;

    private ICameraFrameSource? _source;   // owned by the loop thread only
    private bool _sourceFailed;
    private bool _reload = true;
    private volatile bool _paused;
    private byte[] _lastJpeg = PlaceholderImages.JpegBytes;
    private CameraConfig _config;
    private long _frames;
    private double _measuredFps;
    private string _backend = "test-pattern";
    private string _lastError = "";

    public CameraService(CameraConfig config, Func<CameraConfig, ICameraFrameSource>? factory = null)
    {
        _config = config.Clone();
        _factory = factory;
        _loop = Task.Run(async () => await LoopAsync(_cts.Token));
    }

    private CameraConfig CurrentConfig
    {
        get { lock (_sync) return _config.Clone(); }
    }

    public void ApplyConfig(CameraConfig config)
    {
        lock (_sync)
        {
            _config = config.Clone();
            _reload = true;      // loop thread will release + reopen the device
        }
        Resume();
    }

    public void Pause() => _paused = true;
    public void Resume() => _paused = false;

    public byte[] Snapshot()
    {
        Resume();
        lock (_sync) return _lastJpeg;
    }

    public (ChannelReader<byte[]> Reader, Action Unsubscribe) Subscribe()
    {
        var channel = Channel.CreateUnbounded<byte[]>(new UnboundedChannelOptions
        {
            SingleReader = true,
            SingleWriter = false,
            AllowSynchronousContinuations = false,
        });
        lock (_sync) _subscribers.Add(channel);
        return (channel.Reader, () =>
        {
            lock (_sync) _subscribers.Remove(channel);
            channel.Writer.TryComplete();
        });
    }

    private void Publish(byte[] jpeg)
    {
        Channel<byte[]>[] targets;
        lock (_sync) targets = _subscribers.ToArray();
        foreach (var channel in targets)
        {
            try { channel.Writer.TryWrite(jpeg); }
            catch (ChannelClosedException) { /* client went away */ }
        }
    }

    public CameraStatusView Status()
    {
        var cfg = CurrentConfig;
        int subs;
        long frames;
        string error, backend;
        double fps;
        lock (_sync)
        {
            subs = _subscribers.Count;
            frames = Interlocked.Read(ref _frames);
            error = _lastError;
            backend = _backend;
            fps = _measuredFps;
        }
        return new CameraStatusView
        {
            backend = backend,
            available = backend == "opencv",
            device_index = cfg.Index,
            width = cfg.Width,
            height = cfg.Height,
            fps = cfg.Fps,
            quality = cfg.Quality,
            measured_fps = Math.Round(fps, 1),
            frames = frames,
            subscribers = subs,
            paused = _paused,
            last_error = error,
            camera_select_locked = !cfg.RemoteSelect,
        };
    }

    private async Task LoopAsync(CancellationToken ct)
    {
        var stopwatch = Stopwatch.StartNew();
        var windowStart = stopwatch.Elapsed;
        var windowFrames = 0;

        while (!ct.IsCancellationRequested)
        {
            if (_paused)
            {
                if (!await Delay(200, ct)) break;
                continue;
            }

            var cfg = CurrentConfig;
            byte[]? jpeg = null;
            try
            {
                EnsureSource(cfg);
                if (_source is not null) jpeg = _source.ReadJpeg(cfg.Quality);
            }
            catch (Exception ex)
            {
                _lastError = $"读取摄像头失败：{ex.Message}";
                ReleaseSource();
                _sourceFailed = true;
            }

            if (jpeg is null || jpeg.Length == 0)
            {
                jpeg = PlaceholderImages.JpegBytes;
                _backend = "test-pattern";
            }
            else _backend = (_source is not null && _source.IsRealDevice) ? "opencv" : "test-pattern";

            lock (_sync) _lastJpeg = jpeg;
            Interlocked.Increment(ref _frames);
            Publish(jpeg);

            windowFrames++;
            var now = stopwatch.Elapsed;
            if (now - windowStart >= TimeSpan.FromSeconds(1))
            {
                _measuredFps = windowFrames / (now - windowStart).TotalSeconds;
                windowStart = now;
                windowFrames = 0;
            }

            if (!await Delay(Math.Max(33, 1000 / Math.Clamp(cfg.Fps, 1, 30)), ct)) break;
        }
        ReleaseSource();
    }

    private static async Task<bool> Delay(int ms, CancellationToken ct)
    {
        try { await Task.Delay(ms, ct); return true; }
        catch (OperationCanceledException) { return false; }
    }

    private void EnsureSource(CameraConfig cfg)
    {
        if (_reload)
        {
            _reload = false;
            ReleaseSource();
            _sourceFailed = false;
        }
        if (_source is not null || _sourceFailed) return;
        if (_factory is null)
        {
            _sourceFailed = true;
            _lastError = "摄像头采集组件未加载，正在使用测试画面";
            return;
        }
        try
        {
            var source = _factory(cfg);
            if (source.Open(cfg))
            {
                _source = source;
                _lastError = "";
            }
            else
            {
                source.Dispose();
                _sourceFailed = true;
                _lastError = $"摄像头 {cfg.Index} 不可用，正在使用测试画面";
            }
        }
        catch (Exception ex)
        {
            _sourceFailed = true;
            _lastError = $"打开摄像头失败：{ex.Message}";
        }
    }

    private void ReleaseSource()
    {
        var source = _source;
        _source = null;
        try { source?.Dispose(); } catch (Exception) { /* device already gone */ }
    }

    public void Dispose()
    {
        _cts.Cancel();
        try { _loop.Wait(TimeSpan.FromSeconds(3)); } catch (Exception) { /* shutting down */ }
        _cts.Dispose();
        lock (_sync)
        {
            foreach (var channel in _subscribers) channel.Writer.TryComplete();
            _subscribers.Clear();
        }
    }
}
