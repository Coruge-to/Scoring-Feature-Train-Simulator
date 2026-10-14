using System;
using System.Collections.Generic;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Net;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// PID-D3 offline tests of the Current sender's DataPlane side (CurrentDataPlane.cs + the shared DataPlaneProtocol / TelemetryDirectoryReader).
// No BVE, no BveEX. Compiled by Test-CurrentDataPlaneD3.ps1 together with the three production sources (C# 5 syntax).
// Test ids refer to the PID-D0B-1 automated test specification (DPT/DPC/DPE) and to the owner decisions DEC-1..DEC-4.
public static class CurrentDataPlaneTestFixture
{
    const string Inst = "0123456789abcdef0123456789abcdef";
    const int Pid = 4242;

    sealed class FakeProbe : ICallerProbe
    {
        public bool Enabled, Ready;
        public bool EnabledExists() { return Enabled; }
        public bool ReadyExists() { return Ready; }
    }

    sealed class FakeClock
    {
        public long Ms;
        public long Now() { return Ms; }
    }

    sealed class FakeTransport : ITelemetryTransport
    {
        public List<byte[]> Data = new List<byte[]>();
        public List<IPEndPoint> To = new List<IPEndPoint>();
        public bool Throw;
        public void Send(byte[] data, IPEndPoint destination)
        {
            if (Throw) throw new System.IO.IOException("transport");
            Data.Add((byte[])data.Clone());
            To.Add(destination);
        }
    }

