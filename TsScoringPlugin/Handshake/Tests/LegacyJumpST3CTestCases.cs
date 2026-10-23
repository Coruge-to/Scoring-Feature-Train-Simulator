using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Reflection.Emit;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE PID-D4JA StationIndex ST-3c - the compiled tests of the LEGACY jump transaction (v2 over the shared JumpWire) and of the STALIST acknowledgement (R1-B).
// TEST CODE ONLY: never part of a product DLL. Written BEFORE the product (RED first).
//
// The harness is the LJX-1 rig (LxRig: the real control plane with its seam doubles, the real telemetry session over a fake Legacy API, the real tick runner, a fake host
// and a fake completion sender), reused unchanged. The product is bound by REFLECTION wherever the element is NEW in ST-3c, so that the file compiles against the tree
// BEFORE the phase and a missing element is an EXPECTED RED with a declared code. Elements that already exist (JumpWire, StationListIdentity, LegacyStationRaw, ...) are used
// directly.
//
// Outcome of a case (S3Ctx): PASS, RED (every failed contract clause carries a DECLARED code, or the product element named by a declared token is absent), FAIL (a clause failed
// with an undeclared code, or a GUARD failed) and INVALID (a premise failed or an unexpected exception: never counted as a RED). A premise is a plain check that the rig itself
// works (a formal v1 command is executed and completed exactly as before); an INVALID case proves nothing.
//
// The ids are the ones of the Start Audit (13-Red-Test-Plan.md): N-31..N-38, R1B-1..9, and the ids that ST-3c fixed before writing (N-51..N-69; see the artifact 04).
// Written in C# 5 syntax (Windows PowerShell 5.1 Add-Type).
// ============================================================================================================================================
// The older fixtures (TelemetryTestFixture.cs, LegacyDataPlaneTestFixture.cs) name FileTelemetryDiag, which lives in LegacyTelemetryExtension.cs (the one source that needs AtsEx and is
// left out of the offline source set). This placeholder lets them compile; the ST-3c cases never reach it, and every member refuses to run.
namespace TSScoringPlugin.Telemetry
{
    internal sealed class FileTelemetryDiag : ITelemetryDiag
    {
        internal static string FileNamePrefix { get { throw new NotSupportedException("offline source set"); } }
        internal static string Version { get { throw new NotSupportedException("offline source set"); } }
        internal FileTelemetryDiag() { throw new NotSupportedException("offline source set"); }
        internal FileTelemetryDiag(string pathOverride) { throw new NotSupportedException("offline source set"); }
        internal FileTelemetryDiag(int processId, DateTime processStartUtc, string directory) { throw new NotSupportedException("offline source set"); }
        internal static string NameFor(int pid, string startStamp) { throw new NotSupportedException("offline source set"); }
        internal static string DefaultPath() { throw new NotSupportedException("offline source set"); }
        internal static string StartStamp(DateTime utc) { throw new NotSupportedException("offline source set"); }
        internal static int CurrentProcessId() { throw new NotSupportedException("offline source set"); }
        public void Event(string name, string detail) { throw new NotSupportedException("offline source set"); }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    [AttributeUsage(AttributeTargets.Method)]
    internal sealed class S3Attribute : Attribute
    {
        public readonly string Id;
        public readonly string Label;
        public string Kind = "RED";             // RED: fails against the tree before ST-3c with a declared code; GUARD: passes before and after
        public string Red = "";                 // the declared codes, '|' separated (a clause code, or a token of the absent product element)

        public S3Attribute(string id, string label)
        {
            Id = id;
            Label = label;
        }
    }

    internal sealed class S3Ctx
    {
        public readonly Ctx C;
        public readonly List<string[]> Fails = new List<string[]>();
        public readonly List<string> PremiseFails = new List<string>();

        public S3Ctx(string id)
        {
            C = new Ctx(id);
        }

        public void Premise(bool ok, string what, string actual)
        {
            C.Check(ok, "PREMISE " + what, actual);
            if (!ok) PremiseFails.Add(what + (String.IsNullOrEmpty(actual) ? "" : " [" + actual + "]"));
        }

        public void Premise(bool ok, string what)
        {
            Premise(ok, what, null);
        }

        public void Contract(string code, bool ok, string what, string actual)
        {
            C.Check(ok, what, actual);
            if (!ok) Fails.Add(new string[] { code, what + (String.IsNullOrEmpty(actual) ? "" : " [" + actual + "]") });
        }

        public void Contract(string code, bool ok, string what)
        {
            Contract(code, ok, what, null);
        }
    }

    /// <summary>One implementation of an interface (and the interfaces it inherits) by a handler: Reflection.Emit, like the kit's Proxy, which does not follow inheritance.</summary>
    internal static class AckProxy
    {
        private static readonly object gate = new object();
        private static ModuleBuilder module;
        private static int counter;
        private static readonly Dictionary<Type, KeyValuePair<Type, MethodInfo[]>> made = new Dictionary<Type, KeyValuePair<Type, MethodInfo[]>>();

        internal static object Make(Type iface, ProxyHandler handler)
        {
            Type t;
            MethodInfo[] methods;
            lock (gate)
            {
                if (module == null)
                {
                    AssemblyName an = new AssemblyName("TsScoringLegacyTelemetryTests");
                    AssemblyBuilder ab = AppDomain.CurrentDomain.DefineDynamicAssembly(an, AssemblyBuilderAccess.Run);
                    module = ab.DefineDynamicModule("ackproxies");
                }
                KeyValuePair<Type, MethodInfo[]> hit;
                if (made.TryGetValue(iface, out hit)) { t = hit.Key; methods = hit.Value; }
                else
                {
                    List<MethodInfo> all = new List<MethodInfo>();
                    all.AddRange(iface.GetMethods());
                    foreach (Type b in iface.GetInterfaces()) all.AddRange(b.GetMethods());
                    methods = all.ToArray();
                    TypeBuilder tb = module.DefineType("AckProxy" + (++counter).ToString() + "_" + iface.Name, TypeAttributes.Public | TypeAttributes.Sealed, typeof(object), new Type[] { iface });
                    FieldBuilder fh = tb.DefineField("h", typeof(ProxyHandler), FieldAttributes.Public);
                    FieldBuilder fm = tb.DefineField("ms", typeof(MethodInfo[]), FieldAttributes.Public);
                    for (int k = 0; k < methods.Length; k++)
                    {
                        MethodInfo m = methods[k];
                        ParameterInfo[] ps = m.GetParameters();
                        Type[] pts = new Type[ps.Length];
                        for (int i = 0; i < ps.Length; i++) pts[i] = ps[i].ParameterType;
                        MethodBuilder mb = tb.DefineMethod(m.Name, MethodAttributes.Public | MethodAttributes.Virtual | MethodAttributes.Final | MethodAttributes.HideBySig | MethodAttributes.NewSlot, m.ReturnType, pts);
                        ILGenerator il = mb.GetILGenerator();
                        LocalBuilder arr = il.DeclareLocal(typeof(object[]));
                        il.Emit(OpCodes.Ldc_I4, ps.Length);
                        il.Emit(OpCodes.Newarr, typeof(object));
                        il.Emit(OpCodes.Stloc, arr);
                        for (int i = 0; i < ps.Length; i++)
                        {
                            il.Emit(OpCodes.Ldloc, arr);
                            il.Emit(OpCodes.Ldc_I4, i);
                            il.Emit(OpCodes.Ldarg, i + 1);
                            if (pts[i].IsValueType) il.Emit(OpCodes.Box, pts[i]);
                            il.Emit(OpCodes.Stelem_Ref);
                        }
                        il.Emit(OpCodes.Ldarg_0);
                        il.Emit(OpCodes.Ldfld, fh);
                        il.Emit(OpCodes.Ldarg_0);
                        il.Emit(OpCodes.Ldfld, fm);
                        il.Emit(OpCodes.Ldc_I4, k);
                        il.Emit(OpCodes.Ldelem_Ref);
                        il.Emit(OpCodes.Ldloc, arr);
                        il.Emit(OpCodes.Callvirt, typeof(ProxyHandler).GetMethod("Invoke"));
                        if (m.ReturnType == typeof(void)) il.Emit(OpCodes.Pop);
                        else if (m.ReturnType.IsValueType) il.Emit(OpCodes.Unbox_Any, m.ReturnType);
                        else il.Emit(OpCodes.Castclass, m.ReturnType);
                        il.Emit(OpCodes.Ret);
                        tb.DefineMethodOverride(mb, m);
                    }
                    t = tb.CreateType();
                    made[iface] = new KeyValuePair<Type, MethodInfo[]>(t, methods);
                }
            }
            object o = Activator.CreateInstance(t);
            t.GetField("h").SetValue(o, handler);
            t.GetField("ms").SetValue(o, methods);
            return o;
        }
    }

    /// <summary>A sink that acknowledges (or refuses) the STALIST / META texts: the fake of ITelemetrySinkAck.</summary>
    internal sealed class AckSink
    {
        public object Obj;
        public volatile bool Accept;
        public bool ThrowOnTry;
        public readonly List<string> Tried = new List<string>();      // every text offered through TrySend
        public readonly List<string> Accepted = new List<string>();
        public readonly List<string> Plain = new List<string>();      // every text offered through Send (the rows)
        public bool Closed;
        public int AfterClose;

        public AckSink(bool accept)
        {
            Accept = accept;
            Obj = AckProxy.Make(Pr.T("ITelemetrySinkAck"), Handle);
        }

        private object Handle(MethodInfo m, object[] a)
        {
            if (m.Name == "Send")
            {
                if (Closed) AfterClose++;
                lock (Plain) { Plain.Add((string)a[0]); }
                return null;
            }
            if (m.Name == "TrySend")
            {
                if (Closed) AfterClose++;
                string text = (string)a[0];
                lock (Tried) { Tried.Add(text); }
                if (ThrowOnTry) throw new InvalidOperationException("injected-trysend");
                if (!Accept) return false;
                lock (Accepted) { Accepted.Add(text); }
                return true;
            }
            if (m.Name == "Close") { Closed = true; return null; }
            throw new FixtureFaultException("unexpected sink method " + m.Name);
        }

        public int Count(List<string> l, string prefix)
        {
            int n = 0;
            lock (l) { foreach (string s in l) if (s.StartsWith(prefix, StringComparison.Ordinal)) n++; }
            return n;
        }

