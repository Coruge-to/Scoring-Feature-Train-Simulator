using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA / STAGE S1 - the tests (A4a). TEST CODE ONLY: never part of the product DLL.
//
// The cases below are the product tests of 2A-alpha: ITR-01..16 (ITR-10 is the product replacement of the isolated claim race, decision D-6), EX-01..03,
// WIN-01..04, WIN-99 and PT-01..09 of the automated test plan. They are re-derived from the isolated tests of PID-D0B-1 (expectations not loosened) and talk to the
// product ONLY through the test kit (LegacyJumpPlaneTestKit.cs, A4b): reflection binding, seam doubles, Windows helpers. This file therefore holds no operating
// system resource word and no thread / process / file call; the kit holds them (and only the kit is excluded from Verify-PhaseC3 by exact path).
//
// Outcome of a case: PASS, FAIL, or RED. RED = the case reached a pinned product element that does not exist yet (ProductAbsentException): an EXPECTED red while
// the product is unwritten, classified by its code. Any other exception, and any failed check, is a FAIL.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    [AttributeUsage(AttributeTargets.Method)]
    internal sealed class CaseAttribute : Attribute
    {
        public readonly string Id;
        public readonly string Label;
        public string Kind = "NEW";          // NEW: subject is new functionality (must be RED while the product is absent); GUARD: must stay GREEN
        public string Purpose;
        public string Precondition;
        public string Operation;
        public string Expected;
        public string Contract;

        public CaseAttribute(string id, string label)
        {
            Id = id;
            Label = label;
        }
    }

    public sealed class TestResult
    {
        public string Id;
        public string Label;
        public string Kind;
        public string Outcome;            // PASS | FAIL | RED | INCONCLUSIVE (no verdict could be reached: never a PASS)
        public string RedCode;            // for RED: the first absent product element
        public string FailText;           // for FAIL: the first failing check / exception
        public int Checks;
        public int Failed;
        public double Seconds;
        public string Log;
    }

    public sealed class RunResult
    {
        public List<TestResult> Tests = new List<TestResult>();
        public int Discovered;
        public int Invoked;
        public string Header;
    }

    public static partial class LegacyJumpPlaneTestFixture
    {
        private static readonly string[] Order = new string[]
        {
            "ITR-01", "ITR-02", "ITR-03", "ITR-04", "ITR-05", "ITR-06", "ITR-07", "ITR-08", "ITR-09", "ITR-10", "ITR-11", "ITR-12", "ITR-13", "ITR-14", "ITR-15", "ITR-16",
            "EX-01", "EX-02", "EX-03", "WIN-01", "WIN-02", "WIN-03", "WIN-04",
            "PT-01", "PT-02", "PT-03", "PT-04", "PT-05", "PT-06", "PT-07", "PT-08", "PT-09",
            "WIN-99"
        };

        /// <summary>The ids of every case method found by reflection (the machine count of the tests).</summary>
        public static string[] DiscoverIds()
        {
            List<string> ids = new List<string>();
            foreach (MethodInfo m in typeof(LegacyJumpPlaneTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length > 0 && ((CaseAttribute)a[0]).Kind != "SELF") ids.Add(((CaseAttribute)a[0]).Id);
            }
            ids.Sort(StringComparer.Ordinal);
            return ids.ToArray();
        }

        /// <summary>The ids of the kit self tests (they need no product).</summary>
        public static string[] DiscoverSelfIds()
        {
            List<string> ids = new List<string>();
            foreach (MethodInfo m in typeof(LegacyJumpPlaneTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length > 0 && ((CaseAttribute)a[0]).Kind == "SELF") ids.Add(((CaseAttribute)a[0]).Id);
            }
            ids.Sort(StringComparer.Ordinal);
            return ids.ToArray();
        }

        /// <summary>Runs the kit self tests: they prove the helpers, the trace checker and the residue detectors work, with no product at all.</summary>
        public static RunResult RunSelf(Assembly anyAssembly, string runId, string repoRoot)
        {
            Pr.Load(anyAssembly);
            Env.Init(runId);
            Env.RepoRoot = repoRoot;
            RunResult rr = new RunResult();
            List<string> ids = new List<string>(DiscoverSelfIds());
            rr.Discovered = ids.Count;
            foreach (MethodInfo m in typeof(LegacyJumpPlaneTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length == 0 || ((CaseAttribute)a[0]).Kind != "SELF") continue;
                CaseAttribute ca = (CaseAttribute)a[0];
                rr.Invoked++;
                rr.Tests.Add(Execute(ca.Id, ca, m));
            }
            rr.Header = "self-test run=" + runId;
            return rr;
        }

        /// <summary>Runs the cases against the product assembly. only = null or empty: all cases, in the planned order (WIN-99 last).</summary>
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
            foreach (MethodInfo m in typeof(LegacyJumpPlaneTestFixture).GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                object[] a = m.GetCustomAttributes(typeof(CaseAttribute), false);
                if (a.Length == 0) continue;
                CaseAttribute ca = (CaseAttribute)a[0];
                if (ca.Kind == "SELF") continue;
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
                TestResult tr = Execute(id, attrs[id], byId[id]);
                rr.Tests.Add(tr);
            }
            rr.Header = "product=" + product.GetName().Name + " version=" + product.GetName().Version + " run=" + runId;
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
                catch (TargetInvocationException ex) { ExceptionDispatchInfoRethrow(ex); }
            }
            catch (ProductAbsentException ex)
            {
                redCode = ex.Code;
            }
            catch (Exception ex)
            {
                fault = ex.GetType().Name + " at " + FirstFrame(ex) + " :: " + FlatText(ex);
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
                string text;
                tr.Outcome = OutcomeOf(c, out text);
                tr.FailText = text;
            }
            return tr;
        }

        /// <summary>The outcome of a finished case without a fault: a failed check is a FAIL, a case that could not reach a verdict is INCONCLUSIVE (never a PASS), a case without a check is a FAIL.</summary>
        internal static string OutcomeOf(Ctx c, out string text)
        {
            text = null;
            if (c.FailedChecks > 0)
            {
                foreach (CheckRec r in c.Checks) if (!r.Ok) { text = "check: " + r.What + (r.Actual == null ? "" : " [" + r.Actual + "]"); break; }
                return "FAIL";
            }
            if (c.InconclusiveCount > 0)
            {
                lock (c.Inconclusives) { text = c.Inconclusives[0]; }
                return "INCONCLUSIVE";
            }
            if (c.Checks.Count == 0)
            {
                text = "no check was made (a case without a single assertion proves nothing)";
                return "FAIL";
            }
            return "PASS";
        }

        private static void ExceptionDispatchInfoRethrow(TargetInvocationException ex)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(ex.InnerException).Throw();
        }

        private static string FirstFrame(Exception ex)
        {
            string s = ex.ToString();
            int a = s.IndexOf("   at ", StringComparison.Ordinal);
            if (a < 0) return "?";
            int b = s.IndexOf('\n', a);
            return (b > a ? s.Substring(a, b - a) : s.Substring(a)).Trim();
        }

        private static string FlatText(Exception ex)
        {
            string t = ex.ToString();
            if (t.Length > 600) t = t.Substring(0, 600);
            return t.Replace("\r", " ").Replace("\n", " ");
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // small shared helpers of the cases
        // ---------------------------------------------------------------------------------------------------------------------------------
        internal static PlaneRig ReadyRig(Ctx c, PlaneOpts o, out SnapView snap)
        {
            PlaneRig r = Kit.NewRig(c, o);
            r.P.Start();
            snap = Kit.AwaitReady(r.P, 5000);
            if (snap == null)
            {
                SnapView cur = r.P.Snapshot();
                c.Info("ReadyRig: the plane did not become READY: state=" + PState.Name(cur.State) + " attempts=" + cur.Attempts + " binds=" + r.Seams.BindCalls + " creates=" + r.Seams.CreateCalls + " openPorts=" + r.Seams.OpenPorts + " log=[" + string.Join(" / ", r.Lines()) + "] events=[" + r.Seams.Log.Names() + "]");
            }
            return r;
        }

        internal static PlaneOpts Short()
        {
            return new PlaneOpts();
        }

        internal static bool Same(byte[] a, byte[] b)
        {
            return FakeSource.Hex(a) == FakeSource.Hex(b);
        }

        internal static string Seq(string[] trace)
        {
            StringBuilder sb = new StringBuilder();
            foreach (string l in trace) { if (sb.Length > 0) sb.Append(" ; "); sb.Append(EventLog.NameOf(l)); }
            return sb.ToString();
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpPlaneTestFixture
    {
        // =====================================================================================================================================
        // ITR-01  worker vs Dispose race (G-2)
        // =====================================================================================================================================
        [Case("ITR-01", "worker and Dispose race in every phase",
            Purpose = "G-2: Dispose in every phase of the worker (creating / publishing READY / receiving / retry / withdrawing) keeps the shutdown contract",
            Precondition = "synthetic BVE PID, product Directory name of that PID, loopback port 0, the dedicated worker, stalls injected at the seams",
            Operation = "13 phases x 8 rounds: a disposer thread calls Dispose exactly while the worker sits (and jitters) in that phase",
            Expected = "publish order intact, CLOSED last, no event after CLOSED, no illegal transition, all resources released",
            Contract = "OD-Add1 G-2; v2 4.5 / RC-9; D0B-1 15.3")]
        internal static void Itr01(Ctx c)
        {
            string[] phases = new string[] { "bind", "createnew", "publish-nonready", "read-path", "publish-ready", "step:begin", "read:after-read",
                "recreate:withdrawing", "recreate:after-withdrawing", "teardown:withdrawing", "teardown:after-withdrawing", "retry-waiting", "loop:iteration" };
            int rounds = 8, total = 0, bad = 0, notFired = 0;
            for (int pi = 0; pi < phases.Length; pi++)
            {
                for (int r = 0; r < rounds; r++)
                {
                    total++;
                    bool fired;
                    string problem = DisposeRace(c, phases[pi], r, out fired);
                    if (!fired) notFired++;
                    if (problem != null) { bad++; c.Info("round " + phases[pi] + "#" + r + ": " + problem); }
                }
            }
            c.Check(notFired == 0, "every phase was really exercised (the disposer fired inside that phase)", notFired + " rounds without a hit of " + total);
            c.Check(bad == 0, "every round keeps the shutdown contract", total + " rounds, " + bad + " violations");
        }

        private static string DisposeRace(Ctx c, string phase, int round, out bool fired)
        {
            ManualResetEvent fire = new ManualResetEvent(false);
            int armed = 1;
            int failOnce = phase == "retry-waiting" ? 1 : 0;
            int throwOnce = 0;
            bool recreating = false, disposing = false;
            Random rnd = new Random(round * 7919 + phase.Length);
            PlaneRig rig = null;
            Action hit = delegate
            {
                if (Interlocked.Exchange(ref armed, 0) == 1)
                {
                    fire.Set();
                    Wait.Ms(rnd.Next(0, 4));
                }
            };
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h)
            {
                h.OnBind = delegate
                {
                    if (phase == "retry-waiting" && Interlocked.Exchange(ref failOnce, 0) == 1) throw new IOException("injected-bind-failure");
                    if (phase == "bind") hit();
                };
                h.OnCreate = delegate { if (phase == "createnew") hit(); };
                h.OnAvailable = delegate { if (phase == "read-path" && rig != null && rig.P.State == PState.Publishing) hit(); };
                h.OnClock = delegate { if (phase == "step:begin" && rig != null && rig.P.State == PState.Ready) hit(); };
                h.AfterRead = delegate
                {
                    if (phase == "read:after-read") hit();
                    if (phase.StartsWith("recreate:") && Interlocked.Exchange(ref throwOnce, 0) == 1) { recreating = true; throw new IOException("injected-read"); }
                };
                h.BeforePublish = delegate (UInt32 st)
                {
                    if (phase == "publish-nonready" && st == 1U) hit();
                    if (phase == "publish-ready" && st == 3U) hit();
                    if (phase == "recreate:withdrawing" && recreating && st == 7U) hit();
                    if (phase == "teardown:withdrawing" && disposing && st == 7U) hit();
                };
                h.AfterPublish = delegate (UInt32 st)
                {
                    if (phase == "recreate:after-withdrawing" && recreating && st == 7U) hit();
                    if (phase == "teardown:after-withdrawing" && disposing && st == 7U) hit();
                };
                h.AfterWait = delegate (bool stopped)
                {
                    if (stopped || rig == null) return;
                    if (phase == "retry-waiting" && rig.P.State == PState.RetryWaiting) hit();
                    if (phase == "loop:iteration" && rig.P.State == PState.Ready) hit();
                };
            };
            rig = Kit.NewRig(c, o);
            fired = false;
            Exception disposerError = null;
            Bg disposer = Bg.Start(delegate
            {
                try { fire.WaitOne(6000); rig.P.Dispose(); } catch (Exception ex) { disposerError = ex; }
            });
            string problem = null;
            try
            {
                rig.P.Start();
                if (phase == "read:after-read" || phase.StartsWith("recreate:") || phase.StartsWith("teardown:"))
                {
                    SnapView s = Kit.AwaitReady(rig.P, 5000);
                    if (s == null) { problem = "never reached READY"; }
                    else if (phase == "read:after-read") Net.SendTo(s.Port, Cmd.Valid(s, rig.Pid, rig.Src.Owner, Cmd.Rid()));
                    else if (phase.StartsWith("recreate:"))
                    {
                        Interlocked.Exchange(ref throwOnce, 1);
                        Net.SendTo(s.Port, Cmd.Valid(s, rig.Pid, rig.Src.Owner, Cmd.Rid()));
                    }
                    else { disposing = true; rig.P.Dispose(); }          // the hook then fires the second (concurrent) Dispose
                }
                fire.WaitOne(6000);
                bool joined = disposer.Join(10000);
                if (!joined) problem = problem ?? "disposer did not return";
                if (!Wait.For(delegate { return rig.P.State == PState.Closed; }, 5000)) problem = problem ?? "state is not Closed: " + rig.P.StateName;
                if (disposerError != null) problem = problem ?? "Dispose threw " + disposerError.GetType().Name;
                int n1 = rig.Seams.Log.Count;
                Wait.Ms(40);
                int n2 = rig.Seams.Log.Count;
                if (n1 != n2) problem = problem ?? "the plane kept working after CLOSED";
                string v = TraceChecker.Verify(rig.Seams.Log.Snapshot(), true);
                if (v != null) { problem = problem ?? v; c.Info("trace of the violating round: " + rig.Seams.Log.Names()); }
                if (rig.P.Counter("illegal-transition") != 0) problem = problem ?? "illegal transition";
                if (rig.P.MaxPublishersInside > 1) problem = problem ?? "two writers inside the publisher";
                if (!Net.NameIsFree(rig.Name)) problem = problem ?? "the mapping name is still alive after Dispose";
                if (rig.Seams.OpenPorts != 0 || rig.Seams.OpenMappings != 0) problem = problem ?? "a port or a mapping was left open";
            }
            finally
            {
                fire.Set();
                rig.P.Dispose();
                disposer.Dispose();
            }
            fired = Thread.VolatileRead(ref armed) == 0;
            return problem;
        }

        // =====================================================================================================================================
        // ITR-02  re-entrancy (G-4)
        // =====================================================================================================================================
        [Case("ITR-02", "timer callback re-entrancy vs the dedicated single worker",
            Purpose = "G-4: a periodic timer re-enters (negative control); the dedicated single worker never overlaps itself",
            Precondition = "a slow step (a stall in every step, inside the gate), many Tick-equivalent liveness callers",
            Operation = "(a) timer 5 ms with a 60 ms callback; (b) worker poll 1 ms with a 15 ms stall in every step, 4 threads calling EnsureWorkerAlive",
            Expected = "(a) max concurrent callbacks >= 2; (b) max concurrent steps == 1 over >= 20 steps; no timer type in the product types",
            Contract = "OD-Add1 G-4; v2 4.5 (TA-4); audit 6.3 I1")]
        internal static void Itr02(Ctx c)
        {
            int max, calls;
            Kit.TimerReentrancy(out max, out calls);
            c.Check(max >= 2, "negative control: a periodic timer re-enters a slow callback", "max concurrent callbacks=" + max + " of " + calls + " calls");

            int steps = 0;
            PlaneRig rig = null;
            PlaneOpts o = Short();
            o.PollMs = 1;
            o.Hooks = delegate (SeamHooks h)
            {
                h.OnClock = delegate
                {
                    if (rig != null && rig.P.State == PState.Ready) { Interlocked.Increment(ref steps); Wait.Ms(15); }
                };
            };
            rig = Kit.NewRig(c, o);
            rig.P.Start();
            c.Check(Kit.AwaitReady(rig.P, 5000) != null, "READY before the slow steps are judged");
            int stepsAtReady = Thread.VolatileRead(ref steps);
            bool stop = false;
            List<Bg> ts = new List<Bg>();
            for (int i = 0; i < 4; i++) ts.Add(Bg.Start(delegate { while (!stop) { rig.P.EnsureWorkerAlive(); Wait.Ms(0); } }));
            Wait.Ms(900);
            stop = true;
            foreach (Bg b in ts) b.Join(2000);
            rig.P.Dispose();
            c.Check(Thread.VolatileRead(ref steps) - stepsAtReady >= 20, "the worker really ran many slow steps", "steps=" + (Thread.VolatileRead(ref steps) - stepsAtReady));
            c.Check(rig.P.MaxStepsInside == 1, "dedicated worker: max concurrent steps is exactly 1", "max=" + rig.P.MaxStepsInside);
            c.Check(rig.P.Counter("illegal-transition") == 0 && rig.P.Counter("step-exception") == 0, "no illegal transition / step exception");
            c.Check(rig.Seams.WaiterThreads.Count == 1, "exactly one thread ever drove the plane (the dedicated worker)", "threads=" + rig.Seams.WaiterThreads.Count);
            c.Check(!LegacyIlCallScan.ReferencesType(Pr.Asm, "TSScoringPlugin.Telemetry.LegacyJump", Kit.TimerType), "no timer type is referenced by the product LegacyJump types");
        }

        // =====================================================================================================================================
        // ITR-03  gate serialisation
        // =====================================================================================================================================
        [Case("ITR-03", "gate serialisation of Publish and Dispose",
            Purpose = "G-2/G-4/RC-9: the shared JumpDirectoryPublisher is not thread safe; the single writer gate must serialise every Publish and Dispose",
            Precondition = "negative: the raw publisher; positive: the control plane under four hostile threads (re-create / epoch / send / liveness)",
            Operation = "negative: Publish after Dispose, an overlap counter; positive: 4 hammer threads then Dispose while they still run",
            Expected = "negative control shows the hazard; positive: max writers inside Publish == 1, no exception, no illegal transition, order valid",
            Contract = "RC-9; audit 4.3 H1")]
        internal static void Itr03(Ctx c)
        {
            int pid0 = c.NewPid();
            byte[] tok = FakeSource.RandomBytes(16);
            Kit.RawPublisher pub = new Kit.RawPublisher(pid0, Env.ProductName(pid0) + ".neg");
            pub.Publish(DataPlaneProtocol.Published | DataPlaneProtocol.Ready, 40000U, 7U, tok, 4U);
            pub.Dispose();
            bool threw = false;
            try { pub.Publish(DataPlaneProtocol.Published | DataPlaneProtocol.Ready, 40000U, 7U, tok, 4U); } catch (ObjectDisposedException) { threw = true; }
            c.Check(threw, "negative control: the raw publisher throws when Publish follows Dispose (it has no gate)");
            int racing = 0, rounds = 60;
            for (int i = 0; i < rounds; i++)
            {
                int pidR = c.NewPid();
                Kit.RawPublisher rp = new Kit.RawPublisher(pidR, Env.ProductName(pidR) + ".negrace");
                bool halt = false;
                int exc = 0;
                Bg a = Bg.Start(delegate { try { while (!halt) rp.Publish(DataPlaneProtocol.Published | DataPlaneProtocol.Ready, 40000U, 7U, tok, 4U); } catch (Exception) { Interlocked.Increment(ref exc); } });
                Wait.Ms(1);
                rp.Dispose();
                a.Join(2000);
                halt = true;
                racing += exc;
            }
            c.Info("informational: ungated Publish/Dispose races that threw: " + racing + " of " + rounds);
            c.Check(racing > 0, "negative control: an ungated Publish racing Dispose throws (the hazard is real)", racing + " of " + rounds + " rounds");

            int simInside = 0, simMax = 0;
            object simLock = new object();
            Action sim = delegate
            {
                int n = Interlocked.Increment(ref simInside);
                lock (simLock) { if (n > simMax) simMax = n; }
                Wait.Ms(30);
                Interlocked.Decrement(ref simInside);
            };
            Bg s1 = Bg.Start(sim), s2 = Bg.Start(sim);
            s1.Join(3000); s2.Join(3000);
            c.Check(simMax >= 2, "negative control: the overlap counter detects two writers when nothing serialises them", "max=" + simMax);

            PlaneRig rig = null;
            int throwNext = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-hammer"); }; };
            SnapView snap;
            rig = ReadyRig(c, o, out snap);
            c.Check(snap != null, "READY before the hammer");
            bool done = false;
            List<Exception> errors = new List<Exception>();
            List<Bg> hs = new List<Bg>();
            Action<Action> spawn = delegate (Action body)
            {
                hs.Add(Bg.Start(delegate { try { body(); } catch (Exception ex) { lock (errors) { errors.Add(ex); } } }));
            };
            spawn(delegate
            {
                while (!done)
                {
                    SnapView s = rig.P.Snapshot();
                    if (s.State == PState.Ready && s.Port != 0) { Interlocked.Exchange(ref throwNext, 1); try { Net.SendTo(s.Port, new byte[] { 1, 2, 3 }); } catch (Exception) { } }
                    Wait.Ms(3);
                }
            });
            spawn(delegate { while (!done) { rig.P.NoteScenarioBoundary(); rig.P.Snapshot(); rig.P.Outcomes(); Wait.Ms(0); } });
            spawn(delegate
            {
                while (!done)
                {
                    SnapView s = rig.P.Snapshot();
                    if (s.Port != 0 && s.State == PState.Ready) { try { Net.SendTo(s.Port, Cmd.Valid(s, rig.Pid, rig.Src.Owner, Cmd.Rid())); } catch (Exception) { } }
                    Wait.Ms(1);
                }
            });
            spawn(delegate { while (!done) { rig.P.EnsureWorkerAlive(); Wait.Ms(0); } });
            Wait.Ms(900);
            rig.P.Dispose();
            Wait.Ms(100);
            done = true;
            foreach (Bg b in hs) b.Join(3000);
            c.Check(errors.Count == 0, "no exception escaped any hammer thread", errors.Count == 0 ? null : errors[0].GetType().Name);
            c.Check(rig.P.State == PState.Closed, "closed after the hammered Dispose", rig.P.StateName);
            c.Check(rig.P.MaxPublishersInside == 1, "max writers inside Publish == 1 under the hammer", "max=" + rig.P.MaxPublishersInside);
            c.Check(rig.P.Counter("illegal-transition") == 0, "no illegal transition under the hammer", "illegal=" + rig.P.Counter("illegal-transition"));
            string v = TraceChecker.Verify(rig.Seams.Log.Snapshot(), true);
            c.Check(v == null, "the whole writer trace obeys the endpoint order", v);
            c.Check(rig.P.Snapshot().Published >= 3, "the hammer really re-created endpoints", "endpoints=" + rig.P.Snapshot().Published);
            c.Check(Net.NameIsFree(rig.Name) && rig.Seams.OpenPorts == 0 && rig.Seams.OpenMappings == 0, "nothing of the hammered plane is left in the system");
        }

        // =====================================================================================================================================
        // ITR-04  CreateNew failure -> retry -> success with new generation / token / port
        // =====================================================================================================================================
        [Case("ITR-04", "retry after a CreateNew failure",
            Purpose = "RC-5..RC-7: with an old Reader still holding the old mapping, CreateNew fails; the plane retries safely and publishes NEW values once the handle is gone",
            Precondition = "plane 1 READY; an old-style Reader (kept handle) opened its mapping; plane 1 disposed",
            Operation = "start plane 2 on the same name; watch it for 700 ms; release the old handle",
            Expected = "RetryWaiting with attempts >= 3, never READY (independent watcher); after the release READY with another generation and token; the failed attempts left no port / mapping",
            Contract = "RC-5, RC-6, RC-7, RC-8; v2 3.3")]
        internal static void Itr04(Ctx c)
        {
            SnapView s1;
            PlaneRig p1 = ReadyRig(c, Short(), out s1);
            c.Check(s1 != null, "plane 1 READY");
            HandleHolder holder = c.Own(new HandleHolder(p1.Name));
            p1.P.Dispose();
            c.Check(p1.P.State == PState.Closed, "plane 1 closed");
            c.Check(Net.PortIsFree((int)s1.Port), "plane 1's port is closed (its port can be bound again)", "port=" + s1.Port);
            DirRead rd = new DirRead();
            DirView.Fill(rd, holder.ReadBlock());
            c.Check(rd.Valid && (rd.State & DataPlaneProtocol.Closed) != 0, "the held old mapping shows CLOSED (a Reader sees a fail-closed value)", DirView.StateName(rd.State));

            using (StateWatcher w = new StateWatcher(p1.Name))
            {
                PlaneOpts o2 = Short();
                o2.Pid = p1.Pid;
                o2.Source = p1.Src;
                PlaneRig p2 = Kit.NewRig(c, o2);
                p2.P.Start();
                Wait.Ms(700);
                SnapView mid = null;
                Wait.For(delegate { mid = p2.P.Snapshot(); return mid.State == PState.RetryWaiting; }, 2000);      // an attempt in progress shows Publishing for a moment: sample a retry-waiting moment
                c.Check(mid.State == PState.RetryWaiting, "plane 2 keeps the safe retry state while CreateNew fails", PState.Name(mid.State));
                c.Check(mid.Attempts >= 3, "plane 2 keeps retrying (does not give up)", "attempts=" + mid.Attempts);
                c.Check(mid.Published == 0 && mid.Port == 0, "plane 2 published nothing and holds no endpoint", "published=" + mid.Published);
                c.Check(w.ReadyPolls == 0, "no READY was ever observed during the failure (independent watcher)", "readyPolls=" + w.ReadyPolls + " polls=" + w.Polls);
                c.Check(Wait.For(delegate { return p2.Seams.OpenPorts == 0 && p2.Seams.OpenMappings == 0; }, 2000), "every failed attempt released its own port (between two attempts none is open; a leak would keep growing)", "ports=" + p2.Seams.OpenPorts + " binds=" + p2.Seams.BindCalls);
                c.Check(p2.Seams.BindCalls >= 3, "each attempt binds a NEW port", "binds=" + p2.Seams.BindCalls);
                holder.Dispose();
                SnapView s2 = Kit.AwaitReady(p2.P, 5000);
                c.Check(s2 != null, "plane 2 becomes READY after the old handle is released");
                if (s2 != null)
                {
                    c.Check(s2.Generation != s1.Generation, "new generation", s1.Generation + " -> " + s2.Generation);
                    c.Check(s2.TokenHex != s1.TokenHex, "new token");
                    c.Check(p2.Seams.PortNumbers[p2.Seams.PortNumbers.Count - 1] == (int)s2.Port && p2.Seams.OpenPorts == 1, "the READY endpoint owns the newest port and is the only one open");
                    DirRead r = DirView.Poll(p1.Name);
                    c.Check(r.Ready && r.Generation == s2.Generation && r.Caps == 4U, "the Directory shows plane 2's READY with REQUEST_ID only", DirView.StateName(r.State) + " caps=" + r.Caps);
                }
                c.Check(w.ReadyPolls > 0, "the watcher sees READY only after the release");
                p2.P.Dispose();
                string v = TraceChecker.Verify(p2.Seams.Log.Snapshot(), true);
                c.Check(v == null, "plane 2 writer trace valid (failed attempts left nothing behind)", v);
            }
        }

        /// <summary>The first CreateNew of a plane succeeded and was the only one: judged from the CreateNew record alone (one call, one success, no failure). The generic attempt counter is not used.</summary>
        private static bool CreatedAtOnce(PlaneRig p, SnapView s)
        {
            CreateRec[] crs = p.Seams.CreateSnapshot();
            return s != null && crs.Length == 1 && crs[0].Ok && p.Seams.CreateOk == 1 && p.Seams.CreateFailed == 0 && p.Seams.CreateCalls == 1;
        }
        // =====================================================================================================================================
        // ITR-05  Reader holds no handle (C# Reader, retaining reader as the negative control; the managed-application product Reader is judged in tests/*_2a.py)
        // =====================================================================================================================================
        [Case("ITR-05", "Reader holds no mapping handle",
            Purpose = "RC-2: an idle Reader keeps no handle, so the Writer can re-create at any time; the handle is released on READY / WITHDRAWING / CLOSED / decode failure / ownership mismatch",
            Precondition = "the C# Reader (open, read, close), a retaining Reader as the negative control; the product managed-application Reader is judged by the managed-application tests",
            Operation = "6 cycles poll -> Dispose -> CreateNew; WITHDRAWING / CLOSED / garbage / foreign-pid / CLOSED-block polls; a retaining Reader",
            Expected = "every re-creation succeeds at the FIRST attempt; the retaining Reader reproduces the failure until it closes",
            Contract = "RC-1, RC-2, RC-3, RC-4; Reader contract")]
        internal static void Itr05(Ctx c)
        {
            int pid = c.NewPid();
            FakeSource src = FakeSource.Make(pid);
            int firstTry = 0, cycles = 6;
            for (int i = 1; i <= cycles; i++)
            {
                ManualResetEvent atWithdrawing = new ManualResetEvent(false);
                ManualResetEvent release = new ManualResetEvent(false);
                bool tearing = false;
                PlaneOpts o = Short();
                o.Pid = pid;
                o.Source = src;
                if (i == 1)
                {
                    o.Hooks = delegate (SeamHooks h)
                    {
                        h.AfterPublish = delegate (UInt32 st) { if (tearing && st == 7U) { atWithdrawing.Set(); release.WaitOne(5000); } };
                    };
                }
                SnapView s;
                PlaneRig p = ReadyRig(c, o, out s);
                // The first CreateNew (the mapping) must succeed. Only the CreateNew record counts: one call, one success, no failure. A bind that the plane gave up BEFORE any mapping
                // because the operating system handed it a fixed product port is not a CreateNew and is not in this record; the generic attempt counter is not used.
                if (CreatedAtOnce(p, s)) firstTry++;
                else c.Info("cycle " + i + ": the first CreateNew did not succeed at once: calls=" + p.Seams.CreateCalls + " ok=" + p.Seams.CreateOk + " failed=" + p.Seams.CreateFailed + " (attempts=" + (s == null ? -1 : s.Attempts) + ", information only)");
                DirRead r = DirView.Poll(p.Name);
                c.Check(r.Ready && s != null && r.Generation == s.Generation && r.TokenHex == s.TokenHex && r.Caps == 4U, "cycle " + i + ": the Reader polls READY and the values equal the writer's (REQUEST_ID only)", DirView.StateName(r.State));
                c.Check(Net.NameIsFree(p.Name) == false, "cycle " + i + ": the mapping exists while READY");
                if (i == 1)
                {
                    tearing = true;
                    Bg d = Bg.Start(delegate { p.P.Dispose(); });
                    bool at = atWithdrawing.WaitOne(5000);
                    DirRead rw = DirView.Poll(p.Name);
                    c.Check(at && rw.Valid && rw.State == (DataPlaneProtocol.Published | DataPlaneProtocol.Ready | DataPlaneProtocol.Withdrawing), "the Reader sees WITHDRAWING and keeps no handle", DirView.StateName(rw.State));
                    release.Set();
                    d.Join(8000);
                }
                else if (i == 2)
                {
                    HandleHolder hh = new HandleHolder(p.Name);
                    p.P.Dispose();
                    DirRead rc = new DirRead();
                    DirView.Fill(rc, hh.ReadBlock());
                    c.Check(rc.Valid && rc.State == DataPlaneProtocol.Closed, "a late Reader sees the canonical CLOSED block", DirView.StateName(rc.State));
                    hh.Dispose();
                }
                else
                {
                    p.P.Dispose();
                    DirRead rm = DirView.Poll(p.Name);
                    c.Check(!rm.Found, "cycle " + i + ": the Reader sees the mapping gone", rm.Reason);
                }
                c.Check(p.P.State == PState.Closed, "cycle " + i + ": writer closed");
            }
            c.Check(firstTry == cycles, "EVERY re-creation succeeded at the first CreateNew while Readers polled between the cycles (they hold no handle)", firstTry + "/" + cycles);

            string[] kinds = new string[] { "garbage", "foreign-pid", "closed-block" };
            for (int k = 0; k < kinds.Length; k++)
            {
                string hn = Env.ProductName(c.NewPid());
                byte[] content;
                if (kinds[k] == "garbage") { content = new byte[128]; for (int i = 0; i < 128; i++) content[i] = 0xAB; }
                else if (kinds[k] == "foreign-pid") content = DataPlaneProtocol.EncodeJumpDirectory((UInt32)(pid + 4), 2U, DataPlaneProtocol.Published | DataPlaneProtocol.Ready, (UInt32)(pid + 4), 40000U, 5U, FakeSource.RandomBytes(16), 1U, 4U);
                else content = DataPlaneProtocol.EncodeJumpDirectory((UInt32)pid, 2U, DataPlaneProtocol.Closed, 0U, 0U, 0U, new byte[16], 1U, 0U);
                RawMapping raw = new RawMapping(hn, content);
                DirRead rd = DirView.Poll(hn);
                string want = kinds[k] == "garbage" ? "decode" : (kinds[k] == "foreign-pid" ? "pid" : "closed");
                bool okKind = kinds[k] == "garbage" ? !rd.Valid : (kinds[k] == "foreign-pid" ? rd.Valid && rd.BvePid != (UInt32)pid : rd.Valid && rd.State == DataPlaneProtocol.Closed);
                c.Check(okKind, "the Reader judges a " + kinds[k] + " block (" + want + ")", rd.Reason);
                raw.Dispose();
                bool again;
                try { new RawMapping(hn, content).Dispose(); again = true; } catch (IOException) { again = false; }
                c.Check(again, "after the " + kinds[k] + " poll the same name can be created again at once (the Reader released the handle)");
            }

            // negative control: a Reader that keeps its handle makes the next CreateNew fail until it closes
            SnapView sa;
            PlaneOpts oa = Short();
            oa.Pid = c.NewPid();
            PlaneRig pa = ReadyRig(c, oa, out sa);
            HandleHolder keep = new HandleHolder(pa.Name);
            pa.P.Dispose();
            PlaneOpts ob = Short();
            ob.Pid = pa.Pid;
            ob.Source = pa.Src;
            PlaneRig pb = Kit.NewRig(c, ob);
            pb.P.Start();
            // the fact to wait for is the number of FAILED CreateNew calls (the record of the CreateNew seam), not a duration and not the generic attempt counter
            bool failedThrice = Wait.For(delegate { return pb.Seams.CreateFailed >= 3; }, 5000);
            SnapView mid = pb.P.Snapshot();
            c.Check(failedThrice && pb.Seams.CreateOk == 0 && mid.State != PState.Ready && mid.Published == 0, "negative control: CreateNew keeps failing while a Reader holds the handle (the hazard is real)", PState.Name(mid.State) + " createFailed=" + pb.Seams.CreateFailed + " createOk=" + pb.Seams.CreateOk);
            keep.Dispose();
            c.Check(Kit.AwaitReady(pb.P, 5000) != null, "after the retaining Reader closes, the plane recovers by itself");
            c.Check(pb.Seams.CreateOk == 1, "exactly one CreateNew succeeded after the Reader closed (the failures stay in the failure record)", "ok=" + pb.Seams.CreateOk + " failed=" + pb.Seams.CreateFailed);

            // an existing mapping of the same name is never opened or re-used: the plane's CreateNew fails and nothing is published until the squatter is gone
            PlaneOpts oc = Short();
            oc.Pid = c.NewPid();
            string sqName = Env.ProductName(oc.Pid);
            RawMapping squatter = new RawMapping(sqName, new byte[128]);
            PlaneRig pc = Kit.NewRig(c, oc);
            pc.P.Start();
            bool refusedTwice = Wait.For(delegate { return pc.Seams.CreateFailed >= 2; }, 5000);
            SnapView sq = pc.P.Snapshot();
            c.Check(refusedTwice && pc.Seams.CreateOk == 0 && sq.State != PState.Ready && sq.Published == 0, "an existing mapping of the same name is neither opened nor re-used: CreateNew fails and nothing is published", PState.Name(sq.State) + " createFailed=" + pc.Seams.CreateFailed + " createOk=" + pc.Seams.CreateOk + " published=" + sq.Published);
            squatter.Dispose();
            SnapView after = Kit.AwaitReady(pc.P, 5000);
            c.Check(after != null && pc.Seams.CreateOk == 1, "after the squatter is gone the plane creates its own mapping (one success)", "ok=" + pc.Seams.CreateOk + " failed=" + pc.Seams.CreateFailed);
            c.Check(!CreatedAtOnce(pc, after), "a plane whose first CreateNew failed is NOT counted as created at once (negative control of the expression)", "ok=" + pc.Seams.CreateOk + " failed=" + pc.Seams.CreateFailed);
            CreateRec[] seq = pc.Seams.CreateSnapshot();
            int recFail = 0, recOk = 0;
            foreach (CreateRec cr0 in seq) { if (cr0.Ok) recOk++; else recFail++; }
            c.Check(seq.Length >= 3 && !seq[0].Ok && seq[seq.Length - 1].Ok && recOk == 1 && recOk == pc.Seams.CreateOk && recFail == pc.Seams.CreateFailed && recFail >= 2, "the CreateNew record shows the failures first and then the one success, and agrees with the counters", "records=" + seq.Length + " ok=" + recOk + " failed=" + recFail);
            DirRead dr = DirView.Poll(pc.Name);
            c.Check(after != null && dr.Ready && dr.Generation == after.Generation && dr.TokenHex == after.TokenHex, "the Directory holds the plane's own values", DirView.StateName(dr.State));

            // A refused fixed product port (the first bind claims it, deterministically) is a bind that is given up BEFORE any mapping: the plane needs two attempts but only ONE CreateNew,
            // and that CreateNew succeeds. The generic attempt counter is therefore not the CreateNew count (it was the cause of a false FAIL when the operating system handed out such a port).
            int[] refused = new int[] { Net.FixedA, Net.FixedB };
            for (int k = 0; k < refused.Length; k++)
            {
                int forcedPort = refused[k];
                int binds = 0;
                PlaneOpts od = Short();
                od.Pid = c.NewPid();
                od.Hooks = delegate (SeamHooks h) { h.VirtualPort = delegate { return Interlocked.Increment(ref binds) == 1 ? forcedPort : 0; }; };
                PlaneRig pd = Kit.NewRig(c, od);
                pd.P.Start();
                SnapView sd = Kit.AwaitReady(pd.P, 5000);
                CreateRec[] cr = pd.Seams.CreateSnapshot();
                c.Check(sd != null && sd.Attempts >= 2 && CreatedAtOnce(pd, sd),
                    "forced refused port " + (k == 0 ? "A" : "B") + ": two attempts, one CreateNew, and it succeeded (the bind retry is not a CreateNew)",
                    "attempts=" + (sd == null ? -1 : sd.Attempts) + " createCalls=" + pd.Seams.CreateCalls + " ok=" + pd.Seams.CreateOk + " failed=" + pd.Seams.CreateFailed);
            }
        }

        // =====================================================================================================================================
        // ITR-06  WITHDRAWING -> port close -> CLOSED -> mapping release
        // =====================================================================================================================================
        [Case("ITR-06", "shutdown order WITHDRAWING -> port close -> CLOSED -> release",
            Purpose = "G-2 / D0B-1 15.3: the observable order of the Directory and the datagram port during Dispose",
            Precondition = "READY plane, an independent watcher polling the mapping, a stall right after the WITHDRAWING publication",
            Operation = "Dispose; inside the stall: read the Directory, look at the recorded events, send a datagram; then let Dispose finish",
            Expected = "READY < WITHDRAWING < port close < CLOSED < mapping release; inside the stall the Directory says WITHDRAWING (not CLOSED) and the port is not yet closed",
            Contract = "D0B-1 15.3; OD-Add1 G-2; RC-1")]
        internal static void Itr06(Ctx c)
        {
            string insideState = null;
            bool portClosedInside = true;
            int insideLen = -1;
            bool tearing = false;
            PlaneRig rig = null;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h)
            {
                h.AfterPublish = delegate (UInt32 st)
                {
                    if (tearing && st == 7U)
                    {
                        DirRead r = DirView.Poll(rig.Name);
                        insideState = DirView.StateName(r.State) + (r.Valid ? "" : "(invalid)");
                        portClosedInside = rig.Seams.Log.Has("port-close");
                        insideLen = rig.Seams.Log.Count;
                        Wait.Ms(80);
                    }
                };
            };
            SnapView s;
            rig = ReadyRig(c, o, out s);
            c.Check(s != null, "READY");
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                Wait.Ms(30);
                tearing = true;
                rig.Seams.Log.Add("dispose:called");
                rig.P.Dispose();
                Wait.Ms(30);
                string seq = w.KindSequence();
                c.Info("watcher sequence: " + seq);
                int iReady = seq.IndexOf("READY", StringComparison.Ordinal);
                int iW = seq.IndexOf("WITHDRAWING", StringComparison.Ordinal);
                int iC = seq.IndexOf("CLOSED", StringComparison.Ordinal);
                c.Check(iReady >= 0 && iW > iReady, "the independent watcher saw READY then WITHDRAWING", seq);
                c.Check(iC < 0 || iC > iW, "CLOSED (if seen by the watcher) comes after WITHDRAWING", seq);
            }
            c.Check(insideState == "WITHDRAWING", "inside the stall the Directory shows WITHDRAWING (CLOSED not yet published)", insideState);
            c.Check(!portClosedInside, "inside the stall the port is not yet closed (the close comes after WITHDRAWING)");
            EventLog lg = rig.Seams.Log;
            int iPR = lg.IndexOf("publish:READY", 0), iPW = lg.IndexOf("publish:WITHDRAWING", 0), iSC = lg.IndexOf("port-close", 0), iPC = lg.IndexOf("publish:CLOSED", 0), iMD = lg.IndexOf("mapping-dispose", 0);
            c.Check(iPR >= 0 && iPR < iPW && iPW < iSC && iSC < iPC && iPC < iMD, "event order READY < WITHDRAWING < port-close < CLOSED < mapping-dispose", iPR + "," + iPW + "," + iSC + "," + iPC + "," + iMD);
            int iStopSeen = lg.IndexOf("wait:stopped", 0);
            c.Check(iStopSeen >= 0 && iStopSeen < iPW, "the worker saw the stop request (and left) BEFORE the WITHDRAWING publication: the bounded Join precedes the teardown", iStopSeen + "," + iPW);
            c.Check(TraceChecker.Verify(lg.Snapshot(), true) == null, "the whole event trace obeys the endpoint order");
            c.Check(!DirView.Poll(rig.Name).Found, "the mapping is gone after the final release (no holder)");
            c.Check(insideLen > 0, "the stall point was reached");
            c.Check(Net.PortIsFree((int)s.Port), "the port is free after Dispose");
        }

        // =====================================================================================================================================
        // ITR-07  duplicate writer refusal
        // =====================================================================================================================================
        [Case("ITR-07", "duplicate writer refusal",
            Purpose = "RC-9: a second Writer of the same name is refused and the first stays untouched; one instance owns one endpoint",
            Precondition = "plane 1 READY on the product Directory name of a synthetic PID",
            Operation = "start plane 2 on the same name; start plane 1 again; raw CreateNew",
            Expected = "plane 2 never publishes (RetryWaiting); plane 1 generation / token / state unchanged; a second Start() creates no second endpoint",
            Contract = "RC-9; v2 3.2")]
        internal static void Itr07(Ctx c)
        {
            SnapView s1;
            PlaneRig p1 = ReadyRig(c, Short(), out s1);
            c.Check(s1 != null, "writer 1 READY");
            p1.P.Start();
            p1.P.Start();
            Wait.Ms(100);
            SnapView s1b = p1.P.Snapshot();
            c.Check(s1b.Published == 1 && s1b.Generation == s1.Generation && p1.Seams.BindCalls == 1 && p1.Seams.CreateCalls == 1, "a repeated Start() on the same instance creates no second endpoint", "published=" + s1b.Published + " binds=" + p1p1Binds(p1));
            bool rawRefused = false;
            try { new RawMapping(p1.Name, new byte[128]).Dispose(); } catch (IOException) { rawRefused = true; }
            c.Check(rawRefused, "Windows: a raw CreateNew of the live name is refused");
            PlaneOpts o2 = Short();
            o2.Pid = p1.Pid;
            o2.Source = p1.Src;
            PlaneRig p2 = Kit.NewRig(c, o2);
            p2.P.Start();
            Wait.Ms(600);
            SnapView s2 = null;
            Wait.For(delegate { s2 = p2.P.Snapshot(); return s2.State == PState.RetryWaiting; }, 2000);
            c.Check(s2.State == PState.RetryWaiting && s2.Published == 0 && s2.Attempts >= 3, "writer 2 is refused and stays in RetryWaiting", PState.Name(s2.State) + " attempts=" + s2.Attempts);
            SnapView s1c = p1.P.Snapshot();
            DirRead r = DirView.Poll(p1.Name);
            c.Check(p1.P.State == PState.Ready && s1c.Generation == s1.Generation && s1c.TokenHex == s1.TokenHex && r.Ready && r.Generation == s1.Generation && r.TokenHex == s1.TokenHex,
                "writer 1 is untouched: same state, generation, token and Directory content", DirView.StateName(r.State));
            p2.P.Dispose();
            DirRead r2 = DirView.Poll(p1.Name);
            c.Check(p1.P.State == PState.Ready && r2.Ready && r2.Generation == s1.Generation, "disposing the refused writer 2 does not disturb writer 1's mapping");
            c.Check(TraceChecker.Verify(p2.Seams.Log.Snapshot(), true) == null, "writer 2 left nothing behind");
            p1.P.Dispose();
        }

        private static int p1p1Binds(PlaneRig p) { return p.Seams.BindCalls; }

        // =====================================================================================================================================
        // ITR-08  re-creation, new generation / token / port
        // =====================================================================================================================================
        [Case("ITR-08", "re-creation: new generation, new token, new port",
            Purpose = "RC-7/RC-10: 20 re-creations each publish a different generation, token and port; nothing leaks",
            Precondition = "READY plane, a continuous watcher, a Reader that keeps no handle",
            Operation = "20 x (a read exception while READY -> WITHDRAWING / close / CLOSED / release / new endpoint); check each endpoint against the previous one and against all earlier ones",
            Expected = "21 distinct generations / tokens / ports, consecutive values differ, one port + one mapping alive, handle count stable, READY never changes in place",
            Contract = "RC-7, RC-10; D0B-1 14")]
        internal static void Itr08(Ctx c)
        {
            int throwNext = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-read"); }; };
            GC.Collect(); GC.WaitForPendingFinalizers();
            int handlesBefore = Process.GetCurrentProcess().HandleCount;
            SnapView cur;
            PlaneRig rig = ReadyRig(c, o, out cur);
            c.Check(cur != null, "initial READY");
            HashSet<UInt32> gens = new HashSet<UInt32>();
            HashSet<string> toks = new HashSet<string>();
            gens.Add(cur.Generation); toks.Add(cur.TokenHex);
            int consecutiveEqual = 0, leak = 0, notReady = 0;
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                for (int i = 1; i <= 20; i++)
                {
                    int before = rig.P.Snapshot().Published;
                    Interlocked.Exchange(ref throwNext, 1);
                    Net.SendTo(cur.Port, new byte[] { 9, 9 });
                    if (!Wait.For(delegate { SnapView x = rig.P.Snapshot(); return x.Published > before && x.State == PState.Ready; }, 5000)) { notReady++; break; }
                    SnapView n = rig.P.Snapshot();
                    if (n.Generation == cur.Generation || n.TokenHex == cur.TokenHex || n.Port == 0) consecutiveEqual++;
                    gens.Add(n.Generation); toks.Add(n.TokenHex);
                    if (rig.Seams.OpenPorts != 1 || rig.Seams.OpenMappings != 1) leak++;
                    DirRead r = DirView.Poll(rig.Name);
                    if (!(r.Ready && r.Generation == n.Generation && n.TokenHex == r.TokenHex && r.Caps == 4U)) notReady++;
                    cur = n;
                }
                Wait.Ms(30);
                c.Check(rig.P.Counter("rc10-violation") == 0, "RC-10 (writer side): port / generation / token never change while one mapping is published", "violations=" + rig.P.Counter("rc10-violation"));
                c.Check(w.CountKind("CLOSED") + w.CountKind("WITHDRAWING") + w.CountKind("missing") > 0, "the watcher saw the withdraw phases between endpoints");
            }
            c.Check(notReady == 0, "every cycle reached READY and the Directory matched the plane", "bad=" + notReady);
            c.Check(consecutiveEqual == 0, "consecutive endpoints always differ in generation and token", "equal=" + consecutiveEqual);
            c.Check(gens.Count == 21 && toks.Count == 21, "21 distinct generations / tokens over 20 cycles", gens.Count + "/" + toks.Count);
            c.Check(rig.Seams.BindCalls >= 21 && rig.Seams.PortNumbers.Count == rig.Seams.BindCalls, "every endpoint was built on a NEW bind (no port reuse)", "binds=" + rig.Seams.BindCalls);
            c.Check(leak == 0, "exactly one port and one mapping are alive after every cycle", "leaks=" + leak);
            GC.Collect(); GC.WaitForPendingFinalizers();
            int handlesAfter = Process.GetCurrentProcess().HandleCount;
            c.Check(handlesAfter - handlesBefore <= 16, "the process handle count does not grow with the cycles", handlesBefore + " -> " + handlesAfter);
            rig.P.Dispose();
            c.Check(TraceChecker.Verify(rig.Seams.Log.Snapshot(), true) == null, "writer trace valid over all cycles");
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpPlaneTestFixture
    {
        private sealed class Fx
        {
            public PlaneRig Rig;
            public SnapView Snap;
            public FakeClock Clk;
            public FakeSource Src { get { return Rig.Src; } }
            public PlaneHandle P { get { return Rig.P; } }
        }

        /// <summary>A READY plane on an injected clock; a read exception can be armed (throwNext) to force a re-creation.</summary>
        private static Fx Ready(Ctx c, long ttl, int[] throwNext)
        {
            Fx fx = new Fx();
            fx.Clk = new FakeClock();
            PlaneOpts o = Short();
            o.Clock = fx.Clk;
            o.TtlMs = ttl;
            if (throwNext != null)
            {
                o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext[0], 0) == 1) throw new IOException("injected-read"); }; };
            }
            fx.Rig = Kit.NewRig(c, o);
            fx.Rig.P.Start();
            // The retry back-off of the plane runs on the injected clock. When the operating system hands the plane a fixed product port on a real bind, the plane refuses
            // it and waits for the back-off (the back-off values themselves are the product's and are not touched), so the clock is moved step by step while the plane is not
            // READY (as ITR-09 does). The driver is bounded in steps, in synthetic time and in real time; every step is recorded; a terminal state, a dead worker and an
            // exception end it with a reason, and the end without READY is an explicit FAIL. A READY plane never sees the clock move here.
            PlaneRig rg = fx.Rig;
            ReadyTrace tr = ReadyDriver.Drive(
                delegate { return rg.P.State; },
                delegate { return rg.P.IsWorkerAlive; },
                delegate (long ms) { fx.Clk.Advance(ms); },
                delegate { return "attempts=" + rg.P.Snapshot().Attempts + " creates=" + rg.Seams.CreateCalls + " binds=" + rg.Seams.BindCalls; },
                ReadyDriver.MaxSteps, ReadyDriver.MaxSyntheticMs, ReadyDriver.RealLimitMs, delegate { Wait.Ms(1); });
            if (tr.Steps > 1 || !tr.Reached)
            {
                c.Info("Ready(): " + (tr.Reached ? "READY" : "NOT READY") + " after " + tr.Steps + " step(s), " + tr.SyntheticMs + " ms of synthetic time (" + tr.End + ")");
                foreach (string ln in tr.Lines) c.Info("  " + ln);
            }
            if (!tr.Reached) throw new FixtureFaultException("the plane did not become READY: " + tr.End + " (last step: " + tr.Lines[tr.Lines.Count - 1] + ")");
            fx.Snap = fx.Rig.P.Snapshot();
            return fx;
        }

        private static RecView Accept(Fx fx, byte[] rid, string text)
        {
            return Kit.SendValid(fx.Rig, fx.Snap, rid, text);
        }

        private static bool AwaitState(Fx fx, byte[] rid, int state, string reason)
        {
            return Wait.For(delegate { RecView r = Kit.Find(fx.P, rid); return r != null && r.State == state && (reason == null || r.Reason == reason); }, 4000);
        }

        // =====================================================================================================================================
        // ITR-09  Queued -> Discarded
        // =====================================================================================================================================
        [Case("ITR-09", "stale command: Queued -> Discarded",
            Purpose = "N-1/N-2 (2A part): every stale cause discards the queued command so that it can never be claimed",
            Precondition = "the dedicated worker, an injected clock (the TTL is a test value; the product has none), a fake owner source",
            Operation = "TTL expiry, owner changed, owner lost, Telemetry generation change, scenario epoch, replacement, endpoint re-creation, Dispose",
            Expected = "each cause turns the command Discarded with that reason; the queue slot is empty afterwards; no illegal transition",
            Contract = "OD-Add1 6/7; v2 5.2; AIC-4/AIC-6")]
        internal static void Itr09(Ctx c)
        {
            Fx fx = Ready(c, 1000, null);
            byte[] rid = Cmd.Rid();
            RecView rec = Accept(fx, rid, Cmd.StaText);
            c.Check(rec != null && rec.State == CState.Queued, "a valid command is Queued", rec == null ? "null" : rec.Short);
            c.Check(rec != null && rec.AppInstance == fx.Src.Owner.AppInstance && rec.AppPid == fx.Src.Owner.AppProcessId && rec.ReceivedAtMs == fx.Clk.Now() && rec.ReceiverGeneration == fx.Snap.Generation
                && rec.TelemetryGeneration == fx.Src.Owner.Generation && rec.TelemetryPort == fx.Src.Owner.Port && Same(rec.TelemetryToken, fx.Src.Owner.Token) && rec.BvePid == fx.Rig.Pid,
                "the acceptance record fixes owner, Telemetry endpoint, received-at time and receiver generation");
            fx.Clk.Advance(999);
            Kit.Settle(fx.P, 4, 3000);
            c.Check(Kit.Find(fx.P, rid).State == CState.Queued, "still Queued just inside the TTL");
            fx.Clk.Advance(2);
            c.Check(AwaitState(fx, rid, CState.Discarded, "ttl"), "TTL exceeded -> Discarded(ttl)", Kit.Find(fx.P, rid).Short);
            c.Check(fx.P.Snapshot().Queued == null || fx.P.Snapshot().Queued.State != CState.Queued, "a discarded command is not in the queue slot any more (nothing can claim it)");

            fx = Ready(c, 100000, null);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            fx.Src.Owner = FakeSource.NewOwner(fx.Rig.Pid);
            c.Check(AwaitState(fx, rid, CState.Discarded, "owner-changed"), "a new AppInstance -> Discarded(owner-changed)", Kit.Find(fx.P, rid).Short);

            fx = Ready(c, 100000, null);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            fx.Src.Ok = false;
            c.Check(AwaitState(fx, rid, CState.Discarded, "owner-lost"), "AppDirectory lost -> Discarded(owner-lost)", Kit.Find(fx.P, rid).Short);

            fx = Ready(c, 100000, null);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            TelemetryEndpoint o0 = fx.Src.Owner;
            fx.Src.Owner = new TelemetryEndpoint(o0.BveProcessId, o0.AppInstance, o0.AppProcessId, o0.Port, o0.Generation + 1U, o0.Token, o0.ChangeCount + 1U, o0.Capabilities);
            c.Check(AwaitState(fx, rid, CState.Discarded, "owner-changed"), "Telemetry generation change -> Discarded(owner-changed)", Kit.Find(fx.P, rid).Short);

            fx = Ready(c, 100000, null);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            fx.P.NoteScenarioBoundary();
            c.Check(AwaitState(fx, rid, CState.Discarded, "scenario-epoch"), "scenario boundary -> Discarded(scenario-epoch)", Kit.Find(fx.P, rid).Short);

            fx = Ready(c, 100000, null);
            byte[] rid1 = Cmd.Rid(), rid2 = Cmd.Rid();
            Accept(fx, rid1, "JUMP_STA_TIME:1:36000");
            Accept(fx, rid2, "JUMP_STA_TIME:2:36000");
            c.Check(Kit.Find(fx.P, rid1).State == CState.Discarded && Kit.Find(fx.P, rid1).Reason == "replaced", "an older command is Discarded(replaced) by the newer one");
            c.Check(Kit.Find(fx.P, rid2).State == CState.Queued && fx.P.Snapshot().Queued != null && Same(fx.P.Snapshot().Queued.RequestId, rid2), "the newer command is the only Queued one (queue depth 1, newest first)");

            int[] throwNext = new int[] { 0 };
            fx = Ready(c, 100000, throwNext);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            throwNext[0] = 1;
            Net.SendTo(fx.Snap.Port, new byte[] { 7, 7, 7 });
            c.Check(AwaitState(fx, rid, CState.Discarded, "endpoint-recreated"), "endpoint re-creation -> Discarded(endpoint-recreated)", Kit.Find(fx.P, rid).Short);
            c.Check(Wait.For(delegate { fx.Clk.Advance(50); SnapView x = fx.P.Snapshot(); return x.State == PState.Ready && x.Generation != fx.Snap.Generation; }, 5000), "a NEW endpoint (other generation) is READY after the re-creation (the retry back-off runs on the injected clock, so the clock is moved)");

            fx = Ready(c, 100000, null);
            rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            fx.P.Dispose();
            RecView d = Kit.Find(fx.P, rid);
            c.Check(d.State == CState.Discarded && d.Reason == "dispose", "Dispose -> Discarded(dispose)", d.Short);
            c.Check(fx.P.Counter("illegal-transition") == 0, "no illegal transition in the Dispose scenario");
        }

        // =====================================================================================================================================
        // ITR-10  (product replacement) invalidation causes race: exactly one Discarded, no illegal transition. The claim race of the isolated test
        //         (Queued -> Executing) is NOT ported: the product has no claim (decision D-6, deferred to the 2A-beta entry tests).
        // =====================================================================================================================================
        [Case("ITR-10", "invalidation causes race: exactly one Discarded, no illegal transition (product replacement, D-6)",
            Purpose = "JT-12 (2A part): every invalidation is exclusive under the same gate; a Queued command ends Discarded exactly once whatever races; there is no Executing state",
            Precondition = "(a) the product has no claim API and no Executing state (b) racing scenario boundary / owner change / Dispose with a live worker",
            Operation = "static shape check; 160 racing rounds (130 on one plane: boundary vs owner change; 30 on fresh planes: Dispose vs boundary)",
            Expected = "exactly one Discarded transition per command, never an Executing state, illegal-transition 0; the claim race itself is deferred to 2A-beta",
            Contract = "OD-Add2 10 / JT-12; v2 AIC; decision D-6")]
        internal static void Itr10(Ctx c)
        {
            Type st = Pr.T("LegacyJumpCommandState");
            string[] names = Pr.EnumNames(st);
            Array.Sort(names, StringComparer.Ordinal);
            c.Check(string.Join(",", names) == "Discarded,Queued,Rejected", "the command state has exactly Rejected / Queued / Discarded (no Executing state)", string.Join(",", names));
            bool claimApi = false;
            foreach (System.Reflection.MethodInfo m in Pr.T("LegacyJumpControlPlane").GetMethods(System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic))
            {
                if (m.Name.IndexOf("Claim", StringComparison.OrdinalIgnoreCase) >= 0 || m.Name.IndexOf("Execut", StringComparison.OrdinalIgnoreCase) >= 0 || m.Name.IndexOf("Synthetic", StringComparison.OrdinalIgnoreCase) >= 0) claimApi = true;
            }
            c.Check(!claimApi, "the control plane has no claim / execute / synthetic API");

            int wrong = 0, rounds = 0;
            long illegalTotal = 0;
            Random rnd = new Random(12345);
            Fx fx = Ready(c, 0, null);
            for (int round = 0; round < 160; round++)
            {
                bool useDispose = round >= 130;
                if (useDispose)
                {
                    fx.P.Dispose();
                    illegalTotal += fx.P.Counter("illegal-transition");
                    fx = Ready(c, 0, null);
                }
                byte[] r = Cmd.Rid();
                RecView q = Accept(fx, r, Cmd.StaText);
                if (q == null || q.State != CState.Queued) { wrong++; continue; }
                rounds++;
                int mode = round % 2;
                long discardedBefore = SumDiscarded(fx.P);
                ManualResetEvent go = new ManualResetEvent(false);
                int delayUs = rnd.Next(0, 400);
                Bg a = Bg.Start(delegate
                {
                    go.WaitOne();
                    if (useDispose) fx.P.NoteScenarioBoundary();
                    else if (mode == 0) fx.P.NoteScenarioBoundary();
                    else fx.Src.Owner = FakeSource.NewOwner(fx.Rig.Pid);
                });
                Bg b = Bg.Start(delegate
                {
                    go.WaitOne();
                    Wait.SpinUs(delayUs);
                    if (useDispose) fx.P.Dispose();
                    else fx.P.NoteScenarioBoundary();
                });
                go.Set();
                a.Join(5000); b.Join(8000);
                Wait.For(delegate { RecView x = Kit.Find(fx.P, r); return x != null && x.State != CState.Queued; }, 4000);
                RecView fin = Kit.Find(fx.P, r);
                if (fin == null || fin.State != CState.Discarded) { wrong++; continue; }
                if (SumDiscarded(fx.P) - discardedBefore != 1) wrong++;
            }
            fx.P.Dispose();
            illegalTotal += fx.P.Counter("illegal-transition");
            c.Check(rounds >= 150, "the racing rounds really ran", "rounds=" + rounds);
            c.Check(wrong == 0, "every racing round ended with exactly one Discarded transition and a consistent record", "wrong=" + wrong);
            c.Check(illegalTotal == 0, "no illegal transition at all in the live plane", "illegal=" + illegalTotal);
            c.Info("deferred to the 2A-beta entry tests: Queued -> Executing exclusion (needs a claim)");
        }

        private static long SumDiscarded(PlaneHandle p)
        {
            long n = 0;
            string[] reasons = new string[] { "replaced", "ttl", "scenario-epoch", "owner-changed", "owner-lost", "endpoint-recreated", "dispose" };
            foreach (string r in reasons) n += p.Counter("discarded:" + r);
            return n;
        }

        // =====================================================================================================================================
        // ITR-11  read refused during Dispose
        // =====================================================================================================================================
        [Case("ITR-11", "read is refused while Dispose is in progress",
            Purpose = "shutdown step 1: after the stop request nothing is accepted; a datagram that arrives is counted as Rejected",
            Precondition = "READY plane with a live worker; a valid command is sent exactly when the worker sees the stop request (after the stop flag, before the teardown)",
            Operation = "Dispose with a valid command arriving in that window",
            Expected = "no command is accepted or queued; the datagram is counted Rejected(dispose-in-progress); nothing Queued",
            Contract = "OD-Add1 3 / shutdown 1; audit 4.2")]
        internal static void Itr11(Ctx c)
        {
            PlaneRig rig = null;
            SnapView snap = null;
            int sent = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h)
            {
                h.AfterWait = delegate (bool stopped)
                {
                    if (stopped && snap != null && Interlocked.Exchange(ref sent, 1) == 0) Net.SendTo(snap.Port, Cmd.Valid(snap, rig.Pid, rig.Src.Owner, Cmd.Rid()));
                };
            };
            rig = ReadyRig(c, o, out snap);
            c.Check(snap != null, "READY");
            rig.P.Dispose();
            RecView[] outs = rig.P.Outcomes();
            int rej = 0, queuedCount = 0;
            foreach (RecView r in outs)
            {
                if (r.State == CState.Rejected && r.Reason == "dispose-in-progress") rej++;
                if (r.State == CState.Queued) queuedCount++;
            }
            c.Check(Thread.VolatileRead(ref sent) == 1, "the datagram was sent inside the Dispose window", "sent=" + sent);
            c.Check(rej == 1, "it is counted as Rejected(dispose-in-progress)", "rejected=" + rej);
            c.Check(queuedCount == 0 && rig.P.Counter("queued") == 0, "nothing was accepted or queued", "queued counter=" + rig.P.Counter("queued"));
            c.Check(rig.P.Counter("rejected:dispose-in-progress") == 1, "the rejection is counted", "count=" + rig.P.Counter("rejected:dispose-in-progress"));
            c.Check(rig.P.State == PState.Closed, "closed");
            c.Check(Net.PortIsFree((int)snap.Port), "after Dispose the port is free again (nobody can read)");
        }

        // =====================================================================================================================================
        // ITR-12  REQUEST_ID only (plane side; the product managed-application client side is judged by tests/test_legacy_jump_plane_interop_2a.py through Serve-LegacyJumpPlane2A.ps1)
        // =====================================================================================================================================
        [Case("ITR-12", "REQUEST_ID only: the Directory carries no command capability",
            Purpose = "OD-Add1 7.2: with REQUEST_ID alone the managed-application client can send no Legacy Jump command; plane side: capabilities == 0x4, nothing received, no command outcome",
            Precondition = "READY product plane (production seam implementations, decorated for recording)",
            Operation = "read the Directory over the whole lifecycle; look at the plane's books while no client sends anything",
            Expected = "caps == 0x4 in READY and in every writer call, no command bit, received 0, no outcome; the managed-application half (refusal, zero datagrams) is the interop test",
            Contract = "OD-Add1 7.2 / LJI-08; current_jump_client.py command-unsupported")]
        internal static void Itr12(Ctx c)
        {
            SnapView s;
            PlaneRig rig = ReadyRig(c, Short(), out s);
            c.Check(s != null, "READY");
            DirRead dr = DirView.Poll(rig.Name);
            c.Check(dr.Ready && dr.Caps == 4U, "the Directory is READY and carries the REQUEST_ID capability only (0x4)", "caps=" + dr.Caps);
            c.Check((dr.Caps & 3U) == 0U, "no command capability bit (0x1 / 0x2) is set");
            Kit.Settle(rig.P, 5, 3000);
            SnapView after = rig.P.Snapshot();
            c.Check(after.Received == 0, "the plane received 0 datagrams while no client sent anything", "received=" + after.Received);
            c.Check(rig.P.Outcomes().Length == 0, "no command outcome exists on the plane");
            rig.P.Dispose();
            UInt32 union = 0;
            bool closedZero = true;
            foreach (PublishRec p in rig.Seams.PublishSnapshot()) { if (p.State == DataPlaneProtocol.Closed) { if (p.Caps != 0U) closedZero = false; } else union |= p.Caps; }
            c.Check(union == 4U, "every non-CLOSED Directory write of the lifecycle carried exactly 0x4", "union=" + union);
            c.Check(closedZero, "the CLOSED write carries capabilities 0");
        }

        // =====================================================================================================================================
        // ITR-13  zero Legacy API calls
        // =====================================================================================================================================
        [Case("ITR-13", "no Legacy API / BVE API call at all",
            Purpose = "LJC-06/LJC-09/STOP-7: the LegacyJump product types have no dependency that can call the Legacy API, BVE, Tick or Handshake",
            Precondition = "the product DLL with the LegacyJump types; the IL scanner has proven (self test) that it finds known calls",
            Operation = "IL scan of every LegacyJump* type (+ the shared jump types): call targets, referenced assemblies, referenced types; name scan; default values",
            Expected = "no call outside mscorlib / System / System.Core and the DLL's own LegacyJump / shared types; no Initialize / InitializeTimeAndLocation / SetTime / SetLocation; no CurrentJumpEndpoint.Create; no Tick-named member except OnHostTick; no timer / pool; TTL default 0",
            Contract = "LJC-06, LJC-09; OD-Add1 13")]
        internal static void Itr13(Ctx c)
        {
            Type plane = Pr.T("LegacyJumpControlPlane");
            Pr.T("LegacyJumpEndpoint");
            Pr.T("LegacyJumpCommandQueue");
            LegacyIlCallScan.Result scan = LegacyIlCallScan.ScanPrefix(Pr.Asm, "TSScoringPlugin.Telemetry.LegacyJump");
            c.Check(scan.TypesScanned >= 3 && scan.MethodsScanned >= 10, "the scan is not vacuous: LegacyJump types and methods were really read", scan.TypesScanned + " types, " + scan.MethodsScanned + " methods, " + scan.CallsSeen + " calls");
            List<string> badAsm = new List<string>();
            foreach (string a in scan.ExternalAssemblies) if (a != "mscorlib" && a != "System" && a != "System.Core") badAsm.Add(a);
            c.Check(badAsm.Count == 0, "the LegacyJump types reference only mscorlib / System / System.Core", string.Join(",", badAsm.ToArray()));
            string[] forbiddenMethods = new string[] { "Initialize", "InitializeTimeAndLocation", "SetTime", "SetLocation" };
            List<string> hitMethods = new List<string>();
            foreach (string call in scan.Calls) foreach (string f in forbiddenMethods) if (LegacyIlCallScan.MethodNameOf(call) == f) hitMethods.Add(call);
            c.Check(hitMethods.Count == 0, "no call to Initialize / InitializeTimeAndLocation / SetTime / SetLocation", string.Join(" | ", hitMethods.ToArray()));
            List<string> hitCreate = new List<string>();
            foreach (string call in scan.Calls) if (call.StartsWith("TSScoringPlugin.DataPlane.CurrentJumpEndpoint::")) hitCreate.Add(call);
            c.Check(hitCreate.Count == 0, "the LegacyJump types never call CurrentJumpEndpoint (Create or constructor)", string.Join(" | ", hitCreate.ToArray()));
            List<string> hitPool = new List<string>();
            foreach (string call in scan.Calls) if (call.StartsWith(Kit.TimerNs) || call.StartsWith("System.Threading.ThreadPool::") || call.StartsWith("System.Threading.Tasks.Task::")) hitPool.Add(call);
            foreach (string t in scan.ReferencedTypes) if (t.StartsWith(Kit.TimerNs) || t == "System.Threading.ThreadPool") hitPool.Add(t);
            c.Check(hitPool.Count == 0, "no timer / thread pool / task is used", string.Join(" | ", hitPool.ToArray()));
            int badNames = 0;
            foreach (string n in scan.MemberNames)
            {
                if (n == "OnHostTick") continue;
                if (System.Text.RegularExpressions.Regex.IsMatch(n, "Tick|BveHacker|BveEx|BveTypes|AtsEx|Handshake|Caller|StationIndex", System.Text.RegularExpressions.RegexOptions.IgnoreCase) || n == "AVAIL") { badNames++; c.Info("suspicious member name: " + n); }
            }
            c.Check(badNames == 0, "no type or member carries a Tick / BVE / AtsEX / Handshake / Caller / StationIndex name (OnHostTick is the one allowed name)", "bad=" + badNames);
            object tm = Pr.New(Pr.T("LegacyJumpTimings"));
            c.Check(Convert.ToInt64(Pr.Get(tm, "TtlMs")) == 0L, "the TTL has no product default: time expiry is off (decision D-2)", "ttl=" + Pr.Get(tm, "TtlMs"));
            c.Check(LegacyIlCallScan.CallsAnyOf(scan, "System.Threading.Thread::Abort") == false, "the product never aborts a thread itself");
            LegacyIlCallScan.Result whole = LegacyIlCallScan.ScanAllExcept(Pr.Asm, new string[] { "TSScoringPlugin.DataPlane.CurrentJumpEndpoint" });
            List<string> viaWhole = new List<string>();
            foreach (string call in whole.Calls) if (call.StartsWith("TSScoringPlugin.DataPlane.CurrentJumpEndpoint::")) viaWhole.Add(call);
            c.Check(whole.TypesScanned > 20 && whole.MethodsScanned > 100, "the whole-DLL scan is not vacuous", whole.TypesScanned + " types, " + whole.MethodsScanned + " methods");
            c.Check(viaWhole.Count == 0, "no type of the product DLL (host adapter included) calls CurrentJumpEndpoint.Create or its constructor", string.Join(" | ", viaWhole.ToArray()));
        }

        // =====================================================================================================================================
        // ITR-14  rollback by injected failures (RC-8)
        // =====================================================================================================================================
        [Case("ITR-14", "rollback by injected failure",
            Purpose = "RC-8: a failure at any creation point rolls port and mapping back and no Reader ever sees READY",
            Precondition = "a watcher polls the mapping continuously; a seam throws once at the named point",
            Operation = "inject at bind / createnew / publish-nonready / read-path / publish-ready; inject a read exception while READY",
            Expected = "0 READY observations before the retry succeeds; resources released between attempts; READY appears only after the successful retry; read exception withdraws properly and re-creates",
            Contract = "RC-8; v2 LJI-06")]
        internal static void Itr14(Ctx c)
        {
            string[] points = new string[] { "bind", "createnew", "publish-nonready", "read-path", "publish-ready" };
            for (int i = 0; i < points.Length; i++)
            {
                string pt = points[i];
                int fail = 1;
                PlaneRig rig = null;
                PlaneOpts o = Short();
                o.RetryMinMs = 300; o.RetryMaxMs = 300;
                o.Hooks = delegate (SeamHooks h)
                {
                    if (pt == "bind") h.OnBind = delegate { if (Interlocked.Exchange(ref fail, 0) == 1) throw new IOException("injected-" + pt); };
                    if (pt == "createnew") h.OnCreate = delegate { if (Interlocked.Exchange(ref fail, 0) == 1) throw new IOException("injected-" + pt); };
                    if (pt == "publish-nonready") h.BeforePublish = delegate (UInt32 st) { if (st == 1U && Interlocked.Exchange(ref fail, 0) == 1) throw new IOException("injected-" + pt); };
                    if (pt == "read-path") h.OnAvailable = delegate { if (rig != null && rig.P.State == PState.Publishing && Interlocked.Exchange(ref fail, 0) == 1) throw new IOException("injected-" + pt); };
                    if (pt == "publish-ready") h.BeforePublish = delegate (UInt32 st) { if (st == 3U && Interlocked.Exchange(ref fail, 0) == 1) throw new IOException("injected-" + pt); };
                };
                rig = Kit.NewRig(c, o);
                string name = rig.Name;
                using (StateWatcher w = new StateWatcher(name))
                {
                    rig.P.Start();
                    bool failed = Wait.For(delegate { return rig.P.Counter("create-failed") >= 1; }, 3000);
                    c.Check(failed, pt + ": the injected failure happened");
                    long readyAtFailure = w.ReadyPolls;
                    c.Check(readyAtFailure == 0, pt + ": no READY was observed by the watcher during the failed attempt", "readyPolls=" + readyAtFailure);
                    c.Check(rig.Seams.OpenPorts == 0 && rig.Seams.OpenMappings == 0, pt + ": the failed attempt released its port and mapping", rig.Seams.OpenPorts + "/" + rig.Seams.OpenMappings);
                    c.Check(rig.P.State == PState.RetryWaiting, pt + ": the plane is in the safe retry state", rig.P.StateName);
                    c.Check(Wait.For(delegate { return Net.NameIsFree(name); }, 250), pt + ": the mapping name is free between attempts (a Reader cannot be left on the failed mapping)");
                    SnapView s = Kit.AwaitReady(rig.P, 5000);
                    c.Check(s != null && s.Attempts >= 2, pt + ": the retry succeeded with a fresh endpoint", s == null ? "no READY" : "attempts=" + s.Attempts);
                    Wait.Ms(20);
                    c.Check(w.ReadyPolls > 0, pt + ": READY was observed only after the successful retry");
                    rig.P.Dispose();
                    c.Check(TraceChecker.Verify(rig.Seams.Log.Snapshot(), true) == null, pt + ": writer trace valid", TraceChecker.Verify(rig.Seams.Log.Snapshot(), true));
                }
            }
            int throwNext = 0;
            PlaneOpts o2 = Short();
            o2.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-read"); }; };
            SnapView a;
            PlaneRig p2 = ReadyRig(c, o2, out a);
            Interlocked.Exchange(ref throwNext, 1);
            Net.SendTo(a.Port, Cmd.Valid(a, p2.Pid, p2.Src.Owner, Cmd.Rid()));
            bool rebuilt = Wait.For(delegate { SnapView x = p2.P.Snapshot(); return x.Published >= 2 && x.State == PState.Ready; }, 5000);
            SnapView b = p2.P.Snapshot();
            c.Check(rebuilt && b.Generation != a.Generation && p2.P.Counter("step-exception") == 1, "a read exception withdraws the endpoint and publishes a NEW one", "stepEx=" + p2.P.Counter("step-exception"));
            p2.P.Dispose();
            c.Check(TraceChecker.Verify(p2.Seams.Log.Snapshot(), true) == null, "the read-exception trace is valid (WITHDRAWING -> port close -> CLOSED -> release)");
        }

        // =====================================================================================================================================
        // ITR-15  worker death and restart
        // =====================================================================================================================================
        [Case("ITR-15", "restart of a dead worker",
            Purpose = "audit 6.3 I6: if the worker dies, the host-tick liveness check restarts it; never after a stop request",
            Precondition = "READY plane with a live worker; a seam aborts the worker thread once",
            Operation = "wait until the worker is dead; call OnHostTick; send a command; Dispose; call EnsureWorkerAlive again",
            Expected = "dead -> restarted (restart count 1) and the command is accepted; after Dispose no restart and no worker thread",
            Contract = "audit 6.3 I6")]
        internal static void Itr15(Ctx c)
        {
            // The judgement rests on FACTS, not on durations: the worker identity (the thread object, the instance sequence and the restart generation the plane logs), the recorded
            // stop request, the exit and the Join of the old worker, the start of the new one, the set of live workers and the re-entry count. A thread id alone never tells two
            // workers apart (a managed id can be handed out again). Waiting is bounded and ends in a FAIL at the limit.
            int abortArm = 0;
            bool stopRecorded = false;
            bool gateNewOn = false;
            ManualResetEvent parked = new ManualResetEvent(false);
            ManualResetEvent holdOld = new ManualResetEvent(false);
            ManualResetEvent gateNew = new ManualResetEvent(false);
            PlaneRig rig = null;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h)
            {
                h.AfterWait = delegate (bool stopped)
                {
                    if (!stopped && rig != null && rig.P.State == PState.Ready && Interlocked.Exchange(ref abortArm, 0) == 1)
                    {
                        stopRecorded = true;                 // the stop request of the old worker is recorded here
                        parked.Set();
                        holdOld.WaitOne(10000);
                        Kit.AbortCurrentThread();
                    }
                };
                h.BeforeWorkerRegister = delegate { if (gateNewOn) gateNew.WaitOne(10000); };
            };
            SnapView s;
            rig = ReadyRig(c, o, out s);
            c.Check(s != null && rig.P.IsWorkerAlive, "READY with a live worker");
            Func<WorkerFact[]> facts = delegate { return WorkerFacts.Build(rig.Seams, rig.Lines()); };
            Func<Verdict> verdict = delegate { return WorkerJudge.Restart(facts(), rig.Seams.Reentries, stopRecorded); };
            WorkerFact[] f0 = facts();
            c.Info("facts before the stop: " + WorkerFacts.Describe(f0));
            c.Check(f0.Length == 1 && f0[0].Registered && !f0[0].Exited && f0[0].StartLogged && f0[0].Generation == 0, "exactly one worker (instance 1, generation 0) is recorded and alive", WorkerFacts.Describe(f0));

            // 1. the stop request is recorded while the old worker is still alive: a check at this moment is early (the exit is not there yet), and no second worker may start
            Interlocked.Exchange(ref abortArm, 1);
            bool atAbort = parked.WaitOne(5000);
            c.Check(atAbort && stopRecorded, "the stop request of the old worker is recorded (the old worker is parked at the abort point, still alive)");
            Verdict early = verdict();
            c.Check(early.Kind == VKind.Pending && early.Reason.Contains("old worker exit"), "before the exit of the old worker the verdict is PENDING (not PASS, not FAIL)", early.ToString());
            rig.P.OnHostTick(true, true);
            WorkerFact[] fp = facts();
            c.Check(fp.Length == 1 && rig.P.Snapshot().RestartCount == 0 && rig.P.IsWorkerAlive && rig.Seams.Reentries == 0, "a host tick while the old worker lives restarts nothing (no second worker, no re-entry)", WorkerFacts.Describe(fp) + " restarts=" + rig.P.Snapshot().RestartCount + " reentries=" + rig.Seams.Reentries);
            WorkerRec oldRec = rig.Seams.WorkerSnapshot()[0];

            // 2. the old worker exits; the Join is confirmed; the new worker has not been started yet: the check is early again
            holdOld.Set();
            bool exited = Wait.For(delegate { return !oldRec.T.IsAlive; }, 5000);
            bool joined = WorkerFacts.Join(rig.Seams, 1, 5000);
            c.Check(exited && joined && !rig.P.IsWorkerAlive, "the old worker exited and its Join is confirmed");
            c.Check(rig.P.State == PState.Ready, "the published endpoint is still READY while nobody services it");
            Verdict beforeStart = verdict();
            c.Check(beforeStart.Kind == VKind.Pending && beforeStart.Reason.Contains("new worker start"), "before the start of the new worker the verdict is PENDING", beforeStart.ToString());

            // 3. the restart; the new worker is held just before it is recorded: its start is logged but it is not yet a live worker of the plane
            gateNewOn = true;
            rig.P.OnHostTick(true, true);
            bool startLogged = Wait.For(delegate { WorkerFact[] x = facts(); return x.Length >= 2 && x[1].StartLogged; }, 5000);
            c.Check(startLogged, "OnHostTick (the host Tick path) restarted the worker: its start is logged");
            Verdict beforeReg = verdict();
            c.Check(beforeReg.Kind == VKind.Pending && beforeReg.Reason.Contains("not yet recorded"), "while the new worker is not yet recorded as a live worker the verdict is PENDING", beforeReg.ToString());

            // 4. the new worker is released: the verdict settles on facts
            gateNew.Set();
            AwaitResult ar = Verdicts.Await(verdict, 5000);
            foreach (string st in ar.Steps) c.Info("verdict step: " + st);
            c.Check(ar.Final.Kind == VKind.Pass, "the restart settles on recorded facts (start, exit, Join, generation, live set, re-entry)", ar.Final.ToString());
            Kit.Settle(rig.P, 3, 3000);
            Verdict again = verdict();
            c.Check(again.Kind == VKind.Pass, "the verdict still holds after the new worker has run three more iterations (no late second worker)", again.ToString());
            WorkerFact[] f1 = facts();
            c.Info("facts after the restart: " + WorkerFacts.Describe(f1));
            WorkerRec[] recs = rig.Seams.WorkerSnapshot();
            c.Check(recs.Length == 2 && !object.ReferenceEquals(recs[0].T, recs[1].T), "two distinct worker threads served the plane over its life, one after the other", "workers=" + recs.Length + " ids=" + (recs.Length > 1 ? recs[0].ManagedId + "," + recs[1].ManagedId : "-"));
            c.Check(f1.Length == 2 && f1[1].Generation == f1[0].Generation + 1, "the worker generation advanced by one", WorkerFacts.Describe(f1));
            c.Check(rig.P.Snapshot().RestartCount == 1, "exactly one restart", "restarts=" + rig.P.Snapshot().RestartCount);
            c.Check(rig.P.IsWorkerAlive && rig.Seams.Reentries == 0 && rig.P.MaxStepsInside == 1, "one live worker, no re-entry, never two steps inside at once", "reentries=" + rig.Seams.Reentries + " maxStepsInside=" + rig.P.MaxStepsInside);
            Net.SendTo(s.Port, Cmd.Valid(s, rig.Pid, rig.Src.Owner, Cmd.Rid()));
            c.Check(Wait.For(delegate { return rig.P.Snapshot().Queued != null; }, 3000), "the restarted worker services the port (the command is Queued)");

            // 5. the stop: no restart afterwards, no worker alive, no further worker recorded
            rig.P.Dispose();
            c.Check(rig.P.State == PState.Closed, "closed");
            c.Check(!rig.P.EnsureWorkerAlive(), "no restart after Dispose");
            rig.P.OnHostTick(true, true);
            AwaitResult st2 = Verdicts.Await(delegate { return WorkerJudge.Stopped(facts(), 2); }, 5000);
            c.Check(st2.Final.Kind == VKind.Pass && !rig.P.IsWorkerAlive && rig.P.Snapshot().RestartCount == 1, "no worker thread exists after Dispose (also not after a later host tick) and no further worker was recorded", st2.Final.ToString());
            c.Check(TraceChecker.Verify(rig.Seams.Log.Snapshot(), true) == null, "writer trace valid across the restart");
        }
        // =====================================================================================================================================
        // ITR-16  Join timeout
        // =====================================================================================================================================
        [Case("ITR-16", "Dispose completes in bounded time when the worker stalls",
            Purpose = "H2: a worker that does not stop must not make Dispose wait forever, and nothing is published after the stop",
            Precondition = "(A) the worker stalls OUTSIDE the gate; (B) INSIDE the gate in READY; (C) INSIDE the gate while creating the endpoint (between PUBLISHED and READY); short Join / gate bounds",
            Operation = "Dispose during the stall; release the stall afterwards",
            Expected = "Dispose returns within its bounds; (A) closed by Dispose in order; (B) closed by the worker when it leaves, in order; (C) READY is never published after the stop request, the resumed worker rolls back; no publication after the stop; no residue",
            Contract = "audit 4.3 H2; OD-Add1 G-2")]
        internal static void Itr16(Ctx c)
        {
            // (A) stall outside the gate (in the waiter, READY)
            ManualResetEvent releaseA = new ManualResetEvent(false), stalledA = new ManualResetEvent(false);
            int armedA = 1;
            PlaneRig pa = null;
            PlaneOpts oa = Short();
            oa.JoinMs = 300; oa.GateTryMs = 300;
            oa.Hooks = delegate (SeamHooks h)
            {
                h.AfterWait = delegate (bool stopped) { if (!stopped && pa != null && pa.P.State == PState.Ready && Interlocked.Exchange(ref armedA, 0) == 1) { stalledA.Set(); releaseA.WaitOne(15000); } };
            };
            SnapView sa;
            pa = ReadyRig(c, oa, out sa);
            c.Check(sa != null && stalledA.WaitOne(5000), "(A) READY and the worker is stalled outside the gate");
            Stopwatch swA = Stopwatch.StartNew();
            pa.Seams.Log.Add("dispose:called");
            pa.P.Dispose();
            long msA = swA.ElapsedMilliseconds;
            c.Check(msA < 2500, "(A) Dispose returned within its bounds although the worker did not stop", "elapsed=" + msA + " ms");
            c.Check(msA >= 250, "(A) the bounded Join really timed out (as injected)", "elapsed=" + msA + " ms");
            c.Check(pa.P.State == PState.Closed && Net.NameIsFree(pa.Name), "(A) Dispose itself completed the shutdown (CLOSED, mapping released)", pa.P.StateName);
            int lenAtReturn = pa.Seams.Log.Count;
            releaseA.Set();
            c.Check(Wait.For(delegate { return !pa.P.IsWorkerAlive; }, 5000), "(A) the late worker leaves after the release");
            Wait.Ms(50);
            string[] tA2 = pa.Seams.Log.Snapshot();
            bool publishAfter = false;
            for (int i = lenAtReturn; i < tA2.Length; i++) if (EventLog.NameOf(tA2[i]).StartsWith("publish:")) publishAfter = true;
            c.Check(!publishAfter, "(A) the late worker published NOTHING after the stop");
            c.Check(TraceChecker.Verify(tA2, true, "dispose:called") == null, "(A) writer trace valid, nothing published or made ready after the stop request", TraceChecker.Verify(tA2, true, "dispose:called"));

            // (B) stall inside the gate (in the clock, READY)
            ManualResetEvent releaseB = new ManualResetEvent(false), stalledB = new ManualResetEvent(false);
            int armedB = 0;
            PlaneRig pb = null;
            PlaneOpts ob = Short();
            ob.JoinMs = 300; ob.GateTryMs = 250;
            ob.Hooks = delegate (SeamHooks h)
            {
                h.OnClock = delegate { if (pb != null && pb.P.State == PState.Ready && Interlocked.Exchange(ref armedB, 0) == 1) { stalledB.Set(); releaseB.WaitOne(15000); } };
            };
            SnapView sb;
            pb = ReadyRig(c, ob, out sb);
            Interlocked.Exchange(ref armedB, 1);
            c.Check(sb != null && stalledB.WaitOne(5000), "(B) READY and the worker is stalled INSIDE the gate");
            Stopwatch swB = Stopwatch.StartNew();
            pb.Seams.Log.Add("dispose:called");
            pb.P.Dispose();
            long msB = swB.ElapsedMilliseconds;
            c.Check(msB < 3000, "(B) Dispose returned within its bounds although the gate is held by the stalled worker", "elapsed=" + msB + " ms");
            c.Check(pb.P.State != PState.Closed && !Net.NameIsFree(pb.Name), "(B) both bounded gate acquisitions timed out: the teardown is left to the worker (the mapping still exists)", pb.P.StateName);
            bool pubB = false;
            string[] tB = pb.Seams.Log.Snapshot();
            int idxCalled = pb.Seams.Log.IndexOf("dispose:called", 0);
            for (int i = idxCalled; i < tB.Length; i++) { string n = EventLog.NameOf(tB[i]); if (n == "publish:PUBLISHED" || n == "publish:READY") pubB = true; }
            c.Check(!pubB, "(B) no PUBLISHED / READY was written after the stop request while the gate was blocked");
            releaseB.Set();
            c.Check(Wait.For(delegate { return pb.P.State == PState.Closed; }, 8000), "(B) the worker completed the teardown itself when it left (orphan teardown)", pb.P.StateName);
            c.Check(Wait.For(delegate { return !pb.P.IsWorkerAlive; }, 5000), "(B) the worker thread ended");
            string[] tB2 = pb.Seams.Log.Snapshot();
            c.Check(TraceChecker.Verify(tB2, true, "dispose:called") == null, "(B) the late teardown kept the order WITHDRAWING -> port close -> CLOSED -> release", TraceChecker.Verify(tB2, true, "dispose:called"));
            c.Check(Net.NameIsFree(pb.Name) && pb.Seams.OpenPorts == 0 && pb.Seams.OpenMappings == 0, "(B) no mapping / port residue");

            // (C) the worker stalls INSIDE the gate while it is CREATING the endpoint (between PUBLISHED and READY): the read-path check is the last point before the stop check
            ManualResetEvent releaseC = new ManualResetEvent(false), stalledC = new ManualResetEvent(false);
            int armedC = 1;
            PlaneRig pc = null;
            PlaneOpts oc = Short();
            oc.JoinMs = 300; oc.GateTryMs = 250;
            oc.Hooks = delegate (SeamHooks h)
            {
                h.OnAvailable = delegate { if (pc != null && pc.P.State == PState.Publishing && Interlocked.Exchange(ref armedC, 0) == 1) { stalledC.Set(); releaseC.WaitOne(15000); } };
            };
            pc = Kit.NewRig(c, oc);
            pc.P.Start();
            c.Check(stalledC.WaitOne(5000), "(C) the worker is stalled inside the gate between PUBLISHED and READY");
            DirRead mid = DirView.Poll(pc.Name);
            c.Check(mid.Valid && mid.State == DataPlaneProtocol.Published, "(C) the Directory shows PUBLISHED (not READY) during the stall", DirView.StateName(mid.State));
            Stopwatch swC = Stopwatch.StartNew();
            pc.Seams.Log.Add("dispose:called");
            pc.P.Dispose();
            c.Check(swC.ElapsedMilliseconds < 3000, "(C) Dispose returned within its bounds", "elapsed=" + swC.ElapsedMilliseconds + " ms");
            c.Check(pc.P.State != PState.Closed, "(C) the gate was really unavailable to Dispose (the worker owns the teardown)", pc.P.StateName);
            releaseC.Set();
            c.Check(Wait.For(delegate { return pc.P.State == PState.Closed; }, 8000), "(C) the resumed worker rolled back and completed the teardown", pc.P.StateName);
            c.Check(Wait.For(delegate { return !pc.P.IsWorkerAlive; }, 5000), "(C) the worker thread ended");
            string[] tC = pc.Seams.Log.Snapshot();
            c.Check(!pc.Seams.Log.Has("publish:READY"), "(C) READY was NEVER published although the stop request came before the stalled worker resumed");
            c.Check(TraceChecker.Verify(tC, true, "dispose:called") == null, "(C) writer trace valid; nothing published after the stop request", TraceChecker.Verify(tC, true, "dispose:called"));
            c.Check(Net.NameIsFree(pc.Name) && !DirView.Poll(pc.Name).Found && pc.Seams.OpenPorts == 0 && pc.Seams.OpenMappings == 0, "(C) no mapping / port residue");
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpPlaneTestFixture
    {
        // =====================================================================================================================================
        // EX-01  command contract matrix (Rejected / Queued / Discarded)
        // =====================================================================================================================================
        [Case("EX-01", "command contract matrix",
            Purpose = "section 10 of the work order: every validation item has a final state (Rejected / Queued / Discarded); nothing reaches a Legacy API",
            Precondition = "the dedicated worker, a fake owner source, an injected clock",
            Operation = "garbage, bad magic, zero request id, telemetry type, foreign BVE PID, foreign AppInstance, foreign sender PID, wrong generation, wrong token, bad payload, unresolved owner, duplicate id, valid, replacement",
            Expected = "each hostile datagram ends Rejected with its stable reason; a valid one Queued; a duplicate Rejected; the older one Discarded(replaced)",
            Contract = "work order 10; v2 AIC-2 / AIC-3; V04, V07..V13 of the Current validator")]
        internal static void Ex01(Ctx c)
        {
            Fx fx = Ready(c, 100000, null);
            SnapView s = fx.Snap;
            TelemetryEndpoint ow = fx.Src.Owner;
            UInt32 pid = (UInt32)fx.Rig.Pid;
            byte[] tok = s.Token;
            byte[] good = Cmd.Rid();
            byte[] badMagic = Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, Cmd.Rid(), Cmd.StaText);
            badMagic[0] ^= 0xFF;
            byte[] otherTok = FakeSource.RandomBytes(16);
            byte[] valid = Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, good, Cmd.StaText);
            List<KeyValuePair<string, KeyValuePair<byte[], string>>> cases = new List<KeyValuePair<string, KeyValuePair<byte[], string>>>();
            Action<string, byte[], string> add = delegate (string n, byte[] d, string reason) { cases.Add(new KeyValuePair<string, KeyValuePair<byte[], string>>(n, new KeyValuePair<byte[], string>(d, reason))); };
            add("garbage (10 bytes)", new byte[10], "envelope-size");
            add("bad magic", badMagic, "envelope-magic");
            add("zero RequestId on a command", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, new byte[16], Cmd.StaText), "envelope-request-id");
            add("telemetry MessageType (1) is not a command", Cmd.Envelope(1U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, new byte[16], "x"), "message-type-not-allowed");
            add("foreign BVE PID", Cmd.Envelope(0x100U, pid + 4U, ow.AppProcessId, s.Generation, ow.AppInstance, tok, Cmd.Rid(), Cmd.StaText), "bve-pid-mismatch");
            add("foreign AppInstance", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, FakeSource.RandomInstance(), tok, Cmd.Rid(), Cmd.StaText), "app-instance-mismatch");
            add("foreign sender (App) PID", Cmd.Envelope(0x100U, pid, ow.AppProcessId + 4U, s.Generation, ow.AppInstance, tok, Cmd.Rid(), Cmd.StaText), "sender-pid-mismatch");
            add("wrong generation", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation + 1U, ow.AppInstance, tok, Cmd.Rid(), Cmd.StaText), "generation-mismatch");
            add("wrong token", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, otherTok, Cmd.Rid(), Cmd.StaText), "token-mismatch");
            add("bad payload grammar", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, Cmd.Rid(), "JUMP_STA_TIME:x:1"), "payload-grammar");
            add("location text on the station type", Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, Cmd.Rid(), "JUMP_LOC_TIME:1.5:36000"), "payload-grammar");
            foreach (KeyValuePair<string, KeyValuePair<byte[], string>> k in cases)
            {
                RecView last = Kit.SendAndAwait(fx.Rig, s, k.Value.Key, 4000);
                bool ok = last != null && last.State == CState.Rejected && last.Reason == k.Value.Value;
                c.Check(ok, "Rejected(" + k.Value.Value + "): " + k.Key, last == null ? "no outcome" : last.Short);
            }
            RecView q = Kit.SendAndAwait(fx.Rig, s, valid, 4000);
            c.Check(q != null && q.State == CState.Queued && q.Reason == null, "a valid command ends Queued", q == null ? "none" : q.Short);
            c.Check(q != null && q.MessageType == 0x100U && q.Text == Cmd.StaText && Same(q.RequestId, good), "the record keeps type, text and RequestId (opaque to 2A-alpha)");
            RecView dup = Kit.SendAndAwait(fx.Rig, s, valid, 4000);
            c.Check(dup != null && dup.State == CState.Rejected && dup.Reason == "duplicate-request-id", "the same RequestId again ends Rejected(duplicate-request-id)", dup == null ? "none" : dup.Short);
            c.Check(fx.P.Snapshot().Queued != null && Same(fx.P.Snapshot().Queued.RequestId, good), "the duplicate did not disturb the Queued command");
            byte[] second = Cmd.Rid();
            RecView sec = Accept(fx, second, "JUMP_STA_TIME:2:36000");
            RecView first = Kit.Find(fx.P, good);
            c.Check(sec != null && sec.State == CState.Queued && first.State == CState.Discarded && first.Reason == "replaced", "the older Queued command ends Discarded(replaced) by the newer", first.Short);
            int nQ = 0, nR = 0, nD = 0, nE = 0;
            foreach (RecView r in fx.P.Outcomes())
            {
                if (r.State == CState.Queued) nQ++;
                else if (r.State == CState.Rejected) nR++;
                else if (r.State == CState.Discarded) nD++;
                else nE++;
            }
            c.Check(nQ == 1 && nD == 1 && nE == 0 && nR == cases.Count + 1, "final state census: 1 Queued, 1 Discarded, nothing else, the rest Rejected", "Q=" + nQ + " D=" + nD + " other=" + nE + " R=" + nR);
            fx.Src.Ok = false;
            RecView un = Kit.SendAndAwait(fx.Rig, s, Cmd.Envelope(0x100U, pid, ow.AppProcessId, s.Generation, ow.AppInstance, tok, Cmd.Rid(), Cmd.StaText), 4000);
            c.Check(un != null && un.State == CState.Rejected && un.Reason == "owner-" + fx.Src.FailReason, "an unresolvable owner ends Rejected(owner-...)", un == null ? "none" : un.Short);
            c.Check(Wait.For(delegate { RecView x = Kit.Find(fx.P, second); return x != null && x.State == CState.Discarded && x.Reason == "owner-lost"; }, 4000), "...and the Queued command is Discarded(owner-lost) at the same time");
            fx.Src.Ok = true;
            c.Check(fx.P.Counter("illegal-transition") == 0, "no illegal transition");
        }

        // =====================================================================================================================================
        // EX-02  REQUEST_ID capability only
        // =====================================================================================================================================
        [Case("EX-02", "REQUEST_ID is the only capability ever published",
            Purpose = "OD-LJ-F / LJC-07: 0x4 only, 0x1 and 0x2 never appear in any state of the Directory",
            Precondition = "a continuous watcher over a full lifecycle incl. re-creation and Dispose",
            Operation = "create, re-create twice, dispose",
            Expected = "the union of all observed capability values is exactly 0x4; CLOSED carries 0; the writer calls agree",
            Contract = "OD-Add1 11 (OD-LJ-F); LJC-07")]
        internal static void Ex02(Ctx c)
        {
            int throwNext = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-read"); }; };
            PlaneRig rig = Kit.NewRig(c, o);
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                rig.P.Start();
                SnapView s = Kit.AwaitReady(rig.P, 5000);
                for (int i = 0; i < 2; i++)
                {
                    int before = rig.P.Snapshot().Published;
                    Interlocked.Exchange(ref throwNext, 1);
                    Net.SendTo(rig.P.Snapshot().Port, new byte[] { 5 });
                    Wait.For(delegate { SnapView x = rig.P.Snapshot(); return x.Published > before && x.State == PState.Ready; }, 5000);
                }
                rig.P.Dispose();
                Wait.Ms(30);
                c.Check(s != null && w.CapsUnion == 4U, "the union of all observed capabilities is exactly REQUEST_ID (0x4)", "union=" + w.CapsUnion);
                bool closedZero = true;
                foreach (StateWatcher.Obs ob in w.Snapshot()) if (ob.Kind == "CLOSED" && ob.Caps != 0U) closedZero = false;
                c.Check(closedZero, "a CLOSED block carries capabilities 0");
                c.Check(w.CountKind("READY") >= 1, "READY states were observed", w.KindSequence());
            }
            UInt32 union = 0;
            foreach (PublishRec p in rig.Seams.PublishSnapshot()) if (p.State != DataPlaneProtocol.Closed) union |= p.Caps;
            c.Check(union == 4U && rig.Seams.PublishSnapshot().Length >= 6, "every Directory write the plane made (3 endpoints) asked for capabilities 0x4 only", "union=" + union + " writes=" + rig.Seams.PublishSnapshot().Length);
            Type jc = Pr.TS("JumpCapabilities");
            UInt32 reqId = Convert.ToUInt32(Pr.GetStatic(jc, "RequestId"));
            UInt32 sta = Convert.ToUInt32(Pr.GetStatic(jc, "StationTime")), loc = Convert.ToUInt32(Pr.GetStatic(jc, "LocationTime"));
            c.Check(reqId == 4U && (reqId & (sta | loc)) == 0U, "the shared constant RequestId is 0x4 and is disjoint from the command bits");
        }

        // =====================================================================================================================================
        // EX-03  isolation of names, PIDs and ports (product version)
        // =====================================================================================================================================
        [Case("EX-03", "names, PID, ports and defaults",
            Purpose = "work order 5 (product version): the Legacy name is the product name of a synthetic PID, never the Current name; no fixed port; defaults pinned",
            Precondition = "the run id and the synthetic BVE PIDs of this run",
            Operation = "inspect the names, the never-bind ports and the timing defaults; force the fixed ports at the first bind and at a re-creation (both ports); real-bind cycles; IL send scan",
            Expected = "the name ends with .LegacyJump and never contains .CurrentJump; the synthetic PID is odd and not a live process; NeverBindPorts = the Telemetry port and the one above it; defaults 20 / 1000 / 1000 / 250 / 2000 / 32 / TTL 0; a claimed fixed port is closed before any mapping, never published, never sent to, and the retry has a new port / generation / token",
            Contract = "work order 5; STOP-4; plan 8")]
        internal static void Ex03(Ctx c)
        {
            int pid = c.NewPid();
            string n = (string)Pr.CallStatic(Pr.T("LegacyJumpNames"), "For", pid);
            c.Check(n == Env.ProductName(pid), "LegacyJumpNames.For(pid) is Local\\TSScoringPlugin.v1.<pid>.LegacyJump", n);
            c.Check(n.EndsWith(".LegacyJump") && n.IndexOf(".CurrentJump", StringComparison.Ordinal) < 0, "the suffix is .LegacyJump and the Current name is not contained");
            c.Check(n != DataPlaneProtocol.JumpName((UInt32)pid), "it is not the Current Directory name of the same PID");
            c.Check(pid % 2 == 1 && pid >= 2100000001, "the synthetic PID is odd and huge, so it can never be a real Windows PID (those are multiples of 4)", pid.ToString());
            bool live = true;
            try { Process.GetProcessById(pid); } catch (ArgumentException) { live = false; }
            c.Check(!live, "no live process has the synthetic PID");
            bool threw = false;
            try { Pr.CallStatic(Pr.T("LegacyJumpNames"), "For", 0); } catch (ArgumentOutOfRangeException) { threw = true; }
            c.Check(threw, "a non-positive PID is refused");
            int[] never = (int[])Pr.GetStatic(Pr.T("LegacyJumpEndpoint"), "NeverBindPorts");
            List<int> nl = new List<int>(never);
            nl.Sort();
            c.Check(nl.Count == 2 && nl[0] == Net.FixedA && nl[1] == Net.FixedB, "NeverBindPorts is exactly the two fixed product ports (Telemetry port and the one above it)", string.Join(",", nl.ConvertAll<string>(delegate (int x) { return x.ToString(); }).ToArray()));
            object tm = Pr.New(Pr.T("LegacyJumpTimings"));
            string d = Pr.Get(tm, "PollMs") + "/" + Pr.Get(tm, "JoinMs") + "/" + Pr.Get(tm, "GateTryMs") + "/" + Pr.Get(tm, "RetryMinMs") + "/" + Pr.Get(tm, "RetryMaxMs") + "/" + Pr.Get(tm, "MaxDatagramsPerStep") + "/" + Pr.Get(tm, "TtlMs");
            c.Check(d == "20/1000/1000/250/2000/32/0", "the product default timings are 20 / 1000 / 1000 / 250 / 2000 / 32 and no TTL, independent of the tests", d);
            object env = Pr.CallStatic(Pr.T("LegacyJumpEnvironment"), "Production", pid, null);
            object ptm = Pr.Get(env, "Timings");
            c.Check(Convert.ToInt32(Pr.Get(ptm, "PollMs")) == 20 && Convert.ToInt64(Pr.Get(ptm, "TtlMs")) == 0L, "Production() hands out the default timings (poll 20 ms, no TTL)");
            // The fixed ports are judged by what a plane PUBLISHES and SENDS, never by what the operating system handed out on a bind: a bind on port 0 may legitimately return
            // one of the two product ports (plan 6.4), and the product then refuses it before any mapping exists. The refusal is forced here deterministically.
            Ex03ForcedAtStart(c, Net.FixedA, "the Telemetry port");
            Ex03ForcedAtStart(c, Net.FixedB, "the Telemetry port + 1");
            Ex03ForcedAtRecreate(c, Net.FixedA, "the Telemetry port");
            Ex03ForcedAtRecreate(c, Net.FixedB, "the Telemetry port + 1");
            Ex03RealCycles(c, 12);
            LegacyIlCallScan.Result scan = LegacyIlCallScan.ScanPrefix(Pr.Asm, "TSScoringPlugin.Telemetry.LegacyJump");
            int sends = 0;
            foreach (string call in scan.Calls)
            {
                string mn = LegacyIlCallScan.MethodNameOf(call);
                if (mn == "Send" || mn == "SendTo" || mn == "BeginSend" || mn == "SendAsync") sends++;
            }
            c.Check(scan.TypesScanned >= 3 && scan.MethodsScanned >= 10 && sends == 0, "the LegacyJump types contain no send call at all, so nothing can be sent to a fixed product port", "types=" + scan.TypesScanned + " methods=" + scan.MethodsScanned + " sends=" + sends);
            c.Check(Net.FixedSendsRefused == 0, "no test of this run tried to send to a fixed product port (the senders of the kit refuse them and count the attempt)", "refused=" + Net.FixedSendsRefused);
        }

        private static bool AnyFixed(PlaneRig rig)
        {
            foreach (PublishRec p in rig.Seams.PublishSnapshot()) if (Net.IsFixedPort((int)p.Port)) return true;
            return false;
        }

        private static bool WatcherSawFixed(StateWatcher w)
        {
            foreach (StateWatcher.Obs ob in w.Snapshot()) if (Net.IsFixedPort((int)ob.Port)) return true;
            return false;
        }

        /// <summary>The very first bind is answered with a fixed product port (a double that only CLAIMS the number, nothing is bound there).</summary>
        private static void Ex03ForcedAtStart(Ctx c, int fixedPort, string what)
        {
            string tag = what + " (" + fixedPort + ") at the first bind: ";
            int binds = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.VirtualPort = delegate { return Interlocked.Increment(ref binds) == 1 ? fixedPort : 0; }; };
            PlaneRig rig = Kit.NewRig(c, o);
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                rig.P.Start();
                SnapView s = Kit.AwaitReady(rig.P, 5000);
                c.Check(s != null, tag + "the plane retries and becomes READY on another port");
                if (s != null)
                {
                    c.Check(!Net.IsFixedPort((int)s.Port) && s.Port != 0U, tag + "the READY port is not a fixed product port", "port=" + s.Port);
                    c.Check(s.Attempts >= 2 && rig.P.Counter("create-failed") >= 1, tag + "the claimed port ended the attempt and a retry followed", "attempts=" + s.Attempts + " failed=" + rig.P.Counter("create-failed"));
                    DirRead dr = DirView.Poll(rig.Name);
                    c.Check(dr.Ready && dr.Port == s.Port && dr.Caps == 4U, tag + "the Directory is READY on the retry port with REQUEST_ID only", DirView.StateName(dr.State) + " port=" + dr.Port);
                    RecView q = Kit.SendValid(rig, s, Cmd.Rid(), Cmd.StaText);
                    c.Check(q != null && q.State == CState.Queued, tag + "a command is accepted on the retry port only", q == null ? "none" : q.Short);
                }
                EventLog lg = rig.Seams.Log;
                int iVirt = lg.IndexOf("bind:virtual:" + fixedPort, 0);
                int iClose = iVirt < 0 ? -1 : lg.IndexOf("port-close", iVirt);
                int iCreate = lg.IndexOf("createnew", 0);
                int iPub = lg.IndexOf("publish:PUBLISHED", 0);
                c.Check(iVirt >= 0 && iClose > iVirt && iCreate > iClose && iPub > iCreate, tag + "claimed, closed, and only then a mapping is created and published", iVirt + "," + iClose + "," + iCreate + "," + iPub);
                c.Check(rig.Seams.CreateCalls == 1 && rig.Seams.BindCalls >= 2, tag + "no mapping was created for the refused attempt", "creates=" + rig.Seams.CreateCalls + " binds=" + rig.Seams.BindCalls);
                List<int> pa = new List<int>(rig.Seams.PortNumbers);
                c.Check(pa.Count >= 2 && pa[0] == fixedPort && pa[pa.Count - 1] != fixedPort, tag + "the retry is a NEW bind and the last bind (the published one) is not the fixed port", string.Join(",", pa.ConvertAll<string>(delegate (int x) { return x.ToString(); }).ToArray()));
                c.Check(!AnyFixed(rig) && !WatcherSawFixed(w), tag + "no Directory write and no Directory observation ever named the fixed port");
                c.Check(w.ReadyPolls > 0, tag + "the independent watcher saw READY only on the retry port");
                rig.P.Dispose();
                c.Check(rig.Seams.Log.CountOf("port-close") == pa.Count && rig.Seams.OpenPorts == 0 && rig.Seams.OpenMappings == 0, tag + "every bound port (the refused one included) is closed, nothing is left open", "closes=" + rig.Seams.Log.CountOf("port-close") + " binds=" + pa.Count);
                string tv = TraceChecker.Verify(rig.Seams.Log.Snapshot(), true);
                bool gone = Wait.For(delegate { return Net.NameIsFree(rig.Name); }, 2000);
                c.Check(gone && tv == null, tag + "mapping gone and the writer trace obeys the endpoint order", "gone=" + gone + " trace=" + tv + (tv == null ? "" : " events=" + rig.Seams.Log.Names()));
            }
        }

        /// <summary>A READY endpoint is re-created, and the bind of the re-creation is answered with a fixed product port.</summary>
        private static void Ex03ForcedAtRecreate(Ctx c, int fixedPort, string what)
        {
            string tag = what + " (" + fixedPort + ") at the re-creation: ";
            int binds = 0, throwNext = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h)
            {
                h.VirtualPort = delegate { return Interlocked.Increment(ref binds) == 2 ? fixedPort : 0; };
                h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-read"); };
            };
            PlaneRig rig = Kit.NewRig(c, o);
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                rig.P.Start();
                SnapView s1 = Kit.AwaitReady(rig.P, 5000);
                c.Check(s1 != null, tag + "first endpoint READY");
                if (s1 == null) return;
                Interlocked.Exchange(ref throwNext, 1);
                Net.SendTo(s1.Port, new byte[] { 9, 9 });
                bool again = Wait.For(delegate { SnapView x = rig.P.Snapshot(); return x.Published >= 2 && x.State == PState.Ready; }, 5000);
                SnapView s2 = rig.P.Snapshot();
                c.Check(again, tag + "the plane recovers with a second published endpoint");
                c.Check(s2.Generation != s1.Generation && s2.TokenHex != s1.TokenHex, tag + "the retry uses a NEW generation and a NEW token", s1.Generation + " -> " + s2.Generation);
                c.Check(s2.Port != s1.Port && !Net.IsFixedPort((int)s2.Port), tag + "the retry uses a NEW port that is not a fixed product port", s1.Port + " -> " + s2.Port);
                List<int> pn = new List<int>(rig.Seams.PortNumbers);
                c.Check(pn.Count >= 3 && pn[1] == fixedPort && pn[pn.Count - 1] != pn[0] && pn[pn.Count - 1] != fixedPort, tag + "binds: the first endpoint, the refused claim, then a NEW port (the last bind is the published one)", string.Join(",", pn.ConvertAll<string>(delegate (int x) { return x.ToString(); }).ToArray()));
                c.Check(rig.Seams.CreateCalls == 2, tag + "no mapping was created for the refused attempt", "creates=" + rig.Seams.CreateCalls);
                c.Check(!AnyFixed(rig) && !WatcherSawFixed(w), tag + "no Directory write and no Directory observation ever named the fixed port");
                RecView q = Kit.SendValid(rig, s2, Cmd.Rid(), Cmd.StaText);
                c.Check(q != null && q.State == CState.Queued, tag + "a command is accepted on the new endpoint only", q == null ? "none" : q.Short);
                rig.P.Dispose();
                c.Check(rig.Seams.Log.CountOf("port-close") == pn.Count && rig.Seams.OpenPorts == 0 && rig.Seams.OpenMappings == 0, tag + "the withdrawn port, the refused port and the final port are all closed", "closes=" + rig.Seams.Log.CountOf("port-close") + " binds=" + pn.Count);
                string tv = TraceChecker.Verify(rig.Seams.Log.Snapshot(), true);
                bool gone = Wait.For(delegate { return Net.NameIsFree(rig.Name); }, 2000);
                c.Check(gone && tv == null, tag + "mapping gone and the writer trace obeys the endpoint order", "gone=" + gone + " trace=" + tv + (tv == null ? "" : " events=" + rig.Seams.Log.Names()));
            }
        }

        /// <summary>Planes on real binds: whatever the operating system hands out, no plane ever publishes a fixed product port.</summary>
        private static void Ex03RealCycles(Ctx c, int cycles)
        {
            int published = 0, bad = 0, notReady = 0;
            for (int i = 0; i < cycles; i++)
            {
                SnapView s;
                PlaneRig r = ReadyRig(c, Short(), out s);
                if (s == null) { notReady++; r.P.Dispose(); continue; }
                published++;
                if (Net.IsFixedPort((int)s.Port) || AnyFixed(r)) bad++;
                r.P.Dispose();
                if (r.Seams.OpenPorts != 0 || r.Seams.OpenMappings != 0 || !Net.NameIsFree(r.Name)) bad++;
            }
            c.Check(notReady == 0 && bad == 0 && published == cycles, "real binds: " + cycles + " planes became READY, none published a fixed product port, none left a port or a mapping", "published=" + published + " bad=" + bad + " notReady=" + notReady);
        }

        // =====================================================================================================================================
        // WIN-01  mapping lifecycle on real Windows
        // =====================================================================================================================================
        [Case("WIN-01", "named mapping: create, decode, layout, canonical CLOSED, vanish",
            Purpose = "Windows: the mapping is created, decodes with the shared decoder, has the fixed STDJ v1 layout, CLOSED is the canonical value, and the object disappears when the last handle is closed",
            Precondition = "READY plane on the product name of a synthetic PID; an old-style holder keeps the mapping alive to read the final bytes",
            Operation = "decode; check offsets; hold; Dispose; re-encode CLOSED with the shared Encoder and compare byte for byte; release; probe the name",
            Expected = "valid decode; offsets as in D0B-1; header == tail and even; reserved zero; CLOSED bytes == canonical; name free after release",
            Contract = "D0B-1 9 (STDJ v1, 128 B, seqlock); work order 8 (canonical CLOSED)")]
        internal static void Win01(Ctx c)
        {
            SnapView s;
            PlaneOpts o = Short();
            o.ProductionTimings = true;                // this case runs the product with its own default timings (poll 20 ms)
            PlaneRig rig = ReadyRig(c, o, out s);
            DirRead r = DirView.Poll(rig.Name);
            c.Check(s != null && r.Valid && r.Ready, "the mapping decodes with the shared decoder and is usable READY");
            c.Check(r.BvePid == (UInt32)rig.Pid && r.PublisherPid == (UInt32)rig.Pid && r.Port == s.Port && r.Generation == s.Generation && r.TokenHex == s.TokenHex && r.Caps == 4U,
                "BVE PID, publisher PID, port, generation, token and capabilities equal the plane's values");
            byte[] b = r.Bytes;
            Func<int, UInt32> u32 = delegate (int off) { return BitConverter.ToUInt32(b, off); };
            c.Check(u32(0) == 0x4A445453U && u32(4) == 1U && u32(8) == 128U && u32(12) == (UInt32)rig.Pid, "magic 'STDJ', version 1, size 128, BVE PID @12");
            c.Check(u32(16) == u32(124) && (u32(16) & 1U) == 0U, "seqlock head @16 == tail @124 and even", u32(16) + "/" + u32(124));
            c.Check(u32(20) == 3U && u32(24) == (UInt32)rig.Pid && u32(28) == s.Port && u32(32) == s.Generation, "state @20 (PUBLISHED|READY), publisher PID @24, port @28, generation @32");
            c.Check(u32(56) == 4U && u32(60) == 1U && u32(64) == 4U, "address family 4 @56, transport 1 @60, capabilities 0x4 @64");
            bool reserved = true;
            for (int i = 68; i < 124; i++) if (b[i] != 0) reserved = false;
            c.Check(reserved, "reserved bytes 68..123 are zero");
            HandleHolder hold = new HandleHolder(rig.Name);
            rig.P.Dispose();
            byte[] cb = hold.ReadBlock();
            UInt32 seq = BitConverter.ToUInt32(cb, 16), change = BitConverter.ToUInt32(cb, 52);
            byte[] canon = DataPlaneProtocol.EncodeJumpDirectory((UInt32)rig.Pid, seq, DataPlaneProtocol.Closed, 0U, 0U, 0U, new byte[16], change, 0U);
            c.Check(Same(canon, cb), "the final CLOSED block equals the shared Encoder's canonical CLOSED value, byte for byte", "seq=" + seq + " change=" + change);
            DirRead cr = new DirRead();
            DirView.Fill(cr, cb);
            c.Check(cr.Valid && cr.State == DataPlaneProtocol.Closed, "CLOSED decodes as a valid CLOSED block");
            c.Check(!Net.NameIsFree(rig.Name), "the object still exists while the old holder keeps a handle");
            hold.Dispose();
            c.Check(Net.NameIsFree(rig.Name), "the object disappears as soon as the last handle is closed (mapping gone)");
        }

        // =====================================================================================================================================
        // WIN-02  UDP bind / read / close / port reuse
        // =====================================================================================================================================
        [Case("WIN-02", "UDP: bind, read, close, port reuse",
            Purpose = "Windows: the dynamic loopback port binds exclusively, takes a datagram, and frees its port on close",
            Precondition = "READY plane",
            Operation = "list UDP listeners; bind the same port a second time; send a valid command; Dispose; bind the port again",
            Expected = "loopback only, dynamic range; second bind refused while open; command Queued; port free after Dispose; rebinding succeeds (port reuse)",
            Contract = "RC-7; D0B-1 4.2 / 15.3")]
        internal static void Win02(Ctx c)
        {
            SnapView s;
            PlaneRig rig = ReadyRig(c, Short(), out s);
            c.Check(s != null && s.Port >= 1024U && s.Port <= 65535U && !Net.IsFixedPort((int)s.Port), "the port is dynamic and not a product fixed port", s == null ? "" : s.Port.ToString());
            List<string> ls = Net.ListenersOn((int)s.Port);
            bool wildcard = false, loop = false;
            foreach (string a in ls) { if (IPAddress.IsLoopback(IPAddress.Parse(a))) loop = true; else wildcard = true; }
            c.Check(loop && !wildcard, "the port listens on loopback only (not on 0.0.0.0)", string.Join(",", ls.ToArray()));
            c.Check(!Net.PortIsFree((int)s.Port), "a second bind to the same port is refused while the plane owns it");
            Net.SendTo(s.Port, Cmd.Valid(s, rig.Pid, rig.Src.Owner, Cmd.Rid()));
            c.Check(Wait.For(delegate { return rig.P.Snapshot().Queued != null; }, 3000), "UDP read: a valid command arrives and is Queued");
            rig.P.Dispose();
            c.Check(rig.P.State == PState.Closed, "closed");
            c.Check(Net.PortIsFree((int)s.Port), "port close: the port is free right after Dispose (port reuse works)");
            c.Check(Net.ListenersOn((int)s.Port).Count == 0, "no UDP listener remains on that port");
        }

        // =====================================================================================================================================
        // WIN-03  worker stop / Join / no touch after Dispose
        // =====================================================================================================================================
        [Case("WIN-03", "worker stop, Join, nothing touches after Dispose",
            Purpose = "Windows: the dedicated worker thread exists while running, ends on Dispose within the Join, and neither a seam nor the worker is touched afterwards",
            Precondition = "plane with a live worker and recording seams",
            Operation = "thread counts before / during / after; observe every seam call and the recorded events for 400 ms after Dispose",
            Expected = "exactly one worker; none after Dispose; Join quick; no seam call after CLOSED; no restart; mapping gone",
            Contract = "G-1/G-2; work order 12")]
        internal static void Win03(Ctx c)
        {
            int threadsBefore = Process.GetCurrentProcess().Threads.Count;
            SnapView s;
            PlaneRig rig = ReadyRig(c, Short(), out s);
            c.Check(s != null && rig.P.IsWorkerAlive && rig.Seams.WaiterThreads.Count == 1, "exactly one worker thread drives the plane while it runs", "threads=" + rig.Seams.WaiterThreads.Count);
            int threadsDuring = Process.GetCurrentProcess().Threads.Count;
            Stopwatch sw = Stopwatch.StartNew();
            rig.P.Dispose();
            long ms = sw.ElapsedMilliseconds;
            rig.Seams.DisposedMark = true;
            c.Check(ms < 500, "Dispose (including the worker Join) completes quickly", "elapsed=" + ms + " ms");
            c.Check(rig.P.State == PState.Closed && !rig.P.IsWorkerAlive, "the worker is gone and the plane is closed");
            Wait.Ms(100);
            int threadsAfter = Process.GetCurrentProcess().Threads.Count;
            c.Check(threadsAfter <= threadsBefore + 2, "the process thread count returns to the baseline", threadsBefore + " -> " + threadsDuring + " -> " + threadsAfter);
            int e1 = rig.Seams.Log.Count, o1 = rig.P.Outcomes().Length, it1 = rig.P.Iterations;
            Wait.Ms(400);
            c.Check(rig.Seams.AfterDisposeTouches == 0, "no seam (clock / waiter / port / writer) was touched after Dispose", "touches=" + rig.Seams.AfterDisposeTouches + " " + string.Join(",", rig.Seams.AfterDisposeNames.ToArray()));
            c.Check(rig.Seams.Log.Count == e1 && rig.P.Outcomes().Length == o1 && rig.P.Iterations == it1, "nothing was recorded or iterated after Dispose");
            c.Check(!rig.P.EnsureWorkerAlive() && !rig.P.IsWorkerAlive, "no restart after Dispose");
            c.Check(Net.NameIsFree(rig.Name), "the mapping is gone");
        }

        // =====================================================================================================================================
        // WIN-04  owner resolution through the REAL shared Reader and real (synthetic-PID) mappings
        // =====================================================================================================================================
        [Case("WIN-04", "owner resolution via the shared Directory Reader on Windows",
            Purpose = "AIC-2/AIC-6: the shared TelemetryDirectoryReader resolves a synthetic AppDirectory + Telemetry Directory and a changed Telemetry Directory invalidates the Queued command",
            Precondition = "synthetic AppDirectory and Telemetry Directory mappings under the synthetic (odd, huge) PID; the product's own owner source (the shared Reader, unchanged)",
            Operation = "accept a valid command; republish the Telemetry Directory with another generation",
            Expected = "the command is Queued with the Telemetry generation / port recorded; after the change it ends Discarded (owner-changed or owner-lost)",
            Contract = "v2 2.1 AIC-2/3/4/6; D0B-1 10 step 6")]
        internal static void Win04(Ctx c)
        {
            UInt32 pid = (UInt32)c.NewPid();
            string inst = FakeSource.RandomInstance();
            UInt32 appPid = pid + 2U;
            string appName = "Local\\TSScoringPlugin.v1." + pid + ".AppDirectory";
            string telName = DataPlaneProtocol.TelemetryName(pid, inst);
            byte[] app = new byte[128];
            Action<int, UInt32> w32 = delegate (int off, UInt32 v) { Array.Copy(BitConverter.GetBytes(v), 0, app, off, 4); };
            w32(0, 0x44415354U); w32(4, 1U); w32(8, 80U); w32(12, pid); w32(16, 2U); w32(20, 7U);
            Array.Copy(Encoding.ASCII.GetBytes(inst), 0, app, 24, 32);
            w32(56, appPid); w32(76, 2U);
            byte[] token1 = FakeSource.RandomBytes(16);
            byte[] tel1 = DataPlaneProtocol.EncodeTelemetryDirectory(pid, 2U, DataPlaneProtocol.Published | DataPlaneProtocol.Ready, inst, appPid, 49999U, 0x77U, token1, 1U, 7U);
            RawMapping rApp = c.Own(new RawMapping(appName, app));
            RawMapping rTel = new RawMapping(telName, tel1);
            PlaneOpts o = Short();
            o.Pid = (int)pid;
            o.UseProductSource = true;
            PlaneRig rig = Kit.NewRig(c, o);
            rig.P.Start();
            SnapView s = Kit.AwaitReady(rig.P, 5000);
            c.Check(s != null, "READY with the product's own owner source (the shared Reader)");
            TelemetryEndpoint exp;
            string why;
            c.Check(TelemetryDirectoryReader.TryResolve((int)pid, out exp, out why) && exp.AppInstance == inst && exp.AppProcessId == appPid, "the shared Reader resolves the synthetic owner", why);
            byte[] datagram = DataPlaneProtocol.EncodeEnvelope(0x100U, pid, appPid, s.Generation, inst, s.Token, Cmd.Rid(), Encoding.UTF8.GetBytes(Cmd.StaText));
            Net.SendTo(s.Port, datagram);
            bool queued = Wait.For(delegate { return rig.P.Snapshot().Queued != null; }, 3000);
            SnapView after = rig.P.Snapshot();
            c.Check(queued && after.Queued.AppInstance == inst && after.Queued.AppPid == appPid && after.Queued.TelemetryGeneration == 0x77U && after.Queued.TelemetryPort == 49999U,
                "the command is Queued and the accepted record fixes the Telemetry owner (AppInstance, App PID, generation, port)");
            rTel.Dispose();
            byte[] token2 = FakeSource.RandomBytes(16);
            byte[] tel2 = DataPlaneProtocol.EncodeTelemetryDirectory(pid, 2U, DataPlaneProtocol.Published | DataPlaneProtocol.Ready, inst, appPid, 49999U, 0x78U, token2, 2U, 7U);
            RawMapping rTel2 = c.Own(new RawMapping(telName, tel2));
            string reason = null;
            bool discarded = Wait.For(delegate
            {
                foreach (RecView ro in rig.P.Outcomes()) if (ro.State == CState.Discarded) { reason = ro.Reason; return true; }
                return false;
            }, 3000);
            c.Check(discarded && (reason == "owner-changed" || reason == "owner-lost"), "a republished Telemetry Directory discards the Queued command", reason);
            rig.P.Dispose();
            rTel2.Dispose();
            rApp.Dispose();
            c.Check(Net.NameIsFree(appName) && Net.NameIsFree(telName), "the synthetic AppDirectory / Telemetry mappings are gone");
        }

        // =====================================================================================================================================
        // PT-01  start condition matrix
        // =====================================================================================================================================
        [Case("PT-01", "start condition matrix of OnHostTick",
            Purpose = "plan 5.4 / D-1 / D-10: the plane starts only when (managed) and (events subscribed) and (not disposed); nothing else is a condition",
            Precondition = "a constructed plane with recording seams",
            Operation = "OnHostTick(managed, subscribed) for (undetermined or normal) x (subscribed or not), (managed, not subscribed), (managed, subscribed), and after Dispose; many ticks each",
            Expected = "resources (port, mapping, worker) appear only for (managed, subscribed) and only once; never for the other rows; never after Dispose",
            Contract = "plan 5.4; D-1; D-10; PT-01")]
        internal static void Pt01(Ctx c)
        {
            bool[][] rows = new bool[][] { new bool[] { false, true }, new bool[] { false, false }, new bool[] { true, false } };
            string[] names = new string[] { "not managed (undetermined / normal), events subscribed", "not managed, events not subscribed", "managed, events NOT subscribed (fail closed, D-10)" };
            for (int i = 0; i < rows.Length; i++)
            {
                PlaneRig r = Kit.NewRig(c, Short());
                for (int k = 0; k < 200; k++) r.P.OnHostTick(rows[i][0], rows[i][1]);
                Wait.Ms(40);
                c.Check(r.P.State == PState.NotStarted && !r.P.IsWorkerAlive && r.Seams.BindCalls == 0 && r.Seams.CreateCalls == 0 && r.Seams.WaiterThreads.Count == 0 && Net.NameIsFree(r.Name),
                    names[i] + ": no port, no mapping, no worker after 200 ticks", PState.Name(r.P.State) + " binds=" + r.Seams.BindCalls);
                r.P.Dispose();
            }
            PlaneRig m = Kit.NewRig(c, Short());
            for (int k = 0; k < 50; k++) m.P.OnHostTick(true, true);
            SnapView s = Kit.AwaitReady(m.P, 5000);
            c.Check(s != null, "managed and subscribed: the plane starts and becomes READY");
            for (int k = 0; k < 200; k++) m.P.OnHostTick(true, true);
            Wait.Ms(40);
            SnapView s2 = m.P.Snapshot();
            c.Check(s2.Published == 1 && s2.Generation == s.Generation && m.Seams.BindCalls == 1 && m.Seams.CreateCalls == 1 && m.Seams.WaiterThreads.Count == 1,
                "it started exactly once: one endpoint, one bind, one mapping, one worker, however many ticks follow", "published=" + s2.Published + " binds=" + m.Seams.BindCalls);
            m.P.Dispose();
            PlaneRig d = Kit.NewRig(c, Short());
            d.P.Dispose();
            d.Seams.DisposedMark = true;
            for (int k = 0; k < 50; k++) d.P.OnHostTick(true, true);
            Wait.Ms(40);
            c.Check(d.Seams.BindCalls == 0 && d.Seams.CreateCalls == 0 && !d.P.IsWorkerAlive && Net.NameIsFree(d.Name), "after Dispose a tick never starts anything");
            c.Check(d.Seams.AfterDisposeTouches == 0, "after Dispose a tick touches no seam at all (no clock, no waiter, no port, no writer)", "touches=" + d.Seams.AfterDisposeTouches);
        }

        // =====================================================================================================================================
        // PT-02  normal mode creates nothing
        // =====================================================================================================================================
        [Case("PT-02", "normal mode: nothing is ever created",
            Purpose = "plan 5.4: in Normal / Undetermined mode the plane creates no Directory, no port and no thread",
            Precondition = "a constructed plane, an independent watcher on the product name",
            Operation = "500 host ticks with managed = false",
            Expected = "no READY ever, no mapping, no port, no worker",
            Contract = "plan 5.4; PT-02")]
        internal static void Pt02(Ctx c)
        {
            PlaneRig r = Kit.NewRig(c, Short());
            using (StateWatcher w = new StateWatcher(r.Name))
            {
                for (int k = 0; k < 500; k++) r.P.OnHostTick(false, true);
                Wait.Ms(60);
                c.Check(w.ReadyPolls == 0 && w.CountKind("missing") >= 1 && w.CountKind("READY") == 0 && w.CountKind("PUBLISHED") == 0, "the watcher never saw a mapping", w.KindSequence());
            }
            c.Check(r.Seams.BindCalls == 0 && r.Seams.CreateCalls == 0 && r.Seams.ClockCalls == 0 && r.Seams.WaitCalls == 0, "no seam was ever used", "binds=" + r.Seams.BindCalls + " clock=" + r.Seams.ClockCalls);
            c.Check(!r.P.IsWorkerAlive && r.P.State == PState.NotStarted && r.P.Iterations == 0, "no worker, state NotStarted");
            r.P.Dispose();
            c.Check(r.P.State == PState.Closed, "Dispose of a never started plane closes it without touching any seam", PState.Name(r.P.State) + " touches=" + (r.Seams.BindCalls + r.Seams.CreateCalls));
        }

        // =====================================================================================================================================
        // PT-03  construction alone creates no resource
        // =====================================================================================================================================
        [Case("PT-03", "construction creates no resource",
            Purpose = "plan 5.3: CreateProduction only builds objects; no mapping, no port, no thread",
            Precondition = "the production factory with the production seams",
            Operation = "CreateProduction on a synthetic PID; look at the system; Dispose",
            Expected = "name free, no worker, state NotStarted, thread count unchanged; Dispose is harmless",
            Contract = "plan 5.3; PT-03")]
        internal static void Pt03(Ctx c)
        {
            int pid = c.NewPid();
            string name = Env.ProductName(pid);
            Env.NoteName(name);
            int threads0 = Process.GetCurrentProcess().Threads.Count;
            List<string> lines = new List<string>();
            Action<string> log = delegate (string l) { lock (lines) { lines.Add(l); } };
            PlaneHandle p = new PlaneHandle(Pr.CallStatic(Pr.T("LegacyJumpControlPlane"), "CreateProduction", pid, log));
            c.Own(p);
            Wait.Ms(60);
            c.Check(p.State == PState.NotStarted && !p.IsWorkerAlive, "just constructed: NotStarted, no worker", p.StateName);
            c.Check(Net.NameIsFree(name), "no mapping exists");
            c.Check(Process.GetCurrentProcess().Threads.Count <= threads0 + 1, "no thread was created by the construction", threads0 + " -> " + Process.GetCurrentProcess().Threads.Count);
            c.Check(p.Iterations == 0, "no iteration ran");
            p.Dispose();
            c.Check(p.State == PState.Closed, "Dispose of the never started plane");
            bool noWrongPid = false;
            try { Pr.CallStatic(Pr.T("LegacyJumpControlPlane"), "CreateProduction", 0, log); } catch (ArgumentOutOfRangeException) { noWrongPid = true; }
            c.Check(noWrongPid, "a plane for a non-positive PID cannot be constructed (the Extension catches this and only the Jump feature stays off)");
        }

        // =====================================================================================================================================
        // PT-04  TTL unset
        // =====================================================================================================================================
        [Case("PT-04", "time expiry exists only when a TTL is injected",
            Purpose = "decision D-2 / STOP-10: the product constructs with no TTL; a Queued command never expires by time; an injected TTL still works",
            Precondition = "the injected clock, the dedicated worker",
            Operation = "TTL 0: a command, ten hours pass; TTL 1000: a command, 1001 ms pass",
            Expected = "TTL 0: still Queued; other causes still discard; TTL 1000: Discarded(ttl)",
            Contract = "D-2; PT-04")]
        internal static void Pt04(Ctx c)
        {
            Fx fx = Ready(c, 0, null);
            byte[] rid = Cmd.Rid();
            Accept(fx, rid, Cmd.StaText);
            fx.Clk.Advance(10L * 3600L * 1000L);
            Kit.Settle(fx.P, 6, 3000);
            c.Check(Kit.Find(fx.P, rid).State == CState.Queued, "without a TTL the command stays Queued although ten hours passed");
            fx.P.NoteScenarioBoundary();
            c.Check(AwaitState(fx, rid, CState.Discarded, "scenario-epoch"), "...and a scenario boundary still discards it", Kit.Find(fx.P, rid).Short);
            Fx t = Ready(c, 1000, null);
            byte[] r2 = Cmd.Rid();
            Accept(t, r2, Cmd.StaText);
            t.Clk.Advance(1001);
            c.Check(AwaitState(t, r2, CState.Discarded, "ttl"), "with an injected TTL the command ends Discarded(ttl)", Kit.Find(t.P, r2).Short);
        }

        // =====================================================================================================================================
        // PT-05  final summary line
        // =====================================================================================================================================
        [Case("PT-05", "the final summary line",
            Purpose = "plan 5 / N4: Dispose emits one machine-readable summary line (the G-3b judge reads it)",
            Precondition = "a plane that received one valid command and one garbage datagram",
            Operation = "Dispose; read the log lines",
            Expected = "event=jump-plane-final with the pinned fields in order and the pinned shutdown-order, afterDisposeAccess=0, nothing logged after it",
            Contract = "plan PT-05; N4/N5")]
        internal static void Pt05(Ctx c)
        {
            SnapView s;
            PlaneRig rig = ReadyRig(c, Short(), out s);
            c.Check(s != null, "READY");
            RecView q = Kit.SendValid(rig, s, Cmd.Rid(), Cmd.StaText);
            RecView j = Kit.SendAndAwait(rig, s, new byte[10], 4000);
            c.Check(q != null && q.State == CState.Queued && j != null && j.State == CState.Rejected, "one command accepted and one datagram rejected");
            rig.P.Dispose();
            string[] lines = rig.Lines();
            List<int> finals = new List<int>();
            for (int i = 0; i < lines.Length; i++) if (lines[i].StartsWith("event=jump-plane-final ")) finals.Add(i);
            c.Check(finals.Count == 1, "exactly one summary line", "count=" + finals.Count);
            if (finals.Count == 1)
            {
                string line = lines[finals[0]];
                System.Text.RegularExpressions.Match m = System.Text.RegularExpressions.Regex.Match(line,
                    @"^event=jump-plane-final iterations=(\d+) maxStepsInside=(\d+) maxPublishersInside=(\d+) maxIterationGapMs=(\d+) afterDisposeAccess=(\d+) received=(\d+) accepted=(\d+) rejected=(\d+) rc10Violations=(\d+) shutdown-order=(\S+)$");
                c.Check(m.Success, "the line has exactly the pinned fields in the pinned order", line);
                if (m.Success)
                {
                    c.Check(m.Groups[10].Value == Kit.ShutdownOrder, "shutdown-order is the order of the steps that really ran", m.Groups[10].Value);
                    c.Check(m.Groups[5].Value == "0" && m.Groups[9].Value == "0", "afterDisposeAccess=0 and rc10Violations=0");
                    c.Check(m.Groups[2].Value == "1" && m.Groups[3].Value == "1", "maxStepsInside=1 and maxPublishersInside=1");
                    c.Check(m.Groups[6].Value == "2" && m.Groups[7].Value == "1" && m.Groups[8].Value == "1", "received=2 accepted=1 rejected=1 agree with what was sent", m.Groups[6].Value + "/" + m.Groups[7].Value + "/" + m.Groups[8].Value);
                    c.Check(int.Parse(m.Groups[1].Value) > 0, "the worker really iterated", m.Groups[1].Value);
                }
                c.Check(finals[0] == lines.Length - 1, "no log line follows the summary", "line " + finals[0] + " of " + lines.Length);
            }
            // the orphan teardown (worker finishes the shutdown) keeps the same order string
            ManualResetEvent rel = new ManualResetEvent(false), st = new ManualResetEvent(false);
            PlaneRig pb = null;
            SnapView sb;
            PlaneOpts oc = Short();
            oc.JoinMs = 200; oc.GateTryMs = 150;
            int armedC = 0;
            oc.Hooks = delegate (SeamHooks h) { h.OnClock = delegate { if (pb != null && pb.P.State == PState.Ready && Interlocked.Exchange(ref armedC, 0) == 1) { st.Set(); rel.WaitOne(15000); } }; };
            pb = ReadyRig(c, oc, out sb);
            Interlocked.Exchange(ref armedC, 1);
            st.WaitOne(5000);
            pb.P.Dispose();
            rel.Set();
            c.Check(Wait.For(delegate { return pb.P.State == PState.Closed; }, 8000), "orphan teardown: the worker closed the plane when it left");
            Wait.Ms(30);
            string fin = null;
            foreach (string l in pb.Lines()) if (l.StartsWith("event=jump-plane-final ")) fin = l;
            c.Check(fin != null && fin.EndsWith("shutdown-order=" + Kit.ShutdownOrder), "the orphan teardown writes the same step order", fin);
        }

        // =====================================================================================================================================
        // PT-06  secrets are never logged
        // =====================================================================================================================================
        [Case("PT-06", "no secret value in the logs",
            Purpose = "plan PT-06: the Jump token, the Telemetry token and the AppInstance never appear in a log line",
            Precondition = "a plane that took a command, was re-created once and was disposed; every log line collected",
            Operation = "search the lines for the hex of every token the plane ever published and of the owner's token",
            Expected = "no occurrence",
            Contract = "plan PT-06")]
        internal static void Pt06(Ctx c)
        {
            int throwNext = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new IOException("injected-read"); }; };
            SnapView s;
            PlaneRig rig = ReadyRig(c, o, out s);
            Kit.SendValid(rig, s, Cmd.Rid(), Cmd.StaText);
            Interlocked.Exchange(ref throwNext, 1);
            Net.SendTo(s.Port, new byte[] { 3 });
            Wait.For(delegate { return rig.P.Snapshot().Published >= 2 && rig.P.State == PState.Ready; }, 5000);
            rig.P.Dispose();
            List<string> secrets = new List<string>();
            foreach (PublishRec p in rig.Seams.PublishSnapshot()) if (!secrets.Contains(p.TokenHex) && p.TokenHex != new string('0', 32)) secrets.Add(p.TokenHex);
            secrets.Add(FakeSource.Hex(rig.Src.Owner.Token));
            secrets.Add(rig.Src.Owner.AppInstance);
            string all = string.Join("\n", rig.Lines());
            int leaks = 0;
            foreach (string sec in secrets) if (all.IndexOf(sec, StringComparison.OrdinalIgnoreCase) >= 0) leaks++;
            c.Check(rig.Lines().Length >= 3 && secrets.Count >= 3, "there are log lines and secrets to look for", "lines=" + rig.Lines().Length + " secrets=" + secrets.Count);
            c.Check(leaks == 0, "no token and no AppInstance appears in any log line", "leaks=" + leaks);
        }

        // =====================================================================================================================================
        // PT-07  fixed ports are avoided
        // =====================================================================================================================================
        [Case("PT-07", "the never-bind ports (the two fixed product ports) are rolled back and retried",
            Purpose = "STOP-4: an OS-chosen port that equals a product fixed port is never used; the attempt is rolled back and a new port is taken",
            Precondition = "the port seam first claims the Telemetry port, then the one above it (nothing is bound there), then behaves normally",
            Operation = "start the plane",
            Expected = "the first two attempts are closed and retried without writing a Directory; READY on another port; no Directory ever shows a fixed port",
            Contract = "STOP-4; PT-07; EX-03")]
        internal static void Pt07(Ctx c)
        {
            int n = 0;
            PlaneOpts o = Short();
            o.Hooks = delegate (SeamHooks h) { h.VirtualPort = delegate { int k = Interlocked.Increment(ref n); return k == 1 ? Net.FixedA : (k == 2 ? Net.FixedB : 0); }; };
            PlaneRig rig = Kit.NewRig(c, o);
            using (StateWatcher w = new StateWatcher(rig.Name))
            {
                rig.P.Start();
                SnapView s = Kit.AwaitReady(rig.P, 5000);
                c.Check(s != null && !Net.IsFixedPort((int)s.Port), "READY on a port that is not a product fixed port", s == null ? "no READY" : s.Port.ToString());
                c.Check(s != null && s.Attempts >= 3, "the plane needed three attempts", s == null ? "" : "attempts=" + s.Attempts);
                c.Check(rig.Seams.CreateCalls == 1, "no mapping was created for a vetoed port (the check precedes CreateNew)", "creates=" + rig.Seams.CreateCalls);
                bool fixedWritten = false;
                foreach (PublishRec p in rig.Seams.PublishSnapshot()) if (Net.IsFixedPort((int)p.Port)) fixedWritten = true;
                c.Check(!fixedWritten, "no Directory write ever named a fixed port");
                bool fixedSeen = false;
                foreach (StateWatcher.Obs ob in w.Snapshot()) if (Net.IsFixedPort((int)ob.Port)) fixedSeen = true;
                c.Check(!fixedSeen, "the independent watcher never saw a fixed port");
                c.Check(rig.Seams.OpenPorts == 1, "the vetoed attempts closed their ports (only the live one is open)", "open=" + rig.Seams.OpenPorts);
                c.Check(rig.Seams.Log.CountOf("port-close") == 2, "exactly the two vetoed ports were closed", "closes=" + rig.Seams.Log.CountOf("port-close"));
            }
            rig.P.Dispose();
        }

        // =====================================================================================================================================
        // PT-08  exceptions never escape
        // =====================================================================================================================================
        [Case("PT-08", "exceptions of the seams never reach the host",
            Purpose = "plan 5.6 / PT-08: a throwing log callback, clock, waiter or writer never ends the worker or reaches OnHostTick / NoteScenarioBoundary / Dispose",
            Precondition = "seams that throw once at chosen points",
            Operation = "(1) a log callback that always throws (2) a clock that throws once in READY (3) a waiter that throws once (4) a writer that throws on WITHDRAWING during Dispose",
            Expected = "no exception escapes to the caller; the worker survives (1)-(3); the plane recovers; Dispose completes",
            Contract = "plan 5.6; PT-08")]
        internal static void Pt08(Ctx c)
        {
            PlaneOpts o1 = Short();
            o1.LogThrows = true;
            SnapView s1;
            PlaneRig r1 = ReadyRig(c, o1, out s1);
            c.Check(s1 != null, "(1) a log callback that always throws does not stop the plane from becoming READY");
            Exception e1 = null;
            try { r1.P.OnHostTick(true, true); r1.P.NoteScenarioBoundary(); r1.P.Dispose(); } catch (Exception ex) { e1 = ex; }
            c.Check(e1 == null && r1.P.State == PState.Closed, "(1) OnHostTick / NoteScenarioBoundary / Dispose never throw", e1 == null ? "" : e1.GetType().Name);

            int clockThrow = 0;
            PlaneRig r2 = null;
            PlaneOpts o2 = Short();
            o2.Hooks = delegate (SeamHooks h) { h.OnClock = delegate { if (r2 != null && r2.P.State == PState.Ready && Interlocked.Exchange(ref clockThrow, 0) == 1) throw new InvalidOperationException("injected-clock"); }; };
            SnapView s2;
            r2 = ReadyRig(c, o2, out s2);
            Interlocked.Exchange(ref clockThrow, 1);
            c.Check(Wait.For(delegate { return r2.P.Counter("step-exception") >= 1; }, 3000), "(2) a clock that throws inside the gate is counted as a step exception");
            c.Check(Kit.AwaitReady(r2.P, 5000) != null && r2.P.IsWorkerAlive, "(2) the worker survives and the plane is READY again");
            r2.P.Dispose();

            int waitThrow = 0;
            PlaneRig r3 = null;
            PlaneOpts o3 = Short();
            o3.Hooks = delegate (SeamHooks h) { h.AfterWait = delegate (bool stopped) { if (!stopped && r3 != null && r3.P.State == PState.Ready && Interlocked.Exchange(ref waitThrow, 0) == 1) throw new InvalidOperationException("injected-wait"); }; };
            SnapView s3;
            r3 = ReadyRig(c, o3, out s3);
            int it0 = r3.P.Iterations;
            Interlocked.Exchange(ref waitThrow, 1);
            Wait.For(delegate { return Thread.VolatileRead(ref waitThrow) == 0; }, 3000);
            Kit.Settle(r3.P, 5, 3000);
            c.Check(r3.P.IsWorkerAlive && r3.P.Iterations > it0 + 3 && r3.P.Snapshot().RestartCount == 0, "(3) a waiter that throws does not end the worker (no restart was needed)", "alive=" + r3.P.IsWorkerAlive + " restarts=" + r3.P.Snapshot().RestartCount);
            r3.P.Dispose();

            PlaneOpts o4 = Short();
            o4.Hooks = delegate (SeamHooks h) { h.BeforePublish = delegate (UInt32 st) { if (st == 7U) throw new IOException("injected-withdrawing"); }; };
            SnapView s4;
            PlaneRig r4 = ReadyRig(c, o4, out s4);
            Exception e4 = null;
            try { r4.P.Dispose(); } catch (Exception ex) { e4 = ex; }
            c.Check(e4 == null && r4.P.State == PState.Closed, "(4) a writer that throws on WITHDRAWING does not make Dispose throw and the plane still closes", e4 == null ? PState.Name(r4.P.State) : e4.GetType().Name);
            c.Check(Net.NameIsFree(r4.Name) && r4.Seams.OpenPorts == 0 && r4.Seams.OpenMappings == 0, "(4) the shutdown still released the port and the mapping");
        }

        // =====================================================================================================================================
        // PT-09  non re-entrancy and no access after Dispose
        // =====================================================================================================================================
        [Case("PT-09", "no re-entrancy, no access after Dispose",
            Purpose = "ITR-02 / WIN-03 reinforcement through the plane's own books: maxStepsInside, afterDisposeAccess",
            Precondition = "a plane that ran under load (host ticks from four threads), then Dispose",
            Operation = "read the plane's counters after Dispose and watch the seams for 300 ms",
            Expected = "maxStepsInside == 1, maxPublishersInside == 1, afterDisposeAccess == 0, no seam call, the iteration counter is frozen",
            Contract = "PT-09")]
        internal static void Pt09(Ctx c)
        {
            SnapView s;
            PlaneRig rig = ReadyRig(c, Short(), out s);
            bool stop = false;
            List<Bg> ts = new List<Bg>();
            for (int i = 0; i < 4; i++) ts.Add(Bg.Start(delegate { while (!stop) { rig.P.OnHostTick(true, true); Wait.Ms(0); } }));
            Wait.Ms(300);
            stop = true;
            foreach (Bg b in ts) b.Join(2000);
            rig.P.Dispose();
            rig.Seams.DisposedMark = true;
            int it = rig.P.Iterations;
            Wait.Ms(300);
            c.Check(s != null && it > 5, "the plane really iterated", "iterations=" + it);
            c.Check(rig.P.MaxStepsInside == 1 && rig.P.MaxPublishersInside == 1, "maxStepsInside == 1 and maxPublishersInside == 1", rig.P.MaxStepsInside + "/" + rig.P.MaxPublishersInside);
            c.Check(rig.P.AfterDisposeAccess == 0, "the plane's own afterDisposeAccess is 0", "n=" + rig.P.AfterDisposeAccess);
            c.Check(rig.Seams.AfterDisposeTouches == 0, "the recording seams were not called after Dispose", "n=" + rig.Seams.AfterDisposeTouches);
            c.Check(rig.P.Iterations == it, "the iteration counter is frozen after Dispose");
            c.Check(rig.P.MaxIterationGapMs >= 0, "the iteration gap is recorded", "maxGap=" + rig.P.MaxIterationGapMs);
        }

        // =====================================================================================================================================
        // WIN-99  residue (runs last)
        // =====================================================================================================================================
        [Case("WIN-99", "no resource of this run remains",
            Purpose = "work order 12: nothing of the tests is left (30 measured create/Dispose cycles for handle / thread growth)",
            Precondition = "all other cases finished",
            Operation = "30 more cycles; then compare the books of the seam doubles, every used name and every used port",
            Expected = "no handle / thread growth over the cycles; open ports / mappings 0; every used name creatable; every used port bindable",
            Contract = "work order 12")]
        internal static void Win99(Ctx c)
        {
            for (int i = 0; i < 5; i++) OneCycle(c);
            GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect(); Wait.Ms(200);
            int h0 = Process.GetCurrentProcess().HandleCount, t0 = Process.GetCurrentProcess().Threads.Count;
            for (int i = 0; i < 30; i++) OneCycle(c);
            GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect(); Wait.Ms(300);
            int h1 = Process.GetCurrentProcess().HandleCount, t1 = Process.GetCurrentProcess().Threads.Count;
            c.Check(h1 - h0 <= 12, "30 more create/command/Dispose cycles do not grow the handle count", h0 + " -> " + h1);
            c.Check(t1 - t0 <= 3, "30 more cycles do not grow the thread count (no worker leak)", t0 + " -> " + t1);
            c.Check(Res.OpenPorts == 0 && Res.OpenMappings == 0, "every port and mapping that any seam double ever saw opened was released", Res.OpenPorts + "/" + Res.OpenMappings + " (opened " + Res.PortsOpened + "/" + Res.MappingsOpened + ")");
            // The resources of the planes of THIS run, by ownership. Mappings: the names carry the synthetic PIDs that this run issued; a name of another run is never confused with them.
            string[] names;
            lock (Env.UsedNames) { names = Env.UsedNames.ToArray(); }
            List<string> nameRows = new List<string>();
            Verdict nv = NameJudge.Judge(names, Env.IssuedPidsSnapshot(), Net.NameIsFree, nameRows);
            foreach (string r in nameRows) c.Info(r);
            c.Check(nv.Kind == VKind.Pass, "every mapping name of this run can be created again (nothing of this run is alive)", nv.ToString());
            // Ports: the primary evidence is the recorded close of every port that a plane of this run bound and the successful re-bind of the same port. The table of the operating
            // system (with the owner process) is read only for a port that is busy: still owned by this test process is a FAIL; owned by another process is a re-use by that process,
            // not a port of the plane; an owner that cannot be told is INCONCLUSIVE. The fixed product ports are not excluded (they are never bound here, only looked up).
            OwnedPort[] ledger = Env.OwnedSnapshot();
            int real = 0, published = 0, closedSeen = 0;
            foreach (OwnedPort op in ledger) { if (op.RunId == Env.RunId && !op.Virtual) { real++; if (op.TokenId != null) published++; if (op.CloseSeen) closedSeen++; } }
            c.Check(real >= 35 && closedSeen == real && published >= 35, "the ownership ledger holds the real binds of this run, each with its close, and the planes' published generation / token ids", "binds=" + real + " closed=" + closedSeen + " published=" + published + " run=" + Env.RunId + " pid=" + Process.GetCurrentProcess().Id);
            PortReport pr = PortCheck.Run(ledger, Env.RunId, Process.GetCurrentProcess().Id, 1500);
            foreach (string r in pr.Rows) { if (!r.Contains(": Released - ")) c.Info(r); }
            c.Info("port check: " + pr.Ports + " distinct port(s), " + pr.Lookups + " table lookup(s), " + pr.External + " re-used by another process");
            if (pr.V.Kind == VKind.Inconclusive) c.Inconclusive(pr.V.Reason);
            else c.Check(pr.V.Kind == VKind.Pass, "no port of the planes of this run remains (closed, re-bindable, or re-used by another process)", pr.V.ToString());
            c.Check(Net.FixedSendsRefused == 0, "no test ever tried to send to a fixed product port");
        }

        private static void OneCycle(Ctx outer)
        {
            // a context of its own per cycle: the rig must not stay referenced (and therefore alive) until the end of WIN-99
            Ctx c = new Ctx(outer.Id + "-cycle");
            SnapView s;
            PlaneRig r = ReadyRig(c, Short(), out s);
            if (s != null)
            {
                Net.SendTo(s.Port, Cmd.Valid(s, r.Pid, r.Src.Owner, Cmd.Rid()));
                Wait.For(delegate { return r.P.Snapshot().Queued != null; }, 2000);
            }
            r.P.Dispose();
            c.ReleaseAll();
        }
    }
}

