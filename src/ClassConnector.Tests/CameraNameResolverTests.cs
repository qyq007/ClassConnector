using ClassConnector.Core.Camera;
using Xunit;

namespace ClassConnector.Tests;

public class CameraNameResolverTests
{
    private static readonly string[] Names = { "Integrated Camera", "Logitech C920 HD Pro Webcam" };

    [Fact]
    public void NameFor_ReturnsRealFriendlyName()
    {
        var resolver = new CameraNameResolver(new StaticNames(Names));
        Assert.Equal("Integrated Camera", resolver.NameFor(0));
        Assert.Equal("Logitech C920 HD Pro Webcam", resolver.NameFor(1));
    }

    [Fact]
    public void NameFor_FallsBackToIndexedLabel()
    {
        var resolver = new CameraNameResolver(new StaticNames(Names));
        Assert.Equal("摄像头 5", resolver.NameFor(5));
        Assert.Equal("摄像头 0", new CameraNameResolver().NameFor(0));
    }

    [Fact]
    public void Clean_RemovesControlCharactersAndTrims()
    {
        Assert.Equal("USB Camera", CameraNameResolver.Clean("  USB\0  Camera\r\n  "));
        Assert.Equal("", CameraNameResolver.Clean(null));
        Assert.Equal("", CameraNameResolver.Clean("   "));
    }

    [Fact]
    public void BuildLocalDevices_ListsEveryCameraWithItsName()
    {
        var resolver = new CameraNameResolver(new StaticNames(Names));
        var devices = resolver.BuildLocalDevices(new[] { 0, 1 });
        Assert.Equal(2, devices.Count);
        Assert.Equal("Integrated Camera", devices[0].name);
        Assert.Equal("Logitech C920 HD Pro Webcam", devices[1].name);
        Assert.Equal(0, devices[0].index);
        Assert.Equal(1, devices[1].index);
    }

    [Fact]
    public void BuildLocalDevices_MakesDuplicateNamesDistinguishable()
    {
        var resolver = new CameraNameResolver(new StaticNames(new[] { "USB Camera", "USB Camera" }));
        var devices = resolver.BuildLocalDevices(new[] { 0, 1 });
        Assert.NotEqual(devices[0].name, devices[1].name);
    }

    [Fact]
    public void LockedRemoteView_OnlyExposesTheHostSelectedDevice()
    {
        var resolver = new CameraNameResolver(new StaticNames(Names));
        var view = resolver.BuildRemoteView(1, new[] { 0, 1 }, remoteSelectAllowed: false);
        Assert.True(view.locked);
        Assert.Single(view.devices);
        Assert.Equal(1, view.devices[0].index);
        Assert.Contains("Logitech C920 HD Pro Webcam", view.devices[0].name);
        Assert.Equal(1, view.current);
    }

    [Fact]
    public void UnlockedRemoteView_ListsAllDevicesWithRealNames()
    {
        var resolver = new CameraNameResolver(new StaticNames(Names));
        var view = resolver.BuildRemoteView(0, new[] { 0, 1 }, remoteSelectAllowed: true);
        Assert.False(view.locked);
        Assert.Equal(2, view.devices.Count);
        Assert.Equal("Integrated Camera", view.devices[0].name);
    }

    [Fact]
    public void CachedProvider_AvoidsRepeatedSlowEnumeration()
    {
        var inner = new CountingNames();
        var cached = new CachedCameraNameProvider(inner, TimeSpan.FromMinutes(1));
        Assert.Equal(2, cached.GetFriendlyNames().Count);
        Assert.Equal(2, cached.GetFriendlyNames().Count);
        Assert.Equal(1, inner.Calls);
        cached.Invalidate();
        Assert.Equal(2, cached.GetFriendlyNames().Count);
        Assert.Equal(2, inner.Calls);
    }

    [Fact]
    public void CachedProvider_SwallowsProviderErrors()
    {
        var cached = new CachedCameraNameProvider(new ThrowingNames());
        Assert.Empty(cached.GetFriendlyNames());
    }

    private sealed class ThrowingNames : ICameraNameProvider
    {
        public IReadOnlyList<string> GetFriendlyNames() => throw new InvalidOperationException("WMI blocked");
    }
}
