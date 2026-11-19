using System.Drawing;
using System.Windows.Forms;

namespace ClassConnector.App.Forms;

/// <summary>Small modal password prompt (no dependency on VisualBasic.Interaction).</summary>
public sealed class PasswordDialog : Form
{
    private readonly TextBox _input;

    public string EnteredPassword => _input.Text;

    public PasswordDialog(string title, string prompt)
    {
        Text = title;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MinimizeBox = false;
        MaximizeBox = false;
        ClientSize = new Size(380, 150);
        ShowInTaskbar = false;

        var promptLabel = new Label
        {
            Text = prompt,
            Left = 18, Top = 20, Width = 344,
            AutoSize = false,
        };
        _input = new TextBox
        {
            Left = 18, Top = 50, Width = 344,
            UseSystemPasswordChar = true,
        };
        var ok = new Button
        {
            Text = "确定", Left = 196, Top = 92, Width = 80,
            DialogResult = DialogResult.OK,
        };
        var cancel = new Button
        {
            Text = "取消", Left = 282, Top = 92, Width = 80,
            DialogResult = DialogResult.Cancel,
        };

        Controls.AddRange(new Control[] { promptLabel, _input, ok, cancel });
        AcceptButton = ok;
        CancelButton = cancel;
        _input.Select();
    }
}