namespace TsScoringLegacyTelemetryTests
{
    public interface ISelfProbe
    {
        int Add(int a, int b);
        string Echo(string s);
        void Fail();
    }

    public static partial class LegacyJumpPlaneTestFixture
    {
        // =====================================================================================================================================
        // Kit self tests (no product needed): the helpers, the trace checker and the residue detectors are proven here, so that a RED or a PASS of a product case can be
        // trusted. Their ids are SELF-nn and they are never counted among the product cases.
        // =====================================================================================================================================
        [Case("SELF-01", "trace checker accepts valid and rejects invalid event orders", Kind = "SELF")]
        internal static void Self01(Ctx c)
        {
            Func<string, string[]> t = delegate (string s)
            {
                string[] parts = s.Split(' ');
                string[] r = new string[parts.Length];
                for (int i = 0; i < parts.Length; i++) r[i] = (i + 1) + "|1|" + parts[i];
                return r;
            };
            string[] valid = new string[]
            {
                "publish:PUBLISHED publish:READY publish:WITHDRAWING port-close publish:CLOSED mapping-dispose",
                "publish:PUBLISHED port-close publish:CLOSED mapping-dispose",
                "port-close",
                "port-close mapping-dispose",
                "publish:PUBLISHED publish:READY publish:WITHDRAWING port-close publish:CLOSED mapping-dispose publish:PUBLISHED port-close publish:CLOSED mapping-dispose",
                "bind:real:50000 createnew publish:PUBLISHED publish:READY publish:WITHDRAWING port-close publish:CLOSED mapping-dispose"
            };
            for (int i = 0; i < valid.Length; i++) c.Check(TraceChecker.Verify(t(valid[i]), true) == null, "valid order #" + i + " is accepted", valid[i]);
            string[] invalid = new string[]
            {
                "publish:READY",
                "publish:PUBLISHED publish:PUBLISHED",
                "publish:PUBLISHED publish:READY publish:CLOSED",
                "publish:PUBLISHED publish:READY port-close",
                "publish:PUBLISHED publish:READY publish:WITHDRAWING publish:CLOSED",
                "publish:PUBLISHED publish:READY publish:WITHDRAWING port-close mapping-dispose",
                "mapping-dispose publish:CLOSED"
            };
            for (int i = 0; i < invalid.Length; i++) c.Check(TraceChecker.Verify(t(invalid[i]), true) != null, "invalid order #" + i + " is rejected", invalid[i]);
            c.Check(TraceChecker.Verify(t("publish:PUBLISHED publish:READY publish:WITHDRAWING port-close publish:CLOSED"), true) != null, "an endpoint left unreleased is reported");
            c.Check(TraceChecker.Verify(t("publish:PUBLISHED publish:READY publish:WITHDRAWING port-close publish:CLOSED"), false) == null, "...unless release is not required");
            c.Check(TraceChecker.Verify(t("dispose:called publish:PUBLISHED port-close publish:CLOSED mapping-dispose"), true, "dispose:called") != null, "a PUBLISHED after the marker is reported (strict rule)");
            c.Check(TraceChecker.Verify(t("publish:PUBLISHED publish:READY dispose:called publish:WITHDRAWING port-close publish:CLOSED mapping-dispose"), true, "dispose:called") == null, "teardown events after the marker are fine");
        }