        public string Last(List<string> l, string prefix)
        {
            lock (l) { for (int i = l.Count - 1; i >= 0; i--) if (l[i].StartsWith(prefix, StringComparison.Ordinal)) return l[i]; }
            return null;
        }
    }

    /// <summary>A telemetry session over a fake Legacy API with an acknowledging sink, ticked by hand (no jump plane).</summary>
    internal sealed class SessRig
    {
        public FakeApi Api = new FakeApi();
        public CollectDiag Diag = new CollectDiag();
        public AckSink Sink;
        public object Session;
        public long Mono = 100000;

        public static SessRig Make(bool accept, int stations)
        {
            SessRig r = new SessRig();
            r.Sink = new AckSink(accept);
            for (int i = 0; i < stations; i++)
            {
                FakeStation st = new FakeStation();
                st.Name = "S" + i;
                st.Location = 500.0 + 1000.0 * i;
                r.Api.Stations.Add(st);
            }
            r.Api.SpeedMps = 0.0;
            SessRig self = r;
            Func<long> now = delegate { return self.Mono; };
            Func<long> seed = delegate { return 5000000000L; };
            r.Session = Pr.New(Pr.T("LegacyTelemetrySession"), r.Api, r.Sink.Obj, now, seed, r.Diag);
            return r;
        }

        public void Tick(int stepMs)
        {
            Mono += stepMs;
            Api.TimeMs += stepMs;
            Pr.Call(Session, "OnTick", TimeSpan.FromMilliseconds((double)stepMs));
        }

        public bool Flag(string name) { return (bool)Pr.Get(Session, name); }

        public string ListId { get { return (string)Pr.Get(Pr.Get(Session, "timeline"), "ListId"); } }
    }

    internal static class S3
    {
        public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
        public static string[] FormalV1 = new string[0];
        public static string[] AmbiguousV1 = new string[0];
        private static int timeCounter;

        public const string NoV2 = "v2-refused-at-gate";

        public static int NextTime()
        {
            return 40000000 + 100000 * Interlocked.Increment(ref timeCounter);
        }

        public static void SetStations(LxRig x, double[] st)
        {
            x.Host.Stations = st;
            x.Api.Stations.Clear();
            for (int i = 0; i < st.Length; i++)
            {
                FakeStation f = new FakeStation();
                f.Name = "S" + i;
                f.Location = st[i];
                x.Api.Stations.Add(f);
            }
        }

        /// <summary>A rig whose Legacy API holds exactly these stations, built into the timeline after two Ticks.</summary>
        public static LxRig Rig(S3Ctx s, double[] stations)
        {
            LxOpts o = new LxOpts();
            o.Warm = false;
            LxRig x = LxRig.Make(s.C, o);
            SetStations(x, stations);
            x.Tick(16);
            x.Tick(16);
            return x;
        }

        public static void ClearCalls(LxRig x)
        {
            lock (x.Host.Calls) { x.Host.Calls.Clear(); }
        }

        /// <summary>The premise of every v2 case: a FORMAL v1 station command is executed and completed exactly as before ST-3c (the rig works).</summary>
        public static void Prime(S3Ctx s, LxRig x)
        {
            byte[] rid = Cmd.Rid();
            RecView rv = x.SendSta(rid, 1, NextTime());
            s.Premise(rv != null && rv.State == CState.Queued, "a formal v1 station command is queued", rv == null ? "null" : rv.Short);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Premise(r != null && r.State == Ls.Completed, "and completed (the rig and the host seam work)", r == null ? "null" : r.Short);
            ClearCalls(x);
            x.Sender.Payloads.Clear();
            x.Sender.Ids.Clear();
            x.Sender.Calls = 0;
        }

        // -- the scope the session holds now -----------------------------------------------------------------------------------------------------
        public static int ScenarioId(LxRig x) { return Convert.ToInt32(Pr.Get(x.Session, "ScenarioId")); }
        public static string ListId(LxRig x) { return (string)Pr.Get(Pr.Get(x.Session, "timeline"), "ListId"); }
        public static int Count(LxRig x) { return Convert.ToInt32(Pr.Get(Pr.Get(x.Session, "timeline"), "Count")); }

        public static string V2(string kind, int idx, double loc, int timeMs, int scen, string list, int count)
        {
            string reason;
            string t = JumpWire.FormatRequestV2(kind, idx, timeMs, new JumpWireScope(scen, list, count), loc, out reason);
            if (t == null) throw new FixtureFaultException("the fixture request can not be formatted: " + reason);
            return t;
        }

        public static string V2Now(LxRig x, string kind, int idx, double loc, int timeMs)
        {
            return V2(kind, idx, loc, timeMs, ScenarioId(x), ListId(x), Count(x));
        }

        public static uint TypeOf(string kind) { return kind == "STA" ? 0x100U : 0x101U; }

        public static RecView SendV2(LxRig x, string kind, string text, byte[] rid)
        {
            return x.Send(text, TypeOf(kind), rid);
        }

        // -- the row ---------------------------------------------------------------------------------------------------------------------------
        private static readonly Regex StIdx = new Regex(@"STIDX:1:(-?\d+):(-?\d+):(\d+):(\d+):([0-9A-F]{8})");

        public static int Tgt(LxRig x)
        {
            string line = x.LastTelemetryLine();
            if (line == null) return -99;
            Match m = StIdx.Match(line);
            return m.Success ? Int32.Parse(m.Groups[1].Value, Inv) : -98;
        }

        public static string D(double v) { return v.ToString("R", Inv); }

        public static double NextUp(double v)
        {
            return BitConverter.Int64BitsToDouble(BitConverter.DoubleToInt64Bits(v) + 1L);
        }

        public static bool Has(LxRig x, string call)
        {
            foreach (string c in x.Host.CallsSnapshot()) if (c == call) return true;
            return false;
        }

        public static string Calls(LxRig x) { return String.Join(";", x.Host.CallsSnapshot()); }

        public static int Failures(LxRig x) { return Convert.ToInt32(Pr.Get(x.P.Raw, "consecutiveFailures")); }
        public static bool BreakerOpen(LxRig x) { return (bool)Pr.Get(x.P.Raw, "BreakerOpen"); }
        public static bool JumpAvailable(LxRig x) { return (bool)Pr.Get(x.P.Raw, "JumpAvailable"); }
        public static object InFlight(LxRig x) { return Pr.Get(Pr.Get(x.P.Raw, "queue"), "InFlight"); }

        public static JumpWireCompletion Completion(string payload, out string reason)
        {
            return JumpWire.ParseCompletion(payload, out reason);
        }

        /// <summary>A v2 request that the gate lets in but the judgement must refuse: the verdict word it must carry.</summary>
        public sealed class Bad
        {
            public string Name;
            public string Kind;
            public string Text;
            public string Word;
        }

        public static List<Bad> BadRequests(LxRig x, double[] st)
        {
            int scen = ScenarioId(x);
            string list = ListId(x);
            int count = Count(x);
            int t = NextTime();
            List<Bad> l = new List<Bad>();
            l.Add(new Bad { Name = "scenario", Kind = "STA", Text = V2("STA", 2, st[2], t, scen + 1, list, count), Word = "scenario-mismatch" });
            l.Add(new Bad { Name = "list", Kind = "STA", Text = V2("STA", 2, st[2], t, scen, list == "00000001" ? "00000002" : "00000001", count), Word = "list-mismatch" });
            l.Add(new Bad { Name = "count", Kind = "STA", Text = V2("STA", 2, st[2], t, scen, list, count + 1), Word = "count-mismatch" });
            l.Add(new Bad { Name = "location-other-station", Kind = "STA", Text = V2("STA", 2, st[1], t, scen, list, count), Word = "location-mismatch" });
            l.Add(new Bad { Name = "location-one-ulp", Kind = "STA", Text = V2("STA", 2, NextUp(st[2]), t, scen, list, count), Word = "location-mismatch" });
            l.Add(new Bad { Name = "loc-kind-contradiction", Kind = "LOC", Text = V2("LOC", 3, st[1], t, scen, list, count), Word = "location-mismatch" });
            return l;
        }
    }

    public static class LegacyJumpST3CTestFixture
    {
        public static void SetVectors(string[] formal, string[] ambiguous)
        {
            S3.FormalV1 = formal;
            S3.AmbiguousV1 = ambiguous;
        }

        public static string[] DiscoverIds()
        {
            List<string> ids = new List<string>();
            foreach (MethodInfo m in typeof(LegacyJumpST3CTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(S3Attribute), false);
                if (a.Length > 0) ids.Add(((S3Attribute)a[0]).Id);
            }
            ids.Sort(StringComparer.Ordinal);
            return ids.ToArray();
        }

        public static RunResult Run(Assembly product, string runId, string repoRoot, string[] only)
        {
            Pr.Load(product);
            Env.Init(runId);
            Env.RepoRoot = repoRoot;
            Env.BaselineHandles = System.Diagnostics.Process.GetCurrentProcess().HandleCount;
            Env.BaselineThreads = System.Diagnostics.Process.GetCurrentProcess().Threads.Count;
            RunResult rr = new RunResult();
            SortedDictionary<string, MethodInfo> byId = new SortedDictionary<string, MethodInfo>(StringComparer.Ordinal);
            Dictionary<string, S3Attribute> attrs = new Dictionary<string, S3Attribute>();
            foreach (MethodInfo m in typeof(LegacyJumpST3CTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(S3Attribute), false);
                if (a.Length == 0) continue;
                S3Attribute sa = (S3Attribute)a[0];
                byId[sa.Id] = m;
                attrs[sa.Id] = sa;
            }
            rr.Discovered = byId.Count;
            foreach (KeyValuePair<string, MethodInfo> kv in byId)
            {
                if (only != null && only.Length > 0 && Array.IndexOf(only, kv.Key) < 0) continue;
                rr.Invoked++;
                rr.Tests.Add(Execute(kv.Key, attrs[kv.Key], kv.Value));
            }
            rr.Header = "product=" + product.GetName().Name + " run=" + runId;
            return rr;
        }

        private static bool Declared(S3Attribute a, string code)
        {
            foreach (string d in a.Red.Split('|')) if (d.Length > 0 && code.IndexOf(d, StringComparison.Ordinal) >= 0) return true;
            return false;
        }

