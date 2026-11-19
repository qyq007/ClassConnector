namespace ClassConnector.Core.Configuration;

public sealed class CameraConfig
{
    public int Index { get; set; } = 0;
    public int Width { get; set; } = 1280;
    public int Height { get; set; } = 720;
    public int Fps { get; set; } = 15;
    public int Quality { get; set; } = 70;

    /// <summary>
    /// Host-only privilege: when false, the web manager may only use the device
    /// selected in the desktop settings window and cannot enumerate others.
    /// </summary>
    public bool RemoteSelect { get; set; } = false;

    public CameraConfig Clone() => (CameraConfig)MemberwiseClone();
}

public sealed class AudioConfig
{
    public bool Enabled { get; set; } = true;
    public int SampleRate { get; set; } = 16000;
    public int Chunk { get; set; } = 1024;
}

public sealed class BannerConfig
{
    public int AutoClose { get; set; } = 0;
    public bool NeedAckDefault { get; set; } = true;
    public bool TtsDefault { get; set; } = true;
}

public sealed class TtsConfig
{
    public bool Enabled { get; set; } = true;
    public string Voice { get; set; } = "zh-CN-XiaoxiaoNeural";
    public string Rate { get; set; } = "+0%";
    public string Volume { get; set; } = "+0%";
    public bool UrgentAlert { get; set; } = true;
}

public sealed class AppConfig
{
    public int Version { get; set; } = 1;
    public string Host { get; set; } = "0.0.0.0";
    public int Port { get; set; } = 8420;
    public string RoomName { get; set; } = "未命名班级";
    public string DeviceName { get; set; } = "";
    public string PasswordSalt { get; set; } = "";
    public string PasswordHash { get; set; } = "";
    public bool RequireAuth { get; set; } = false;
    public int IdleTimeoutSeconds { get; set; } = 20;

    /// <summary>Start with only the tray icon visible (headless background mode).</summary>
    public bool StartMinimized { get; set; } = false;

    public CameraConfig Camera { get; set; } = new();
    public AudioConfig Audio { get; set; } = new();
    public BannerConfig Banner { get; set; } = new();
    public TtsConfig Tts { get; set; } = new();
    public string LogLevel { get; set; } = "INFO";

    public static AppConfig CreateDefault() => new();

    /// <summary>
    /// A blank or malformed listen host must never produce "http://:port",
    /// which makes Kestrel fail to bind and the LAN service silently disappear.
    /// </summary>
    public static string NormalizeHost(string? host)
    {
        if (string.IsNullOrWhiteSpace(host)) return "0.0.0.0";
        var value = host.Trim();
        if (value.StartsWith("http://", StringComparison.OrdinalIgnoreCase))
            value = value[7..].Split('/')[0];
        if (value.Contains(':')) value = value[..value.IndexOf(':')];
        if (string.IsNullOrWhiteSpace(value)) return "0.0.0.0";
        // This is a classroom agent: a leftover loopback-only value would make
        // the LAN manager unreachable, which defeats the whole product.
        if (value is "127.0.0.1" or "localhost" or "::1") return "0.0.0.0";
        return value;
    }

    public static readonly string[] Resolutions = { "320x240", "640x480", "1280x720", "1920x1080" };
    public static readonly int[] FpsChoices = { 5, 10, 15, 20, 25, 30 };

    public static readonly (string Id, string Name)[] TtsVoices =
    {
        ("zh-CN-XiaoxiaoNeural", "晓晓（女声）"),
        ("zh-CN-YunxiNeural", "云希（男声）"),
        ("zh-CN-YunjianNeural", "云健（男声·播报）"),
        ("zh-CN-XiaoyiNeural", "晓伊（女声）"),
        ("zh-CN-liaoning-XiaobeiNeural", "晓北（东北话）"),
        ("zh-CN-shaanxi-XiaoniNeural", "晓妮（陕西话）"),
        ("zh-TW-HsiaoChenNeural", "曉臻（中国台湾）"),
        ("zh-HK-HiuMaanNeural", "曉曼（中国香港）"),
    };
}
