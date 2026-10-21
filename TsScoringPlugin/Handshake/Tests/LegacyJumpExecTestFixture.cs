using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP LJX-1 (the minimal execution slice) - the tests, written BEFORE the product (RED first). TEST CODE ONLY: never part of the product DLL.
//
// Like the 2A-alpha tests (LegacyJumpPlaneTestFixture.cs) these cases bind the product by REFLECTION through the 2A kit (class Pr): a product element that does not exist
// yet is an EXPECTED RED (ProductAbsentException, classified by its code); any other exception and any failed check is a FAIL. The kit, the fakes of the Legacy telemetry
// tests (FakeApi, CollectDiag, Harness) and the IL scanner are compiled into the same assembly (TsScoringLegacyTelemetryTests), which the product lets in through
// InternalsVisibleTo.
//
// The product elements the cases pin (all internal, namespace TSScoringPlugin.Telemetry, Legacy project only):
//   LegacyJumpEnvironment.ExecutionEnabled / FeatureBits, LegacyJumpEnvironment.Production(pid, log, executionEnabled)
//   LegacyJumpFeatures (Sta, Loc, Complete, All), LegacyJumpTimings.ExecutionTtlMs, LegacyJumpBuild.ExecutionCompiledIn
//   LegacyJumpControlPlane.TryClaimForTick / ReportExecution / TryCompleteInPostSession / AbandonInFlight / JumpAvailable / ExecutionActive / PublishedCapabilities
//   LegacyJumpCommandState (Executing, CompletionPending, Completed, Failed, Abandoned), LegacyJumpClaim, LegacyJumpClaimFacts, LegacyJumpExecResult, LegacyJumpCompletion
//   ILegacyJumpHost, LegacyJumpReadBack, LegacyJumpExecutor, LegacyJumpTickRunner, ILegacyJumpCompleteSender, LegacyJumpSend, ILegacyJumpSessionPort, ILegacyJumpAvailability
//   LegacyTelemetrySession (9 argument constructor with the availability, NoteOfficialJump, LinesSent, LastLineJumpCount), LegacyDataPlaneSink.SendJumpComplete
//   AtsExLegacyJumpHost (the ONLY type that names the Legacy jump API)
// Written in C# 5 syntax (Windows PowerShell 5.1 Add-Type).
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    /// <summary>States of a receipt after the 2A-alpha ones (Rejected 0, Queued 1, Discarded 2).</summary>
    internal static class Ls
    {
        public const int Rejected = 0, Queued = 1, Discarded = 2, Executing = 3, CompletionPending = 4, Completed = 5, Failed = 6, Abandoned = 7;

        public static string Name(int s)
        {
            switch (s)
            {
                case 0: return "Rejected";
                case 1: return "Queued";
                case 2: return "Discarded";
                case 3: return "Executing";
                case 4: return "CompletionPending";
                case 5: return "Completed";
                case 6: return "Failed";
                case 7: return "Abandoned";
            }
            return "state" + s;
        }

        public const int SendHeld = 0, SendSent = 1, SendExcluded = 2;
        public const int CompleteNone = 0, CompleteDone = 1, CompletePending = 2, CompleteAbandoned = 3;
    }

    internal sealed class LxRec
    {
        public long Sequence;
        public int State;
        public string Reason;
        public string RidHex;
        public long AgeAtClaimMs;

        public string Short { get { return Ls.Name(State) + "/" + Reason; } }
    }

    /// <summary>A fake of the host seam of the executor: a tiny state machine that records every call in order. No Legacy API is involved.</summary>
    internal sealed class LxHost
    {
        public readonly EventLog Log;
        public object Obj;
        public volatile bool Created = true;
        public int TimeMs = 36000000;
        public double Location = 500.0;
        public double[] Stations = new double[] { 0.0, 1000.0, 2000.0, 3000.0 };
        public bool ReadBackUnreadable;
        public int TimeSkew;
        public double LocationSkew;
        public string ThrowOn;
        public int ThrowTimes = 1000000;
        public Action InsideCall;
        public Action Changed;
        public readonly List<string> Calls = new List<string>();
        private int inside;
        public int MaxInside;
        private int thrown;

        public LxHost(EventLog log)
        {
            Log = log;
            Obj = Proxy.Make(Pr.T("ILegacyJumpHost"), Handle);
        }

        public int ApiCalls { get { lock (Calls) { return Calls.Count; } } }

        public string[] CallsSnapshot() { lock (Calls) { return Calls.ToArray(); } }

        private static string D(double v) { return v.ToString("R", CultureInfo.InvariantCulture); }

        private void Enter(string what)
        {
            lock (Calls) { Calls.Add(what); }
            Log.Add("api:" + what);
            int n = Interlocked.Increment(ref inside);
            if (n > MaxInside) MaxInside = n;
        }

        private void Leave()
        {
            Interlocked.Decrement(ref inside);
            Action ch = Changed;
            if (ch != null) ch();
        }

        private void MaybeThrow(string name)
        {
            if (ThrowOn == name && Interlocked.Increment(ref thrown) <= ThrowTimes) throw new InvalidOperationException("injected-" + name);
        }

        private object Handle(MethodInfo m, object[] a)
        {
            switch (m.Name)
            {
                case "IsScenarioCreated":
                    return Created;
                case "ReadBack":
                    if (ReadBackUnreadable) return null;
                    object rb = Pr.New(Pr.T("LegacyJumpReadBack"));
                    Pr.Set(rb, "TimeMs", TimeMs + TimeSkew);
                    Pr.Set(rb, "Location", Location + LocationSkew);
                    Pr.Set(rb, "StationCount", Stations.Length);
                    return rb;
                case "StationLocation":
                    {
                        int i = (int)a[0];
                        return (i >= 0 && i < Stations.Length) ? Stations[i] : double.NaN;
                    }
                case "MoveToStation":
                    {
                        int i = (int)a[0];
                        Enter("MoveToStation(" + i + ")");
                        try
                        {
                            if (InsideCall != null) InsideCall();
                            MaybeThrow("MoveToStation");
                            if (i >= 0 && i < Stations.Length) Location = Stations[i];
                        }
                        finally { Leave(); }
                        return null;
                    }
                case "MoveToLocation":
                    {
                        double loc = (double)a[0];
                        int t = (int)a[1];
                        Enter("MoveToLocation(" + D(loc) + "," + t + ")");
                        try
                        {
                            if (InsideCall != null) InsideCall();
                            MaybeThrow("MoveToLocation");
                            Location = loc;
                            TimeMs = t;
                        }
                        finally { Leave(); }
                        return null;
                    }
                case "SetClockMs":
                    {
                        int t = (int)a[0];
                        Enter("SetClockMs(" + t + ")");
                        try
                        {
                            if (InsideCall != null) InsideCall();
                            MaybeThrow("SetClockMs");
                            TimeMs = t;
                        }
                        finally { Leave(); }
                        return null;
                    }
            }
            throw new FixtureFaultException("unexpected host seam method " + m.Name);
        }
    }

    /// <summary>A fake of the completion sender: records payload and request id, answers from a script (Held 0, Sent 1, Excluded 2).</summary>
    internal sealed class LxSender
    {
        public readonly EventLog Log;
        public object Obj;
        public readonly List<string> Payloads = new List<string>();
        public readonly List<string> Ids = new List<string>();
        public readonly Queue<int> Script = new Queue<int>();
        public int Default = Ls.SendSent;
        public bool ThrowNext;
        public int Calls;

        public LxSender(EventLog log)
        {
            Log = log;
            Obj = Proxy.Make(Pr.T("ILegacyJumpCompleteSender"), Handle);
        }

        private object Handle(MethodInfo m, object[] a)
        {
            if (m.Name != "SendJumpComplete") throw new FixtureFaultException("unexpected sender method " + m.Name);
            Interlocked.Increment(ref Calls);
            lock (Payloads)
            {
                Payloads.Add(Encoding.UTF8.GetString((byte[])a[0]));
                Ids.Add(FakeSource.Hex((byte[])a[1]));
            }
            Log.Add("complete");
            if (ThrowNext) { ThrowNext = false; throw new InvalidOperationException("injected-sender"); }
            int r = Default;
            lock (Script) { if (Script.Count > 0) r = Script.Dequeue(); }
            return r;
        }

        public string LastPayload { get { lock (Payloads) { return Payloads.Count == 0 ? null : Payloads[Payloads.Count - 1]; } } }
    }

    internal sealed class LxOpts
    {
        public long TtlMs = 5000;
        public bool Enabled = true;
        public int Features = 7;
        public bool Start = true;
        public bool Warm = true;
        public bool JumpAvail = true;       // the session gets the plane as its availability provider
        public Action<SeamHooks> Hooks;
        public Func<LxRig, object> SenderFactory;       // null = the recording fake; the served plane puts the real sink here
        public Func<int, TelemetryEndpoint> Owner;      // null = the random owner of the kit; the served plane takes the identity of the managed application
    }

    /// <summary>The plane of the 2A kit with the LJX-1 pieces around it: fake host, fake sender, the real session over the fake Legacy API, the product tick runner.</summary>
    internal sealed class LxRig : IDisposable
    {
        public PlaneRig R;
        public SnapView Snap;
        public LxHost Host;
        public LxSender Sender;
        public FakeApi Api;
        public CollectDiag Diag;
        public EventLog Log;
        public FakeClock Clk;
        public object Session;
        public object Executor;
        public object Runner;
        public long Mono = 100000;
        public readonly List<string> Sent = new List<string>();
        public int Ticks;

        public PlaneHandle P { get { return R.P; } }

        public void Dispose()
        {
            try { R.Dispose(); } catch { }
        }

        public static LxRig Make(Ctx c, LxOpts o)
        {
            LxRig x = new LxRig();
            PlaneOpts po = new PlaneOpts();
            x.Clk = new FakeClock();
            po.Clock = x.Clk;
            po.TtlMs = o.TtlMs;
            po.Hooks = o.Hooks;
            x.R = Kit.NewRig(c, po);
            Pr.Set(x.R.RawEnv, "ExecutionEnabled", o.Enabled);
            Pr.Set(x.R.RawEnv, "FeatureBits", o.Features);
            if (o.Owner != null) x.R.Src.Owner = o.Owner(x.R.Pid);
            x.Log = x.R.Seams.Log;
            x.Host = new LxHost(x.Log);
            x.Sender = new LxSender(x.Log);
            x.Api = new FakeApi();
            x.Diag = new CollectDiag();
            for (int i = 0; i < x.Host.Stations.Length; i++)
            {
                FakeStation st = new FakeStation();
                st.Name = "S" + i;
                st.Location = x.Host.Stations[i];
                x.Api.Stations.Add(st);
            }
            x.Api.SpeedMps = 0.0;
            x.Api.TimeMs = x.Host.TimeMs;
            x.Api.Location = x.Host.Location;
            LxRig self = x;
            x.Host.Changed = delegate { self.Api.TimeMs = self.Host.TimeMs; self.Api.Location = self.Host.Location; };
            object sink = Proxy.Make(Pr.T("ITelemetrySink"), delegate (MethodInfo m, object[] a)
            {
                if (m.Name == "Send")
                {
                    string text = (string)a[0];
                    lock (self.Sent) { self.Sent.Add(text); }
                    if (text.StartsWith("SCENARIO_ID:", StringComparison.Ordinal)) self.Log.Add("line");
                }
                return null;
            });
            Func<long> nowMs = delegate { return self.Mono; };
            Func<long> seed = delegate { return 5000000000L; };
            x.Session = Pr.New(Pr.T("LegacyTelemetrySession"), x.Api, sink, nowMs, seed, x.Diag, null, null, null, o.JumpAvail ? x.R.P.Raw : null);
            x.Executor = Pr.New(Pr.T("LegacyJumpExecutor"), x.Host.Obj, new Func<long>(x.Clk.Now));
            x.Runner = Pr.New(Pr.T("LegacyJumpTickRunner"), x.R.P.Raw, x.Executor, x.Host.Obj, x.Session, o.SenderFactory != null ? o.SenderFactory(x) : x.Sender.Obj);
            if (o.Start)
            {
                x.R.P.Start();
                x.Snap = Kit.AwaitReady(x.R.P, 15000);
                if (x.Snap == null)
                {
                    SnapView cur = x.R.P.Snapshot();
                    throw new FixtureFaultException("the plane did not become READY: state=" + PState.Name(cur.State) + " attempts=" + cur.Attempts + " binds=" + x.R.Seams.BindCalls
                        + " creates=" + x.R.Seams.CreateCalls + " alive=" + x.R.P.IsWorkerAlive + " log=[" + string.Join(" / ", x.R.Lines()) + "]");
                }
                if (o.Warm) x.Tick(16);
            }
            return x;
        }

        /// <summary>The first half of a Tick alone (claim, host sequence); repeated only when the claim found the gate busy.</summary>
        public void PreOnly()
        {
            for (int k = 0; k < 40; k++)
            {
                long contendedBefore = Counter("claim-contended");
                Pr.Call(Runner, "TickPre");
                if (Counter("claim-contended") == contendedBefore) break;
            }
        }

        public void Tick(int stepMs)
        {
            Mono += stepMs;
            Host.TimeMs += stepMs;
            Api.TimeMs = Host.TimeMs;
            Api.Location = Host.Location;
            // the claim never waits for the gate: when the worker happens to be stepping it counts a contention and returns nothing. A real host would simply try again on its next
            // Tick; the harness repeats only the claim half (the session and the completion still run once per logical Tick) so that the cases do not depend on that coincidence.
            for (int k = 0; k < 40; k++)
            {
                long contendedBefore = Counter("claim-contended");
                Pr.Call(Runner, "TickPre");
                if (Counter("claim-contended") == contendedBefore) break;
            }
            Pr.Call(Session, "OnTick", TimeSpan.FromMilliseconds((double)stepMs));
            Pr.Call(Runner, "TickPost");
            Ticks++;
        }

        public object NewFacts(bool created, bool active)
        {
            object f = Pr.New(Pr.T("LegacyJumpClaimFacts"));
            Pr.Set(f, "ScenarioCreated", created);
            Pr.Set(f, "SessionActive", active);
            return f;
        }

        /// <summary>One claim; repeated only when it found the gate busy (the worker was stepping), as a host Tick would try again.</summary>
        public object Claim()
        {
            object t = null;
            for (int k = 0; k < 40; k++)
            {
                long contendedBefore = Counter("claim-contended");
                t = Pr.Call(P.Raw, "TryClaimForTick", NewFacts(true, true));
                if (t != null || Counter("claim-contended") == contendedBefore) break;
            }
            return t;
        }

        public RecView Send(string text, UInt32 type, byte[] rid)
        {
            return Kit.SendAndAwait(R, Snap, Cmd.Valid(Snap, R.Pid, R.Src.Owner, rid, text, type), 4000);
        }

        public RecView SendSta(byte[] rid, int index, int timeMs)
        {
            return Send("JUMP_STA_TIME:" + index + ":" + timeMs, 0x100U, rid);
        }

        public RecView SendLoc(byte[] rid, double loc, int timeMs)
        {
            return Send("JUMP_LOC_TIME:" + loc.ToString("R", CultureInfo.InvariantCulture) + ":" + timeMs, 0x101U, rid);
        }

        public LxRec Rec(byte[] rid)
        {
            string h = FakeSource.Hex(rid);
            System.Collections.IEnumerable e = (System.Collections.IEnumerable)Pr.Call(P.Raw, "Outcomes");
            LxRec found = null;
            foreach (object r in e)
            {
                byte[] id = (byte[])Pr.Get(r, "RequestId");
                if (id != null && FakeSource.Hex(id) == h)
                {
                    LxRec v = new LxRec();
                    v.Sequence = Convert.ToInt64(Pr.Get(r, "Sequence"));
                    v.State = Convert.ToInt32(Pr.Get(r, "State"));
                    v.Reason = (string)Pr.Get(r, "Reason");
                    v.RidHex = h;
                    v.AgeAtClaimMs = Convert.ToInt64(Pr.Get(r, "AgeAtClaimMs"));
                    found = v;
                }
            }
            return found;
        }

        public string[] Lines() { return R.Lines(); }

        public List<string> LinesWith(string word)
        {
            List<string> l = new List<string>();
            foreach (string s in R.Lines()) if (s.IndexOf(word, StringComparison.Ordinal) >= 0) l.Add(s);
            return l;
        }

        public string LastTelemetryLine()
        {
            lock (Sent)
            {
                for (int i = Sent.Count - 1; i >= 0; i--) if (Sent[i].StartsWith("SCENARIO_ID:", StringComparison.Ordinal)) return Sent[i];
            }
            return null;
        }

        public long Counter(string key) { return P.Counter(key); }

        public int Illegal { get { return (int)Counter("illegal-transition"); } }
    }

    public static partial class LegacyJumpExecTestFixture
    {
        /// <summary>Set by the runner: the DLL under test was built with the LJX-1 compile symbol (the acceptance build) or not (the default build).</summary>
        public static bool ExpectCompiledIn;

        private static readonly string[] Order = new string[]
        {
            "LJX-01", "LJX-02", "LJX-03", "LJX-04", "LJX-05", "LJX-06", "LJX-07", "LJX-08", "LJX-09", "LJX-10", "LJX-11", "LJX-12", "LJX-13", "LJX-14", "LJX-15",
            "LJX-16", "LJX-17", "LJX-18", "LJX-19", "LJX-20", "LJX-21", "LJX-22", "LJX-23", "LJX-24", "LJX-25", "LJX-26", "LJX-27", "LJX-28", "LJX-29", "LJX-30", "LJX-31", "LJX-32", "LJX-99"
        };

        public static string[] DiscoverIds()
        {
            List<string> ids = new List<string>();
            foreach (MethodInfo m in typeof(LegacyJumpExecTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length > 0) ids.Add(((CaseAttribute)a[0]).Id);
            }
            ids.Sort(StringComparer.Ordinal);
            return ids.ToArray();
        }

        public static RunResult Run(Assembly product, string runId, string repoRoot, string[] only)
        {
            Pr.Load(product);
            Env.Init(runId);
            Env.RepoRoot = repoRoot;
            Env.BaselineHandles = Process.GetCurrentProcess().HandleCount;
            Env.BaselineThreads = Process.GetCurrentProcess().Threads.Count;
            RunResult rr = new RunResult();
            Dictionary<string, MethodInfo> byId = new Dictionary<string, MethodInfo>();
            Dictionary<string, CaseAttribute> attrs = new Dictionary<string, CaseAttribute>();
            foreach (MethodInfo m in typeof(LegacyJumpExecTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length == 0) continue;
                CaseAttribute ca = (CaseAttribute)a[0];
                byId[ca.Id] = m;
                attrs[ca.Id] = ca;
            }
            rr.Discovered = byId.Count;
            List<string> ids = new List<string>();
            foreach (string id in Order) if (byId.ContainsKey(id)) ids.Add(id);
            foreach (string id in byId.Keys) if (!ids.Contains(id)) ids.Add(id);
            foreach (string id in ids)
            {
                if (only != null && only.Length > 0 && Array.IndexOf(only, id) < 0) continue;
                rr.Invoked++;
                rr.Tests.Add(Execute(id, attrs[id], byId[id]));
            }
            rr.Header = "product=" + product.GetName().Name + " version=" + product.GetName().Version + " run=" + runId + " compiledIn=" + ExpectCompiledIn;
            return rr;
        }

        private static TestResult Execute(string id, CaseAttribute ca, MethodInfo m)
        {
            TestResult tr = new TestResult();
            tr.Id = id;
            tr.Label = ca.Label;
            tr.Kind = ca.Kind;
            Ctx c = new Ctx(id);
            Stopwatch sw = Stopwatch.StartNew();
            string redCode = null;
            string fault = null;
            try
            {
                try { m.Invoke(null, new object[] { c }); }
                catch (TargetInvocationException ex) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); }
            }
            catch (ProductAbsentException ex)
            {
                redCode = ex.Code;
            }
            catch (Exception ex)
            {
                string t = ex.ToString();
                if (t.Length > 700) t = t.Substring(0, 700);
                fault = ex.GetType().Name + " :: " + t.Replace("\r", " ").Replace("\n", " ");
            }
            finally
            {
                c.ReleaseAll();
            }
            tr.Seconds = sw.Elapsed.TotalSeconds;
            tr.Checks = c.Checks.Count;
            tr.Failed = c.FailedChecks;
            tr.Log = c.Log.ToString();
            if (redCode != null) { tr.Outcome = "RED"; tr.RedCode = redCode; }
            else if (fault != null) { tr.Outcome = "FAIL"; tr.FailText = fault; }
            else
            {
                if (c.FailedChecks > 0)
                {
                    tr.Outcome = "FAIL";
                    foreach (CheckRec r in c.Checks) if (!r.Ok) { tr.FailText = "check: " + r.What + (r.Actual == null ? "" : " [" + r.Actual + "]"); break; }
                }
                else if (c.InconclusiveCount > 0) { tr.Outcome = "INCONCLUSIVE"; lock (c.Inconclusives) { tr.FailText = c.Inconclusives[0]; } }
                else if (c.Checks.Count == 0) { tr.Outcome = "FAIL"; tr.FailText = "no check was made"; }
                else tr.Outcome = "PASS";
            }
            return tr;
        }

        // ---- small helpers ---------------------------------------------------------------------------------------------------------------------
        internal static string Seq(string[] events)
        {
            StringBuilder sb = new StringBuilder();
            foreach (string l in events) { if (sb.Length > 0) sb.Append(" ; "); sb.Append(EventLog.NameOf(l)); }
            return sb.ToString();
        }

        internal static int IndexOfEvent(string[] events, string prefix)
        {
            for (int i = 0; i < events.Length; i++) if (EventLog.NameOf(events[i]).StartsWith(prefix, StringComparison.Ordinal)) return i;
            return -1;
        }

        internal static string KeyValue(string line, string key)
        {
            int i = line.IndexOf(" " + key + "=", StringComparison.Ordinal);
            if (i < 0) return null;
            int s = i + key.Length + 2;
            int e = line.IndexOf(' ', s);
            return e < 0 ? line.Substring(s) : line.Substring(s, e - s);
        }

        internal static string RemoveJump(string line)
        {
            if (line == null) return null;
            int a = line.IndexOf("AVAIL:1:", StringComparison.Ordinal);
            if (a >= 0)
            {
                int b = line.IndexOf(',', a);
                string avail = line.Substring(a, b - a);
                string[] parts = avail.Substring("AVAIL:1:".Length).Split('+');
                List<string> keep = new List<string>();
                foreach (string p in parts) if (p != "jump") keep.Add(p);
                line = line.Substring(0, a) + "AVAIL:1:" + string.Join("+", keep.ToArray()) + line.Substring(b);
            }
            int j = line.IndexOf(",JUMP:", StringComparison.Ordinal);
            if (j >= 0)
            {
                int k = line.IndexOf(',', j + 1);
                line = k < 0 ? line.Substring(0, j) : line.Substring(0, j) + line.Substring(k);
            }
            return line;
        }

        /// <summary>The way the managed application reads a JUMP_COMPLETE: at least 6 fields; the 3rd an int, the 4th a float, the 5th and 6th ints.</summary>
        internal static bool ReadsAsComplete(string text, out string kind, out int index, out double location, out int time, out int count)
        {
            kind = null; index = 0; location = 0; time = 0; count = 0;
            if (text == null || !text.StartsWith("JUMP_COMPLETE:", StringComparison.Ordinal)) return false;
            string[] p = text.Split(':');
            if (p.Length < 6) return false;
            kind = p[1];
            return int.TryParse(p[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out index)
                && double.TryParse(p[3], NumberStyles.Float, CultureInfo.InvariantCulture, out location)
                && int.TryParse(p[4], NumberStyles.Integer, CultureInfo.InvariantCulture, out time)
                && int.TryParse(p[5], NumberStyles.Integer, CultureInfo.InvariantCulture, out count);
        }

        internal static object Ticket(LxRig x, int kind, int index, double location, int timeMs)
        {
            object t = Pr.New(Pr.T("LegacyJumpClaim"));
            Pr.Set(t, "Kind", kind);
            Pr.Set(t, "StaIndex", index);
            Pr.Set(t, "Location", location);
            Pr.Set(t, "TimeMs", timeMs);
            Pr.Set(t, "RequestId", Cmd.Rid());
            return t;
        }

        internal static object ExecuteTicket(LxRig x, object ticket)
        {
            return Pr.Call(x.Executor, "Execute", ticket, (Func<int>)delegate { return 0; });
        }
    }
}