        private static TestResult Execute(string id, S3Attribute sa, MethodInfo m)
        {
            TestResult tr = new TestResult();
            tr.Id = id;
            tr.Label = sa.Label;
            tr.Kind = sa.Kind;
            S3Ctx s = new S3Ctx(id);
            System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
            string absent = null;
            string fault = null;
            try
            {
                try { m.Invoke(null, new object[] { s }); }
                catch (TargetInvocationException ex) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); }
            }
            catch (ProductAbsentException ex)
            {
                absent = ex.Code;
            }
            catch (Exception ex)
            {
                string t = ex.ToString();
                if (t.Length > 700) t = t.Substring(0, 700);
                fault = ex.GetType().Name + " :: " + t.Replace("\r", " ").Replace("\n", " ");
            }
            finally
            {
                s.C.ReleaseAll();
            }
            tr.Seconds = sw.Elapsed.TotalSeconds;
            tr.Checks = s.C.Checks.Count;
            tr.Failed = s.C.FailedChecks;
            tr.Log = s.C.Log.ToString();
            if (fault != null) { tr.Outcome = "INVALID"; tr.FailText = "exception " + fault; return tr; }
            if (s.PremiseFails.Count > 0) { tr.Outcome = "INVALID"; tr.FailText = "premise: " + s.PremiseFails[0]; return tr; }
            if (absent != null)
            {
                if (sa.Kind == "RED" && Declared(sa, absent)) { tr.Outcome = "RED"; tr.RedCode = absent; }
                else { tr.Outcome = "INVALID"; tr.FailText = "absent product element (undeclared): " + absent; }
                return tr;
            }
            if (s.Fails.Count > 0)
            {
                bool allDeclared = sa.Kind == "RED";
                foreach (string[] f in s.Fails) if (!Declared(sa, f[0])) allDeclared = false;
                if (allDeclared) { tr.Outcome = "RED"; tr.RedCode = s.Fails[0][0]; tr.FailText = s.Fails[0][1]; }
                else { tr.Outcome = "FAIL"; tr.RedCode = s.Fails[0][0]; tr.FailText = s.Fails[0][1]; }
                return tr;
            }
            if (s.C.Checks.Count == 0) { tr.Outcome = "INVALID"; tr.FailText = "no check was made"; return tr; }
            tr.Outcome = "PASS";
            return tr;
        }