        [Case("SELF-02", "interface proxy routes calls, boxes values, passes exceptions", Kind = "SELF")]
        internal static void Self02(Ctx c)
        {
            int calls = 0;
            object p = Proxy.Make(typeof(ISelfProbe), delegate (MethodInfo m, object[] a)
            {
                calls++;
                if (m.Name == "Add") return (int)a[0] + (int)a[1];
                if (m.Name == "Echo") return "<" + (string)a[0] + ">";
                throw new InvalidOperationException("boom");
            });
            ISelfProbe sp = (ISelfProbe)p;
            c.Check(sp.Add(20, 22) == 42, "a value-type method is routed and its result unboxed");
            c.Check(sp.Echo("x") == "<x>", "a reference-type method is routed");
            bool threw = false;
            try { sp.Fail(); } catch (InvalidOperationException) { threw = true; }
            c.Check(threw, "an exception of the handler reaches the caller");
            c.Check(calls == 3, "every call went through the handler", "calls=" + calls);
            object p2 = Proxy.Make(typeof(ISelfProbe), delegate (MethodInfo m, object[] a) { return null; });
            c.Check(!object.ReferenceEquals(p, p2) && p.GetType() == p2.GetType(), "two proxies of one interface share the generated type and keep their own handler");
        }

        [Case("SELF-03", "mapping helpers: poll without a retained handle, raw mapping, holder, watcher", Kind = "SELF")]
        internal static void Self03(Ctx c)
        {
            int pid = c.NewPid();
            string name = Env.ProductName(pid) + ".self";
            Env.NoteName(name);
            byte[] closed = DataPlaneProtocol.EncodeJumpDirectory((UInt32)pid, 2U, DataPlaneProtocol.Closed, 0U, 0U, 0U, new byte[16], 1U, 0U);
            RawMapping raw = new RawMapping(name, closed);
            DirRead r = DirView.Poll(name);
            c.Check(r.Found && r.Valid && r.State == DataPlaneProtocol.Closed, "Poll reads a valid CLOSED block", DirView.StateName(r.State));
            raw.Dispose();
            c.Check(Net.NameIsFree(name), "after the poll and the raw dispose no handle is left (the poll retained none)");
            byte[] ready = DataPlaneProtocol.EncodeJumpDirectory((UInt32)pid, 4U, DataPlaneProtocol.Published | DataPlaneProtocol.Ready, (UInt32)pid, 41000U, 9U, FakeSource.RandomBytes(16), 2U, 4U);
            RawMapping raw2 = new RawMapping(name, ready);
            using (StateWatcher w = new StateWatcher(name))
            {
                Wait.For(delegate { return w.ReadyPolls > 0; }, 2000);
                c.Check(w.ReadyPolls > 0 && w.CapsUnion == 4U && w.KindSequence().Contains("READY"), "the watcher sees READY and its capabilities", w.KindSequence());
            }
            HandleHolder hold = new HandleHolder(name);
            raw2.Dispose();
            c.Check(!Net.NameIsFree(name), "a Reader that keeps its handle keeps the object alive (the negative control works)");
            DirRead rh = new DirRead();
            DirView.Fill(rh, hold.ReadBlock());
            c.Check(rh.Valid && rh.Ready && rh.Port == 41000U, "the holder still reads the old block");
            hold.Dispose();
            c.Check(Net.NameIsFree(name), "closing the holder frees the name");
            byte[] junk = new byte[128];
            for (int i = 0; i < junk.Length; i++) junk[i] = 0xAB;
            RawMapping rj = new RawMapping(name, junk);
            DirRead dj = DirView.Poll(name);
            c.Check(dj.Found && !dj.Valid, "a garbage block is found but invalid", dj.Reason);
            rj.Dispose();
            c.Check(!DirView.Poll(name).Found, "a missing mapping is reported missing");
        }

