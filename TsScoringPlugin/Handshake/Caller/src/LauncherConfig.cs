using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

// ============================================================================
// PHASE E3 - the development launcher configuration of the Caller (read + validate, nothing else).
//
// File:   %LOCALAPPDATA%\Coruge-to\TS Scoring\launcher.json   (outside the repository, outside BVE's folders; written by the user)
// Absent: nothing is started and the manual way of running the application stays exactly as it is.
// Schema (version 1, UTF-8, ONE flat JSON object, no nesting, no comments):
//     { "schemaVersion": 1,                       optional, if present it must be 1
//       "mode": "development",                    required, exactly this text
//       "pythonExecutable": "X:\\...\\python.exe", required, absolute, an existing .exe (never pythonw.exe)
//       "scriptPath":       "X:\\...\\main.py",    required, absolute, an existing .py
//       "workingDirectory": "X:\\...\\" }          required, absolute, an existing directory
// Unknown keys are refused (a typo must not silently change what is started, and no secret / token field has a place here).
//
// Safety rules (all checked, none "repaired"): no environment-variable or relative-path expansion, no PATH lookup, no shell. A path must be
// "X:\dir\file" - drive letter, backslashes only, no "." / ".." / empty segment, no control character (NUL included), no quote, no
// < > | * ? %, no leading / trailing blank, at most 259 characters. The reasons are a fixed vocabulary: a path or a value from the file is
// NEVER copied into a reason (so a log line cannot leak it).
// Nothing in this file starts a process; the result is handed to AppProcessManager.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal enum LauncherConfigStatus
    {
        /// <summary>No launcher.json: the launch is not wanted. Not an error.</summary>
        Absent = 0,

        /// <summary>A file exists but does not satisfy the contract: nothing is started.</summary>
        Invalid,

        Loaded,
    }

    internal sealed class LauncherConfig
    {
        public string PythonExecutable;
        public string ScriptPath;
        public string WorkingDirectory;
    }

    internal sealed class LauncherConfigResult
    {
        public LauncherConfigStatus Status;

        /// <summary>Fixed-vocabulary code (see the constants of LauncherConfigLoader); empty when Loaded.</summary>
        public string Reason = string.Empty;

        public LauncherConfig Config;

        public static LauncherConfigResult Absent(string reason)
        {
            return new LauncherConfigResult { Status = LauncherConfigStatus.Absent, Reason = reason };
        }

        public static LauncherConfigResult Invalid(string reason)
        {
            return new LauncherConfigResult { Status = LauncherConfigStatus.Invalid, Reason = reason };
        }

        public static LauncherConfigResult Ok(LauncherConfig config)
        {
            return new LauncherConfigResult { Status = LauncherConfigStatus.Loaded, Config = config };
        }
    }

    internal static class LauncherConfigLoader
    {
        public const string CompanyFolder = "Coruge-to";
        public const string ProductFolder = "TS Scoring";
        public const string FileName = "launcher.json";
        public const int MaxFileBytes = 8192;
        public const int MaxPathChars = 259;
        public const string DevelopmentMode = "development";

        /// <summary>Offline-test hook only (null in production): replaces the default location, so a test never reads the user's real launcher.json.</summary>
        internal static string TestPath { get; set; }

        /// <summary>The location the production code reads: the test hook when set, otherwise the default.</summary>
        public static string ConfiguredPath()
        {
            return TestPath ?? DefaultPath();
        }

        /// <summary>The file location of the production build. Pure: creates nothing, reads nothing. Null when the OS gives no folder.</summary>
        public static string DefaultPath()
        {
            try
            {
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                if (string.IsNullOrEmpty(local))
                {
                    return null;
                }

                return Path.Combine(Path.Combine(Path.Combine(local, CompanyFolder), ProductFolder), FileName);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>Reads and validates the file. Never throws.</summary>
        public static LauncherConfigResult Load(string path)
        {
            try
            {
                if (string.IsNullOrEmpty(path))
                {
                    return LauncherConfigResult.Absent("no-location");
                }

                if (Directory.Exists(path))
                {
                    return LauncherConfigResult.Invalid("config-is-directory");
                }

                if (!File.Exists(path))
                {
                    return LauncherConfigResult.Absent("file-absent");
                }

                byte[] bytes;
                try
                {
                    using (FileStream fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    {
                        if (fs.Length > MaxFileBytes)
                        {
                            return LauncherConfigResult.Invalid("file-too-large");
                        }

                        bytes = new byte[(int)fs.Length];
                        int read = 0;
                        while (read < bytes.Length)
                        {
                            int n = fs.Read(bytes, read, bytes.Length - read);
                            if (n <= 0)
                            {
                                break;
                            }

                            read += n;
                        }

                        if (read != bytes.Length)
                        {
                            return LauncherConfigResult.Invalid("unreadable");
                        }
                    }
                }
                catch (FileNotFoundException)
                {
                    return LauncherConfigResult.Absent("file-absent");
                }
                catch (DirectoryNotFoundException)
                {
                    return LauncherConfigResult.Absent("file-absent");
                }
                catch
                {
                    return LauncherConfigResult.Invalid("unreadable");
                }

                return Parse(bytes);
            }
            catch
            {
                return LauncherConfigResult.Invalid("unreadable");
            }
        }

        /// <summary>Validates the bytes of a launcher.json (file system checks included). Never throws.</summary>
        public static LauncherConfigResult Parse(byte[] bytes)
        {
            try
            {
                int offset = 0;
                if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
                {
                    offset = 3; // a UTF-8 BOM (PowerShell / Notepad write one) is tolerated
                }

                string text;
                try
                {
                    text = new UTF8Encoding(false, true).GetString(bytes, offset, bytes.Length - offset);
                }
                catch (ArgumentException)
                {
                    return LauncherConfigResult.Invalid("not-utf8");
                }

                Dictionary<string, object> map;
                string reason;
                if (!FlatJson.TryParse(text, out map, out reason))
                {
                    return LauncherConfigResult.Invalid(reason);
                }

                foreach (string key in map.Keys)
                {
                    if (key != "schemaVersion" && key != "mode" && key != "pythonExecutable" && key != "scriptPath" && key != "workingDirectory")
                    {
                        return LauncherConfigResult.Invalid("unknown-key");
                    }
                }

                object version;
                if (map.TryGetValue("schemaVersion", out version))
                {
                    if (!(version is long) || (long)version != 1)
                    {
                        return LauncherConfigResult.Invalid("schema-version");
                    }
                }

                string mode;
                if (!TryGetString(map, "mode", out mode, out reason))
                {
                    return LauncherConfigResult.Invalid(reason);
                }

                if (!string.Equals(mode, DevelopmentMode, StringComparison.Ordinal))
                {
                    return LauncherConfigResult.Invalid("mode-not-development");
                }

                string python;
                string script;
                string work;
                if (!TryGetString(map, "pythonExecutable", out python, out reason)
                    || !TryGetString(map, "scriptPath", out script, out reason)
                    || !TryGetString(map, "workingDirectory", out work, out reason))
                {
                    return LauncherConfigResult.Invalid(reason);
                }

                if (!CheckPathText(python, false, out reason, "python")
                    || !CheckPathText(script, false, out reason, "script")
                    || !CheckPathText(work, true, out reason, "workdir"))
                {
                    return LauncherConfigResult.Invalid(reason);
                }

                if (!HasExtension(python, ".exe"))
                {
                    return LauncherConfigResult.Invalid("python-not-exe");
                }

                if (string.Equals(Path.GetFileName(python), "pythonw.exe", StringComparison.OrdinalIgnoreCase))
                {
                    return LauncherConfigResult.Invalid("python-is-pythonw");
                }

                if (!HasExtension(script, ".py"))
                {
                    return LauncherConfigResult.Invalid("script-not-py");
                }

                if (!File.Exists(python))
                {
                    return LauncherConfigResult.Invalid("python-not-found");
                }

                if (!File.Exists(script))
                {
                    return LauncherConfigResult.Invalid("script-not-found");
                }

                if (!Directory.Exists(work))
                {
                    return LauncherConfigResult.Invalid("workdir-not-found");
                }

                return LauncherConfigResult.Ok(new LauncherConfig { PythonExecutable = python, ScriptPath = script, WorkingDirectory = work });
            }
            catch
            {
                return LauncherConfigResult.Invalid("unreadable");
            }
        }

        private static bool TryGetString(Dictionary<string, object> map, string key, out string value, out string reason)
        {
            value = null;
            reason = string.Empty;
            object raw;
            if (!map.TryGetValue(key, out raw))
            {
                reason = "missing-" + key;
                return false;
            }

            value = raw as string;
            if (value == null)
            {
                reason = "wrong-type-" + key;
                return false;
            }

            if (value.Length == 0)
            {
                reason = "empty-" + key;
                return false;
            }

            return true;
        }

        private static bool HasExtension(string path, string extension)
        {
            return path.EndsWith(extension, StringComparison.OrdinalIgnoreCase) && path.Length > extension.Length && path[path.Length - extension.Length - 1] != '\\';
        }

        /// <summary>
        /// The text rules for one absolute Windows path. <paramref name="what"/> only prefixes the reason ("python", "script", "workdir").
        /// </summary>
        internal static bool CheckPathText(string value, bool allowTrailingSeparator, out string reason, string what)
        {
            reason = string.Empty;
            if (value.Length > MaxPathChars)
            {
                reason = what + "-too-long";
                return false;
            }

            foreach (char c in value)
            {
                if (c < 0x20 || c == 0x7F)
                {
                    reason = what + "-control-char";
                    return false;
                }

                if (c == '"')
                {
                    reason = what + "-quote";
                    return false;
                }

                if (c == '<' || c == '>' || c == '|' || c == '*' || c == '?')
                {
                    reason = what + "-invalid-char";
                    return false;
                }

                if (c == '%')
                {
                    reason = what + "-env-syntax";
                    return false;
                }

                if (c == '/')
                {
                    reason = what + "-not-normalized";
                    return false;
                }
            }

            if (value != value.Trim() || value[value.Length - 1] == '.' || (value[value.Length - 1] == ' '))
            {
                reason = what + "-not-normalized";
                return false;
            }

            bool drive = value.Length >= 3 && ((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z')) && value[1] == ':' && value[2] == '\\';
            if (!drive)
            {
                reason = what + "-not-absolute";
                return false;
            }

            string rest = value.Substring(3);
            if (rest.Length == 0)
            {
                return true; // a drive root such as C:\ (only meaningful as a directory; the file rules reject it by extension)
            }

            if (rest.EndsWith("\\", StringComparison.Ordinal))
            {
                if (!allowTrailingSeparator)
                {
                    reason = what + "-not-normalized";
                    return false;
                }

                rest = rest.Substring(0, rest.Length - 1);
            }

            if (rest.IndexOf(':') >= 0)
            {
                reason = what + "-invalid-char";
                return false;
            }

            foreach (string segment in rest.Split('\\'))
            {
                if (segment.Length == 0 || segment == "." || segment == "..")
                {
                    reason = what + "-not-normalized";
                    return false;
                }
            }

            return true;
        }
    }

    /// <summary>
    /// A deliberately tiny, strict JSON reader for ONE flat object whose values are strings or integers. Anything else (nesting, arrays,
    /// true / false / null, fractions, comments, duplicate keys, text after the object) is refused with a fixed reason. It exists so the Caller
    /// needs no extra framework reference for a four-line file.
    /// </summary>
    internal static class FlatJson
    {
        public static bool TryParse(string text, out Dictionary<string, object> map, out string reason)
        {
            map = new Dictionary<string, object>(StringComparer.Ordinal);
            reason = "json-invalid";
            int i = 0;
            SkipWs(text, ref i);
            if (i >= text.Length || text[i] != '{')
            {
                return false;
            }

            i++;
            SkipWs(text, ref i);
            if (i < text.Length && text[i] == '}')
            {
                i++;
                return Finish(text, i, ref reason);
            }

            while (true)
            {
                SkipWs(text, ref i);
                string key;
                if (!ReadString(text, ref i, out key))
                {
                    return false;
                }

                SkipWs(text, ref i);
                if (i >= text.Length || text[i] != ':')
                {
                    return false;
                }

                i++;
                SkipWs(text, ref i);
                if (i >= text.Length)
                {
                    return false;
                }

                object value;
                if (text[i] == '"')
                {
                    string s;
                    if (!ReadString(text, ref i, out s))
                    {
                        return false;
                    }

                    value = s;
                }
                else if (text[i] == '-' || (text[i] >= '0' && text[i] <= '9'))
                {
                    long n;
                    if (!ReadInteger(text, ref i, out n))
                    {
                        return false;
                    }

                    value = n;
                }
                else
                {
                    reason = "unsupported-value";
                    return false;
                }

                if (map.ContainsKey(key))
                {
                    reason = "duplicate-key";
                    return false;
                }

                map[key] = value;
                SkipWs(text, ref i);
                if (i >= text.Length)
                {
                    return false;
                }

                if (text[i] == ',')
                {
                    i++;
                    continue;
                }

                if (text[i] == '}')
                {
                    i++;
                    return Finish(text, i, ref reason);
                }

                return false;
            }
        }

        private static bool Finish(string text, int i, ref string reason)
        {
            SkipWs(text, ref i);
            if (i != text.Length)
            {
                reason = "trailing-text";
                return false;
            }

            reason = string.Empty;
            return true;
        }

        private static void SkipWs(string text, ref int i)
        {
            while (i < text.Length && (text[i] == ' ' || text[i] == '\t' || text[i] == '\r' || text[i] == '\n'))
            {
                i++;
            }
        }

        private static bool ReadInteger(string text, ref int i, out long value)
        {
            value = 0;
            int start = i;
            if (text[i] == '-')
            {
                i++;
            }

            int digits = 0;
            while (i < text.Length && text[i] >= '0' && text[i] <= '9' && digits < 15)
            {
                i++;
                digits++;
            }

            if (digits == 0)
            {
                return false;
            }

            if (i < text.Length && (text[i] == '.' || text[i] == 'e' || text[i] == 'E' || (text[i] >= '0' && text[i] <= '9')))
            {
                return false;
            }

            string number = text.Substring(start, i - start);
            if (digits > 1 && (number.StartsWith("0", StringComparison.Ordinal) || number.StartsWith("-0", StringComparison.Ordinal)))
            {
                return false;
            }

            return long.TryParse(number, System.Globalization.NumberStyles.AllowLeadingSign, System.Globalization.CultureInfo.InvariantCulture, out value);
        }

        private static bool ReadString(string text, ref int i, out string value)
        {
            value = null;
            if (i >= text.Length || text[i] != '"')
            {
                return false;
            }

            i++;
            StringBuilder sb = new StringBuilder();
            while (i < text.Length)
            {
                char c = text[i++];
                if (c == '"')
                {
                    value = sb.ToString();
                    return true;
                }

                if (c < 0x20)
                {
                    return false; // a raw control character inside a string is not JSON
                }

                if (c != '\\')
                {
                    sb.Append(c);
                    continue;
                }

                if (i >= text.Length)
                {
                    return false;
                }

                char e = text[i++];
                switch (e)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 > text.Length)
                        {
                            return false;
                        }

                        int code;
                        if (!int.TryParse(text.Substring(i, 4), System.Globalization.NumberStyles.AllowHexSpecifier, System.Globalization.CultureInfo.InvariantCulture, out code))
                        {
                            return false;
                        }

                        sb.Append((char)code);
                        i += 4;
                        break;
                    default:
                        return false;
                }
            }

            return false; // unterminated string
        }
    }
}
