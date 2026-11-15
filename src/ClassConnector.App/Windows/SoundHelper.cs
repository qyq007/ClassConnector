using System.Media;
using System.Text;

namespace ClassConnector.App.Windows;

/// <summary>
/// Small dependency-free WAV tone used by the "试听播报 / 试听警报音" buttons.
/// No ffmpeg / pygame / ffplay needed, unlike the previous Python build.
/// </summary>
public static class SoundHelper
{
    public static void Play(bool urgent)
    {
        _ = Task.Run(() =>
        {
            try
            {
                var wav = BuildWav(urgent ? 920 : 620, urgent ? 800 : 380);
                using var stream = new MemoryStream(wav);
                using var player = new SoundPlayer(stream);
                player.PlaySync();
            }
            catch (Exception) { /* no audio device - ignore */ }
        });
    }

    private static byte[] BuildWav(int frequency, int durationMs)
    {
        const int sampleRate = 16000;
        var samples = sampleRate * durationMs / 1000;
        var pcm = new byte[samples * 2];
        for (var i = 0; i < samples; i++)
        {
            var attack = Math.Min(1.0, i / (sampleRate * 0.02));
            var release = Math.Min(1.0, (samples - i) / (sampleRate * 0.06));
            var envelope = attack * release;
            var value = (short)(Math.Sin(2 * Math.PI * frequency * i / sampleRate) * 12000 * envelope);
            pcm[i * 2] = (byte)(value & 0xFF);
            pcm[i * 2 + 1] = (byte)((value >> 8) & 0xFF);
        }

        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write(Encoding.ASCII.GetBytes("RIFF"));
        writer.Write(36 + pcm.Length);
        writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
        writer.Write(16);
        writer.Write((short)1);          // PCM
        writer.Write((short)1);          // mono
        writer.Write(sampleRate);
        writer.Write(sampleRate * 2);    // byte rate
        writer.Write((short)2);          // block align
        writer.Write((short)16);         // bits per sample
        writer.Write(Encoding.ASCII.GetBytes("data"));
        writer.Write(pcm.Length);
        writer.Write(pcm);
        writer.Flush();
        return stream.ToArray();
    }
}