        [Case("SELF-04", "fixed ports are never bound and never written to", Kind = "SELF")]
        internal static void Self04(Ctx c)
        {
            int before = Net.FixedSendsRefused;
            Net.SendTo((uint)Net.FixedA, new byte[] { 1 });
            Net.SendTo((uint)Net.FixedB, new byte[] { 1 });
            c.Check(Net.FixedSendsRefused == before + 2, "SendTo refuses both fixed product ports and counts the refusal");
            bool threw = false;
            try { Net.PortIsFree(Net.FixedA); } catch (FixtureFaultException) { threw = true; }
            c.Check(threw, "PortIsFree refuses to probe a fixed product port (probing would bind it)");
            Net.FixedSendsRefused = before;
            c.Check(Net.IsFixedPort(Net.FixedA) && Net.IsFixedPort(Net.FixedB) && !Net.IsFixedPort(Net.FixedB + 1), "IsFixedPort is exact");
        }

        [Case("SELF-05", "synthetic PIDs, names and the resource books", Kind = "SELF")]
        internal static void Self05(Ctx c)
        {
            HashSet<int> seen = new HashSet<int>();
            bool allOdd = true, allHuge = true, unique = true;
            for (int i = 0; i < 200; i++)
            {
                int p = Env.NextPid();
                if (p % 2 == 0) allOdd = false;
                if (p < 2100000001) allHuge = false;
                if (!seen.Add(p)) unique = false;
            }
            c.Check(allOdd && allHuge && unique, "200 PIDs: odd, >= 2100000001, all different");
            c.Check(Env.ProductName(2100000003) == "Local\\TSScoringPlugin.v1.2100000003.LegacyJump", "the product name format");
            Res.Reset();
            Interlocked.Increment(ref Res.PortsOpened); Interlocked.Increment(ref Res.MappingsOpened);
            c.Check(Res.OpenPorts == 1 && Res.OpenMappings == 1, "the books count an opened port and mapping");
            Interlocked.Increment(ref Res.PortsClosed); Interlocked.Increment(ref Res.MappingsReleased);
            c.Check(Res.OpenPorts == 0 && Res.OpenMappings == 0, "...and a closed one");
            Env.Init(Env.RunId);
            int a = Env.NextPid(), b = Env.NextPid();
            c.Check(b == a + 2, "consecutive PIDs differ by 2 (stay odd)");
        }

