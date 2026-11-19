using System.Text.RegularExpressions;

namespace ClassConnector.Core.Camera;

/// <summary>Supplies OS-level friendly camera names, in device-index order.</summary>
public interface ICameraNameProvider
{
    IReadOnlyList<string> GetFriendlyNames();
}

public sealed class EmptyCameraNameProvider : ICameraNameProvider
{
    public IReadOnlyList<string> GetFriendlyNames() => Array.Empty<string>();
}

/// <summary>
/// Caches provider results. WMI / VFW enumeration can take a second or two;
/// the settings window and the /api/camera/devices endpoint must stay snappy.
/// </summary>
public sealed class CachedCameraNameProvider : ICameraNameProvider
{
    private readonly ICameraNameProvider _inner;
    private readonly TimeSpan _ttl;
    private readonly object _sync = new();
    private IReadOnlyList<string> _cache = Array.Empty<string>();
    private DateTime _loadedAt = DateTime.MinValue;

    public CachedCameraNameProvider(ICameraNameProvider inner, TimeSpan? ttl = null)
    {
        _inner = inner;
        _ttl = ttl ?? TimeSpan.FromSeconds(10);
    }

    public void Invalidate()
    {
        lock (_sync) _loadedAt = DateTime.MinValue;
    }

    public IReadOnlyList<string> GetFriendlyNames()
    {
        lock (_sync)
        {
            if (DateTime.UtcNow - _loadedAt < _ttl) return _cache;
            try { _cache = _inner.GetFriendlyNames() ?? Array.Empty<string>(); }
            catch (Exception) { _cache = Array.Empty<string>(); }
            _loadedAt = DateTime.UtcNow;
            return _cache;
        }
    }
}

/// <summary>
/// Turns a list of friendly names into per-index labels. This is the piece that
/// fixes "camera page only shows 摄像头 0/1/2": real names are shown whenever
/// the OS provides them, with a readable fallback otherwise.
/// </summary>
public sealed class CameraNameResolver
{
    private readonly ICameraNameProvider _provider;

    public CameraNameResolver(ICameraNameProvider? provider = null)
    {
        _provider = provider ?? new EmptyCameraNameProvider();
    }

    public static string Clean(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return "";
        var text = raw.Replace("\0", "").Trim();
        text = Regex.Replace(text, @"[\r\n\t]+", " ");
        text = Regex.Replace(text, @"\s{2,}", " ");
        // WMI sometimes appends "USB Video Device" duplicates or trailing punctuation.
        text = text.Trim(' ', '-', ',', ';');
        return text.Length > 120 ? text[..120] : text;
    }

    public string NameFor(int index)
    {
        var names = _provider.GetFriendlyNames();
        if (index >= 0 && index < names.Count)
        {
            var friendly = Clean(names[index]);
            if (!string.IsNullOrWhiteSpace(friendly)) return friendly;
        }
        return $"摄像头 {index}";
    }

    public static string LabelFor(CameraDevice device)
        => $"{device.name}（设备 {device.index}）";

    /// <summary>
    /// Full list for the local settings window. <paramref name="indices"/> are
    /// indices that were actually opened successfully by the capture backend.
    /// </summary>
    public List<CameraDevice> BuildLocalDevices(
        IEnumerable<int> indices,
        Func<int, (int Width, int Height)>? sizeOf = null)
    {
        var result = new List<CameraDevice>();
        var counts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var index in indices)
        {
            var name = NameFor(index);
            // Two identical webcams must still be distinguishable in the ComboBox.
            if (counts.TryGetValue(name, out var seenCount))
            {
                counts[name] = seenCount + 1;
                name = $"{name} #{seenCount + 1}";
            }
            else counts[name] = 1;
            var size = sizeOf?.Invoke(index) ?? (0, 0);
            result.Add(new CameraDevice
            {
                index = index,
                name = name,
                width = size.Width,
                height = size.Height,
            });
        }
        if (result.Count == 0)
            result.Add(new CameraDevice { index = -1, name = "测试画面（未检测到摄像头）" });
        return result;
    }

    /// <summary>
    /// View for the web manager. When locked, only the host-selected device is
    /// returned (with its real name), never the whole machine's camera list.
    /// </summary>
    public CameraDevicesView BuildRemoteView(
        int currentIndex,
        IEnumerable<int> indices,
        Func<int, (int Width, int Height)>? sizeOf = null,
        bool remoteSelectAllowed = false)
    {
        if (!remoteSelectAllowed)
        {
            return new CameraDevicesView
            {
                locked = true,
                current = currentIndex,
                devices = new List<CameraDevice>
                {
                    new()
                    {
                        index = currentIndex,
                        name = $"主机指定的摄像头：{NameFor(currentIndex)}",
                        width = 0,
                        height = 0,
                    },
                },
            };
        }
        return new CameraDevicesView
        {
            locked = false,
            current = currentIndex,
            devices = BuildLocalDevices(indices, sizeOf),
        };
    }
}