    sealed class FakeSource : IEndpointSource
    {
        public TelemetryEndpoint Endpoint;
        public string Reason = "telemetry-directory-missing";
        public int Calls;
        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            Calls++;
            endpoint = Endpoint;
            reason = Endpoint != null ? "ok" : Reason;
            return Endpoint != null;
        }
    }

    sealed class Rig
    {
        public FakeProbe Probe = new FakeProbe();
        public FakeClock Clock = new FakeClock();
        public FakeTransport Transport = new FakeTransport();
        public FakeSource Source = new FakeSource();
        public List<string> Log = new List<string>();
        public CurrentTelemetryRouter Router;
        public IPEndPoint Legacy = new IPEndPoint(IPAddress.Loopback, 50001);
        public Rig()
        {
            CurrentModeLatch latch = new CurrentModeLatch(Probe, Clock.Now, CurrentModeLatch.DefaultHoldOffMs, delegate(string s) { Log.Add(s); });
            Router = new CurrentTelemetryRouter(Pid, Transport, Legacy, Source, latch, Clock.Now, delegate(string s) { Log.Add(s); });
        }
    }

    static byte[] Token(byte seed) { byte[] t = new byte[16]; for (int i = 0; i < 16; i++) t[i] = (byte)(seed + i); return t; }
    static TelemetryEndpoint Ep(uint port, uint gen, byte seed, uint caps, string inst)
    {
        return new TelemetryEndpoint((uint)Pid, inst, 777U, port, gen, Token(seed), 5U, caps);
    }
    static TelemetryEndpoint Ep(uint port, uint gen, byte seed) { return Ep(port, gen, seed, TelemetryCapabilities.EnvelopeV1 | TelemetryCapabilities.LegacyTextPayload, Inst); }
    static byte[] U8(string s) { return Encoding.UTF8.GetBytes(s); }
    static bool Eq(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }

    static List<string> failures;
    static int checks;
    static void Check(string id, bool ok) { checks++; if (!ok) failures.Add(id); }

    public static string[] Run(string goldenFolder)
    {
        failures = new List<string>();
        checks = 0;
        Modes();
        ManagedSend();
        FailClosed();
        Capabilities();
        Rediscovery();
        Diagnostics();
        Payloads();
        JumpComplete();
        Lifecycle();
        Parity();
        RealReader();
        Log();
        if (!String.IsNullOrEmpty(goldenFolder)) WriteGolden(goldenFolder);
        failures.Insert(0, "CHECKS=" + checks);
        return failures.ToArray();
    }

    // ---- DEC-1: mode latch ---------------------------------------------------------------------------------------------------------------
    static void Modes()
    {
        Rig r = new Rig();
        r.Source.Endpoint = Ep(40001, 1, 1);                                  // a perfectly valid Directory exists - it must NOT decide the mode
        CurrentTelemetryRouter.SendBatch b = r.Router.Begin();
        Check("M01 hold-off: nothing sent, mode undetermined", b.Mode == CurrentSenderMode.Undetermined && !b.Send(1U, U8("SCENARIO_ID:1")) && r.Transport.Data.Count == 0);
        r.Clock.Ms = 1999; b = r.Router.Begin();
        Check("M02 still hold-off at 1999 ms", b.Mode == CurrentSenderMode.Undetermined && !b.Send(1U, U8("SCENARIO_ID:1")));
        r.Clock.Ms = 2000; b = r.Router.Begin();
        bool sent = b.Send(1U, U8("SCENARIO_ID:1,SPEED:0"));
        Check("M03 normal after the hold-off without Enabled/Ready: plain text to the legacy destination", b.Mode == CurrentSenderMode.Normal && sent && r.Transport.Data.Count == 1
            && Eq(r.Transport.Data[0], U8("SCENARIO_ID:1,SPEED:0")) && r.Transport.To[0].Port == 50001);
        Check("M04 the Directory is never consulted in normal mode (not a mode source)", r.Source.Calls == 0);
        r.Probe.Ready = true; r.Clock.Ms = 3500; b = r.Router.Begin();
        Check("M05 a late Ready upgrades normal to managed", b.Mode == CurrentSenderMode.Managed);
        r.Probe.Ready = false; r.Probe.Enabled = false; r.Clock.Ms = 60000; b = r.Router.Begin();
        Check("M06 managed is latched: Enabled/Ready gone does not return to normal", b.Mode == CurrentSenderMode.Managed && r.Router.Mode == CurrentSenderMode.Managed);

        Rig e = new Rig(); e.Probe.Enabled = true; e.Source.Endpoint = Ep(40002, 2, 2);
        CurrentTelemetryRouter.SendBatch be = e.Router.Begin();
        Check("M07 Enabled alone (before Ready) is managed immediately", be.Mode == CurrentSenderMode.Managed && be.Send(1U, U8("SCENARIO_ID:2")));
        Rig y = new Rig(); y.Probe.Ready = true; y.Source.Endpoint = Ep(40003, 3, 3);
        Check("M08 Ready alone is managed", y.Router.Begin().Mode == CurrentSenderMode.Managed);
        Check("M09 managed mode never uses the legacy destination", e.Transport.To.Count == 1 && e.Transport.To[0].Port == 40002 && e.Transport.To[0].Address.Equals(IPAddress.Loopback));

        Rig t = new Rig(); t.Probe.Enabled = true; t.Clock.Ms = 10;
        t.Router.Begin(); t.Probe.Ready = true; t.Clock.Ms = 400; t.Router.Begin();
        Check("M10 the first sightings of Enabled and Ready are logged with offsets (L-0 evidence)", t.Log.Exists(delegate(string s) { return s.StartsWith("event=enabled-seen"); }) && t.Log.Exists(delegate(string s) { return s.StartsWith("event=ready-seen"); }));
    }

    // ---- DPC-T-002 / DPC-T-003: dynamic destination, envelope content, payload bytes ----------------------------------------------------------
    static void ManagedSend()
    {
        Rig r = new Rig(); r.Probe.Enabled = true; r.Source.Endpoint = Ep(40010, 9, 7);
        CurrentTelemetryRouter.SendBatch b = r.Router.Begin();
        string sta = "STALIST:東京=1=0=0=0=0=15000=0=0";
        string meta = "META:タイトル:路線:車両:作者:コメント";
        string tel = "SCENARIO_ID:5,SPEED:12.5,TIME:1000,LOCATION:30";
        string hb = "STATUS:LOADED:RUNNING";
        Check("S01 four sends accepted", b.Send(DataPlaneMessageTypes.StationList, U8(sta)) && b.Send(DataPlaneMessageTypes.Metadata, U8(meta)) && b.Send(DataPlaneMessageTypes.Telemetry, U8(tel)) && b.Send(DataPlaneMessageTypes.Heartbeat, U8(hb)));
        string[] payloads = new string[] { sta, meta, tel, hb };
        uint[] types = new uint[] { 3U, 4U, 1U, 2U };
        bool allOk = r.Transport.Data.Count == 4;
        for (int i = 0; allOk && i < 4; i++)
        {
            Envelope env = DataPlaneProtocol.DecodeEnvelope(r.Transport.Data[i]);
            allOk = env.MessageType == types[i] && env.BvePid == (uint)Pid && env.SenderPid == (uint)Pid && env.Generation == 9U && env.AppInstance == Inst
                && Eq(env.Token, Token(7)) && Eq(env.RequestId, new byte[16]) && Eq(env.Payload, U8(payloads[i])) && r.Transport.To[i].Port == 40010;
        }
        Check("S02 type, BvePid, SenderPid=BvePid, generation, instance, token, zero RequestId, byte-identical payload, dynamic port", allOk);
        Check("S03 no datagram was sent anywhere but the Directory port", r.Transport.To.TrueForAll(delegate(IPEndPoint ep) { return ep.Port == 40010; }));
        Check("S04 counters", r.Router.WrappedSent == 4 && r.Router.PlainSent == 0);
    }

    // ---- DPT-T-001..005 / DEC-1: fail closed, never a fixed-port fallback -------------------------------------------------------------------
    static void FailClosed()
    {
        string[] reasons = new string[] { "app-directory-missing", "app-directory-torn", "app-directory-invalid", "app-directory-not-ready", "telemetry-directory-missing",
            "telemetry-directory-torn", "telemetry-directory-invalid", "telemetry-not-ready", "bve-pid-mismatch", "app-instance-mismatch", "app-pid-mismatch" };
        foreach (string reason in reasons)
        {
            Rig r = new Rig(); r.Probe.Ready = true; r.Source.Reason = reason;
            CurrentTelemetryRouter.SendBatch b = r.Router.Begin();
            bool sent = b.Send(1U, U8("SCENARIO_ID:1")) | b.Send(2U, U8("STATUS:LOADED:RUNNING"));
            Check("F01 " + reason + ": nothing sent, no fallback", !sent && r.Transport.Data.Count == 0 && r.Router.FailClosed == 2 && r.Router.ReasonCount(reason) == 2);
        }
        Rig d = new Rig(); d.Probe.Enabled = true; d.Source.Endpoint = Ep(40020, 1, 1);
        Check("F02 connected", d.Router.Begin().Send(1U, U8("SCENARIO_ID:1")));
        d.Source.Endpoint = null; d.Source.Reason = "telemetry-not-ready";                // WITHDRAWING / CLOSED / not READY after a connection
        d.Clock.Ms += 1;
        int before = d.Transport.Data.Count;
        bool after = d.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Check("F03 withdrawal stops sending at once (no blind reuse of the last endpoint)", !after && d.Transport.Data.Count == before);
        Check("F04 the disconnect is logged once with its reason", d.Log.FindAll(delegate(string s) { return s.StartsWith("event=disconnected reason=telemetry-not-ready"); }).Count == 1);
        d.Clock.Ms += 10; d.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Check("F05 resolution retries are bounded while disconnected (no storm)", d.Source.Calls <= 3);
        d.Clock.Ms += 200; d.Source.Endpoint = Ep(40021, 2, 2);
        Check("F06 reconnect to the new endpoint after the retry delay", d.Router.Begin().Send(1U, U8("SCENARIO_ID:2")) && d.Transport.To[d.Transport.To.Count - 1].Port == 40021);
    }

    // ---- DEC-3: capabilities ------------------------------------------------------------------------------------------------------------------
    static void Capabilities()
    {
        Rig r = new Rig(); r.Probe.Ready = true;
        r.Source.Endpoint = Ep(40030, 1, 1, 0U, Inst);
        Check("C01 capabilities 0 (ENVELOPE_V1 missing): fail closed, capability-missing", !r.Router.Begin().Send(1U, U8("SCENARIO_ID:1")) && r.Router.ReasonCount("capability-missing") == 1 && r.Transport.Data.Count == 0);
        r = new Rig(); r.Probe.Ready = true;
        r.Source.Endpoint = Ep(40031, 1, 1, TelemetryCapabilities.LegacyTextPayload, Inst);
        Check("C02 LEGACY_TEXT_PAYLOAD without ENVELOPE_V1 is not connectable", !r.Router.Begin().Send(1U, U8("SCENARIO_ID:1")));
        r = new Rig(); r.Probe.Ready = true;
        r.Source.Endpoint = Ep(40032, 1, 1, TelemetryCapabilities.EnvelopeV1 | TelemetryCapabilities.LegacyTextPayload, Inst);
        Check("C03 the published value ENVELOPE_V1|LEGACY_TEXT_PAYLOAD (0x3, composed from the constants) connects", r.Router.Begin().Send(1U, U8("SCENARIO_ID:1")));
        byte[] ok = DataPlaneProtocol.EncodeTelemetryDirectory((uint)Pid, 2U, 3U, Inst, 777U, 40033U, 1U, Token(1), 5U, TelemetryCapabilities.EnvelopeV1 | TelemetryCapabilities.LegacyTextPayload);
        Check("C04 a 128-byte READY snapshot carrying the composed capabilities decodes", DataPlaneProtocol.DecodeTelemetryDirectory(ok).Capabilities == 3U);
        bool rejected = false;
        try { DataPlaneProtocol.DecodeTelemetryDirectory(DataPlaneProtocol.EncodeTelemetryDirectory((uint)Pid, 2U, 3U, Inst, 777U, 40033U, 1U, Token(1), 5U, 8U)); }
        catch (ArgumentException) { rejected = true; }
        Check("C05 an unsupported capability bit (0x8) is rejected by the directory decoder", rejected);
    }

    // ---- DPT-T-006/007/010: replacement and send errors --------------------------------------------------------------------------------------
    static void Rediscovery()
    {
        Rig r = new Rig(); r.Probe.Enabled = true; r.Source.Endpoint = Ep(40040, 1, 1);
        r.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        r.Source.Endpoint = Ep(40041, 1, 9, TelemetryCapabilities.EnvelopeV1, "fedcba0987abcdeffedcba0987abcdef"); // another instance, port and token
        r.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Envelope last = DataPlaneProtocol.DecodeEnvelope(r.Transport.Data[1]);
        Check("R01 instance replacement: the next packet carries only the new identity and goes to the new port", r.Transport.To[1].Port == 40041 && last.AppInstance == "fedcba0987abcdeffedcba0987abcdef" && Eq(last.Token, Token(9)));
        Check("R02 the replacement is logged as endpoint-changed", r.Log.Exists(delegate(string s) { return s.StartsWith("event=endpoint-changed"); }));
        r.Source.Endpoint = Ep(40041, 2, 5, TelemetryCapabilities.EnvelopeV1, "fedcba0987abcdeffedcba0987abcdef");  // same instance, new generation and token, same port
        r.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Envelope re = DataPlaneProtocol.DecodeEnvelope(r.Transport.Data[2]);
        Check("R03 endpoint recreation (new generation/token, same port): only the new generation/token is used", re.Generation == 2U && Eq(re.Token, Token(5)));

        Rig f = new Rig(); f.Probe.Enabled = true; f.Source.Endpoint = Ep(40042, 1, 1); f.Transport.Throw = true;
        bool threw = false; bool sent = true;
        try { sent = f.Router.Begin().Send(1U, U8("SCENARIO_ID:1")); } catch { threw = true; }
        Check("R04 a managed send failure never throws and reports not-sent", !threw && !sent && f.Router.SendFailures == 1);
        f.Router.Begin().Send(1U, U8("SCENARIO_ID:1")); f.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Check("R05 repeated send failures log once (no per-Tick log)", f.Log.FindAll(delegate(string s) { return s.StartsWith("event=send-failed"); }).Count == 1);
        f.Transport.Throw = false;
        Check("R06 recovery after the failure", f.Router.Begin().Send(1U, U8("SCENARIO_ID:1")));
    }

    // ---- read-only diagnostics used by the live acceptance (first tick, first datagram of each kind) -------------------------------------------
    static void Diagnostics()
    {
        Rig m = new Rig(); m.Probe.Enabled = true; m.Source.Endpoint = Ep(40095, 4, 4);
        m.Router.NoteTick(); m.Router.NoteTick();
        CurrentTelemetryRouter.SendBatch b = m.Router.Begin();
        b.Send(1U, U8("SCENARIO_ID:1")); b.Send(2U, U8("STATUS:LOADED:RUNNING"));
        Check("Z01 first-tick is written once", m.Log.FindAll(delegate(string s) { return s == "event=first-tick"; }).Count == 1);
        Check("Z02 first-send-managed is written once, after endpoint-adopted, with port and generation", m.Log.FindAll(delegate(string s) { return s.StartsWith("event=first-send-managed type=1 port=40095 gen=4"); }).Count == 1
            && m.Log.FindIndex(delegate(string s) { return s.StartsWith("event=endpoint-adopted"); }) < m.Log.FindIndex(delegate(string s) { return s.StartsWith("event=first-send-managed"); }));
        Check("Z03 a managed sender never writes first-send-plain", !m.Log.Exists(delegate(string s) { return s.StartsWith("event=first-send-plain"); }));
        Rig n = new Rig(); n.Clock.Ms = 0; n.Router.Begin(); n.Clock.Ms = 2100;
        CurrentTelemetryRouter.SendBatch nb = n.Router.Begin(); nb.Send(1U, U8("SCENARIO_ID:1")); nb.Send(1U, U8("SCENARIO_ID:1"));
        Check("Z04 normal mode: first-send-plain once, after mode=normal, never first-send-managed", n.Log.FindAll(delegate(string s) { return s.StartsWith("event=first-send-plain"); }).Count == 1
            && n.Log.FindIndex(delegate(string s) { return s.StartsWith("event=mode=normal"); }) < n.Log.FindIndex(delegate(string s) { return s.StartsWith("event=first-send-plain"); })
            && !n.Log.Exists(delegate(string s) { return s.StartsWith("event=first-send-managed"); }));
        Rig h = new Rig(); h.Source.Endpoint = Ep(40096, 1, 1); h.Router.Begin().Send(1U, U8("SCENARIO_ID:1")); h.Clock.Ms = 1500; h.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        m.Router.Close();
        Check("Z06 the summary counts wrapped datagrams per message type (heartbeat visible as type 2)", m.Log.Exists(delegate(string s) { return s.StartsWith("event=summary") && s.Contains(" types=1:1,2:1 "); }));
        Check("Z05 during the hold-off nothing is logged as sent and nothing leaves", h.Transport.Data.Count == 0 && !h.Log.Exists(delegate(string s) { return s.StartsWith("event=first-send"); }));
    }

    // ---- payload size and encoding --------------------------------------------------------------------------------------------------------------
    static void Payloads()
    {
        Rig r = new Rig(); r.Probe.Enabled = true; r.Source.Endpoint = Ep(40050, 1, 1);
        byte[] max = new byte[65411]; for (int i = 0; i < max.Length; i++) max[i] = (byte)'a';
        byte[] big = new byte[65412]; for (int i = 0; i < big.Length; i++) big[i] = (byte)'a';
        Check("P01 65,507-byte datagram (96 + 65,411) is sent", r.Router.Begin().Send(1U, max) && r.Transport.Data[0].Length == 65507);
        bool threw = false; bool sent = true;
        try { sent = r.Router.Begin().Send(1U, big); } catch { threw = true; }
        Check("P02 a 65,508-byte datagram is refused before sending, without an exception", !threw && !sent && r.Router.PayloadTooLarge == 1 && r.Transport.Data.Count == 1);
        Check("P03 the oversize event is logged once", r.Log.FindAll(delegate(string s) { return s.StartsWith("event=payload-too-large"); }).Count == 1);
    }

    // ---- DEC-2 -----------------------------------------------------------------------------------------------------------------------------------
    static void JumpComplete()
    {
        byte[] jc = U8("JUMP_COMPLETE:STA:3:100.5:43000000:2");
        Rig n = new Rig(); n.Clock.Ms = 0; n.Router.Begin(); n.Clock.Ms = 2100;
        Check("J01 normal mode: JUMP_COMPLETE goes out plain exactly as before", n.Router.Begin().SendJumpComplete(jc) && Eq(n.Transport.Data[0], jc) && n.Transport.To[0].Port == 50001);
        Rig m = new Rig(); m.Probe.Ready = true; m.Source.Endpoint = Ep(40060, 1, 1);
        Check("J02 managed mode: JUMP_COMPLETE is consumed without any datagram (known constraint until PID-D6)", m.Router.Begin().SendJumpComplete(jc) && m.Transport.Data.Count == 0 && m.Router.JumpCompleteExcluded == 1);
        Check("J03 the exclusion is logged once", m.Router.Begin().SendJumpComplete(jc) && m.Log.FindAll(delegate(string s) { return s.StartsWith("event=jump-complete-excluded"); }).Count == 1);
        Rig u = new Rig();
        Check("J04 hold-off: the notice stays pending", !u.Router.Begin().SendJumpComplete(jc) && u.Transport.Data.Count == 0);
    }

    // ---- DPC-T-004 and normal-mode compatibility -----------------------------------------------------------------------------------------------
    static void Lifecycle()
    {
        Rig r = new Rig(); r.Probe.Enabled = true; r.Source.Endpoint = Ep(40070, 1, 1);
        r.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        r.Router.Close(); r.Router.Close();
        Check("L01 Close is idempotent and writes one summary", r.Log.FindAll(delegate(string s) { return s.StartsWith("event=summary"); }).Count == 1);
        Check("L02 nothing escapes after Close", !r.Router.Begin().Send(1U, U8("SCENARIO_ID:1")) && r.Transport.Data.Count == 1);

        Rig n = new Rig(); n.Clock.Ms = 0; n.Router.Begin(); n.Clock.Ms = 2100; n.Transport.Throw = true;
        bool threw = false;
        try { n.Router.Begin().Send(1U, U8("SCENARIO_ID:1")); } catch { threw = true; }
        Check("L03 normal mode keeps the pre-migration behaviour: a transport exception propagates to the caller's own catch", threw);

        Rig c = new Rig(); c.Probe.Enabled = true; c.Source.Endpoint = Ep(40071, 1, 1);
        int errors = 0; int ok = 0;
        Thread[] ts = new Thread[4];
        for (int k = 0; k < ts.Length; k++)
        {
            ts[k] = new Thread(delegate() { for (int i = 0; i < 500; i++) { try { if (c.Router.Begin().Send(2U, U8("STATUS:LOADED:RUNNING"))) Interlocked.Increment(ref ok); } catch { Interlocked.Increment(ref errors); } } });
            ts[k].Start();
        }
        for (int k = 0; k < ts.Length; k++) ts[k].Join();
        Check("L04 concurrent Tick/heartbeat use of one router: no exception", errors == 0 && ok > 0);
    }

    // ---- parity of constants ------------------------------------------------------------------------------------------------------------------------
    static void Parity()
    {
        Check("Y01 capability constants are the contract values", TelemetryCapabilities.EnvelopeV1 == 1U && TelemetryCapabilities.LegacyTextPayload == 2U && TelemetryCapabilities.JumpCompleteV1 == 4U);
        Check("Y02 the known mask equals the shared decoder's mask", TelemetryCapabilities.Known == DataPlaneProtocol.TelemetryKnownCapabilities);
        Check("Y03 control plane names", CallerControlPlaneProbe.EnabledName(1234) == "Local\\TSScoringPlugin.v1.1234.Enabled" && CallerControlPlaneProbe.ReadyName(1234) == "Local\\TSScoringPlugin.v1.1234.Ready");
        Check("Y04 message type values", DataPlaneMessageTypes.Telemetry == 1U && DataPlaneMessageTypes.Heartbeat == 2U && DataPlaneMessageTypes.StationList == 3U && DataPlaneMessageTypes.Metadata == 4U);
    }

    // ---- the shared reader against real named mappings (it had no test before) -------------------------------------------------------------------
    static byte[] AppBlock(int pid, uint seq, uint flags, string inst, uint appPid)
    {
        byte[] b = new byte[80];
        W32(b, 0, 0x44415354U); W32(b, 4, 1U); W32(b, 8, 80U); W32(b, 12, (uint)pid); W32(b, 16, seq); W32(b, 20, flags);
        if (inst != null) Array.Copy(Encoding.ASCII.GetBytes(inst), 0, b, 24, 32);
        W32(b, 56, appPid); W32(b, 60, 1U); W32(b, 76, seq);
        return b;
    }
    static void W32(byte[] b, int o, uint v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }

    static MemoryMappedFile Map(string name, byte[] data)
    {
        MemoryMappedFile m = MemoryMappedFile.CreateNew(name, data.Length, MemoryMappedFileAccess.ReadWrite);
        using (MemoryMappedViewAccessor v = m.CreateViewAccessor(0, data.Length, MemoryMappedFileAccess.ReadWrite)) { v.WriteArray(0, data, 0, data.Length); }
        return m;
    }

    static string Resolve(int pid, out TelemetryEndpoint ep)
    {
        string reason;
        TelemetryDirectoryReader.TryResolve(pid, out ep, out reason);
        return reason;
    }

    static void RealReader()
    {
        int pid = 2000000000 + (Process_Id() % 100000);
        TelemetryEndpoint ep;
        Check("D01 no AppDirectory", Resolve(pid, out ep) == TelemetryDirectoryReader.AppDirectoryMissing && ep == null);
        string appName = "Local\\TSScoringPlugin.v1." + pid + ".AppDirectory";
        string telName = DataPlaneProtocol.TelemetryName((uint)pid, Inst);
        uint ready = 1U | 2U | 4U;
        List<IDisposable> keep = new List<IDisposable>();
        try
        {
            // InstancePublished|ProcessStarted without ReadyAccepted = a normal wait state (DPT-T-002)
            using (Map(appName, AppBlock(pid, 2U, 1U | 2U, Inst, 777U))) { Check("D02 AppDirectory not ReadyAccepted", Resolve(pid, out ep) == TelemetryDirectoryReader.AppDirectoryNotReady); }
            using (Map(appName, AppBlock(pid, 2U, ready, Inst, 777U)))
            {
                Check("D03 Telemetry directory absent", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryDirectoryMissing);
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 2U, 1U, Inst, 777U, 40080U, 3U, Token(1), 1U, 3U)))
                    Check("D04 PUBLISHED without READY", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryNotReady);
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, Inst, 777U, 40080U, 3U, Token(1), 2U, 3U)))
                {
                    string reason = Resolve(pid, out ep);
                    Check("D05 READY: endpoint resolved with port, generation, token, capabilities", reason == TelemetryDirectoryReader.Ok && ep != null && ep.Port == 40080U && ep.Generation == 3U && Eq(ep.Token, Token(1)) && ep.Capabilities == 3U);
                }
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 6U, 7U, Inst, 777U, 40080U, 3U, Token(1), 3U, 3U)))
                    Check("D06 WITHDRAWING is not usable", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryNotReady);
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 8U, 8U, String.Empty, 0U, 0U, 0U, new byte[16], 4U, 0U)))
                    Check("D07 CLOSED is not usable", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryNotReady);
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, Inst, 778U, 40080U, 3U, Token(1), 2U, 3U)))
                    Check("D08 AppPid mismatch", Resolve(pid, out ep) == TelemetryDirectoryReader.AppPidMismatch);
                using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid + 1U, 4U, 3U, Inst, 777U, 40080U, 3U, Token(1), 2U, 3U)))
                    Check("D09 BvePid mismatch", Resolve(pid, out ep) == TelemetryDirectoryReader.BvePidMismatch);
                byte[] torn = DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, Inst, 777U, 40080U, 3U, Token(1), 2U, 3U);
                W32(torn, 16, 5U);                                              // odd HEAD = a writer in progress
                using (Map(telName, torn)) Check("D10 torn snapshot (odd HEAD)", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryDirectoryTorn);
                byte[] caps = DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, Inst, 777U, 40080U, 3U, Token(1), 2U, 3U);
                W32(caps, 96, 0x80U);                                           // unknown capability bit
                using (Map(telName, caps)) Check("D11 unsupported capabilities are an invalid directory", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryDirectoryInvalid);
            }
            string other = "fedcba0987abcdeffedcba0987abcdef";
            using (Map(appName, AppBlock(pid, 2U, ready, other, 777U)))
            using (Map(telName, DataPlaneProtocol.EncodeTelemetryDirectory((uint)pid, 4U, 3U, Inst, 777U, 40080U, 3U, Token(1), 2U, 3U)))
                Check("D12 a Telemetry directory of another instance is never adopted (the name is built from the AppDirectory instance)", Resolve(pid, out ep) == TelemetryDirectoryReader.TelemetryDirectoryMissing);
            using (Map(appName, AppBlock(pid, 2U, 1U | 2U | 4U | 16U, Inst, 777U)))
                Check("D13 AppDirectory CLOSED", Resolve(pid, out ep) == TelemetryDirectoryReader.AppDirectoryNotReady);
        }
        finally { foreach (IDisposable d in keep) d.Dispose(); }
    }

    static int Process_Id() { return System.Diagnostics.Process.GetCurrentProcess().Id; }

    // ---- diagnostics file -------------------------------------------------------------------------------------------------------------------------
    static void Log()
    {
        string dir = Path.Combine(Path.GetTempPath(), "tsd3-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            string other = Path.Combine(dir, "TSScoring-CurrentTelemetry-P2.log");
            File.WriteAllText(other, "KEEP");
            CurrentTelemetryLogFile a = new CurrentTelemetryLogFile(1, dir);
            a.Write("one"); a.Write("two");
            string text = File.ReadAllText(Path.Combine(dir, "TSScoring-CurrentTelemetry-P1.log"));
            Check("G01 one file per BVE PID, own prologue lines, the other process' file untouched", text.Contains("bve=1 one") && text.Contains("bve=1 two") && File.ReadAllText(other) == "KEEP");
            for (int i = 0; i < CurrentTelemetryLogFile.MaxLines + 50; i++) a.Write("x");
            Check("G02 the file is bounded", File.ReadAllLines(Path.Combine(dir, "TSScoring-CurrentTelemetry-P1.log")).Length <= CurrentTelemetryLogFile.MaxLines);
            new CurrentTelemetryLogFile(1, dir).Write("again");
            Check("G03 a new process truncates only its own file", File.ReadAllText(Path.Combine(dir, "TSScoring-CurrentTelemetry-P1.log")).Contains("bve=1 again") && !File.ReadAllText(Path.Combine(dir, "TSScoring-CurrentTelemetry-P1.log")).Contains("one"));
            CurrentTelemetryLogFile broken = new CurrentTelemetryLogFile(3, Path.Combine(dir, "does\\not\\exist"));
            bool threw = false; try { broken.Write("x"); } catch { threw = true; }
            Check("G04 a log failure never throws", !threw);
        }
        finally { try { Directory.Delete(dir, true); } catch { } }
    }

    // ---- C# -> Python interop datagrams (validated by tests\test_current_dataplane_d3_interop.py) -------------------------------------------------
    static void WriteGolden(string folder)
    {
        Directory.CreateDirectory(folder);
        Rig r = new Rig(); r.Probe.Enabled = true; r.Source.Endpoint = Ep(40090, 77, 33);
        CurrentTelemetryRouter.SendBatch b = r.Router.Begin();
        b.Send(DataPlaneMessageTypes.StationList, U8("STALIST:東京=1=0=0=0=0=15000=0=0"));
        b.Send(DataPlaneMessageTypes.Metadata, U8("META:タイトル:路線:車両:作者:コメント"));
        b.Send(DataPlaneMessageTypes.Telemetry, U8("SCENARIO_ID:5,SPEED:12.5,TIME:1000,LOCATION:30"));
        b.Send(DataPlaneMessageTypes.Heartbeat, U8("STATUS:LOADED:PAUSED"));
        string[] names = new string[] { "stalist", "meta", "telemetry", "heartbeat" };
        for (int i = 0; i < names.Length; i++) File.WriteAllBytes(Path.Combine(folder, "current_" + names[i] + ".bin"), r.Transport.Data[i]);
        File.WriteAllText(Path.Combine(folder, "current_identity.txt"), Pid + "\n" + Inst + "\n77\n" + BitConverter.ToString(Token(33)).Replace("-", "").ToLowerInvariant() + "\n");
    }
}
