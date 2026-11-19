using System.Management;
using System.Runtime.InteropServices;
using System.Text;
using ClassConnector.Core.Camera;

namespace ClassConnector.App.Windows;

/// <summary>
/// Resolves the REAL friendly names of the classroom PC's cameras.
///
/// Primary source is WMI (Win32_PnPEntity, class Camera/Image), which reports
/// names such as "Integrated Camera" or "Logitech C920 HD Pro Webcam".
/// A VFW (avicap32.dll) driver-description walk is used as a fallback and
/// gives names in the same device-index order that OpenCV / DirectShow uses.
///
/// This is the fix for "选择摄像头页面要列出摄像头名称": the settings window
/// now shows actual device names instead of "摄像头 0 / 摄像头 1".
/// </summary>
public sealed class WindowsCameraNameProvider : ICameraNameProvider
{
    [DllImport("avicap32.dll", EntryPoint = "capGetDriverDescriptionW",
               CharSet = CharSet.Unicode, SetLastError = false)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CapGetDriverDescription(
        uint driverIndex, StringBuilder name, int nameCapacity,
        StringBuilder version, int versionCapacity);

    public IReadOnlyList<string> GetFriendlyNames()
    {
        if (!OperatingSystem.IsWindows()) return Array.Empty<string>();

        var wmi = WmiNames();
        if (wmi.Count > 0) return wmi;

        var vfw = VfwNames();
        if (vfw.Count > 0) return vfw;

        return Array.Empty<string>();
    }

    private static List<string> WmiNames()
    {
        var names = new List<string>();
        try
        {
            const string query =
                "SELECT Name FROM Win32_PnPEntity WHERE PNPClass='Camera' OR PNPClass='Image'";
            using var searcher = new ManagementObjectSearcher(query);
            using var collection = searcher.Get();
            foreach (ManagementObject device in collection)
            {
                using (device) Append(names, device["Name"]?.ToString());
            }
        }
        catch (Exception)
        {
            // WMI blocked / unavailable - the VFW fallback below still works.
        }
        return names;
    }

    private static List<string> VfwNames()
    {
        var names = new List<string>();
        try
        {
            for (uint index = 0; index < 10; index++)
            {
                var name = new StringBuilder(256);
                var version = new StringBuilder(256);
                if (CapGetDriverDescription(index, name, name.Capacity, version, version.Capacity))
                    Append(names, name.ToString());
            }
        }
        catch (Exception) { /* avicap32.dll missing on exotic systems */ }
        return names;
    }

    private static void Append(List<string> names, string? raw)
    {
        var clean = CameraNameResolver.Clean(raw);
        if (string.IsNullOrWhiteSpace(clean)) return;
        if (clean.Contains("WDM Image Capture", StringComparison.OrdinalIgnoreCase)
            && names.Count > 0) return;   // generic placeholder, keep real names
        if (names.Any(n => string.Equals(n, clean, StringComparison.OrdinalIgnoreCase))) return;
        names.Add(clean);
    }
}
