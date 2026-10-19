using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.ExceptionServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using TSScoringPlugin.DataPlane;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA / STAGE S1 - test kit (A4b). TEST CODE ONLY: it is never part of the product DLL and is never linked into a product project.
//
// What it is: the product-facing half of the 2A-alpha tests. The tests (A4a, LegacyJumpPlaneTestFixture.cs) talk to the not-yet-written product ONLY through this kit:
//   * the product types are bound by REFLECTION (class Pr) - the kit and the tests compile with or without the product types, so a missing product shows up as a
//     classified, expected RED (ProductAbsentException) and never as a compile error;
//   * the five test seams of the product (clock, owner source, datagram port + factory, mapping writer + factory, waiter) are wrapped by recording / fault-injecting
//     doubles that decorate the PRODUCTION implementations (the product adapters themselves are exercised, not replaced);
//   * Windows resources of the tests (named mappings, loopback UDP) are created and released here, on synthetic BVE PIDs only; the fixed ports 54321 / 54322 are
//     never bound and never written to (every sender refuses them).
// The kit uses the shared DataPlane types (DataPlaneProtocol, TelemetryEndpoint, IEndpointSource, TelemetryDirectoryReader) at compile time: they are linked into the
// existing Legacy DLL since Slice 1 and are not 2A-alpha product code.
// Written in C# 5 syntax (Windows PowerShell 5.1 Add-Type). The product assembly lets this assembly in through InternalsVisibleTo("TsScoringLegacyTelemetryTests").
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    /// <summary>A pinned product element does not exist (yet): the test is an EXPECTED RED, classified by Code.</summary>
    internal sealed class ProductAbsentException : Exception
    {
        public readonly string Code;

        public ProductAbsentException(string code)
            : base("product-absent:" + code)
        {
            Code = code;
        }
    }

    /// <summary>The fixture itself is wrong (a bad assertion setup, a resource that should not exist): never an expected RED.</summary>
    internal sealed class FixtureFaultException : Exception
    {
        public FixtureFaultException(string text)
            : base("fixture-fault:" + text)
        {
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // Product binding (reflection). Every product type of 2A-alpha is internal in namespace TSScoringPlugin.Telemetry.
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal static class Pr
    {
        internal const string Ns = "TSScoringPlugin.Telemetry.";
        private static Assembly asm;
        private static readonly Dictionary<string, Type> cache = new Dictionary<string, Type>();
        private const BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

        internal static void Load(Assembly a)
        {
            asm = a;
            lock (cache) { cache.Clear(); }
        }

        internal static Assembly Asm
        {
            get
            {
                if (asm == null) throw new FixtureFaultException("product assembly not loaded");
                return asm;
            }
        }

        internal static bool Has(string shortName)
        {
            try { return Find(shortName) != null; } catch (ProductAbsentException) { return false; }
        }

        private static Type Find(string shortName)
        {
            lock (cache)
            {
                Type t;
                if (cache.TryGetValue(shortName, out t)) return t;
                t = Asm.GetType(Ns + shortName, false);
                cache[shortName] = t;
                return t;
            }
        }

        /// <summary>The product type, or an EXPECTED-RED exception naming it.</summary>
        internal static Type T(string shortName)
        {
            Type t = Find(shortName);
            if (t == null) throw new ProductAbsentException("type:" + shortName);
            return t;
        }

        /// <summary>A shared (linked) DataPlane type of the product assembly, e.g. JumpDirectoryPublisher / JumpCapabilities. Absent => expected RED.</summary>
        internal static Type TS(string shortName)
        {
            string key = "DataPlane." + shortName;
            lock (cache)
            {
                Type t;
                if (!cache.TryGetValue(key, out t))
                {
                    t = Asm.GetType("TSScoringPlugin.DataPlane." + shortName, false);
                    cache[key] = t;
                }
                if (t == null) throw new ProductAbsentException("shared-type:" + shortName);
                return t;
            }
        }

        internal static object New(Type t, params object[] args)
        {
            Type[] types = new Type[args.Length];
            for (int i = 0; i < args.Length; i++) types[i] = args[i] == null ? null : args[i].GetType();
            foreach (ConstructorInfo c in t.GetConstructors(All))
            {
                if (c.IsStatic) continue;
                ParameterInfo[] ps = c.GetParameters();
                if (ps.Length != args.Length) continue;
                bool ok = true;
                for (int i = 0; i < ps.Length; i++) if (args[i] != null && !ps[i].ParameterType.IsInstanceOfType(args[i])) { ok = false; break; }
                if (!ok) continue;
                try { return c.Invoke(args); }
                catch (TargetInvocationException ex) { ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); }
            }
            throw new ProductAbsentException("ctor:" + t.Name + "/" + args.Length);
        }

        private static FieldInfo FieldOf(Type t, string name)
        {
            for (Type x = t; x != null; x = x.BaseType)
            {
                FieldInfo f = x.GetField(name, All);
                if (f != null) return f;
            }
            return null;
        }

        private static PropertyInfo PropOf(Type t, string name)
        {
            for (Type x = t; x != null; x = x.BaseType)
            {
                PropertyInfo p = x.GetProperty(name, All);
                if (p != null) return p;
            }
            return null;
        }

        private static MethodInfo MethodOf(Type t, string name, int argc, bool wantStatic)
        {
            for (Type x = t; x != null; x = x.BaseType)
            {
                foreach (MethodInfo m in x.GetMethods(All))
                {
                    if (m.Name == name && m.GetParameters().Length == argc && m.IsStatic == wantStatic) return m;
                }
            }
            return null;
        }

        internal static bool HasMember(Type t, string name)
        {
            return FieldOf(t, name) != null || PropOf(t, name) != null;
        }

        internal static object Get(object o, string name)
        {
            Type t = o.GetType();
            FieldInfo f = FieldOf(t, name);
            if (f != null) return f.GetValue(o);
            PropertyInfo p = PropOf(t, name);
            if (p != null)
            {
                try { return p.GetValue(o, null); }
                catch (TargetInvocationException ex) { ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); }
            }
            throw new ProductAbsentException("member:" + t.Name + "." + name);
        }

        internal static object GetStatic(Type t, string name)
        {
            FieldInfo f = FieldOf(t, name);
            if (f != null) return f.GetValue(null);
            PropertyInfo p = PropOf(t, name);
            if (p != null) return p.GetValue(null, null);
            throw new ProductAbsentException("member:" + t.Name + "." + name);
        }

        internal static void Set(object o, string name, object value)
        {
            Type t = o.GetType();
            FieldInfo f = FieldOf(t, name);
            if (f != null) { f.SetValue(o, value); return; }
            PropertyInfo p = PropOf(t, name);
            if (p != null) { p.SetValue(o, value, null); return; }
            throw new ProductAbsentException("member:" + t.Name + "." + name);
        }

        internal static object Call(object o, string name, params object[] args)
        {
            MethodInfo m = MethodOf(o.GetType(), name, args.Length, false);
            if (m == null) throw new ProductAbsentException("method:" + o.GetType().Name + "." + name);
            try { return m.Invoke(o, args); }
            catch (TargetInvocationException ex) { ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); return null; }
        }

        internal static object CallStatic(Type t, string name, params object[] args)
        {
            MethodInfo m = MethodOf(t, name, args.Length, true);
            if (m == null) throw new ProductAbsentException("method:" + t.Name + "." + name);
            try { return m.Invoke(null, args); }
            catch (TargetInvocationException ex) { ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); return null; }
        }

        internal static string[] EnumNames(Type e)
        {
            return Enum.GetNames(e);
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // Interface proxies (Reflection.Emit): implement a product interface with a handler. The dynamic assembly carries the name that the product lets in through
    // InternalsVisibleTo, so it may implement the internal seam interfaces.
    // ---------------------------------------------------------------------------------------------------------------------------------------
    // public on purpose: the generated proxy classes live in a dynamic assembly and must be able to call the handler.
    public delegate object ProxyHandler(MethodInfo method, object[] args);

    internal static class Proxy
    {
        private static readonly object gate = new object();
        private static ModuleBuilder module;
        private static int counter;
        // the generated type AND the method array it was generated from: the IL addresses a method by its index in THAT array, and a later GetMethods() call is not
        // guaranteed to return the same order (it did not, after a large reflection scan), so every instance must get this very array
        private static readonly Dictionary<Type, KeyValuePair<Type, MethodInfo[]>> made = new Dictionary<Type, KeyValuePair<Type, MethodInfo[]>>();

        internal static object Make(Type iface, ProxyHandler handler)
        {
            if (iface == null) throw new FixtureFaultException("proxy of a null interface");
            Type t;
            MethodInfo[] methods;
            lock (gate)
            {
                if (module == null)
                {
                    AssemblyName an = new AssemblyName("TsScoringLegacyTelemetryTests");
                    AssemblyBuilder ab = AppDomain.CurrentDomain.DefineDynamicAssembly(an, AssemblyBuilderAccess.Run);
                    module = ab.DefineDynamicModule("proxies");
                }
                KeyValuePair<Type, MethodInfo[]> hit;
                if (made.TryGetValue(iface, out hit)) { t = hit.Key; methods = hit.Value; }
                else
                {
                    TypeBuilder tb = module.DefineType("Proxy" + (++counter).ToString() + "_" + iface.Name, TypeAttributes.Public | TypeAttributes.Sealed, typeof(object), new Type[] { iface });
                    FieldBuilder fh = tb.DefineField("h", typeof(ProxyHandler), FieldAttributes.Public);
                    FieldBuilder fm = tb.DefineField("ms", typeof(MethodInfo[]), FieldAttributes.Public);
                    methods = iface.GetMethods();
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

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // Event log (the writer-side trace that the product does not keep: the seam doubles record it)
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class EventLog
    {
        private readonly List<string> items = new List<string>();
        private long n;

        internal void Add(string name)
        {
            long k = Interlocked.Increment(ref n);
            lock (items) { items.Add(k.ToString() + "|" + Thread.CurrentThread.ManagedThreadId.ToString() + "|" + name); }
        }

        internal string[] Snapshot()
        {
            lock (items) { return items.ToArray(); }
        }

        internal int Count { get { lock (items) { return items.Count; } } }

        internal static string NameOf(string line)
        {
            string[] p = line.Split('|');
            return p.Length >= 3 ? p[2] : line;
        }

        internal bool Has(string name)
        {
            foreach (string l in Snapshot()) if (NameOf(l) == name) return true;
            return false;
        }

        internal int IndexOf(string name, int from)
        {
            string[] s = Snapshot();
            for (int i = from; i < s.Length; i++) if (NameOf(s[i]) == name) return i;
            return -1;
        }

        internal int CountOf(string name)
        {
            int c = 0;
            foreach (string l in Snapshot()) if (NameOf(l) == name) c++;
            return c;
        }

        internal string Names()
        {
            StringBuilder sb = new StringBuilder();
            foreach (string l in Snapshot()) { if (sb.Length > 0) sb.Append(" ; "); sb.Append(NameOf(l)); }
            return sb.ToString();
        }
    }

    /// <summary>Validates the writer-side event order of every endpoint recorded by the seam doubles. Returns null when valid, else the first violation.</summary>
    internal static class TraceChecker
    {
        // ep: 0 none, 1 PUBLISHED, 2 READY, 3 WITHDRAWING, 4 socket closed after WITHDRAWING, 5 CLOSED, 6 socket closed after PUBLISHED (rollback)
        internal static string Verify(string[] trace, bool expectReleased)
        {
            return Verify(trace, expectReleased, null);
        }

        /// <param name="strictAfter">when not null: the marker event after which NO publish:PUBLISHED / publish:READY may occur (the test controls the timing).</param>
        internal static string Verify(string[] trace, bool expectReleased, string strictAfter)
        {
            int ep = 0;
            bool afterMarker = false;
            for (int i = 0; i < trace.Length; i++)
            {
                string n = EventLog.NameOf(trace[i]);
                if (strictAfter != null && n == strictAfter) afterMarker = true;
                if (afterMarker && (n == "publish:PUBLISHED" || n == "publish:READY")) return "publication after the marker " + strictAfter + " at #" + i + " (" + n + ")";
                switch (n)
                {
                    case "publish:PUBLISHED": if (ep != 0) return Bad(n, ep, i); ep = 1; break;
                    case "publish:READY": if (ep != 1) return Bad(n, ep, i); ep = 2; break;
                    case "publish:WITHDRAWING": if (ep != 2) return Bad(n, ep, i); ep = 3; break;
                    case "port-close":
                        if (ep == 3) ep = 4;
                        else if (ep == 1) ep = 6;
                        else if (ep == 0) { }
                        else return Bad(n, ep, i);
                        break;
                    case "publish:CLOSED": if (ep != 4 && ep != 6) return Bad(n, ep, i); ep = 5; break;
                    case "mapping-dispose":
                        if (ep == 5 || ep == 0) ep = 0;
                        else return Bad(n, ep, i);
                        break;
                }
            }
            if (expectReleased && ep != 0) return "an endpoint was left unreleased (phase " + ep + ")";
            return null;
        }

        private static string Bad(string n, int ep, int i)
        {
            return "event " + n + " at #" + i + " is not allowed in endpoint phase " + ep;
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    internal sealed class CheckRec
    {
        public string What;
        public bool Ok;
        public string Actual;
    }

    /// <summary>One test run: its checks, its log and the disposables it owns (released in reverse order when the test ends, pass or fail).</summary>
    internal sealed class Ctx
    {
        public readonly string Id;
        public readonly StringBuilder Log = new StringBuilder();
        public readonly List<CheckRec> Checks = new List<CheckRec>();
        private readonly List<IDisposable> owned = new List<IDisposable>();
        private int pidsTaken;

        public Ctx(string id)
        {
            Id = id;
        }

        public void Check(bool ok, string what, string actual)
        {
            CheckRec r = new CheckRec();
            r.What = what;
            r.Ok = ok;
            r.Actual = actual;
            lock (Checks) { Checks.Add(r); }
            Info((ok ? "PASS " : "FAIL ") + what + (String.IsNullOrEmpty(actual) ? "" : "  [" + actual + "]"));
        }

        public void Check(bool ok, string what)
        {
            Check(ok, what, null);
        }

        public void Info(string line)
        {
            lock (Log) { Log.AppendLine(DateTime.Now.ToString("HH:mm:ss.fff") + " " + line); }
        }

        /// <summary>The case could not reach a verdict (an owner of a resource cannot be told, ...). Never a PASS: the outcome of the case is INCONCLUSIVE unless a check failed.</summary>
        public readonly List<string> Inconclusives = new List<string>();

        public void Inconclusive(string why)
        {
            lock (Inconclusives) { Inconclusives.Add(why); }
            Info("INCONCLUSIVE " + why);
        }

        public int InconclusiveCount
        {
            get { lock (Inconclusives) { return Inconclusives.Count; } }
        }

        public T Own<T>(T item) where T : IDisposable
        {
            lock (owned) { owned.Add(item); }
            return item;
        }

        /// <summary>A synthetic BVE PID that has never been used in this run (odd and huge: a real Windows PID is a multiple of 4).</summary>
        public int NewPid()
        {
            pidsTaken++;
            return Env.NextPid();
        }

        public int FailedChecks
        {
            get { lock (Checks) { int n = 0; foreach (CheckRec r in Checks) if (!r.Ok) n++; return n; } }
        }

        public void ReleaseAll()
        {
            IDisposable[] items;
            lock (owned) { items = owned.ToArray(); owned.Clear(); }
            for (int i = items.Length - 1; i >= 0; i--)
            {
                try { items[i].Dispose(); } catch (Exception ex) { Info("release error " + ex.GetType().Name); }
            }
        }
    }

    /// <summary>Run wide facts: the run id, synthetic PIDs, every named object / port ever used (for the residue checks).</summary>
    internal static class Env
    {
        public static string RunId = "run";
        public static string RepoRoot = "";
        private static int pidCounter;
        private static int pidBase = 2100000001;
        public static readonly List<string> UsedNames = new List<string>();
        public static readonly List<int> UsedPorts = new List<int>();
        // the ownership ledger of the loopback ports that the planes of THIS run bound for real (WIN-99): who bound which port, in which run, and whether the close was seen
        public static readonly List<OwnedPort> OwnedPorts = new List<OwnedPort>();
        // ports that the kit itself re-bound on purpose after a plane had released them (a same-process reuse that is not a residue)
        public static readonly List<int> ReusePorts = new List<int>();
        public static int BaselineHandles;
        public static int BaselineThreads;

        public static void Init(string runId)
        {
            RunId = runId;
            int h = 17;
            for (int i = 0; i < runId.Length; i++) h = unchecked(h * 31 + runId[i]);
            pidBase = 2100000001 + 2 * (Math.Abs(h % 1000000));
            pidCounter = 0;
            lock (UsedNames) { UsedNames.Clear(); }
            lock (UsedPorts) { UsedPorts.Clear(); }
            lock (OwnedPorts) { OwnedPorts.Clear(); }
            lock (ReusePorts) { ReusePorts.Clear(); }
            lock (IssuedPids) { IssuedPids.Clear(); }
            Res.Reset();
        }

        public static OwnedPort NoteOwnedPort(int planePid, int port, bool isVirtual)
        {
            OwnedPort o = new OwnedPort();
            o.RunId = RunId;
            o.PlanePid = planePid;
            o.Port = port;
            o.OsPid = System.Diagnostics.Process.GetCurrentProcess().Id;
            o.Virtual = isVirtual;
            lock (OwnedPorts) { o.Seq = OwnedPorts.Count + 1; OwnedPorts.Add(o); }
            return o;
        }

        public static OwnedPort[] OwnedSnapshot()
        {
            lock (OwnedPorts) { return OwnedPorts.ToArray(); }
        }

        public static void NoteReuse(int port)
        {
            lock (ReusePorts) { ReusePorts.Add(port); }
        }

        public static void ForgetReuse(int port)
        {
            lock (ReusePorts) { ReusePorts.Remove(port); }
        }

        public static int[] ReuseSnapshot()
        {
            lock (ReusePorts) { return ReusePorts.ToArray(); }
        }

        public static int NextPid()
        {
            int pid = pidBase + 2 * Interlocked.Increment(ref pidCounter);
            lock (IssuedPids) { IssuedPids.Add(pid); }
            return pid;
        }

        // the synthetic PIDs that THIS run issued (the product Directory names of this run carry them)
        public static readonly List<int> IssuedPids = new List<int>();

        public static int[] IssuedPidsSnapshot()
        {
            lock (IssuedPids) { return IssuedPids.ToArray(); }
        }

        public static void NoteName(string name)
        {
            lock (UsedNames) { if (!UsedNames.Contains(name)) UsedNames.Add(name); }
        }

        public static void NotePort(int port)
        {
            lock (UsedPorts) { if (!UsedPorts.Contains(port)) UsedPorts.Add(port); }
        }

        /// <summary>The product Directory name for a synthetic PID (written out here on purpose: it is the contract, not the product function).</summary>
        public static string ProductName(int pid)
        {
            return "Local\\TSScoringPlugin.v1." + pid.ToString() + ".LegacyJump";
        }
    }

    /// <summary>Counters of the Windows resources that the seam doubles saw being created / released (independent of the product's own books).</summary>
    internal static class Res
    {
        public static int PortsOpened, PortsClosed, MappingsOpened, MappingsReleased, WorkersSeen;
        public static void Reset() { PortsOpened = 0; PortsClosed = 0; MappingsOpened = 0; MappingsReleased = 0; WorkersSeen = 0; }
        public static int OpenPorts { get { return Thread.VolatileRead(ref PortsOpened) - Thread.VolatileRead(ref PortsClosed); } }
        public static int OpenMappings { get { return Thread.VolatileRead(ref MappingsOpened) - Thread.VolatileRead(ref MappingsReleased); } }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // fakes
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class FakeSource : IEndpointSource
    {
        public volatile bool Ok = true;
        public volatile TelemetryEndpoint Owner;
        public string FailReason = "app-directory-missing";
        public int Calls;

        public static string RandomInstance()
        {
            byte[] b = new byte[16];
            using (RandomNumberGenerator g = RandomNumberGenerator.Create()) { g.GetBytes(b); }
            return Hex(b);
        }

        public static byte[] RandomBytes(int n)
        {
            byte[] b = new byte[n];
            using (RandomNumberGenerator g = RandomNumberGenerator.Create())
            {
                do { g.GetBytes(b); } while (IsZero(b));
            }
            return b;
        }

        public static bool IsZero(byte[] b)
        {
            for (int i = 0; i < b.Length; i++) if (b[i] != 0) return false;
            return true;
        }

        public static string Hex(byte[] b)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < b.Length; i++) sb.Append(b[i].ToString("x2"));
            return sb.ToString();
        }

        public static TelemetryEndpoint NewOwner(int bvePid)
        {
            return new TelemetryEndpoint((UInt32)bvePid, RandomInstance(), (UInt32)(bvePid + 2), (UInt32)(49200 + new Random().Next(0, 4000)), 0x1234U, RandomBytes(16), 1U, 7U);
        }

        public static FakeSource Make(int bvePid)
        {
            FakeSource s = new FakeSource();
            s.Owner = NewOwner(bvePid);
            return s;
        }

        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            Interlocked.Increment(ref Calls);
            TelemetryEndpoint o = Owner;
            if (!Ok || o == null)
            {
                endpoint = null;
                reason = FailReason;
                return false;
            }
            endpoint = o;
            reason = "ok";
            return true;
        }
    }

    internal sealed class FakeClock
    {
        private long now = 1000;
        public long Now() { return Interlocked.Read(ref now); }
        public void Advance(long ms) { Interlocked.Add(ref now, ms); }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // threads / waiting (the tests themselves contain no thread or sleep word)
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class Bg : IDisposable
    {
        private readonly System.Threading.Thread th;
        public Exception Error;

        private Bg(Action body)
        {
            th = new System.Threading.Thread(delegate ()
            {
                try { body(); } catch (Exception ex) { Error = ex; }
            });
            th.IsBackground = true;
        }

        public static Bg Start(Action body)
        {
            Bg b = new Bg(body);
            b.th.Start();
            return b;
        }

        /// <summary>Creates the thread without starting it (so that several can be released at the same instant).</summary>
        public static Bg Make(Action body)
        {
            return new Bg(body);
        }

        public void Begin() { th.Start(); }
        public bool Join(int ms) { return th.Join(ms); }
        public bool Alive { get { return th.IsAlive; } }
        public void Dispose() { try { th.Join(3000); } catch { } }
    }

    internal static class Wait
    {
        private static readonly ManualResetEvent never = new ManualResetEvent(false);

        public static void Ms(int ms)
        {
            never.WaitOne(ms);
        }

        public static bool For(Func<bool> f, int ms)
        {
            Stopwatch sw = Stopwatch.StartNew();
            while (sw.ElapsedMilliseconds < ms)
            {
                if (f()) return true;
                Ms(1);
            }
            return f();
        }

        /// <summary>Busy wait in microseconds (a few hundred) for racing rounds.</summary>
        public static void SpinUs(int us)
        {
            Stopwatch sw = Stopwatch.StartNew();
            while (sw.Elapsed.TotalMilliseconds * 1000.0 < us) { }
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // Directory reading and raw Windows objects of the tests
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class DirRead
    {
        public bool Found;
        public bool Valid;
        public string Reason;
        public byte[] Bytes;
        public UInt32 State, Generation, Port, Caps, PublisherPid, BvePid, Change;
        public string TokenHex;

        public bool Ready { get { return Valid && (State & (DataPlaneProtocol.Published | DataPlaneProtocol.Ready)) == (DataPlaneProtocol.Published | DataPlaneProtocol.Ready) && (State & (DataPlaneProtocol.Withdrawing | DataPlaneProtocol.Closed)) == 0; } }
        public string Key { get { return State + "/" + Generation + "/" + Port + "/" + TokenHex; } }
    }

    internal static class DirView
    {
        public static string StateName(UInt32 s)
        {
            if (s == 0) return "ZERO";
            if ((s & DataPlaneProtocol.Closed) != 0) return "CLOSED";
            if ((s & DataPlaneProtocol.Withdrawing) != 0) return "WITHDRAWING";
            if ((s & DataPlaneProtocol.Ready) != 0) return "READY";
            return "PUBLISHED";
        }

        /// <summary>One poll with NO retained handle: the mapping and the view are disposed before this returns.</summary>
        public static DirRead Poll(string name)
        {
            DirRead r = new DirRead();
            MemoryMappedFile m = null;
            MemoryMappedViewAccessor v = null;
            try
            {
                m = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);
                v = m.CreateViewAccessor(0, DataPlaneProtocol.DirectorySize, MemoryMappedFileAccess.Read);
                r.Found = true;
                for (int attempt = 0; attempt < 3; attempt++)
                {
                    UInt32 before = v.ReadUInt32(16);
                    if ((before & 1U) != 0U) continue;
                    byte[] b = new byte[DataPlaneProtocol.DirectorySize];
                    v.ReadArray(0, b, 0, b.Length);
                    UInt32 after = v.ReadUInt32(16);
                    if (before != after) continue;
                    r.Bytes = b;
                    Fill(r, b);
                    return r;
                }
                r.Reason = "torn";
                return r;
            }
            catch (FileNotFoundException)
            {
                r.Reason = "missing";
                return r;
            }
            catch (Exception ex)
            {
                r.Reason = "error:" + ex.GetType().Name;
                return r;
            }
            finally
            {
                if (v != null) { try { v.Dispose(); } catch { } }
                if (m != null) { try { m.Dispose(); } catch { } }
            }
        }

        public static void Fill(DirRead r, byte[] b)
        {
            try
            {
                JumpDirectory d = DataPlaneProtocol.DecodeJumpDirectory(b);
                r.Valid = true;
                r.State = d.State; r.Generation = d.Generation; r.Port = d.Port; r.Caps = d.Capabilities; r.PublisherPid = d.PublisherPid; r.BvePid = d.BvePid; r.Change = d.ChangeCount;
                r.TokenHex = FakeSource.Hex(d.Token);
            }
            catch (ArgumentException ex)
            {
                r.Valid = false;
                r.Reason = "decode:" + ex.GetType().Name;
                if (b.Length >= 24) r.State = BitConverter.ToUInt32(b, 20);
            }
        }
    }

    /// <summary>Polls a Directory continuously (a fresh open per poll) and records every change.</summary>
    internal sealed class StateWatcher : IDisposable
    {
        public sealed class Obs
        {
            public long Ticks;
            public string Kind;
            public UInt32 State, Generation, Port, Caps;
            public string TokenHex;
        }

        private readonly string name;
        private readonly System.Threading.Thread thread;
        private volatile bool stop;
        public readonly List<Obs> Observations = new List<Obs>();
        public long ReadyPolls;
        public long Polls;
        public UInt32 CapsUnion;
        private string lastKey = "";

        public StateWatcher(string name)
        {
            this.name = name;
            thread = new System.Threading.Thread(Run);
            thread.IsBackground = true;
            thread.Start();
        }

        private void Run()
        {
            while (!stop)
            {
                DirRead r = DirView.Poll(name);
                Polls++;
                string kind;
                if (!r.Found) kind = "missing";
                else if (!r.Valid) kind = "invalid:" + r.Reason + ":" + r.State;
                else kind = DirView.StateName(r.State);
                if (r.Valid) CapsUnion |= r.Caps;
                if (r.Ready) ReadyPolls++;
                string key = kind + (r.Valid ? "/" + r.Generation + "/" + r.Port + "/" + r.TokenHex : "");
                if (key != lastKey)
                {
                    lastKey = key;
                    Obs o = new Obs();
                    o.Ticks = Stopwatch.GetTimestamp();
                    o.Kind = kind;
                    if (r.Valid) { o.State = r.State; o.Generation = r.Generation; o.Port = r.Port; o.Caps = r.Caps; o.TokenHex = r.TokenHex; }
                    lock (Observations) { Observations.Add(o); }
                }
                Wait.Ms(0);
            }
        }

        public List<Obs> Snapshot()
        {
            lock (Observations) { return new List<Obs>(Observations); }
        }

        public int CountKind(string kind)
        {
            int n = 0;
            foreach (Obs o in Snapshot()) if (o.Kind == kind) n++;
            return n;
        }

        public string KindSequence()
        {
            StringBuilder sb = new StringBuilder();
            foreach (Obs o in Snapshot()) { if (sb.Length > 0) sb.Append(" > "); sb.Append(o.Kind); }
            return sb.ToString();
        }

        public void Dispose()
        {
            stop = true;
            try { thread.Join(2000); } catch { }
        }
    }

    /// <summary>A raw mapping writer for hostile / hand built blocks (tests only).</summary>
    internal sealed class RawMapping : IDisposable
    {
        private MemoryMappedFile map;
        private MemoryMappedViewAccessor view;

        public RawMapping(string name, byte[] content)
        {
            Env.NoteName(name);
            map = MemoryMappedFile.CreateNew(name, 128, MemoryMappedFileAccess.ReadWrite);
            view = map.CreateViewAccessor(0, 128, MemoryMappedFileAccess.ReadWrite);
            view.WriteArray(0, content, 0, content.Length);
            view.Flush();
        }

        public void Dispose()
        {
            if (view != null) { try { view.Dispose(); } catch { } view = null; }
            if (map != null) { try { map.Dispose(); } catch { } map = null; }
        }
    }

    /// <summary>Models an OLD Reader that keeps its handle (the Python client before the RC-2 fix).</summary>
    internal sealed class HandleHolder : IDisposable
    {
        private MemoryMappedFile map;
        private MemoryMappedViewAccessor view;

        public HandleHolder(string name)
        {
            map = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);
            view = map.CreateViewAccessor(0, 128, MemoryMappedFileAccess.Read);
        }

        public byte[] ReadBlock()
        {
            byte[] b = new byte[128];
            view.ReadArray(0, b, 0, 128);
            return b;
        }

        public void Dispose()
        {
            if (view != null) { try { view.Dispose(); } catch { } view = null; }
            if (map != null) { try { map.Dispose(); } catch { } map = null; }
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // loopback UDP helpers of the tests. Fixed ports 54321 / 54322 are NEVER bound and NEVER written to.
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal static class Net
    {
        // the two product ports that no test may touch: the Telemetry port of the shared contract and the one above it (the Current jump port). Never written as literals.
        public const int FixedA = TSScoringPlugin.Telemetry.TelemetryContract.Port;
        public const int FixedB = TSScoringPlugin.Telemetry.TelemetryContract.Port + 1;

        public static bool IsFixedPort(int port)
        {
            return port == FixedA || port == FixedB;
        }

        public static int FixedSendsRefused;

        public static void SendTo(UInt32 port, byte[] data)
        {
            if (IsFixedPort((int)port)) { Interlocked.Increment(ref FixedSendsRefused); return; }
            using (UdpClient u = new UdpClient())
            {
                u.Send(data, data.Length, new IPEndPoint(IPAddress.Loopback, (int)port));
            }
        }

        /// <summary>True when a bind on the loopback port succeeds (= nobody listens there).</summary>
        public static bool PortIsFree(int port)
        {
            if (IsFixedPort(port)) throw new FixtureFaultException("PortIsFree on a fixed product port");
            try
            {
                using (UdpClient u = new UdpClient(new IPEndPoint(IPAddress.Loopback, port))) { }
                return true;
            }
            catch
            {
                return false;
            }
        }

        public static List<string> ListenersOn(int port)
        {
            List<string> r = new List<string>();
            foreach (IPEndPoint ep in IPGlobalProperties.GetIPGlobalProperties().GetActiveUdpListeners())
            {
                if (ep.Port == port) r.Add(ep.Address.ToString());
            }
            return r;
        }

        /// <summary>A loopback listener owned by the kit itself (used by the self tests to prove the residue detectors). Never a fixed port: it asks the OS for port 0.</summary>
        public sealed class Listener : IDisposable
        {
            private UdpClient client;
            public Listener(out int port)
            {
                client = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
                port = ((IPEndPoint)client.Client.LocalEndPoint).Port;
                if (IsFixedPort(port)) { client.Close(); throw new FixtureFaultException("the OS handed out a fixed product port; rerun"); }
            }
            public void Dispose() { if (client != null) { try { client.Close(); } catch { } client = null; } }
        }

        public static Listener Listen(out int port)
        {
            return new Listener(out port);
        }

        /// <summary>True when a CreateNew with this name succeeds (= no mapping object with that name is alive).</summary>
        public static bool NameIsFree(string name)
        {
            try
            {
                using (MemoryMappedFile m = MemoryMappedFile.CreateNew(name, 128, MemoryMappedFileAccess.ReadWrite)) { }
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // datagram builders
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal static class Cmd
    {
        public static byte[] Rid()
        {
            return FakeSource.RandomBytes(16);
        }

        public const string StaText = "JUMP_STA_TIME:1:36000";

        public static byte[] Envelope(UInt32 type, UInt32 bve, UInt32 sender, UInt32 gen, string inst, byte[] token, byte[] rid, string text)
        {
            return DataPlaneProtocol.EncodeEnvelope(type, bve, sender, gen, inst, token, rid, Encoding.UTF8.GetBytes(text));
        }

        public static byte[] Valid(SnapView s, int bvePid, TelemetryEndpoint owner, byte[] rid, string text, UInt32 type)
        {
            return Envelope(type, (UInt32)bvePid, owner.AppProcessId, s.Generation, owner.AppInstance, s.Token, rid, text);
        }

        public static byte[] Valid(SnapView s, int bvePid, TelemetryEndpoint owner, byte[] rid)
        {
            return Valid(s, bvePid, owner, rid, StaText, 0x100U);
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    // ---------------------------------------------------------------------------------------------------------------------------------------
    // typed views of the product's records (copies read by reflection)
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal static class PState
    {
        public const int NotStarted = 0, Publishing = 1, Ready = 2, Withdrawing = 3, RetryWaiting = 4, Disposing = 5, Closed = 6;

        public static string Name(int s)
        {
            switch (s)
            {
                case 0: return "NotStarted";
                case 1: return "Publishing";
                case 2: return "Ready";
                case 3: return "Withdrawing";
                case 4: return "RetryWaiting";
                case 5: return "Disposing";
                case 6: return "Closed";
            }
            return "state" + s;
        }
    }

    internal static class CState
    {
        public const int Rejected = 0, Queued = 1, Discarded = 2;

        public static string Name(int s)
        {
            switch (s)
            {
                case 0: return "Rejected";
                case 1: return "Queued";
                case 2: return "Discarded";
            }
            return "state" + s;
        }
    }

    internal sealed class RecView
    {
        public long Sequence;
        public int State;
        public string Reason;
        public byte[] RequestId;
        public UInt32 MessageType;
        public string Text;
        public int BvePid;
        public string AppInstance;
        public UInt32 AppPid;
        public UInt32 TelemetryGeneration;
        public byte[] TelemetryToken;
        public UInt32 TelemetryPort;
        public UInt32 ReceiverGeneration;
        public long ReceivedAtMs;
        public int ScenarioEpoch;

        public string RidHex { get { return RequestId == null ? null : FakeSource.Hex(RequestId); } }
        public string Short { get { return CState.Name(State) + "/" + Reason; } }

        public static RecView From(object r)
        {
            if (r == null) return null;
            RecView v = new RecView();
            v.Sequence = Convert.ToInt64(Pr.Get(r, "Sequence"));
            v.State = Convert.ToInt32(Pr.Get(r, "State"));
            v.Reason = (string)Pr.Get(r, "Reason");
            v.RequestId = (byte[])Pr.Get(r, "RequestId");
            v.MessageType = Convert.ToUInt32(Pr.Get(r, "MessageType"));
            v.Text = (string)Pr.Get(r, "Text");
            v.BvePid = Convert.ToInt32(Pr.Get(r, "BvePid"));
            v.AppInstance = (string)Pr.Get(r, "AppInstance");
            v.AppPid = Convert.ToUInt32(Pr.Get(r, "AppPid"));
            v.TelemetryGeneration = Convert.ToUInt32(Pr.Get(r, "TelemetryGeneration"));
            v.TelemetryToken = (byte[])Pr.Get(r, "TelemetryToken");
            v.TelemetryPort = Convert.ToUInt32(Pr.Get(r, "TelemetryPort"));
            v.ReceiverGeneration = Convert.ToUInt32(Pr.Get(r, "ReceiverGeneration"));
            v.ReceivedAtMs = Convert.ToInt64(Pr.Get(r, "ReceivedAtMs"));
            v.ScenarioEpoch = Convert.ToInt32(Pr.Get(r, "ScenarioEpoch"));
            return v;
        }
    }

    internal sealed class SnapView
    {
        public int State;
        public UInt32 Generation;
        public byte[] Token;
        public UInt32 Port;
        public int Attempts;
        public int Published;
        public long Received;
        public long RestartCount;
        public RecView Queued;

        public string TokenHex { get { return Token == null ? "" : FakeSource.Hex(Token); } }

        public static SnapView From(object s)
        {
            SnapView v = new SnapView();
            v.State = Convert.ToInt32(Pr.Get(s, "State"));
            v.Generation = Convert.ToUInt32(Pr.Get(s, "Generation"));
            v.Token = (byte[])Pr.Get(s, "Token");
            v.Port = Convert.ToUInt32(Pr.Get(s, "Port"));
            v.Attempts = Convert.ToInt32(Pr.Get(s, "Attempts"));
            v.Published = Convert.ToInt32(Pr.Get(s, "Published"));
            v.Received = Convert.ToInt64(Pr.Get(s, "Received"));
            v.RestartCount = Convert.ToInt64(Pr.Get(s, "RestartCount"));
            v.Queued = RecView.From(Pr.Get(s, "Queued"));
            return v;
        }
    }

    /// <summary>The product's control plane, driven through reflection.</summary>
    internal sealed class PlaneHandle : IDisposable
    {
        public readonly object Raw;

        public PlaneHandle(object raw)
        {
            Raw = raw;
        }

        public int State { get { return Convert.ToInt32(Pr.Get(Raw, "State")); } }
        public bool IsWorkerAlive { get { return (bool)Pr.Get(Raw, "IsWorkerAlive"); } }
        public int Iterations { get { return Convert.ToInt32(Pr.Get(Raw, "Iterations")); } }
        public int MaxStepsInside { get { return Convert.ToInt32(Pr.Get(Raw, "MaxStepsInside")); } }
        public int MaxPublishersInside { get { return Convert.ToInt32(Pr.Get(Raw, "MaxPublishersInside")); } }
        public long MaxIterationGapMs { get { return Convert.ToInt64(Pr.Get(Raw, "MaxIterationGapMs")); } }
        public int AfterDisposeAccess { get { return Convert.ToInt32(Pr.Get(Raw, "AfterDisposeAccess")); } }
        public string StateName { get { return PState.Name(State); } }

        public void Start() { Pr.Call(Raw, "Start"); }
        public void OnHostTick(bool managed, bool boundaryObservable) { Pr.Call(Raw, "OnHostTick", managed, boundaryObservable); }
        public bool EnsureWorkerAlive() { return (bool)Pr.Call(Raw, "EnsureWorkerAlive"); }
        public void NoteScenarioBoundary() { Pr.Call(Raw, "NoteScenarioBoundary"); }
        public void Dispose() { Pr.Call(Raw, "Dispose"); }
        public SnapView Snapshot() { return SnapView.From(Pr.Call(Raw, "Snapshot")); }
        public long Counter(string key) { return Convert.ToInt64(Pr.Call(Raw, "CounterValue", key)); }

        public RecView[] Outcomes()
        {
            object arr = Pr.Call(Raw, "Outcomes");
            System.Collections.IEnumerable e = (System.Collections.IEnumerable)arr;
            List<RecView> l = new List<RecView>();
            foreach (object o in e) l.Add(RecView.From(o));
            return l.ToArray();
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // the seam doubles: recording, fault / stall injecting decorators of the PRODUCTION seam implementations
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class SeamHooks
    {
        public Action OnBind, OnCreate, OnAvailable, OnClock, AfterRead;
        public Action<UInt32> BeforePublish, AfterPublish;
        public Action<bool> AfterWait;
        public Func<int> VirtualPort;        // a value > 0: the bind returns a double that only CLAIMS this port number (nothing is bound)
        public Action BeforeWorkerRegister;  // called on a thread that drives the plane for the first time, BEFORE it is recorded as a worker (a gate for the restart controls)
    }

    internal sealed class PublishRec
    {
        public UInt32 State, Port, Generation, Caps;
        public string TokenHex;
        public int Thread;
    }

    internal sealed class SeamSet
    {
        public const string SocketIface = "ILegacyJumpSocket";
        public const string SocketFactoryIface = "ILegacyJumpSocketFactory";
        public const string WriterIface = "ILegacyJumpWriter";
        public const string WriterFactoryIface = "ILegacyJumpWriterFactory";
        public const string WaitIface = "ILegacyJumpWait";

        public readonly EventLog Log = new EventLog();
        public readonly SeamHooks Hooks = new SeamHooks();
        public readonly List<PublishRec> Publishes = new List<PublishRec>();
        public readonly List<int> PortNumbers = new List<int>();
        public readonly List<string> PortOrder = new List<string>();
        // the thread OBJECTS that ever drove the plane (a managed thread id can be handed out again after a thread has ended, so ids cannot tell two workers apart)
        public readonly HashSet<System.Threading.Thread> WaiterThreads = new HashSet<System.Threading.Thread>();
        // the workers of this plane in the order in which they first drove it: the thread OBJECT is the identity (the instance sequence is its position), the managed id is information only
        public readonly List<WorkerRec> Workers = new List<WorkerRec>();
        public int Reentries;                  // a thread started to drive the plane while another recorded worker was still alive
        public int PlanePid;                   // the synthetic BVE PID of the plane that owns these seams (the ownership ledger)
        public readonly List<OwnedPort> MyPorts = new List<OwnedPort>();
        // the CreateNew calls of the plane, with their results (success and failure kept apart; a bind that was given up before any mapping is not among them)
        public readonly List<CreateRec> Creates = new List<CreateRec>();
        public int CreateOk, CreateFailed;
        public int ClockCalls, WaitCalls, AvailableCalls, ReadCalls, BindCalls, CreateCalls;
        public int OpenPorts, OpenMappings;
        public volatile bool DisposedMark;
        public int AfterDisposeTouches;
        public readonly List<string> AfterDisposeNames = new List<string>();
        public Func<long> BaseClock;

        private void Touch(string what)
        {
            if (DisposedMark)
            {
                Interlocked.Increment(ref AfterDisposeTouches);
                lock (AfterDisposeNames) { AfterDisposeNames.Add(what); }
            }
        }

        public UInt32 CapsUnion
        {
            get { UInt32 u = 0; lock (Publishes) { foreach (PublishRec p in Publishes) u |= p.Caps; } return u; }
        }

        public PublishRec[] PublishSnapshot()
        {
            lock (Publishes) { return Publishes.ToArray(); }
        }

        public static string StateEvent(UInt32 s)
        {
            if (s == 1U) return "publish:PUBLISHED";
            if (s == 3U) return "publish:READY";
            if (s == 7U) return "publish:WITHDRAWING";
            if (s == 8U) return "publish:CLOSED";
            return "publish:state" + s;
        }

        public Func<long> Clock()
        {
            return delegate
            {
                Interlocked.Increment(ref ClockCalls);
                Touch("clock");
                Action h = Hooks.OnClock;
                if (h != null) h();
                return BaseClock();
            };
        }

        public object Wait(object inner)
        {
            return Proxy.Make(Pr.T(WaitIface), delegate (MethodInfo m, object[] a)
            {
                Interlocked.Increment(ref WaitCalls);
                Touch("wait");
                RegisterWorker();
                bool r = (bool)Invoke(inner, m, a);
                if (r) Log.Add("wait:stopped");
                Action<bool> h = Hooks.AfterWait;
                if (h != null) h(r);
                return r;
            });
        }

        private void RegisterWorker()
        {
            System.Threading.Thread cur = System.Threading.Thread.CurrentThread;
            lock (Workers) { foreach (WorkerRec w in Workers) if (object.ReferenceEquals(w.T, cur)) return; }
            Action pre = Hooks.BeforeWorkerRegister;
            if (pre != null) pre();
            lock (Workers)
            {
                foreach (WorkerRec w in Workers) if (object.ReferenceEquals(w.T, cur)) return;
                foreach (WorkerRec w in Workers) if (w.T.IsAlive) Reentries++;
                WorkerRec n = new WorkerRec();
                n.Instance = Workers.Count + 1;
                n.T = cur;
                n.ManagedId = cur.ManagedThreadId;
                Workers.Add(n);
            }
            lock (WaiterThreads) { WaiterThreads.Add(cur); }
        }

        public WorkerRec[] WorkerSnapshot()
        {
            lock (Workers) { return Workers.ToArray(); }
        }

        public CreateRec[] CreateSnapshot()
        {
            lock (Creates) { return Creates.ToArray(); }
        }

        public object SocketFactory(object innerFactory)
        {
            return Proxy.Make(Pr.T(SocketFactoryIface), delegate (MethodInfo m, object[] a)
            {
                Interlocked.Increment(ref BindCalls);
                Touch("bind");
                Action h = Hooks.OnBind;
                if (h != null) h();
                Func<int> vp = Hooks.VirtualPort;
                int virt = vp == null ? 0 : vp();
                object sock;
                int id = Interlocked.Increment(ref Res.PortsOpened);
                Interlocked.Increment(ref OpenPorts);
                if (virt > 0)
                {
                    OwnedPort ov = Env.NoteOwnedPort(PlanePid, virt, true);
                    lock (MyPorts) { MyPorts.Add(ov); }
                    sock = VirtualSocket(id, virt, ov);
                    lock (PortNumbers) { PortNumbers.Add(virt); PortOrder.Add("virtual:" + virt); }
                    Log.Add("bind:virtual:" + virt);
                }
                else
                {
                    object innerSock = Invoke(innerFactory, m, a);
                    int port = Convert.ToInt32(Pr.Get(innerSock, "Port"));
                    Env.NotePort(port);
                    OwnedPort orl = Env.NoteOwnedPort(PlanePid, port, false);
                    lock (MyPorts) { MyPorts.Add(orl); }
                    sock = RealSocket(id, innerSock, port, orl);
                    lock (PortNumbers) { PortNumbers.Add(port); PortOrder.Add("real:" + port); }
                    Log.Add("bind:real:" + port);
                }
                return sock;
            });
        }

        private object VirtualSocket(int id, int port, OwnedPort led)
        {
            bool closed = false;
            return Proxy.Make(Pr.T(SocketIface), delegate (MethodInfo m, object[] a)
            {
                Touch("vsock." + m.Name);
                switch (m.Name)
                {
                    case "get_Port": return port;
                    case "get_Available": Interlocked.Increment(ref AvailableCalls); { Action h = Hooks.OnAvailable; if (h != null) h(); } return 0;
                    case "ReadDatagram": throw new InvalidOperationException("virtual port has no data");
                    case "Close":
                        if (!closed) { closed = true; led.CloseSeen = true; Interlocked.Increment(ref Res.PortsClosed); Interlocked.Decrement(ref OpenPorts); Log.Add("port-close"); }
                        return null;
                }
                throw new FixtureFaultException("virtual socket method " + m.Name);
            });
        }

        private object RealSocket(int id, object inner, int port, OwnedPort led)
        {
            int closedFlag = 0;
            return Proxy.Make(Pr.T(SocketIface), delegate (MethodInfo m, object[] a)
            {
                Touch("sock." + m.Name);
                switch (m.Name)
                {
                    case "get_Port": return port;
                    case "get_Available":
                        Interlocked.Increment(ref AvailableCalls);
                        { Action h = Hooks.OnAvailable; if (h != null) h(); }
                        return Invoke(inner, m, a);
                    case "ReadDatagram":
                        {
                            object data = Invoke(inner, m, a);
                            Interlocked.Increment(ref ReadCalls);
                            Log.Add("read");
                            Action h = Hooks.AfterRead;
                            if (h != null) h();
                            return data;
                        }
                    case "Close":
                        if (Interlocked.Exchange(ref closedFlag, 1) == 0)
                        {
                            led.CloseSeen = true;
                            Interlocked.Increment(ref Res.PortsClosed);
                            Interlocked.Decrement(ref OpenPorts);
                            Log.Add("port-close");
                        }
                        return Invoke(inner, m, a);
                }
                throw new FixtureFaultException("socket method " + m.Name);
            });
        }

        public object WriterFactory(object innerFactory)
        {
            return Proxy.Make(Pr.T(WriterFactoryIface), delegate (MethodInfo m, object[] a)
            {
                Interlocked.Increment(ref CreateCalls);
                Touch("create");
                Action h = Hooks.OnCreate;
                if (h != null) h();
                Env.NoteName((string)a[1]);
                CreateRec crec = new CreateRec();
                crec.Name = (string)a[1];
                crec.Call = CreateCalls;
                object inner;
                try { inner = Invoke(innerFactory, m, a); }
                catch (Exception cex)
                {
                    crec.Ok = false;
                    crec.Error = cex.GetType().Name;
                    lock (Creates) { Creates.Add(crec); }
                    Interlocked.Increment(ref CreateFailed);
                    throw;
                }
                crec.Ok = true;
                lock (Creates) { Creates.Add(crec); }
                Interlocked.Increment(ref CreateOk);
                Interlocked.Increment(ref Res.MappingsOpened);
                Interlocked.Increment(ref OpenMappings);
                Log.Add("createnew");
                return WriterDouble(inner);
            });
        }

        private object WriterDouble(object inner)
        {
            int releasedFlag = 0;
            return Proxy.Make(Pr.T(WriterIface), delegate (MethodInfo m, object[] a)
            {
                Touch("writer." + m.Name);
                if (m.Name == "Publish")
                {
                    UInt32 state = (UInt32)a[0];
                    Action<UInt32> before = Hooks.BeforePublish;
                    if (before != null) before(state);
                    Invoke(inner, m, a);
                    PublishRec r = new PublishRec();
                    r.State = state; r.Port = (UInt32)a[1]; r.Generation = (UInt32)a[2]; r.TokenHex = FakeSource.Hex((byte[])a[3]); r.Caps = (UInt32)a[4];
                    LinkPublished(r.Port, r.Generation, (byte[])a[3]);
                    r.Thread = Thread.CurrentThread.ManagedThreadId;
                    lock (Publishes) { Publishes.Add(r); }
                    Log.Add(StateEvent(state));
                    Action<UInt32> after = Hooks.AfterPublish;
                    if (after != null) after(state);
                    return null;
                }
                if (m.Name == "Release")
                {
                    if (Interlocked.Exchange(ref releasedFlag, 1) == 0)
                    {
                        Interlocked.Increment(ref Res.MappingsReleased);
                        Interlocked.Decrement(ref OpenMappings);
                        Log.Add("mapping-dispose");
                    }
                    return Invoke(inner, m, a);
                }
                throw new FixtureFaultException("writer method " + m.Name);
            });
        }

        // the safe identification of a published endpoint in the ownership ledger: generation and the first 4 bytes of a hash of the token (never the token itself)
        private void LinkPublished(UInt32 port, UInt32 generation, byte[] token)
        {
            if (port == 0U) return;
            string id = null;
            lock (MyPorts)
            {
                for (int i = MyPorts.Count - 1; i >= 0; i--)
                {
                    OwnedPort op = MyPorts[i];
                    if ((UInt32)op.Port != port) continue;
                    if (op.TokenId == null)
                    {
                        if (id == null) { using (SHA256 sh = SHA256.Create()) { id = FakeSource.Hex(sh.ComputeHash(token)).Substring(0, 8); } }
                        op.Generation = generation;
                        op.TokenId = id;
                    }
                    break;
                }
            }
        }

        private static object Invoke(object target, MethodInfo ifaceMethod, object[] args)
        {
            try { return ifaceMethod.Invoke(target, args); }
            catch (TargetInvocationException ex) { ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); return null; }
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // plane construction
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class PlaneOpts
    {
        public int Pid;                           // 0 = a new synthetic PID
        public IEndpointSource Source;            // null = a fresh FakeSource for the PID
        public bool UseProductSource;             // true = keep the product's own owner source (the shared Directory Reader)
        public FakeClock Clock;                   // null = the real monotonic clock
        public bool ProductionTimings;            // true = leave the product's default timings alone
        public int PollMs = 2, JoinMs = 1500, GateTryMs = 1500, RetryMinMs = 10, RetryMaxMs = 40, MaxDatagrams = 32;
        public long TtlMs = 0;
        public bool Decorate = true;              // wrap the production seams with the recording doubles
        public Action<SeamHooks> Hooks;           // convenience: set the hooks before the plane exists
        public bool LogThrows;                    // the log callback records the line and then throws (PT-08)
    }

    internal sealed class PlaneRig : IDisposable
    {
        public PlaneHandle P;
        public SeamSet Seams;
        public FakeSource Src;
        public FakeClock Clk;
        public int Pid;
        public string Name;
        public readonly List<string> LogLines = new List<string>();
        public object RawEnv;

        public string[] Lines() { lock (LogLines) { return LogLines.ToArray(); } }

        public void Dispose()
        {
            try { P.Dispose(); } catch { }
        }

        public SnapView AwaitReady(int ms)
        {
            return Kit.AwaitReady(P, ms);
        }
    }

    internal static class Kit
    {
        public static PlaneRig NewRig(Ctx c, PlaneOpts o)
        {
            PlaneRig rig = new PlaneRig();
            rig.Pid = o.Pid > 0 ? o.Pid : c.NewPid();
            rig.Name = Env.ProductName(rig.Pid);
            Env.NoteName(rig.Name);
            Type envType = Pr.T("LegacyJumpEnvironment");
            Type planeType = Pr.T("LegacyJumpControlPlane");
            Action<string> log = delegate (string line)
            {
                lock (rig.LogLines) { rig.LogLines.Add(line); }
                if (o.LogThrows) throw new InvalidOperationException("injected-log");
            };
            object env = Pr.CallStatic(envType, "Production", rig.Pid, log);
            rig.RawEnv = env;
            if (!o.UseProductSource)
            {
                IEndpointSource src = o.Source;
                if (src == null) { rig.Src = FakeSource.Make(rig.Pid); src = rig.Src; }
                else rig.Src = src as FakeSource;
                Pr.Set(env, "Source", src);
            }
            SeamSet seams = new SeamSet();
            seams.PlanePid = rig.Pid;
            rig.Seams = seams;
            if (o.Hooks != null) o.Hooks(seams.Hooks);
            if (o.Clock != null) { rig.Clk = o.Clock; seams.BaseClock = o.Clock.Now; }
            else
            {
                Stopwatch sw = Stopwatch.StartNew();
                seams.BaseClock = delegate { return sw.ElapsedMilliseconds + 1000; };
            }
            if (!o.ProductionTimings)
            {
                object tm = Pr.Get(env, "Timings");
                Pr.Set(tm, "PollMs", o.PollMs);
                Pr.Set(tm, "JoinMs", o.JoinMs);
                Pr.Set(tm, "GateTryMs", o.GateTryMs);
                Pr.Set(tm, "RetryMinMs", o.RetryMinMs);
                Pr.Set(tm, "RetryMaxMs", o.RetryMaxMs);
                Pr.Set(tm, "MaxDatagramsPerStep", o.MaxDatagrams);
                Pr.Set(tm, "TtlMs", o.TtlMs);
            }
            if (o.Decorate)
            {
                Pr.Set(env, "ClockMs", seams.Clock());
                Pr.Set(env, "Sockets", seams.SocketFactory(Pr.Get(env, "Sockets")));
                Pr.Set(env, "Writers", seams.WriterFactory(Pr.Get(env, "Writers")));
                Pr.Set(env, "Waiter", seams.Wait(Pr.Get(env, "Waiter")));
            }
            else if (o.Clock != null)
            {
                Pr.Set(env, "ClockMs", seams.BaseClock);
            }
            rig.P = new PlaneHandle(Pr.New(planeType, env));
            c.Own(rig);
            return rig;
        }

        /// <summary>A rig that is started right away (Start()).</summary>
        public static PlaneRig Started(Ctx c, PlaneOpts o)
        {
            PlaneRig r = NewRig(c, o);
            r.P.Start();
            return r;
        }

        public static SnapView AwaitReady(PlaneHandle p, int ms)
        {
            if (!Wait.For(delegate { return p.State == PState.Ready; }, ms)) return null;
            return p.Snapshot();
        }

        /// <summary>Waits until the worker has run at least n more iterations (a fact, not a duration).</summary>
        public static bool Settle(PlaneHandle p, int n, int ms)
        {
            int start = p.Iterations;
            return Wait.For(delegate { return p.Iterations >= start + n; }, ms);
        }

        public static RecView Find(PlaneHandle p, byte[] rid)
        {
            RecView[] all = p.Outcomes();
            string h = FakeSource.Hex(rid);
            for (int i = all.Length - 1; i >= 0; i--) if (all[i].RidHex == h) return all[i];
            return null;
        }

        /// <summary>Sends one command to the plane's port and waits until the plane recorded one more outcome. Returns that record, or null.</summary>
        public static RecView SendAndAwait(PlaneRig r, SnapView s, byte[] datagram, int ms)
        {
            int before = r.P.Outcomes().Length;
            Net.SendTo(s.Port, datagram);
            RecView got = null;
            Wait.For(delegate
            {
                RecView[] o = r.P.Outcomes();
                if (o.Length > before) { got = o[o.Length - 1]; return true; }
                return false;
            }, ms);
            return got;
        }

        public static RecView SendValid(PlaneRig r, SnapView s, byte[] rid, string text)
        {
            return SendAndAwait(r, s, Cmd.Valid(s, r.Pid, r.Src.Owner, rid, text, 0x100U), 4000);
        }

        // the pinned order of the shutdown steps in the final summary line (plan N4); kept here because the tests contain no port-type word
        public const string ShutdownOrder = "stop,join,withdrawing,socket-close,closed,release";

        // names of the timer type, kept here because the tests contain no timer word
        public const string TimerType = "System.Timers.Timer";
        public const string TimerNs = "System.Timers.";

        /// <summary>Ends the calling thread with a thread abort (a simulated worker death, ITR-15).</summary>
        public static void AbortCurrentThread()
        {
            Thread.CurrentThread.Abort();
        }

        /// <summary>The negative control of ITR-02: a periodic timer re-enters a slow callback.</summary>
        public static void TimerReentrancy(out int max, out int calls)
        {
            int cur = 0, mx = 0, cl = 0;
            object mlock = new object();
            System.Timers.Timer t = new System.Timers.Timer(5);
            t.Elapsed += delegate
            {
                int n = Interlocked.Increment(ref cur);
                Interlocked.Increment(ref cl);
                lock (mlock) { if (n > mx) mx = n; }
                Wait.Ms(60);
                Interlocked.Decrement(ref cur);
            };
            t.Start();
            Wait.Ms(500);
            t.Stop();
            Wait.For(delegate { return Thread.VolatileRead(ref cur) == 0; }, 3000);
            t.Dispose();
            max = mx;
            calls = cl;
        }

        /// <summary>The shared Directory publisher WITHOUT the plane's gate (the negative control of ITR-03).</summary>
        public sealed class RawPublisher : IDisposable
        {
            private readonly object pub;

            public RawPublisher(int pid, string name)
            {
                Env.NoteName(name);
                pub = Pr.New(Pr.TS("JumpDirectoryPublisher"), (UInt32)pid, name);
            }

            public void Publish(UInt32 state, UInt32 port, UInt32 gen, byte[] token, UInt32 caps) { Pr.Call(pub, "Publish", state, port, gen, token, caps); }
            public void Dispose() { Pr.Call(pub, "Dispose"); }
        }
    }
}

// ============================================================================================================================================
// Flake-fix addendum (S3, v1): fact based judges for ITR-15 (worker restart) and WIN-99 (resources of the planes of this run), the bounded driver of Ready(), and the records
// of ITR-05 (CreateNew successes and failures). The judges are PURE functions of recorded facts, so that deterministic positive and negative controls (SELF-11..18) can prove
// them without a product; the real cases only collect the facts and call them. Nothing here changes the product, its timings or its back-off.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    internal sealed class WorkerRec
    {
        public int Instance;                       // 1-based order in which this thread first drove the plane (the instance sequence)
        public System.Threading.Thread T;          // the thread OBJECT: the identity of the worker
        public int ManagedId;                      // information only: a managed id can be handed out again after a thread has ended
        public volatile bool Joined;               // the test joined this thread
    }

    internal sealed class CreateRec
    {
        public string Name;
        public int Call;                           // the number of the CreateNew call of this plane (1-based)
        public bool Ok;
        public string Error;
    }

    internal sealed class OwnedPort
    {
        public string RunId;                       // the run that bound the port
        public int PlanePid;                       // the synthetic BVE PID of the plane
        public int Port;
        public int OsPid;                          // the operating system process that bound it (this test process)
        public bool Virtual;                       // a claim only: nothing was bound
        public volatile bool CloseSeen;            // the plane's Close of this port was seen
        public UInt32 Generation;                  // the generation published for this port (0 = never published)
        public string TokenId;                     // first 4 bytes of a hash of the token (never the token)
        public int Seq;

        public string Short
        {
            get { return "#" + Seq + " run=" + RunId + " plane=" + PlanePid + " port=" + Port + (Virtual ? " virtual" : "") + " gen=" + Generation + " tok=" + (TokenId ?? "-") + " closed=" + CloseSeen; }
        }
    }

    internal enum VKind { Pending, Pass, Fail, Inconclusive }

    internal sealed class Verdict
    {
        public VKind Kind;
        public string Reason;

        public static Verdict Pending(string r) { Verdict v = new Verdict(); v.Kind = VKind.Pending; v.Reason = r; return v; }
        public static Verdict Pass(string r) { Verdict v = new Verdict(); v.Kind = VKind.Pass; v.Reason = r; return v; }
        public static Verdict Fail(string r) { Verdict v = new Verdict(); v.Kind = VKind.Fail; v.Reason = r; return v; }
        public static Verdict Inconclusive(string r) { Verdict v = new Verdict(); v.Kind = VKind.Inconclusive; v.Reason = r; return v; }
        public override string ToString() { return Kind + ": " + Reason; }
    }

    internal sealed class WorkerFact
    {
        public int Instance;                       // instance sequence
        public int Generation;                     // the restart generation written by the plane at the start of this worker (-1 = not logged)
        public int ThreadId;                       // information only
        public bool StartLogged;                   // the plane logged the start of this worker
        public bool Registered;                    // the thread was seen driving the plane through the wait seam (a live worker of the plane)
        public bool Exited;                        // the thread is no longer alive
        public bool Joined;                        // the test joined it

        public static WorkerFact Make(int instance, int generation, int threadId, bool startLogged, bool registered, bool exited, bool joined)
        {
            WorkerFact f = new WorkerFact();
            f.Instance = instance; f.Generation = generation; f.ThreadId = threadId; f.StartLogged = startLogged; f.Registered = registered; f.Exited = exited; f.Joined = joined;
            return f;
        }

        public string Short
        {
            get { return "i" + Instance + "/g" + Generation + "/t" + ThreadId + (StartLogged ? "/start-logged" : "") + (Registered ? "/registered" : "") + (Exited ? "/exited" : "/alive") + (Joined ? "/joined" : ""); }
        }
    }

    /// <summary>The fact based verdict of a worker restart. Pending = the facts are not all there yet (never a PASS, never a FAIL: the caller waits, bounded); the judge never looks at a duration.</summary>
    internal static class WorkerJudge
    {
        public static Verdict Restart(WorkerFact[] f, int reentries, bool stopRequestRecorded)
        {
            if (reentries > 0) return Verdict.Fail("worker re-entry: " + reentries + " thread(s) started to drive the plane while another worker was alive");
            if (!stopRequestRecorded) return Verdict.Fail("no stop request of the old worker is recorded");
            if (f.Length == 0) return Verdict.Pending("no worker is recorded");
            WorkerFact old = f[0];
            if (f.Length > 1 && !old.Exited && AnyRegisteredAfter(f, 0)) return Verdict.Fail("the old worker is still alive while a new worker runs");
            if (!old.Exited) return Verdict.Pending("old worker exit not recorded");
            if (!old.Joined) return Verdict.Pending("old worker Join not confirmed");
            if (f.Length < 2) return Verdict.Pending("new worker start not recorded");
            for (int i = 0; i < f.Length; i++)
            {
                for (int j = i + 1; j < f.Length; j++)
                {
                    if (f[i].Instance == f[j].Instance) return Verdict.Fail("instance sequence repeated: " + f[i].Instance);
                    if (f[i].Generation >= 0 && f[i].Generation == f[j].Generation) return Verdict.Fail("worker generation reused: " + f[i].Generation);
                }
            }
            WorkerFact nw = f[1];
            if (!nw.StartLogged) return Verdict.Pending("new worker start not logged by the plane");
            if (!nw.Registered) return Verdict.Pending("new worker not yet recorded as a live worker of the plane");
            if (nw.Generation < old.Generation) return Verdict.Fail("worker generation went back: " + old.Generation + " -> " + nw.Generation);
            int live = 0;
            for (int i = 0; i < f.Length; i++) if (f[i].Registered && !f[i].Exited) live++;
            if (live == 0) return Verdict.Fail("no live worker after the restart");
            if (live > 1) return Verdict.Fail("live workers: " + live);
            if (f.Length > 2) return Verdict.Fail("more than one new worker started: " + (f.Length - 1));
            return Verdict.Pass("restart settled: old " + old.Short + " -> new " + nw.Short);
        }
        /// <summary>After the stop: the same number of workers as before, none alive.</summary>
        public static Verdict Stopped(WorkerFact[] f, int expectedInstances)
        {
            if (f.Length != expectedInstances) return Verdict.Fail("workers recorded after the stop: " + f.Length + " (expected " + expectedInstances + ")");
            for (int i = 0; i < f.Length; i++) if (f[i].Registered && !f[i].Exited) return Verdict.Pending("worker " + f[i].Instance + " has not exited");
            return Verdict.Pass("no worker is alive");
        }

        private static bool AnyRegisteredAfter(WorkerFact[] f, int index)
        {
            for (int i = index + 1; i < f.Length; i++) if (f[i].Registered) return true;
            return false;
        }
    }

    internal static class WorkerFacts
    {
        private static readonly Regex StartLine = new Regex("jump-worker-start restarts=(\\d+)");

        /// <summary>The facts of the workers of one plane: the threads seen by the wait seam, the start lines the plane logged, and whether each thread is still alive.</summary>
        public static WorkerFact[] Build(SeamSet seams, string[] logLines)
        {
            List<int> gens = new List<int>();
            foreach (string l in logLines)
            {
                Match m = StartLine.Match(l);
                if (m.Success) gens.Add(int.Parse(m.Groups[1].Value));
            }
            WorkerRec[] w = seams.WorkerSnapshot();
            int n = Math.Max(w.Length, gens.Count);
            WorkerFact[] r = new WorkerFact[n];
            for (int i = 0; i < n; i++)
            {
                WorkerFact f = new WorkerFact();
                f.Instance = i + 1;
                f.Generation = i < gens.Count ? gens[i] : -1;
                f.StartLogged = i < gens.Count;
                if (i < w.Length)
                {
                    f.Registered = true;
                    f.ThreadId = w[i].ManagedId;
                    f.Exited = !w[i].T.IsAlive;
                    f.Joined = w[i].Joined;
                }
                r[i] = f;
            }
            return r;
        }

        /// <summary>Joins the worker of the given instance (1-based) and records the fact.</summary>
        public static bool Join(SeamSet seams, int instance, int ms)
        {
            WorkerRec[] w = seams.WorkerSnapshot();
            if (instance < 1 || instance > w.Length) return false;
            bool j = w[instance - 1].T.Join(ms);
            if (j) w[instance - 1].Joined = true;
            return j;
        }

        public static string Describe(WorkerFact[] f)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < f.Length; i++) { if (i > 0) sb.Append(" ; "); sb.Append(f[i].Short); }
            return sb.ToString();
        }
    }

    internal sealed class AwaitResult
    {
        public Verdict Final;
        public int Evaluations;
        public long ElapsedMs;
        public readonly List<string> Steps = new List<string>();
    }

    internal static class Verdicts
    {
        /// <summary>Evaluates until the verdict is no longer Pending; a verdict that is still Pending at the limit is a FAIL. Every change of the state is recorded.</summary>
        public static AwaitResult Await(Func<Verdict> eval, int limitMs)
        {
            AwaitResult r = new AwaitResult();
            Stopwatch sw = Stopwatch.StartNew();
            string last = null;
            while (true)
            {
                Verdict v = eval();
                r.Evaluations++;
                string key = v.Kind + ": " + v.Reason;
                if (key != last) { r.Steps.Add("t+" + sw.ElapsedMilliseconds + "ms " + key); last = key; }
                if (v.Kind != VKind.Pending) { r.Final = v; break; }
                if (sw.ElapsedMilliseconds >= limitMs) { r.Final = Verdict.Fail("limit of " + limitMs + " ms reached while pending: " + v.Reason); break; }
                Wait.Ms(1);
            }
            r.ElapsedMs = sw.ElapsedMilliseconds;
            return r;
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // Ready(): the bounded driver
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal sealed class ReadyTrace
    {
        public bool Reached;
        public int Steps;
        public long SyntheticMs;
        public string End;
        public readonly List<string> Lines = new List<string>();
    }

    internal static class ReadyDriver
    {
        public const int MaxSteps = 3000;              // explicit bound of the steps
        public const long MaxSyntheticMs = 120000;     // explicit bound of the synthetic time that this driver may add to the injected clock
        public const int StepMs = 50;                  // synthetic time added per step; the back-off values of the product are never touched
        public const int RealLimitMs = 8000;           // explicit bound of the real time

        /// <summary>Moves the injected clock step by step until the plane is READY. Every step is recorded; a terminal state, a dead worker, an exception and every bound end it with a reason.</summary>
        public static ReadyTrace Drive(Func<int> state, Func<bool> alive, Action<long> advance, Func<string> describe, int maxSteps, long maxSyntheticMs, int realLimitMs, Action pause)
        {
            ReadyTrace t = new ReadyTrace();
            Stopwatch sw = Stopwatch.StartNew();
            for (int step = 1; step <= maxSteps; step++)
            {
                t.Steps = step;
                int s;
                bool al;
                try { s = state(); al = alive(); }
                catch (Exception ex)
                {
                    t.End = "exception while observing the plane: " + ex.GetType().Name;
                    t.Lines.Add("step " + step + " " + t.End);
                    return t;
                }
                t.Lines.Add("step " + step + " state=" + PState.Name(s) + " alive=" + al + " synthetic=" + t.SyntheticMs + "ms " + describe());
                if (s == PState.Ready) { t.Reached = true; t.End = "READY"; return t; }
                if (s == PState.Closed || s == PState.Disposing || s == PState.Withdrawing) { t.End = "terminal state " + PState.Name(s) + " before READY"; return t; }
                if (!al) { t.End = "the worker is not alive before READY (state " + PState.Name(s) + ")"; return t; }
                if (t.SyntheticMs >= maxSyntheticMs) { t.End = "synthetic time limit of " + maxSyntheticMs + " ms reached"; return t; }
                if (sw.ElapsedMilliseconds >= realLimitMs) { t.End = "real time limit of " + realLimitMs + " ms reached"; return t; }
                pause();
                advance(StepMs);
                t.SyntheticMs += StepMs;
            }
            t.End = "step limit of " + maxSteps + " reached";
            return t;
        }
    }

    // ---------------------------------------------------------------------------------------------------------------------------------------
    // WIN-99: the sockets of the planes of this run
    // ---------------------------------------------------------------------------------------------------------------------------------------
    internal enum PortClass { Released, SameProcessReuse, ExternalReuse, NotClosed, OwnedByTestProcess, OwnerUnknown, OtherRun }

    internal sealed class PortFacts
    {
        public string RunId;
        public int Port;
        public bool Virtual;
        public bool Fixed;               // one of the two product ports: judged like any other port, but never bound by a test (only the table of the operating system is read)
        public bool CloseSeen;           // every bind of the plane on this port has its close recorded
        public int Probe;                // 0 not tried, 1 the port could be bound again (re-use succeeded), 2 busy
        public int[] Owners;             // owner pids in the table of the operating system (null = the table could not be read)
        public bool RegisteredReuse;     // the kit itself holds this port on purpose (a same-process re-use after the plane closed)
    }

    internal static class PortJudge
    {
        public static PortClass Classify(PortFacts f, string runId, int ownPid, out string note)
        {
            if (f.RunId != runId) { note = "bound in run " + f.RunId + ", not in this run"; return PortClass.OtherRun; }
            if (f.Virtual) { note = "a claim only, no operating system port"; return PortClass.Released; }
            if (!f.CloseSeen) { note = "the close of the plane's port was never seen"; return PortClass.NotClosed; }
            if (f.Probe == 1) { note = "the port could be bound again"; return PortClass.Released; }
            if (f.Owners == null) { note = "the owner of the busy port cannot be told (no table)"; return PortClass.OwnerUnknown; }
            if (f.Owners.Length == 0) { note = "the port is not in the table of the operating system"; return PortClass.Released; }
            bool own = false, unknown = false;
            for (int i = 0; i < f.Owners.Length; i++)
            {
                if (f.Owners[i] == ownPid) own = true;
                else if (f.Owners[i] <= 0) unknown = true;
            }
            if (own)
            {
                if (f.RegisteredReuse) { note = "re-bound by the test process on purpose after the plane closed it"; return PortClass.SameProcessReuse; }
                note = "still owned by the test process (pid " + ownPid + ")";
                return PortClass.OwnedByTestProcess;
            }
            if (unknown) { note = "the owner of the busy port cannot be told (pid 0)"; return PortClass.OwnerUnknown; }
            note = "re-used by another process (pid " + string.Join(",", Array.ConvertAll(f.Owners, delegate (int x) { return x.ToString(); })) + ")";
            return PortClass.ExternalReuse;
        }

        public static Verdict Judge(PortFacts[] all, string runId, int ownPid, List<string> rows, out int external)
        {
            external = 0;
            int bad = 0, unknown = 0, counted = 0;
            List<string> why = new List<string>();
            foreach (PortFacts f in all)
            {
                string note;
                PortClass k = Classify(f, runId, ownPid, out note);
                if (rows != null) rows.Add("port " + f.Port + (f.Fixed ? " (fixed product port)" : "") + ": " + k + " - " + note);
                if (k == PortClass.OtherRun) continue;
                counted++;
                if (k == PortClass.ExternalReuse) external++;
                if (k == PortClass.NotClosed || k == PortClass.OwnedByTestProcess) { bad++; why.Add(f.Port + ":" + k); }
                if (k == PortClass.OwnerUnknown) { unknown++; why.Add(f.Port + ":" + k); }
            }
            if (bad > 0) return Verdict.Fail("ports of this run that remain: " + string.Join(", ", why.ToArray()));
            if (unknown > 0) return Verdict.Inconclusive("the owner cannot be told for: " + string.Join(", ", why.ToArray()));
            return Verdict.Pass(counted + " port(s) of this run: none remains" + (external > 0 ? " (" + external + " re-used by another process)" : ""));
        }
    }

    /// <summary>Names of mappings: only the names of the PIDs that THIS run issued are judged; a name of another run is never confused with a resource of this one.</summary>
    internal static class NameJudge
    {
        private static readonly Regex Pid = new Regex("\\.v1\\.(\\d+)\\.");

        public static Verdict Judge(string[] names, int[] issuedPids, Func<string, bool> isFree, List<string> rows)
        {
            int alive = 0, judged = 0, foreign = 0;
            foreach (string n in names)
            {
                Match m = Pid.Match(n);
                bool ours = true;
                if (m.Success)
                {
                    int pid;
                    ours = int.TryParse(m.Groups[1].Value, out pid) && Array.IndexOf(issuedPids, pid) >= 0;
                }
                if (!ours) { foreign++; if (rows != null) rows.Add("name of another run, not judged: " + n); continue; }
                judged++;
                if (!isFree(n)) { alive++; if (rows != null) rows.Add("name still alive: " + n); }
            }
            if (alive > 0) return Verdict.Fail(alive + " of " + judged + " mapping name(s) of this run are still alive");
            return Verdict.Pass(judged + " mapping name(s) of this run can be created again" + (foreign > 0 ? " (" + foreign + " of another run ignored)" : ""));
        }
    }

    /// <summary>Tools of the operating system (read only): the table of the UDP ports with the owner process. Auxiliary diagnosis only; the primary evidence is the close and the re-use.</summary>
    internal static class UdpOwners
    {
        private static readonly Regex Row = new Regex("^\\s*UDP\\s+(\\S+):(\\d+)\\s+\\S+\\s+(\\d+)\\s*$", RegexOptions.IgnoreCase);

        /// <summary>Parses the output of the table tool; returns null when it does not look like a table at all.</summary>
        public static Dictionary<int, List<int>> Parse(string text)
        {
            if (text == null) return null;
            Dictionary<int, List<int>> d = new Dictionary<int, List<int>>();
            int rows = 0;
            foreach (string line in text.Split('\n'))
            {
                Match m = Row.Match(line.TrimEnd('\r'));
                if (!m.Success) continue;
                rows++;
                int port = int.Parse(m.Groups[2].Value);
                int pid = int.Parse(m.Groups[3].Value);
                List<int> l;
                if (!d.TryGetValue(port, out l)) { l = new List<int>(); d[port] = l; }
                l.Add(pid);
            }
            return rows == 0 ? null : d;
        }

        public static string RunTable(int timeoutMs)
        {
            System.Diagnostics.Process p = new System.Diagnostics.Process();
            p.StartInfo.FileName = Path.Combine(Environment.SystemDirectory, "netstat.exe");
            p.StartInfo.Arguments = "-ano -p UDP";
            p.StartInfo.UseShellExecute = false;
            p.StartInfo.RedirectStandardOutput = true;
            p.StartInfo.CreateNoWindow = true;
            try
            {
                p.Start();
                string text = null;
                Bg reader = Bg.Start(delegate { text = p.StandardOutput.ReadToEnd(); });
                if (!reader.Join(timeoutMs)) { try { p.Kill(); } catch { } return null; }
                p.WaitForExit(timeoutMs);
                return p.ExitCode == 0 ? text : null;
            }
            catch
            {
                return null;
            }
            finally
            {
                p.Dispose();
            }
        }

        /// <summary>The owners of a port; null when the table cannot be read.</summary>
        public static int[] Read(int port)
        {
            Dictionary<int, List<int>> d = Parse(RunTable(10000));
            if (d == null) return null;
            List<int> l;
            return d.TryGetValue(port, out l) ? l.ToArray() : new int[0];
        }
    }

    internal sealed class PortReport
    {
        public Verdict V;
        public readonly List<string> Rows = new List<string>();
        public int External;
        public int Ports;
        public int Lookups;
    }

    internal static class PortCheck
    {
        /// <summary>Collects the facts of every port that the planes of the given run bound and judges them. Primary evidence: the close and the successful re-bind; the table of the operating system is read only for a port that is busy.</summary>
        public static PortReport Run(OwnedPort[] ledger, string runId, int ownPid, int limitMs)
        {
            PortReport rep = new PortReport();
            List<int> ports = new List<int>();
            foreach (OwnedPort o in ledger) if (!ports.Contains(o.Port)) ports.Add(o.Port);
            List<PortFacts> facts = new List<PortFacts>();
            foreach (int port in ports)
            {
                PortFacts f = new PortFacts();
                f.Port = port;
                f.Fixed = Net.IsFixedPort(port);
                f.CloseSeen = true;
                f.Virtual = true;
                f.RunId = runId;
                foreach (OwnedPort o in ledger)
                {
                    if (o.Port != port) continue;
                    f.RunId = o.RunId;
                    if (!o.Virtual) f.Virtual = false;
                    if (!o.CloseSeen) f.CloseSeen = false;
                }
                int[] reuse = Env.ReuseSnapshot();
                f.RegisteredReuse = Array.IndexOf(reuse, port) >= 0;
                if (f.RunId == runId && !f.Virtual && f.CloseSeen)
                {
                    Stopwatch sw = Stopwatch.StartNew();
                    while (true)
                    {
                        if (!f.Fixed)
                        {
                            f.Probe = Net.PortIsFree(port) ? 1 : 2;
                            if (f.Probe == 1) break;
                        }
                        rep.Lookups++;
                        f.Owners = UdpOwners.Read(port);
                        // the port was busy a moment ago and is not in the table now: it was released in between, try the re-bind once more
                        if (f.Owners != null && f.Owners.Length == 0 && !f.Fixed && sw.ElapsedMilliseconds < limitMs) { Wait.Ms(20); continue; }
                        break;
                    }
                }
                facts.Add(f);
            }
            rep.Ports = facts.Count;
            rep.V = PortJudge.Judge(facts.ToArray(), runId, ownPid, rep.Rows, out rep.External);
            return rep;
        }
    }

    /// <summary>A stand-in for a plane port in the controls: a real loopback port that the OS chose (never a fixed product port), entered in the ledger like a plane port.</summary>
    internal sealed class SimPort : IDisposable
    {
        private UdpClient client;
        public readonly OwnedPort Led;
        public readonly int Port;

        public SimPort(string runId)
        {
            for (int attempt = 0; attempt < 50; attempt++)
            {
                UdpClient u = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
                int p = ((IPEndPoint)u.Client.LocalEndPoint).Port;
                if (Net.IsFixedPort(p)) { u.Close(); continue; }
                client = u;
                Port = p;
                break;
            }
            if (client == null) throw new FixtureFaultException("the operating system handed out a fixed product port 50 times");
            Led = new OwnedPort();
            Led.RunId = runId;
            Led.PlanePid = 1;
            Led.Port = Port;
            Led.OsPid = System.Diagnostics.Process.GetCurrentProcess().Id;
            Led.Seq = 1;
        }

        /// <summary>The proper close: the socket is closed and the close is recorded.</summary>
        public void Close() { if (client != null) { try { client.Close(); } catch { } client = null; } Led.CloseSeen = true; }

        /// <summary>The defect "the book lies": the close is recorded but the socket stays open.</summary>
        public void RecordCloseOnly() { Led.CloseSeen = true; }

        public void Dispose() { if (client != null) { try { client.Close(); } catch { } client = null; } }
    }

    /// <summary>A same-process re-bind of a port after a plane has released it, registered with the kit.</summary>
    internal sealed class ReuseHolder : IDisposable
    {
        private UdpClient client;
        private readonly int port;
        private readonly bool register;

        public ReuseHolder(int port, bool register)
        {
            this.port = port;
            this.register = register;
            if (Net.IsFixedPort(port)) throw new FixtureFaultException("ReuseHolder on a fixed product port");
            client = new UdpClient(new IPEndPoint(IPAddress.Loopback, port));
            if (register) Env.NoteReuse(port);
        }

        public void Dispose()
        {
            if (client != null) { try { client.Close(); } catch { } client = null; }
            if (register) Env.ForgetReuse(port);
        }
    }

    /// <summary>A second process of the test (a child that this test started and that only it stops) that binds a loopback port.</summary>
    internal sealed class ExternalHolder : IDisposable
    {
        private System.Diagnostics.Process p;
        public int Pid;
        public int Port;

        public static ExternalHolder Hold(int port, int timeoutMs)
        {
            if (Net.IsFixedPort(port)) throw new FixtureFaultException("ExternalHolder on a fixed product port");
            string script = "$ProgressPreference = 'SilentlyContinue'; $u = New-Object System.Net.Sockets.UdpClient((New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Loopback, " + port + "))); "
                + "[Console]::Out.WriteLine('HOLD ' + $PID); [Console]::Out.Flush(); [void][Console]::In.ReadLine(); $u.Close()";
            string encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
            ExternalHolder h = new ExternalHolder();
            h.Port = port;
            h.p = new System.Diagnostics.Process();
            h.p.StartInfo.FileName = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell\\v1.0\\powershell.exe");
            h.p.StartInfo.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded;
            h.p.StartInfo.UseShellExecute = false;
            h.p.StartInfo.RedirectStandardInput = true;
            h.p.StartInfo.RedirectStandardOutput = true;
            h.p.StartInfo.CreateNoWindow = true;
            try
            {
                h.p.Start();
                string line = null;
                Bg reader = Bg.Start(delegate { line = h.p.StandardOutput.ReadLine(); });
                if (!reader.Join(timeoutMs) || line == null || !line.StartsWith("HOLD ")) { h.Dispose(); return null; }
                h.Pid = int.Parse(line.Substring(5).Trim());
                return h;
            }
            catch
            {
                h.Dispose();
                return null;
            }
        }

        public bool Alive
        {
            get { try { return p != null && !p.HasExited; } catch { return false; } }
        }

        public void Dispose()
        {
            if (p == null) return;
            try
            {
                if (!p.HasExited)
                {
                    try { p.StandardInput.WriteLine(); p.StandardInput.Close(); } catch { }
                    if (!p.WaitForExit(4000)) { try { p.Kill(); } catch { } }
                }
            }
            catch { }
            try { p.Dispose(); } catch { }
            p = null;
        }
    }
}
