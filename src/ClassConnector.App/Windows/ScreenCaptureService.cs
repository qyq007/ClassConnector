using System.Drawing;
using System.Drawing.Imaging;
using System.Windows.Forms;
using ClassConnector.Core.Imaging;

namespace ClassConnector.App.Windows;

/// <summary>Screen enumeration and PNG capture for the web manager.</summary>
public static class ScreenCaptureService
{
    public static int DisplayCount()
    {
        try { return Math.Max(1, Screen.AllScreens.Length); }
        catch (Exception) { return 1; }
    }

    public static (byte[] Bytes, bool Fallback, object Meta) Capture(int display, float scale)
    {
        try
        {
            var screens = Screen.AllScreens;
            var bounds = screens[Math.Clamp(display, 0, screens.Length - 1)].Bounds;
            using var bitmap = new Bitmap(bounds.Width, bounds.Height);
            using (var graphics = Graphics.FromImage(bitmap))
                graphics.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size);

            Image output = bitmap;
            Bitmap? scaled = null;
            if (scale > 0.05f && Math.Abs(scale - 1.0f) > 0.01f)
            {
                scaled = new Bitmap(bitmap,
                    Math.Max(1, (int)(bitmap.Width * scale)),
                    Math.Max(1, (int)(bitmap.Height * scale)));
                output = scaled;
            }

            var outWidth = output.Width;
            var outHeight = output.Height;
            using var stream = new MemoryStream();
            output.Save(stream, ImageFormat.Png);
            var bytes = stream.ToArray();
            scaled?.Dispose();
            return (bytes, false, new { display, width = outWidth, height = outHeight, scale });
        }
        catch (Exception ex)
        {
            return (PlaceholderImages.PngBytes, true,
                    new { display, error = ex.Message, note = "截图不可用" });
        }
    }
}
