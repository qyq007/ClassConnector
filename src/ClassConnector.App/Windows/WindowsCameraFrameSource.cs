using System.Drawing;
using ClassConnector.Core.Camera;
using ClassConnector.Core.Configuration;
using OpenCvSharp;

namespace ClassConnector.App.Windows;

/// <summary>
/// OpenCV/DirectShow capture. If no physical camera is available the source
/// stays alive and produces an animated test pattern, so the MJPEG stream is
/// always live and the service never fails to start because of a missing device.
/// </summary>
public sealed class WindowsCameraFrameSource : ICameraFrameSource
{
    private VideoCapture? _capture;
    private CameraConfig _config = new();
    private string _error = "";

    public bool IsRealDevice => _capture is not null;
    public (int Width, int Height) Size => (_config.Width, _config.Height);

    public bool Open(CameraConfig config)
    {
        Close();
        _config = config;
        if (!OperatingSystem.IsWindows()) { _error = "非 Windows 平台"; return true; }

        try
        {
            var capture = new VideoCapture(config.Index, VideoCaptureAPIs.DSHOW);
            if (!capture.IsOpened())
            {
                capture.Release();
                capture.Dispose();
                _error = $"摄像头 {config.Index} 不可用，正在使用测试画面";
            }
            else
            {
                capture.Set(VideoCaptureProperties.FrameWidth, config.Width);
                capture.Set(VideoCaptureProperties.FrameHeight, config.Height);
                capture.Set(VideoCaptureProperties.Fps, config.Fps);
                _capture = capture;
                _error = "";
            }
        }
        catch (Exception ex)
        {
            _error = $"打开摄像头失败：{ex.Message}";
        }
        // Always "open": the test pattern keeps the LAN manager usable.
        return true;
    }

    public byte[]? ReadJpeg(int quality)
    {
        var capture = _capture;
        if (capture is not null)
        {
            try
            {
                using var frame = new Mat();
                if (capture.Read(frame) && !frame.Empty())
                {
                    byte[] encoded;
                    Cv2.ImEncode(".jpg", frame, out encoded,
                        new ImageEncodingParam(ImwriteFlags.JpegQuality, Math.Clamp(quality, 10, 100)));
                    if (encoded.Length > 0) return encoded;
                }
            }
            catch (Exception ex)
            {
                _error = $"读取摄像头失败：{ex.Message}";
                Close();
            }
        }
        return RenderTestPattern(quality);
    }

    private byte[] RenderTestPattern(int quality)
    {
        try
        {
            var width = Math.Clamp(_config.Width, 320, 1920);
            var height = Math.Clamp(_config.Height, 240, 1080);
            using var image = new Mat(height, width, MatType.CV_8UC3, new Scalar(42, 23, 15));
            var seconds = DateTime.Now.TimeOfDay.TotalSeconds;
            var cx = width / 2 + (int)(width / 3.0 * Math.Sin(seconds * 0.8));
            var cy = height / 2 + (int)(height / 4.0 * Math.Cos(seconds * 0.6));
            Cv2.Circle(image, cx, cy, Math.Max(20, height / 12), new Scalar(235, 99, 37), -1);

            var scale = Math.Max(0.6, height / 900.0);
            Cv2.PutText(image, "ClassConnector TEST PATTERN",
                new OpenCvSharp.Point(width / 16, height / 7),
                HersheyFonts.HersheySimplex, scale * 1.4, Scalar.White, 2);
            Cv2.PutText(image, _error,
                new OpenCvSharp.Point(width / 16, height / 7 + (int)(40 * scale)),
                HersheyFonts.HersheySimplex, scale, new Scalar(21, 204, 250), 1);
            Cv2.PutText(image, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"),
                new OpenCvSharp.Point(width / 16, height - height / 10),
                HersheyFonts.HersheySimplex, scale, new Scalar(184, 163, 148), 1);

            byte[] bytes;
            Cv2.ImEncode(".jpg", image, out bytes,
                new ImageEncodingParam(ImwriteFlags.JpegQuality, Math.Clamp(quality, 10, 100)));
            return bytes;
        }
        catch (Exception)
        {
            return ClassConnector.Core.Imaging.PlaceholderImages.JpegBytes;
        }
    }

    private void Close()
    {
        var capture = _capture;
        _capture = null;
        try { capture?.Release(); capture?.Dispose(); }
        catch (Exception) { /* device already gone */ }
    }

    public void Dispose() => Close();
}