        // =====================================================================================================================================
        // gate and parser
        // =====================================================================================================================================
        [S3("N-51", "the Legacy gate is the shared JumpWire: 16 formal v1 in, 16 ambiguous v1 out, v2 in", Red = "gate-accepts-ambiguous-v1|v2-refused-at-gate")]
        internal static void N51(S3Ctx s)
        {
            s.Premise(S3.FormalV1.Length == 16 && S3.AmbiguousV1.Length == 16, "the vector table gives 16 formal and 16 ambiguous v1 inputs", S3.FormalV1.Length + "/" + S3.AmbiguousV1.Length);
            LxRig x = s.C.Own(LxRig.Make(s.C, new LxOpts()));
            int formalIn = 0, ambiguousIn = 0;
            string firstBad = "";
            foreach (string raw in S3.FormalV1)
            {
                RecView rv = x.Send(raw, raw.StartsWith("JUMP_LOC_TIME", StringComparison.Ordinal) ? 0x101U : 0x100U, Cmd.Rid());
                if (rv != null && rv.State == CState.Queued) formalIn++;
            }
            foreach (string raw in S3.AmbiguousV1)
            {
                RecView rv = x.Send(raw, raw.StartsWith("JUMP_LOC_TIME", StringComparison.Ordinal) ? 0x101U : 0x100U, Cmd.Rid());
                if (rv != null && rv.State == CState.Queued) { ambiguousIn++; if (firstBad.Length == 0) firstBad = raw; }
            }
            s.Contract("formal-v1-refused", formalIn == 16, "all 16 formal v1 inputs are accepted by the gate", "" + formalIn);
            s.Contract("gate-accepts-ambiguous-v1", ambiguousIn == 0, "none of the 16 ambiguous v1 inputs is accepted (payload-grammar)", ambiguousIn + " accepted, e.g. " + firstBad.Replace("\n", "\\n"));
            double[] st = x.Host.Stations;
            string sta = S3.V2Now(x, "STA", 2, st[2], S3.NextTime());
            string loc = S3.V2Now(x, "LOC", 2, st[2], S3.NextTime());
            RecView a = S3.SendV2(x, "STA", sta, Cmd.Rid());
            RecView b = S3.SendV2(x, "LOC", loc, Cmd.Rid());
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, "a v2 station command is accepted by the gate", a == null ? "null" : a.Short);
            s.Contract(S3.NoV2, b != null && b.State == CState.Queued, "a v2 location command is accepted by the gate", b == null ? "null" : b.Short);
        }

        [S3("N-52", "a v2 command is read by the shared reader and executed with the values it names", Red = S3.NoV2)]
        internal static void N52(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            int t1 = S3.NextTime();
            byte[] ridA = Cmd.Rid();
            RecView a = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], t1), ridA);
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, "the v2 station command is queued", a == null ? "null" : a.Short);
            x.Tick(16);
            s.Contract(S3.NoV2, S3.Has(x, "MoveToStation(2)"), "the host was called with station index 2", S3.Calls(x));
            s.Contract(S3.NoV2, S3.Has(x, "SetClockMs(" + t1 + ")"), "and with the time of the command", S3.Calls(x));
            LxRec ra = x.Rec(ridA);
            s.Contract(S3.NoV2, ra != null && ra.State == Ls.Completed, "the command ends Completed", ra == null ? "null" : ra.Short);
            S3.ClearCalls(x);
            int t2 = S3.NextTime();
            byte[] ridB = Cmd.Rid();
            RecView b = S3.SendV2(x, "LOC", S3.V2Now(x, "LOC", 1, st[1], t2), ridB);
            s.Contract(S3.NoV2, b != null && b.State == CState.Queued, "the v2 location command is queued", b == null ? "null" : b.Short);
            x.Tick(16);
            s.Contract(S3.NoV2, S3.Has(x, "MoveToLocation(" + S3.D(st[1]) + "," + t2 + ")"), "the host was called with the location and the time of the command", S3.Calls(x));
            LxRec rb = x.Rec(ridB);
            s.Contract(S3.NoV2, rb != null && rb.State == Ls.Completed, "the command ends Completed", rb == null ? "null" : rb.Short);
        }

        [S3("N-53", "station index 0 is a valid request (not a fallback)", Red = S3.NoV2)]
        internal static void N53(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            int t = S3.NextTime();
            byte[] rid = Cmd.Rid();
            RecView a = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 0, st[0], t), rid);
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, "the v2 station command for index 0 is queued", a == null ? "null" : a.Short);
            x.Tick(16);
            s.Contract(S3.NoV2, S3.Has(x, "MoveToStation(0)"), "the host was called with index 0", S3.Calls(x));
            string reason;
            JumpWireCompletion c = x.Sender.LastPayload == null ? null : S3.Completion(x.Sender.LastPayload, out reason);
            s.Contract(S3.NoV2, c != null && c.Version == 2 && c.SelectedIndex == 0, "the completion carries selected_idx 0", x.Sender.LastPayload);
            s.Contract(S3.NoV2, S3.Tgt(x) == 0, "and the target after the jump is index 0", "" + S3.Tgt(x));
        }

        // =====================================================================================================================================
        // the target after a jump
        // =====================================================================================================================================
        private static void KeepsIndex(S3Ctx s, double[] st, int idx, string kind, string label)
        {
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            int t = S3.NextTime();
            byte[] rid = Cmd.Rid();
            RecView a = S3.SendV2(x, kind, S3.V2Now(x, kind, idx, st[idx], t), rid);
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, label + ": the v2 command is queued", a == null ? "null" : a.Short);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Contract(S3.NoV2, r != null && r.State == Ls.Completed, label + ": it is completed", r == null ? "null" : r.Short);
            s.Contract(S3.NoV2, S3.Tgt(x) == idx, label + ": the STIDX target of the row is the requested index " + idx, "" + S3.Tgt(x));
            object tl = Pr.Get(x.Session, "timeline");
            s.Contract(S3.NoV2, Convert.ToInt32(Pr.Get(tl, "TargetIndex")) == idx, label + ": the timeline target is the requested index", "" + Pr.Get(tl, "TargetIndex"));
        }

        [S3("N-31", "the requested index is kept when two stations share one position", Red = S3.NoV2)]
        internal static void N31(S3Ctx s)
        {
            KeepsIndex(s, new double[] { 0.5, 1000.5, 2000.0, 2000.0, 3000.0 }, 3, "STA", "same position, STA");
        }

        [S3("N-32", "the requested index is kept when an earlier station is 40.5 m / 50.0 m behind it", Red = S3.NoV2)]
        internal static void N32(S3Ctx s)
        {
            KeepsIndex(s, new double[] { 0.5, 1000.5, 1959.5, 2000.0, 3000.0 }, 3, "STA", "40.5 m nearby, STA");
            KeepsIndex(s, new double[] { 0.5, 1000.5, 1950.0, 2000.0, 3000.0 }, 3, "STA", "50.0 m nearby, STA");
        }

        [S3("N-61", "a location jump re-initialises the target with the adopted index (same position, 40.5 m, index 0)", Red = S3.NoV2)]
        internal static void N61(S3Ctx s)
        {
            KeepsIndex(s, new double[] { 0.5, 1000.5, 2000.0, 2000.0, 3000.0 }, 3, "LOC", "same position, LOC");
            KeepsIndex(s, new double[] { 0.5, 1000.5, 1959.5, 2000.0, 3000.0 }, 3, "LOC", "40.5 m nearby, LOC");
            KeepsIndex(s, new double[] { 100.5, 1000.5, 2000.0, 3000.0 }, 0, "LOC", "index 0, LOC");
        }

        [S3("N-62", "a list that can no longer carry the index never falls back to the position search; the completion is abandoned", Red = S3.NoV2)]
        internal static void N62(S3Ctx s)
        {
            double[] st = new double[] { 0.5, 1000.5, 2000.25, 3000.125, 4000.0 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            int t = S3.NextTime();
            byte[] rid = Cmd.Rid();
            RecView a = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 4, st[4], t), rid);
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, "the v2 command for the last station is queued", a == null ? "null" : a.Short);
            // the host's list loses its last two stations while the jump runs: after the jump the rebuilt list has 3 stations and index 4 does not exist
            x.Host.InsideCall = delegate
            {
                while (x.Api.Stations.Count > 3) x.Api.Stations.RemoveAt(x.Api.Stations.Count - 1);
            };
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Contract(S3.NoV2, r != null && r.State == Ls.Abandoned && r.Reason != null && r.Reason.StartsWith("reinit-", StringComparison.Ordinal), "the command ends Abandoned(reinit-...)", r == null ? "null" : r.Short);
            s.Contract(S3.NoV2, x.Sender.Calls == 0, "no completion was sent", "" + x.Sender.Calls);
            s.Contract(S3.NoV2, S3.Tgt(x) == 1, "the target is left alone (index 1, the station of the earlier jump), not chosen again from the vehicle position", "" + S3.Tgt(x));
        }

        // =====================================================================================================================================
        // one-shot target, directly on the timeline
        // =====================================================================================================================================
        private static IList<LegacyStationRaw> Raw(double[] st)
        {
            List<LegacyStationRaw> l = new List<LegacyStationRaw>();
            for (int i = 0; i < st.Length; i++)
            {
                LegacyStationRaw r = new LegacyStationRaw();
                r.Name = "S" + i;
                r.Location = st[i];
                r.DoorSide = 1;
                r.ArrivalMs = -1;
                r.DepartureMs = -1;
                r.DefaultMs = -1;
                r.StoppageMs = 15000;
                r.MarginMin = -5.0;
                r.MarginMax = 5.0;
                l.Add(r);
            }
            return l;
        }

        private static int Target(LegacyStationTimeline tl) { return tl.TargetIndex; }

        [S3("N-35", "RequestTarget is one-shot: consumed once, expires over a Tick, cleared by Reset; other discontinuities stay position based", Red = "RequestTarget")]
        internal static void N35(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 1959.5, 2000.0, 3000.0 };
            IList<LegacyStationRaw> raw = Raw(st);
            LegacyStationTimeline tl = new LegacyStationTimeline();
            tl.Step(raw, st.Length, 500.0, 0.0, 36000000, true);
            s.Premise(Target(tl) == 1, "without a request the first Tick chooses by position (station 1 at 1000.5 for a vehicle at 500)", "" + Target(tl));
            tl.MarkDiscontinuity();
            tl.Step(raw, st.Length, 2000.0, 0.0, 36100000, true);
            s.Premise(Target(tl) == 2, "a plain discontinuity chooses by position (index 2 at 1959.5 is within 50 m behind 2000.0)", "" + Target(tl));

            Pr.Call(tl, "RequestTarget", 3, 2000.0);
            tl.MarkDiscontinuity();
            tl.Step(raw, st.Length, 2000.0, 0.0, 36200000, true);
            s.Contract("request-not-kept", Target(tl) == 3, "the requested index 3 is the target although the position search would give 2", "" + Target(tl));
            tl.MarkDiscontinuity();
            tl.Step(raw, st.Length, 2000.0, 0.0, 36300000, true);
            s.Contract("request-not-consumed", Target(tl) == 2, "the request was consumed: the next discontinuity is position based again", "" + Target(tl));

            Pr.Call(tl, "RequestTarget", 3, 2000.0);
            object wasPending = Pr.Call(tl, "ExpireRequestedTarget");
            object notApplied = Pr.Call(tl, "TakeRequestRefusal");
            s.Contract("expiry-not-reported", wasPending is bool && (bool)wasPending && notApplied != null && (string)notApplied == "reinit-not-applied", "expiring a pending request says so and reports reinit-not-applied", wasPending + " / " + notApplied);
            tl.MarkDiscontinuity();
            tl.Step(raw, st.Length, 2000.0, 0.0, 36400000, true);
            s.Contract("request-not-expired", Target(tl) == 2, "an expired request is gone (a request that crossed a Tick without a station build)", "" + Target(tl));
            object nothing = Pr.Call(tl, "ExpireRequestedTarget");
            s.Contract("expiry-of-nothing", nothing is bool && !(bool)nothing, "expiring nothing says so", "" + nothing);

            Pr.Call(tl, "RequestTarget", 3, 2000.0);
            tl.Reset();
            tl.Step(raw, st.Length, 2000.0, 0.0, 36500000, true);
            s.Contract("request-survives-reset", Target(tl) == 2, "Reset() clears the request", "" + Target(tl));

            Pr.Call(tl, "RequestTarget", 9, 2000.0);
            tl.MarkDiscontinuity();
            int before = Target(tl);
            tl.Step(raw, st.Length, 2000.0, 0.0, 36600000, true);
            object why = Pr.Call(tl, "TakeRequestRefusal");
            s.Contract("refusal-not-reported", why != null && ((string)why).StartsWith("reinit-", StringComparison.Ordinal), "an index the list can not carry is refused with a reinit-... word", "" + why);
            s.Contract("refusal-falls-back", Target(tl) == before, "and the target is left alone (no position search)", "was " + before + " now " + Target(tl));
            object again = Pr.Call(tl, "TakeRequestRefusal");
            s.Contract("refusal-reported-twice", again == null, "the refusal is reported once", "" + again);

            Pr.Call(tl, "RequestTarget", 3, 2000.5);
            tl.MarkDiscontinuity();
            before = Target(tl);
            tl.Step(raw, st.Length, 2000.0, 0.0, 36700000, true);
            why = Pr.Call(tl, "TakeRequestRefusal");
            s.Contract("location-refusal-not-reported", why != null && ((string)why) == "reinit-location-mismatch", "a location that is not the station's is refused (reinit-location-mismatch)", "" + why);
            s.Contract("location-refusal-falls-back", Target(tl) == before, "and the target is left alone", "was " + before + " now " + Target(tl));
        }

        [S3("N-63", "re-initialisations that carry no index stay position based (first Tick, scenario change, station count change, manual time jump)", Kind = "GUARD")]
        internal static void N63(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 1959.5, 2000.0, 3000.0 };
            IList<LegacyStationRaw> raw = Raw(st);
            LegacyStationTimeline tl = new LegacyStationTimeline();
            tl.Step(raw, st.Length, 1990.0, 0.0, 36000000, true);
            s.Contract("first-tick-not-position-based", Target(tl) == 2, "the first Tick chooses by position (1959.5 is within 50 m behind 1990.0)", "" + Target(tl));
            tl.MarkDiscontinuity();
            tl.Step(raw, st.Length, 2500.0, 0.0, 36100000, true);
            s.Contract("discontinuity-not-position-based", Target(tl) == 4, "a manual time jump chooses by position (first station at or after 2450)", "" + Target(tl));
            tl.Reset();
            tl.Step(raw, st.Length, 50.0, 0.0, 36200000, true);
            s.Contract("scenario-change-not-position-based", Target(tl) == 0, "after Reset (a scenario change) the choice is by position again", "" + Target(tl));
            double[] six = new double[] { 100.5, 1000.5, 1959.5, 2000.0, 3000.0, 4000.0 };
            tl.Step(Raw(six), six.Length, 3500.0, 0.0, 36300000, true);
            s.Contract("count-change-not-position-based", Target(tl) == 5, "a changed station count rebuilds and chooses by position", "" + Target(tl));
        }

        // =====================================================================================================================================
        // refusals: before the claim, not a breaker failure
        // =====================================================================================================================================
        private static void RefusalRound(S3Ctx s, LxRig x, S3.Bad bad, int rounds, bool strict)
        {
            for (int k = 0; k < rounds; k++)
            {
                long claimed = x.Counter("claimed");
                S3.ClearCalls(x);
                byte[] rid = Cmd.Rid();
                RecView rv = S3.SendV2(x, bad.Kind, bad.Text, rid);
                s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, bad.Name + ": the gate lets the well-formed v2 command in", rv == null ? "null" : rv.Short);
                if (rv == null || rv.State != CState.Queued) return;
                x.Tick(16);
                LxRec r = x.Rec(rid);
                s.Contract(S3.NoV2, r != null && r.State == Ls.Discarded && r.Reason == "contract-" + bad.Word, bad.Name + ": the command is Discarded(contract-" + bad.Word + ") by the claim", r == null ? "null" : r.Short);
                s.Contract(S3.NoV2, x.Host.ApiCalls == 0, bad.Name + ": the host API was not called", S3.Calls(x));
                if (strict)
                {
                    s.Contract(S3.NoV2, x.Counter("claimed") == claimed, bad.Name + ": nothing was claimed", "claimed " + claimed + " -> " + x.Counter("claimed"));
                    s.Contract(S3.NoV2, S3.InFlight(x) == null, bad.Name + ": nothing is in flight", "");
                    s.Contract(S3.NoV2, x.Sender.Calls == 0, bad.Name + ": no completion was handed over", "" + x.Sender.Calls);
                }
            }
        }

        [S3("N-33", "a contradiction or a scope mismatch is refused: no host call, Discarded, never counted by the breaker", Red = S3.NoV2)]
        internal static void N33(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            foreach (S3.Bad b in S3.BadRequests(x, st)) RefusalRound(s, x, b, 1, true);
            s.Contract(S3.NoV2, S3.Failures(x) == 0, "no refusal was counted as a failure of the breaker", "" + S3.Failures(x));
            s.Contract(S3.NoV2, x.Illegal == 0, "illegal-transition is 0", "" + x.Illegal);
        }

        [S3("N-54", "validation refusals are not breaker failures: 18 refusals leave the jump available and the next good command runs", Red = S3.NoV2)]
        internal static void N54(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            foreach (S3.Bad b in S3.BadRequests(x, st)) RefusalRound(s, x, b, 3, false);
            s.Contract(S3.NoV2, S3.Failures(x) == 0, "the consecutive failure count is 0 after 18 refusals", "" + S3.Failures(x));
            s.Contract(S3.NoV2, !S3.BreakerOpen(x), "the breaker is closed", "");
            s.Contract(S3.NoV2, S3.JumpAvailable(x), "AVAIL jump is still announced", "");
            S3.ClearCalls(x);
            byte[] rid = Cmd.Rid();
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "a good command is queued after the refusals", rv == null ? "null" : rv.Short);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Contract(S3.NoV2, r != null && r.State == Ls.Completed && S3.Has(x, "MoveToStation(2)"), "and is executed and completed", r == null ? "null" : r.Short + " " + S3.Calls(x));
        }

        [S3("N-55", "a validation refusal happens before the claim (claimed 0, nothing in flight, Discarded and not Failed)", Red = S3.NoV2)]
        internal static void N55(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            long claimed = x.Counter("claimed");
            long failed = x.Counter("failed");
            List<S3.Bad> bad = S3.BadRequests(x, st);
            RefusalRound(s, x, bad[0], 1, true);
            RefusalRound(s, x, bad[3], 1, true);
            s.Contract(S3.NoV2, x.Counter("claimed") == claimed, "the claimed counter did not move", claimed + " -> " + x.Counter("claimed"));
            s.Contract(S3.NoV2, x.Counter("failed") == failed, "the failed counter did not move (the refusal is not an execution failure)", failed + " -> " + x.Counter("failed"));
            s.Contract(S3.NoV2, x.Counter("discarded:contract-scenario-mismatch") == 1 && x.Counter("discarded:contract-location-mismatch") == 1, "each refusal is booked as a discard with its word", "");
        }

        // =====================================================================================================================================
        // the executor: exact location (v2), the old tolerance (v1), failures still count
        // =====================================================================================================================================
        [S3("N-36", "v2: the read-back location must EQUAL the station's; one ulp away fails (a breaker failure); v1 keeps its 0.01 m", Red = S3.NoV2)]
        internal static void N36(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            byte[] ok = Cmd.Rid();
            RecView a = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), ok);
            s.Contract(S3.NoV2, a != null && a.State == CState.Queued, "the v2 command is queued", a == null ? "null" : a.Short);
            x.Tick(16);
            LxRec r1 = x.Rec(ok);
            s.Contract(S3.NoV2, r1 != null && r1.State == Ls.Completed, "an equal read-back location succeeds", r1 == null ? "null" : r1.Short);
            x.Host.LocationSkew = S3.NextUp(st[3]) - st[3];
            byte[] bad = Cmd.Rid();
            RecView b = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 3, st[3], S3.NextTime()), bad);
            s.Contract(S3.NoV2, b != null && b.State == CState.Queued, "the second v2 command is queued", b == null ? "null" : b.Short);
            x.Tick(16);
            LxRec r2 = x.Rec(bad);
            s.Contract(S3.NoV2, r2 != null && r2.State == Ls.Failed && r2.Reason == "readback-location-mismatch", "a read-back one ulp away fails with readback-location-mismatch", r2 == null ? "null" : r2.Short);
            s.Contract(S3.NoV2, S3.Failures(x) == 1, "and it IS an execution failure of the breaker", "" + S3.Failures(x));
            s.Contract(S3.NoV2, x.Sender.Calls == 1, "no completion for the failed command (one for the good one)", "" + x.Sender.Calls);
        }

        [S3("N-60", "an execution failure after the claim still counts: three in a row open the breaker, a success resets it", Red = S3.NoV2)]
        internal static void N60(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            x.Host.ThrowOn = "MoveToStation";
            for (int k = 0; k < 2; k++)
            {
                byte[] rid = Cmd.Rid();
                RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid);
                s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "a v2 command is queued (" + k + ")", rv == null ? "null" : rv.Short);
                x.Tick(16);
                LxRec r = x.Rec(rid);
                s.Contract(S3.NoV2, r != null && r.State == Ls.Failed && r.Reason == "api-exception", "it fails with api-exception (" + k + ")", r == null ? "null" : r.Short);
            }
            s.Contract(S3.NoV2, S3.Failures(x) == 2 && !S3.BreakerOpen(x), "two failures: counted, the breaker is still closed", "" + S3.Failures(x));
            x.Host.ThrowOn = null;
            byte[] okRid = Cmd.Rid();
            RecView okv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), okRid);
            s.Contract(S3.NoV2, okv != null && okv.State == CState.Queued, "a good command is queued", okv == null ? "null" : okv.Short);
            x.Tick(16);
            s.Contract(S3.NoV2, S3.Failures(x) == 0, "a success resets the count", "" + S3.Failures(x));
            x.Host.ThrowOn = "MoveToStation";
            for (int k = 0; k < 3; k++)
            {
                RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 3, st[3], S3.NextTime()), Cmd.Rid());
                s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "a v2 command is queued (3x " + k + ")", rv == null ? "null" : rv.Short);
                x.Tick(16);
            }
            s.Contract(S3.NoV2, S3.BreakerOpen(x) && !S3.JumpAvailable(x), "three in a row: the breaker is open and AVAIL jump closes", "failures " + S3.Failures(x));
            byte[] late = Cmd.Rid();
            RecView lv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), late);
            s.Contract(S3.NoV2, lv != null && lv.State == CState.Queued, "a further command is queued", lv == null ? "null" : lv.Short);
            x.Tick(16);
            LxRec lr = x.Rec(late);
            s.Contract(S3.NoV2, lr != null && lr.State == Ls.Discarded && lr.Reason == "breaker-open", "and is Discarded(breaker-open)", lr == null ? "null" : lr.Short);
            s.Contract(S3.NoV2, S3.Failures(x) == 3, "a command discarded at the claim is not a further failure (the count stays at the three that opened the breaker)", "" + S3.Failures(x));
        }

        [S3("N-59", "the claim of a v2 command is exclusive and written before the host call; one in flight", Red = S3.NoV2)]
        internal static void N59(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            long claimed = x.Counter("claimed");
            byte[] rid = Cmd.Rid();
            int stateInside = -1;
            x.Host.InsideCall = delegate { LxRec r0 = x.Rec(rid); if (stateInside < 0 && r0 != null) stateInside = r0.State; };
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the v2 command is queued", rv == null ? "null" : rv.Short);
            x.Tick(16);
            s.Contract(S3.NoV2, stateInside == Ls.Executing, "the receipt is Executing while the host call runs (written before the call)", "" + stateInside);
            s.Contract(S3.NoV2, x.Counter("claimed") == claimed + 1, "exactly one claim", claimed + " -> " + x.Counter("claimed"));
            s.Contract(S3.NoV2, x.Counter("max-in-flight") <= 1, "never more than one in flight", "" + x.Counter("max-in-flight"));
            s.Contract(S3.NoV2, x.Illegal == 0, "illegal-transition is 0", "" + x.Illegal);
        }

        [S3("N-58", "the 5.0 s TTL applies to a v2 command unchanged (5001 ms: Discarded(ttl); exactly 5000 ms: still claimable)", Red = S3.NoV2)]
        internal static void N58(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            byte[] rid = Cmd.Rid();
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the v2 command is queued", rv == null ? "null" : rv.Short);
            x.Clk.Advance(5001);
            s.Contract(S3.NoV2, Wait.For(delegate { LxRec q = x.Rec(rid); return q != null && q.State == Ls.Discarded && q.Reason == "ttl"; }, 3000), "after 5001 ms the sweep discards it (ttl)", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            x.Tick(16);
            s.Contract(S3.NoV2, x.Host.ApiCalls == 0, "the host was never called for the expired command", "" + x.Host.ApiCalls);
            s.Contract(S3.NoV2, S3.Failures(x) == 0, "an expired command is not a failure of the breaker (nothing was claimed)", "" + S3.Failures(x));
            byte[] rid2 = Cmd.Rid();
            RecView rv2 = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid2);
            s.Contract(S3.NoV2, rv2 != null && rv2.State == CState.Queued, "a second v2 command is queued", rv2 == null ? "null" : rv2.Short);
            x.Clk.Advance(5000);
            Kit.Settle(x.P, 6, 3000);
            LxRec q2 = x.Rec(rid2);
            s.Contract(S3.NoV2, q2 != null && q2.State == Ls.Queued, "at exactly 5000 ms it is still Queued", q2 == null ? "null" : q2.Short);
            x.Tick(16);
            q2 = x.Rec(rid2);
            s.Contract(S3.NoV2, q2 != null && q2.State == Ls.Completed, "and is executed and completed", q2 == null ? "null" : q2.Short);
        }

        // =====================================================================================================================================
        // the completion
        // =====================================================================================================================================
        [S3("N-56", "completion v2: nine fields, the adopted index, the scope of now, the measured location through the canonical codec", Red = S3.NoV2)]
        internal static void N56(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            int t = S3.NextTime();
            byte[] rid = Cmd.Rid();
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], t), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the v2 station command is queued", rv == null ? "null" : rv.Short);
            x.Tick(16);
            string reason = null;
            string payload = x.Sender.LastPayload;
            JumpWireCompletion c = payload == null ? null : S3.Completion(payload, out reason);
            s.Contract(S3.NoV2, c != null && c.Version == 2, "the completion is a v2 completion (nine fields)", payload + " " + reason);
            if (c != null && c.Version == 2)
            {
                s.Contract(S3.NoV2, c.Kind == "STA" && c.SelectedIndex == 2, "kind STA and the adopted index 2", c.Kind + "/" + c.SelectedIndex);
                s.Contract(S3.NoV2, c.Location == st[2], "the location is the measured one (equal to the station's)", S3.D(c.Location));
                s.Contract(S3.NoV2, c.TimeMs == t, "the time is the time of the command", "" + c.TimeMs);
                s.Contract(S3.NoV2, c.Scope != null && c.Scope.ScenarioId == S3.ScenarioId(x) && c.Scope.ListId == S3.ListId(x) && c.Scope.Count == S3.Count(x), "the scope is the scope of now", c.Scope == null ? "null" : c.Scope.ScenarioId + "/" + c.Scope.ListId + "/" + c.Scope.Count);
                s.Contract(S3.NoV2, c.JumpCount >= 0, "the jump counter is the counter of the row", "" + c.JumpCount);
            }
            // a location command carries the adopted index too (not -1)
            byte[] rid2 = Cmd.Rid();
            int t2 = S3.NextTime();
            RecView rv2 = S3.SendV2(x, "LOC", S3.V2Now(x, "LOC", 1, st[1], t2), rid2);
            s.Contract(S3.NoV2, rv2 != null && rv2.State == CState.Queued, "the v2 location command is queued", rv2 == null ? "null" : rv2.Short);
            x.Tick(16);
            payload = x.Sender.LastPayload;
            JumpWireCompletion c2 = payload == null ? null : S3.Completion(payload, out reason);
            s.Contract(S3.NoV2, c2 != null && c2.Version == 2 && c2.Kind == "LOC" && c2.SelectedIndex == 1, "the location completion carries the adopted index 1, not -1", payload + " " + reason);
            s.Contract(S3.NoV2, c2 != null && c2.Location == st[1], "and the measured location", c2 == null ? "null" : S3.D(c2.Location));
        }

        [S3("N-57", "one completion per request: success, held then sent, failure, refusal, expiry, scenario change, Dispose, duplicate id", Red = S3.NoV2)]
        internal static void N57(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            // 1 success, then more Ticks: exactly one send
            byte[] rid = Cmd.Rid();
            string text = S3.V2Now(x, "STA", 2, st[2], S3.NextTime());
            RecView rv = S3.SendV2(x, "STA", text, rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the v2 command is queued", rv == null ? "null" : rv.Short);
            for (int k = 0; k < 6; k++) x.Tick(16);
            s.Contract(S3.NoV2, x.Sender.Calls == 1, "success: one send over seven Ticks", "" + x.Sender.Calls);
            // the same request id again: the validator refuses it, nothing runs
            S3.ClearCalls(x);
            RecView dup = S3.SendV2(x, "STA", text, rid);
            x.Tick(16);
            s.Contract(S3.NoV2, dup != null && dup.State == CState.Rejected && x.Host.ApiCalls == 0 && x.Sender.Calls == 1, "a repeated request id is rejected: no second execution, no second completion", dup == null ? "null" : dup.Short + " calls " + x.Host.ApiCalls + " sends " + x.Sender.Calls);
            // 2 held, held, then sent: the same payload each time, one datagram
            x.Sender.Script.Enqueue(Ls.SendHeld);
            x.Sender.Script.Enqueue(Ls.SendHeld);
            int before = x.Sender.Calls;
            byte[] rid2 = Cmd.Rid();
            RecView rv2 = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 1, st[1], S3.NextTime()), rid2);
            s.Contract(S3.NoV2, rv2 != null && rv2.State == CState.Queued, "a second v2 command is queued", rv2 == null ? "null" : rv2.Short);
            for (int k = 0; k < 6; k++) x.Tick(16);
            int attempts = x.Sender.Calls - before;
            bool same = true;
            string first = null;
            lock (x.Sender.Payloads) { for (int i = before; i < x.Sender.Payloads.Count; i++) { if (first == null) first = x.Sender.Payloads[i]; else if (x.Sender.Payloads[i] != first) same = false; } }
            s.Contract(S3.NoV2, attempts == 3 && same, "held, held, sent: three attempts with one and the same payload, then no more", attempts + " " + same);
            LxRec r2 = x.Rec(rid2);
            s.Contract(S3.NoV2, r2 != null && r2.State == Ls.Completed, "and the receipt is Completed", r2 == null ? "null" : r2.Short);
            // 3 execution failure: no completion at all
            before = x.Sender.Calls;
            x.Host.ThrowOn = "MoveToStation";
            byte[] rid3 = Cmd.Rid();
            S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid3);
            for (int k = 0; k < 3; k++) x.Tick(16);
            x.Host.ThrowOn = null;
            s.Contract(S3.NoV2, x.Sender.Calls == before, "failure: no completion", (x.Sender.Calls - before) + " sends");
            // 4 a refusal: no completion
            before = x.Sender.Calls;
            S3.Bad bad = S3.BadRequests(x, st)[0];
            S3.SendV2(x, bad.Kind, bad.Text, Cmd.Rid());
            for (int k = 0; k < 3; k++) x.Tick(16);
            s.Contract(S3.NoV2, x.Sender.Calls == before, "refusal: no completion", (x.Sender.Calls - before) + " sends");
            // 5 a scenario change between the execution and the completion: abandoned, no completion
            before = x.Sender.Calls;
            byte[] rid5 = Cmd.Rid();
            RecView rv5 = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 2, st[2], S3.NextTime()), rid5);
            s.Contract(S3.NoV2, rv5 != null && rv5.State == CState.Queued, "a command for the scenario-change case is queued", rv5 == null ? "null" : rv5.Short);
            x.Mono += 16; x.Host.TimeMs += 16; x.Api.TimeMs = x.Host.TimeMs;
            x.PreOnly();
            x.P.NoteScenarioBoundary();
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            LxRec r5 = x.Rec(rid5);
            s.Contract(S3.NoV2, x.Sender.Calls == before && r5 != null && r5.State == Ls.Abandoned, "a scenario change before the hand-over abandons it: no completion", r5 == null ? "null" : r5.Short + " " + (x.Sender.Calls - before) + " sends");
            // 6 Dispose with a command queued: nothing is sent afterwards
            before = x.Sender.Calls;
            x.P.Dispose();
            for (int k = 0; k < 3; k++) x.Tick(16);
            s.Contract(S3.NoV2, x.Sender.Calls == before, "Dispose: no completion afterwards", (x.Sender.Calls - before) + " sends");
        }

        // =====================================================================================================================================
        // diagnostics
        // =====================================================================================================================================
        [S3("N-66", "a refusal leaves one line with reason / req_idx / req_count / current_count: numbers and words only, 200 characters at most", Red = S3.NoV2)]
        internal static void N66(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            string text = S3.V2Now(x, "STA", 2, st[2], S3.NextTime()).Replace(":4:2000.25", ":5:2000.25");
            s.Premise(text.Contains(":5:2000.25"), "the fixture command names count 5", text);
            byte[] rid = Cmd.Rid();
            int linesBefore = x.LinesWith("event=legacy-jump-refused").Count;
            RecView rv = S3.SendV2(x, "STA", text, rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the command is queued", rv == null ? "null" : rv.Short);
            for (int k = 0; k < 4; k++) x.Tick(16);
            List<string> lines = x.LinesWith("event=legacy-jump-refused");
            s.Contract(S3.NoV2, lines.Count == linesBefore + 1, "exactly one refusal line for the request (not one per Tick)", "" + (lines.Count - linesBefore));
            string line = lines.Count > 0 ? lines[lines.Count - 1] : "";
            s.Contract(S3.NoV2, line.Contains(" reason=count-mismatch") && line.Contains(" req_idx=2") && line.Contains(" req_count=5") && line.Contains(" current_count=4"), "it names the reason and the three numbers", line);
            s.Contract(S3.NoV2, line.Length > 0 && line.Length <= 200, "it is at most 200 characters", "" + line.Length);
            s.Contract(S3.NoV2, !line.Contains("JUMP_") && !line.Contains(text), "and carries no part of the command text", line);
            s.Contract(S3.NoV2, line.Contains(" id=" + FakeSource.Hex(rid).Substring(0, 8)), "the request is identified by the first four bytes of its id", line);
        }

        // =====================================================================================================================================
        // formal v1 keeps its semantics (GUARD)
        // =====================================================================================================================================
        [S3("N-67", "a formal v1 command is executed as before: station completion with the index, location completion with -1, 0.01 m tolerance", Kind = "GUARD")]
        internal static void N67(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            byte[] ridA = Cmd.Rid();
            RecView a = x.SendSta(ridA, 2, S3.NextTime());
            s.Contract("v1-sta-refused", a != null && a.State == CState.Queued, "the v1 station command is queued", a == null ? "null" : a.Short);
            x.Tick(16);
            LxRec ra = x.Rec(ridA);
            s.Contract("v1-sta-not-completed", ra != null && ra.State == Ls.Completed, "it is executed and completed", ra == null ? "null" : ra.Short);
            s.Contract("v1-sta-payload", x.Sender.LastPayload != null && x.Sender.LastPayload.StartsWith("JUMP_COMPLETE:STA:2:2000.25:", StringComparison.Ordinal) && x.Sender.LastPayload.Split(':').Length == 6, "the completion is the six field v1 text with the index", x.Sender.LastPayload);
            byte[] ridB = Cmd.Rid();
            RecView b = x.SendLoc(ridB, 1000.5, S3.NextTime());
            s.Contract("v1-loc-refused", b != null && b.State == CState.Queued, "the v1 location command is queued", b == null ? "null" : b.Short);
            x.Tick(16);
            LxRec rb = x.Rec(ridB);
            s.Contract("v1-loc-not-completed", rb != null && rb.State == Ls.Completed, "it is executed and completed", rb == null ? "null" : rb.Short);
            s.Contract("v1-loc-payload", x.Sender.LastPayload != null && x.Sender.LastPayload.StartsWith("JUMP_COMPLETE:LOC:-1:1000.5:", StringComparison.Ordinal), "the location completion carries -1", x.Sender.LastPayload);
            x.Host.LocationSkew = 0.005;
            byte[] ridC = Cmd.Rid();
            x.SendSta(ridC, 3, S3.NextTime());
            x.Tick(16);
            LxRec rc = x.Rec(ridC);
            s.Contract("v1-tolerance-lost", rc != null && rc.State == Ls.Completed, "a read-back 0.005 m away is still accepted for v1", rc == null ? "null" : rc.Short);
            x.Host.LocationSkew = 0.02;
            byte[] ridD = Cmd.Rid();
            x.SendSta(ridD, 2, S3.NextTime());
            x.Tick(16);
            LxRec rd = x.Rec(ridD);
            s.Contract("v1-tolerance-widened", rd != null && rd.State == Ls.Failed && rd.Reason == "readback-location-mismatch", "and 0.02 m away still fails", rd == null ? "null" : rd.Short);
        }

        // =====================================================================================================================================
        // the numbers of the STALIST
        // =====================================================================================================================================
        [S3("N-65", "STALIST positions are written by the canonical codec and read back exactly (also under another culture)", Red = "stalist-not-canonical")]
        internal static void N65(S3Ctx s)
        {
            // positions whose "R" text is not the exact shortest text of the contract (found deterministically)
            List<double> samples = new List<double>();
            long seed = 20261023;
            for (int i = 0; i < 300000 && samples.Count < 3; i++)
            {
                seed = (seed * 6364136223846793005L + 1442695040888963407L);
                double v = ((double)((ulong)seed >> 11) / 9007199254740992.0) * 50000.0;
                string reason;
                string canon = JumpWire.FormatLocation(v, out reason);
                if (canon != null && canon != v.ToString("R", CultureInfo.InvariantCulture)) samples.Add(v);
            }
            s.Premise(samples.Count >= 1, "the fixture found positions where the \"R\" text differs from the canonical text", "" + samples.Count);
            samples.Add(1000.5);
            samples.Add(0.1);
            double[] st = samples.ToArray();
            Array.Sort(st);
            LegacyStationTimeline tl = new LegacyStationTimeline();
            tl.Step(Raw(st), st.Length, 0.0, 0.0, 36000000, true);
            CultureInfo saved = Thread.CurrentThread.CurrentCulture;
            try
            {
                Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
                string sta = tl.ComposeStaList();
                s.Premise(sta != null && sta.StartsWith("STALIST:", StringComparison.Ordinal), "a STALIST text is composed");
                string[] stations = sta.Substring(8).Split(',');
                s.Premise(stations.Length == st.Length, "it has one entry per station", stations.Length + "/" + st.Length);
                int exact = 0;
                for (int i = 0; i < stations.Length && i < st.Length; i++)
                {
                    string[] f = stations[i].Split('=');
                    double back = 0.0;
                    string why = f.Length > 2 ? JumpWire.ParseLocation(f[2], out back) : "fields";
                    string reason2;
                    string canon = JumpWire.FormatLocation(st[i], out reason2);
                    if (why == null && back == st[i] && f[2] == canon) exact++;
                }
                s.Contract("stalist-not-canonical", exact == st.Length, "every position is the canonical text of the station's location and reads back exactly", exact + "/" + st.Length + " in " + sta);
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = saved;
            }
        }

        // =====================================================================================================================================
        // R1-B: the STALIST / META acknowledgement
        // =====================================================================================================================================
        [S3("R1B-1", "while the sink refuses, the STALIST is not marked sent and is tried on every Tick", Red = "ITelemetrySinkAck")]
        internal static void R1B1(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 6; k++) r.Tick(100);
            s.Contract("sent-flag-set-without-ack", !r.Flag("staListSent"), "staListSent stays false", "");
            s.Contract("not-retried", r.Sink.Count(r.Sink.Tried, "STALIST:") == 6, "one attempt per Tick (6 of 6)", "" + r.Sink.Count(r.Sink.Tried, "STALIST:"));
            s.Contract("sent-without-ack", r.Sink.Count(r.Sink.Accepted, "STALIST:") == 0, "nothing was accepted", "");
        }

        [S3("R1B-2", "the first acceptance marks it sent; no resend until the interval has passed", Red = "ITelemetrySinkAck")]
        internal static void R1B2(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 3; k++) r.Tick(100);
            r.Sink.Accept = true;
            r.Tick(100);
            s.Contract("acceptance-not-booked", r.Flag("staListSent") && r.Sink.Count(r.Sink.Accepted, "STALIST:") == 1, "the first accepted attempt marks it sent", "accepted " + r.Sink.Count(r.Sink.Accepted, "STALIST:"));
            int triesAfter = r.Sink.Count(r.Sink.Tried, "STALIST:");
            for (int k = 0; k < 8; k++) r.Tick(100);
            s.Contract("duplicate-resend", r.Sink.Count(r.Sink.Tried, "STALIST:") == triesAfter, "no further attempt for 800 ms (READY: no duplicates)", (r.Sink.Count(r.Sink.Tried, "STALIST:") - triesAfter) + " extra");
            for (int k = 0; k < 3; k++) r.Tick(100);
            s.Contract("periodic-resend-lost", r.Sink.Count(r.Sink.Accepted, "STALIST:") == 2, "after the 1000 ms interval the periodic resend happens once", "accepted " + r.Sink.Count(r.Sink.Accepted, "STALIST:"));
        }

        [S3("R1B-3", "a list rebuilt while the sink refuses is sent as the CURRENT list (its list id)", Red = "ITelemetrySinkAck")]
        internal static void R1B3(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 2; k++) r.Tick(100);
            string firstId = r.ListId;
            FakeStation extra = new FakeStation();
            extra.Name = "S9";
            extra.Location = 9500.0;
            r.Api.Stations.Add(extra);
            r.Tick(100);
            string nowId = r.ListId;
            s.Premise(nowId != firstId, "the rebuilt list has another list id", firstId + " -> " + nowId);
            r.Sink.Accept = true;
            r.Tick(100);
            string accepted = r.Sink.Last(r.Sink.Accepted, "STALIST:");
            s.Contract("stale-list-sent", accepted != null && StationListIdentity.Compute(accepted.Substring(8)) == nowId, "the accepted STALIST is the current list", accepted == null ? "null" : StationListIdentity.Compute(accepted.Substring(8)) + " vs " + nowId);
        }

        [S3("R1B-4", "a scenario change, OnScenarioOpened or a reload resets the flag; the old list is never sent again", Red = "ITelemetrySinkAck")]
        internal static void R1B4(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 2; k++) r.Tick(100);
            string oldId = r.ListId;
            // a different scenario with different stations
            r.Api.Scenario = new object();
            r.Api.Stations.Clear();
            for (int i = 0; i < 4; i++) { FakeStation st = new FakeStation(); st.Name = "N" + i; st.Location = 700.0 + 900.0 * i; r.Api.Stations.Add(st); }
            int triesBefore = r.Sink.Tried.Count;                        // the position in the list of every offered text (STALIST and META)
            r.Tick(100);
            r.Tick(100);
            string newId = r.ListId;
            s.Premise(newId != oldId, "the new scenario has another list", oldId + " -> " + newId);
            int stale = 0;
            lock (r.Sink.Tried) { for (int i = triesBefore; i < r.Sink.Tried.Count; i++) if (r.Sink.Tried[i].StartsWith("STALIST:", StringComparison.Ordinal) && StationListIdentity.Compute(r.Sink.Tried[i].Substring(8)) == oldId) stale++; }
            s.Contract("old-list-resent", stale == 0, "the old list is not offered again after the scenario changed", "" + stale);
            r.Sink.Accept = true;
            r.Tick(100);
            s.Contract("new-list-not-sent", r.Sink.Count(r.Sink.Accepted, "STALIST:") == 1 && StationListIdentity.Compute(r.Sink.Last(r.Sink.Accepted, "STALIST:").Substring(8)) == newId, "the new list is accepted", "");
            // accepted, then a reload: the flag goes back to false and the list is offered at once
            Pr.Call(r.Session, "OnScenarioOpened", true);
            s.Contract("flag-kept-over-reload", !r.Flag("staListSent"), "OnScenarioOpened(reload) resets the flag", "");
            int acceptedBefore = r.Sink.Count(r.Sink.Accepted, "STALIST:");
            r.Tick(100);
            r.Tick(100);
            s.Contract("not-resent-after-reload", r.Sink.Count(r.Sink.Accepted, "STALIST:") > acceptedBefore, "and the list is offered again", "");
        }

        [S3("R1B-5", "after OnDispose nothing is sent and nothing is kept", Red = "ITelemetrySinkAck")]
        internal static void R1B5(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 3; k++) r.Tick(100);
            int tried = r.Sink.Count(r.Sink.Tried, "STALIST:");
            Pr.Call(r.Session, "OnDispose");
            r.Sink.Accept = true;
            for (int k = 0; k < 15; k++) r.Tick(100);
            s.Contract("sent-after-dispose", r.Sink.Count(r.Sink.Tried, "STALIST:") == tried && r.Sink.AfterClose == 0, "no attempt after Dispose", (r.Sink.Count(r.Sink.Tried, "STALIST:") - tried) + " extra, after close " + r.Sink.AfterClose);
            s.Contract("sink-not-closed", r.Sink.Closed, "the sink was closed", "");
            bool keepsText = false;
            foreach (FieldInfo f in r.Session.GetType().GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public))
            {
                if (f.FieldType != typeof(string)) continue;
                string v = f.GetValue(r.Session) as string;
                if (v != null && (v.StartsWith("STALIST:", StringComparison.Ordinal) || v.StartsWith("META:", StringComparison.Ordinal))) keepsText = true;
            }
            s.Contract("text-kept", !keepsText, "the session keeps no STALIST / META text", "");
        }

        [S3("R1B-6", "META has the same shape (metaSent follows the acknowledgement)", Red = "ITelemetrySinkAck")]
        internal static void R1B6(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 4; k++) r.Tick(100);
            s.Contract("meta-flag-set-without-ack", !r.Flag("metaSent") && r.Sink.Count(r.Sink.Tried, "META:") == 4, "while refused: metaSent false, tried on every Tick", "tried " + r.Sink.Count(r.Sink.Tried, "META:"));
            r.Sink.Accept = true;
            r.Tick(100);
            s.Contract("meta-acceptance-not-booked", r.Flag("metaSent") && r.Sink.Count(r.Sink.Accepted, "META:") == 1, "the first acceptance marks it sent", "");
            int tried = r.Sink.Count(r.Sink.Tried, "META:");
            for (int k = 0; k < 8; k++) r.Tick(100);
            s.Contract("meta-duplicate", r.Sink.Count(r.Sink.Tried, "META:") == tried, "and no resend within the interval", "");
        }

        [S3("N-68", "only the STALIST and META are retried: the operating row is sent once per Tick, whatever the acknowledgement says", Red = "ITelemetrySinkAck")]
        internal static void N68(S3Ctx s)
        {
            SessRig r = SessRig.Make(false, 3);
            for (int k = 0; k < 7; k++) r.Tick(100);
            int rows = r.Sink.Count(r.Sink.Plain, "SCENARIO_ID:");
            s.Contract("row-resent", rows == 7, "seven Ticks, seven rows", "" + rows);
            s.Contract("row-through-trysend", r.Sink.Count(r.Sink.Tried, "SCENARIO_ID:") == 0, "the rows do not go through TrySend", "");
        }

        [S3("R1B-8", "a sink that does not acknowledge keeps the old behaviour (every offered text counts as sent)", Kind = "GUARD")]
        internal static void R1B8(S3Ctx s)
        {
            FakeApi api = new FakeApi();
            for (int i = 0; i < 3; i++) { FakeStation st = new FakeStation(); st.Name = "S" + i; st.Location = 500.0 + 1000.0 * i; api.Stations.Add(st); }
            api.SpeedMps = 0.0;
            CollectSink sink = new CollectSink();
            long mono = 100000;
            Func<long> now = delegate { return mono; };
            Func<long> seed = delegate { return 5000000000L; };
            object session = Pr.New(Pr.T("LegacyTelemetrySession"), api, sink, now, seed, new CollectDiag());
            for (int k = 0; k < 5; k++)
            {
                mono += 100;
                api.TimeMs += 100;
                Pr.Call(session, "OnTick", TimeSpan.FromMilliseconds(100.0));
            }
            int sta = 0;
            foreach (string t in sink.Sent) if (t.StartsWith("STALIST:", StringComparison.Ordinal)) sta++;
            s.Contract("old-sink-resent", sta == 1, "a plain sink gets the STALIST once within 500 ms (it counts as sent at once)", "" + sta);
            s.Contract("old-sink-flag", (bool)Pr.Get(session, "staListSent"), "and the flag is set", "");
        }

        [S3("R1B-7", "LegacyDataPlaneSink.TrySend: false when closed / no router / unresolved / held off, true in the normal mode and when the managed endpoint resolves, false on an exception", Red = "TrySend")]
        internal static void R1B7(S3Ctx s)
        {
            object none = Pr.New(Pr.T("LegacyDataPlaneSink"), null, null, null);
            s.Contract("no-router-true", !(bool)Pr.Call(none, "TrySend", "STALIST:A=0=0=0=0=0=0=0=0"), "no router: false", "");
            s.Contract("null-text-true", !(bool)Pr.Call(none, "TrySend", new object[] { null }), "a null text: false", "");

            DpRig held = new DpRig();
            held.Source.Set(40060, 1, 1, DpRig.Inst, DpRig.CapsText);
            held.Tick();
            bool h = (bool)Pr.Call(held.Sink, "TrySend", "SCENARIO_ID:1,SPEED:0");
            s.Contract("held-true", !h && held.Transport.Count == 0, "inside the hold-off nothing was consumed: false", "result " + h + " sent " + held.Transport.Count);

            DpRig unresolved = new DpRig();
            unresolved.Probe.Ready = true;
            unresolved.Source.Clear("telemetry-directory-missing");
            unresolved.Tick();
            bool u = (bool)Pr.Call(unresolved.Sink, "TrySend", "SCENARIO_ID:1,SPEED:0");
            s.Contract("unresolved-true", !u && unresolved.Transport.Count == 0, "managed mode without a resolvable endpoint: false", "result " + u + " sent " + unresolved.Transport.Count);

            DpRig managed = new DpRig();
            managed.Probe.Enabled = true;
            managed.Source.Set(40051, 1, 1, DpRig.Inst, DpRig.CapsText);
            managed.Tick();
            int cnt = managed.Transport.Count;
            bool m = (bool)Pr.Call(managed.Sink, "TrySend", "SCENARIO_ID:1,SPEED:0");
            s.Contract("managed-false", m && managed.Transport.Count == cnt + 1, "managed mode with a resolved endpoint: true and one datagram", "result " + m + " sent " + (managed.Transport.Count - cnt));

            DpRig normal = new DpRig();
            normal.AddStations();
            normal.Run(180, 16);
            int ncnt = normal.Transport.Count;
            bool n = (bool)Pr.Call(normal.Sink, "TrySend", "SCENARIO_ID:1,SPEED:0");
            s.Contract("normal-false", n && normal.Transport.Count == ncnt + 1, "normal mode: true and one datagram", "result " + n + " sent " + (normal.Transport.Count - ncnt));

            normal.Transport.Throw = true;
            bool e = true;
            try { e = (bool)Pr.Call(normal.Sink, "TrySend", "SCENARIO_ID:2,SPEED:0"); }
            catch (Exception) { e = true; }
            s.Contract("exception-true", !e, "a transport exception: false, and it does not escape", "result " + e);
            normal.Transport.Throw = false;

            Pr.Call(normal.Sink, "Close");
            bool c = (bool)Pr.Call(normal.Sink, "TrySend", "SCENARIO_ID:3,SPEED:0");
            s.Contract("closed-true", !c, "closed: false", "result " + c);
        }

        // =====================================================================================================================================
        // the judgement itself, called directly (the clauses that the plane tests reach only through a full session)
        // =====================================================================================================================================
        private static object NewView(int scenario, bool ready, string listId, int count, double[] locations)
        {
            object v = Pr.New(Pr.T("LegacyJumpView"));
            Pr.Set(v, "ScenarioId", scenario);
            Pr.Set(v, "ListReady", ready);
            Pr.Set(v, "ListId", listId);
            Pr.Set(v, "ListCount", count);
            Pr.Set(v, "Locations", locations);
            return v;
        }

        private static object Judge(string text, uint type, object view)
        {
            return Pr.CallStatic(Pr.T("LegacyJumpJudge"), "Judge", text, type, view);
        }

        private static string Verdict(object d)
        {
            return ((bool)Pr.Get(d, "Accepted")) ? "accepted" : (string)Pr.Get(d, "Reason");
        }

        [S3("N-70", "the judgement, clause by clause: scope, list, count, consistency, location; a formal v1 command passes untouched", Red = "LegacyJumpJudge|LegacyJumpView")]
        internal static void N70(S3Ctx s)
        {
            double[] loc = new double[] { 10.5, 200.25, 3000.125 };
            string list = "A1B2C3D4";
            string text = S3.V2("STA", 1, 200.25, 1000, 7, list, 3);
            object ok = Judge(text, 0x100U, NewView(7, true, list, 3, loc));
            s.Contract("judge-rejects-good", Verdict(ok) == "accepted" && Convert.ToInt32(Pr.Get(ok, "AdoptedIndex")) == 1 && (double)Pr.Get(ok, "AdoptedLocation") == 200.25 && Convert.ToInt32(Pr.Get(ok, "Version")) == 2, "a command that agrees with the view is accepted, with the ADOPTED index and location", Verdict(ok));
            s.Contract("judge-null-view", Verdict(Judge(text, 0x100U, null)) == "scenario-mismatch", "no view: scenario-mismatch", Verdict(Judge(text, 0x100U, null)));
            s.Contract("judge-scenario", Verdict(Judge(text, 0x100U, NewView(8, true, list, 3, loc))) == "scenario-mismatch", "another scenario: scenario-mismatch");
            s.Contract("judge-not-ready", Verdict(Judge(text, 0x100U, NewView(7, false, list, 3, loc))) == "list-not-ready", "a list that is not ready: list-not-ready");
            s.Contract("judge-list", Verdict(Judge(text, 0x100U, NewView(7, true, "A1B2C3D5", 3, loc))) == "list-mismatch", "another list id: list-mismatch");
            s.Contract("judge-count", Verdict(Judge(text, 0x100U, NewView(7, true, list, 4, new double[] { 10.5, 200.25, 3000.125, 4000.0 }))) == "count-mismatch", "another count: count-mismatch");
            s.Contract("judge-no-locations", Verdict(Judge(text, 0x100U, NewView(7, true, list, 3, null))) == "list-inconsistent", "no locations: list-inconsistent");
            s.Contract("judge-short-locations", Verdict(Judge(text, 0x100U, NewView(7, true, list, 3, new double[] { 10.5, 200.25 }))) == "list-inconsistent", "fewer locations than the count: list-inconsistent");
            s.Contract("judge-location", Verdict(Judge(text, 0x100U, NewView(7, true, list, 3, new double[] { 10.5, S3.NextUp(200.25), 3000.125 }))) == "location-mismatch", "a location one ulp away: location-mismatch");
            s.Contract("judge-v1", Verdict(Judge("JUMP_STA_TIME:1:1000", 0x100U, null)) == "accepted" && Convert.ToInt32(Pr.Get(Judge("JUMP_STA_TIME:1:1000", 0x100U, null), "Version")) == 1, "a formal v1 command passes (it names no scope)", Verdict(Judge("JUMP_STA_TIME:1:1000", 0x100U, null)));
            object bad = Judge("JUMP_STA_TIME:x:1000", 0x100U, null);
            s.Contract("judge-malformed", Verdict(bad) == "malformed", "text that is no command: malformed", Verdict(bad));
            object kind = Judge(S3.V2("LOC", 1, 200.25, 1000, 7, list, 3), 0x100U, NewView(7, true, list, 3, loc));
            s.Contract("judge-kind", Verdict(kind) == "malformed", "a location command under the station message type: malformed", Verdict(kind));
            object diag = Pr.Get(Judge(S3.V2("STA", 1, 200.25, 1000, 7, list, 3).Replace(":3:200.25", ":5:200.25"), 0x100U, NewView(7, true, list, 3, loc)), "Diagnostic");
            s.Contract("judge-diag", (string)Pr.Get(diag, "RequestedIndexText") == "1" && (string)Pr.Get(diag, "RequestedCountText") == "5" && (string)Pr.Get(diag, "CurrentCountText") == "3", "the diagnostic carries the named index, the named count and the current count as text", "" + Pr.Get(diag, "RequestedIndexText") + "/" + Pr.Get(diag, "RequestedCountText") + "/" + Pr.Get(diag, "CurrentCountText"));
        }

        [S3("N-71", "a requested target that never reached a selection is not left for a later discontinuity, and no completion announces it", Red = S3.NoV2)]
        internal static void N71(S3Ctx s)
        {
            double[] st = new double[] { 0.5, 1000.5, 2000.0, 2000.0, 3000.0 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            x.Api.Fail.Add("TryDoorsClosed");                  // the station part of the next Tick is skipped (the doors can not be read)
            byte[] rid = Cmd.Rid();
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 3, st[3], S3.NextTime()), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the v2 command is queued", rv == null ? "null" : rv.Short);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Contract(S3.NoV2, r != null && r.State == Ls.Abandoned && r.Reason == "reinit-not-applied", "the target was not set as requested: the command ends Abandoned(reinit-not-applied)", r == null ? "null" : r.Short);
            s.Contract(S3.NoV2, x.Sender.Calls == 0, "and no completion was announced", "" + x.Sender.Calls);
            x.Api.Fail.Remove("TryDoorsClosed");
            // a later discontinuity that carries no index must choose by position: the request is not waiting for it
            x.Host.TimeMs += 5000;
            x.Api.TimeMs = x.Host.TimeMs;
            x.Tick(16);
            s.Contract(S3.NoV2, S3.Tgt(x) == 2, "the next discontinuity chooses by position (index 2 at 2000.0), not the stale request (index 3)", "" + S3.Tgt(x));
        }

        [S3("N-72", "a v2 jump is refused BEFORE the vehicle moves when the host does not agree with the list on the location of the station", Red = S3.NoV2)]
        internal static void N72(S3Ctx s)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = s.C.Own(S3.Rig(s, st));
            S3.Prime(s, x);
            double[] hostStations = new double[] { 100.5, 1000.5, 2000.25, 3000.625 };      // the host places station 3 half a metre elsewhere
            x.Host.Stations = hostStations;
            byte[] rid = Cmd.Rid();
            RecView rv = S3.SendV2(x, "STA", S3.V2Now(x, "STA", 3, st[3], S3.NextTime()), rid);
            s.Contract(S3.NoV2, rv != null && rv.State == CState.Queued, "the command agrees with the list and is queued", rv == null ? "null" : rv.Short);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            s.Contract(S3.NoV2, r != null && r.State == Ls.Failed && r.Reason == "station-location-mismatch", "the executor refuses it before the host call (Failed: station-location-mismatch)", r == null ? "null" : r.Short);
            s.Contract(S3.NoV2, !S3.Has(x, "MoveToStation(3)") && x.Sender.Calls == 0, "the vehicle was not moved and nothing was announced", S3.Calls(x));
        }

    }
}
