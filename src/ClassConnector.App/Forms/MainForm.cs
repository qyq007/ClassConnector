using System.Drawing;
using System.Net;
using System.Net.Sockets;
using System.Windows.Forms;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using Timer = System.Windows.Forms.Timer;

namespace ClassConnector.App.Forms;

/// <summary>
/// Pure-settings main window. The camera tab lists REAL device names from the
/// host OS; the web manager can only see the one device selected here.
/// </summary>
public sealed class MainForm : Form
{
    private static readonly Color Muted = Color.FromArgb(100, 116, 139);
    private static readonly Color Accent = Color.FromArgb(37, 99, 235);
    private static readonly Color Warn = Color.FromArgb(180, 83, 9);
    private static readonly Color Danger = Color.FromArgb(220, 38, 38);

    private readonly AppBootstrapper _app;
    private readonly Dictionary<string, int> _deviceMap = new();
    private readonly Dictionary<string, string> _voiceMap = new();
    private readonly Timer _timer = new() { Interval = 1000 };

    private readonly ComboBox _device = Combo(400);
    private readonly ComboBox _resolution = Combo(150);
    private readonly ComboBox _fps = Combo(80);
    private readonly ComboBox _voice = Combo(280);
    private readonly ComboBox _rate = Combo(90);
    private readonly ComboBox _volume = Combo(90);
    private readonly TrackBar _quality = new() { Minimum = 10, Maximum = 100, TickFrequency = 10, Width = 300 };
    private readonly Label _qualityLabel = Txt("70", 12, 88, 40);
    private readonly CheckBox _remoteSelect = Check("允许管理端在 Web 上枚举 / 切换摄像头", 12, 26, 620);
    private readonly CheckBox _ttsEnabled = Check("启用横幅内容语音播报", 12, 24, 620);
    private readonly CheckBox _urgentAlert = Check("紧急通知先播放独立警报音（与普通通知区分）", 12, 24, 620);
    private readonly CheckBox _requireAuth = Check("管理端需要密码登录（所有管理操作均需验证）", 12, 24, 620);
    private readonly CheckBox _startMinimized = Check("启动时最小化到系统托盘（后台运行）", 12, 24, 620);
    private readonly TextBox _room = Input(24, 260);
    private readonly TextBox _port = Input(24, 90);
    private readonly TextBox _idle = Input(24, 90);

    private readonly Label _serviceStatus = Txt("■ 启动中", 12, 22, 110);
    private readonly Label _connStatus = Txt("连接 0", 130, 22, 100);
    private readonly Label _camStatus = Txt("摄像头：检测中", 240, 22, 260);
    private readonly Label _address = Txt("", 70, 50, 560);
    private readonly Label _addresses = Txt("", 12, 24, 620);
    private readonly Label _errorStatus = Txt("", 12, 74, 620);
    private readonly Label _playerStatus = Txt("", 12, 92, 620);

    public MainForm(AppBootstrapper app)
    {
        _app = app;
        Text = "ClassConnector · 设置  v2.0.0 (.NET 8)";
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(760, 760);
        MinimumSize = new Size(680, 640);
        try { Icon = TrayHost.LoadIcon(); }
        catch (Exception) { /* icon optional */ }

        BuildUi();
        LoadFromConfig();
        _timer.Tick += (_, _) => RefreshStatus();
        _timer.Start();
        RefreshStatus();
    }

    // ---------------------------------------------------------------- helpers
    private static ComboBox Combo(int width) => new()
    {
        Width = width,
        DropDownStyle = ComboBoxStyle.DropDownList,
        FlatStyle = FlatStyle.System,
    };

    private static Label Txt(string text, int left, int top, int width) => new()
    {
        Text = text, Left = left, Top = top, Width = width,
        AutoSize = false, Height = 20,
    };

    private static TextBox Input(int top, int width) => new()
    {
        Left = 190, Top = top, Width = width,
    };

    private static CheckBox Check(string text, int left, int top, int width) => new()
    {
        Text = text, Left = left, Top = top, Width = width, AutoSize = false, Height = 24,
    };

    private static Button Btn(string text, int width) => new()
    {
        Text = text, Width = width, Height = 30,
    };

    private static GroupBox Group(string title, int height) => new()
    {
        Text = title, Height = height, Dock = DockStyle.Fill,
        Padding = new Padding(10),
    };