        [Case("SELF-06", "command builders", Kind = "SELF")]
        internal static void Self06(Ctx c)
        {
            int pid = c.NewPid();
            FakeSource src = FakeSource.Make(pid);
            SnapView s = new SnapView();
            s.Generation = 77U; s.Token = FakeSource.RandomBytes(16); s.Port = 41000U;
            byte[] rid = Cmd.Rid();
            byte[] d = Cmd.Valid(s, pid, src.Owner, rid);
            Envelope e = DataPlaneProtocol.DecodeEnvelope(d);
            c.Check(e.MessageType == 0x100U && e.BvePid == (UInt32)pid && e.SenderPid == src.Owner.AppProcessId && e.Generation == 77U && e.AppInstance == src.Owner.AppInstance && Same(e.Token, s.Token) && Same(e.RequestId, rid)
                && Encoding.UTF8.GetString(e.Payload) == Cmd.StaText, "a valid datagram decodes with the intended fields");
            c.Check(!FakeSource.IsZero(rid) && rid.Length == 16 && FakeSource.RandomInstance().Length == 32, "request ids are non-zero 16 bytes, instances are 32 hex digits");
            TelemetryEndpoint ep;
            string why;
            c.Check(src.TryResolve(pid, out ep, out why) && why == "ok" && ep.BveProcessId == (UInt32)pid, "the fake owner source resolves");
            src.Ok = false;
            c.Check(!src.TryResolve(pid, out ep, out why) && why == "app-directory-missing" && src.Calls == 2, "...and refuses on demand, counting the calls");
            FakeClock k = new FakeClock();
            long t0 = k.Now();
            k.Advance(250);
            c.Check(k.Now() == t0 + 250, "the fake clock advances only when told");
        }

