using System.Net.Http.Json;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using Xunit;

namespace ClassConnector.Tests;

/// <summary>
/// Starts the real Kestrel service in-process and exercises the LAN API.
/// This is the regression test for "exe 无法启动服务".
/// </summary>
public class AgentServerIntegrationTests
{
    [Fact]
    public async Task Service_StartsAndAnswersHealth()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        Assert.True(agent.Host.IsRunning);
        Assert.Empty(agent.Host.LastError);

        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };
        using var doc = await client.GetFromJsonAsync<JsonDocument>("/api/health");
        Assert.NotNull(doc);
        Assert.True(doc!.RootElement.GetProperty("ok").GetBoolean());
        Assert.Equal("classconnector-agent", doc.RootElement.GetProperty("service").GetString());
        Assert.True(doc.RootElement.GetProperty("port").GetInt32() > 0);
    }

    [Fact]
    public async Task CameraDevices_Locked_OnlyExposesHostSelectedCamera()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };

        using var doc = await client.GetFromJsonAsync<JsonDocument>("/api/camera/devices");
        var root = doc!.RootElement;
        Assert.True(root.GetProperty("locked").GetBoolean());
        Assert.Equal(1, root.GetProperty("devices").GetArrayLength());
        Assert.Contains("Integrated Camera",
            root.GetProperty("devices")[0].GetProperty("name").GetString());
    }

    [Fact]
    public async Task CameraDevices_Unlocked_ListsRealNames()
    {
        using var agent = new TestAgent();
        agent.Store.Update(cfg => cfg.Camera.RemoteSelect = true);
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };

        using var doc = await client.GetFromJsonAsync<JsonDocument>("/api/camera/devices");
        var devices = doc!.RootElement.GetProperty("devices");
        Assert.False(doc.RootElement.GetProperty("locked").GetBoolean());
        Assert.Equal(2, devices.GetArrayLength());
        Assert.Equal("Integrated Camera", devices[0].GetProperty("name").GetString());
        Assert.Equal("USB HD Webcam", devices[1].GetProperty("name").GetString());
    }

    [Fact]
    public async Task CameraConfig_Locked_IgnoresIndexFromNetwork()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };

        using var response = await client.PostAsJsonAsync("/api/camera/config",
            new { index = 1, quality = 82 });
        using var doc = await response.Content.ReadFromJsonAsync<JsonDocument>();
        var root = doc!.RootElement;
        Assert.True(root.GetProperty("ok").GetBoolean());
        Assert.Equal(0, root.GetProperty("config").GetProperty("index").GetInt32());
        Assert.Equal(82, root.GetProperty("config").GetProperty("quality").GetInt32());
        Assert.Contains("index",
            root.GetProperty("ignored_fields").EnumerateArray().Select(e => e.GetString() ?? ""));
    }

    [Fact]
    public async Task MjpegStream_ProducesAFrame()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(6));

        using var response = await client.GetAsync("/api/camera/stream",
            HttpCompletionOption.ResponseHeadersRead, cts.Token);
        Assert.Contains("multipart/x-mixed-replace",
            response.Content.Headers.ContentType?.MediaType ?? "");
        await using var stream = await response.Content.ReadAsStreamAsync(cts.Token);
        var buffer = new byte[4096];
        var read = await stream.ReadAsync(buffer, cts.Token);
        Assert.True(read > 0);
        Assert.Contains("--classconnector-frame", Encoding.ASCII.GetString(buffer, 0, read));
    }

    [Fact]
    public async Task WebSocket_SendsHello()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(6));
        using var socket = new ClientWebSocket();
        await socket.ConnectAsync(new Uri($"ws://127.0.0.1:{agent.Port}/ws"), cts.Token);
        var buffer = new byte[4096];
        var result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), cts.Token);
        var text = Encoding.UTF8.GetString(buffer, 0, result.Count);
        Assert.Contains("hello", text);
        Assert.Contains("state", text);
        await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "done", cts.Token);
    }

    [Fact]
    public async Task Status_And_Snapshot_EndpointsWork()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };

        using var status = await client.GetFromJsonAsync<JsonDocument>("/api/status");
        Assert.True(status!.RootElement.GetProperty("ok").GetBoolean());
        Assert.True(status.RootElement.TryGetProperty("camera", out _));
        Assert.True(status.RootElement.TryGetProperty("capabilities", out _));

        var jpeg = await client.GetByteArrayAsync("/api/camera/snapshot");
        Assert.True(jpeg.Length > 0);
        Assert.Equal(0xFF, jpeg[0]);
        Assert.Equal(0xD8, jpeg[1]);

        var png = await client.GetByteArrayAsync("/api/screen/shot");
        Assert.Equal(0x89, png[0]);
        Assert.Equal((byte)'P', png[1]);
    }

    [Fact]
    public async Task SecondBindOnSamePort_FailsCleanly()
    {
        using var first = new TestAgent();
        Assert.True(await first.StartAsync(), first.Host.LastError);

        using var second = new TestAgent();
        // Force the same port by starting against the already-bound port.
        var ok = await second.Host.StartAsync("127.0.0.1", first.Port);
        Assert.False(ok);
        Assert.NotEmpty(second.Host.LastError);
        Assert.False(second.Host.IsRunning);
    }

    [Fact]
    public async Task QueryToken_AllowsImgTagsWhenAuthRequired()
    {
        using var agent = new TestAgent();
        agent.Store.SetPassword("test1234");
        agent.Store.Update(cfg => cfg.RequireAuth = true);
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };

        // No token -> 401 on a protected API.
        using var denied = await client.GetAsync("/api/camera/snapshot");
        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, denied.StatusCode);

        using var login = await client.PostAsJsonAsync("/api/auth", new { password = "test1234" });
        using var loginDoc = await login.Content.ReadFromJsonAsync<JsonDocument>();
        var token = loginDoc!.RootElement.GetProperty("token").GetString();
        Assert.False(string.IsNullOrEmpty(token));

        // Header auth works.
        client.DefaultRequestHeaders.Add("X-CC-Token", token);
        using var byHeader = await client.GetAsync("/api/camera/snapshot");
        Assert.Equal(System.Net.HttpStatusCode.OK, byHeader.StatusCode);

        // Query auth works too (<img src> / MJPEG cannot set headers).
        using var imageClient = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };
        using var byQuery = await imageClient.GetAsync($"/api/camera/snapshot?token={token}");
        Assert.Equal(System.Net.HttpStatusCode.OK, byQuery.StatusCode);
        using var noToken = await imageClient.GetAsync("/api/camera/snapshot");
        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, noToken.StatusCode);
    }

    [Fact]
    public async Task TtsVoices_IncludeChineseDisplayNames()
    {
        using var agent = new TestAgent();
        Assert.True(await agent.StartAsync(), agent.Host.LastError);
        using var client = new HttpClient { BaseAddress = new Uri(agent.BaseUrl) };
        using var doc = await client.GetFromJsonAsync<JsonDocument>("/api/tts/voices");
        var voices = doc!.RootElement.GetProperty("voices");
        Assert.True(voices.GetArrayLength() >= 4);
        Assert.Contains("晓晓", voices[0].GetProperty("name").GetString());
    }
}
