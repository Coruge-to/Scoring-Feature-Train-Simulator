// PHASE PID-D4 / SLICE 1 test fixture (C# 5 on purpose: Windows PowerShell's Add-Type compiles it). Compiled TOGETHER with TelemetryTestFixture.cs into an assembly NAMED
// TsScoringLegacyTelemetryTests, which the Legacy telemetry DLL lets see its internals (InternalsVisibleTo). It drives the REAL built DLL: the real LegacyTelemetrySession
// (through the fake Legacy API of TelemetryTestFixture.cs), the real LegacyDataPlaneSink and the real Current routing core that the DLL links from CurrentDataPlane.cs.
// Two kinds of checks: (1) a rig with a fake clock, probe, Directory source and transport (every datagram is inspected), and (2) the production wiring against real named
// events / mappings of a synthetic BVE process id and real loopback sockets owned by the test. Nothing touches BVE, AtsEX, the fixed ports 54321 / 54322 or the user's disk
// (the diagnostic files are written to a temporary folder).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;

namespace TsScoringLegacyTelemetryTests
{
    public class DpProbe : ICallerProbe
    {
        public volatile bool Enabled;
        public volatile bool Ready;
        public bool EnabledExists() { return Enabled; }
        public bool ReadyExists() { return Ready; }
    }

    public class DpClock
    {
        private long ms;
        public long Now() { return Interlocked.Read(ref ms); }
        public void Set(long value) { Interlocked.Exchange(ref ms, value); }
        public void Add(long delta) { Interlocked.Add(ref ms, delta); }
    }

    public class DpTransport : ITelemetryTransport
    {
        private readonly object gate = new object();
        private readonly List<byte[]> data = new List<byte[]>();
        private readonly List<IPEndPoint> to = new List<IPEndPoint>();
        public bool Throw;

        public void Send(byte[] bytes, IPEndPoint destination)
        {
            if (Throw) { throw new IOException("transport"); }
            lock (gate) { data.Add((byte[])bytes.Clone()); to.Add(destination); }
        }

        public int Count { get { lock (gate) { return data.Count; } } }
        public byte[] DataAt(int i) { lock (gate) { return data[i]; } }
        public IPEndPoint ToAt(int i) { lock (gate) { return to[i]; } }
    }

    internal sealed class DpSource : IEndpointSource
    {
        private readonly object gate = new object();
        private TelemetryEndpoint endpoint;
        private string reason = "telemetry-directory-missing";
        private int calls;

        public int Calls { get { lock (gate) { return calls; } } }

        public void Set(uint port, uint generation, byte tokenSeed, string instance, uint capabilities)
        {
            lock (gate) { endpoint = new TelemetryEndpoint((uint)DpRig.Pid, instance, 777U, port, generation, DpRig.Token(tokenSeed), 5U, capabilities); }
        }

        public void Clear(string why)
        {
            lock (gate) { endpoint = null; reason = why; }
        }

        public bool TryResolve(int bveProcessId, out TelemetryEndpoint result, out string why)
        {
            lock (gate)
            {
                calls++;
                result = endpoint;
                why = endpoint != null ? "ok" : reason;
                return endpoint != null;
            }
        }
    }

    /// <summary>A transport that wraps the REAL socket transport and notes any datagram that leaves after the owner saw Close() return.</summary>
    public class DpGuardTransport : ITelemetryTransport
    {
        private readonly LegacyUdpTransport inner;
        private int after;
        private int sent;
        public volatile bool ClosedReturned;

        internal DpGuardTransport(LegacyUdpTransport inner) { this.inner = inner; }

        public int SendsAfterClose { get { return Interlocked.CompareExchange(ref after, 0, 0); } }
        public int Sent { get { return Interlocked.CompareExchange(ref sent, 0, 0); } }

        public void Send(byte[] data, IPEndPoint destination)
        {
            bool wasClosed = ClosedReturned;
            inner.Send(data, destination);          // throws when the socket is closed
            Interlocked.Increment(ref sent);
            if (wasClosed) { Interlocked.Increment(ref after); }
        }
    }

    public class DpEnv
    {
        public uint Type;
        public uint BvePid;
        public uint SenderPid;
        public uint Generation;
        public string Instance;
        public string TokenHex;
        public string Text;
        public bool RequestIdZero;
        public int Port;
    }

    /// <summary>The real session + the real sink over a fake clock / probe / Directory source / transport.</summary>
    public class DpRig
    {
        public const int Pid = 4242;
        public const string Inst = "0123456789abcdef0123456789abcdef";
        public const uint CapsText = 3U;          // ENVELOPE_V1 | LEGACY_TEXT_PAYLOAD

        public FakeApi Api = new FakeApi();
        public DpProbe Probe = new DpProbe();
        public DpClock Clock = new DpClock();
        public DpTransport Transport = new DpTransport();
        internal DpSource Source = new DpSource();
        public CollectDiag Diag = new CollectDiag();
        public List<string> RouterLog = new List<string>();
        public long Now = 1000;
        public long Seed = 5000000000L;
        public IPEndPoint Legacy = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 54321);
        internal CurrentTelemetryRouter Router;
        internal LegacyDataPlaneSink Sink;
        internal LegacyTelemetrySession Session;

        public DpRig()
        {
            Build(null, null);
        }

        internal DpRig(ITelemetryTransport customTransport, LegacyUdpTransport closeable)
        {
            Build(customTransport, closeable);
        }

        private void LogR(string text)
        {
            lock (RouterLog) { RouterLog.Add(text); }
        }

