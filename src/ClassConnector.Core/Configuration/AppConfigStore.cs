using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace ClassConnector.Core.Configuration;

/// <summary>
/// Thread-safe JSON config store with PBKDF2-HMAC-SHA256 password hashing.
/// The plaintext password and the hash are never returned by <see cref="Public"/>.
/// </summary>
public sealed class AppConfigStore
{
    private const int Iterations = 200_000;
    private readonly object _sync = new();
    private readonly string _path;
    private AppConfig _config;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        PropertyNameCaseInsensitive = true,
    };

    public AppConfigStore(string? path = null)
    {
        _path = path ?? AppPaths.ConfigFile;
        _config = Load();
    }

    public string Path => _path;

    private AppConfig Load()
    {
        try
        {
            if (File.Exists(_path))
            {
                var cfg = JsonSerializer.Deserialize<AppConfig>(
                    File.ReadAllText(_path, Encoding.UTF8), JsonOptions);
                if (cfg is not null)
                {
                    Normalize(cfg);
                    return cfg;
                }
            }
        }
        catch (Exception)
        {
            // Corrupted config: fall back to safe defaults, never crash startup.
        }
        var fresh = AppConfig.CreateDefault();
        SaveInternal(fresh);
        return fresh;
    }

    private static void Normalize(AppConfig c)
    {
        c.Camera ??= new CameraConfig();
        c.Audio ??= new AudioConfig();
        c.Banner ??= new BannerConfig();
        c.Tts ??= new TtsConfig();
        c.Port = Math.Clamp(c.Port, 1, 65535);
        c.IdleTimeoutSeconds = Math.Clamp(c.IdleTimeoutSeconds, 0, 3600);
        c.Camera.Index = Math.Clamp(c.Camera.Index, 0, 15);
        c.Camera.Width = Math.Clamp(c.Camera.Width, 320, 3840);
        c.Camera.Height = Math.Clamp(c.Camera.Height, 240, 2160);
        c.Camera.Fps = Math.Clamp(c.Camera.Fps, 1, 30);
        c.Camera.Quality = Math.Clamp(c.Camera.Quality, 10, 100);
        c.RoomName ??= "未命名班级";
        c.Host = AppConfig.NormalizeHost(c.Host);
        c.DeviceName ??= "";
    }

    /// <summary>Returns a detached copy; safe to read without locking.</summary>
    public AppConfig Snapshot()
    {
        lock (_sync)
            return JsonSerializer.Deserialize<AppConfig>(
                JsonSerializer.Serialize(_config, JsonOptions), JsonOptions)!;
    }

    public void Update(Action<AppConfig> mutate)
    {
        lock (_sync)
        {
            mutate(_config);
            Normalize(_config);
            SaveInternal(_config);
        }
    }

    public void Save()
    {
        lock (_sync) SaveInternal(_config);
    }

    private void SaveInternal(AppConfig cfg)
    {
        var dir = System.IO.Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        var tmp = _path + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(cfg, JsonOptions), new UTF8Encoding(false));
        File.Move(tmp, _path, true);
    }

    // ---------------------------------------------------------------- password
    public bool HasPassword
    {
        get { lock (_sync) return !string.IsNullOrEmpty(_config.PasswordSalt) && !string.IsNullOrEmpty(_config.PasswordHash); }
    }

    public static string HashPassword(string password, string saltHex)
    {
        var salt = Convert.FromHexString(saltHex);
        var hash = Rfc2898DeriveBytes.Pbkdf2(
            Encoding.UTF8.GetBytes(password), salt, Iterations,
            HashAlgorithmName.SHA256, 32);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public void SetPassword(string password)
    {
        if (password.Length < 4) throw new ArgumentException("密码至少 4 位", nameof(password));
        var salt = RandomNumberGenerator.GetBytes(16);
        var saltHex = Convert.ToHexString(salt).ToLowerInvariant();
        Update(c =>
        {
            c.PasswordSalt = saltHex;
            c.PasswordHash = HashPassword(password, saltHex);
        });
    }

    public bool VerifyPassword(string? password)
    {
        if (string.IsNullOrEmpty(password)) return false;
        string salt, expected;
        lock (_sync) { salt = _config.PasswordSalt; expected = _config.PasswordHash; }
        if (string.IsNullOrEmpty(salt) || string.IsNullOrEmpty(expected)) return false;
        try
        {
            var actual = Convert.FromHexString(HashPassword(password, salt));
            var want = Convert.FromHexString(expected);
            return CryptographicOperations.FixedTimeEquals(actual, want);
        }
        catch (Exception) { return false; }
    }

    /// <summary>Config safe to hand to the web manager (secrets removed).</summary>
    public object Public()
    {
        var c = Snapshot();
        return new
        {
            version = c.Version,
            host = c.Host,
            port = c.Port,
            room_name = c.RoomName,
            device_name = string.IsNullOrEmpty(c.DeviceName) ? Environment.MachineName : c.DeviceName,
            require_auth = c.RequireAuth,
            has_password = HasPassword,
            idle_timeout = c.IdleTimeoutSeconds,
            start_minimized = c.StartMinimized,
            camera = new
            {
                index = c.Camera.Index, width = c.Camera.Width, height = c.Camera.Height,
                fps = c.Camera.Fps, quality = c.Camera.Quality,
                remote_select = c.Camera.RemoteSelect,
            },
            audio = new { enabled = c.Audio.Enabled, sample_rate = c.Audio.SampleRate, chunk = c.Audio.Chunk },
            banner = new { auto_close = c.Banner.AutoClose, need_ack_default = c.Banner.NeedAckDefault, tts_default = c.Banner.TtsDefault },
            tts = new { enabled = c.Tts.Enabled, voice = c.Tts.Voice, rate = c.Tts.Rate, volume = c.Tts.Volume, urgent_alert = c.Tts.UrgentAlert },
            log_level = c.LogLevel,
        };
    }
}
