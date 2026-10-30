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
    }
}
