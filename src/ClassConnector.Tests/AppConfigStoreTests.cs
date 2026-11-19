using System.Text.Json;
using ClassConnector.Core.Configuration;
using Xunit;

namespace ClassConnector.Tests;

public class AppConfigStoreTests : IDisposable
{
    private readonly string _path = Path.Combine(Path.GetTempPath(),
        "cc-cfg-" + Guid.NewGuid().ToString("N") + ".json");

    public void Dispose()
    {
        try { if (File.Exists(_path)) File.Delete(_path); }
        catch (Exception) { /* temp file */ }
    }

    [Fact]
    public void Defaults_AreSafeAndPortIs8420()
    {
        var store = new AppConfigStore(_path);
        Assert.Equal(8420, store.Snapshot().Port);
        Assert.Equal("0.0.0.0", store.Snapshot().Host);
        Assert.False(store.Snapshot().Camera.RemoteSelect);
        Assert.False(store.HasPassword);
        Assert.True(File.Exists(_path));
    }

    [Fact]
    public void Password_IsPbkdf2Hashed_NeverPlaintext()
    {
        var store = new AppConfigStore(_path);
        store.SetPassword("MySecretPass!2024");
        Assert.True(store.HasPassword);
        Assert.True(store.VerifyPassword("MySecretPass!2024"));
        Assert.False(store.VerifyPassword("wrong-password"));
        Assert.False(store.VerifyPassword(null));

        var raw = File.ReadAllText(_path);
        Assert.DoesNotContain("MySecretPass!2024", raw);
        Assert.Contains("PasswordSalt", raw);
        Assert.Contains("PasswordHash", raw);
    }

    [Fact]
    public void Password_SurvivesReload()
    {
        new AppConfigStore(_path).SetPassword("abcd1234");
        var reloaded = new AppConfigStore(_path);
        Assert.True(reloaded.HasPassword);
        Assert.True(reloaded.VerifyPassword("abcd1234"));
    }

    [Fact]
    public void Public_RemovesAllSecretFields()
    {
        var store = new AppConfigStore(_path);
        store.SetPassword("abcd1234");
        var json = JsonSerializer.Serialize(store.Public());
        Assert.DoesNotContain("password_salt", json);
        Assert.DoesNotContain("password_hash", json);
        Assert.Contains("has_password", json);
        Assert.Contains("camera", json);
    }

    [Fact]
    public void Update_ClampsOutOfRangeValues()
    {
        var store = new AppConfigStore(_path);
        store.Update(cfg =>
        {
            cfg.Port = 99999;
            cfg.Camera.Quality = 500;
            cfg.Camera.Index = -3;
            cfg.IdleTimeoutSeconds = -1;
        });
        var cfg = store.Snapshot();
        Assert.Equal(65535, cfg.Port);
        Assert.Equal(100, cfg.Camera.Quality);
        Assert.Equal(0, cfg.Camera.Index);
        Assert.Equal(0, cfg.IdleTimeoutSeconds);
    }

    [Fact]
    public void BlankOrMalformedHost_NormalizesToAllInterfaces()
    {
        File.WriteAllText(_path, "{\"Host\":\"\"}");
        var store = new AppConfigStore(_path);
        Assert.Equal("0.0.0.0", store.Snapshot().Host);

        File.WriteAllText(_path, "{\"Host\":\"http://192.168.1.9:8420/manager\"}");
        store = new AppConfigStore(_path);
        Assert.Equal("192.168.1.9", store.Snapshot().Host);

        // Legacy loopback config must not silently disable LAN access.
        File.WriteAllText(_path, "{\"Host\":\"127.0.0.1\"}");
        store = new AppConfigStore(_path);
        Assert.Equal("0.0.0.0", store.Snapshot().Host);
    }

    [Fact]
    public void CorruptedConfig_FallsBackToDefaults()
    {
        File.WriteAllText(_path, "{ this is not json");
        var store = new AppConfigStore(_path);
        Assert.Equal(8420, store.Snapshot().Port);
    }
}