    private static TableLayoutPanel Page()
    {
        var page = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            AutoScroll = true,
            Padding = new Padding(12),
        };
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return page;
    }

    private static void AddRow(TableLayoutPanel page, Control control, int height)
    {
        var row = page.RowStyles.Count;
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        page.RowCount = row + 1;
        page.Controls.Add(control, 0, row);
    }

    // ---------------------------------------------------------------- UI
    private void BuildUi()
    {
        var grid = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(10),
        };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 128));
        grid.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));

        var header = new Panel { Dock = DockStyle.Fill };
        header.Controls.Add(new Label
        {
            Text = "ClassConnector", Font = new Font("Segoe UI", 13, FontStyle.Bold),
            Left = 2, Top = 4, AutoSize = true,
        });
        header.Controls.Add(new Label
        {
            Text = "  教室电脑设置 · 修改后点击「保存设置」生效",
            Left = 175, Top = 8, AutoSize = true, ForeColor = Muted,
        });

        var tabs = new TabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(BuildCameraTab());
        tabs.TabPages.Add(BuildVoiceTab());
        tabs.TabPages.Add(BuildNetworkTab());

        var status = new GroupBox { Text = "运行状态", Dock = DockStyle.Fill, Padding = new Padding(8) };
        _serviceStatus.Font = new Font(Font, FontStyle.Bold);
        _serviceStatus.ForeColor = Accent;
        _address.ForeColor = Accent;
        _errorStatus.ForeColor = Danger;
        _errorStatus.Height = 22;
        status.Controls.AddRange(new Control[]
        {
            _serviceStatus, _connStatus, _camStatus,
            new Label { Text = "局域网：", Left = 12, Top = 50, Width = 60 },
            _address, _errorStatus,
        });

        var buttons = new Panel { Dock = DockStyle.Fill };
        var open = Btn("打开管理端", 110);
        open.Left = 0; open.Top = 4;
        open.Click += (_, _) => _app.OpenManager();
        var restart = Btn("重启服务", 100);
        restart.Left = 116; restart.Top = 4;
        restart.Click += (_, _) => _ = _app.RestartServiceAsync();
        var save = Btn("保存设置", 100);
        save.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        save.Click += (_, _) => SaveSettings();
        var exitBtn = Btn("退出", 90);
        exitBtn.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        exitBtn.Click += (_, _) => _app.RequestExit();
        buttons.Controls.AddRange(new Control[] { open, restart, save, exitBtn });
        buttons.Resize += (_, _) =>
        {
            exitBtn.Left = buttons.Width - exitBtn.Width;
            save.Left = buttons.Width - exitBtn.Width - save.Width - 8;
        };
        // initial placement
        exitBtn.Left = 640; save.Left = 532;

        grid.Controls.Add(header, 0, 0);
        grid.Controls.Add(tabs, 0, 1);
        grid.Controls.Add(status, 0, 2);
        grid.Controls.Add(buttons, 0, 3);
        Controls.Add(grid);
    }

    private TabPage BuildCameraTab()
    {
        var tab = new TabPage("  摄像头  ");
        var page = Page();
        tab.Controls.Add(page);

        var devices = Group("摄像头设备（仅本机可见）", 116);
        _device.Left = 78; _device.Top = 24;
        var refresh = Btn("刷新设备", 92);
        refresh.Left = 486; refresh.Top = 23;
        refresh.Click += (_, _) => RefreshDevices();
        var hint = Txt("只有这台电脑的设置窗口能列出并选择摄像头。管理端默认只能看到这里指定的那一路画面，无法访问本机其他摄像头。",
                       12, 62, 620);
        hint.Height = 40; hint.ForeColor = Muted;
        devices.Controls.AddRange(new Control[]
        {
            new Label { Text = "设备：", Left = 12, Top = 28, Width = 60 },
            _device, refresh, hint,
        });
        AddRow(page, devices, 124);

        var picture = Group("画面参数", 116);
        _resolution.Left = 78; _resolution.Top = 22;
        _resolution.Items.AddRange(AppConfig.Resolutions);
        _fps.Left = 330; _fps.Top = 22;
        _fps.Items.AddRange(AppConfig.FpsChoices.Select(f => (object)f.ToString()).ToArray());
        _quality.Left = 88; _quality.Top = 66;
        _quality.ValueChanged += (_, _) => _qualityLabel.Text = _quality.Value.ToString();
        _qualityLabel.Left = 48; _qualityLabel.Top = 72;
        picture.Controls.AddRange(new Control[]
        {
            new Label { Text = "分辨率：", Left = 12, Top = 26, Width = 66 },
            _resolution,
            new Label { Text = "帧率：", Left = 252, Top = 26, Width = 60 },
            _fps,
            new Label { Text = "画质：", Left = 12, Top = 72, Width = 40 },
            _qualityLabel, _quality,
        });
        AddRow(page, picture, 124);

        var access = Group("网络访问权限", 112);
        var warn = Txt("默认关闭。开启后，任何能访问本服务的管理端都可以查看并切换本机全部摄像头，请仅在可信局域网内使用。",
                       12, 56, 620);
        warn.Height = 40; warn.ForeColor = Warn;
        access.Controls.AddRange(new Control[] { _remoteSelect, warn });
        AddRow(page, access, 120);
        return tab;
    }

    private TabPage BuildVoiceTab()
    {
        var tab = new TabPage("  播报与音效  ");
        var page = Page();
        tab.Controls.Add(page);

        var tts = Group("Edge TTS 语音播报", 152);
        _voice.Left = 100; _voice.Top = 54;
        _rate.Left = 100; _rate.Top = 88;
        _rate.Items.AddRange(new object[] { "-20%", "-10%", "+0%", "+10%", "+20%" });
        _volume.Left = 300; _volume.Top = 88;
        _volume.Items.AddRange(new object[] { "-20%", "-10%", "+0%", "+10%", "+20%" });
        tts.Controls.AddRange(new Control[]
        {
            _ttsEnabled,
            new Label { Text = "播报语音：", Left = 12, Top = 58, Width = 88 },
            _voice,
            new Label { Text = "语速：", Left = 12, Top = 92, Width = 88 },
            _rate,
            new Label { Text = "音量：", Left = 220, Top = 92, Width = 60 },
            _volume,
        });
        AddRow(page, tts, 160);

        var alert = Group("紧急事件音效", 148);
        var speak = Btn("试听播报", 100);
        speak.Left = 12; speak.Top = 56;
        speak.Click += (_, _) =>
        {
            _app.TestSpeak();
            MessageBox.Show(this, "已播放测试提示音。横幅内容语音播报由管理端 /api/tts/speak 触发。",
                "试听", MessageBoxButtons.OK, MessageBoxIcon.Information);
        };
        var testAlert = Btn("试听警报音", 100);
        testAlert.Left = 120; testAlert.Top = 56;
        testAlert.Click += (_, _) =>
        {
            _app.TestAlert();
            MessageBox.Show(this, "正在播放紧急警报音。", "试听",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
        };
        _playerStatus.ForeColor = Muted;
        _playerStatus.Top = 94;
        _playerStatus.Height = 34;
        alert.Controls.AddRange(new Control[] { _urgentAlert, speak, testAlert, _playerStatus });
        AddRow(page, alert, 156);

        var note = Txt("提示：Edge TTS 合成需要联网；本机音效优先使用系统播放器。管理端可通过 /api/tts/speak 触发播报。",
                       12, 8, 620);
        note.Height = 40; note.ForeColor = Muted;
        AddRow(page, note, 56);
        return tab;
    }

    private TabPage BuildNetworkTab()
    {
        var tab = new TabPage("  网络与安全  ");
        var page = Page();
        tab.Controls.Add(page);

        var info = Group("设备信息", 128);
        _room.Top = 22; _port.Top = 54; _idle.Top = 86;
        info.Controls.AddRange(new Control[]
        {
            new Label { Text = "班级名称：", Left = 12, Top = 26, Width = 170 }, _room,
            new Label { Text = "服务端口：", Left = 12, Top = 58, Width = 170 }, _port,
            new Label { Text = "空闲休眠（秒，0 = 不休眠）：", Left = 12, Top = 90, Width = 170 }, _idle,
        });
        AddRow(page, info, 136);

        var security = Group("访问与退出密码", 124);
        var setPassword = Btn("设置 / 修改退出密码", 160);
        setPassword.Left = 12; setPassword.Top = 52;
        setPassword.Click += (_, _) => SetPassword();
        var note = Txt("密码以 PBKDF2-HMAC-SHA256 加盐哈希保存在 data/config.json，不会明文存储或返回给管理端。",
                       12, 86, 620);
        note.ForeColor = Muted;
        security.Controls.AddRange(new Control[] { _requireAuth, setPassword, note });
        AddRow(page, security, 132);

        var startup = Group("启动方式", 76);
        startup.Controls.Add(_startMinimized);
        AddRow(page, startup, 84);

        var lan = Group("局域网访问地址", 108);
        _addresses.ForeColor = Accent;
        _addresses.Height = 70;
        lan.Controls.Add(_addresses);
        AddRow(page, lan, 116);

        var portable = Txt("同一局域网内的电脑 / 手机浏览器打开上面的地址即可进入管理端。本程序不写注册表、不安装系统服务，删除整个文件夹即完成卸载。",
                           12, 8, 620);
        portable.Height = 44; portable.ForeColor = Muted;
        AddRow(page, portable, 60);
        return tab;
    }

    // ---------------------------------------------------------------- data
    private void LoadFromConfig()
    {
        var cfg = _app.Store.Snapshot();
        var resolution = $"{cfg.Camera.Width}x{cfg.Camera.Height}";
        _resolution.SelectedItem = AppConfig.Resolutions.Contains(resolution) ? resolution : "1280x720";
        _fps.SelectedItem = cfg.Camera.Fps.ToString();
        if (_fps.SelectedIndex < 0) _fps.SelectedIndex = 2;
        _quality.Value = cfg.Camera.Quality;
        _qualityLabel.Text = cfg.Camera.Quality.ToString();
        _remoteSelect.Checked = cfg.Camera.RemoteSelect;

        foreach (var (id, name) in AppConfig.TtsVoices) _voiceMap[name] = id;
        _voice.Items.AddRange(_voiceMap.Keys.Cast<object>().ToArray());
        var currentVoice = _voiceMap.FirstOrDefault(kv => kv.Value == cfg.Tts.Voice).Key;
        if (currentVoice is not null) _voice.SelectedItem = currentVoice;
        else if (_voice.Items.Count > 0) _voice.SelectedIndex = 0;
        _ttsEnabled.Checked = cfg.Tts.Enabled;
        _rate.SelectedItem = cfg.Tts.Rate;
        _volume.SelectedItem = cfg.Tts.Volume;
        _urgentAlert.Checked = cfg.Tts.UrgentAlert;

        _room.Text = cfg.RoomName;
        _port.Text = cfg.Port.ToString();
        _idle.Text = cfg.IdleTimeoutSeconds.ToString();
        _requireAuth.Checked = cfg.RequireAuth;
        _startMinimized.Checked = cfg.StartMinimized;

        RefreshDevices();
        UpdatePlayerStatus();
    }

    private void RefreshDevices()
    {
        _app.InvalidateNames();
        _deviceMap.Clear();
        var devices = _app.Names.BuildLocalDevices(_app.Devices.Indices());
        foreach (var device in devices)
        {
            var label = CameraNameResolver.LabelFor(device);
            _deviceMap[label] = device.index;
        }
        _device.Items.Clear();
        foreach (var label in _deviceMap.Keys) _device.Items.Add(label);
        var current = _app.Store.Snapshot().Camera.Index;
        var selected = _deviceMap.FirstOrDefault(kv => kv.Value == current).Key;
        if (selected is not null) _device.SelectedItem = selected;
        else if (_device.Items.Count > 0) _device.SelectedIndex = 0;
    }

    private void UpdatePlayerStatus()
    {
        _playerStatus.Text = "播放器：系统音频  ·  已播报 0 次  ·  Edge TTS 合成由管理端 /api/tts/speak 触发";
    }

    private void SaveSettings()
    {
        try
        {
            var oldPort = _app.Store.Snapshot().Port;
            _app.Store.Update(cfg =>
            {
                if (_device.SelectedItem is string label && _deviceMap.TryGetValue(label, out var index) && index >= 0)
                    cfg.Camera.Index = index;
                var parts = (_resolution.SelectedItem?.ToString() ?? "1280x720").Split('x');
                if (parts.Length == 2 && int.TryParse(parts[0], out var width) && int.TryParse(parts[1], out var height))
                {
                    cfg.Camera.Width = width;
                    cfg.Camera.Height = height;
                }
                if (int.TryParse(_fps.SelectedItem?.ToString(), out var fps)) cfg.Camera.Fps = fps;
                cfg.Camera.Quality = _quality.Value;
                cfg.Camera.RemoteSelect = _remoteSelect.Checked;

                cfg.Tts.Enabled = _ttsEnabled.Checked;
                if (_voice.SelectedItem is string voiceName && _voiceMap.TryGetValue(voiceName, out var voiceId))
                    cfg.Tts.Voice = voiceId;
                cfg.Tts.Rate = _rate.SelectedItem?.ToString() ?? cfg.Tts.Rate;
                cfg.Tts.Volume = _volume.SelectedItem?.ToString() ?? cfg.Tts.Volume;
                cfg.Tts.UrgentAlert = _urgentAlert.Checked;

                cfg.RoomName = string.IsNullOrWhiteSpace(_room.Text) ? "未命名班级" : _room.Text.Trim();
                if (int.TryParse(_port.Text, out var port)) cfg.Port = port;
                if (int.TryParse(_idle.Text, out var idle)) cfg.IdleTimeoutSeconds = idle;
                if (_requireAuth.Checked && !_app.Store.HasPassword)
                    throw new InvalidOperationException("启用管理密码登录前，请先设置退出密码");
                cfg.RequireAuth = _requireAuth.Checked;
                cfg.StartMinimized = _startMinimized.Checked;
            });

            var updated = _app.Store.Snapshot();
            _app.Camera.ApplyConfig(updated.Camera);
            if (updated.RequireAuth) _app.RevokeTokens();
            if (updated.Port != oldPort) _ = _app.RestartServiceAsync();

            MessageBox.Show(this,
                updated.Port != oldPort ? "设置已保存，服务已按新端口重启。" : "设置已保存并即时生效。",
                "已保存", MessageBoxButtons.OK, MessageBoxIcon.Information);
            UpdatePlayerStatus();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "设置无效", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void SetPassword()
    {
        if (_app.Store.HasPassword)
        {
            using var verify = new PasswordDialog("验证", "请输入当前退出密码：");
            if (verify.ShowDialog(this) != DialogResult.OK) return;
            if (!_app.Store.VerifyPassword(verify.EnteredPassword))
            {
                MessageBox.Show(this, "当前密码不正确，未作修改。", "密码错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
        }
        using var first = new PasswordDialog("设置退出密码", "新密码（至少 4 位）：");
        if (first.ShowDialog(this) != DialogResult.OK) return;
        if (first.EnteredPassword.Length < 4)
        {
            MessageBox.Show(this, "密码至少 4 位，未作修改。", "无效",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        using var second = new PasswordDialog("设置退出密码", "再次输入：");
        if (second.ShowDialog(this) != DialogResult.OK) return;
        if (first.EnteredPassword != second.EnteredPassword)
        {
            MessageBox.Show(this, "两次输入不一致，未作修改。", "不一致",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        _app.Store.SetPassword(first.EnteredPassword);
        MessageBox.Show(this, "退出密码已保存到 data/config.json。", "完成",
            MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void RefreshStatus()
    {
        try
        {
            var running = _app.Server.IsRunning;
            var failed = !string.IsNullOrEmpty(_app.Server.LastError);
            _serviceStatus.Text = running ? "● 运行中" : (failed ? "■ 启动失败" : "■ 已停止");
            _serviceStatus.ForeColor = running ? Color.FromArgb(22, 163, 74) : Danger;
            _connStatus.Text = $"连接 {_app.Runtime.ActiveCount}"
                               + (_app.Runtime.Sleeping ? " · 休眠中" : "");
            var cam = _app.Camera.Status();
            _camStatus.Text = $"摄像头：{cam.backend} · {cam.measured_fps:0.0} fps";
            var addresses = LanAddresses(_app.Store.Snapshot().Port);
            _address.Text = addresses.Length > 0 ? addresses[0] : $"http://127.0.0.1:{_app.Store.Snapshot().Port}/";
            _addresses.Text = string.Join("\n", addresses.Length > 0
                ? addresses : new[] { $"http://127.0.0.1:{_app.Store.Snapshot().Port}/" });
            _errorStatus.Text = failed ? "⚠ " + _app.Server.LastError : "";
            _app.SetTrayStatus(running ? "● 服务运行中" : (failed ? "■ 服务启动失败" : "■ 服务已停止"));
        }
        catch (Exception) { /* status refresh must never crash the UI */ }
    }

    private static string[] LanAddresses(int port)
    {
        var ips = new List<string>();
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

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!_app.ExitRequested)
        {
            e.Cancel = true;
            _app.HideToTray();
            return;
        }
        _timer.Stop();
        base.OnFormClosing(e);
    }
}
