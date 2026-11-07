// Shadow sway diagnostics: the READ-ONLY reflection reader of the state the BVE passenger-sway figure ("乗客の揺れ") keeps. SHADOW-DIAGNOSTIC ONLY, PRIVATE_VERSION_DEPENDENT.
//
// What it reads (BveTs 5.8.7554.391 and 6.0.7554.619 were audited: the field declarations of the six classes are identical in both):
//   the figure object b4 keeps two springs, the private fields c (front-back) and d (left-right), both of one nested type S : u : t.
//   t declares  protected double b (the position state x) and c (the velocity state v);  u declares  protected double a (omega), b (zeta), c, d - the SAME NAMES as the
//   fields of t. So x and v are always taken from the DECLARING type t (DeclaredOnly); a name looked up from S or u would give zeta / the offset instead.
// What it never does: it writes nothing, calls nothing of the host, shows nothing, explores nothing (no member enumeration: an unknown version is not guessed at), and
// invents nothing (a state it cannot read is "not available", never 0).
// It depends on no host library (BveTypes, BveEX, AtsEX): it works on an object and System.Reflection only, so that the Current sender and the Legacy sender share it.
using System;
using System.Diagnostics;
using System.Globalization;
using System.Reflection;

namespace TSScoringPlugin.Telemetry
{
    internal enum SwayStatus
    {
        Pending,             // no source object yet (the scenario is not ready, or the figure is not in the list)
        Ok,                  // resolved: the four states can be read
        VersionUnsupported,  // the BVE file version is not one of the audited versions: no member is touched
        StructureMismatch,   // a member is absent, a type differs, or the structure signature (omega, zeta) does not hold
        Unavailable          // resolved once, but the states can no longer be read (repeated read failures)
    }

    internal sealed class SwayStateReader
    {
        internal const double Omega = 1.9792033717615696;     // the natural angular frequency of the figure's springs (rad/s)
        internal const double Zeta = 1.0;                      // the damping ratio
        private const double Tolerance = 1e-12;
        private const int MaxConsecutiveReadFailures = 3;
        private static readonly string[] AllowedVersions = new string[] { "5.8.7554.391", "6.0.7554.619" };
        private const BindingFlags Own = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        private readonly string version;
        private readonly string entry;
        private SwayStatus status = SwayStatus.Pending;
        private string detail = "no-source";
        private object source;
        private FieldInfo springLongitudinal;
        private FieldInfo springLateral;
        private FieldInfo stateX;
        private FieldInfo stateV;
        private int resolveAttempts;
        private int structureProbes;
        private int readAttempts;
        private int consecutiveReadFailures;

        internal SwayStateReader(string bveFileVersion, string entryName)
        {
            version = bveFileVersion == null ? "" : bveFileVersion.Trim();
            entry = string.IsNullOrEmpty(entryName) ? "unknown" : entryName;
        }

        internal SwayStatus Status { get { return status; } }

        internal string Detail { get { return detail; } }

        internal string Version { get { return version; } }

        internal int ResolveAttempts { get { return resolveAttempts; } }

        internal int StructureProbes { get { return structureProbes; } }

        internal int ReadAttempts { get { return readAttempts; } }

        /// <summary>The BVE file version of the host process (BveTs.exe), read once by the caller. "unknown" when it cannot be read (which is not an allowed version).</summary>
        internal static string HostFileVersion()
        {
            try
            {
                string path = Process.GetCurrentProcess().MainModule.FileName;
                string text = FileVersionInfo.GetVersionInfo(path).FileVersion;
                return string.IsNullOrEmpty(text) ? "unknown" : text.Trim();
            }
            catch
            {
                return "unknown";
            }
        }

        /// <summary>A scenario boundary: the binding is forgotten (the figure object belongs to one scenario instance).</summary>
        internal void Reset()
        {
            ClearBinding();
            status = SwayStatus.Pending;
            detail = "no-source";
        }

        /// <summary>Binds the reader to the figure object (b4). The same object again returns the cached result (a failure is not retried every Tick); another object is resolved again.</summary>
        internal SwayStatus Resolve(object figure)
        {
            if (!VersionAllowed())
            {
                ClearBinding();
                status = SwayStatus.VersionUnsupported;
                detail = "version-" + Clean(version.Length == 0 ? "none" : version);
                return status;
            }

            if (figure == null)
            {
                ClearBinding();
                status = SwayStatus.Pending;
                detail = "no-source";
                return status;
            }

            if (object.ReferenceEquals(figure, source))
            {
                return status;
            }

            ClearBinding();
            source = figure;
            resolveAttempts++;
            try
            {
                ResolveStructure(figure);
            }
            catch (Exception ex)
            {
                ClearFields();
                status = SwayStatus.StructureMismatch;
                detail = "exception-" + Clean(ex.GetType().Name);
            }

            return status;
        }

