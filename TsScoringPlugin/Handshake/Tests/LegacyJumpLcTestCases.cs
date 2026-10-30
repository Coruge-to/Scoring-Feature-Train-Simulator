using System;
using System.Collections.Generic;
using System.Threading;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE LC-1b (Legacy scoring integration) - C# RED / characterization cases of the Legacy Jump executor. TEST CODE ONLY: never part of the product DLL.
//
// Same harness as LJX-1 (LegacyJumpExecTestFixture.cs: LxRig = the real plane + the real session + the real tick runner over a fake host and a fake sender) - these cases are
// ADDED to the partial fixture class and run by Test-LegacyJumpLC1b.ps1 only; the LJX-1 runner (33 cases) does not compile this file and is unchanged.
// NO product seam: the gate of the control plane is a private field and is taken from a second thread BY REFLECTION. Every wait is finite.
//   LC-J01  C-LJ-1  RED   the report of the execution Tick finds the gate busy twice (TickPre and TickPost): the completion of an EXECUTED jump must still be sent
//   LC-J02  C-LJ-2  RED   a host that was moved and then failed (SetClockMs throws) leaves the official jump note for the next row
//   LC-J03  C-LJ-2  RED   a read back that disagrees after the jump (the host was moved) leaves the note too
//   LC-J04  C-LJ-1  GUARD ONE busy report (TickPre only) is recovered by TickPost: the completion is sent once
//   LC-J05  C-LJ-2  GUARD a failure BEFORE the host was moved leaves no note (the LJX-32 rule must survive the fix)
// Phase LC-4 adds LC-J06..J09, LC-J02v2, LC-J03v2, LC-J05v2 (see the block comment before LC-J06).
// Written in C# 5 syntax (Windows PowerShell 5.1 Add-Type).
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpExecTestFixture
    {
        /// <summary>Holds a monitor from a second thread until released (or 10 s at the latest). Taking it is bounded by the caller.</summary>
        internal sealed class GateHolder : IDisposable
        {
            private readonly object gate;
            private readonly ManualResetEvent acquired = new ManualResetEvent(false);
            private readonly ManualResetEvent release = new ManualResetEvent(false);
            private Thread thread;

            public GateHolder(object gate) { this.gate = gate; }

            public bool Take(int waitMs)
            {
                thread = new Thread(delegate ()
                {
                    Monitor.Enter(gate);
                    try
                    {
                        acquired.Set();
                        release.WaitOne(10000);
                    }
                    finally { Monitor.Exit(gate); }
                });
                thread.IsBackground = true;
                thread.Start();
                return acquired.WaitOne(waitMs);
            }

            public void Release()
            {
                release.Set();
                Thread t = thread;
                if (t != null) t.Join(5000);
            }

            public void Dispose() { Release(); }
        }

        private static string RecText(LxRig x, byte[] rid)
        {
            LxRec r = x.Rec(rid);
            return r == null ? "null" : r.Short;
        }

        // =====================================================================================================================================
        [Case("LC-J01", "C-LJ-1: the completion of an executed jump survives a busy gate at BOTH reports of the execution Tick",
            Purpose = "an executed jump (the JUMP counter row is sent) must not end Abandoned(completion-no-payload) because the gate was busy for about 100 ms",
            Operation = "take the gate from a second thread inside the host call, TickPre, the session row, TickPost (gate still held), release, two more Ticks",
            Expected = "the command ends Completed and the completion is sent exactly once",
            Contract = "Night C C-LJ-1; LegacyJumpExecutor.TickPre/TickPost (executedThisRound)")]
        internal static void LcJ01(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            object gate = Pr.Get(x.P.Raw, "gate");
            GateHolder h = c.Own(new GateHolder(gate));
            bool tried = false;
            bool got = false;
            x.Host.InsideCall = delegate
            {
                if (tried) return;
                tried = true;
                got = h.Take(5000);
            };
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            Pr.Call(x.Runner, "TickPre");
            c.Check(tried && got, "the gate was taken inside the host call (after the claim, before the first report)", tried + "/" + got);
            c.Check(x.Host.ApiCalls == 2, "the host sequence ran", "" + x.Host.ApiCalls);
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            c.Check(x.Sender.Calls == 0, "nothing was sent while the gate was busy at both reports", "" + x.Sender.Calls);
            h.Release();
            x.Tick(16);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "the completion of the executed jump was sent exactly once and the command is Completed", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
        }

        // =====================================================================================================================================
        [Case("LC-J02", "C-LJ-2: a host that was moved and then failed (SetClockMs throws) leaves the official jump note",
            Purpose = "the vehicle moved (MoveToStation ran) although the command is Failed: the station state machine must be told, as for an executed jump",
            Operation = "ThrowOn SetClockMs, claim and host sequence (TickPre), look at the session",
            Expected = "the command is Failed and the session has the official jump note pending",
            Contract = "Night C C-LJ-2; LegacyJumpExecutor.TickPre (NoteOfficialJump only on res.Ok)")]
        internal static void LcJ02(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Host.ThrowOn = "SetClockMs";
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.PreOnly();
            c.Check(StateIs(x, rid, Ls.Failed, null), "the command is Failed", RecText(x, rid));
            c.Check(x.Host.Location == x.Host.Stations[1], "the host WAS moved (partial execution)", "" + x.Host.Location);
            c.Check((bool)Pr.Get(x.Session, "officialJumpPending"), "a moved host leaves the official jump note pending");
            c.Check((int)Pr.Get(x.Session, "officialTargetIndex") < 0, "the note of a FAILED jump carries no adopted station (the position search), not the requested one", "" + Pr.Get(x.Session, "officialTargetIndex"));
        }

        // =====================================================================================================================================
        [Case("LC-J03", "C-LJ-2: a read back that disagrees after the jump (the host was moved) leaves the official jump note",
            Purpose = "readback-* failures happen after the host sequence ran",
            Operation = "TimeSkew on the read back, claim and host sequence (TickPre), look at the session",
            Expected = "the command is Failed and the session has the official jump note pending",
            Contract = "Night C C-LJ-2")]
        internal static void LcJ03(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.Host.TimeSkew = 7000;
            x.PreOnly();
            c.Check(StateIs(x, rid, Ls.Failed, null), "the command is Failed", RecText(x, rid));
            c.Check(x.Host.Location == x.Host.Stations[1], "the host WAS moved", "" + x.Host.Location);
            c.Check((bool)Pr.Get(x.Session, "officialJumpPending"), "a moved host leaves the official jump note pending");
            c.Check((int)Pr.Get(x.Session, "officialTargetIndex") < 0, "the note of a FAILED jump carries no adopted station (the position search), not the requested one", "" + Pr.Get(x.Session, "officialTargetIndex"));
        }

        // =====================================================================================================================================
        [Case("LC-J04", "C-LJ-1: ONE busy report (TickPre only) is recovered by TickPost - the completion is sent once",
            Kind = "GUARD",
            Purpose = "the existing recovery (unreportedClaim) must survive the fix of the double-busy case",
            Operation = "take the gate inside the host call, TickPre, release, the session row, TickPost",
            Expected = "Completed and exactly one completion sent",
            Contract = "LegacyJumpExecutor.TickPost (unreportedClaim)")]
        internal static void LcJ04(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            object gate = Pr.Get(x.P.Raw, "gate");
            GateHolder h = c.Own(new GateHolder(gate));
            bool tried = false;
            bool got = false;
            x.Host.InsideCall = delegate
            {
                if (tried) return;
                tried = true;
                got = h.Take(5000);
            };
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            Pr.Call(x.Runner, "TickPre");
            c.Check(tried && got, "the gate was taken inside the host call", tried + "/" + got);
            h.Release();
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "TickPost reported and completed the jump", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
        }

        // =====================================================================================================================================
        [Case("LC-J05", "C-LJ-2: a failure BEFORE the host was moved leaves no official jump note",
            Kind = "GUARD",
            Purpose = "the fix of C-LJ-2 must note only a moved host (the LJX-32 rule)",
            Operation = "ThrowOn MoveToStation, claim and host sequence (TickPre), look at the session",
            Expected = "the command is Failed, the host did not move, no note",
            Contract = "LJX-32")]
        internal static void LcJ05(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            double before = x.Host.Location;
            x.Host.ThrowOn = "MoveToStation";
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.PreOnly();
            c.Check(StateIs(x, rid, Ls.Failed, null), "the command is Failed", RecText(x, rid));
            c.Check(x.Host.Location == before, "the host did not move", "" + x.Host.Location);
            c.Check(!(bool)Pr.Get(x.Session, "officialJumpPending"), "no note for a host that did not move");
        }

        // =====================================================================================================================================
        // Phase LC-4 additions: the contract of the completion payload (C-LJ-1) and of the note of a moved host (C-LJ-2), v1 and v2.
        //   LC-J06   C-LJ-1  RED   contract of the double busy gate: ONE host sequence, ONE completion, the same payload as without the contention, nothing outstanding, no second notice
        //   LC-J07   C-LJ-1  RED   a gate that stays busy for several Ticks: every Tick returns in bounded time, nothing is sent, the host is not called again, the release completes it
        //   LC-J08   C-LJ-1  RED   the same for a v2 command: the v2 completion carries the adopted station
        //   LC-J09   C-LJ-1  RED   a scenario boundary after the contention: the late completion is never sent across it (scenario epoch)
//   LC-J10   C-LJ-1  GUARD a held completion is retried with the payload that was made once
        //   LC-J02v2 C-LJ-2  RED   a v2 command, the host was moved, SetClockMs throws: the note carries NO station (not the success note), the station state restarts, nothing is announced
        //   LC-J03v2 C-LJ-2  RED   the same for a time read back that differs and for a location read back that differs (v2 equality)
        //   LC-J05v2 C-LJ-2  GUARD a v2 failure BEFORE the host was moved leaves no note and the station state alone
        // =====================================================================================================================================
        private sealed class Contention
        {
            public GateHolder Holder;
            public bool Tried;
            public bool Got;
        }

        /// <summary>The gate taken by a second thread inside the host call (after the claim, before the first report); the case releases it.</summary>
        private static Contention Contend(Ctx c, LxRig x)
        {
            Contention k = new Contention();
            k.Holder = c.Own(new GateHolder(Pr.Get(x.P.Raw, "gate")));
            x.Host.InsideCall = delegate
            {
                if (k.Tried) return;
                k.Tried = true;
                k.Got = k.Holder.Take(5000);
            };
            return k;
        }

        private static bool NothingOutstanding(LxRig x)
        {
            return Pr.Get(Pr.Get(x.P.Raw, "queue"), "InFlight") == null;
        }

        /// <summary>A rig whose host and Legacy API hold exactly these stations, built into the timeline (the premise of every v2 case).</summary>
        private static LxRig V2Rig(Ctx c, double[] st)
        {
            LxOpts o = new LxOpts();
            o.Warm = false;
            LxRig x = c.Own(LxRig.Make(c, o));
            x.Host.Stations = st;
            x.Api.Stations.Clear();
            for (int i = 0; i < st.Length; i++)
            {
                FakeStation f = new FakeStation();
                f.Name = "S" + i;
                f.Location = st[i];
                x.Api.Stations.Add(f);
            }
            x.Tick(16);
            x.Tick(16);
            return x;
        }

        private static string V2Text(LxRig x, string kind, int idx, double loc, int timeMs)
        {
            object tl = Pr.Get(x.Session, "timeline");
            TSScoringPlugin.DataPlane.JumpWireScope scope = new TSScoringPlugin.DataPlane.JumpWireScope(Convert.ToInt32(Pr.Get(x.Session, "ScenarioId")), (string)Pr.Get(tl, "ListId"), Convert.ToInt32(Pr.Get(tl, "Count")));
            string reason;
            string text = TSScoringPlugin.DataPlane.JumpWire.FormatRequestV2(kind, idx, timeMs, scope, loc, out reason);
            if (text == null) throw new FixtureFaultException("the fixture request can not be formatted: " + reason);
            return text;
        }

        private static int TargetOf(LxRig x)
        {
            return Convert.ToInt32(Pr.Get(Pr.Get(x.Session, "timeline"), "TargetIndex"));
        }

        private static int CountOf(LxRig x)
        {
            return Convert.ToInt32(Pr.Get(Pr.Get(x.Session, "timeline"), "Count"));
        }

        /// <summary>The target of the timeline is the station idx (the explicit seed of a rig: one shot request, consumed by the next Tick).</summary>
        private static void SeedTarget(Ctx c, LxRig x, int idx, double loc)
        {
            object tl = Pr.Get(x.Session, "timeline");
            Pr.Call(tl, "RequestTarget", idx, loc);
            Pr.Call(tl, "MarkDiscontinuity");
            x.Tick(16);
            c.Check(TargetOf(x) == idx, "PREMISE the seeded station is the target of the rig", "" + TargetOf(x));
        }

        // =====================================================================================================================================
        [Case("LC-J06", "C-LJ-1 contract: a double busy gate loses nothing - one host sequence, one completion, the payload of the uncontended run",
            Purpose = "the completion payload of an executed jump is bound to the command: it survives a gate that is busy at both reports of the execution Tick",
            Operation = "an uncontended control run, then the contended run (gate taken inside the host call, released after TickPost), two more Ticks, three more after the completion",
            Expected = "Completed, one host sequence (2 calls), one completion with the payload of the control run, nothing outstanding, nothing sent again",
            Contract = "Owner LC-4 C-LJ-1: one request, one claim, one host execution, one completion, payload kept, receipt consistent, no double notice, gate release completes")]
        internal static void LcJ06(Ctx c)
        {
            LxRig k = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] krid = Cmd.Rid();
            k.SendSta(krid, 1, 36000000);
            k.Tick(16);
            c.Check(StateIs(k, krid, Ls.Completed, null) && k.Sender.Calls == 1, "PREMISE the control run completes once", "sender " + k.Sender.Calls + " state " + RecText(k, krid));
            string control = k.Sender.LastPayload;

            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            Contention g = Contend(c, x);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            Pr.Call(x.Runner, "TickPre");
            c.Check(g.Tried && g.Got, "PREMISE the gate was taken inside the host call", g.Tried + "/" + g.Got);
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            c.Check(x.Sender.Calls == 0 && StateIs(x, rid, Ls.Executing, null), "PREMISE nothing was sent and the command is still Executing while the gate is busy", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            g.Holder.Release();
            x.Tick(16);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "C-LJ-1 contract: Completed with exactly one completion", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            c.Check(x.Host.ApiCalls == 2, "one host sequence only (MoveToStation, SetClockMs)", String.Join(";", x.Host.CallsSnapshot()));
            c.Check(control != null && x.Sender.LastPayload == control, "the payload is the payload of the uncontended run", "control=" + control + " contended=" + x.Sender.LastPayload);
            c.Check(NothingOutstanding(x), "nothing is outstanding after the completion");
            for (int i = 0; i < 3; i++) x.Tick(16);
            c.Check(x.Sender.Calls == 1 && x.Host.ApiCalls == 2, "no second notice and no second host sequence", "sender " + x.Sender.Calls + " host " + x.Host.ApiCalls);
            c.Check(x.Illegal == 0, "illegal-transition 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LC-J07", "C-LJ-1 contract: a gate that stays busy for several Ticks - bounded Ticks, nothing sent, the host not called again, the release completes it",
            Purpose = "the wait is finite: a busy gate delays the completion, it never blocks the host Tick for long and never loses the command",
            Operation = "the gate stays taken for 5 Ticks (each timed), then released, then 2 Ticks",
            Expected = "each Tick below 2 s; 2 host calls and 0 completions while busy; Completed with one completion after the release",
            Contract = "Owner LC-4 C-LJ-1: timeout finite, completion possible after the gate is released")]
        internal static void LcJ07(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            Contention g = Contend(c, x);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            long worst = 0;
            System.Diagnostics.Stopwatch sw = new System.Diagnostics.Stopwatch();
            for (int i = 0; i < 5; i++)
            {
                sw.Reset();
                sw.Start();
                if (i == 0)
                {
                    Pr.Call(x.Runner, "TickPre");
                    Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
                    Pr.Call(x.Runner, "TickPost");
                }
                else x.Tick(16);
                sw.Stop();
                if (sw.ElapsedMilliseconds > worst) worst = sw.ElapsedMilliseconds;
            }
            c.Check(g.Tried && g.Got, "PREMISE the gate was taken inside the host call", g.Tried + "/" + g.Got);
            c.Check(worst < 2000, "every Tick returned in bounded time while the gate stayed busy", "worst " + worst + " ms");
            c.Check(x.Host.ApiCalls == 2, "the host was not called again while the report is pending", String.Join(";", x.Host.CallsSnapshot()));
            c.Check(x.Sender.Calls == 0 && StateIs(x, rid, Ls.Executing, null), "nothing was sent and the command is still Executing", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            g.Holder.Release();
            x.Tick(16);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "after the release the command completes with exactly one completion", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            c.Check(x.Host.ApiCalls == 2, "and the host still ran one sequence only", String.Join(";", x.Host.CallsSnapshot()));
        }

        // =====================================================================================================================================
        [Case("LC-J08", "C-LJ-1 contract (v2): a double busy gate - the v2 completion carries the adopted station and is sent once",
            Purpose = "the nine field v2 completion is made once for the executed command, whatever the gate did at the reports",
            Operation = "a v2 station command for index 2; the gate taken inside the host call, released after TickPost; two more Ticks",
            Expected = "Completed, one completion that parses as v2 with selected_idx 2, one host sequence",
            Contract = "Owner LC-4 C-LJ-1 (v2 side); ST-3c completion")]
        internal static void LcJ08(Ctx c)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = V2Rig(c, st);
            Contention g = Contend(c, x);
            byte[] rid = Cmd.Rid();
            RecView q = x.Send(V2Text(x, "STA", 2, st[2], x.Host.TimeMs), 0x100U, rid);
            c.Check(q != null && q.State == CState.Queued, "PREMISE the v2 station command is queued", q == null ? "null" : q.Short);
            Pr.Call(x.Runner, "TickPre");
            c.Check(g.Tried && g.Got, "PREMISE the gate was taken inside the host call", g.Tried + "/" + g.Got);
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            g.Holder.Release();
            x.Tick(16);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "C-LJ-1 contract (v2): Completed with exactly one completion", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            string reason;
            TSScoringPlugin.DataPlane.JumpWireCompletion cc = x.Sender.LastPayload == null ? null : TSScoringPlugin.DataPlane.JumpWire.ParseCompletion(x.Sender.LastPayload, out reason);
            c.Check(cc != null && cc.Version == 2 && cc.SelectedIndex == 2, "the completion is a v2 completion of the adopted station 2", x.Sender.LastPayload);
            c.Check(x.Host.ApiCalls == 2 && NothingOutstanding(x), "one host sequence, nothing outstanding", String.Join(";", x.Host.CallsSnapshot()));
        }

        // =====================================================================================================================================
        [Case("LC-J09", "C-LJ-1 contract: a scenario boundary after the contention - the late completion is never sent across it",
            Purpose = "keeping the payload must not let a completion of the previous scenario reach the new one (scenario epoch)",
            Operation = "the contention as in LC-J06, release, a scenario boundary, two Ticks",
            Expected = "no completion is sent, the command ends Abandoned(completion-scenario-changed), nothing is outstanding",
            Contract = "Owner LC-4: scenario epoch mismatch is never executed or announced; no outstanding command")]
        internal static void LcJ09(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            Contention g = Contend(c, x);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            Pr.Call(x.Runner, "TickPre");
            c.Check(g.Tried && g.Got, "PREMISE the gate was taken inside the host call", g.Tried + "/" + g.Got);
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            Pr.Call(x.Runner, "TickPost");
            g.Holder.Release();
            x.P.NoteScenarioBoundary();
            x.Tick(16);
            x.Tick(16);
            LxRec r = x.Rec(rid);
            c.Check(x.Sender.Calls == 0, "no completion crossed the boundary", "" + x.Sender.Calls);
            c.Check(r != null && r.State == Ls.Abandoned && r.Reason == "completion-scenario-changed", "the command ended Abandoned(completion-scenario-changed)", RecText(x, rid));
            c.Check(NothingOutstanding(x), "nothing is outstanding");
            c.Check(x.Host.ApiCalls == 2, "the host ran one sequence only", String.Join(";", x.Host.CallsSnapshot()));
        }

        // =====================================================================================================================================
        [Case("LC-J10", "C-LJ-1 contract: a held completion is retried with the payload that was made ONCE (a JUMP counter that moves meanwhile does not change it)",
            Kind = "GUARD",
            Purpose = "the payload belongs to the executed command: it is made once, so the retries of a held send carry the same text and the same counter",
            Operation = "the sender answers Held; the host clock jumps by hand (the session counts a discontinuity, the JUMP counter of the rows moves); the next Tick sends",
            Expected = "the second attempt carries the payload of the first; the command is Completed with two attempts",
            Contract = "LJX-22 (same payload and id on a retry); Owner LC-4 C-LJ-1: payload kept")]
        internal static void LcJ10(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Sender.Script.Enqueue(Ls.SendHeld);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.CompletionPending, null) && x.Sender.Calls == 1, "PREMISE the first attempt was held", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            string first = x.Sender.LastPayload;
            int countAtFirst = Convert.ToInt32(Pr.Get(x.Session, "LastLineJumpCount"));
            x.Host.TimeMs += 5000000;
            x.Tick(16);
            int countNow = Convert.ToInt32(Pr.Get(x.Session, "LastLineJumpCount"));
            c.Check(countNow != countAtFirst, "PREMISE the JUMP counter of the rows moved meanwhile", countAtFirst + " -> " + countNow);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 2, "the second attempt completed it", "sender " + x.Sender.Calls + " state " + RecText(x, rid));
            c.Check(first != null && x.Sender.Payloads.Count == 2 && x.Sender.Payloads[1] == first, "the retry carries the payload that was made once", "first=" + first + " second=" + (x.Sender.Payloads.Count > 1 ? x.Sender.Payloads[1] : "-"));
        }
        // =====================================================================================================================================
        private static void MovedFailureV2(Ctx c, string label, Action<LxRig> inject)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = V2Rig(c, st);
            SeedTarget(c, x, 1, st[1]);
            inject(x);
            int timeMs = x.Host.TimeMs;
            byte[] rid = Cmd.Rid();
            RecView q = x.Send(V2Text(x, "STA", 2, st[2], timeMs), 0x100U, rid);
            c.Check(q != null && q.State == CState.Queued, label + ": PREMISE the v2 station command is queued", q == null ? "null" : q.Short);
            x.PreOnly();
            c.Check(StateIs(x, rid, Ls.Failed, null), label + ": the command is Failed", RecText(x, rid));
            c.Check(x.Host.Location == st[2], label + ": the host WAS moved to the adopted station", "" + x.Host.Location);
            string calls = String.Join(";", x.Host.CallsSnapshot());
            c.Check(calls == "MoveToStation(2);SetClockMs(" + timeMs + ")", label + ": one host sequence, the adopted station only (no other station, no retry)", calls);
            c.Check((bool)Pr.Get(x.Session, "officialJumpPending"), label + ": a moved host leaves the official jump note pending");
            c.Check((int)Pr.Get(x.Session, "officialTargetIndex") < 0, label + ": the note carries NO station (neither the adopted one nor a searched one: not the success note)", "" + Pr.Get(x.Session, "officialTargetIndex"));
            c.Check(x.Sender.Calls == 0, label + ": no completion is announced for a failed jump", "" + x.Sender.Calls);
            c.Check(NothingOutstanding(x), label + ": nothing is outstanding");
            x.Tick(16);
            c.Check(TargetOf(x) != 1 && TargetOf(x) != 2 && TargetOf(x) >= CountOf(x), label + ": the station state restarted with the target UNSET (the old target is gone, no station is chosen from the position although the vehicle stands at station 2)", "target " + TargetOf(x) + " count " + CountOf(x));
            c.Check(!(bool)Pr.Get(x.Session, "officialJumpPending"), label + ": the next row consumed the note");
            c.Check(x.Sender.Calls == 0, label + ": still no completion", "" + x.Sender.Calls);
        }

        [Case("LC-J02v2", "C-LJ-2 (v2): a v2 command, the host was moved, SetClockMs throws - the note carries no station and the station state restarts",
            Purpose = "closes C07: only a v2 command can tell the note with an adopted station (the success note) from the note without one",
            Operation = "seed the target 1, ThrowOn SetClockMs, a v2 station command for index 2 at the current clock, claim and host sequence, one row",
            Expected = "Failed, note pending with no station, no completion, after the row the target is UNSET (not 1, not 2)",
            Contract = "Owner LC-4 C-LJ-2: no adopted station, no fallback station, no distance search, no success note, no false completion")]
        internal static void LcJ02v2(Ctx c)
        {
            MovedFailureV2(c, "SetClockMs throws", delegate (LxRig x) { x.Host.ThrowOn = "SetClockMs"; });
        }

        [Case("LC-J03v2", "C-LJ-2 (v2): a v2 command, the host was moved, a read back disagrees (time, location) - the note carries no station",
            Purpose = "readback-* failures happen after the host sequence ran; for a v2 command the location must EQUAL the adopted station",
            Operation = "the contract of LC-J02v2 with TimeSkew 7000, then with LocationSkew 0.5",
            Expected = "Failed, note pending with no station, no completion, the target UNSET after the row",
            Contract = "Owner LC-4 C-LJ-2")]
        internal static void LcJ03v2(Ctx c)
        {
            MovedFailureV2(c, "time read back", delegate (LxRig x) { x.Host.TimeSkew = 7000; });
            MovedFailureV2(c, "location read back", delegate (LxRig x) { x.Host.LocationSkew = 0.5; });
        }

        [Case("LC-J05v2", "C-LJ-2 (v2): a failure BEFORE the host was moved leaves no note and the station state alone",
            Kind = "GUARD",
            Purpose = "the fix of C-LJ-2 must note only a moved host, for a v2 command too",
            Operation = "seed the target 1, ThrowOn MoveToStation, a v2 station command for index 2, claim and host sequence, one row",
            Expected = "Failed, the host did not move, no note, the target stays 1, no completion",
            Contract = "LJX-32; Owner LC-4 C-LJ-2")]
        internal static void LcJ05v2(Ctx c)
        {
            double[] st = new double[] { 100.5, 1000.5, 2000.25, 3000.125 };
            LxRig x = V2Rig(c, st);
            SeedTarget(c, x, 1, st[1]);
            double before = x.Host.Location;
            x.Host.ThrowOn = "MoveToStation";
            byte[] rid = Cmd.Rid();
            int timeMs = x.Host.TimeMs;
            RecView q = x.Send(V2Text(x, "STA", 2, st[2], timeMs), 0x100U, rid);
            c.Check(q != null && q.State == CState.Queued, "PREMISE the v2 station command is queued", q == null ? "null" : q.Short);
            x.PreOnly();
            c.Check(StateIs(x, rid, Ls.Failed, null), "the command is Failed", RecText(x, rid));
            c.Check(x.Host.Location == before, "the host did not move", "" + x.Host.Location);
            c.Check(!(bool)Pr.Get(x.Session, "officialJumpPending"), "no note for a host that did not move");
            x.Tick(16);
            c.Check(TargetOf(x) == 1, "the station state is left alone (target 1)", "" + TargetOf(x));
            c.Check(x.Sender.Calls == 0, "no completion", "" + x.Sender.Calls);
        }
    }
}