        [Case("SELF-07", "residue detectors detect a deliberate leak", Kind = "SELF")]
        internal static void Self07(Ctx c)
        {
            string name = Env.ProductName(c.NewPid()) + ".leak";
            Env.NoteName(name);
            RawMapping leak = new RawMapping(name, new byte[128]);
            c.Check(!Net.NameIsFree(name), "a leaked mapping is detected by the name probe");
            leak.Dispose();
            c.Check(Net.NameIsFree(name), "...and the probe is clean after the release");
            int port;
            Net.Listener l = Net.Listen(out port);
            c.Check(!Net.PortIsFree(port) && Net.ListenersOn(port).Count == 1, "a leaked loopback listener is detected by the port probe and the listener list", "port=" + port);
            Env.NotePort(port);
            l.Dispose();
            c.Check(Net.PortIsFree(port) && Net.ListenersOn(port).Count == 0, "...and the probe is clean after the close");
            Res.Reset();
            Interlocked.Increment(ref Res.PortsOpened);
            c.Check(Res.OpenPorts == 1, "an unbalanced port book is visible");
            Res.Reset();
        }

        [Case("SELF-08", "waiting and thread helpers", Kind = "SELF")]
        internal static void Self08(Ctx c)
        {
            int n = 0;
            c.Check(Wait.For(delegate { return ++n >= 3; }, 1000) && n >= 3, "Wait.For returns true as soon as the fact holds");
            Stopwatch sw = Stopwatch.StartNew();
            bool never = Wait.For(delegate { return false; }, 60);
            c.Check(!never && sw.ElapsedMilliseconds >= 55, "Wait.For gives up after the limit and says so", sw.ElapsedMilliseconds + " ms");
            Bg b = Bg.Start(delegate { throw new InvalidOperationException("x"); });
            b.Join(2000);
            c.Check(b.Error is InvalidOperationException, "Bg keeps the error of its body instead of crashing the process");
            Bg ok = Bg.Start(delegate { Wait.Ms(5); });
            c.Check(ok.Join(2000) && ok.Error == null, "Bg joins a normal body");
            Stopwatch s2 = Stopwatch.StartNew();
            Wait.SpinUs(300);
            c.Check(s2.Elapsed.TotalMilliseconds >= 0.25, "SpinUs spins at least the requested time");
        }

