using System.Windows.Forms;

namespace ClassConnector.App;

/// <summary>Command line switches shared by VS launchSettings.json and CI checks.</summary>
public sealed class StartupOptions
{
    public int? Port { get; init; }
    public bool NoBrowser { get; init; }
    public bool Minimized { get; init; }
    public bool NoService { get; init; }

    public static StartupOptions Parse(string[] args)
    {
        int? port = null;
        var noBrowser = false;
        var minimized = false;
        var noService = false;

        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--port":
                    if (i + 1 < args.Length && int.TryParse(args[++i], out var value)) port = value;
                    break;
                case "--no-browser": noBrowser = true; break;
                case "--minimized": minimized = true; break;
                case "--no-service": noService = true; break;
                case "--headless-check":
                    // CI / smoke check: no browser, tray-only, service still starts.
                    noBrowser = true;
                    minimized = true;
                    break;
            }
        }
        return new StartupOptions
        {
            Port = port,
            NoBrowser = noBrowser,
            Minimized = minimized,
            NoService = noService,
        };
    }
}

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();

        using var mutex = new Mutex(true, @"Local\ClassConnector.SingleInstance", out var createdNew);
        if (!createdNew)
        {
            MessageBox.Show("ClassConnector 已在运行，请看右下角系统托盘图标。",
                "ClassConnector", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }

        var options = StartupOptions.Parse(args);
        var app = new AppBootstrapper(options);
        app.Initialize(options);
        Application.Run(app);
        return 0;
    }
}
