using System.Diagnostics;
using System.Windows.Forms;
using ClassConnector.App.Forms;
using ClassConnector.App.Windows;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using ClassConnector.Core.Hosting;
using ClassConnector.Core.Runtime;

namespace ClassConnector.App;

/// <summary>
/// Composition root. Owns the whole lifetime so that hiding the settings window
/// never stops the service: only a password-verified exit does.
/// </summary>
public sealed class AppBootstrapper : ApplicationContext
{
    private readonly CachedCameraNameProvider _nameProvider;
    private readonly ServerContext _context;
    private MainForm? _form;
    private TrayHost? _tray;
    private volatile bool _exitRequested;

    public AppConfigStore Store { get; }
    public CameraService Camera { get; }
    public AgentRuntime Runtime { get; }
    public CameraNameResolver Names { get; }
    public DeviceCatalog Devices { get; }
    public AgentServerHost Server { get; }

    /// <summary>True only while a password-verified shutdown is in progress.</summary>
    public bool ExitRequested => _exitRequested;

    public AppBootstrapper(StartupOptions options)
    {
        AppPaths.EnsureDataDirectory();
        Store = new AppConfigStore();
        if (options.Port.HasValue) Store.Update(cfg => cfg.Port = options.Port.Value);

        _nameProvider = new CachedCameraNameProvider(
            new WindowsCameraNameProvider(), TimeSpan.FromSeconds(8));
        Names = new CameraNameResolver(_nameProvider);
        Devices = new DeviceCatalog(_nameProvider);
        Camera = new CameraService(Store.Snapshot().Camera,
                                   _ => new WindowsCameraFrameSource());
        Runtime = new AgentRuntime(Store);
        Runtime.OnSleep = Camera.Pause;
        Runtime.OnWake = Camera.Resume;

        _context = new ServerContext
        {
            Store = Store,
            Camera = Camera,
            Runtime = Runtime,
            Names = Names,
            DeviceIndices = () => Devices.Indices(),
            DeviceSize = index => Devices.SizeOf(index),
            DisplayCount = ScreenCaptureService.DisplayCount,
            ScreenCapture = ScreenCaptureService.Capture,
            Version = "2.0.0",
            RequestExit = RequestExit,
        };
        Server = new AgentServerHost(_context);
    }

    public void Initialize(StartupOptions options)
    {
        _form = new MainForm(this);
        MainForm = _form;   // keeps the WinForms message loop alive

        var cfg = Store.Snapshot();
        _tray = new TrayHost(
            ShowSettings,
            OpenManager,
            () => _ = RestartServiceAsync(),
            RequestExit,
            cfg.Port);

        var startHidden = options.Minimized || cfg.StartMinimized;
        if (startHidden)
        {
            _form.Hide();
            _tray.Notify("ClassConnector",
                "已最小化到系统托盘，服务正在后台运行。双击托盘图标可打开设置窗口。");
        }
        else _form.Show();

        // Fire-and-forget on the UI context: the window appears immediately,
        // the status bar flips to 运行中 as soon as the health probe passes.
        _ = StartServiceAsync(options);

        if (!options.NoBrowser && !startHidden)
        {
            _ = Task.Run(async () =>
            {
                await Task.Delay(1500);
                OpenManager();
            });
        }
    }

    private async Task StartServiceAsync(StartupOptions options)
    {
        if (options.NoService)
        {
            Runtime.Log("warning", "按命令行参数要求，本次不启动采集端服务");
            return;
        }
        var cfg = Store.Snapshot();
        var ok = await Server.StartAsync(cfg.Host, cfg.Port);
        if (ok)
            _tray?.Notify("ClassConnector", $"服务已启动：http://127.0.0.1:{cfg.Port}/");
        else
            _tray?.Notify("ClassConnector 服务启动失败", Server.LastError, ToolTipIcon.Error);
    }

    // ---------------------------------------------------------------- tray actions
    public void InvalidateNames() => _nameProvider.Invalidate();
    public void RevokeTokens() => _context.RevokeTokens();
    public void SetTrayStatus(string text) => _tray?.SetStatus(text);
    public void TestSpeak() { SoundHelper.Play(false); Runtime.Log("info", "试听播报提示音"); }
    public void TestAlert() { SoundHelper.Play(true); Runtime.Log("info", "试听紧急警报音"); }

    public void ShowSettings()
    {
        var form = _form;
        if (form is null) return;
        if (form.InvokeRequired) { form.BeginInvoke(ShowSettings); return; }
        form.Show();
        form.ShowInTaskbar = true;
        form.WindowState = FormWindowState.Normal;
        form.BringToFront();
        form.Activate();
    }

    /// <summary>Closing the window (X or 退出 button) hides it to the tray.</summary>
    public void HideToTray()
    {
        _form?.Hide();
        _tray?.Notify("ClassConnector",
            "已最小化到系统托盘，服务继续在后台运行。双击托盘图标可重新打开设置窗口。");
    }

    public void OpenManager()
    {
        try
        {
            Process.Start(new ProcessStartInfo($"http://127.0.0.1:{Store.Snapshot().Port}/")
            {
                UseShellExecute = true,
            });
        }
        catch (Exception ex) { Runtime.Log("warning", $"打开管理端失败：{ex.Message}"); }
    }

    public async Task RestartServiceAsync()
    {
        var cfg = Store.Snapshot();
        var ok = await Server.StartAsync(cfg.Host, cfg.Port);
        Runtime.Log(ok ? "info" : "error",
                    ok ? "采集端服务已重启" : "采集端服务重启失败：" + Server.LastError);
    }

    /// <summary>Exit requires the install password; also used by the web API.</summary>
    public void RequestExit()
    {
        if (_exitRequested) return;
        var form = _form;
        if (form is not null && form.IsHandleCreated && form.InvokeRequired)
        {
            form.BeginInvoke(RequestExit);
            return;
        }

        if (Store.HasPassword)
        {
            using var dialog = new PasswordDialog("退出确认", "请输入安装时设置的退出密码：");
            if (dialog.ShowDialog() != DialogResult.OK) return;
            if (!Store.VerifyPassword(dialog.EnteredPassword))
            {
                MessageBox.Show("密码不正确，程序继续运行。", "密码错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
        }
        ExitAsync();
    }

    private async void ExitAsync()
    {
        _exitRequested = true;
        try
        {
            _tray?.Dispose();
            _tray = null;
            await Server.DisposeAsync();
            Camera.Dispose();
            Runtime.Log("info", "设置窗口已关闭，程序退出");
        }
        catch (Exception ex)
        {
            Runtime.Log("error", $"退出时清理失败：{ex.Message}");
        }
        finally
        {
            _form?.Hide();
            ExitThread();
        }
    }
}
