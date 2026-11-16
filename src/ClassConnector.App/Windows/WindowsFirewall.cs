using System.Diagnostics;

namespace ClassConnector.App.Windows;

/// <summary>
/// Adds an inbound TCP rule for the agent port. Windows Firewall (or a third
/// party firewall) is the usual reason the service listens correctly but LAN
/// clients still cannot open the manager page. The UI offers this as an
/// explicit, UAC-elevated action instead of silently changing system policy.
/// </summary>
public static class WindowsFirewall
{
    public static bool AllowInbound(int port)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("自动放行仅支持 Windows");
        if (port is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(port));

        var name = $"ClassConnector ({port})";
        var args = $"advfirewall firewall add rule name=\"{name}\" dir=in action=allow " +
                   $"protocol=TCP localport={port} profile=any";
        var start = new ProcessStartInfo("netsh.exe", args)
        {
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        using var process = Process.Start(start);
        if (process is null) return false;
        if (!process.WaitForExit(20000))
        {
            try { process.Kill(); } catch (Exception) { /* already gone */ }
            return false;
        }
        return process.ExitCode == 0;
    }
}
