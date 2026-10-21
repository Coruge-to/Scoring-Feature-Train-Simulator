using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP LJX-1 - the cases (RED first). See LegacyJumpExecTestFixture.cs for the pinned product elements and the rules of the harness.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpExecTestFixture
    {
        // ---- helpers of the cases ---------------------------------------------------------------------------------------------------------------
        internal static object OkResult(long elapsedMs, int timeMs, double location)
        {
            object r = Pr.New(Pr.T("LegacyJumpExecResult"));
            Pr.Set(r, "Ok", true);
            Pr.Set(r, "Step", "done");
            Pr.Set(r, "ElapsedMs", elapsedMs);
            Pr.Set(r, "ReadBackTimeMs", timeMs);
            Pr.Set(r, "ReadBackLocation", location);
            return r;
        }

        internal static object FailResult(string reason)
        {
            object r = Pr.New(Pr.T("LegacyJumpExecResult"));
            Pr.Set(r, "Ok", false);
            Pr.Set(r, "Step", "failed");
            Pr.Set(r, "Reason", reason);
            return r;
        }

        /// <summary>Takes a claimed ticket through report (ok) and the completion, the way the tick runner would: the receipt ends Completed.</summary>
        internal static int FinishTicket(LxRig x, object ticket)
        {
            Pr.Call(x.P.Raw, "ReportExecution", ticket, OkResult(1, 36000000, 1000.0));
            Pr.Set(ticket, "Payload", Encoding.UTF8.GetBytes("JUMP_COMPLETE:STA:1:1000:36000000:1"));
            return Convert.ToInt32(Pr.Call(x.P.Raw, "TryCompleteInPostSession", ticket, x.NewFacts(true, true), x.Sender.Obj));
        }

        internal static bool StateIs(LxRig x, byte[] rid, int state, string reason)
        {
            LxRec r = x.Rec(rid);
            return r != null && r.State == state && (reason == null || r.Reason == reason);
        }

        internal static bool AwaitState(LxRig x, byte[] rid, int state, string reason, int ms)
        {
            return Wait.For(delegate { return StateIs(x, rid, state, reason); }, ms);
        }

        // =====================================================================================================================================
        [Case("LJX-01", "claim is exclusive: one winner among racing claimers",
            Purpose = "the Queued to Executing transition has one entry and one winner (INV-3)",
            Operation = "8 threads call TryClaimForTick at the same instant on one Queued command, 12 rounds",
            Expected = "exactly one ticket per round, the receipt is Executing, illegal-transition 0",
            Contract = "LJX-1 spec 3.1 / 3.3; invariant INV-3")]
        internal static void Ljx01(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            int badRounds = 0;
            for (int round = 0; round < 12; round++)
            {
                byte[] rid = Cmd.Rid();
                RecView rv = x.SendSta(rid, 1, 36000000);
                if (rv == null || rv.State != CState.Queued) { c.Check(false, "the command was queued in round " + round, rv == null ? "null" : rv.Short); return; }
                int winners = 0;
                object won = null;
                ManualResetEvent go = new ManualResetEvent(false);
                List<Bg> threads = new List<Bg>();
                for (int k = 0; k < 8; k++)
                {
                    threads.Add(Bg.Make(delegate
                    {
                        go.WaitOne(3000);
                        // a claim that finds the gate busy (the worker is stepping) returns nothing and is tried again; after the win every further claim must return nothing
                        for (int attempt = 0; attempt < 25; attempt++)
                        {
                            object t = x.Claim();
                            if (t != null) { lock (threads) { winners++; won = t; } }
                        }
                    }));
                }
                foreach (Bg b in threads) b.Begin();
                go.Set();
                foreach (Bg b in threads) b.Join(5000);
                bool ok = winners == 1 && StateIs(x, rid, Ls.Executing, null);
                if (!ok) { badRounds++; c.Info("round " + round + ": winners=" + winners + " state=" + (x.Rec(rid) == null ? "?" : x.Rec(rid).Short)); }
                if (won != null) FinishTicket(x, won);
            }
            c.Check(badRounds == 0, "every round has exactly one winner and an Executing receipt", badRounds + " bad rounds");
            c.Check(x.Illegal == 0, "illegal-transition is 0", "" + x.Illegal);
            c.Check(x.Counter("claimed") == 12, "claimed counts one per round", "" + x.Counter("claimed"));
        }

        // =====================================================================================================================================
        [Case("LJX-02", "Queued and Discarded exclude each other (claim against the TTL expiry)",
            Purpose = "a command is either claimed or discarded, never both",
            Operation = "20 rounds: a claimer and a clock mover race at the TTL boundary",
            Expected = "claimed => Executing and age <= TTL; not claimed => Discarded(ttl); never both; no host call; illegal-transition 0",
            Contract = "LJX-1 spec 3.1; invariant INV-2")]
        internal static void Ljx02(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            int bad = 0, claimedRounds = 0, discardedRounds = 0;
            for (int round = 0; round < 20; round++)
            {
                byte[] rid = Cmd.Rid();
                RecView rv = x.SendSta(rid, 1, 36000000);
                if (rv == null) { c.Check(false, "queued in round " + round); return; }
                x.Clk.Advance(5000);
                object ticket = null;
                ManualResetEvent go = new ManualResetEvent(false);
                Bg a = Bg.Make(delegate { go.WaitOne(3000); ticket = x.Claim(); });
                Bg b = Bg.Make(delegate { go.WaitOne(3000); x.Clk.Advance(1); });
                a.Begin(); b.Begin(); go.Set(); a.Join(5000); b.Join(5000);
                Wait.For(delegate { LxRec r0 = x.Rec(rid); return r0 != null && r0.State != Ls.Queued; }, 2000);
                LxRec r = x.Rec(rid);
                if (ticket != null)
                {
                    claimedRounds++;
                    if (r.State != Ls.Executing || r.AgeAtClaimMs > 5000) { bad++; c.Info("claimed round " + round + ": " + r.Short + " age=" + r.AgeAtClaimMs); }
                    FinishTicket(x, ticket);
                }
                else
                {
                    discardedRounds++;
                    if (r.State != Ls.Discarded || r.Reason != "ttl") { bad++; c.Info("unclaimed round " + round + ": " + r.Short); }
                }
            }
            c.Check(bad == 0, "every round ends claimed-and-Executing or Discarded(ttl)", bad + " bad rounds; claimed " + claimedRounds + ", discarded " + discardedRounds);
            c.Check(x.Host.ApiCalls == 0, "no host call was made by the claim race alone", "" + x.Host.ApiCalls);
            c.Check(x.Illegal == 0, "illegal-transition is 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LJX-03", "Executing and Discarded exclude each other",
            Purpose = "a claimed command never becomes Discarded (INV-2: Discarded means no host call)",
            Operation = "claim, then drive every discard cause (scenario boundary, clock beyond the TTL, owner change) and Dispose",
            Expected = "the receipt stays Executing until Dispose, which makes it Abandoned(dispose); never Discarded",
            Contract = "LJX-1 spec 3.3; invariant INV-2")]
        internal static void Ljx03(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            object ticket = x.Claim();
            c.Check(ticket != null, "the command was claimed");
            x.P.NoteScenarioBoundary();
            x.Clk.Advance(9000);
            x.R.Src.Owner = FakeSource.NewOwner(x.R.Pid);
            Kit.Settle(x.P, 8, 3000);
            LxRec r = x.Rec(rid);
            c.Check(r != null && r.State == Ls.Executing, "after every discard cause the receipt is still Executing", r == null ? "null" : r.Short);
            x.P.Dispose();
            r = x.Rec(rid);
            c.Check(r != null && r.State == Ls.Abandoned && r.Reason == "dispose", "Dispose abandons it, it is not Discarded", r == null ? "null" : r.Short);
            c.Check(x.Illegal == 0, "illegal-transition is 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LJX-04", "TTL value: 5.0 s, strictly between 0 and 10 s, in the product environment",
            Purpose = "the Legacy Queue TTL contract",
            Operation = "read the pinned constant and the environments the product builds",
            Expected = "ExecutionTtlMs == 5000 and 0 < TTL < 10000; execution ON environment: TtlMs 5000, features 7; default environment: TtlMs 0",
            Contract = "owner decision of the O-1 acceptance; the 10.0 s wait of the managed application is pinned statically")]
        internal static void Ljx04(Ctx c)
        {
            long ttl = Convert.ToInt64(Pr.GetStatic(Pr.T("LegacyJumpTimings"), "ExecutionTtlMs"));
            c.Check(ttl == 5000L, "ExecutionTtlMs is 5000", "" + ttl);
            c.Check(ttl > 0L && ttl < 10000L, "0 < TTL < 10000 (the managed application waits 10.0 s)", "" + ttl);
            Type env = Pr.T("LegacyJumpEnvironment");
            object on = Pr.CallStatic(env, "Production", Env.NextPid(), (Action<string>)delegate { }, true);
            object tmOn = Pr.Get(on, "Timings");
            c.Check(Convert.ToInt64(Pr.Get(tmOn, "TtlMs")) == 5000L, "the execution environment has TtlMs 5000", "" + Pr.Get(tmOn, "TtlMs"));
            c.Check((bool)Pr.Get(on, "ExecutionEnabled"), "the execution environment is enabled");
            c.Check(Convert.ToInt32(Pr.Get(on, "FeatureBits")) == 7, "the execution environment has all three features", "" + Pr.Get(on, "FeatureBits"));
            object off = Pr.CallStatic(env, "Production", Env.NextPid(), (Action<string>)delegate { });
            object tmOff = Pr.Get(off, "Timings");
            bool offEnabled = (bool)Pr.Get(off, "ExecutionEnabled");
            c.Check(offEnabled == ExpectCompiledIn, "the default environment follows the build flag", "enabled=" + offEnabled + " expected=" + ExpectCompiledIn);
            if (!ExpectCompiledIn) c.Check(Convert.ToInt64(Pr.Get(tmOff, "TtlMs")) == 0L, "the default (flag OFF) environment keeps TtlMs 0", "" + Pr.Get(tmOff, "TtlMs"));
        }

        // =====================================================================================================================================
        [Case("LJX-05", "an expired command is Discarded(ttl) and the host is never called",
            Purpose = "Pause: the Tick stops, the worker keeps sweeping",
            Operation = "queue a command, advance the clock beyond 5.0 s with no Tick, then Tick; and the boundary at exactly 5.0 s",
            Expected = "Discarded(ttl) with 0 host calls; at exactly 5000 ms the command is still claimable and is executed",
            Contract = "owner decision TTL 5.0 s; Discarded means the host API was never called")]
        internal static void Ljx05(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.Clk.Advance(5001);
            c.Check(AwaitState(x, rid, Ls.Discarded, "ttl", 3000), "Pause: the sweep discards the command (ttl)", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            x.Tick(16);
            c.Check(x.Host.ApiCalls == 0, "the host was never called for the expired command", "" + x.Host.ApiCalls);
            c.Check(x.Sender.Calls == 0, "no completion was sent", "" + x.Sender.Calls);
            byte[] rid2 = Cmd.Rid();
            x.SendSta(rid2, 2, 36500000);
            x.Clk.Advance(5000);
            Kit.Settle(x.P, 6, 3000);
            c.Check(StateIs(x, rid2, Ls.Queued, null), "at exactly 5000 ms the command is still Queued", x.Rec(rid2) == null ? "null" : x.Rec(rid2).Short);
            x.Tick(16);
            c.Check(x.Host.ApiCalls == 2, "the boundary command was executed (two host calls)", "" + x.Host.ApiCalls);
            c.Check(StateIs(x, rid2, Ls.Completed, null), "and completed", x.Rec(rid2) == null ? "null" : x.Rec(rid2).Short);
            c.Check(x.Counter("discarded:ttl") == 1, "one ttl discard in the books", "" + x.Counter("discarded:ttl"));
        }

        // =====================================================================================================================================
        [Case("LJX-06", "a scenario boundary discards the command (scenario-epoch) and the host is never called",
            Purpose = "reload: a command of the previous scenario must not move the new one",
            Operation = "queue, NoteScenarioBoundary, then Tick; and the claim racing the sweep",
            Expected = "Discarded(scenario-epoch), 0 host calls, no ticket",
            Contract = "owner decision: Discarded(scenario-epoch)")]
        internal static void Ljx06(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.P.NoteScenarioBoundary();
            c.Check(AwaitState(x, rid, Ls.Discarded, "scenario-epoch", 3000), "the sweep discards it (scenario-epoch)", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            x.Tick(16);
            c.Check(x.Host.ApiCalls == 0, "the host was never called", "" + x.Host.ApiCalls);
            for (int i = 0; i < 6; i++)
            {
                byte[] r2 = Cmd.Rid();
                x.SendSta(r2, 1, 36000000);
                x.P.NoteScenarioBoundary();
                object t = x.Claim();
                Wait.For(delegate { LxRec q = x.Rec(r2); return q != null && q.State != Ls.Queued; }, 2000);
                c.Check(t == null && StateIs(x, r2, Ls.Discarded, "scenario-epoch"), "the claim after a boundary gets nothing (round " + i + ")", x.Rec(r2) == null ? "null" : x.Rec(r2).Short);
            }
            c.Check(x.Host.ApiCalls == 0, "still no host call", "" + x.Host.ApiCalls);
        }

        // =====================================================================================================================================
        [Case("LJX-07", "STA: parse, host sequence, effect, completion",
            Purpose = "station jump = Initialize(index) then SetTime(time), executed on the Tick",
            Operation = "JUMP_STA_TIME:2:36100000, one Tick",
            Expected = "host calls [MoveToStation(2), SetClockMs(36100000)] in this order; location 2000; receipt Completed",
            Contract = "LJX-1 spec 4")]
        internal static void Ljx07(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 2, 36100000);
            c.Check(x.Host.ApiCalls == 0, "queuing alone does not call the host", "" + x.Host.ApiCalls);
            x.Tick(16);
            string[] calls = x.Host.CallsSnapshot();
            c.Check(calls.Length == 2 && calls[0] == "MoveToStation(2)" && calls[1] == "SetClockMs(36100000)", "the two host calls in order", string.Join(" ; ", calls));
            c.Check(Math.Abs(x.Host.Location - 2000.0) < 0.01 && x.Host.TimeMs == 36100000, "the effect on the fake scenario", x.Host.Location + " / " + x.Host.TimeMs);
            c.Check(StateIs(x, rid, Ls.Completed, null), "the receipt is Completed", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            c.Check(x.Host.MaxInside == 1, "never two host calls at once", "" + x.Host.MaxInside);
        }

        // =====================================================================================================================================
        [Case("LJX-08", "LOC: parse, host sequence, effect, completion",
            Purpose = "location jump = InitializeTimeAndLocation(location, time) then SetTime(time)",
            Operation = "JUMP_LOC_TIME:1234.5:36200000, one Tick",
            Expected = "host calls [MoveToLocation(1234.5,36200000), SetClockMs(36200000)]; receipt Completed",
            Contract = "LJX-1 spec 4")]
        internal static void Ljx08(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendLoc(rid, 1234.5, 36200000);
            x.Tick(16);
            string[] calls = x.Host.CallsSnapshot();
            c.Check(calls.Length == 2 && calls[0] == "MoveToLocation(1234.5,36200000)" && calls[1] == "SetClockMs(36200000)", "the two host calls in order", string.Join(" ; ", calls));
            c.Check(Math.Abs(x.Host.Location - 1234.5) < 0.01 && x.Host.TimeMs == 36200000, "the effect on the fake scenario", x.Host.Location + " / " + x.Host.TimeMs);
            c.Check(StateIs(x, rid, Ls.Completed, null), "the receipt is Completed", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            string kind; int idx; double loc; int time; int count;
            bool ok = ReadsAsComplete(x.Sender.LastPayload, out kind, out idx, out loc, out time, out count);
            c.Check(ok && kind == "LOC" && idx == -1 && Math.Abs(loc - 1234.5) < 0.01 && time == 36200000, "the LOC completion reads as the managed application reads it", x.Sender.LastPayload);
        }

        // =====================================================================================================================================
        [Case("LJX-09", "malformed commands are refused before the host is touched",
            Purpose = "validator grammar and the executor argument checks",
            Operation = "bad grammar datagrams; tickets with bad index, time or location",
            Expected = "Rejected(payload-grammar); Failed(bad-args / station-out-of-range / readback-unavailable) with 0 host calls",
            Contract = "LJX-1 spec 4 (arguments are checked before the call)")]
        internal static void Ljx09(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            string[][] bad = new string[][]
            {
                new string[] { "JUMP_STA_TIME:x:36000", "256" }, new string[] { "JUMP_STA_TIME:1", "256" }, new string[] { "JUMP_STA_TIME:1:2:3", "256" },
                new string[] { "JUMP_LOC_TIME:NaN:36000", "257" }, new string[] { "JUMP_LOC_TIME:1.5", "257" }, new string[] { "JUMP_STA_TIME:1:36000", "257" },
                new string[] { "JUMP_LOC_TIME:1.5:36000", "256" }, new string[] { "JUMP_STA_TIME:1:abc", "256" }
            };
            int notRejected = 0;
            foreach (string[] b in bad)
            {
                RecView rv = x.Send(b[0], UInt32.Parse(b[1], CultureInfo.InvariantCulture), Cmd.Rid());
                if (rv == null || rv.State != CState.Rejected || rv.Reason != "payload-grammar") { notRejected++; c.Info("not rejected: " + b[0] + " -> " + (rv == null ? "null" : rv.Short)); }
            }
            c.Check(notRejected == 0, "every malformed datagram is Rejected(payload-grammar)", notRejected + " not rejected");
            c.Check(x.Claim() == null, "nothing was queued, nothing is claimable");
            object[] tickets = new object[]
            {
                Ticket(x, 1, -1, 0.0, 36000000), Ticket(x, 1, 4, 0.0, 36000000), Ticket(x, 1, 1000, 0.0, 36000000), Ticket(x, 1, 1, 0.0, -1), Ticket(x, 1, 1, 0.0, 172800001),
                Ticket(x, 2, -1, double.NaN, 36000000), Ticket(x, 2, -1, double.PositiveInfinity, 36000000), Ticket(x, 2, -1, 10.0, -5), Ticket(x, 2, -1, 10.0, 172800001), Ticket(x, 9, -1, 10.0, 36000000)
            };
            int executed = 0;
            foreach (object t in tickets)
            {
                object res = Pr.Call(x.Executor, "Execute", t, (Func<int>)delegate { return 0; });
                if ((bool)Pr.Get(res, "Ok")) executed++;
            }
            c.Check(executed == 0, "no bad ticket executes", executed + " executed");
            c.Check(x.Host.ApiCalls == 0, "the host was never called for a bad ticket", "" + x.Host.ApiCalls);
            x.Host.ReadBackUnreadable = true;
            object r2 = Pr.Call(x.Executor, "Execute", Ticket(x, 1, 1, 0.0, 36000000), (Func<int>)delegate { return 0; });
            c.Check(!(bool)Pr.Get(r2, "Ok") && (string)Pr.Get(r2, "Reason") == "readback-unavailable" && x.Host.ApiCalls == 0, "an unreadable scenario fails closed before any call", "" + Pr.Get(r2, "Reason"));
        }

        // =====================================================================================================================================
        [Case("LJX-10", "stale generation / token / receiver generation never reach the host",
            Purpose = "the validator refuses stale datagrams; the claim re-checks the receiver generation",
            Operation = "wrong generation, wrong token; then a receiver generation that no longer matches at claim time",
            Expected = "Rejected(generation-mismatch / token-mismatch); Discarded(endpoint-recreated); 0 host calls",
            Contract = "LJX-1 spec 3.1 (success conditions); D0B-1 13.3")]
        internal static void Ljx10(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] g = Cmd.Envelope(0x100U, (UInt32)x.R.Pid, x.R.Src.Owner.AppProcessId, x.Snap.Generation + 1U, x.R.Src.Owner.AppInstance, x.Snap.Token, Cmd.Rid(), "JUMP_STA_TIME:1:36000000");
            RecView r1 = Kit.SendAndAwait(x.R, x.Snap, g, 4000);
            c.Check(r1 != null && r1.State == CState.Rejected && r1.Reason == "generation-mismatch", "wrong generation is Rejected", r1 == null ? "null" : r1.Short);
            byte[] tk = (byte[])x.Snap.Token.Clone();
            tk[0] ^= 0x5A;
            byte[] t = Cmd.Envelope(0x100U, (UInt32)x.R.Pid, x.R.Src.Owner.AppProcessId, x.Snap.Generation, x.R.Src.Owner.AppInstance, tk, Cmd.Rid(), "JUMP_STA_TIME:1:36000000");
            RecView r2 = Kit.SendAndAwait(x.R, x.Snap, t, 4000);
            c.Check(r2 != null && r2.State == CState.Rejected && r2.Reason == "token-mismatch", "wrong token is Rejected", r2 == null ? "null" : r2.Short);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            object queue = Pr.Get(x.P.Raw, "queue");
            object live = Pr.Get(queue, "Queued");
            Pr.Set(live, "ReceiverGeneration", Convert.ToUInt32(Pr.Get(live, "ReceiverGeneration")) + 1U);
            object ticket = x.Claim();
            Wait.For(delegate { LxRec q = x.Rec(rid); return q != null && q.State != Ls.Queued; }, 2000);
            c.Check(ticket == null && StateIs(x, rid, Ls.Discarded, "endpoint-recreated"), "a receiver generation that moved on is Discarded(endpoint-recreated)", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            c.Check(x.Host.ApiCalls == 0, "0 host calls", "" + x.Host.ApiCalls);
        }

        // =====================================================================================================================================
        [Case("LJX-11", "an owner that changed or went away before the claim: Discarded, no host call",
            Purpose = "claim-time re-check of the owner (AIC 2)",
            Operation = "queue, then replace the owner / make it unresolvable, then claim",
            Expected = "Discarded(owner-changed / owner-lost), no ticket, 0 host calls",
            Contract = "LJX-1 spec 3.1")]
        internal static void Ljx11(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.R.Src.Owner = FakeSource.NewOwner(x.R.Pid);
            object t = x.Claim();
            Wait.For(delegate { LxRec q = x.Rec(rid); return q != null && q.State != Ls.Queued; }, 2000);
            LxRec r = x.Rec(rid);
            c.Check(t == null && r != null && r.State == Ls.Discarded && r.Reason == "owner-changed", "a changed owner", r == null ? "null" : r.Short);
            byte[] rid2 = Cmd.Rid();
            x.R.Src.Owner = FakeSource.NewOwner(x.R.Pid);
            x.SendSta(rid2, 1, 36000000);
            x.R.Src.Ok = false;
            object t2 = x.Claim();
            Wait.For(delegate { LxRec q = x.Rec(rid2); return q != null && q.State != Ls.Queued; }, 2000);
            LxRec r2 = x.Rec(rid2);
            c.Check(t2 == null && r2 != null && r2.State == Ls.Discarded && r2.Reason == "owner-lost", "a lost owner", r2 == null ? "null" : r2.Short);
            c.Check(x.Host.ApiCalls == 0, "0 host calls", "" + x.Host.ApiCalls);
        }

        // =====================================================================================================================================
        [Case("LJX-12", "RequestId echo, JUMP counter and jump_count agree",
            Purpose = "the completion answers the right request and carries the counter that the row of the execution Tick carries",
            Operation = "one STA and one LOC through the real session; read the row and the completion",
            Expected = "RequestId bytes equal; jump_count == JUMP of the row == Discontinuities; the completion reads as the managed application reads it",
            Contract = "LJX-1 spec 5 / 6; invariant INV-5")]
        internal static void Ljx12(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36300000);
            x.Tick(16);
            string row = x.LastTelemetryLine();
            c.Check(x.Sender.Calls == 1 && x.Sender.Ids[0] == FakeSource.Hex(rid), "one completion that echoes the RequestId", x.Sender.Calls + " " + (x.Sender.Ids.Count > 0 ? x.Sender.Ids[0] : ""));
            string kind; int idx; double loc; int time; int count;
            bool ok = ReadsAsComplete(x.Sender.LastPayload, out kind, out idx, out loc, out time, out count);
            c.Check(ok && kind == "STA" && idx == 1 && Math.Abs(loc - 1000.0) < 0.01 && time == 36300000, "the STA completion reads as the managed application reads it", x.Sender.LastPayload);
            int disc = Convert.ToInt32(Pr.Get(x.Session, "Discontinuities"));
            c.Check(count == disc && disc == 1, "jump_count equals the session counter (1)", count + " / " + disc);
            c.Check(row != null && row.IndexOf(",JUMP:" + disc + ",", StringComparison.Ordinal) >= 0 || (row != null && row.EndsWith(",JUMP:" + disc, StringComparison.Ordinal)), "the row of the execution Tick carries JUMP:" + disc, row);
            c.Check(Convert.ToInt32(Pr.Get(x.Session, "LastLineJumpCount")) == disc, "LastLineJumpCount is that value", "" + Pr.Get(x.Session, "LastLineJumpCount"));
            byte[] rid2 = Cmd.Rid();
            x.SendLoc(rid2, 2500.0, 36500000);
            x.Tick(16);
            ok = ReadsAsComplete(x.Sender.LastPayload, out kind, out idx, out loc, out time, out count);
            int disc2 = Convert.ToInt32(Pr.Get(x.Session, "Discontinuities"));
            c.Check(ok && kind == "LOC" && count == disc2 && disc2 == 2 && x.Sender.Ids[1] == FakeSource.Hex(rid2), "the LOC completion echoes its own id and counter 2", x.Sender.LastPayload);
        }

        // =====================================================================================================================================
        [Case("LJX-13", "order: host calls, then the session row, then the completion",
            Purpose = "API -> session.OnTick -> JUMP_COMPLETE",
            Operation = "STA and LOC, the events of the host, the session sink and the sender are recorded in one log",
            Expected = "api:MoveTo... < api:SetClockMs < line < complete",
            Contract = "LJX-1 spec 3.2")]
        internal static void Ljx13(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.SendSta(Cmd.Rid(), 3, 36400000);
            string[] before = x.Log.Snapshot();
            x.Tick(16);
            string[] ev = x.Log.Snapshot();
            string[] mine = new string[ev.Length - before.Length];
            Array.Copy(ev, before.Length, mine, 0, mine.Length);
            int iMove = IndexOfEvent(mine, "api:MoveToStation");
            int iSet = IndexOfEvent(mine, "api:SetClockMs");
            int iLine = IndexOfEvent(mine, "line");
            int iComplete = IndexOfEvent(mine, "complete");
            c.Check(iMove >= 0 && iSet > iMove && iLine > iSet && iComplete > iLine, "STA order", Seq(mine));
            x.SendLoc(Cmd.Rid(), 700.0, 36600000);
            before = x.Log.Snapshot();
            x.Tick(16);
            ev = x.Log.Snapshot();
            mine = new string[ev.Length - before.Length];
            Array.Copy(ev, before.Length, mine, 0, mine.Length);
            iMove = IndexOfEvent(mine, "api:MoveToLocation");
            iSet = IndexOfEvent(mine, "api:SetClockMs");
            iLine = IndexOfEvent(mine, "line");
            iComplete = IndexOfEvent(mine, "complete");
            c.Check(iMove >= 0 && iSet > iMove && iLine > iSet && iComplete > iLine, "LOC order", Seq(mine));
        }

        // =====================================================================================================================================
        [Case("LJX-14", "flag OFF: nothing is claimed, executed, sent or announced",
            Purpose = "the default (OFF) behaviour of the plane and the session is the one of the 2A-alpha build",
            Operation = "execution disabled; a command is queued; Ticks run",
            Expected = "capabilities 0x4 only, no AVAIL jump, no JUMP key, no claim, 0 host calls, 0 completions, no exec log vocabulary, plain final line",
            Contract = "LJX-1 spec 9; EX-02 / LJC-07..10")]
        internal static void Ljx14(Ctx c)
        {
            LxOpts o = new LxOpts();
            o.Enabled = false;
            o.TtlMs = 0;
            LxRig x = c.Own(LxRig.Make(c, o));
            RecView rv = x.SendSta(Cmd.Rid(), 1, 36000000);
            c.Check(rv != null && rv.State == CState.Queued, "the datagram is still received and held", rv == null ? "null" : rv.Short);
            for (int i = 0; i < 5; i++) x.Tick(16);
            c.Check(Convert.ToInt32(Pr.Get(x.P.Raw, "PublishedCapabilities")) == 4, "published capabilities are REQUEST_ID only (0x4)", "" + Pr.Get(x.P.Raw, "PublishedCapabilities"));
            c.Check(x.R.Seams.CapsUnion == 4U, "every Directory write carried 0x4 (or 0 for CLOSED)", "" + x.R.Seams.CapsUnion);
            c.Check(!(bool)Pr.Get(x.P.Raw, "JumpAvailable") && !(bool)Pr.Get(x.P.Raw, "ExecutionActive"), "no availability, no execution");
            c.Check(x.Claim() == null, "nothing is claimable");
            c.Check(x.Host.ApiCalls == 0 && x.Sender.Calls == 0, "no host call, no completion", x.Host.ApiCalls + "/" + x.Sender.Calls);
            string row = x.LastTelemetryLine();
            c.Check(row != null && row.IndexOf("JUMP", StringComparison.Ordinal) < 0 && row.IndexOf("jump", StringComparison.Ordinal) < 0, "the row has no JUMP key and no jump token", row);
            x.P.Dispose();
            c.Check(x.LinesWith("jump-exec-").Count == 0 && x.LinesWith("jump-complete-").Count == 0, "no execution log vocabulary");
            List<string> fin = x.LinesWith("jump-plane-final");
            c.Check(fin.Count == 1 && fin[0].IndexOf("claimed=", StringComparison.Ordinal) < 0 && fin[0].IndexOf("ageAtClaimMax", StringComparison.Ordinal) < 0, "the final summary line is the 2A-alpha one", fin.Count > 0 ? fin[0] : "none");
            RecView[] outs = x.P.Outcomes();
            c.Check(outs.Length == 1 && outs[0].State == CState.Discarded && outs[0].Reason == "dispose", "the held command ends Discarded(dispose)", outs.Length > 0 ? outs[outs.Length - 1].Short : "none");
        }

        // =====================================================================================================================================
        [Case("LJX-15", "flag ON but STA, LOC or the completion missing: no capability, no AVAIL jump",
            Purpose = "the jump contract is published only when everything behind it exists",
            Operation = "feature sets 1, 2, 4, 3, 5, 6 and 7",
            Expected = "only set 7 publishes 0x7 and opens AVAIL jump; every other set stays 0x4 with no jump token and no execution",
            Contract = "owner instruction: STA, LOC, COMPLETE, counter, TTL and the exclusive transitions must all hold")]
        internal static void Ljx15(Ctx c)
        {
            int[] sets = new int[] { 1, 2, 4, 3, 5, 6, 7 };
            foreach (int f in sets)
            {
                LxOpts o = new LxOpts();
                o.Features = f;
                LxRig x = c.Own(LxRig.Make(c, o));
                x.SendSta(Cmd.Rid(), 1, 36000000);
                x.Tick(16);
                uint caps = x.R.Seams.CapsUnion;
                bool avail = (bool)Pr.Get(x.P.Raw, "JumpAvailable");
                string row = x.LastTelemetryLine();
                bool rowHas = row != null && row.IndexOf("jump", StringComparison.Ordinal) >= 0;
                if (f == 7)
                {
                    c.Check(caps == 7U && avail && rowHas && x.Host.ApiCalls == 2, "set 7: 0x7, AVAIL jump, executed", "caps=" + caps + " avail=" + avail + " row=" + rowHas + " calls=" + x.Host.ApiCalls);
                }
                else
                {
                    c.Check(caps == 4U && !avail && !rowHas && x.Host.ApiCalls == 0, "set " + f + ": 0x4, no AVAIL jump, nothing executed", "caps=" + caps + " avail=" + avail + " row=" + rowHas + " calls=" + x.Host.ApiCalls);
                }
                x.Dispose();
            }
        }

        // =====================================================================================================================================
        [Case("LJX-16", "the complete set publishes 0x7 and AVAIL jump, and closes them at once when the plane is not Ready",
            Purpose = "AVAIL jump follows the plane state",
            Operation = "enabled with all features; read the Directory writes, the availability and the row; Dispose",
            Expected = "caps 0x7 on every non-CLOSED write; AVAIL carries jump and the row carries JUMP:0; after Dispose the availability is false",
            Contract = "LJX-1 spec 8")]
        internal static void Ljx16(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            PublishRec[] pubs = x.R.Seams.PublishSnapshot();
            int nonClosed = 0, wrong = 0;
            foreach (PublishRec p in pubs)
            {
                if (p.State == 8U) { if (p.Caps != 0U) wrong++; continue; }
                nonClosed++;
                if (p.Caps != 7U) wrong++;
            }
            c.Check(nonClosed >= 2 && wrong == 0, "PUBLISHED and READY carry 0x7", nonClosed + " writes, " + wrong + " wrong");
            c.Check(Convert.ToInt32(Pr.Get(x.P.Raw, "PublishedCapabilities")) == 7, "PublishedCapabilities is 7");
            c.Check((bool)Pr.Get(x.P.Raw, "JumpAvailable"), "AVAIL jump is open while Ready");
            x.Tick(16);
            string row = x.LastTelemetryLine();
            c.Check(row != null && row.IndexOf("AVAIL:1:", StringComparison.Ordinal) >= 0 && row.IndexOf("jump", StringComparison.Ordinal) >= 0 && row.IndexOf(",JUMP:0", StringComparison.Ordinal) >= 0, "the row announces jump and carries JUMP:0", row);
            x.P.Dispose();
            c.Check(!(bool)Pr.Get(x.P.Raw, "JumpAvailable"), "after Dispose the availability is false");
        }

        // =====================================================================================================================================
        [Case("LJX-17", "with the availability the row is the OFF row plus the JUMP key; NoteOfficialJump semantics",
            Purpose = "nothing but the jump group changes in the row; the official jump resets the station state without moving the counter",
            Operation = "the same inputs through a session with and a session without the availability; NoteOfficialJump with a small and a large time step",
            Expected = "RemoveJump(ON row) == OFF row; a small step does not count a discontinuity, a large step does; the note is consumed by one Tick",
            Contract = "LJX-1 spec 5")]
        internal static void Ljx17(Ctx c)
        {
            LxRig on = c.Own(LxRig.Make(c, new LxOpts()));
            LxOpts oo = new LxOpts();
            oo.JumpAvail = false;
            LxRig off = c.Own(LxRig.Make(c, oo));
            for (int i = 0; i < 3; i++) { on.Tick(16); off.Tick(16); }
            string a = on.LastTelemetryLine();
            string b = off.LastTelemetryLine();
            c.Check(a != null && b != null && RemoveJump(a) == b, "ON row minus the jump group equals the OFF row", a + " <> " + b);
            c.Check(b != null && b.IndexOf("jump", StringComparison.Ordinal) < 0, "the OFF row has no jump token");
            int d0 = Convert.ToInt32(Pr.Get(on.Session, "Discontinuities"));
            Pr.Call(on.Session, "NoteOfficialJump");
            on.Tick(16);
            c.Check(Convert.ToInt32(Pr.Get(on.Session, "Discontinuities")) == d0, "a small step with the note: the 300 ms rule keeps the counter", "" + Pr.Get(on.Session, "Discontinuities"));
            Pr.Call(on.Session, "NoteOfficialJump");
            on.Host.TimeMs += 90000;
            on.Tick(16);
            c.Check(Convert.ToInt32(Pr.Get(on.Session, "Discontinuities")) == d0 + 1, "a large step: the counter moves by one", "" + Pr.Get(on.Session, "Discontinuities"));
            on.Host.TimeMs += 90000;
            on.Tick(16);
            c.Check(Convert.ToInt32(Pr.Get(on.Session, "Discontinuities")) == d0 + 2, "without a note the 300 ms rule still counts a large step (unchanged behaviour)", "" + Pr.Get(on.Session, "Discontinuities"));
        }

        // =====================================================================================================================================
        [Case("LJX-18", "every claimed request logs its ageAtClaim; the final summary keeps the maximum",
            Purpose = "acceptance evidence: ageAtClaim of ALL requests",
            Operation = "three commands claimed after 100, 700 and 1200 ms on the plane clock",
            Expected = "three jump-exec-claimed lines with ageAtClaimMs 100 / 700 / 1200, receipts carry the age, ageAtClaimMax=1200 in jump-plane-final",
            Contract = "owner decision 8 / 9 of the O-1 acceptance")]
        internal static void Ljx18(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            long[] ages = new long[] { 100, 700, 1200 };
            List<byte[]> rids = new List<byte[]>();
            foreach (long age in ages)
            {
                byte[] rid = Cmd.Rid();
                rids.Add(rid);
                x.SendSta(rid, 1, 36000000);
                x.Clk.Advance(age);
                x.Tick(16);
            }
            List<string> claimed = x.LinesWith("event=jump-exec-claimed");
            c.Check(claimed.Count == 3, "three claimed lines", "" + claimed.Count);
            for (int i = 0; i < claimed.Count && i < 3; i++) c.Check(KeyValue(claimed[i], "ageAtClaimMs") == ages[i].ToString(CultureInfo.InvariantCulture), "line " + i + " carries ageAtClaimMs " + ages[i], claimed[i]);
            for (int i = 0; i < 3; i++) c.Check(x.Rec(rids[i]).AgeAtClaimMs == ages[i], "receipt " + i + " carries the age", "" + x.Rec(rids[i]).AgeAtClaimMs);
            x.P.Dispose();
            List<string> fin = x.LinesWith("jump-plane-final");
            c.Check(fin.Count == 1 && fin[0].IndexOf("ageAtClaimMax=1200", StringComparison.Ordinal) >= 0 && fin[0].IndexOf("claimed=3", StringComparison.Ordinal) >= 0 && fin[0].IndexOf("completed=3", StringComparison.Ordinal) >= 0, "the final line has claimed=3, completed=3 and ageAtClaimMax=1200", fin.Count > 0 ? fin[0] : "none");
        }

        // =====================================================================================================================================
        [Case("LJX-19", "the Executing time is a diagnostic only: nothing is aborted",
            Purpose = "Executing watchdog = elapsed milliseconds, no interruption",
            Operation = "every host call takes 250 ms of the plane clock (4 calls over two commands)",
            Expected = "jump-exec-end lines carry elapsedMs=500; both commands complete; the final line carries execElapsedMax=500",
            Contract = "owner decision 5 / 6 of the O-1 acceptance")]
        internal static void Ljx19(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Host.InsideCall = delegate { x.Clk.Advance(250); };
            byte[] r1 = Cmd.Rid();
            byte[] r2 = Cmd.Rid();
            x.SendSta(r1, 1, 36000000);
            x.Tick(16);
            x.SendLoc(r2, 900.0, 36000000);
            x.Tick(16);
            List<string> ends = x.LinesWith("event=jump-exec-end");
            c.Check(ends.Count == 2, "two jump-exec-end lines", "" + ends.Count);
            foreach (string e in ends) c.Check(KeyValue(e, "elapsedMs") == "500" && KeyValue(e, "ok") == "1", "elapsedMs=500 ok=1", e);
            c.Check(StateIs(x, r1, Ls.Completed, null) && StateIs(x, r2, Ls.Completed, null), "both commands were carried through (no abort)");
            x.P.Dispose();
            List<string> fin = x.LinesWith("jump-plane-final");
            c.Check(fin.Count == 1 && fin[0].IndexOf("execElapsedMax=500", StringComparison.Ordinal) >= 0, "the final line keeps execElapsedMax", fin.Count > 0 ? fin[0] : "none");
        }

        // =====================================================================================================================================
        [Case("LJX-20", "after Dispose nothing is claimed; Dispose does not interrupt an Executing call",
            Purpose = "shutdown bans",
            Operation = "(a) Dispose, then claim and Tick; (b) Dispose from another thread while the host call is in progress",
            Expected = "(a) no ticket, 0 host calls, afterDisposeAccess 0; (b) Dispose returns, the call finishes, the receipt is Abandoned(dispose), no completion",
            Contract = "LJX-1 spec 3.5; invariant INV-10")]
        internal static void Ljx20(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.P.Dispose();
            c.Check(x.Claim() == null, "(a) no claim after Dispose");
            x.Tick(16);
            c.Check(x.Host.ApiCalls == 0 && x.Sender.Calls == 0, "(a) no host call, no completion after Dispose", x.Host.ApiCalls + "/" + x.Sender.Calls);
            c.Check(x.P.AfterDisposeAccess == 0, "(a) afterDisposeAccess is 0", "" + x.P.AfterDisposeAccess);

            LxRig y = c.Own(LxRig.Make(c, new LxOpts()));
            ManualResetEvent inCall = new ManualResetEvent(false);
            ManualResetEvent release = new ManualResetEvent(false);
            y.Host.InsideCall = delegate { inCall.Set(); release.WaitOne(8000); };
            byte[] rid2 = Cmd.Rid();
            y.SendSta(rid2, 1, 36000000);
            Bg runner = Bg.Start(delegate { y.Tick(16); });
            bool entered = inCall.WaitOne(5000);
            c.Check(entered, "(b) the host call is in progress");
            Bg disposer = Bg.Start(delegate { y.P.Dispose(); });
            bool disposed = disposer.Join(6000);
            c.Check(disposed, "(b) Dispose returns while the call is still in progress (it does not wait for, or interrupt, the call)");
            release.Set();
            runner.Join(8000);
            LxRec r = y.Rec(rid2);
            c.Check(r != null && r.State == Ls.Abandoned && r.Reason == "dispose", "(b) the receipt is Abandoned(dispose)", r == null ? "null" : r.Short);
            c.Check(y.Sender.Calls == 0, "(b) no completion was sent", "" + y.Sender.Calls);
            c.Check(y.Host.ApiCalls == 2, "(b) the sequence ran to its end (2 host calls)", "" + y.Host.ApiCalls);
            c.Check(y.Illegal == 0 && y.P.AfterDisposeAccess == 0, "(b) illegal-transition 0, afterDisposeAccess 0", y.Illegal + "/" + y.P.AfterDisposeAccess);
        }

        // =====================================================================================================================================
        [Case("LJX-21", "no host call unless the plane is Ready (NotStarted, retry, WITHDRAWING, CLOSED)",
            Purpose = "WITHDRAWING / CLOSED forbid the host call",
            Operation = "claim and Tick in each non-Ready state",
            Expected = "no ticket and no host call in every one of them",
            Contract = "LJX-1 spec 3.1 (plane Ready)")]
        internal static void Ljx21(Ctx c)
        {
            LxOpts n = new LxOpts();
            n.Start = false;
            LxRig a = c.Own(LxRig.Make(c, n));
            c.Check(a.P.State == PState.NotStarted && a.Claim() == null, "NotStarted: no ticket");
            a.Tick(16);
            c.Check(a.Host.ApiCalls == 0, "NotStarted: no host call", "" + a.Host.ApiCalls);

            LxOpts f = new LxOpts();
            f.Start = false;
            f.Hooks = delegate (SeamHooks h) { h.OnCreate = delegate { throw new InvalidOperationException("injected-create"); }; };
            LxRig b = c.Own(LxRig.Make(c, f));
            b.P.Start();
            bool retry = Wait.For(delegate { return b.P.State == PState.RetryWaiting; }, 5000);
            c.Check(retry, "the plane is in RetryWaiting", b.P.StateName);
            c.Check(b.Claim() == null, "RetryWaiting: no ticket");
            b.Tick(16);
            c.Check(b.Host.ApiCalls == 0, "RetryWaiting: no host call", "" + b.Host.ApiCalls);

            ManualResetEvent held = new ManualResetEvent(false);
            ManualResetEvent go = new ManualResetEvent(false);
            LxOpts w = new LxOpts();
            w.Hooks = delegate (SeamHooks h)
            {
                h.AfterPublish = delegate (UInt32 s) { if (s == 7U) { held.Set(); go.WaitOne(8000); } };
            };
            LxRig d = c.Own(LxRig.Make(c, w));
            d.SendSta(Cmd.Rid(), 1, 36000000);
            Bg disposer = Bg.Start(delegate { d.P.Dispose(); });
            bool inWithdraw = held.WaitOne(5000);
            c.Check(inWithdraw && d.P.State == PState.Withdrawing, "the plane sits in WITHDRAWING", d.P.StateName);
            c.Check(d.Claim() == null, "WITHDRAWING: no ticket");
            d.Tick(16);
            c.Check(d.Host.ApiCalls == 0, "WITHDRAWING: no host call", "" + d.Host.ApiCalls);
            go.Set();
            disposer.Join(8000);
            c.Check(d.P.State == PState.Closed && d.Claim() == null, "CLOSED: no ticket", d.P.StateName);
            d.Tick(16);
            c.Check(d.Host.ApiCalls == 0, "CLOSED: no host call", "" + d.Host.ApiCalls);
        }

        // =====================================================================================================================================
        [Case("LJX-22", "a failed completion send never ends Completed",
            Purpose = "fail-closed completion (OD-X5): retry while the facts hold, abandon when they change, never invent Completed",
            Operation = "sender answers Held twice, then Sent; Held then a boundary; a throwing sender; an excluded answer",
            Expected = "CompletionPending while Held (same payload and id each time), Completed only on Sent; Abandoned on a changed fact / exclusion",
            Contract = "LJX-1 spec 6; state table row CompletionPending")]
        internal static void Ljx22(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Sender.Script.Enqueue(Ls.SendHeld);
            x.Sender.Script.Enqueue(Ls.SendHeld);
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.CompletionPending, null), "Held: CompletionPending", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.CompletionPending, null), "Held again: still CompletionPending", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            x.Tick(16);
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 3, "Sent: Completed after three attempts", x.Sender.Calls + " " + (x.Rec(rid) == null ? "null" : x.Rec(rid).Short));
            c.Check(x.Sender.Payloads[0] == x.Sender.Payloads[2] && x.Sender.Ids[0] == x.Sender.Ids[2], "the retries send the same payload and id");
            c.Check(x.Host.ApiCalls == 2, "the host was called once (2 calls), never again for a retry", "" + x.Host.ApiCalls);

            byte[] rid2 = Cmd.Rid();
            x.Sender.Script.Enqueue(Ls.SendHeld);
            x.SendSta(rid2, 2, 36500000);
            x.Tick(16);
            c.Check(StateIs(x, rid2, Ls.CompletionPending, null), "Held: CompletionPending (2)");
            int callsBefore = x.Sender.Calls;
            x.P.NoteScenarioBoundary();
            x.Tick(16);
            LxRec r2 = x.Rec(rid2);
            c.Check(r2 != null && r2.State == Ls.Abandoned && r2.Reason.StartsWith("completion-", StringComparison.Ordinal), "a changed scenario abandons it (completion-...)", r2 == null ? "null" : r2.Short);
            x.Tick(16);
            c.Check(x.Sender.Calls == callsBefore, "nothing is sent after the abandon", x.Sender.Calls + " vs " + callsBefore);

            byte[] rid3 = Cmd.Rid();
            x.Sender.ThrowNext = true;
            x.SendSta(rid3, 1, 36000000);
            x.Tick(16);
            c.Check(!StateIs(x, rid3, Ls.Completed, null), "a throwing sender does not complete", x.Rec(rid3) == null ? "null" : x.Rec(rid3).Short);
            x.Tick(16);
            c.Check(StateIs(x, rid3, Ls.Completed, null), "and the next attempt can", x.Rec(rid3) == null ? "null" : x.Rec(rid3).Short);

            byte[] rid4 = Cmd.Rid();
            x.Sender.Script.Enqueue(Ls.SendExcluded);
            x.SendSta(rid4, 1, 36000000);
            x.Tick(16);
            LxRec r4 = x.Rec(rid4);
            c.Check(r4 != null && r4.State == Ls.Abandoned && r4.Reason == "completion-excluded", "an excluded answer is Abandoned(completion-excluded), not Completed", r4 == null ? "null" : r4.Short);
            c.Check(x.Illegal == 0, "illegal-transition 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LJX-23", "the same RequestId never executes twice",
            Purpose = "duplicate protection",
            Operation = "send one command, execute it, send the same datagram again (before and after completion)",
            Expected = "the second is Rejected(duplicate-request-id); the host runs one sequence only",
            Contract = "LJX-1 invariant INV-9; D0B-1 13.3")]
        internal static void Ljx23(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            byte[] datagram = Cmd.Valid(x.Snap, x.R.Pid, x.R.Src.Owner, rid, "JUMP_STA_TIME:1:36000000", 0x100U);
            RecView first = Kit.SendAndAwait(x.R, x.Snap, datagram, 4000);
            RecView dup1 = Kit.SendAndAwait(x.R, x.Snap, datagram, 4000);
            c.Check(first != null && first.State == CState.Queued, "the first is Queued");
            c.Check(dup1 != null && dup1.State == CState.Rejected && dup1.Reason == "duplicate-request-id", "the duplicate before execution is Rejected", dup1 == null ? "null" : dup1.Short);
            x.Tick(16);
            RecView dup2 = Kit.SendAndAwait(x.R, x.Snap, datagram, 4000);
            c.Check(dup2 != null && dup2.State == CState.Rejected && dup2.Reason == "duplicate-request-id", "the duplicate after completion is Rejected", dup2 == null ? "null" : dup2.Short);
            x.Tick(16);
            c.Check(x.Host.ApiCalls == 2, "one sequence only (2 host calls)", "" + x.Host.ApiCalls);
            c.Check(x.Sender.Calls == 1, "one completion only", "" + x.Sender.Calls);
        }

        // =====================================================================================================================================
        [Case("LJX-24", "one command in flight; a newer command supersedes a pending completion",
            Purpose = "INV-4 and the superseded transition",
            Operation = "hold the completion (Held), accept a second command, Tick",
            Expected = "first is Abandoned(superseded); the second is not claimed while the first is in flight and is executed afterwards; never two in flight",
            Contract = "LJX-1 spec 3.4")]
        internal static void Ljx24(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Sender.Default = Ls.SendHeld;
            byte[] a = Cmd.Rid();
            byte[] b = Cmd.Rid();
            x.SendSta(a, 1, 36000000);
            x.Tick(16);
            c.Check(StateIs(x, a, Ls.CompletionPending, null), "the first is CompletionPending");
            RecView rb = x.SendSta(b, 2, 36500000);
            c.Check(rb != null && rb.State == CState.Queued, "the second is Queued");
            Wait.For(delegate { LxRec q = x.Rec(a); return q != null && q.State == Ls.Abandoned; }, 2000);
            LxRec ra = x.Rec(a);
            c.Check(ra != null && ra.State == Ls.Abandoned && ra.Reason == "superseded", "the first is Abandoned(superseded)", ra == null ? "null" : ra.Short);
            c.Check(x.Host.ApiCalls == 2, "the second is not executed yet in the same moment", "" + x.Host.ApiCalls);
            x.Sender.Default = Ls.SendSent;
            x.Tick(16);
            x.Tick(16);
            c.Check(StateIs(x, b, Ls.Completed, null) && x.Host.ApiCalls == 4, "the second was executed afterwards and completed", x.Host.ApiCalls + " " + (x.Rec(b) == null ? "null" : x.Rec(b).Short));
            c.Check(x.Counter("max-in-flight") <= 1, "never more than one in flight", "" + x.Counter("max-in-flight"));
            c.Check(x.Illegal == 0, "illegal-transition 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LJX-25", "consecutive execution failures close AVAIL jump (breaker)",
            Purpose = "OD-X6 option B: three consecutive failures close the availability; a success resets the count; a scenario boundary reopens",
            Operation = "the host throws; Ticks; AVAIL and the row are watched",
            Expected = "Failed(api-exception) with no completion; after the third consecutive failure JumpAvailable is false and the row has no jump; two failures, a success, two failures keep it open",
            Contract = "LJX-1 spec 8 (breaker not open); owner decision pending on N=3")]
        internal static void Ljx25(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            x.Host.ThrowOn = "MoveToStation";
            for (int i = 0; i < 2; i++) { x.SendSta(Cmd.Rid(), 1, 36000000); x.Tick(16); }
            c.Check((bool)Pr.Get(x.P.Raw, "JumpAvailable"), "two failures: still available");
            x.Host.ThrowOn = null;
            byte[] ok = Cmd.Rid();
            x.SendSta(ok, 1, 36000000);
            x.Tick(16);
            c.Check(StateIs(x, ok, Ls.Completed, null), "a success completes");
            x.Host.ThrowOn = "MoveToStation";
            for (int i = 0; i < 2; i++) { x.SendSta(Cmd.Rid(), 1, 36000000); x.Tick(16); }
            c.Check((bool)Pr.Get(x.P.Raw, "JumpAvailable"), "two failures after a success: the count was reset, still available");
            byte[] third = Cmd.Rid();
            x.SendSta(third, 1, 36000000);
            x.Tick(16);
            LxRec r = x.Rec(third);
            c.Check(r != null && r.State == Ls.Failed, "the failing command is Failed", r == null ? "null" : r.Short);
            c.Check(!(bool)Pr.Get(x.P.Raw, "JumpAvailable"), "three consecutive failures: AVAIL jump closed");
            x.Tick(16);
            string row = x.LastTelemetryLine();
            c.Check(row != null && row.IndexOf("jump", StringComparison.Ordinal) < 0 && row.IndexOf("JUMP", StringComparison.Ordinal) < 0, "the row no longer announces jump", row);
            c.Check(x.Sender.Calls == 1, "no completion was sent for any failure (only the one success)", "" + x.Sender.Calls);
            x.P.NoteScenarioBoundary();
            c.Check((bool)Pr.Get(x.P.Raw, "JumpAvailable"), "a scenario boundary reopens it");
        }

        // =====================================================================================================================================
        [Case("LJX-26", "no Current fallback, no fixed port: the plane and the sender use recorded dynamic destinations only",
            Purpose = "runtime side of the static pins",
            Operation = "read the published port and everything the real sink sends to",
            Expected = "the Directory port is neither of the two fixed product ports; no datagram goes to a fixed port; the fixed-port send counter of the kit is 0",
            Contract = "LJX-1 spec 7 (fixed ports, Current types)")]
        internal static void Ljx26(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            c.Check(!Net.IsFixedPort((int)x.Snap.Port), "the plane port is dynamic", "" + x.Snap.Port);
            c.Check(!SinkSendsToFixedPort(), "the real sink never sends to a fixed port");
            c.Check(Net.FixedSendsRefused == 0, "the kit refused no send to a fixed port", "" + Net.FixedSendsRefused);
        }

        private static bool SinkSendsToFixedPort()
        {
            DpRig r = new DpRig();
            r.Probe.Enabled = true;
            r.Source.Set(40110, 3, 5, DpRig.Inst, 7U);
            r.AddStations();
            r.Run(3, 16);
            Pr.Call(r.Sink, "SendJumpComplete", Encoding.UTF8.GetBytes("JUMP_COMPLETE:STA:1:1000:36000000:1"), Cmd.Rid());
            for (int i = 0; i < r.Transport.Count; i++) if (Net.IsFixedPort(r.Transport.ToAt(i).Port)) return true;
            return false;
        }

        // =====================================================================================================================================
        [Case("LJX-27", "the Directory keeps its layout: 128 bytes, valid, one writer path",
            Purpose = "the shared layout is not touched by the execution slice",
            Operation = "read the live mapping of the plane with the kit's raw reader",
            Expected = "found, valid, state PUBLISHED|READY, capabilities 0x7, the generation and port of the snapshot, 128 bytes",
            Contract = "D0B-1 layout; LJX-1 stop condition")]
        internal static void Ljx27(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            DirRead d = DirView.Poll(x.R.Name);
            c.Check(d.Found && d.Valid, "the Directory is found and valid", d.Reason);
            c.Check(d.Bytes != null && d.Bytes.Length == 128, "128 bytes", d.Bytes == null ? "null" : "" + d.Bytes.Length);
            c.Check(d.State == 3U && d.Caps == 7U, "state PUBLISHED|READY with capabilities 0x7", d.State + "/" + d.Caps);
            c.Check(d.Generation == x.Snap.Generation && d.Port == x.Snap.Port, "generation and port are the plane's", d.Generation + "/" + d.Port);
            c.Check(d.BvePid == (UInt32)x.R.Pid, "the BVE pid is the plane's");
        }

        // =====================================================================================================================================
        [Case("LJX-28", "the Legacy jump API is named by one type only, and only the Tick reaches it",
            Purpose = "allow-list of the host API call sites and their reachability (static call graph over the product IL)",
            Operation = "scan every product type; build the call graph; walk from the heartbeat, the lifecycle handlers, Dispose and the worker",
            Expected = "Initialize / InitializeTimeAndLocation / SetTime are called only inside AtsExLegacyJumpHost (1 + 1 + 1 call instructions); they are reachable from Tick only",
            Contract = "LJX-1 spec 7 (static pins)")]
        internal static void Ljx28(Ctx c)
        {
            Assembly asm = Pr.Asm;
            Type host = Pr.T("AtsExLegacyJumpHost");
            string[] api = new string[] { "Initialize", "InitializeTimeAndLocation", "SetTime" };
            LegacyIlCallScan.Result outside = LegacyIlCallScan.ScanAllExcept(asm, new string[] { host.FullName });
            c.Check(outside.TypesScanned > 20 && outside.MethodsScanned > 150 && outside.CallsSeen > 500, "the scan is not vacuous", outside.TypesScanned + "/" + outside.MethodsScanned + "/" + outside.CallsSeen);
            List<string> leaks = new List<string>();
            foreach (string call in outside.Calls)
            {
                if (!call.StartsWith("BveTypes.", StringComparison.Ordinal)) continue;
                if (Array.IndexOf(api, LegacyIlCallScan.MethodNameOf(call)) >= 0) leaks.Add(call);
            }
            c.Check(leaks.Count == 0, "no type outside AtsExLegacyJumpHost calls the jump API", string.Join(",", leaks.ToArray()));
            LegacyIlCallScan.Result inside = LegacyIlCallScan.ScanTypes(asm, new Type[] { host });
            int ini = 0, ital = 0, set = 0;
            foreach (string call in inside.Calls)
            {
                if (!call.StartsWith("BveTypes.", StringComparison.Ordinal)) continue;
                string n = LegacyIlCallScan.MethodNameOf(call);
                if (n == "Initialize") ini++;
                else if (n == "InitializeTimeAndLocation") ital++;
                else if (n == "SetTime") set++;
            }
            c.Check(ini == 1 && ital == 1 && set == 1, "AtsExLegacyJumpHost has exactly one call instruction per jump API", ini + "/" + ital + "/" + set);

            Dictionary<string, HashSet<string>> graph = BuildGraph(asm);
            c.Check(graph.Count > 200, "the call graph is not vacuous", "" + graph.Count);
            HashSet<string> fromTick = Reach(graph, new string[] { "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::Tick" });
            bool tickReaches = false;
            foreach (string k in fromTick) if (k.StartsWith(host.FullName + "::", StringComparison.Ordinal)) tickReaches = true;
            c.Check(tickReaches, "positive control: the host adapter is reachable from Tick");
            string[] others = new string[]
            {
                "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::OnHeartbeat", "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::Dispose",
                "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::OnScenarioOpened", "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::OnScenarioClosed",
                "TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension::OnScenarioCreated", "TSScoringPlugin.Telemetry.LegacyJumpControlPlane::Loop",
                "TSScoringPlugin.Telemetry.LegacyJumpControlPlane::Dispose", "TSScoringPlugin.Telemetry.LegacyJumpControlPlane::OnHostTick",
                "TSScoringPlugin.Telemetry.LegacyJumpControlPlane::NoteScenarioBoundary", "TSScoringPlugin.Telemetry.LegacyTelemetrySession::ComposeHeartbeat"
            };
            foreach (string entry in others)
            {
                bool known = graph.ContainsKey(entry);
                HashSet<string> reach = Reach(graph, new string[] { entry });
                bool bad = false;
                foreach (string k in reach) if (k.StartsWith(host.FullName + "::", StringComparison.Ordinal) || k.StartsWith("TSScoringPlugin.Telemetry.LegacyJumpExecutor::Execute", StringComparison.Ordinal)) bad = true;
                c.Check(known && !bad, "from " + entry.Substring(entry.LastIndexOf('.') + 1) + " the host adapter and the executor are unreachable", known ? "" : "entry missing");
            }
            List<string> claimCallers = new List<string>();
            foreach (KeyValuePair<string, HashSet<string>> kv in graph)
            {
                if (kv.Value.Contains("TSScoringPlugin.Telemetry.LegacyJumpControlPlane::TryClaimForTick")) claimCallers.Add(kv.Key);
            }
            bool onlyRunner = claimCallers.Count > 0;
            foreach (string cc in claimCallers) if (!cc.StartsWith("TSScoringPlugin.Telemetry.LegacyJumpTickRunner::", StringComparison.Ordinal)) onlyRunner = false;
            c.Check(onlyRunner, "TryClaimForTick is called from the tick runner only (one claim entry)", string.Join(",", claimCallers.ToArray()));
            LegacyIlCallScan.Result all = LegacyIlCallScan.ScanAllExcept(asm, new string[] { "TSScoringPlugin.DataPlane.CurrentJumpEndpoint" });
            bool cur = LegacyIlCallScan.CallsAnyOf(all, "TSScoringPlugin.DataPlane.CurrentJumpEndpoint::Create") || LegacyIlCallScan.CallsAnyOf(all, "TSScoringPlugin.DataPlane.CurrentJumpEndpoint::.ctor");
            c.Check(!cur, "no Legacy type creates the Current jump endpoint (no Current fallback)");
        }

        private static Dictionary<string, HashSet<string>> BuildGraph(Assembly asm)
        {
            Dictionary<string, HashSet<string>> g = new Dictionary<string, HashSet<string>>();
            BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
            List<Type> types = new List<Type>(LegacyIlCallScan.LoadableTypes(asm));
            foreach (Type t in types)
            {
                if (t.FullName == null) continue;
                List<MethodBase> ms = new List<MethodBase>();
                foreach (MethodInfo m in t.GetMethods(all)) ms.Add(m);
                foreach (ConstructorInfo k in t.GetConstructors(all)) ms.Add(k);
                foreach (MethodBase mb in ms)
                {
                    string key = OwnerOf(t) + "::" + mb.Name;
                    HashSet<string> set;
                    if (!g.TryGetValue(key, out set)) { set = new HashSet<string>(); g[key] = set; }
                    LegacyIlCallScan.Result r = LegacyIlCallScan.ScanMethod(asm, mb);
                    foreach (string call in r.Calls) set.Add(NormalizeCall(call));
                }
                // interface methods lead to their implementations (by name)
                foreach (Type i in t.GetInterfaces())
                {
                    if (i.FullName == null || !i.FullName.StartsWith("TSScoringPlugin.", StringComparison.Ordinal)) continue;
                    foreach (MethodInfo im in i.GetMethods())
                    {
                        string ik = i.FullName + "::" + im.Name;
                        HashSet<string> s2;
                        if (!g.TryGetValue(ik, out s2)) { s2 = new HashSet<string>(); g[ik] = s2; }
                        s2.Add(OwnerOf(t) + "::" + im.Name);
                    }
                }
            }
            return g;
        }

        /// <summary>Compiler generated closure and iterator classes belong to the type that contains them: their calls are the calls of that type's methods.</summary>
        private static string OwnerOf(Type t)
        {
            return t.FullName.Replace('+', '.');
        }

        private static string NormalizeCall(string call)
        {
            return call.Replace('+', '.');
        }

        private static HashSet<string> Reach(Dictionary<string, HashSet<string>> g, string[] entries)
        {
            HashSet<string> seen = new HashSet<string>();
            Queue<string> q = new Queue<string>();
            foreach (string e in entries) { seen.Add(e); q.Enqueue(e); }
            while (q.Count > 0)
            {
                string k = q.Dequeue();
                HashSet<string> next;
                if (!g.TryGetValue(k, out next)) continue;
                foreach (string n in next)
                {
                    if (seen.Add(n)) q.Enqueue(n);
                }
            }
            return seen;
        }

        // =====================================================================================================================================
        [Case("LJX-29", "the real sink sends JUMP_COMPLETE as a type 5 envelope to the recorded endpoint only, and says whether it was consumed",
            Purpose = "SendJumpComplete of LegacyDataPlaneSink: Sent / Held / Excluded; RequestId echo; no classifier involvement",
            Operation = "managed mode with a JUMP_COMPLETE capable endpoint; an unresolvable endpoint; an endpoint without the capability",
            Expected = "Sent: one type 5 envelope with the RequestId to the endpoint port; Held: nothing sent; Excluded: nothing sent; the classifier still does not know JUMP_COMPLETE",
            Contract = "LJX-1 spec 6; CurrentDataPlane.cs unchanged")]
        internal static void Ljx29(Ctx c)
        {
            byte[] payload = Encoding.UTF8.GetBytes("JUMP_COMPLETE:STA:1:1000:36000000:1");
            DpRig r = new DpRig();
            r.Probe.Enabled = true;
            r.Source.Set(40120, 3, 5, DpRig.Inst, 7U);
            r.AddStations();
            r.Run(3, 16);
            int before = r.Transport.Count;
            byte[] rid = Cmd.Rid();
            int res = Convert.ToInt32(Pr.Call(r.Sink, "SendJumpComplete", payload, rid));
            c.Check(res == Ls.SendSent && r.Transport.Count == before + 1, "Sent: one datagram", res + " / " + (r.Transport.Count - before));
            if (r.Transport.Count == before + 1)
            {
                Envelope e = DataPlaneProtocol.DecodeEnvelope(r.Transport.DataAt(before));
                c.Check(e.MessageType == 5U, "message type 5", "" + e.MessageType);
                c.Check(FakeSource.Hex(e.RequestId) == FakeSource.Hex(rid), "the RequestId is echoed");
                c.Check(Encoding.UTF8.GetString(e.Payload) == Encoding.UTF8.GetString(payload), "the payload is unchanged");
                c.Check(r.Transport.ToAt(before).Port == 40120, "sent to the recorded endpoint port only", "" + r.Transport.ToAt(before).Port);
            }
            DpRig h = new DpRig();
            h.Probe.Enabled = true;
            h.Source.Clear("telemetry-directory-missing");
            h.Run(3, 16);
            int hb = h.Transport.Count;
            int held = Convert.ToInt32(Pr.Call(h.Sink, "SendJumpComplete", payload, Cmd.Rid()));
            c.Check(held == Ls.SendHeld && h.Transport.Count == hb, "Held: nothing sent when the endpoint cannot be resolved", held + " / " + (h.Transport.Count - hb));
            DpRig x = new DpRig();
            x.Probe.Enabled = true;
            x.Source.Set(40121, 3, 5, DpRig.Inst, DpRig.CapsText);
            x.Run(3, 16);
            int xb = x.Transport.Count;
            int excl = Convert.ToInt32(Pr.Call(x.Sink, "SendJumpComplete", payload, Cmd.Rid()));
            c.Check(excl == Ls.SendExcluded && x.Transport.Count == xb, "Excluded: consumed without a datagram when the endpoint lacks the capability", excl + " / " + (x.Transport.Count - xb));
            c.Check(LegacyMessageClassifier.Classify("JUMP_COMPLETE:STA:1:1000:36000000:1") == LegacyMessageClassifier.Unknown, "the classifier does not know JUMP_COMPLETE (it never travels through Send)");
        }

        // =====================================================================================================================================
        [Case("LJX-30", "the build flag: default OFF in the default build, ON only in the acceptance build",
            Purpose = "the flag is a compile symbol; the build tells which one it is",
            Operation = "read LegacyJumpBuild.ExecutionCompiledIn",
            Expected = "false in the default build; true in the acceptance build (the runner says which one it is testing)",
            Contract = "OD-X16 option A")]
        internal static void Ljx30(Ctx c)
        {
            bool compiled = (bool)Pr.GetStatic(Pr.T("LegacyJumpBuild"), "ExecutionCompiledIn");
            c.Check(compiled == ExpectCompiledIn, "ExecutionCompiledIn matches the build under test", "compiled=" + compiled + " expected=" + ExpectCompiledIn);
        }

        // =====================================================================================================================================
        [Case("LJX-31", "a failed host sequence is Failed and never completed (read back, partial execution, lifecycle event, re-entrance)",
            Purpose = "fail-closed execution: the result of the host sequence is checked, a failure is not repaired and sends nothing",
            Operation = "a time read back that differs, a location read back that differs, a clock call that throws, a scenario boundary during the call, a re-entrant call",
            Expected = "Failed(readback-time-mismatch / readback-location-mismatch / partial-execution / lifecycle-event-during-call), no completion; the re-entrant call is refused and the outer one is not disturbed",
            Contract = "LJX-1 spec 4 (success conditions)")]
        internal static void Ljx31(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] a = Cmd.Rid();
            x.Host.TimeSkew = 5;
            x.SendSta(a, 1, 36000000);
            x.Tick(16);
            LxRec ra = x.Rec(a);
            c.Check(ra != null && ra.State == Ls.Failed && ra.Reason == "readback-time-mismatch", "a time read back that differs", ra == null ? "null" : ra.Short);
            x.Host.TimeSkew = 0;
            byte[] b = Cmd.Rid();
            x.Host.LocationSkew = 0.5;
            x.SendSta(b, 1, 36000000);
            x.Tick(16);
            LxRec rb = x.Rec(b);
            c.Check(rb != null && rb.State == Ls.Failed && rb.Reason == "readback-location-mismatch", "a location read back that differs by 0.5 m", rb == null ? "null" : rb.Short);
            x.Host.LocationSkew = 0.009;
            byte[] ok = Cmd.Rid();
            x.SendSta(ok, 1, 36000000);
            x.Tick(16);
            c.Check(StateIs(x, ok, Ls.Completed, null), "a location read back within 0.01 m is accepted (and resets the failure count)", x.Rec(ok) == null ? "null" : x.Rec(ok).Short);
            x.Host.LocationSkew = 0.0;
            byte[] p = Cmd.Rid();
            x.Host.ThrowOn = "SetClockMs";
            int callsBefore = x.Host.ApiCalls;
            x.SendSta(p, 1, 36000000);
            x.Tick(16);
            LxRec rp = x.Rec(p);
            c.Check(rp != null && rp.State == Ls.Failed && rp.Reason == "partial-execution", "the clock call throws after the first call: partial execution", rp == null ? "null" : rp.Short);
            c.Check(x.Host.ApiCalls - callsBefore == 2, "the sequence was not repeated or repaired (two calls, one of them failed)", "" + (x.Host.ApiCalls - callsBefore));
            x.Host.ThrowOn = null;
            byte[] d = Cmd.Rid();
            x.Host.InsideCall = delegate { x.P.NoteScenarioBoundary(); };
            x.SendSta(d, 1, 36000000);
            x.Tick(16);
            x.Host.InsideCall = null;
            LxRec rd = x.Rec(d);
            c.Check(rd != null && rd.State == Ls.Failed && rd.Reason == "lifecycle-event-during-call", "a scenario boundary during the host call", rd == null ? "null" : rd.Short);
            int completionsBefore = x.Sender.Calls;
            c.Check(completionsBefore == 1, "only the one successful command sent a completion", "" + completionsBefore);
            object inner = null;
            byte[] e = Cmd.Rid();
            int entered = 0;
            x.Host.InsideCall = delegate
            {
                if (entered++ == 0) inner = Pr.Call(x.Executor, "Execute", Ticket(x, 1, 1, 0.0, 36000000), (Func<int>)delegate { return 0; });
            };
            x.SendSta(e, 1, 36000000);
            x.Tick(16);
            x.Host.InsideCall = null;
            c.Check(inner != null && !(bool)Pr.Get(inner, "Ok") && (string)Pr.Get(inner, "Reason") == "reentrant", "a re-entrant Execute is refused", inner == null ? "null" : "" + Pr.Get(inner, "Reason"));
            c.Check(StateIs(x, e, Ls.Completed, null), "and the outer command is not disturbed", x.Rec(e) == null ? "null" : x.Rec(e).Short);
            c.Check(x.Host.MaxInside == 1, "never two host calls at once", "" + x.Host.MaxInside);
            c.Check(x.Illegal == 0, "illegal-transition 0", "" + x.Illegal);
        }

        // =====================================================================================================================================
        [Case("LJX-32", "an executed jump leaves the official jump note for the row; a failed one does not",
            Purpose = "the runner tells the session about an official jump before the row is written",
            Operation = "TickPre alone (claim, host sequence), then the session Tick; and a failing sequence",
            Expected = "after an executed jump the session has the note pending, the next row consumes it; after a failed sequence there is no note",
            Contract = "LJX-1 spec 5 (NoteOfficialJump)")]
        internal static void Ljx32(Ctx c)
        {
            LxRig x = c.Own(LxRig.Make(c, new LxOpts()));
            byte[] rid = Cmd.Rid();
            x.SendSta(rid, 1, 36000000);
            x.PreOnly();
            c.Check(x.Host.ApiCalls == 2, "TickPre ran the host sequence", "" + x.Host.ApiCalls);
            c.Check((bool)Pr.Get(x.Session, "officialJumpPending"), "the session has the official jump note pending");
            c.Check(StateIs(x, rid, Ls.CompletionPending, null), "the command waits for its completion", x.Rec(rid) == null ? "null" : x.Rec(rid).Short);
            c.Check(x.Sender.Calls == 0, "nothing is sent before the row");
            Pr.Call(x.Session, "OnTick", TimeSpan.FromMilliseconds(16.0));
            c.Check(!(bool)Pr.Get(x.Session, "officialJumpPending"), "the row consumed the note");
            Pr.Call(x.Runner, "TickPost");
            c.Check(StateIs(x, rid, Ls.Completed, null) && x.Sender.Calls == 1, "TickPost sent the completion", x.Sender.Calls + " " + (x.Rec(rid) == null ? "null" : x.Rec(rid).Short));
            x.Host.ThrowOn = "MoveToStation";
            byte[] bad = Cmd.Rid();
            x.SendSta(bad, 1, 36000000);
            x.PreOnly();
            c.Check(!(bool)Pr.Get(x.Session, "officialJumpPending"), "a failed sequence leaves no note");
            c.Check(StateIs(x, bad, Ls.Failed, null), "the failed command is Failed", x.Rec(bad) == null ? "null" : x.Rec(bad).Short);
        }
        // =====================================================================================================================================
        [Case("LJX-99", "no port or mapping of these cases remains",
            Kind = "GUARD",
            Purpose = "residue check of the whole run",
            Operation = "compare the seam counters of the kit",
            Expected = "every opened port and mapping was released",
            Contract = "2A-alpha WIN-99 spirit")]
        internal static void Ljx99(Ctx c)
        {
            GC.Collect();
            GC.WaitForPendingFinalizers();
            bool ok = Wait.For(delegate { return Res.OpenPorts == 0 && Res.OpenMappings == 0; }, 5000);
            c.Check(ok, "no open port or mapping", "ports " + Res.OpenPorts + " (opened " + Res.PortsOpened + "), mappings " + Res.OpenMappings + " (opened " + Res.MappingsOpened + ")");
            c.Check(Net.FixedSendsRefused == 0, "no send to a fixed product port was attempted by the run", "" + Net.FixedSendsRefused);
        }
    }
}
