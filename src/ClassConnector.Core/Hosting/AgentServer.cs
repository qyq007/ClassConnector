using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using System.Text.RegularExpressions;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using ClassConnector.Core.Imaging;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace ClassConnector.Core.Hosting;

/// <summary>
/// The whole LAN service: Kestrel + REST + MJPEG + WebSocket + static manager UI,
/// all hosted inside the desktop process. No Python, no uvicorn, no console.
/// </summary>
public static class AgentServer
{
    private const string Boundary = "classconnector-frame";

    public static WebApplication CreateApp(ServerContext context, string host, int port)
    {
        var builder = WebApplication.CreateBuilder(new WebApplicationOptions
        {
            Args = Array.Empty<string>(),
            ContentRootPath = AppPaths.BaseDirectory,
        });

        // A WinExe has no console. Never attach console loggers; write to file.
        builder.Logging.ClearProviders();
        builder.Logging.AddProvider(new FileLoggerProvider(AppPaths.LogFile));
        builder.Logging.SetMinimumLevel(LogLevel.Information);
        // UseUrls wins over ASPNETCORE_URLS / launch profiles. Normalizing the
        // host prevents "http://:port" (blank host) from killing the bind.
        builder.WebHost.UseUrls($"http://{AppConfig.NormalizeHost(host)}:{port}");
        builder.Services.AddSingleton(context);

        var manager = AppPaths.ManagerDirectory;
        if (Directory.Exists(manager)) builder.Environment.WebRootPath = manager;

        var app = builder.Build();
        app.Lifetime.ApplicationStarted.Register(() =>
            context.Runtime.Log("info", $"采集端服务已启动，监听 {host}:{port}"));

        // CORS + optional token auth for the manager UI.
        app.Use(async (http, next) =>
        {
            http.Response.Headers["Access-Control-Allow-Origin"] = "*";
            http.Response.Headers["Access-Control-Allow-Methods"] = "*";
            http.Response.Headers["Access-Control-Allow-Headers"] = "*";
            http.Response.Headers["Access-Control-Expose-Headers"] = "X-CC-Fallback, X-CC-Meta, Content-Disposition";
            if (http.Request.Method == HttpMethods.Options)
            {
                http.Response.StatusCode = 204;
                return;
            }
            var path = http.Request.Path.Value ?? "";
            var isPublic = path.StartsWith("/api/health", StringComparison.OrdinalIgnoreCase)
                        || path.StartsWith("/api/auth", StringComparison.OrdinalIgnoreCase)
                        || path.StartsWith("/api/tts/voices", StringComparison.OrdinalIgnoreCase);
            if (path.StartsWith("/api/", StringComparison.OrdinalIgnoreCase)
                && !isPublic
                && context.Store.Snapshot().RequireAuth)
            {
                // <img src> / MJPEG cannot set headers, so the manager UI passes
                // ?token=... - support both, matching the v1.x wire format.
                var token = http.Request.Headers["X-CC-Token"].ToString();
                if (string.IsNullOrEmpty(token)) token = http.Request.Query["token"].ToString();
                if (!context.ValidToken(token))
                {
                    http.Response.StatusCode = 401;
                    await http.Response.WriteAsJsonAsync(new { detail = "需要管理密码登录" });
                    return;
                }
            }
            await next();
        });

        app.UseWebSockets(new WebSocketOptions { KeepAliveInterval = TimeSpan.FromSeconds(20) });
        if (Directory.Exists(manager))
        {
            app.UseDefaultFiles();
            app.UseStaticFiles();
        }

        MapApis(app, context);
        // Only register the SPA fallback when the manager files really exist;
        // unit-test hosts have no wwwroot and must still serve the API.
        if (Directory.Exists(manager)) app.MapFallbackToFile("index.html");
        return app;
    }

