using System.Collections.Concurrent;
using System.Diagnostics;
using OpenGeul.Office.Core;

public static class WorkerMenuCommandTests
{
    public static IEnumerable<(string Name, Func<Task> Run)> Cases()
    {
        yield return ("Worker forwards native Home Exit and HWP creation to the owning application", async () =>
        {
            await WithWorker(async client =>
            {
                var events = new ConcurrentBag<WorkerCommand>();
                var complete = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                client.CommandReceived += command =>
                {
                    events.Add(command);
                    if (events.Count == 3) complete.TrySetResult(true);
                };
                await client.SendAsync("menu-events", new { });
                try { await complete.Task.WaitAsync(TimeSpan.FromSeconds(3)); }
                catch (TimeoutException) { throw new Exception("Native Home or Exit was dropped by the worker command boundary"); }
                var actual = events.Select(e => e.Command + ":" + e.Module).Order().ToArray();
                if (!actual.SequenceEqual(new[] { "exit:writer", "home:writer", "new:hwp" }))
                    throw new Exception("Native application commands changed their owner or scope");
            });
        });
        yield return ("Worker preserves the native integration error code for safe session termination", async () =>
        {
            await WithWorker(async client =>
            {
                SuiteException? failure = null;
                try { await client.SendAsync("menu-error", new { }); }
                catch (SuiteException error) { failure = error; }
                if (failure is null || !Equals(typeof(SuiteException).GetProperty("WorkerCode")?.GetValue(failure), "native_menu_unavailable"))
                    throw new Exception("The worker boundary lost the native menu failure classification");
            });
        });
    }

    public static async Task<int> RunAsync()
    {
        var errors = new List<Exception>(); var count = 0;
        foreach (var (name, run) in Cases())
        {
            try { await run(); count++; }
            catch (Exception error) { errors.Add(new Exception(name, error)); }
        }
        if (errors.Count > 0) throw new AggregateException(errors);
        return count;
    }

    private static async Task WithWorker(Func<WorkerClient, Task> run)
    {
        var folder = Path.Combine(Path.GetTempPath(), "opengeul-menu-client-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        WorkerClient? client = null;
        try
        {
            var script = Path.Combine(folder, "worker.py");
            File.WriteAllText(script, """
                import json,sys
                for line in sys.stdin:
                    request=json.loads(line)
                    if request['command']=='menu-events':
                        for command,module in [('new','hwp'),('home','writer'),('exit','writer')]:
                            print(json.dumps(dict(event='command',command=command,module=module)),flush=True)
                    if request['command']=='menu-error':
                        print(json.dumps(dict(id=request['id'],ok=False,error=dict(code='native_menu_unavailable',message='synthetic menu failure'))),flush=True)
                    else:
                        print(json.dumps(dict(id=request['id'],ok=True,result={})),flush=True)
                    if request['command']=='shutdown':break
                """);
            var start = new ProcessStartInfo { FileName = OperatingSystem.IsWindows() ? "python" : "python3" };
            start.ArgumentList.Add("-u"); start.ArgumentList.Add(script);
            client = WorkerClient.Start(start, TimeSpan.FromSeconds(5));
            await run(client);
        }
        finally
        {
            if (client is not null) await client.DisposeAsync();
            Directory.Delete(folder, recursive: true);
        }
    }
}
