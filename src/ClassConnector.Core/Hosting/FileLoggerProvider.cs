using System.Text;
using Microsoft.Extensions.Logging;

namespace ClassConnector.Core.Hosting;

/// <summary>
/// All ASP.NET Core / Kestrel logs go to a file. A WinExe has no console, so
/// writing to stdout would be noise at best and an exception at worst - this
/// is the .NET-side fix for the old "exe starts but the service does not"
/// failure caused by the Python uvicorn colour formatter touching sys.stdout.
/// </summary>
public sealed class FileLoggerProvider : ILoggerProvider
{
    private readonly string _path;
    private readonly object _sync = new();

    public FileLoggerProvider(string path) => _path = path;

    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);
    public void Dispose() { }

    internal void Write(string line)
    {
        lock (_sync)
        {
            try
            {
                var dir = Path.GetDirectoryName(_path);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.AppendAllText(_path, line + Environment.NewLine, new UTF8Encoding(false));
            }
            catch (Exception) { /* logging must never crash the app */ }
        }
    }

    private sealed class FileLogger : ILogger
    {
        private readonly FileLoggerProvider _owner;
        private readonly string _category;

        public FileLogger(FileLoggerProvider owner, string category)
        {
            _owner = owner;
            _category = category;
        }

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state,
                                Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel)) return;
            var message = formatter(state, exception);
            if (exception is not null) message += " | " + exception.Message;
            _owner.Write($"{DateTime.Now:yyyy-MM-dd HH:mm:ss} [{logLevel}] {_category}: {message}");
        }
    }
}