        /// <summary>The four raw states (front-back x, v and left-right x, v) exactly as the figure keeps them. false = not available: nothing is invented.</summary>
        internal bool TryRead(out double longitudinalX, out double longitudinalV, out double lateralX, out double lateralV)
        {
            longitudinalX = 0.0;
            longitudinalV = 0.0;
            lateralX = 0.0;
            lateralV = 0.0;
            if (status != SwayStatus.Ok)
            {
                return false;
            }

            readAttempts++;
            try
            {
                object c = springLongitudinal.GetValue(source);
                object d = springLateral.GetValue(source);
                if (c == null || d == null)
                {
                    throw new InvalidOperationException("spring-null");
                }

                double xc = (double)stateX.GetValue(c);
                double vc = (double)stateV.GetValue(c);
                double xd = (double)stateX.GetValue(d);
                double vd = (double)stateV.GetValue(d);
                consecutiveReadFailures = 0;
                if (!Finite(xc) || !Finite(vc) || !Finite(xd) || !Finite(vd))
                {
                    return false;
                }

                longitudinalX = xc;
                longitudinalV = vc;
                lateralX = xd;
                lateralV = vd;
                return true;
            }
            catch
            {
                consecutiveReadFailures++;
                if (consecutiveReadFailures >= MaxConsecutiveReadFailures)
                {
                    status = SwayStatus.Unavailable;
                    detail = "read-exception";
                }

                return false;
            }
        }

        /// <summary>The value of the SWAYR part: result:version:entry[:detail]. Fixed words; the detail has no comma, colon or space (it travels inside a telemetry line).</summary>
        internal string ResolutionText()
        {
            string text = ResultWord() + ":" + Clean(version.Length == 0 ? "none" : version) + ":" + Clean(entry);
            if (status != SwayStatus.Ok && detail.Length > 0)
            {
                text += ":" + Clean(detail);
            }

            return text;
        }

        internal string ResultWord()
        {
            switch (status)
            {
                case SwayStatus.Ok: return "ok";
                case SwayStatus.VersionUnsupported: return "version-unsupported";
                case SwayStatus.StructureMismatch: return "structure-mismatch";
                case SwayStatus.Unavailable: return "unavailable";
                default: return "pending";
            }
        }

        private bool VersionAllowed()
        {
            for (int i = 0; i < AllowedVersions.Length; i++)
            {
                if (string.Equals(version, AllowedVersions[i], StringComparison.Ordinal))
                {
                    return true;
                }
            }

            return false;
        }

        private void ResolveStructure(object figure)
        {
            structureProbes++;
            Type figureType = figure.GetType();
            FieldInfo c = figureType.GetField("c", Own);
            FieldInfo d = figureType.GetField("d", Own);
            if (c == null || d == null)
            {
                Mismatch("member-absent-b4." + (c == null ? "c" : "d"));
                return;
            }

            Type spring = c.FieldType;
            if (!object.ReferenceEquals(spring, d.FieldType))
            {
                Mismatch("type-mismatch-spring-types");
                return;
            }

            // spring -> u -> t: the declaring type of the states is the base of the base
            Type u = spring.BaseType;
            Type t = u == null ? null : u.BaseType;
            if (u == null || t == null || object.ReferenceEquals(t, typeof(object)) || object.ReferenceEquals(u, typeof(object)))
            {
                Mismatch("type-mismatch-base-chain");
                return;
            }

            FieldInfo x = t.GetField("b", Own);
            FieldInfo v = t.GetField("c", Own);
            if (x == null || v == null)
            {
                Mismatch("member-absent-t." + (x == null ? "b" : "c"));
                return;
            }

            if (!object.ReferenceEquals(x.DeclaringType, t) || !object.ReferenceEquals(v.DeclaringType, t) || !object.ReferenceEquals(x.FieldType, typeof(double)) || !object.ReferenceEquals(v.FieldType, typeof(double)))
            {
                Mismatch("type-mismatch-t.b-c");
                return;
            }

            FieldInfo omega = u.GetField("a", Own);
            FieldInfo zeta = u.GetField("b", Own);
            if (omega == null || zeta == null)
            {
                Mismatch("member-absent-u." + (omega == null ? "a" : "b"));
                return;
            }

            if (!object.ReferenceEquals(omega.FieldType, typeof(double)) || !object.ReferenceEquals(zeta.FieldType, typeof(double)))
            {
                Mismatch("type-mismatch-u.a-b");
                return;
            }

            object cValue = c.GetValue(figure);
            object dValue = d.GetValue(figure);
            if (cValue == null || dValue == null)
            {
                Mismatch("instance-null-spring");
                return;
            }

            object[] springs = new object[] { cValue, dValue };
            for (int i = 0; i < springs.Length; i++)
            {
                double w = (double)omega.GetValue(springs[i]);
                double z = (double)zeta.GetValue(springs[i]);
                if (!(Math.Abs(w - Omega) <= Tolerance))
                {
                    Mismatch("signature-mismatch-omega");
                    return;
                }

                if (!(Math.Abs(z - Zeta) <= Tolerance))
                {
                    Mismatch("signature-mismatch-zeta");
                    return;
                }
            }

            springLongitudinal = c;
            springLateral = d;
            stateX = x;
            stateV = v;
            status = SwayStatus.Ok;
            detail = "";
        }

        private void Mismatch(string why)
        {
            ClearFields();
            status = SwayStatus.StructureMismatch;
            detail = why;
        }

        private void ClearFields()
        {
            springLongitudinal = null;
            springLateral = null;
            stateX = null;
            stateV = null;
        }

        private void ClearBinding()
        {
            source = null;
            ClearFields();
            consecutiveReadFailures = 0;
        }

        private static bool Finite(double value)
        {
            return !double.IsNaN(value) && !double.IsInfinity(value);
        }

        private static string Clean(string text)
        {
            if (text == null)
            {
                return "none";
            }

            char[] chars = text.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                char ch = chars[i];
                bool keep = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '_';
                if (!keep)
                {
                    chars[i] = '-';
                }
            }

            string clean = new string(chars);
            return clean.Length == 0 ? "none" : clean;
        }
    }
}
