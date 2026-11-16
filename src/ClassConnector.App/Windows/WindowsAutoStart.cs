using Microsoft.Win32;

namespace ClassConnector.App.Windows;

/// <summary>
/// Per-user startup registration for the packaged desktop app. It writes a
/// single HKCU Run value (no system service, no machine-wide change) and is
/// fully reversible from the settings window or POST /api/autostart.
/// </summary>
public static class WindowsAutoStart
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "ClassConnector";

    public static bool IsEnabled
    {
        get
        {
            if (!OperatingSystem.IsWindows()) return false;
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(RunKey);
                var command = key?.GetValue(ValueName) as string ?? "";
                return command.Contains("ClassConnector.exe", StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception) { return false; }
        }
    }

    public static void SetEnabled(bool enabled)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("开机自启仅支持 Windows");

        using var key = Registry.CurrentUser.OpenSubKey(RunKey, true)
                        ?? throw new InvalidOperationException("无法打开当前用户的启动项");
        if (!enabled)
        {
            key.DeleteValue(ValueName, false);
            return;
        }

        var exe = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(exe) || !exe.EndsWith("ClassConnector.exe", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("无法确定 ClassConnector.exe 的路径，请从正式发布的 exe 启动后再开启自启");

        key.SetValue(ValueName, $"\"{exe}\" --minimized --no-browser", RegistryValueKind.String);
    }
}
