namespace ClassConnector.Core.Camera;

/// <summary>
/// Lowercase property names are intentional: ASP.NET Core serializes them
/// verbatim, which keeps the wire format compatible with the existing
/// <c>manager/app.js</c> (dev.name / dev.index / d.locked / d.current).
/// </summary>
public sealed class CameraDevice
{
    public int index { get; set; }
    public string name { get; set; } = "";
    public int width { get; set; }
    public int height { get; set; }
}

public sealed class CameraDevicesView
{
    public List<CameraDevice> devices { get; set; } = new();
    public int current { get; set; }
    public bool locked { get; set; }
}

public sealed class CameraStatusView
{
    public string backend { get; set; } = "test-pattern";
    public bool available { get; set; }
    public int device_index { get; set; }
    public int width { get; set; }
    public int height { get; set; }
    public int fps { get; set; }
    public int quality { get; set; }
    public int actual_width { get; set; }
    public int actual_height { get; set; }
    public double measured_fps { get; set; }
    public long frames { get; set; }
    public int subscribers { get; set; }
    public bool paused { get; set; }
    public string last_error { get; set; } = "";
    public bool camera_select_locked { get; set; }
}
