using System;
using System.IO;

namespace ClassConnector.Core.Configuration;

/// <summary>
/// Green / portable layout. Every runtime file (config, log, marker) lives in
/// <c>data/</c> next to the exe. Nothing is written to the registry, AppData,
/// or the user profile. Delete the folder to uninstall.
/// </summary>
public static class AppPaths
{
    /// <summary>Exe / output directory. Works for single-file publish too.</summary>
    public static string BaseDirectory { get; } = ResolveBaseDirectory();

    private static string ResolveBaseDirectory()
    {
        var overrideDir = Environment.GetEnvironmentVariable("CLASSCONNECTOR_HOME");
        if (!string.IsNullOrWhiteSpace(overrideDir))
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(overrideDir));
        // AppContext.BaseDirectory stays correct for single-file bundles,
        // unlike Assembly.Location which is empty in that mode.
        return AppContext.BaseDirectory;
    }

    public static string DataDirectory => Path.Combine(BaseDirectory, "data");
    public static string ConfigFile => Path.Combine(DataDirectory, "config.json");
    public static string LogFile => Path.Combine(DataDirectory, "agent.log");
    public static string ManagerDirectory => Path.Combine(BaseDirectory, "manager");
    public static string AssetsDirectory => Path.Combine(BaseDirectory, "assets");
    public static string IconFile(string name = "icon.ico") => Path.Combine(AssetsDirectory, name);

    public static void EnsureDataDirectory()
    {
        Directory.CreateDirectory(DataDirectory);
        var marker = Path.Combine(DataDirectory, "PORTABLE.txt");
        if (!File.Exists(marker))
        {
            File.WriteAllText(marker,
                "ClassConnector .NET portable mode\n" +
                "All runtime data stays in this folder (data/).\n" +
                "No registry, autostart, system service or user-profile writes.\n" +
                "Delete the whole folder to uninstall.\n");
        }
    }
}