        private void Build(ITelemetryTransport customTransport, LegacyUdpTransport closeable)
        {
            CurrentModeLatch latch = new CurrentModeLatch(Probe, Clock.Now, CurrentModeLatch.DefaultHoldOffMs, LogR);
            ITelemetryTransport t = customTransport != null ? customTransport : (ITelemetryTransport)Transport;
            Router = new CurrentTelemetryRouter(Pid, t, Legacy, Source, latch, Clock.Now, LogR);
            Sink = new LegacyDataPlaneSink(Router, closeable != null ? closeable : new LegacyUdpTransport(), LogR);
            Session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, Diag);
        }

        public static byte[] Token(byte seed)
        {
            byte[] t = new byte[16];
            for (int i = 0; i < 16; i++) { t[i] = (byte)(seed + i); }
            return t;
        }

        public static string Hex(byte[] b)
        {
            return BitConverter.ToString(b).Replace("-", string.Empty).ToLowerInvariant();
        }

        public void Tick() { Session.OnTick(TimeSpan.FromMilliseconds(16.0)); }

        public void Run(int ticks, int stepMs)
        {
            for (int i = 0; i < ticks; i++)
            {
                Now += stepMs;
                Api.TimeMs += stepMs;
                Clock.Add(stepMs);
                Session.OnTick(TimeSpan.FromMilliseconds((double)stepMs));
            }
        }

        public string Heartbeat() { return Session.ComposeHeartbeat(); }

        /// <summary>What OnHeartbeat of the host adapter does: compose, and hand a non-null text to the sink.</summary>
        public void Beat()
        {
            string text = Session.ComposeHeartbeat();
            if (text != null) { Sink.Send(text); }
        }

        public void Dispose() { Session.OnDispose(); }

        public void AddStations()
        {
            FakeStation a = new FakeStation(); a.Name = "A"; a.Location = 0.0;
            FakeStation b = new FakeStation(); b.Name = "B"; b.Location = 1000.0; b.ArrivalMs = 36100000; b.DepartureMs = 36130000;
            FakeStation c = new FakeStation(); c.Name = "C"; c.Location = 2000.0; c.Pass = true;
            FakeStation d = new FakeStation(); d.Name = "D"; d.Location = 3000.0; d.ArrivalMs = 36400000; d.IsTerminal = true;
            Api.Stations.Add(a); Api.Stations.Add(b); Api.Stations.Add(c); Api.Stations.Add(d);
        }

        public DpEnv Env(int i)
        {
            Envelope e = DataPlaneProtocol.DecodeEnvelope(Transport.DataAt(i));
            return Describe(e, Transport.ToAt(i));
        }

        internal static DpEnv Describe(Envelope e, IPEndPoint to)
        {
            DpEnv r = new DpEnv();
            r.Type = e.MessageType; r.BvePid = e.BvePid; r.SenderPid = e.SenderPid; r.Generation = e.Generation; r.Instance = e.AppInstance;
            r.TokenHex = Hex(e.Token); r.Text = Encoding.UTF8.GetString(e.Payload);
            bool zero = true;
            for (int i = 0; i < e.RequestId.Length; i++) { if (e.RequestId[i] != 0) { zero = false; } }
            r.RequestIdZero = zero;
            r.Port = to == null ? -1 : to.Port;
            return r;
        }
    }

    public static class LegacyDataPlaneTestFixture
    {
        private static List<string> failures;
        private static int checks;

        private static void Check(string id, bool ok) { checks++; if (!ok) { failures.Add(id); } }

        private static bool IsEnvelope(byte[] data)
        {
            try { DataPlaneProtocol.DecodeEnvelope(data); return true; } catch { return false; }
        }

        private static uint ExpectedType(string text)
        {
            if (text.StartsWith("SCENARIO_ID:")) return 1U;
            if (text.StartsWith("STATUS:")) return 2U;
            if (text.StartsWith("STALIST:")) return 3U;
            if (text.StartsWith("META:")) return 4U;
            return 0U;
        }

        public static string[] Run(string goldenFolder)
        {
            failures = new List<string>();
            checks = 0;
            Classification();
            ManagedSend();
            PlainEquivalence();
            FailClosed();
            Rediscovery();
            NormalMode();
            HoldOff();
            Heartbeat();
            ConcurrencyAndShutdown();
            RealWiring();
            Logging();
            if (!string.IsNullOrEmpty(goldenFolder)) { WriteGolden(goldenFolder); }
            failures.Insert(0, "CHECKS=" + checks);
            return failures.ToArray();
        }

        // ---- A: the four message kinds -----------------------------------------------------------------------------------------------------------
        private static void Classification()
        {
            Check("A01 SCENARIO_ID is type 1", LegacyMessageClassifier.Classify("SCENARIO_ID:5,SPEED:1") == 1U);
            Check("A02 STATUS is type 2", LegacyMessageClassifier.Classify("STATUS:LOADED:PAUSED") == 2U);
            Check("A03 STALIST is type 3", LegacyMessageClassifier.Classify("STALIST:A=0=0") == 3U);
            Check("A04 META is type 4", LegacyMessageClassifier.Classify("META:a:b:c:d:e") == 4U);
            Check("A05 anything else has no type", LegacyMessageClassifier.Classify("HELLO") == 0U && LegacyMessageClassifier.Classify(string.Empty) == 0U && LegacyMessageClassifier.Classify(null) == 0U
                && LegacyMessageClassifier.Classify("JUMP_COMPLETE:STA:1:2:3:4") == 0U && LegacyMessageClassifier.Classify("scenario_id:5") == 0U);
            Check("A06 the type values are the contract values of the Current sender", DataPlaneMessageTypes.Telemetry == 1U && DataPlaneMessageTypes.Heartbeat == 2U && DataPlaneMessageTypes.StationList == 3U && DataPlaneMessageTypes.Metadata == 4U);
        }

        // ---- A: managed transmission --------------------------------------------------------------------------------------------------------------
        private static void ManagedSend()
        {
            DpRig r = new DpRig(); r.Probe.Enabled = true; r.Source.Set(40010, 9, 7, DpRig.Inst, DpRig.CapsText);
            r.AddStations();
            r.Tick(); r.Run(3, 16);
            r.Now += 200; r.Beat();                           // no Tick for 200 ms: the heartbeat reports PAUSED
            int n = r.Transport.Count;
            Check("M01 the session produced datagrams (STALIST, META, lines, heartbeat)", n >= 6);
            bool allEnvelopes = true, typesOk = true, fieldsOk = true, portOk = true, reqOk = true;
            bool seen1 = false, seen2 = false, seen3 = false, seen4 = false;
            for (int i = 0; i < n; i++)
            {
                if (!IsEnvelope(r.Transport.DataAt(i))) { allEnvelopes = false; continue; }
                DpEnv e = r.Env(i);
                if (e.Type != ExpectedType(e.Text) || e.Type == 0U) { typesOk = false; }
                if (e.Type == 1U) seen1 = true; if (e.Type == 2U) seen2 = true; if (e.Type == 3U) seen3 = true; if (e.Type == 4U) seen4 = true;
                if (e.BvePid != (uint)DpRig.Pid || e.SenderPid != (uint)DpRig.Pid || e.Generation != 9U || e.Instance != DpRig.Inst || e.TokenHex != DpRig.Hex(DpRig.Token(7))) { fieldsOk = false; }
                if (!e.RequestIdZero) { reqOk = false; }
                if (e.Port != 40010) { portOk = false; }
            }
            Check("M02 every datagram is an Envelope v1", allEnvelopes);
            Check("M03 SCENARIO_ID lines are type 1, STATUS type 2, STALIST type 3, META type 4 (each payload is the type its prefix names)", typesOk && seen1 && seen2 && seen3 && seen4);
            Check("M04 BvePid, SenderPid = BvePid, generation, AppInstance and token are those of the published endpoint", fieldsOk);
            Check("M05 every datagram goes to the dynamic Directory port and none anywhere else", portOk);
            Check("M06 the RequestId of every Legacy telemetry datagram is zero (no jump exists in Slice 1)", reqOk);
            Check("M07 fixed 54321 plain sends: 0 (counter and destinations)", r.Router.PlainSent == 0 && r.Router.WrappedSent == n && r.Transport.Count == n);
            bool no54321 = true;
            for (int i = 0; i < n; i++) { if (r.Transport.ToAt(i).Port == 54321 || r.Transport.ToAt(i).Port == 54322) { no54321 = false; } }
            Check("M08 not one datagram to 54321 or 54322", no54321);
            Check("M09 the hold-off does not apply to managed mode and the Directory is the only source of the destination", r.Router.Mode == CurrentSenderMode.Managed && r.Source.Calls >= n);
            string hbText = r.Env(n - 1).Text;
            Check("M10 the PAUSED heartbeat is a type 2 envelope carrying the unchanged text", hbText == "STATUS:LOADED:PAUSED" && r.Env(n - 1).Type == 2U);
            Check("M11 the first managed send is logged once with the dynamic port and generation (the live evidence: the STALIST goes out first), and no plain send is ever logged",
                r.RouterLog.FindAll(delegate (string s) { return s.StartsWith("event=first-send-managed type=3 port=40010 gen=9"); }).Count == 1
                && r.RouterLog.FindAll(delegate (string s) { return s.StartsWith("event=first-send-managed"); }).Count == 1
                && !r.RouterLog.Exists(delegate (string s) { return s.StartsWith("event=first-send-plain"); }));
        }

        // ---- the managed payloads are exactly the texts the plain sink gets for the same session ---------------------------------------------------------
        private static void PlainEquivalence()
        {
            Harness h = new Harness(); h.Api.Stations.Add(St("A", 0.0)); h.Api.Stations.Add(St("B", 1000.0));
            h.Tick(); h.Run(3, 16);
            DpRig m = new DpRig(); m.Probe.Enabled = true; m.Source.Set(40011, 2, 3, DpRig.Inst, DpRig.CapsText);
            m.Api.Stations.Add(St("A", 0.0)); m.Api.Stations.Add(St("B", 1000.0));
            m.Tick(); m.Run(3, 16);
            bool same = h.Sink.Sent.Count == m.Transport.Count;
            for (int i = 0; same && i < h.Sink.Sent.Count; i++) { same = h.Sink.Sent[i] == m.Env(i).Text; }
            Check("E01 the managed payloads, in order, are byte for byte the texts of the plain sink (the session is not changed)", same && h.Sink.Sent.Count >= 5);
        }

        private static FakeStation St(string name, double location)
        {
            FakeStation s = new FakeStation(); s.Name = name; s.Location = location;
            return s;
        }

        // ---- A: fail closed ----------------------------------------------------------------------------------------------------------------------
        private static void FailClosed()
        {
            string[] reasons = new string[] { "app-directory-missing", "app-directory-torn", "app-directory-invalid", "app-directory-not-ready", "telemetry-directory-missing",
                "telemetry-directory-torn", "telemetry-directory-invalid", "telemetry-not-ready", "bve-pid-mismatch", "app-instance-mismatch", "app-pid-mismatch" };
            foreach (string reason in reasons)
            {
                DpRig r = new DpRig(); r.Probe.Ready = true; r.Source.Clear(reason); r.AddStations();
                r.Tick(); r.Run(3, 16); r.Now += 200; r.Beat();
                Check("F01 " + reason + ": nothing sent, no fallback, counted", r.Transport.Count == 0 && r.Router.PlainSent == 0 && r.Router.WrappedSent == 0 && r.Router.FailClosed > 0 && r.Router.ReasonCount(reason) > 0);
            }

            DpRig c = new DpRig(); c.Probe.Enabled = true; c.Source.Set(40012, 1, 1, DpRig.Inst, 0U);
            c.Tick(); c.Run(2, 16);
            Check("F02 capabilities without ENVELOPE_V1: fail closed (capability-missing), nothing sent", c.Transport.Count == 0 && c.Router.ReasonCount("capability-missing") > 0);

            DpRig d = new DpRig(); d.Probe.Enabled = true; d.Source.Set(40013, 1, 1, DpRig.Inst, DpRig.CapsText);
            d.Tick(); d.Run(2, 16);
            int before = d.Transport.Count;
            d.Source.Clear("telemetry-not-ready");
            d.Run(3, 16);
            Check("F03 a withdrawn / not READY Directory stops the sending at once (no blind reuse of the last endpoint)", before > 0 && d.Transport.Count == before);
            d.Run(20, 16);
            d.Source.Set(40014, 2, 2, DpRig.Inst, DpRig.CapsText);
            d.Run(20, 16);
            Check("F04 when the Directory is READY again the sending resumes, to the new endpoint only", d.Transport.Count > before && d.Transport.ToAt(d.Transport.Count - 1).Port == 40014);
            Check("F05 and fixed 54321 was never used in the whole run", d.Router.PlainSent == 0);
        }

        // ---- A: endpoint changes ------------------------------------------------------------------------------------------------------------------
        private static void Rediscovery()
        {
            DpRig r = new DpRig(); r.Probe.Enabled = true; r.Source.Set(40040, 1, 1, DpRig.Inst, DpRig.CapsText);
            r.Tick(); r.Run(5, 16);
            int before = r.Transport.Count;
            string other = "fedcba0987abcdeffedcba0987abcdef";
            r.Source.Set(40041, 6, 9, other, 1U);
            r.Clock.Add(1);
            r.Run(5, 16);
            bool oldUsed = false, newOk = r.Transport.Count > before;
            for (int i = before; i < r.Transport.Count; i++)
            {
                DpEnv e = r.Env(i);
                if (r.Transport.ToAt(i).Port == 40040 || e.Generation == 1U) { oldUsed = true; }
                if (r.Transport.ToAt(i).Port != 40041 || e.Instance != other || e.Generation != 6U || e.TokenHex != DpRig.Hex(DpRig.Token(9))) { newOk = false; }
            }
            Check("R01 after the endpoint changed (port, instance, generation, token) every datagram carries only the new identity and goes to the new port", newOk && !oldUsed);
            Check("R02 the change is logged as endpoint-changed", r.RouterLog.Exists(delegate (string s) { return s.StartsWith("event=endpoint-changed"); }));
            int mid = r.Transport.Count;
            r.Source.Set(40041, 7, 5, other, 1U);                       // same port, new generation and token
            r.Run(3, 16);
            DpEnv last = r.Env(r.Transport.Count - 1);
            Check("R03 recreation on the same port (new generation / token): only the new generation and token are used", r.Transport.Count > mid && last.Generation == 7U && last.TokenHex == DpRig.Hex(DpRig.Token(5)));
            r.Transport.Throw = true;
            bool threw = false;
            try { r.Run(2, 16); r.Now += 200; r.Beat(); } catch { threw = true; }
            Check("R04 a managed transport failure never throws out of the session or the heartbeat and is counted", !threw && r.Router.SendFailures > 0);
            r.Transport.Throw = false;
            int resumeFrom = r.Transport.Count;
            r.Run(3, 16);
            Check("R05 and the sending recovers", r.Transport.Count > resumeFrom);
        }

        // ---- B: normal mode ----------------------------------------------------------------------------------------------------------------------
        private static void NormalMode()
        {
            // the same session through the OLD plain sink (CollectSink) is the reference
            Harness h = new Harness(); h.Api.Stations.Add(St("A", 0.0)); h.Api.Stations.Add(St("B", 1000.0));
            h.Tick(); h.Run(6, 16);
            DpRig n = new DpRig();
            n.Source.Set(40050, 1, 1, DpRig.Inst, DpRig.CapsText);          // a perfectly valid managed Directory exists - it must NOT be adopted in normal mode
            n.Api.Stations.Add(St("A", 0.0)); n.Api.Stations.Add(St("B", 1000.0));
            n.Router.Begin(); n.Clock.Set(2100);                              // the hold-off elapses with neither Enabled nor Ready observed: normal mode
            n.Tick(); n.Run(6, 16);
            Check("N01 mode is normal after the hold-off without Enabled / Ready", n.Router.Mode == CurrentSenderMode.Normal);
            bool same = n.Transport.Count == h.Sink.Sent.Count;
            for (int i = 0; same && i < n.Transport.Count; i++) { same = Encoding.UTF8.GetString(n.Transport.DataAt(i)) == h.Sink.Sent[i]; }
            Check("N02 the plain datagrams are byte for byte, in the same order, those of the old plain sink", same && n.Transport.Count >= 7);
            bool dest = true, noEnv = true;
            for (int i = 0; i < n.Transport.Count; i++)
            {
                IPEndPoint to = n.Transport.ToAt(i);
                if (to.Port != 54321 || !to.Address.Equals(IPAddress.Parse("127.0.0.1"))) { dest = false; }
                if (IsEnvelope(n.Transport.DataAt(i))) { noEnv = false; }
            }
            Check("N03 every datagram goes to 127.0.0.1:54321 and none is wrapped", dest && noEnv && n.Router.WrappedSent == 0 && n.Router.PlainSent == n.Transport.Count);
            Check("N04 the Directory is never consulted in normal mode (the managed Directory is not adopted)", n.Source.Calls == 0);
            n.Sink.Send("HELLO");
            Check("N05 a text of no known kind is still sent plain in normal mode (what the old sink did)", n.Transport.Count > 0 && Encoding.UTF8.GetString(n.Transport.DataAt(n.Transport.Count - 1)) == "HELLO");
            n.Sink.Send(string.Empty);
            Check("N06 an empty text is sent as an empty plain datagram, as before", n.Transport.DataAt(n.Transport.Count - 1).Length == 0);

            DpRig m = new DpRig(); m.Probe.Enabled = true; m.Source.Set(40051, 1, 1, DpRig.Inst, DpRig.CapsText);
            m.Tick(); int cnt = m.Transport.Count;
            m.Sink.Send("HELLO");
            Check("N07 managed mode drops a text of no known kind: never invented as telemetry, never sent plain", m.Transport.Count == cnt && m.Sink.UnclassifiedDropped == 1 && m.Router.PlainSent == 0);
            m.Sink.Send("HELLO2");
            Check("N08 the drop is reported once", m.RouterLog.FindAll(delegate (string s) { return s == "event=unclassified-text-dropped"; }).Count == 1 && m.Sink.UnclassifiedDropped == 2);

            // the latch: a late Ready upgrades normal to managed, and managed is never left again
            DpRig u = new DpRig(); u.Source.Set(40052, 1, 1, DpRig.Inst, DpRig.CapsText);
            u.Router.Begin(); u.Clock.Set(2100); u.Sink.Send("SCENARIO_ID:1,SPEED:0");
            u.Probe.Ready = true; u.Clock.Set(3500); u.Sink.Send("SCENARIO_ID:2,SPEED:0");
            u.Probe.Ready = false; u.Clock.Set(60000); u.Sink.Send("SCENARIO_ID:3,SPEED:0");
            int plain = 0, wrapped = 0;
            for (int i = 0; i < u.Transport.Count; i++) { if (IsEnvelope(u.Transport.DataAt(i))) wrapped++; else plain++; }
            Check("N09 plain while normal, wrapped after a late Ready, still wrapped after Ready is gone (latched)", plain == 1 && wrapped == 2 && u.Router.Mode == CurrentSenderMode.Managed);
        }

        // ---- the first 2 seconds ------------------------------------------------------------------------------------------------------------------
        private static void HoldOff()
        {
            DpRig r = new DpRig(); r.Source.Set(40060, 1, 1, DpRig.Inst, DpRig.CapsText); r.AddStations();
            r.Tick();
            Check("H01 during the hold-off (neither Enabled nor Ready seen yet) nothing is sent", r.Transport.Count == 0 && r.Router.Mode == CurrentSenderMode.Undetermined && r.Router.Held > 0);
            r.Run(100, 16);                                            // 1.6 s of simulation time
            Check("H02 still nothing at 1.6 s", r.Transport.Count == 0);
            r.Run(80, 16);                                             // 2.9 s
            Check("H03 after the hold-off the normal mode sends again", r.Transport.Count > 0 && r.Router.Mode == CurrentSenderMode.Normal);
            bool sta = false, meta = false;
            for (int i = 0; i < r.Transport.Count; i++) { string t = Encoding.UTF8.GetString(r.Transport.DataAt(i)); if (t.StartsWith("STALIST:")) sta = true; if (t.StartsWith("META:")) meta = true; }
            Check("H04 STALIST and META were not lost for good by the hold-off", sta && meta);
        }

        // ---- C: the heartbeat ----------------------------------------------------------------------------------------------------------------------
        private static void Heartbeat()
        {
            DpRig r = new DpRig(); r.Probe.Enabled = true; r.Source.Set(40070, 1, 1, DpRig.Inst, DpRig.CapsText);
            Check("C01 no heartbeat before the first scenario instance (nothing to report)", r.Heartbeat() == null);
            r.Beat();
            Check("C02 and nothing is sent for it", r.Transport.Count == 0);
            r.Tick();
            int c0 = r.Transport.Count;
            r.Beat();
            Check("C03 RUNNING right after a Tick: type 2 with the unchanged text", r.Transport.Count == c0 + 1 && r.Env(c0).Type == 2U && r.Env(c0).Text == "STATUS:LOADED:RUNNING");
            r.Now += 500; r.Beat();
            Check("C04 PAUSED above 100 ms without a Tick: type 2 STATUS:LOADED:PAUSED", r.Env(r.Transport.Count - 1).Type == 2U && r.Env(r.Transport.Count - 1).Text == "STATUS:LOADED:PAUSED");
            r.Session.OnScenarioClosed();
            int c1 = r.Transport.Count; r.Beat();
            Check("C05 no heartbeat after the scenario ended", r.Transport.Count == c1);
            r.Dispose();
            r.Beat();
            Check("C06 no heartbeat after Dispose, and the router is closed", r.Transport.Count == c1 && r.Sink.Router.Begin().Mode == CurrentSenderMode.Undetermined);
        }

        // ---- C: threads, endpoint switching and shutdown ------------------------------------------------------------------------------------------
        private static void ConcurrencyAndShutdown()
        {
            // 1. endpoint switching while the Tick thread and three heartbeat threads send: every datagram is internally consistent (its destination port belongs to the identity it carries)
            DpRig r = new DpRig(); r.Probe.Enabled = true; r.Source.Set(41001, 1, 11, DpRig.Inst, DpRig.CapsText); r.AddStations();
            r.Tick();
            Exception error = null;
            bool stop = false;
            Thread flipper = new Thread(delegate ()
            {
                int k = 0;
                while (!stop)
                {
                    k++;
                    int slot = k % 3;
                    r.Source.Set((uint)(41001 + slot), (uint)(1 + slot), (byte)(11 + slot), slot == 2 ? "fedcba0987abcdeffedcba0987abcdef" : DpRig.Inst, DpRig.CapsText);
                    Thread.Sleep(1);
                }
            });
            List<Thread> workers = new List<Thread>();
            for (int i = 0; i < 3; i++)
            {
                workers.Add(new Thread(delegate () { try { for (int j = 0; j < 400; j++) { r.Beat(); } } catch (Exception e) { error = e; } }));
            }
            workers.Add(new Thread(delegate () { try { for (int j = 0; j < 100; j++) { r.Run(1, 16); } } catch (Exception e) { error = e; } }));
            flipper.Start();
            foreach (Thread t in workers) t.Start();
            foreach (Thread t in workers) t.Join();
            stop = true; flipper.Join();
            bool consistent = true;
            int total = r.Transport.Count;
            for (int i = 0; i < total; i++)
            {
                DpEnv e = r.Env(i);
                int slot = e.Port - 41001;
                bool ok = slot >= 0 && slot <= 2 && e.Generation == (uint)(1 + slot) && e.TokenHex == DpRig.Hex(DpRig.Token((byte)(11 + slot))) && e.Instance == (slot == 2 ? "fedcba0987abcdeffedcba0987abcdef" : DpRig.Inst);
                if (!ok) { consistent = false; }
            }
            Check("T01 endpoint switching under Tick + heartbeat threads: no exception, and no datagram mixes the destination of one endpoint with the identity of another", error == null && consistent && total > 100);

            // 2. shutdown racing the heartbeat timer thread: with the REAL socket transport, no datagram leaves after Close() returned
            UdpClient rx = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            int rxPort = ((IPEndPoint)rx.Client.LocalEndPoint).Port;
            int sendsAfter = 0, exceptions = 0, rounds = 25;
            for (int round = 0; round < rounds; round++)
            {
                LegacyUdpTransport real = new LegacyUdpTransport();
                DpGuardTransport guard = new DpGuardTransport(real);
                DpRig g = new DpRig(guard, real);
                g.Probe.Enabled = true; g.Source.Set((uint)rxPort, 1, 1, DpRig.Inst, DpRig.CapsText);
                g.Tick();
                bool go = true;
                List<Thread> beats = new List<Thread>();
                for (int i = 0; i < 3; i++)
                {
                    beats.Add(new Thread(delegate () { try { while (go) { g.Beat(); } } catch { Interlocked.Increment(ref exceptions); } }));
                }
                foreach (Thread t in beats) t.Start();
                Thread.Sleep(5 + (round % 7));
                g.Sink.Close();
                guard.ClosedReturned = true;
                Thread.Sleep(15);
                go = false;
                foreach (Thread t in beats) t.Join();
                sendsAfter += guard.SendsAfterClose;
                g.Sink.Send("SCENARIO_ID:1,SPEED:0");
                g.Sink.Close();
                if (guard.SendsAfterClose != 0) { sendsAfter++; }
            }
            rx.Close();
            Check("T02 shutdown vs the heartbeat timer thread (25 rounds, real socket): no exception, no datagram after Close() returned, Close twice is harmless", sendsAfter == 0 && exceptions == 0);

            // 3. after Dispose of the session the sink stays closed
            DpRig d = new DpRig(); d.Probe.Enabled = true; d.Source.Set(41010, 1, 1, DpRig.Inst, DpRig.CapsText);
            d.Run(5, 16); d.Dispose();
            int n0 = d.Transport.Count;
            d.Run(5, 16); d.Session.OnScenarioOpened(false); d.Session.OnScenarioCreated(); d.Beat(); d.Sink.Send("SCENARIO_ID:9,SPEED:1");
            Check("T03 after Dispose nothing is sent, whatever arrives", d.Transport.Count == n0 && n0 > 0);
            Check("T03b the router's summary line was written once at the close", d.RouterLog.FindAll(delegate (string s) { return s.StartsWith("event=summary"); }).Count == 1);
        }

        // ---- the production wiring against real events / mappings / sockets ---------------------------------------------------------------------------
        private static void W32(byte[] b, int o, uint v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }

        private static byte[] AppBlock(int pid, uint seq, uint flags, string inst, uint appPid)
        {
            byte[] b = new byte[80];
            W32(b, 0, 0x44415354U); W32(b, 4, 1U); W32(b, 8, 80U); W32(b, 12, (uint)pid); W32(b, 16, seq); W32(b, 20, flags);
            if (inst != null) { Array.Copy(Encoding.ASCII.GetBytes(inst), 0, b, 24, 32); }
            W32(b, 56, appPid); W32(b, 60, 1U); W32(b, 76, seq);
            return b;
        }

        private sealed class LiveMap : IDisposable
        {
            private readonly MemoryMappedFile map;
            private readonly int size;
            internal LiveMap(string name, byte[] data) { size = data.Length; map = MemoryMappedFile.CreateNew(name, size, MemoryMappedFileAccess.ReadWrite); Write(data); }
            internal void Write(byte[] data)
            {
                using (MemoryMappedViewAccessor v = map.CreateViewAccessor(0, size, MemoryMappedFileAccess.ReadWrite)) { v.WriteArray(0, data, 0, size); }
            }
            public void Dispose() { map.Dispose(); }
        }

        private static byte[] Receive(UdpClient client, int timeoutMs)
        {
            client.Client.ReceiveTimeout = timeoutMs;
            try { IPEndPoint any = new IPEndPoint(IPAddress.Any, 0); return client.Receive(ref any); }
            catch (SocketException) { return null; }
        }

        private static void Drain(UdpClient client)
        {
            while (client.Available > 0) { IPEndPoint any = new IPEndPoint(IPAddress.Any, 0); client.Receive(ref any); }
        }

        private static void RealWiring()
        {
            int curPid = Process.GetCurrentProcess().Id;
            UdpClient plainRx = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            IPEndPoint plainDest = new IPEndPoint(IPAddress.Loopback, ((IPEndPoint)plainRx.Client.LocalEndPoint).Port);
            UdpClient rx = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            UdpClient rx2 = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            int port1 = ((IPEndPoint)rx.Client.LocalEndPoint).Port;
            int port2 = ((IPEndPoint)rx2.Client.LocalEndPoint).Port;
            List<string> log = new List<string>();
            Action<string> logger = delegate (string s) { lock (log) { log.Add(s); } };

            // R-NORMAL: no Enabled / Ready event: the plain text reaches the plain destination (the stand-in of 54321), exactly, after the 2 s hold-off
            int pidN = 2000000000 + (curPid % 50000);
            LegacyDataPlaneSink normal = LegacyDataPlaneSink.Create(pidN, plainDest, logger);
            string wanted = "SCENARIO_ID:1,SPEED:" + char.ConvertFromUtf32(0x99C5);
            byte[] got = null;
            Stopwatch sw = Stopwatch.StartNew();
            while (got == null && sw.ElapsedMilliseconds < 5000) { normal.Send(wanted); got = Receive(plainRx, 50); }
            Check("W01 production wiring, no Caller: the plain UTF-8 text reaches the fixed-destination stand-in unchanged after the hold-off (UTF-8, non-ASCII safe)", got != null && Encoding.UTF8.GetString(got) == wanted && normal.Router.Mode == CurrentSenderMode.Normal);
            Check("W02 and it was sent plain (counter), never wrapped", normal.Router.PlainSent >= 1 && normal.Router.WrappedSent == 0);
            normal.Close();
            normal.Send(wanted);
            Drain(plainRx);
            normal.Send(wanted);
            Check("W03 after Close nothing more is sent", Receive(plainRx, 150) == null);

            // R-MANAGED: the control plane event, the AppDirectory and the Telemetry Directory of a synthetic BVE process, a real receiver socket
            int pid = 2000050000 + (curPid % 49000);
            string appName = "Local\\TSScoringPlugin.v1." + pid + ".AppDirectory";
            string telName = DataPlaneProtocol.TelemetryName((uint)pid, DpRig.Inst);
            uint ready = 1U | 2U | 4U;
            EventWaitHandle enabled = null;
            LiveMap app = null, tel = null;
            LegacyDataPlaneSink sink = null;
            try
            {
                // before anything is published: Enabled exists (the Caller is on) but the Directory does not: managed, fail closed, no plain fallback
                enabled = new EventWaitHandle(false, EventResetMode.ManualReset, "Local\\TSScoringPlugin.v1." + pid + ".Enabled");
                sink = LegacyDataPlaneSink.Create(pid, plainDest, logger);
                for (int i = 0; i < 5; i++) { sink.Send("SCENARIO_ID:1,SPEED:0"); Thread.Sleep(20); }
                Check("W10 Caller ON (Enabled event) but no application Directory: nothing is sent to the Directory port AND nothing to the fixed destination (fail closed, no fallback)", sink.Router.Mode == CurrentSenderMode.Managed
                    && Receive(rx, 100) == null && Receive(plainRx, 100) == null && sink.Router.PlainSent == 0 && sink.Router.ReasonCount("app-directory-missing") > 0);

                app = new LiveMap(appName, AppBlock(pid, 2U, 1U | 2U, DpRig.Inst, 777U));                       // published, process started, NOT ReadyAccepted
                Thread.Sleep(150);
                sink.Send("SCENARIO_ID:1,SPEED:0");
                Check("W11 AppDirectory not ReadyAccepted: nothing sent", Receive(rx, 100) == null && sink.Router.ReasonCount("app-directory-not-ready") > 0);

                app.Write(AppBlock(pid, 4U, ready, DpRig.Inst, 777U));
                Thread.Sleep(150);
                sink.Send("SCENARIO_ID:1,SPEED:0");
                Check("W12 Telemetry Directory absent: nothing sent", Receive(rx, 100) == null && sink.Router.ReasonCount("telemetry-directory-missing") > 0);

                // not READY (PUBLISHED only)
                tel = new LiveMap(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 2U, 1U, DpRig.Inst, 777U, (uint)port1, 3U, DpRig.Token(1), 1U, DpRig.CapsText));
                Thread.Sleep(150);
                sink.Send("SCENARIO_ID:1,SPEED:0");
                Check("W13 Telemetry Directory PUBLISHED but not READY: nothing sent", Receive(rx, 100) == null && sink.Router.ReasonCount("telemetry-not-ready") > 0);

                // ownership mismatches, each with an otherwise READY directory
                string[] names = new string[] { "bve-pid-mismatch", "app-instance-mismatch", "app-pid-mismatch" };
                byte[][] bad = new byte[][]
                {
                    DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid + 1U, 4U, 3U, DpRig.Inst, 777U, (uint)port1, 3U, DpRig.Token(1), 2U, DpRig.CapsText),
                    DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, "fedcba0987abcdeffedcba0987abcdef", 777U, (uint)port1, 3U, DpRig.Token(1), 2U, DpRig.CapsText),
                    DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, DpRig.Inst, 778U, (uint)port1, 3U, DpRig.Token(1), 2U, DpRig.CapsText)
                };
                for (int k = 0; k < 3; k++)
                {
                    tel.Write(bad[k]);
                    Thread.Sleep(150);
                    sink.Send("SCENARIO_ID:1,SPEED:0");
                    Check("W14 " + names[k] + " (BVE PID / AppInstance / AppPid of the Directory differ from the AppDirectory): rejected, nothing sent", Receive(rx, 100) == null && sink.Router.ReasonCount(names[k]) > 0);
                }

                // the good READY directory: the four kinds arrive wrapped on the dynamic port
                tel.Write(DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, DpRig.Inst, 777U, (uint)port1, 3U, DpRig.Token(1), 2U, DpRig.CapsText));
                Thread.Sleep(150);
                string[] texts = new string[] { "STALIST:A=0=0=0=0=0=15000=0=0", "META:T:R:V:A:C", "SCENARIO_ID:1,SPEED:12.5", "STATUS:LOADED:RUNNING" };
                uint[] types = new uint[] { 3U, 4U, 1U, 2U };
                bool good = true;
                for (int k = 0; k < 4; k++)
                {
                    sink.Send(texts[k]);
                    byte[] d = Receive(rx, 1000);
                    if (d == null || !IsEnvelope(d)) { good = false; continue; }
                    Envelope e = DataPlaneProtocol.DecodeEnvelope(d);
                    if (e.MessageType != types[k] || Encoding.UTF8.GetString(e.Payload) != texts[k] || e.Generation != 3U || e.BvePid != (uint)pid || e.SenderPid != (uint)pid || e.AppInstance != DpRig.Inst) { good = false; }
                }
                Check("W15 READY and owned: STALIST / META / telemetry / heartbeat arrive as Envelope v1 (types 3 / 4 / 1 / 2) on the dynamic port with the Directory's generation and instance", good);
                Check("W16 and the fixed destination stand-in received NOTHING in the whole managed run", Receive(plainRx, 100) == null && sink.Router.PlainSent == 0);

                // the endpoint moves (new port, new generation, new token): the old socket gets nothing any more
                tel.Write(DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 6U, 3U, DpRig.Inst, 777U, (uint)port2, 4U, DpRig.Token(2), 3U, DpRig.CapsText));
                Drain(rx); Drain(rx2);
                sink.Send("SCENARIO_ID:2,SPEED:1");
                byte[] moved = Receive(rx2, 1000);
                Envelope me = moved != null && IsEnvelope(moved) ? DataPlaneProtocol.DecodeEnvelope(moved) : null;
                Check("W17 the Directory changed: the next datagram goes to the NEW port with the NEW generation and token, and the old port gets nothing", me != null && me.Generation == 4U && DpRig.Hex(me.Token) == DpRig.Hex(DpRig.Token(2)) && Receive(rx, 100) == null);

                // withdrawn: stops at once
                tel.Write(DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 8U, 7U, DpRig.Inst, 777U, (uint)port2, 4U, DpRig.Token(2), 4U, DpRig.CapsText));
                Thread.Sleep(150);
                Drain(rx2);
                sink.Send("SCENARIO_ID:3,SPEED:1");
                Check("W18 WITHDRAWING: the sending stops at once", Receive(rx2, 150) == null);

                // back to READY, then the AppDirectory is closed
                tel.Write(DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 10U, 3U, DpRig.Inst, 777U, (uint)port2, 5U, DpRig.Token(3), 5U, DpRig.CapsText));
                app.Write(AppBlock(pid, 6U, ready | 16U, DpRig.Inst, 777U));
                Thread.Sleep(150);
                sink.Send("SCENARIO_ID:4,SPEED:1");
                Check("W19 AppDirectory CLOSED: nothing is sent even though the Telemetry Directory still says READY", Receive(rx2, 150) == null);

                sink.Close();
                tel.Write(DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 12U, 3U, DpRig.Inst, 777U, (uint)port2, 5U, DpRig.Token(3), 6U, DpRig.CapsText));
                app.Write(AppBlock(pid, 8U, ready, DpRig.Inst, 777U));
                Thread.Sleep(150);
                sink.Send("SCENARIO_ID:5,SPEED:1");
                Check("W20 after Close nothing is sent even when the Directory is READY again", Receive(rx2, 150) == null);
            }
            finally
            {
                if (sink != null) { sink.Close(); }
                if (tel != null) tel.Dispose();
                if (app != null) app.Dispose();
                if (enabled != null) enabled.Dispose();
                rx.Close(); rx2.Close(); plainRx.Close();
            }
        }

        // ---- D: the diagnostic log name ----------------------------------------------------------------------------------------------------------
        private static void Logging()
        {
            DateTime t1 = new DateTime(2026, 10, 15, 1, 2, 3, DateTimeKind.Utc);
            DateTime t2 = new DateTime(2026, 10, 15, 1, 2, 4, DateTimeKind.Utc);
            string a = FileTelemetryDiag.NameFor(1234, FileTelemetryDiag.StartStamp(t1));
            Check("D01 the name is TSScoring-LegacyTelemetry-P<pid>-T<start>.log", a == "TSScoring-LegacyTelemetry-P1234-T20261015010203.log");
            Check("D02 different BVE processes get different names (pid) and a reused pid a different name (start)", a != FileTelemetryDiag.NameFor(1235, FileTelemetryDiag.StartStamp(t1)) && a != FileTelemetryDiag.NameFor(1234, FileTelemetryDiag.StartStamp(t2)));
            bool ascii = true; foreach (char c in a) { if (c > 127) ascii = false; }
            Check("D03 the name is ASCII only and has no path separator", ascii && a.IndexOfAny(new char[] { '\\', '/', ':' }) < 0);
            string defaultPath = FileTelemetryDiag.DefaultPath();
            string defName = defaultPath == null ? string.Empty : Path.GetFileName(defaultPath);
            System.Text.RegularExpressions.Regex rx = new System.Text.RegularExpressions.Regex("^TSScoring-LegacyTelemetry-P" + Process.GetCurrentProcess().Id + "-T([0-9]{14}|0)\\.log$");
            Check("D04 the production path is this process' own per-PID file in the Downloads folder, not the old fixed name", rx.IsMatch(defName) && defName.IndexOf("L3-Telemetry") < 0 && defaultPath.IndexOf("Downloads") > 0);
            string dir = Path.Combine(Path.GetTempPath(), "tsd4-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(dir);
            try
            {
                FileTelemetryDiag one = new FileTelemetryDiag(111, t1, dir);
                FileTelemetryDiag two = new FileTelemetryDiag(222, t1, dir);
                FileTelemetryDiag three = new FileTelemetryDiag(111, t2, dir);
                File.WriteAllText(Path.Combine(dir, "TSScoring-LegacyTelemetry-P333-T20261015010203.log"), "KEEP");
                for (int i = 0; i < 20; i++)
                {
                    one.Event("TEL_ONE", "n=" + i);
                    two.Event("TEL_TWO", "n=" + i);
                    three.Event("TEL_THREE", "n=" + i);
                }
                string f1 = File.ReadAllText(Path.Combine(dir, FileTelemetryDiag.NameFor(111, FileTelemetryDiag.StartStamp(t1))));
                string f2 = File.ReadAllText(Path.Combine(dir, FileTelemetryDiag.NameFor(222, FileTelemetryDiag.StartStamp(t1))));
                string f3 = File.ReadAllText(Path.Combine(dir, FileTelemetryDiag.NameFor(111, FileTelemetryDiag.StartStamp(t2))));
                Check("D05 three BVE processes write three files and the lines never mix (each file holds only its own events and its own P=pid)",
                    f1.Contains("TEL_ONE") && !f1.Contains("TEL_TWO") && !f1.Contains("TEL_THREE") && f1.Contains(" P=111 ")
                    && f2.Contains("TEL_TWO") && !f2.Contains("TEL_ONE") && !f2.Contains("TEL_THREE") && f2.Contains(" P=222 ")
                    && f3.Contains("TEL_THREE") && !f3.Contains("TEL_ONE") && !f3.Contains("TEL_TWO") && f3.Contains(" P=111 "));
                Check("D06 a file of another process is never touched or truncated", File.ReadAllText(Path.Combine(dir, "TSScoring-LegacyTelemetry-P333-T20261015010203.log")) == "KEEP");
                Check("D07 no file with the old fixed name is created", !File.Exists(Path.Combine(dir, "TSScoring-L3-Telemetry.log")) && Directory.GetFiles(dir, "*L3-Telemetry*").Length == 0);
                Check("D08 the routing core's lines can be logged through the same diagnostic (TEL_DP lines keep the log format)", LogLineOk(dir));
            }
            finally { try { Directory.Delete(dir, true); } catch { } }
        }

        private static bool LogLineOk(string dir)
        {
            FileTelemetryDiag d = new FileTelemetryDiag(444, new DateTime(2026, 10, 15, 0, 0, 0, DateTimeKind.Utc), dir);
            d.Event("TEL_DP", "event=first-send-managed type=1 port=40010 gen=9 t=+5ms");
            string text = File.ReadAllText(Path.Combine(dir, FileTelemetryDiag.NameFor(444, "20261015000000")));
            return System.Text.RegularExpressions.Regex.IsMatch(text, "^\\d\\d:\\d\\d:\\d\\d\\.\\d{3} P=444 I=\\d+ TEL_DP event=first-send-managed type=1 port=40010 gen=9 t=\\+5ms\\r\\n$");
        }

        // ---- the datagrams for the Python interop test (tests\legacy_dataplane_chain_check.py, tests\test_legacy_dataplane_interop_d4.py) -----------------------------
        private static void WriteGolden(string folder)
        {
            Directory.CreateDirectory(folder);
            DpRig r = new DpRig(); r.Probe.Enabled = true; r.Source.Set(40090, 77, 33, DpRig.Inst, DpRig.CapsText);
            r.Api.SpeedMps = 20.0; r.Api.Location = 900.0; r.Api.GradientRatio = -0.0125; r.Api.SignalMps = 25.0; r.Api.ForwardSignalMps = 11.0;
            r.Api.NextSectionLoc = 1500.0; r.Api.GroundMps = 20.0; r.Api.BrakeKind = 2; r.Api.BrakeNotches = 5; r.Api.Holding = true;
            r.Api.Rates = new double[] { 0.0, 0.2, 0.4, 0.6, 0.8, 1.0 }; r.Api.MaxPa = 490000.0;
            FakeStation sa = St("A", 0.0);
            FakeStation sb = St("B", 1000.0); sb.ArrivalMs = 36100000; sb.DepartureMs = 36130000;
            FakeStation sc = St("C", 2000.0); sc.Pass = true;
            FakeStation sd = St("D", 3000.0); sd.ArrivalMs = 36400000; sd.IsTerminal = true;
            r.Api.Stations.Add(sa); r.Api.Stations.Add(sb); r.Api.Stations.Add(sc); r.Api.Stations.Add(sd);
            r.Tick(); r.Run(3, 16);
            r.Now += 200; r.Beat();
            StringBuilder manifest = new StringBuilder();
            for (int i = 0; i < r.Transport.Count; i++)
            {
                File.WriteAllBytes(Path.Combine(folder, "legacy_" + i.ToString("000") + ".bin"), r.Transport.DataAt(i));
                DpEnv e = r.Env(i);
                manifest.Append(i.ToString("000")).Append(' ').Append(e.Type).Append('\n');
            }
            File.WriteAllText(Path.Combine(folder, "legacy_manifest.txt"), manifest.ToString(), new UTF8Encoding(false));
            File.WriteAllText(Path.Combine(folder, "legacy_identity.txt"), DpRig.Pid + "\n" + DpRig.Inst + "\n77\n" + DpRig.Hex(DpRig.Token(33)) + "\n", new UTF8Encoding(false));
        }
    }
}