        [Case("SELF-09", "case discovery is complete and in order", Kind = "SELF")]
        internal static void Self09(Ctx c)
        {
            string[] found = DiscoverIds();
            List<string> order = new List<string>(Order);
            order.Sort(StringComparer.Ordinal);
            c.Check(string.Join(",", found) == string.Join(",", order.ToArray()), "the planned order lists exactly the discovered product cases", found.Length + " discovered, " + order.Count + " planned");
            c.Check(found.Length == 33, "33 product cases: ITR 16 + EX 3 + WIN 4 + WIN-99 + PT 9", "n=" + found.Length);
            int itr = 0, ex = 0, win = 0, pt = 0;
            foreach (string id in found) { if (id.StartsWith("ITR-")) itr++; else if (id.StartsWith("EX-")) ex++; else if (id.StartsWith("WIN-")) win++; else if (id.StartsWith("PT-")) pt++; }
            c.Check(itr == 16 && ex == 3 && win == 5 && pt == 9, "ITR 16 / EX 3 / WIN 5 (WIN-01..04 + WIN-99) / PT 9", itr + "/" + ex + "/" + win + "/" + pt);
        }

        [Case("SELF-10", "the product binding reports an absent element as a classified RED, never as a crash", Kind = "SELF")]
        internal static void Self10(Ctx c)
        {
            string code = null;
            try { Pr.T("NoSuchTypeForSelfTest"); } catch (ProductAbsentException ex) { code = ex.Code; }
            c.Check(code == "type:NoSuchTypeForSelfTest", "an absent product type is a ProductAbsentException with its code", code);
            string code2 = null;
            try { Pr.TS("NoSuchSharedTypeForSelfTest"); } catch (ProductAbsentException ex) { code2 = ex.Code; }
            c.Check(code2 == "shared-type:NoSuchSharedTypeForSelfTest", "an absent shared type likewise", code2);
            c.Check(Pr.Has("NoSuchTypeForSelfTest") == false, "Has says false");
            string code3 = null;
            try { Pr.Get("text", "NoSuchMemberForSelfTest"); } catch (ProductAbsentException ex) { code3 = ex.Code; }
            c.Check(code3 == "member:String.NoSuchMemberForSelfTest", "an absent member likewise", code3);
            object s = Pr.Call("abcdef", "Substring", 2);
            c.Check((string)s == "cdef", "Call finds and invokes a method by name and argument count");
            bool unwrapped = false;
            try { Pr.Call("abc", "Substring", 99); } catch (ArgumentOutOfRangeException) { unwrapped = true; }
            c.Check(unwrapped, "an exception of the invoked method is rethrown unwrapped");
        }

        // =====================================================================================================================================
        // Flake-fix addendum: deterministic positive and negative controls of the judges of ITR-15, WIN-99, Ready() and the outcome INCONCLUSIVE.
        // =====================================================================================================================================
        private static void Expect(Ctx c, string what, Verdict v, VKind want, string reasonPart)
        {
            bool ok = v.Kind == want && (reasonPart == null || v.Reason.Contains(reasonPart));
            c.Check(ok, what, v.ToString() + (reasonPart == null ? "" : " (wanted " + want + " with '" + reasonPart + "')"));
        }

