using System.Globalization;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using ClassConnector.Core.Configuration;
using Microsoft.AspNetCore.Http;

namespace ClassConnector.Core.Hosting;

internal static class ApiHelpers
{
    public static string GetLocalIp()
    {
        try
        {
            using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            socket.Connect("223.5.5.5", 80);
            return ((IPEndPoint)socket.LocalEndPoint!).Address.ToString();
        }
        catch (Exception)
        {
            try
            {
                return Dns.GetHostAddresses(Dns.GetHostName())
                    .First(a => a.AddressFamily == AddressFamily.InterNetwork).ToString();
            }
            catch (Exception) { return "127.0.0.1"; }
        }
    }

    /// <summary>All usable LAN URLs, derived from live NICs rather than a UDP
    /// probe (which fails on offline machines and hides the real address).</summary>
    public static string[] LanUrls(int port)
    {
        var ips = new List<string>();
        try
        {
            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (nic.OperationalStatus != OperationalStatus.Up) continue;
                foreach (var info in nic.GetIPProperties().UnicastAddresses)
                    if (info.Address.AddressFamily == AddressFamily.InterNetwork
                        && !info.Address.ToString().StartsWith("127."))
                        ips.Add(info.Address.ToString());
            }
        }
        catch (Exception) { /* NIC enumeration is best effort */ }
        try
        {
            foreach (var address in Dns.GetHostAddresses(Dns.GetHostName()))
                if (address.AddressFamily == AddressFamily.InterNetwork
                    && !address.ToString().StartsWith("127."))
                    ips.Add(address.ToString());
        }
        catch (Exception) { /* no DNS */ }
        try
        {
            using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            socket.Connect("223.5.5.5", 80);
            var ip = ((IPEndPoint)socket.LocalEndPoint!).Address.ToString();
            if (!ip.StartsWith("127.")) ips.Add(ip);
        }
        catch (Exception) { /* offline */ }
        return ips.Distinct().Select(ip => $"http://{ip}:{port}/").ToArray();
    }

    public static int QueryInt(HttpContext http, string key, int fallback) =>
        int.TryParse(http.Request.Query[key].ToString(), out var value) ? value : fallback;

    public static double QueryDouble(HttpContext http, string key, double fallback) =>
        double.TryParse(http.Request.Query[key].ToString(), NumberStyles.Float,
                        CultureInfo.InvariantCulture, out var value) ? value : fallback;

    public static async Task<Dictionary<string, JsonElement>> Body(HttpContext http)
    {
        try
        {
            return await http.Request.ReadFromJsonAsync<Dictionary<string, JsonElement>>()
                   ?? new Dictionary<string, JsonElement>();
        }
        catch (Exception) { return new Dictionary<string, JsonElement>(); }
    }

    public static Dictionary<string, JsonElement>? Object(Dictionary<string, JsonElement> body, string key)
    {
        if (!body.TryGetValue(key, out var value) || value.ValueKind != JsonValueKind.Object) return null;
        return value.EnumerateObject().ToDictionary(p => p.Name, p => p.Value);
    }

    public static bool TryInt(Dictionary<string, JsonElement> body, string key, out int value)
    {
        value = 0;
        if (!body.TryGetValue(key, out var item)) return false;
        if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out value)) return true;
        if (item.ValueKind == JsonValueKind.String && int.TryParse(item.GetString(), out value)) return true;
        return false;
    }

    public static string Str(Dictionary<string, JsonElement> body, string key, string fallback)
    {
        if (!body.TryGetValue(key, out var item)) return fallback;
        return item.ValueKind == JsonValueKind.String ? item.GetString() ?? fallback : item.ToString();
    }

    public static bool Bool(Dictionary<string, JsonElement> body, string key, bool fallback)
    {
        if (!body.TryGetValue(key, out var item)) return fallback;
        if (item.ValueKind is JsonValueKind.True or JsonValueKind.False) return item.GetBoolean();
        if (item.ValueKind == JsonValueKind.String && bool.TryParse(item.GetString(), out var parsed)) return parsed;
        return fallback;
    }

    public static void ApplyTts(AppConfig cfg, Dictionary<string, JsonElement> tts)
    {
        if (tts.TryGetValue("enabled", out var enabled)
            && enabled.ValueKind is JsonValueKind.True or JsonValueKind.False)
            cfg.Tts.Enabled = enabled.GetBoolean();
        if (tts.TryGetValue("voice", out var voice) && voice.ValueKind == JsonValueKind.String)
            cfg.Tts.Voice = voice.GetString() ?? cfg.Tts.Voice;
        if (tts.TryGetValue("rate", out var rate) && rate.ValueKind == JsonValueKind.String)
            cfg.Tts.Rate = rate.GetString() ?? cfg.Tts.Rate;
        if (tts.TryGetValue("volume", out var volume) && volume.ValueKind == JsonValueKind.String)
            cfg.Tts.Volume = volume.GetString() ?? cfg.Tts.Volume;
        if (tts.TryGetValue("urgent_alert", out var urgent)
            && urgent.ValueKind is JsonValueKind.True or JsonValueKind.False)
            cfg.Tts.UrgentAlert = urgent.GetBoolean();
    }

    public static object[] Displays(ServerContext ctx)
    {
        var count = Math.Clamp(ctx.DisplayCount?.Invoke() ?? 1, 1, 8);
        return Enumerable.Range(0, count).Select(i => (object)new
        {
            index = i,
            name = i == 0 ? "主显示器" : $"显示器 {i + 1}",
            width = 1920,
            height = 1080,
            primary = i == 0,
        }).ToArray();
    }

    public static object TtsStatus(ServerContext ctx)
    {
        var tts = ctx.Store.Snapshot().Tts;
        return new
        {
            enabled = tts.Enabled,
            voice = tts.Voice,
            edge_tts_installed = false,
            player = "system",
            spoken = ctx.SpokenCount,
            pending = 0,
            busy = false,
            last_error = "",
            urgent_alert = tts.UrgentAlert,
            voices = AppConfig.TtsVoices.Select(v => new { id = v.Id, name = v.Name }).ToArray(),
        };
    }

    public static async Task<IResult> ExitResult(HttpContext http, ServerContext ctx, string action)
    {
        var body = await Body(http);
        if (!ctx.Store.HasPassword)
            return Results.Json(new { detail = "尚未设置退出密码，请在设置窗口设置" }, statusCode: 409);
        if (!ctx.Store.VerifyPassword(Str(body, "password", "")))
            return Results.Json(new { detail = "密码错误" }, statusCode: 403);
        ctx.Runtime.Log("warning", $"收到带密码的{action}指令，采集端即将关闭");
        _ = Task.Run(async () =>
        {
            await Task.Delay(600);
            ctx.RequestExit?.Invoke();
        });
        return Results.Json(new { ok = true, message = $"密码校验通过，采集端正在{action}" });
    }

    public static string StripMarkdown(string source)
    {
        var text = Regex.Replace(source, @"!\[[^\]]*\]\([^)]*\)", "");
        text = Regex.Replace(text, @"\[([^\]]+)\]\([^)]*\)", "$1");
        text = Regex.Replace(text, @"[*_`#>]", "");
        return text.Trim();
    }

    public static string ToHtml(string source)
    {
        var escaped = WebUtility.HtmlEncode(source ?? "");
        escaped = Regex.Replace(escaped, @"^######\s?(.*)$", "<h6>$1</h6>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"^#####\s?(.*)$", "<h5>$1</h5>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"^####\s?(.*)$", "<h4>$1</h4>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"^###\s?(.*)$", "<h3>$1</h3>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"^##\s?(.*)$", "<h2>$1</h2>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"^#\s?(.*)$", "<h1>$1</h1>", RegexOptions.Multiline);
        escaped = Regex.Replace(escaped, @"\*\*(.+?)\*\*", "<strong>$1</strong>");
        escaped = Regex.Replace(escaped, @"\*(.+?)\*", "<em>$1</em>");
        return escaped.Replace("\r\n", "\n").Replace("\n", "<br>");
    }

    public static Task SendJson(WebSocket ws, object payload)
    {
        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload));
        return ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text,
                            true, CancellationToken.None);
    }
}