    private static void MapApis(WebApplication app, ServerContext c)
    {
        // ------------------------------------------------------------ basics
        app.MapGet("/api/health", (ServerContext ctx) =>
        {
            var cfg = ctx.Store.Snapshot();
            return new
            {
                ok = true,
                service = "classconnector-agent",
                version = ctx.Version,
                name = string.IsNullOrEmpty(cfg.DeviceName) ? Environment.MachineName : cfg.DeviceName,
                room = cfg.RoomName,
                ip = ApiHelpers.GetLocalIp(),
                port = cfg.Port,
                host = AppConfig.NormalizeHost(cfg.Host),
                bind = $"{AppConfig.NormalizeHost(cfg.Host)}:{cfg.Port}",
                lan_urls = ApiHelpers.LanUrls(cfg.Port),
                sleeping = ctx.Runtime.Sleeping,
                auth_required = cfg.RequireAuth,
                has_password = ctx.Store.HasPassword,
                time = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
            };
        });

        app.MapGet("/api/status", (ServerContext ctx) =>
        {
            var cfg = ctx.Store.Snapshot();
            var cam = ctx.Camera.Status();
            return new
            {
                ok = true,
                version = ctx.Version,
                device = new
                {
                    name = string.IsNullOrEmpty(cfg.DeviceName) ? Environment.MachineName : cfg.DeviceName,
                    hostname = Environment.MachineName,
                    room = cfg.RoomName,
                    ip = ApiHelpers.GetLocalIp(),
                    port = cfg.Port,
                    bind = $"{AppConfig.NormalizeHost(cfg.Host)}:{cfg.Port}",
                    lan_urls = ApiHelpers.LanUrls(cfg.Port),
                    system = Environment.OSVersion.VersionString,
                    os = Environment.OSVersion.Platform.ToString(),
                    runtime = ".NET 8",
                },
                runtime = ctx.Runtime.Snapshot(),
                camera = cam,
                audio = new { available = false, enabled = cfg.Audio.Enabled, sample_rate = cfg.Audio.SampleRate, talk_mode = false },
                screen = new { displays = ApiHelpers.Displays(ctx), mss = ctx.ScreenCapture is not null, pillow = true },
                banner = new { current = ctx.Banner.Current, count = ctx.Banner.History(200).Count },
                tts = ApiHelpers.TtsStatus(ctx),
                autostart = new
                {
                    enabled = ctx.AutoStartEnabled?.Invoke() ?? false,
                    method = ctx.AutoStartEnabled is null ? "portable" : "registry-run",
                },
                config = ctx.Store.Public(),
                capabilities = new
                {
                    camera = true, audio = false, screen = ctx.ScreenCapture is not null,
                    banner = true, tts = true, talk = false,
                },
            };
        });

        app.MapGet("/api/logs", (HttpContext http, ServerContext ctx) =>
            new { logs = ctx.Runtime.RecentLogs(ApiHelpers.QueryInt(http, "limit", 100)) });

        app.MapPost("/api/auth", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var password = ApiHelpers.Str(body, "password", "");
            if (!ctx.Store.HasPassword)
                return Results.Json(new { detail = "尚未设置退出密码，请在设置窗口设置" }, statusCode: 409);
            if (!ctx.Store.VerifyPassword(password))
                return Results.Json(new { detail = "密码错误" }, statusCode: 403);
            return Results.Json(new { ok = true, token = ctx.IssueToken(), expires_in = 8 * 3600 });
        });

        app.MapGet("/api/platform", (ServerContext ctx) => new
        {
            autostart = new
            {
                enabled = ctx.AutoStartEnabled?.Invoke() ?? false,
                method = ctx.AutoStartEnabled is null ? "portable" : "registry-run",
            },
            system = Environment.OSVersion.Platform.ToString(),
            release = Environment.OSVersion.VersionString,
            runtime = ".NET 8",
            project_root = AppPaths.BaseDirectory,
            background = false,
        });

        app.MapPost("/api/autostart", async (HttpContext http, ServerContext ctx) =>
        {
            if (ctx.SetAutoStart is null)
                return Results.Json(new { detail = "当前平台不支持开机自启" }, statusCode: 400);
            var body = await ApiHelpers.Body(http);
            var enabled = ApiHelpers.Bool(body, "enabled", false);
            try
            {
                ctx.SetAutoStart(enabled);
                return Results.Json(new
                {
                    ok = true,
                    enabled = ctx.AutoStartEnabled?.Invoke() ?? enabled,
                });
            }
            catch (Exception ex)
            {
                return Results.Json(new { detail = ex.Message }, statusCode: 500);
            }
        });

        // ------------------------------------------------------------ config
        app.MapGet("/api/config", (ServerContext ctx) => ctx.Store.Public());

