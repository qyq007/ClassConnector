using System.Drawing;
using System.Windows.Forms;
using ClassConnector.Core.Configuration;

namespace ClassConnector.App;

/// <summary>
/// System-tray presence. This is what makes the app a real background agent:
/// closing the settings window only hides it, the embedded service keeps
/// running, and the tray menu is the way back in (or to exit with a password).
/// </summary>
public sealed class TrayHost : IDisposable
{
    private readonly SynchronizationContext? _uiContext;
    private readonly ToolStripMenuItem _statusItem;
    private NotifyIcon? _icon;

    public TrayHost(
        Action showSettings,
        Action openManager,
        Action restartService,
        Action restartApp,
        Action exit,
        int port)
    {
        _uiContext = SynchronizationContext.Current;
        _statusItem = new ToolStripMenuItem("● 服务运行中") { Enabled = false };

        var menu = new ContextMenuStrip();
        menu.Items.Add(_statusItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem("打开设置窗口（需管理密码）", null, (_, _) => showSettings()));
        menu.Items.Add(new ToolStripMenuItem("打开管理端", null, (_, _) => openManager()));
        menu.Items.Add(new ToolStripMenuItem("重启服务", null, (_, _) => restartService()));
        menu.Items.Add(new ToolStripMenuItem("重启程序（需管理密码）", null, (_, _) => restartApp()));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem("退出（需管理密码）", null, (_, _) => exit()));

        _icon = new NotifyIcon
        {
            Icon = LoadIcon(),
            Text = $"ClassConnector · 班级连接器 (端口 {port})",
            ContextMenuStrip = menu,
            Visible = true,
        };
        _icon.DoubleClick += (_, _) => showSettings();
    }

    internal static Icon LoadIcon()
    {
        var ico = AppPaths.IconFile("icon.ico");
        if (File.Exists(ico))
        {
            try { return new Icon(ico); }
            catch (Exception) { /* fall through to the PNG / generated icon */ }
        }
        // Same artwork as the web manager => tray icon and app icon stay identical.
        var png = AppPaths.IconFile("icon.png");
        if (File.Exists(png))
        {
            try
            {
                using var source = new Bitmap(png);
                return Icon.FromHandle(source.GetHicon());
            }
            catch (Exception) { /* fall through to generated icon */ }
        }
        using var bitmap = new Bitmap(32, 32);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.Clear(Color.FromArgb(37, 99, 235));
            graphics.DrawEllipse(Pens.White, 5, 5, 22, 22);
            graphics.DrawLine(Pens.White, 16, 5, 16, 27);
            graphics.DrawLine(Pens.White, 5, 16, 27, 16);
        }
        return Icon.FromHandle(bitmap.GetHicon());
    }

    public void SetStatus(string text)
    {
        if (_icon is null) return;
        if (_uiContext is not null) _uiContext.Post(_ => _statusItem.Text = text, null);
        else _statusItem.Text = text;
    }

    public void Notify(string title, string message, ToolTipIcon icon = ToolTipIcon.Info)
        => _icon?.ShowBalloonTip(4000, title, message, icon);

    public void Dispose()
    {
        if (_icon is null) return;
        _icon.Visible = false;   // otherwise a ghost icon remains after exit
        _icon.ContextMenuStrip?.Dispose();
        _icon.Dispose();
        _icon = null;
    }
}
