using ClassConnector.Core.Camera;

namespace ClassConnector.App.Windows;

/// <summary>
/// Device indices shown in the local settings window. Driven by the number of
/// friendly names reported by the OS, so a machine with two webcams lists both
/// even before they are opened for capture.
/// </summary>
public sealed class DeviceCatalog
{
    private readonly ICameraNameProvider _names;

    public DeviceCatalog(ICameraNameProvider names) => _names = names;

    public IReadOnlyList<int> Indices()
    {
        var count = _names.GetFriendlyNames().Count;
        if (count <= 0) return new[] { 0 };
        return Enumerable.Range(0, Math.Min(count, 16)).ToArray();
    }

    public (int Width, int Height) SizeOf(int index) => (0, 0);
}