        app.MapPost("/api/config", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var source = ApiHelpers.Object(body, "config") ?? body;
            ctx.Store.Update(cfg =>
            {
                if (source.TryGetValue("room_name", out var room) && room.ValueKind == JsonValueKind.String)
                    cfg.RoomName = room.GetString() ?? cfg.RoomName;
                if (source.TryGetValue("device_name", out var device) && device.ValueKind == JsonValueKind.String)
                    cfg.DeviceName = device.GetString() ?? "";
                if (ApiHelpers.TryInt(source, "idle_timeout", out var idle)) cfg.IdleTimeoutSeconds = idle;
                if (source.TryGetValue("log_level", out var level) && level.ValueKind == JsonValueKind.String)
                    cfg.LogLevel = level.GetString() ?? cfg.LogLevel;
                if (source.TryGetValue("require_auth", out var require) && require.ValueKind is JsonValueKind.True or JsonValueKind.False)
                {
                    cfg.RequireAuth = require.GetBoolean();
                    if (cfg.RequireAuth) ctx.RevokeTokens();
                }
                if (ApiHelpers.Object(source, "camera") is { } camera)
                {
                    // index / remote_select are host privileges: never accepted over the network.
                    if (ApiHelpers.TryInt(camera, "width", out var w)) cfg.Camera.Width = w;
                    if (ApiHelpers.TryInt(camera, "height", out var h)) cfg.Camera.Height = h;
                    if (ApiHelpers.TryInt(camera, "fps", out var f)) cfg.Camera.Fps = f;
                    if (ApiHelpers.TryInt(camera, "quality", out var q)) cfg.Camera.Quality = q;
                    ctx.Camera.ApplyConfig(cfg.Camera);
                }
                if (ApiHelpers.Object(source, "tts") is { } tts) ApiHelpers.ApplyTts(cfg, tts);
            });
            ctx.Runtime.Log("info", "管理端更新了设备配置");
            return Results.Json(new { ok = true, config = ctx.Store.Public() });
        });

        app.MapPost("/api/password/change", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            if (!ctx.Store.VerifyPassword(ApiHelpers.Str(body, "old_password", "")))
                return Results.Json(new { detail = "原密码错误" }, statusCode: 403);
            var next = ApiHelpers.Str(body, "new_password", "");
            if (next.Length < 4)
                return Results.Json(new { detail = "新密码至少 4 位" }, statusCode: 400);
            ctx.Store.SetPassword(next);
            ctx.RevokeTokens();
            ctx.Runtime.Log("warning", "退出密码已被修改，所有登录会话已失效");
            return Results.Json(new { ok = true, token = ctx.IssueToken() });
        });

        // ------------------------------------------------------------ camera
        app.MapGet("/api/camera/config", (ServerContext ctx) =>
        {
            var cfg = ctx.Store.Snapshot().Camera;
            return new
            {
                config = new
                {
                    index = cfg.Index, width = cfg.Width, height = cfg.Height,
                    fps = cfg.Fps, quality = cfg.Quality, remote_select = cfg.RemoteSelect,
                },
                status = ctx.Camera.Status(),
                camera_select_locked = !cfg.RemoteSelect,
            };
        });

        app.MapPost("/api/camera/config", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var patch = ApiHelpers.Object(body, "config") ?? body;
            var locked = !ctx.Store.Snapshot().Camera.RemoteSelect;
            var ignored = new List<string>();
            ctx.Store.Update(cfg =>
            {
                if (ApiHelpers.TryInt(patch, "width", out var w)) cfg.Camera.Width = w;
                if (ApiHelpers.TryInt(patch, "height", out var h)) cfg.Camera.Height = h;
                if (ApiHelpers.TryInt(patch, "fps", out var f)) cfg.Camera.Fps = f;
                if (ApiHelpers.TryInt(patch, "quality", out var q)) cfg.Camera.Quality = q;
                if (ApiHelpers.TryInt(patch, "index", out var idx))
                {
                    if (locked) ignored.Add("index");
                    else cfg.Camera.Index = idx;
                }
                ctx.Camera.ApplyConfig(cfg.Camera);
            });
            var cfg = ctx.Store.Snapshot().Camera;
            return Results.Json(new
            {
                ok = true,
                config = new
                {
                    index = cfg.Index, width = cfg.Width, height = cfg.Height,
                    fps = cfg.Fps, quality = cfg.Quality, remote_select = cfg.RemoteSelect,
                },
                camera_select_locked = locked,
                ignored_fields = ignored,
            });
        });

        // Real friendly names come from the host provider; locked view exposes
        // only the device chosen in the desktop settings window.
        app.MapGet("/api/camera/devices", async (ServerContext ctx) =>
        {
            var cfg = ctx.Store.Snapshot().Camera;
            return await Task.Run(() => ctx.Names.BuildRemoteView(
                cfg.Index, ctx.DeviceIndices(), ctx.DeviceSize, cfg.RemoteSelect));
        });

        app.MapGet("/api/camera/snapshot", (HttpContext http, ServerContext ctx) =>
        {
            ctx.Runtime.Touch();
            http.Response.Headers["Cache-Control"] = "no-store, no-cache";
            return Results.File(ctx.Camera.Snapshot(), "image/jpeg");
        });

        app.MapGet("/api/camera/stream", async (HttpContext http, ServerContext ctx) =>
        {
            http.Response.ContentType = $"multipart/x-mixed-replace; boundary={Boundary}";
            http.Response.Headers["Cache-Control"] = "no-store, no-cache, must-revalidate";
            http.Response.Headers["Pragma"] = "no-cache";
            http.Response.Headers["X-Accel-Buffering"] = "no";

            ctx.Runtime.AddStream();
            var (reader, unsubscribe) = ctx.Camera.Subscribe();
            var token = http.RequestAborted;
            try
            {
                while (!token.IsCancellationRequested)
                {
                    byte[] jpeg;
                    try
                    {
                        using var wait = CancellationTokenSource.CreateLinkedTokenSource(token);
                        wait.CancelAfter(TimeSpan.FromSeconds(2));
                        jpeg = await reader.ReadAsync(wait.Token);
                    }
                    catch (OperationCanceledException)
                    {
                        jpeg = ctx.Camera.Snapshot();   // keep-alive frame
                    }
                    catch (ChannelClosedException) { break; }

                    var header = Encoding.ASCII.GetBytes(
                        $"--{Boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {jpeg.Length}\r\n\r\n");
                    await http.Response.Body.WriteAsync(header, token);
                    await http.Response.Body.WriteAsync(jpeg, token);
                    await http.Response.Body.WriteAsync(Encoding.ASCII.GetBytes("\r\n"), token);
                    await http.Response.Body.FlushAsync(token);
                }
            }
            catch (OperationCanceledException) { /* browser closed the tab */ }
            finally
            {
                unsubscribe();
                ctx.Runtime.RemoveStream();
            }
        });

        // ------------------------------------------------------------ screen
        app.MapGet("/api/screen/displays", (ServerContext ctx) => new { displays = ApiHelpers.Displays(ctx) });

        app.MapGet("/api/screen/shot", (HttpContext http, ServerContext ctx) =>
        {
            ctx.Runtime.Touch();
            var display = ApiHelpers.QueryInt(http, "display", 0);
            var scale = (float)ApiHelpers.QueryDouble(http, "scale", 1.0);
            var (bytes, fallback, meta) = ctx.ScreenCapture is not null
                ? ctx.ScreenCapture(display, scale)
                : (PlaceholderImages.PngBytes, true, (object)new { display, note = "截图组件未加载" });
            http.Response.Headers["Cache-Control"] = "no-store, no-cache";
            http.Response.Headers["X-CC-Fallback"] = fallback ? "1" : "0";
            http.Response.Headers["X-CC-Meta"] = JsonSerializer.Serialize(meta);
            return Results.File(bytes, "image/png");
        });

        // ------------------------------------------------------------ banner
        app.MapPost("/api/banner/send", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var markdown = ApiHelpers.Str(body, "markdown", "");
            if (string.IsNullOrWhiteSpace(markdown))
                return Results.Json(new { detail = "横幅内容不能为空" }, statusCode: 400);
            var banner = ctx.Banner.Send(
                ApiHelpers.Str(body, "title", "班级通知"), markdown,
                ApiHelpers.Bool(body, "urgent", false),
                ApiHelpers.Bool(body, "need_ack", true),
                ApiHelpers.Bool(body, "tts", true));
            ctx.Runtime.Log("info", $"收到横幅通知：{banner.title}");
            return Results.Json(new { ok = true, banner });
        });

        app.MapGet("/api/banner/history", (HttpContext http, ServerContext ctx) => new
        {
            items = ctx.Banner.History(ApiHelpers.QueryInt(http, "limit", 50)),
            current = ctx.Banner.Current,
        });

        app.MapGet("/api/banner/status", (ServerContext ctx) => new
        {
            current = ctx.Banner.Current,
            count = ctx.Banner.History(200).Count,
        });

        app.MapPost("/api/banner/ack", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var id = ApiHelpers.Str(body, "id", ctx.Banner.Current?.id ?? "");
            var record = ctx.Banner.Ack(id, "web");
            return record is null
                ? Results.Json(new { detail = "横幅不存在" }, statusCode: 404)
                : Results.Json(new { ok = true, banner = record });
        });

        app.MapPost("/api/banner/dismiss", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            ctx.Banner.Dismiss(ApiHelpers.Str(body, "id", ""), "web");
            return Results.Json(new { ok = true });
        });

        app.MapPost("/api/markdown/render", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var source = ApiHelpers.Str(body, "markdown", "");
            return new { html = ApiHelpers.ToHtml(source), plain = ApiHelpers.StripMarkdown(source) };
        });

        // ------------------------------------------------------------ tts
        app.MapGet("/api/tts/status", (ServerContext ctx) => ApiHelpers.TtsStatus(ctx));

        app.MapGet("/api/tts/voices", (ServerContext ctx) => new
        {
            voices = AppConfig.TtsVoices.Select(v => new { id = v.Id, name = v.Name }).ToArray(),
            current = ctx.Store.Snapshot().Tts.Voice,
        });

        app.MapPost("/api/tts/speak", async (HttpContext http, ServerContext ctx) =>
        {
            var body = await ApiHelpers.Body(http);
            var text = ApiHelpers.Str(body, "text", "");
            if (string.IsNullOrWhiteSpace(text))
                return Results.Json(new { detail = "播报内容不能为空" }, statusCode: 400);
            ctx.CountSpeak();
            ctx.Runtime.Log("info", $"语音播报：{text}");
            return Results.Json(new { ok = true, queued = true, spoken = ctx.SpokenCount });
        });

        // ------------------------------------------------------------ exit
        app.MapPost("/api/agent/stop", async (HttpContext http, ServerContext ctx) =>
            await ApiHelpers.ExitResult(http, ctx, "退出"));
        app.MapPost("/api/agent/restart", async (HttpContext http, ServerContext ctx) =>
            await ApiHelpers.ExitResult(http, ctx, "重启"));

        // ------------------------------------------------------------ websocket
        app.Map("/ws", async (HttpContext http, ServerContext ctx) =>
        {
            if (!http.WebSockets.IsWebSocketRequest)
            {
                http.Response.StatusCode = 400;
                return;
            }
            using var ws = await http.WebSockets.AcceptWebSocketAsync();
            ctx.Runtime.AddClient();
            var authRequired = ctx.Store.Snapshot().RequireAuth;
            var authed = !authRequired;
            try
            {
                await ApiHelpers.SendJson(ws, new
                {
                    type = "hello",
                    client_id = Guid.NewGuid().ToString("N")[..12],
                    version = ctx.Version,
                    device = new
                    {
                        name = Environment.MachineName,
                        room = ctx.Store.Snapshot().RoomName,
                        ip = ApiHelpers.GetLocalIp(),
                        port = ctx.Store.Snapshot().Port,
                    },
                    token_required = authRequired,
                    authed,
                    state = ctx.Runtime.Snapshot(),
                });

                var buffer = new byte[8192];
                while (ws.State == WebSocketState.Open)
                {
                    var result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), http.RequestAborted);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        // Echo the close frame so the browser/client can finish
                        // the handshake instead of seeing an aborted connection.
                        try
                        {
                            await ws.CloseAsync(WebSocketCloseStatus.NormalClosure,
                                                "bye", CancellationToken.None);
                        }
                        catch (Exception) { /* peer already gone */ }
                        break;
                    }
                    if (result.MessageType != WebSocketMessageType.Text) continue;
                    var raw = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    string type, token = "";
                    try
                    {
                        using var doc = JsonDocument.Parse(raw);
                        var root = doc.RootElement;
                        type = root.GetProperty("type").GetString() ?? "";
                        if (root.TryGetProperty("token", out var tokenElement)
                            && tokenElement.ValueKind == JsonValueKind.String)
                            token = tokenElement.GetString() ?? "";
                    }
                    catch (Exception) { continue; }

                    if (type == "auth")
                    {
                        authed = authed || ctx.ValidToken(token);
                        await ApiHelpers.SendJson(ws, new { type = "auth_result", ok = authed });
                    }
                    else if (authRequired && !authed)
                        await ApiHelpers.SendJson(ws, new { type = "error", message = "需要管理密码登录" });
                    else if (type == "ping")
                        await ApiHelpers.SendJson(ws, new { type = "pong", ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 });
                    else if (type == "status")
                        await ApiHelpers.SendJson(ws, new { type = "status", runtime = ctx.Runtime.Snapshot() });
                }
            }
            catch (OperationCanceledException) { /* disconnected */ }
            catch (WebSocketException) { /* disconnected */ }
            finally { ctx.Runtime.RemoveClient(); }
        });
    }
}
