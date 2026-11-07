// Shadow sway diagnostics test fixture (C# 5 on purpose: Windows PowerShell's Add-Type compiles it). Compiled into an assembly NAMED TsScoringLegacyTelemetryTests, which the
// telemetry DLL lets see its internals (InternalsVisibleTo). FAKE types with the STRUCTURE of the audited BVE passenger-sway figure (BveTs 5.8.7554.391 and 6.0.7554.619):
//   b4          : private field c (front-back spring) and private field d (left-right spring), both of the nested type b4.Spring
//   b4.Spring   : u
//   u           : protected double a (omega), b (zeta), c (equilibrium offset), d (input) - the SAME NAMES as the fields of t (hiding them): the trap
//   t           : protected object a (the clock), double b (x, the position state), double c (v, the velocity state), double d
// Nothing here touches BVE, AtsEX, the network or the disk.
using System;
using System.Globalization;
using TSScoringPlugin.Telemetry;

namespace TsScoringSwayFakes
{
    public abstract class t
    {
        protected object a;
        protected double b;
        protected double c;
        protected double d;
        public void SetState(double x, double v) { b = x; c = v; }
        public string DumpState() { return b.ToString("R", CultureInfo.InvariantCulture) + "|" + c.ToString("R", CultureInfo.InvariantCulture); }
    }

    public class u : t
    {
        protected new double a = 1.9792033717615696;      // omega
        protected new double b = 1.0;                     // zeta (same name as t.b)
        protected new double c = 0.0;                     // equilibrium offset (same name as t.c)
        protected new double d = 0.0;
        public void SetSignature(double omega, double zeta) { a = omega; b = zeta; }
        public string DumpSignature() { return a.ToString("R", CultureInfo.InvariantCulture) + "|" + b.ToString("R", CultureInfo.InvariantCulture) + "|" + c.ToString("R", CultureInfo.InvariantCulture) + "|" + d.ToString("R", CultureInfo.InvariantCulture); }
    }

    public class b4
    {
        public class Spring : u { }
        private Spring c = new Spring();
        private Spring d = new Spring();
        public void Set(double xc, double vc, double xd, double vd) { c.SetState(xc, vc); d.SetState(xd, vd); }
        public void SetSignature(double omega, double zeta) { c.SetSignature(omega, zeta); d.SetSignature(omega, zeta); }
        public void SetSignatureLateralOnly(double omega, double zeta) { d.SetSignature(omega, zeta); }
        public void ClearSpring(bool longitudinal) { if (longitudinal) { c = null; } else { d = null; } }
        public string Dump() { return c.DumpState() + "|" + d.DumpState() + "|" + c.DumpSignature() + "|" + d.DumpSignature(); }
    }

    // ---- wrong structures (each must be refused as a structure mismatch) ----
    public class b4NoD
    {
        private b4.Spring c = new b4.Spring();
        public object Touch() { return c; }
    }

    public class SpringOnT : t { }

    public class b4WrongBase
    {
        private SpringOnT c = new SpringOnT();
        private SpringOnT d = new SpringOnT();
        public object Touch() { return c ?? (object)d; }
    }

    public abstract class t2 { protected object a; protected double b; protected double c; protected double d; public string Touch2() { return (a == null ? "" : "a") + b + c + d; } }
    public class u2 : t2
    {
        protected new float a = 1.979f;                   // omega with the wrong type
        protected new double b = 1.0;
        protected new double c = 0.0;
        protected new double d = 0.0;
        public string Touch() { return a.ToString() + b + c + d; }
    }
    public class Spring2 : u2 { }
    public class b4FloatOmega
    {
        private Spring2 c = new Spring2();
        private Spring2 d = new Spring2();
        public object Touch() { return c ?? (object)d; }
    }

    public class b4DifferentSprings
    {
        private b4.Spring c = new b4.Spring();
        private Spring2 d = new Spring2();
        public object Touch() { return c ?? (object)d; }
    }

    public class b4NoStates
    {
        private string c = "not a spring";
        private string d = "not a spring";
        public string Touch() { return c + d; }
    }

    public static class SwayFake
    {
        public static object Ok(double xc, double vc, double xd, double vd) { b4 o = new b4(); o.Set(xc, vc, xd, vd); return o; }
        public static object Make(string kind)
        {
            switch (kind)
            {
                case "ok": return Ok(0.01, 0.02, 0.03, 0.04);
                case "no-d": return new b4NoD();
                case "wrong-base": return new b4WrongBase();
                case "float-omega": return new b4FloatOmega();
                case "different-springs": return new b4DifferentSprings();
                case "no-states": return new b4NoStates();
                case "bad-omega": { b4 o = new b4(); o.SetSignature(2.0, 1.0); return o; }
                case "bad-zeta": { b4 o = new b4(); o.SetSignature(1.9792033717615696, 0.7); return o; }
                case "bad-lateral-signature": { b4 o = new b4(); o.SetSignatureLateralOnly(1.9792033717615696, 0.5); return o; }
            }
            throw new ArgumentException(kind);
        }
        public static void Set(object o, double xc, double vc, double xd, double vd) { ((b4)o).Set(xc, vc, xd, vd); }
        public static void Break(object o, bool longitudinal) { ((b4)o).ClearSpring(longitudinal); }
        public static string Dump(object o) { return ((b4)o).Dump(); }
    }

    /// <summary>A public wrapper of the (internal) reader, so that the script can drive it.</summary>
    public sealed class SwayProbe
    {
        private readonly SwayStateReader reader;
        public SwayProbe(string version, string entry) { reader = new SwayStateReader(version, entry); }
        public string Resolve(object source) { return reader.Resolve(source).ToString(); }
        public string Status { get { return reader.Status.ToString(); } }
        public string Detail { get { return reader.Detail; } }
        public string Diagnostic { get { return reader.ResolutionText(); } }
        public int ResolveAttempts { get { return reader.ResolveAttempts; } }
        public int StructureProbes { get { return reader.StructureProbes; } }
        public int ReadAttempts { get { return reader.ReadAttempts; } }
        public void Reset() { reader.Reset(); }
        public string Read()
        {
            double a, b, c, d;
            if (!reader.TryRead(out a, out b, out c, out d)) { return "none"; }
            return a.ToString("R", CultureInfo.InvariantCulture) + "|" + b.ToString("R", CultureInfo.InvariantCulture) + "|" + c.ToString("R", CultureInfo.InvariantCulture) + "|" + d.ToString("R", CultureInfo.InvariantCulture);
        }
    }
}