        [Case("SELF-11", "worker restart judge: early checks are PENDING, defects are FAIL, a reused thread id is not a defect", Kind = "SELF")]
        internal static void Self11(Ctx c)
        {
            WorkerFact oldDone = WorkerFact.Make(1, 0, 7, true, true, true, true);
            WorkerFact oldLive = WorkerFact.Make(1, 0, 7, true, true, false, false);
            WorkerFact oldNoJoin = WorkerFact.Make(1, 0, 7, true, true, true, false);
            WorkerFact newOk = WorkerFact.Make(2, 1, 9, true, true, false, false);
            Expect(c, "a normal restart (old exited and joined, new registered, generation advanced) is PASS", WorkerJudge.Restart(new WorkerFact[] { oldDone, newOk }, 0, true), VKind.Pass, null);
            Expect(c, "the thread id of the new worker equals the old one (the id was handed out again): still PASS, the identity is the instance and the generation", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(2, 1, 7, true, true, false, false) }, 0, true), VKind.Pass, null);
            Expect(c, "race: checked before the exit of the old worker, no new worker yet: PENDING", WorkerJudge.Restart(new WorkerFact[] { oldLive }, 0, true), VKind.Pending, "old worker exit");
            Expect(c, "race: the old worker exited but its Join is not confirmed: PENDING", WorkerJudge.Restart(new WorkerFact[] { oldNoJoin }, 0, true), VKind.Pending, "Join");
            Expect(c, "race: checked before the start of the new worker: PENDING", WorkerJudge.Restart(new WorkerFact[] { oldDone }, 0, true), VKind.Pending, "new worker start");
            Expect(c, "race: the new worker is started (logged) but not yet a live worker of the plane: PENDING", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(2, 1, 9, true, false, false, false) }, 0, true), VKind.Pending, "not yet recorded");
            Expect(c, "race: the new worker runs but its start is not logged: PENDING", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(2, -1, 9, false, true, false, false) }, 0, true), VKind.Pending, "not logged");
            Expect(c, "defect: the old worker remains alive while a new worker runs: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldLive, newOk }, 0, true), VKind.Fail, "old worker is still alive");
            Expect(c, "defect: no live worker after the restart (the new worker died): FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(2, 1, 9, true, true, true, true) }, 0, true), VKind.Fail, "no live worker");
            Expect(c, "defect: two new workers are alive: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, newOk, WorkerFact.Make(3, 2, 11, true, true, false, false) }, 0, true), VKind.Fail, "live workers: 2");
            Expect(c, "defect: a second new worker was started and has already gone: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, newOk, WorkerFact.Make(3, 2, 11, true, true, true, true) }, 0, true), VKind.Fail, "more than one new worker");
            Expect(c, "defect: the worker generation is reused: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(2, 0, 9, true, true, false, false) }, 0, true), VKind.Fail, "generation reused");
            Expect(c, "defect: the worker generation goes back: FAIL", WorkerJudge.Restart(new WorkerFact[] { WorkerFact.Make(1, 3, 7, true, true, true, true), WorkerFact.Make(2, 2, 9, true, true, false, false) }, 0, true), VKind.Fail, "went back");
            Expect(c, "defect: the instance sequence repeats: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, WorkerFact.Make(1, 1, 9, true, true, false, false) }, 0, true), VKind.Fail, "instance sequence");
            Expect(c, "defect: a worker re-entry was counted: FAIL", WorkerJudge.Restart(new WorkerFact[] { oldDone, newOk }, 1, true), VKind.Fail, "re-entry");
            Expect(c, "no stop request recorded: FAIL (the restart is not judged without it)", WorkerJudge.Restart(new WorkerFact[] { oldDone, newOk }, 0, false), VKind.Fail, "stop request");
            Expect(c, "no worker recorded at all: PENDING", WorkerJudge.Restart(new WorkerFact[0], 0, true), VKind.Pending, "no worker");
            Expect(c, "stopped: no worker alive and no further worker: PASS", WorkerJudge.Stopped(new WorkerFact[] { oldDone, WorkerFact.Make(2, 1, 9, true, true, true, true) }, 2), VKind.Pass, null);
            Expect(c, "stopped: a further worker was recorded after the stop: FAIL", WorkerJudge.Stopped(new WorkerFact[] { oldDone, WorkerFact.Make(2, 1, 9, true, true, true, true), WorkerFact.Make(3, 2, 11, true, true, true, true) }, 2), VKind.Fail, "after the stop");
            Expect(c, "stopped: a worker is still alive: PENDING", WorkerJudge.Stopped(new WorkerFact[] { oldDone, newOk }, 2), VKind.Pending, "has not exited");
        }

        [Case("SELF-12", "bounded waiting for a verdict: a verdict that stays PENDING ends in a FAIL at the limit", Kind = "SELF")]
        internal static void Self12(Ctx c)
        {
            Stopwatch sw = Stopwatch.StartNew();
            AwaitResult never = Verdicts.Await(delegate { return Verdict.Pending("nothing happens"); }, 150);
            c.Check(never.Final.Kind == VKind.Fail && never.Final.Reason.Contains("limit of 150 ms") && sw.ElapsedMilliseconds >= 140 && sw.ElapsedMilliseconds < 3000, "a PENDING that never settles is a FAIL at the limit, and the wait is bounded", never.Final + " after " + sw.ElapsedMilliseconds + " ms");
            int n = 0;
            AwaitResult late = Verdicts.Await(delegate { n++; return n < 5 ? Verdict.Pending("not yet " + n) : Verdict.Pass("settled"); }, 2000);
            c.Check(late.Final.Kind == VKind.Pass && late.Evaluations == 5 && late.Steps.Count == 5, "a verdict that settles is PASS and every change of the state is recorded", late.Final + " evaluations=" + late.Evaluations + " steps=" + late.Steps.Count);
            sw.Restart();
            AwaitResult early = Verdicts.Await(delegate { return Verdict.Fail("defect"); }, 5000);
            c.Check(early.Final.Kind == VKind.Fail && early.Evaluations == 1 && sw.ElapsedMilliseconds < 1000, "a FAIL ends the wait at once (no fixed wait before the verdict)", early.Final + " after " + sw.ElapsedMilliseconds + " ms");
            AwaitResult inc = Verdicts.Await(delegate { return Verdict.Inconclusive("cannot tell"); }, 5000);
            c.Check(inc.Final.Kind == VKind.Inconclusive && inc.Evaluations == 1, "INCONCLUSIVE ends the wait and is neither PASS nor FAIL", inc.Final.ToString());
            AwaitResult passAtOnce = Verdicts.Await(delegate { return Verdict.Pass("ready"); }, 5000);
            c.Check(passAtOnce.Final.Kind == VKind.Pass && passAtOnce.Evaluations == 1, "a PASS on the first look is returned at once");
        }

        [Case("SELF-13", "Ready() driver: bounded in steps, synthetic time and real time; every step recorded; terminal states, a dead worker and exceptions end it", Kind = "SELF")]
        internal static void Self13(Ctx c)
        {
            int[] seq = new int[] { PState.Publishing, PState.Publishing, PState.RetryWaiting, PState.Ready };
            int idx = 0, advances = 0;
            long clock = 0;
            ReadyTrace ok = ReadyDriver.Drive(delegate { return seq[Math.Min(idx++, seq.Length - 1)]; }, delegate { return true; }, delegate (long ms) { advances++; clock += ms; }, delegate { return "d"; }, 100, 10000, 5000, delegate { });
            c.Check(ok.Reached && ok.Steps == 4 && ok.SyntheticMs == 150 && advances == 3 && clock == 150 && ok.Lines.Count == 4, "READY after 4 steps: the clock moved only through the advance step (3 x 50 ms) and every step is recorded", "steps=" + ok.Steps + " synthetic=" + ok.SyntheticMs + " lines=" + ok.Lines.Count);
            ReadyTrace at1 = ReadyDriver.Drive(delegate { return PState.Ready; }, delegate { return true; }, delegate (long ms) { advances++; }, delegate { return ""; }, 100, 10000, 5000, delegate { });
            c.Check(at1.Reached && at1.Steps == 1 && at1.SyntheticMs == 0, "a plane that is READY at once is not touched");
            ReadyTrace term = ReadyDriver.Drive(delegate { return PState.Closed; }, delegate { return true; }, delegate (long ms) { }, delegate { return ""; }, 100, 10000, 5000, delegate { });
            c.Check(!term.Reached && term.End.Contains("terminal state Closed"), "a terminal state other than READY ends the drive with its reason", term.End);
            ReadyTrace dead = ReadyDriver.Drive(delegate { return PState.RetryWaiting; }, delegate { return false; }, delegate (long ms) { }, delegate { return ""; }, 100, 10000, 5000, delegate { });
            c.Check(!dead.Reached && dead.End.Contains("worker is not alive"), "a dead worker ends the drive with its reason", dead.End);
            int polls = 0;
            ReadyTrace boom = ReadyDriver.Drive(delegate { if (++polls == 3) throw new InvalidOperationException("injected"); return PState.Publishing; }, delegate { return true; }, delegate (long ms) { }, delegate { return ""; }, 100, 10000, 5000, delegate { });
            c.Check(!boom.Reached && boom.End.Contains("exception while observing the plane: InvalidOperationException") && boom.Steps == 3, "an exception is not swallowed: the drive ends with it", boom.End);
            ReadyTrace steps = ReadyDriver.Drive(delegate { return PState.RetryWaiting; }, delegate { return true; }, delegate (long ms) { }, delegate { return ""; }, 10, 1000000, 5000, delegate { });
            c.Check(!steps.Reached && steps.Steps == 10 && steps.End.Contains("step limit of 10"), "the step bound ends a plane that never becomes READY", steps.End);
            ReadyTrace syn = ReadyDriver.Drive(delegate { return PState.RetryWaiting; }, delegate { return true; }, delegate (long ms) { }, delegate { return ""; }, 1000, 200, 5000, delegate { });
            c.Check(!syn.Reached && syn.End.Contains("synthetic time limit of 200") && syn.SyntheticMs == 200, "the synthetic time bound ends it (the clock was moved by 200 ms and not more)", syn.End + " synthetic=" + syn.SyntheticMs);
            Stopwatch sw = Stopwatch.StartNew();
            ReadyTrace real = ReadyDriver.Drive(delegate { return PState.RetryWaiting; }, delegate { return true; }, delegate (long ms) { }, delegate { return ""; }, 100, 100000000, 120, delegate { Wait.Ms(30); });
            c.Check(!real.Reached && real.End.Contains("real time limit of 120") && sw.ElapsedMilliseconds < 3000, "the real time bound ends it", real.End + " after " + sw.ElapsedMilliseconds + " ms");
            c.Check(ReadyDriver.MaxSteps > 0 && ReadyDriver.MaxSteps <= 5000 && ReadyDriver.MaxSyntheticMs > 0 && ReadyDriver.MaxSyntheticMs <= 300000 && ReadyDriver.RealLimitMs > 0 && ReadyDriver.StepMs > 0, "the bounds of the production driver are explicit and finite", ReadyDriver.MaxSteps + " steps / " + ReadyDriver.MaxSyntheticMs + " ms synthetic / " + ReadyDriver.RealLimitMs + " ms real");
        }

        private static PortFacts Pf(string run, int port, bool closed, int probe, int[] owners, bool reuse, bool fixedPort, bool virt)
        {
            PortFacts f = new PortFacts();
            f.RunId = run; f.Port = port; f.CloseSeen = closed; f.Probe = probe; f.Owners = owners; f.RegisteredReuse = reuse; f.Fixed = fixedPort; f.Virtual = virt;
            return f;
        }

        [Case("SELF-14", "port judge: closed and re-bindable, residue of the test process, re-use by another process, unknown owner, fixed ports not excluded, other run ignored", Kind = "SELF")]
        internal static void Self14(Ctx c)
        {
            const int me = 1000;
            string note;
            c.Check(PortJudge.Classify(Pf("r", 50001, true, 1, null, false, false, false), "r", me, out note) == PortClass.Released, "closed and the port could be bound again: released", note);
            c.Check(PortJudge.Classify(Pf("r", 50002, false, 1, null, false, false, false), "r", me, out note) == PortClass.NotClosed, "the close was never seen: not closed (even if the port can be bound)", note);
            c.Check(PortJudge.Classify(Pf("r", 50003, true, 2, new int[] { me }, false, false, false), "r", me, out note) == PortClass.OwnedByTestProcess, "closed on the book but the test process still owns the port: residue", note);
            c.Check(PortJudge.Classify(Pf("r", 50004, true, 2, new int[] { me }, true, false, false), "r", me, out note) == PortClass.SameProcessReuse, "the test process re-bound it on purpose (registered): same-process re-use, not a residue", note);
            c.Check(PortJudge.Classify(Pf("r", 50005, true, 2, new int[] { 2222 }, false, false, false), "r", me, out note) == PortClass.ExternalReuse, "another process owns it: re-use by that process, not a residue of the plane", note);
            c.Check(PortJudge.Classify(Pf("r", 50006, true, 2, new int[] { 0 }, false, false, false), "r", me, out note) == PortClass.OwnerUnknown, "owner pid 0: the owner cannot be told", note);
            c.Check(PortJudge.Classify(Pf("r", 50007, true, 2, null, false, false, false), "r", me, out note) == PortClass.OwnerUnknown, "no table: the owner cannot be told", note);
            c.Check(PortJudge.Classify(Pf("r", 50008, true, 2, new int[0], false, false, false), "r", me, out note) == PortClass.Released, "busy a moment ago and not in the table now: released", note);
            c.Check(PortJudge.Classify(Pf("r", 50009, true, 2, new int[] { 2222, me }, false, false, false), "r", me, out note) == PortClass.OwnedByTestProcess, "owned by another process AND by the test process: the test process counts", note);
            c.Check(PortJudge.Classify(Pf("other", 50010, false, 2, new int[] { me }, false, false, false), "r", me, out note) == PortClass.OtherRun, "a port of another run is never judged as a resource of this run", note);
            c.Check(PortJudge.Classify(Pf("r", 50011, true, 0, null, false, false, true), "r", me, out note) == PortClass.Released, "a virtual claim has no operating system port", note);
            c.Check(PortJudge.Classify(Pf("r", Net.FixedA, true, 0, new int[] { me }, false, true, false), "r", me, out note) == PortClass.OwnedByTestProcess, "a fixed product port is NOT excluded: owned by the test process is a residue", note);
            c.Check(PortJudge.Classify(Pf("r", Net.FixedA, true, 0, new int[0], false, true, false), "r", me, out note) == PortClass.Released, "a fixed product port nobody owns: released (looked up, never bound)", note);
            c.Check(PortJudge.Classify(Pf("r", Net.FixedB, true, 0, new int[] { 2222 }, false, true, false), "r", me, out note) == PortClass.ExternalReuse, "a fixed product port owned by another process: external", note);
            c.Check(PortJudge.Classify(Pf("r", Net.FixedB, false, 0, null, false, true, false), "r", me, out note) == PortClass.NotClosed, "a fixed product port whose close was not seen: not closed", note);
            int ext;
            PortFacts good = Pf("r", 50020, true, 1, null, false, false, false);
            PortFacts external = Pf("r", 50021, true, 2, new int[] { 2222 }, false, false, false);
            PortFacts leak = Pf("r", 50022, true, 2, new int[] { me }, false, false, false);
            PortFacts unknown = Pf("r", 50023, true, 2, new int[] { 0 }, false, false, false);
            PortFacts foreign = Pf("other", 50024, false, 2, new int[] { me }, false, false, false);
            Expect(c, "judge: closed ports and a re-use by another process: PASS", PortJudge.Judge(new PortFacts[] { good, external, foreign }, "r", me, null, out ext), VKind.Pass, "re-used by another process");
            c.Check(ext == 1, "the re-use by another process is counted (information)", "external=" + ext);
            Expect(c, "judge: a residue of the test process among good ports: FAIL", PortJudge.Judge(new PortFacts[] { good, external, leak }, "r", me, null, out ext), VKind.Fail, "50022");
            Expect(c, "judge: an unknown owner only: INCONCLUSIVE (never PASS)", PortJudge.Judge(new PortFacts[] { good, unknown }, "r", me, null, out ext), VKind.Inconclusive, "50023");
            Expect(c, "judge: a residue beats an unknown owner: FAIL", PortJudge.Judge(new PortFacts[] { unknown, leak }, "r", me, null, out ext), VKind.Fail, "50022");
            Expect(c, "judge: the ports of another run alone leave nothing to judge but never fail this run", PortJudge.Judge(new PortFacts[] { foreign }, "r", me, null, out ext), VKind.Pass, "0 port");
        }

        [Case("SELF-15", "WIN-99 controls with real ports: proper close, leaked port, a book that lies, same-process re-use, re-use by another process, other run", Kind = "SELF")]
        internal static void Self15(Ctx c)
        {
            string run = Env.RunId;
            int me = Process.GetCurrentProcess().Id;
            // a. a plane port is closed properly and the close is recorded
            SimPort proper = c.Own(new SimPort(run));
            proper.Close();
            PortReport ra = PortCheck.Run(new OwnedPort[] { proper.Led }, run, me, 1500);
            Expect(c, "a. closed properly: PASS (the port can be bound again)", ra.V, VKind.Pass, null);
            // b. the port is leaked: the close is never seen
            SimPort leaked = c.Own(new SimPort(run));
            PortReport rb = PortCheck.Run(new OwnedPort[] { leaked.Led }, run, me, 1500);
            Expect(c, "b. a port that stays open and whose close is never seen: FAIL", rb.V, VKind.Fail, "NotClosed");
            // c. the book lies: the close is recorded, the port is still open, the test process owns it
            SimPort lying = c.Own(new SimPort(run));
            lying.RecordCloseOnly();
            PortReport rc = PortCheck.Run(new OwnedPort[] { lying.Led }, run, me, 1500);
            if (rc.V.Kind == VKind.Inconclusive) c.Inconclusive("control c cannot run: " + rc.V.Reason);
            else Expect(c, "c. closed on the book but the port is still owned by the test process: FAIL", rc.V, VKind.Fail, "OwnedByTestProcess");
            // d. the same process re-uses the port after the plane closed it
            SimPort again = c.Own(new SimPort(run));
            again.Close();
            using (ReuseHolder registered = new ReuseHolder(again.Port, true))
            {
                PortReport rd = PortCheck.Run(new OwnedPort[] { again.Led }, run, me, 1500);
                if (rd.V.Kind == VKind.Inconclusive) c.Inconclusive("control d cannot run: " + rd.V.Reason);
                else Expect(c, "d. the same process re-bound the port on purpose after the plane closed it (registered): PASS, not a residue", rd.V, VKind.Pass, null);
            }
            SimPort again2 = c.Own(new SimPort(run));
            again2.Close();
            using (ReuseHolder unregistered = new ReuseHolder(again2.Port, false))
            {
                PortReport rd2 = PortCheck.Run(new OwnedPort[] { again2.Led }, run, me, 1500);
                if (rd2.V.Kind == VKind.Inconclusive) c.Inconclusive("control d2 cannot run: " + rd2.V.Reason);
                else Expect(c, "d2. the port is held by the test process and nobody registered the re-use: FAIL", rd2.V, VKind.Fail, "OwnedByTestProcess");
            }
            // e. ANOTHER process re-uses the port after the plane closed it: not a residue of the plane; the other process is neither stopped nor disturbed
            SimPort other = c.Own(new SimPort(run));
            other.Close();
            ExternalHolder holder = ExternalHolder.Hold(other.Port, 30000);
            if (holder == null) c.Inconclusive("control e cannot run: the second process did not start");
            else
            {
                c.Own(holder);
                PortReport re = PortCheck.Run(new OwnedPort[] { other.Led }, run, me, 1500);
                if (re.V.Kind == VKind.Inconclusive) c.Inconclusive("control e cannot run: " + re.V.Reason);
                else
                {
                    Expect(c, "e. another process re-used the port after the plane closed it: PASS", re.V, VKind.Pass, null);
                    c.Check(re.External == 1, "e. the re-use is recognised as external by its owner pid", "external=" + re.External + " holder pid=" + holder.Pid + " test pid=" + me);
                }
                int[] owners = UdpOwners.Read(other.Port);
                c.Check(holder.Alive && owners != null && Array.IndexOf(owners, holder.Pid) >= 0 && !Net.PortIsFree(other.Port), "e. the other process was not stopped and its port was not closed by the judge", "alive=" + holder.Alive + " owners=" + (owners == null ? "?" : string.Join(",", Array.ConvertAll(owners, delegate (int x) { return x.ToString(); }))));
            }
            // f. a leaked port of ANOTHER run is not a residue of this run
            SimPort foreign = c.Own(new SimPort("another-run"));
            PortReport rf = PortCheck.Run(new OwnedPort[] { foreign.Led }, run, me, 1500);
            Expect(c, "f. an open port that belongs to another run is not judged as a resource of this run: PASS", rf.V, VKind.Pass, null);
            PortReport rf2 = PortCheck.Run(new OwnedPort[] { foreign.Led }, "another-run", me, 1500);
            Expect(c, "f2. the same ledger judged for its own run: FAIL (the run id is what separates them)", rf2.V, VKind.Fail, "NotClosed");
        }

        [Case("SELF-16", "table parser, owner lookup and the outcome INCONCLUSIVE", Kind = "SELF")]
        internal static void Self16(Ctx c)
        {
            string sample = "\r\nActive Connections\r\n\r\n  Proto  Local Address          Foreign Address        State           PID\r\n  UDP    0.0.0.0:123            *:*                                    4321\r\n  UDP    127.0.0.1:53224        *:*                                    1234\r\n  UDP    127.0.0.1:53224        *:*                                    1234\r\n  UDP    192.168.0.5:5353       *:*                                    77\r\n";
            Dictionary<int, List<int>> d = UdpOwners.Parse(sample);
            c.Check(d != null && d.Count == 3 && d[123][0] == 4321 && d[53224].Count == 2 && d[5353][0] == 77, "the table text is parsed into port -> owner pids", d == null ? "null" : "ports=" + d.Count);
            c.Check(UdpOwners.Parse("nothing like a table") == null && UdpOwners.Parse("") == null && UdpOwners.Parse(null) == null, "text that is no table is reported as unreadable (null), never as an empty table");
            int port;
            Net.Listener l = Net.Listen(out port);
            int[] owners = UdpOwners.Read(port);
            if (owners == null) c.Inconclusive("the table of the operating system cannot be read here");
            else c.Check(owners.Length >= 1 && Array.IndexOf(owners, Process.GetCurrentProcess().Id) >= 0, "the real table names this process as the owner of its own listener", "port=" + port + " owners=" + owners.Length);
            l.Dispose();
            Ctx fail = new Ctx("x");
            fail.Check(false, "a failed check");
            fail.Inconclusive("also inconclusive");
            Ctx inc = new Ctx("x");
            inc.Check(true, "a passed check");
            inc.Inconclusive("cannot tell");
            Ctx pass = new Ctx("x");
            pass.Check(true, "a passed check");
            Ctx none = new Ctx("x");
            string tx;
            c.Check(OutcomeOf(fail, out tx) == "FAIL", "a failed check is a FAIL even if the case is also inconclusive");
            c.Check(OutcomeOf(inc, out tx) == "INCONCLUSIVE" && tx == "cannot tell", "a case that could not reach a verdict is INCONCLUSIVE, never a PASS", tx);
            c.Check(OutcomeOf(pass, out tx) == "PASS", "passed checks and nothing inconclusive: PASS");
            c.Check(OutcomeOf(none, out tx) == "FAIL", "a case without a single check is a FAIL");
        }

        [Case("SELF-17", "mapping names: only the names of this run's PIDs are judged", Kind = "SELF")]
        internal static void Self17(Ctx c)
        {
            int mine = c.NewPid();
            int[] issued = Env.IssuedPidsSnapshot();
            string nameMine = Env.ProductName(mine);
            string nameForeign = Env.ProductName(mine + 1000001);
            c.Check(Array.IndexOf(issued, mine) >= 0 && Array.IndexOf(issued, mine + 1000001) < 0, "the PID of this run is issued, the other one is not");
            RawMapping alive = new RawMapping(nameMine, new byte[128]);
            List<string> rows = new List<string>();
            Expect(c, "a mapping of this run that is still alive: FAIL", NameJudge.Judge(new string[] { nameMine }, issued, Net.NameIsFree, rows), VKind.Fail, "still alive");
            alive.Dispose();
            Expect(c, "...and after its release: PASS", NameJudge.Judge(new string[] { nameMine }, issued, Net.NameIsFree, rows), VKind.Pass, "can be created again");
            RawMapping foreignAlive = new RawMapping(nameForeign, new byte[128]);
            Expect(c, "a mapping of ANOTHER run that is alive is not confused with a resource of this run: PASS", NameJudge.Judge(new string[] { nameMine, nameForeign }, issued, Net.NameIsFree, rows), VKind.Pass, "another run ignored");
            foreignAlive.Dispose();
            string odd = "Local\\TSScoringPlugin.selftest." + mine;
            RawMapping oddAlive = new RawMapping(odd, new byte[128]);
            Expect(c, "a name that carries no PID cannot be attributed to another run, so it counts: FAIL while alive", NameJudge.Judge(new string[] { odd }, issued, Net.NameIsFree, rows), VKind.Fail, "still alive");
            oddAlive.Dispose();
            Env.NoteName(nameMine);
        }

        [Case("SELF-18", "worker facts of real threads: alive, exited, joined, start lines, instance sequence", Kind = "SELF")]
        internal static void Self18(Ctx c)
        {
            SeamSet seams = new SeamSet();
            ManualResetEvent stopA = new ManualResetEvent(false), stopB = new ManualResetEvent(false);
            // two threads whose life the test controls
            System.Threading.Thread ta = new System.Threading.Thread(delegate () { stopA.WaitOne(10000); });
            System.Threading.Thread tb = new System.Threading.Thread(delegate () { stopB.WaitOne(10000); });
            ta.IsBackground = true; tb.IsBackground = true;
            ta.Start(); tb.Start();
            WorkerRec ra = new WorkerRec(); ra.Instance = 1; ra.T = ta; ra.ManagedId = ta.ManagedThreadId;
            WorkerRec rb = new WorkerRec(); rb.Instance = 2; rb.T = tb; rb.ManagedId = tb.ManagedThreadId;
            lock (seams.Workers) { seams.Workers.Add(ra); seams.Workers.Add(rb); }
            string[] log = new string[] { "x event=jump-worker-start restarts=0 y", "noise", "x event=jump-worker-start restarts=1 y" };
            WorkerFact[] f = WorkerFacts.Build(seams, log);
            c.Check(f.Length == 2 && f[0].Registered && !f[0].Exited && f[1].Registered && !f[1].Exited && f[0].Generation == 0 && f[1].Generation == 1 && f[0].StartLogged && f[1].StartLogged, "two live workers with their logged generations", WorkerFacts.Describe(f));
            stopA.Set();
            c.Check(WorkerFacts.Join(seams, 1, 5000) && !WorkerFacts.Join(seams, 2, 50), "the Join of an exited thread is confirmed and recorded; a thread that lives is not joined");
            WorkerFact[] f2 = WorkerFacts.Build(seams, log);
            c.Check(f2[0].Exited && f2[0].Joined && !f2[1].Exited && !f2[1].Joined, "the exit and the Join are facts read from the threads themselves", WorkerFacts.Describe(f2));
            WorkerFact[] f3 = WorkerFacts.Build(seams, new string[] { "x event=jump-worker-start restarts=0 y", "x event=jump-worker-start restarts=1 y", "x event=jump-worker-start restarts=2 y" });
            c.Check(f3.Length == 3 && f3[2].StartLogged && !f3[2].Registered && f3[2].Generation == 2, "a start line without a registered thread is a logged start that is not yet a live worker", WorkerFacts.Describe(f3));
            Expect(c, "the restart judge reads these real facts: two logged starts after the old worker is a defect, not a PASS", WorkerJudge.Restart(f3, 0, true), VKind.Fail, "more than one new worker");
            stopB.Set();
            ta.Join(3000);
            tb.Join(3000);
        }

        [Case("SELF-19", "worker registration seam: identity is the thread object, the instance sequence, re-entry is counted, the gate sits before the registration", Kind = "SELF")]
        internal static void Self19(Ctx c)
        {
            SeamSet seams = new SeamSet();
            MethodInfo waitOne = Pr.T(SeamSet.WaitIface).GetMethod("WaitOne");
            object inner = Proxy.Make(Pr.T(SeamSet.WaitIface), delegate (MethodInfo m, object[] a) { return false; });
            object wait = seams.Wait(inner);
            ManualResetEvent parkedA = new ManualResetEvent(false), releaseA = new ManualResetEvent(false), never = new ManualResetEvent(false);
            int gateCalls = 0, first = 0;
            List<int> gateSaw = new List<int>();
            seams.Hooks.BeforeWorkerRegister = delegate { Interlocked.Increment(ref gateCalls); lock (gateSaw) { gateSaw.Add(seams.WorkerSnapshot().Length); } };
            seams.Hooks.AfterWait = delegate (bool stopped) { if (Interlocked.Exchange(ref first, 1) == 0) { parkedA.Set(); releaseA.WaitOne(5000); } };
            Bg ba = Bg.Start(delegate { waitOne.Invoke(wait, new object[] { never, 1 }); waitOne.Invoke(wait, new object[] { never, 1 }); });
            c.Check(parkedA.WaitOne(5000), "worker A is parked inside its first wait (alive)");
            c.Check(seams.WorkerSnapshot().Length == 1 && seams.Reentries == 0 && gateCalls == 1 && seams.WaiterThreads.Count == 1, "worker A is recorded as instance 1; the gate was passed once", "workers=" + seams.WorkerSnapshot().Length + " gate=" + gateCalls);
            Bg b = Bg.Start(delegate { waitOne.Invoke(wait, new object[] { never, 1 }); });
            c.Check(b.Join(5000), "a second thread passes the seam while A is still alive");
            c.Check(seams.WorkerSnapshot().Length == 2 && seams.Reentries == 1 && gateCalls == 2, "a thread that starts to drive the plane while another worker is alive is counted as a re-entry", "workers=" + seams.WorkerSnapshot().Length + " reentries=" + seams.Reentries);
            releaseA.Set();
            c.Check(ba.Join(5000), "worker A finishes (its second wait included)");
            c.Check(seams.WorkerSnapshot().Length == 2 && gateCalls == 2 && seams.Reentries == 1, "a thread that is recorded already is not registered again (the identity is the thread object, not a count of calls)", "workers=" + seams.WorkerSnapshot().Length + " gate=" + gateCalls);
            Bg d = Bg.Start(delegate { waitOne.Invoke(wait, new object[] { never, 1 }); });
            d.Join(5000);
            WorkerRec[] w = seams.WorkerSnapshot();
            c.Check(w.Length == 3 && w[0].Instance == 1 && w[1].Instance == 2 && w[2].Instance == 3 && seams.Reentries == 1 && !object.ReferenceEquals(w[0].T, w[2].T), "a worker that starts after the others have ended is no re-entry; the instance sequence counts 1, 2, 3", "workers=" + w.Length + " reentries=" + seams.Reentries);
            lock (gateSaw)
            {
                c.Check(gateSaw.Count == 3 && gateSaw[0] == 0 && gateSaw[1] == 1 && gateSaw[2] == 2, "the gate sits BEFORE the registration: a thread is not yet recorded when it passes the gate", "recorded at the gate: " + gateSaw.Count + " calls, first=" + (gateSaw.Count > 0 ? gateSaw[0].ToString() : "-"));
            }
        }    }

    /// <summary>A plane served to an external process (the managed-application interop test) by Serve-LegacyJumpPlane2A.ps1: production seams, one synthetic PID, controlled from outside.</summary>
    public sealed class ServeSession : IDisposable
    {
        private readonly Ctx ctx;
        private PlaneRig rig;
        private readonly int pid;
        private readonly FakeSource src;
        private int throwNext;
        private readonly List<string> doneNames = new List<string>();

        private ServeSession(int pid)
        {
            this.pid = pid;
            ctx = new Ctx("SERVE");
            src = FakeSource.Make(pid);
        }

        public static ServeSession Open(Assembly product, string runId, int pid)
        {
            Pr.Load(product);
            Env.Init(runId);
            if (pid <= 0) pid = Env.NextPid();
            ServeSession s = new ServeSession(pid);
            s.StartPlane();
            return s;
        }

        private PlaneOpts NewOpts()
        {
            PlaneOpts o = new PlaneOpts();
            o.Pid = pid;
            o.Source = src;
            o.Hooks = delegate (SeamHooks h) { h.AfterRead = delegate { if (Interlocked.Exchange(ref throwNext, 0) == 1) throw new System.IO.IOException("injected-read"); }; };
            return o;
        }

        private void StartPlane()
        {
            rig = Kit.NewRig(ctx, NewOpts());
            rig.P.Start();
            Kit.AwaitReady(rig.P, 5000);
        }

        public int Pid { get { return pid; } }

        /// <summary>Disposes the current plane and starts a new one on the same name at once; returns the status after READY (the first CreateNew must succeed: attempts == 1).</summary>
        public string Cycle()
        {
            rig.P.Dispose();
            StartPlane();
            return Status();
        }

        /// <summary>Disposes the current plane and starts a new one, WITHOUT waiting for READY; returns the status after waitMs (a Reader that kept its handle makes the new plane retry).</summary>
        public string CycleNoWait(int waitMs)
        {
            rig.P.Dispose();
            rig = Kit.NewRig(ctx, NewOpts());
            rig.P.Start();
            Wait.Ms(waitMs);
            return Status();
        }

        /// <summary>Waits for READY (up to ms) and returns the status.</summary>
        public string AwaitReady(int ms)
        {
            Kit.AwaitReady(rig.P, ms);
            return Status();
        }

        /// <summary>The next datagram that the plane reads makes the read fail: the plane withdraws and re-creates its endpoint.</summary>
        public void ArmReceiveFault()
        {
            Interlocked.Exchange(ref throwNext, 1);
        }

        public string Status()
        {
            SnapView s = rig.P.Snapshot();
            StringBuilder sb = new StringBuilder();
            sb.Append("{\"bve_pid\":").Append(pid);
            sb.Append(",\"name\":\"").Append(rig.Name.Replace("\\", "\\\\")).Append("\"");
            sb.Append(",\"state\":\"").Append(PState.Name(s.State)).Append("\"");
            sb.Append(",\"port\":").Append(s.Port);
            sb.Append(",\"generation\":").Append(s.Generation);
            sb.Append(",\"token\":\"").Append(s.TokenHex).Append("\"");
            sb.Append(",\"app_instance\":\"").Append(src.Owner.AppInstance).Append("\"");
            sb.Append(",\"app_pid\":").Append(src.Owner.AppProcessId);
            sb.Append(",\"attempts\":").Append(s.Attempts);
            sb.Append(",\"published\":").Append(s.Published);
            sb.Append(",\"received\":").Append(s.Received);
            sb.Append(",\"outcomes\":").Append(rig.P.Outcomes().Length);
            sb.Append(",\"caps_union\":").Append(rig.Seams.CapsUnion);
            sb.Append(",\"open_ports\":").Append(rig.Seams.OpenPorts);
            sb.Append(",\"open_mappings\":").Append(rig.Seams.OpenMappings);
            sb.Append("}");
            return sb.ToString();
        }

        public string Finish()
        {
            string st = Status();
            rig.P.Dispose();
            return st;
        }

        public void Dispose()
        {
            try { rig.P.Dispose(); } catch { }
            ctx.ReleaseAll();
        }

        private static bool Same(byte[] a, byte[] b) { return FakeSource.Hex(a) == FakeSource.Hex(b); }
    }
}
