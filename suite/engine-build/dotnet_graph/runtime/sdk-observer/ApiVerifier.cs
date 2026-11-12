using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

namespace OpenGeulSynthetic;

// Runs only on the pinned synthetic fixture. It never loads a user document.
public static class ApiVerifier
{
    private static readonly string[] Names = { "net_basetypes", "net_uretypes", "net_oootypes", "net_bridge" };
    private static readonly string[] Types = { "BaseValue", "UreValue", "OfficeValue", "BridgeValue" };
    private static readonly Version ExpectedVersion = new Version(0, 1, 0, 0);
    private const int MaxAssemblyBytes = 16 * 1024 * 1024;

    public static int Main(string[] args)
    {
        string root, output; int expectedBase;
        try
        {
            if (args.Length != 3) return 2;
            root = Canonical(args[0]); output = Canonical(args[2]);
            if (!int.TryParse(args[1], NumberStyles.None, CultureInfo.InvariantCulture, out expectedBase) ||
                (expectedBase != 1 && expectedBase != 2)) return 2;
            CheckDirectory(root);
            if (!string.Equals(Path.GetDirectoryName(output), Path.Combine(root, "observations"), StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.GetExtension(output), ".json", StringComparison.Ordinal)) return 2;
            CheckDirectory(Path.GetDirectoryName(output)!);
            if (File.Exists(output) || Directory.Exists(output) || File.Exists(output + ".pending") || Directory.Exists(output + ".pending")) return 2;
        }
        catch (Exception) { return 2; }
        var receipt = new VerifierReceipt { ExpectedBase = expectedBase, ErrorCode = 3 };
        var held = new List<FileStream>();
        try
        {
            var paths = Names.Select(name => Path.Combine(root, "DotnetLibrary", name, name + ".dll")).ToArray();
            var hashes = new byte[4][];
            for (var index = 0; index < 4; index++)
            {
                CheckDirectory(Path.GetDirectoryName(paths[index])!);
                if ((File.GetAttributes(paths[index]) & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException();
                var stream = new FileStream(paths[index], FileMode.Open, FileAccess.Read, FileShare.Read);
                held.Add(stream);
                if (stream.Length <= 0 || stream.Length > MaxAssemblyBytes) throw new InvalidOperationException();
                hashes[index] = SHA256.HashData(stream); stream.Position = 0;
            }
            var loader = new OwnedContext(paths);
            var assemblies = paths.Select(loader.LoadFromAssemblyPath).ToArray();
            var expected = new[] { expectedBase, expectedBase + 2, expectedBase + 6, expectedBase + 10 };
            for (var index = 0; index < 4; index++)
            {
                var assembly = assemblies[index]; var name = assembly.GetName();
                var own = string.Equals(Path.GetFullPath(assembly.Location), paths[index], StringComparison.OrdinalIgnoreCase);
                var exported = assembly.GetExportedTypes();
                var type = exported.SingleOrDefault();
                var metadata = own && name.Name == Names[index] && name.Version == ExpectedVersion &&
                    string.IsNullOrEmpty(name.CultureName) && (name.GetPublicKeyToken()?.Length ?? 0) == 0 &&
                    type is not null && type.FullName == "OpenGeulSynthetic." + Types[index] &&
                    type.IsPublic && type.IsAbstract && type.IsSealed && !type.IsGenericType;
                if (metadata)
                {
                    var methods = type!.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
                    var method = methods.SingleOrDefault();
                    metadata = method is not null && method.Name == "Read" && method.ReturnType == typeof(int) &&
                        !method.IsGenericMethod && method.GetParameters().Length == 0 &&
                        type.GetFields(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly).Length == 0 &&
                        type.GetProperties(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly).Length == 0 &&
                        type.GetEvents(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly).Length == 0;
                    if (metadata) receipt.Values[index] = (int)method!.Invoke(null, null)!;
                }
                receipt.PublicApi[index] = metadata && receipt.Values[index] == expected[index] ? 1 : 0;
                var references = assembly.GetReferencedAssemblies().Where(item => Names.Contains(item.Name, StringComparer.Ordinal)).ToArray();
                var expectedReference = index == 0 ? Array.Empty<string>() : new[] { Names[index == 1 ? 0 : 1] };
                receipt.ReferenceClosure[index] = references.Length == expectedReference.Length &&
                    references.Select(item => item.Name!).OrderBy(item => item, StringComparer.Ordinal).SequenceEqual(expectedReference) &&
                    references.All(item => item.Version == ExpectedVersion && string.IsNullOrEmpty(item.CultureName) &&
                        (item.GetPublicKeyToken()?.Length ?? 0) == 0) ? 1 : 0;
            }
            var copy = 0;
            foreach (var owner in new[] { 2, 3 })
                foreach (var dependency in new[] { 1, 0 })
                {
                    var path = Path.Combine(root, "DotnetLibrary", Names[owner], Names[dependency] + ".dll");
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException();
                    using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                    if (stream.Length <= 0 || stream.Length > MaxAssemblyBytes) throw new InvalidOperationException();
                    receipt.CopiedReferences[copy++] = stream.Length == held[dependency].Length &&
                        CryptographicOperations.FixedTimeEquals(SHA256.HashData(stream), hashes[dependency]) ? 1 : 0;
                }
            receipt.Known = 1;
            receipt.Success = receipt.PublicApi.All(value => value == 1) && receipt.ReferenceClosure.All(value => value == 1) &&
                receipt.CopiedReferences.All(value => value == 1) ? 1 : 0;
            receipt.ErrorCode = receipt.Success == 1 ? 0 : 3;
        }
        catch (Exception) { receipt.Known = 0; receipt.Success = 0; receipt.ErrorCode = 3; }
        finally
        {
            foreach (var stream in held)
                try { stream.Dispose(); }
                catch (Exception) { receipt.Known = 0; receipt.Success = 0; receipt.ErrorCode = 3; }
        }
        try
        {
            var bytes = JsonSerializer.SerializeToUtf8Bytes(receipt, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
            if (bytes.Length > 16384) return 4;
            CheckDirectory(Path.GetDirectoryName(output)!);
            if (File.Exists(output) || Directory.Exists(output)) return 4;
            using (var stream = new FileStream(output + ".pending", FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes); stream.Flush(true); }
            File.Move(output + ".pending", output, false);
        }
        catch (Exception) { return 4; }
        return receipt.Success == 1 ? 0 : 3;
    }

    private sealed class OwnedContext : AssemblyLoadContext
    {
        private readonly string[] paths;
        internal OwnedContext(string[] paths) : base(isCollectible: false) { this.paths = paths; }
        protected override Assembly? Load(AssemblyName name)
        {
            var index = Array.FindIndex(Names, item => item == name.Name);
            if (index < 0) return null;
            if (name.Version != ExpectedVersion || !string.IsNullOrEmpty(name.CultureName) || (name.GetPublicKeyToken()?.Length ?? 0) != 0)
                throw new InvalidOperationException();
            return LoadFromAssemblyPath(paths[index]);
        }
    }

    private static string Canonical(string path)
    {
        if (string.IsNullOrEmpty(path) || path.Any(c => char.IsControl(c) || c == ';') ||
            !Path.IsPathFullyQualified(path) || path.StartsWith(@"\\", StringComparison.Ordinal)) throw new InvalidOperationException();
        var full = Path.GetFullPath(path);
        if (!string.Equals(path, full, StringComparison.Ordinal)) throw new InvalidOperationException();
        return full;
    }

    private static void CheckDirectory(string path)
    {
        for (var info = new DirectoryInfo(path); info is not null; info = info.Parent)
            if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException();
    }

    private sealed class VerifierReceipt
    {
        public int SchemaVersion { get; set; } = 1;
        public int ExpectedBase { get; set; }
        public int Known { get; set; }
        public int Success { get; set; }
        public int ErrorCode { get; set; }
        public int[] Values { get; set; } = new int[4];
        public int[] PublicApi { get; set; } = new int[4];
        public int[] ReferenceClosure { get; set; } = new int[4];
        public int[] CopiedReferences { get; set; } = new int[4];
    }
}
