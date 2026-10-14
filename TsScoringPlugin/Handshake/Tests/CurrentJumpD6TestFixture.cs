using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Net;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// PID-D6 offline tests of the Current jump endpoint (CurrentJumpEndpoint.cs) and of the RequestId echo of the JUMP_COMPLETE (CurrentDataPlane.cs),
// together with the shared DataPlaneProtocol / TelemetryDirectoryReader. No BVE, no BveEX. Compiled by Test-CurrentJumpD6.ps1 (C# 5 syntax).
// The only operating system objects are synthetic named mappings under an unused high PID (the production endpoint opens its own loopback socket).
public static class CurrentJumpD6TestFixture
{
    const string Inst = "0123456789abcdef0123456789abcdef";
    const string OtherInst = "00112233445566778899aabbccddeeff";
    const int Pid = 4242;
    const uint AppPid = 777U;
    const uint JumpGen = 91U;

    sealed class FakeSource : IEndpointSource
    {
        public TelemetryEndpoint Endpoint;
        public string Reason = "app-directory-missing";
        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            endpoint = Endpoint;
            reason = Endpoint != null ? "ok" : Reason;
            return Endpoint != null;
        }
    }

    sealed class FakeProbe : ICallerProbe
    {
        public bool Enabled = false, Ready = false;
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
        public int ThrowTimes;
        public void Send(byte[] data, IPEndPoint destination)
        {
            if (ThrowTimes > 0) { ThrowTimes--; throw new IOException("transport"); }
            Data.Add((byte[])data.Clone());
            To.Add(destination);
        }
    }

    static byte[] Token(byte seed) { byte[] t = new byte[16]; for (int i = 0; i < 16; i++) t[i] = (byte)(seed + i); return t; }
    static byte[] U8(string s) { return Encoding.UTF8.GetBytes(s); }
    static bool Eq(byte[] a, byte[] b)
    {
        if (a == null || b == null || a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }
    static byte[] Req(byte seed) { byte[] t = new byte[16]; for (int i = 0; i < 16; i++) t[i] = (byte)(seed ^ (i * 7 + 1)); if (Eq(t, new byte[16])) t[0] = 1; return t; }
    static string Hex(byte[] b) { StringBuilder sb = new StringBuilder(); for (int i = 0; i < b.Length; i++) sb.Append(b[i].ToString("x2")); return sb.ToString(); }
    static byte[] FromHex(string s) { byte[] b = new byte[s.Length / 2]; for (int i = 0; i < b.Length; i++) b[i] = Convert.ToByte(s.Substring(i * 2, 2), 16); return b; }

    static TelemetryEndpoint Owner(uint caps)
    {
        return new TelemetryEndpoint((uint)Pid, Inst, AppPid, 40001U, 5U, Token(50), 3U, caps);
    }

    static List<string> failures;
    static int checks;
    static void Check(string id, bool ok) { checks++; if (!ok) failures.Add(id); }

    static byte[] Command(uint type, string text, byte[] requestId, uint bvePid, uint sender, uint gen, string inst, byte[] token)
    {
        return DataPlaneProtocol.EncodeEnvelope(type, bvePid, sender, gen, inst, token, requestId, U8(text));
    }

    static JumpCommandValidator NewValidator(FakeSource source, List<string> log)
    {
        return new JumpCommandValidator(Pid, JumpGen, Token(9), source, delegate(string s) { log.Add(s); });
    }

    public static string[] Run(string interopFolder)
    {
        failures = new List<string>();
        checks = 0;
        Validator();
        Publisher();
        Echo();
        Parity();
        if (!String.IsNullOrEmpty(interopFolder)) Interop(interopFolder);
        failures.Insert(0, "CHECKS=" + checks);
        return failures.ToArray();
    }

    // ---- contract 10 / 13.3: validation of one command datagram ----------------------------------------------------------------------------
    static void Validator()
    {
        FakeSource src = new FakeSource(); src.Endpoint = Owner(7U);
        List<string> log = new List<string>();
        JumpCommandValidator v = NewValidator(src, log);
        string reason;
        byte[] id1 = Req(1);
        CurrentJumpCommand c = v.Validate(Command(0x100U, "JUMP_STA_TIME:3:43000000", id1, (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason);
        Check("V01 a valid station command is accepted with its text and RequestId", c != null && reason == null && c.Text == "JUMP_STA_TIME:3:43000000" && Eq(c.RequestId, id1) && c.MessageType == 0x100U);
        byte[] id2 = Req(2);
        c = v.Validate(Command(0x101U, "JUMP_LOC_TIME:1000.5:36000000", id2, (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason);
        Check("V02 a valid location command (invariant decimal point) is accepted", c != null && c.Text == "JUMP_LOC_TIME:1000.5:36000000" && Eq(c.RequestId, id2));
        Check("V03 the first accept is logged once", log.FindAll(delegate(string s) { return s.StartsWith("event=jump-command-first-accept"); }).Count == 1);

        c = v.Validate(Command(0x100U, "JUMP_STA_TIME:3:43000000", id1, (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason);
        Check("V04 a duplicate RequestId is rejected and not executed", c == null && reason == "duplicate-request-id");
        long acceptedBefore = v.Accepted;

        Expect(v, "V05 bad magic", Mutate(Command(0x100U, "JUMP_STA_TIME:1:2", Req(3), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), 0, 0), "envelope-magic");
        Expect(v, "V06 short datagram", new byte[10], "envelope-size");
        Expect(v, "V07 other BVE process", Command(0x100U, "JUMP_STA_TIME:1:2", Req(4), (uint)Pid + 1U, AppPid, JumpGen, Inst, Token(9)), "bve-pid-mismatch");
        Expect(v, "V08 other app instance", Command(0x100U, "JUMP_STA_TIME:1:2", Req(5), (uint)Pid, AppPid, JumpGen, OtherInst, Token(9)), "app-instance-mismatch");
        Expect(v, "V09 other endpoint generation (stale endpoint)", Command(0x100U, "JUMP_STA_TIME:1:2", Req(6), (uint)Pid, AppPid, JumpGen + 1U, Inst, Token(9)), "generation-mismatch");
        Expect(v, "V10 other endpoint token", Command(0x100U, "JUMP_STA_TIME:1:2", Req(7), (uint)Pid, AppPid, JumpGen, Inst, Token(10)), "token-mismatch");
        Expect(v, "V11 JUMP_COMPLETE is not a command", Command(5U, "JUMP_COMPLETE:STA:1:0:0:0", Req(8), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "message-type-not-allowed");
        Expect(v, "V12 a telemetry type is not a command", DataPlaneProtocol.EncodeEnvelope(1U, (uint)Pid, (uint)Pid, JumpGen, Inst, Token(9), new byte[16], U8("SCENARIO_ID:1")), "message-type-not-allowed");
        Expect(v, "V13 sender is not the managed application", Command(0x100U, "JUMP_STA_TIME:1:2", Req(9), (uint)Pid, AppPid + 1U, JumpGen, Inst, Token(9)), "sender-pid-mismatch");
        Expect(v, "V14 zero RequestId", Command(0x100U, "JUMP_STA_TIME:1:2", new byte[16], (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "envelope-request-id");
        Expect(v, "V15 station command with a non-integer index", Command(0x100U, "JUMP_STA_TIME:x:2", Req(10), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "payload-grammar");
        Expect(v, "V16 location text under the station type", Command(0x100U, "JUMP_LOC_TIME:1.5:2", Req(11), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "payload-grammar");
        Expect(v, "V17 station text under the location type", Command(0x101U, "JUMP_STA_TIME:1:2", Req(12), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "payload-grammar");
        Expect(v, "V18 missing field", Command(0x100U, "JUMP_STA_TIME:1", Req(13), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "payload-grammar");
        Expect(v, "V19 NaN location", Command(0x101U, "JUMP_LOC_TIME:NaN:5", Req(14), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "payload-grammar");
        Check("V20 nothing was accepted by any rejected datagram", v.Accepted == acceptedBefore);
        Check("V21 every reason is logged once, never per datagram", log.FindAll(delegate(string s) { return s.StartsWith("event=jump-command-reject reason=payload-grammar"); }).Count == 1 && v.ReasonCount("payload-grammar") == 5);

        src.Endpoint = null;
        Expect(v, "V22 no usable AppDirectory identity", Command(0x100U, "JUMP_STA_TIME:1:2", Req(20), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), "owner-app-directory-missing");
        src.Endpoint = Owner(7U);
        c = v.Validate(Command(0x100U, "JUMP_STA_TIME:1:2", Req(20), (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason);
        Check("V23 a command rejected for the owner is not remembered as a duplicate", c != null);

        JumpCommandValidator bounded = NewValidator(src, new List<string>());
        byte[] first = null;
        bool allOk = true;
        for (int i = 0; i < JumpCommandValidator.RecentCapacity + 1; i++)
        {
            byte[] id = new byte[16]; id[0] = (byte)(i + 1); id[1] = 0x55;
            if (i == 0) first = id;
            allOk &= bounded.Validate(Command(0x100U, "JUMP_STA_TIME:1:2", id, (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason) != null;
        }
        Check("V24 the recent-request cache is bounded (the oldest id is forgotten after capacity + 1)", allOk
            && bounded.Validate(Command(0x100U, "JUMP_STA_TIME:1:2", first, (uint)Pid, AppPid, JumpGen, Inst, Token(9)), out reason) != null);
        Check("V25 Validate never throws on null", v.Validate(null, out reason) == null && reason != null);
    }

    static byte[] Mutate(byte[] data, int offset, byte value) { byte[] c = (byte[])data.Clone(); c[offset] = value; return c; }

    static void Expect(JumpCommandValidator v, string id, byte[] datagram, string expected)
    {
        string reason;
        CurrentJumpCommand c = v.Validate(datagram, out reason);
        Check(id + " -> " + expected + " (got " + reason + ")", c == null && reason == expected);
    }

    // ---- contract 9 / 15.3: the published directory and the real socket -------------------------------------------------------------------
    static void Publisher()
    {
        int pid = 1900000000 + (Environment.TickCount & 0xFFFF);
        string name = DataPlaneProtocol.JumpName((uint)pid);
        FakeSource src = new FakeSource(); src.Endpoint = new TelemetryEndpoint((uint)pid, Inst, AppPid, 40001U, 5U, Token(50), 3U, 7U);
        List<string> log = new List<string>();
        CurrentJumpEndpoint ep = CurrentJumpEndpoint.Create(pid, src, delegate(string s) { log.Add(s); });
        try
        {
            JumpDirectory d = ReadDirectory(name);
            Check("P01 the directory is PUBLISHED | READY", d != null && d.State == (DataPlaneProtocol.Published | DataPlaneProtocol.Ready));
            Check("P02 identity: BVE PID, publisher PID = BVE PID, loopback port, nonzero generation and token", d != null && d.BvePid == (uint)pid && d.PublisherPid == (uint)pid
                && d.Port == ep.Port && d.Port >= 1U && d.Port <= 65535U && d.Generation == ep.Generation && d.Generation != 0U && Eq(d.Token, ep.TokenCopy) && !Eq(d.Token, new byte[16]));
            Check("P03 capabilities: STATION_TIME | LOCATION_TIME | REQUEST_ID", d != null && d.Capabilities == 7U);
            // (the datagram path over a real socket - valid envelope accepted, wrong token and plain text dropped - is proved by tests/test_current_jump_endpoint_live_d6.py;
            //  the test sources of the Handshake folder hold no socket type by contract, see tests/test_hud_data_path_e4.py)
            List<CurrentJumpCommand> got = new List<CurrentJumpCommand>();
            ep.Drain(got);
            Check("P05 nothing has been received yet: an empty drain yields no command", got.Count == 0 && ep.Validator.Accepted == 0 && ep.Validator.Rejected == 0);

            bool secondFailed = false;
            try { CurrentJumpEndpoint.Create(pid, src, null).Dispose(); } catch { secondFailed = true; }
            Check("P06 a second endpoint for the same BVE process cannot be published", secondFailed);
            Check("P07 the first endpoint still works after the failed second one", ReadDirectory(name) != null && ReadDirectory(name).Port == ep.Port);

            uint port = ep.Port;
            MemoryMappedFile heldMapping = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);        // the managed application keeps its handle open
            MemoryMappedViewAccessor heldView = heldMapping.CreateViewAccessor(0, 128, MemoryMappedFileAccess.Read);
            ep.Dispose();
            byte[] closedBytes = new byte[128];
            heldView.ReadArray(0, closedBytes, 0, 128);
            heldView.Dispose(); heldMapping.Dispose();
            JumpDirectory closed = DataPlaneProtocol.DecodeJumpDirectory(closedBytes);
            Check("P08 Dispose leaves a CLOSED snapshot with every endpoint field zero", closed != null && closed.State == DataPlaneProtocol.Closed && closed.PublisherPid == 0U && closed.Port == 0U
                && closed.Generation == 0U && Eq(closed.Token, new byte[16]) && closed.Capabilities == 0U);
            ep.Dispose();
            List<CurrentJumpCommand> after = new List<CurrentJumpCommand>();
            ep.Drain(after);
            Check("P09 Dispose is idempotent and a disposed endpoint drains nothing", after.Count == 0);
            Check("P10 the published port was a loopback port that is gone from the directory after Dispose", port >= 1U && port <= 65535U && closed != null && closed.Port == 0U);
            Check("P11 the lifecycle is logged (published, summary)", log.Exists(delegate(string s) { return s.StartsWith("event=jump-endpoint-published"); }) && log.Exists(delegate(string s) { return s.StartsWith("event=jump-endpoint-summary"); }));
        }
        finally
        {
            ep.Dispose();
        }
    }

    static JumpDirectory ReadDirectoryAny(string name)
    {
        MemoryMappedFile mapping = null; MemoryMappedViewAccessor view = null;
        try
        {
            mapping = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);
            view = mapping.CreateViewAccessor(0, 128, MemoryMappedFileAccess.Read);
            byte[] b = new byte[128];
            view.ReadArray(0, b, 0, 128);
            return DataPlaneProtocol.DecodeJumpDirectory(b);
        }
        catch { return null; }
        finally
        {
            if (view != null) view.Dispose();
            if (mapping != null) mapping.Dispose();
        }
    }

    static JumpDirectory ReadDirectory(string name)
    {
        JumpDirectory d = ReadDirectoryAny(name);
        return d;
    }

    // ---- the RequestId echo of the JUMP_COMPLETE ------------------------------------------------------------------------------------------
    sealed class EchoRig
    {
        public FakeProbe Probe = new FakeProbe();
        public FakeClock Clock = new FakeClock();
        public FakeTransport Transport = new FakeTransport();
        public FakeSource Source = new FakeSource();
        public List<string> Log = new List<string>();
        public CurrentTelemetryRouter Router;
        public EchoRig()
        {
            CurrentModeLatch latch = new CurrentModeLatch(Probe, Clock.Now, CurrentModeLatch.DefaultHoldOffMs, delegate(string s) { Log.Add(s); });
            Router = new CurrentTelemetryRouter(Pid, Transport, new IPEndPoint(IPAddress.Loopback, 50001), Source, latch, Clock.Now, delegate(string s) { Log.Add(s); });
        }
    }

    static void Echo()
    {
        byte[] payload = U8("JUMP_COMPLETE:STA:3:100.5:43000000:2");
        EchoRig r = new EchoRig(); r.Probe.Ready = true; r.Source.Endpoint = Owner(7U);
        byte[] id = Req(60);
        bool sent = r.Router.Begin().SendJumpComplete(payload, id);
        Envelope e = r.Transport.Data.Count == 1 ? DataPlaneProtocol.DecodeEnvelope(r.Transport.Data[0]) : null;
        Check("E01 managed: a type 5 envelope is sent and the pending notice is consumed", sent && e != null && e.MessageType == 5U);
        Check("E02 the RequestId is echoed byte for byte", e != null && Eq(e.RequestId, id));
        Check("E03 addressed to the Telemetry endpoint (port, generation, token, instance) and never to a fixed port", e != null && r.Transport.To[0].Port == 40001
            && r.Transport.To[0].Address.Equals(IPAddress.Loopback) && e.Generation == 5U && Eq(e.Token, Token(50)) && e.AppInstance == Inst);
        Check("E04 SenderPid = BvePid and the payload is the unchanged legacy text", e != null && e.BvePid == (uint)Pid && e.SenderPid == (uint)Pid && Eq(e.Payload, payload));
        Check("E05 counted and logged once", r.Router.JumpCompleteSent == 1 && r.Router.JumpCompleteExcluded == 0 && r.Log.FindAll(delegate(string s) { return s.StartsWith("event=jump-complete-sent id=" + Hex(id).Substring(0, 8)); }).Count == 1);
        r.Router.Begin().SendJumpComplete(payload, Req(61));
        Check("E06 the log line is written for the first notice only, the second goes out as well", r.Transport.Data.Count == 2 && r.Router.JumpCompleteSent == 2
            && r.Log.FindAll(delegate(string s) { return s.StartsWith("event=jump-complete-sent"); }).Count == 1);

        bool allEcho = true;
        for (int i = 0; i < 20; i++)
        {
            EchoRig q = new EchoRig(); q.Probe.Ready = true; q.Source.Endpoint = Owner(7U);
            byte[] rid = new byte[16]; for (int k = 0; k < 16; k++) rid[k] = (byte)(i * 13 + k * 5 + 1);
            q.Router.Begin().SendJumpComplete(payload, rid);
            allEcho &= q.Transport.Data.Count == 1 && Eq(DataPlaneProtocol.DecodeEnvelope(q.Transport.Data[0]).RequestId, rid);
        }
        Check("E07 20 different RequestIds are all echoed exactly", allEcho);

        EchoRig noCap = new EchoRig(); noCap.Probe.Ready = true; noCap.Source.Endpoint = Owner(3U);
        bool consumed = noCap.Router.Begin().SendJumpComplete(payload, Req(62));
        Check("E08 without the JUMP_COMPLETE_V1 capability nothing is sent and the notice is consumed (logged once)", consumed && noCap.Transport.Data.Count == 0 && noCap.Router.JumpCompleteExcluded == 1
            && noCap.Log.FindAll(delegate(string s) { return s.StartsWith("event=jump-complete-excluded reason=capability-missing"); }).Count == 1);

        EchoRig down = new EchoRig(); down.Probe.Ready = true;
        bool pending = !down.Router.Begin().SendJumpComplete(payload, Req(63));
        Check("E09 an unresolved Telemetry endpoint keeps the notice pending and sends nothing", pending && down.Transport.Data.Count == 0 && down.Router.FailClosed == 1);
        down.Clock.Ms += CurrentTelemetryRouter.FailureRetryMs + 1; down.Source.Endpoint = Owner(7U);
        Check("E10 it is delivered when the endpoint is back", down.Router.Begin().SendJumpComplete(payload, Req(63)) && down.Transport.Data.Count == 1);

        EchoRig hold = new EchoRig();
        Check("E11 during the hold-off the notice stays pending", !hold.Router.Begin().SendJumpComplete(payload, Req(64)) && hold.Transport.Data.Count == 0);

        EchoRig normal = new EchoRig(); normal.Source.Endpoint = Owner(7U);
        normal.Router.Begin(); normal.Clock.Ms = 2000;                       // the hold-off starts with the first evaluation
        bool nc = normal.Router.Begin().SendJumpComplete(payload, Req(65));
        Check("E12 normal mode never wraps: a RequestId notice is consumed without a datagram", nc && normal.Transport.Data.Count == 0 && normal.Router.Mode == CurrentSenderMode.Normal);
        EchoRig plain = new EchoRig();
        plain.Router.Begin(); plain.Clock.Ms = 2000;
        Check("E13 normal mode plain command (no RequestId): plain text to the legacy destination, as before", plain.Router.Begin().SendJumpComplete(payload, null) && Eq(plain.Transport.Data[0], payload) && plain.Transport.To[0].Port == 50001);
        EchoRig managedPlain = new EchoRig(); managedPlain.Probe.Ready = true; managedPlain.Source.Endpoint = Owner(7U);
        Check("E14 managed mode without a RequestId is still consumed without a datagram", managedPlain.Router.Begin().SendJumpComplete(payload, null) && managedPlain.Transport.Data.Count == 0 && managedPlain.Router.JumpCompleteExcluded == 1);

        EchoRig fail = new EchoRig(); fail.Probe.Ready = true; fail.Source.Endpoint = Owner(7U); fail.Transport.ThrowTimes = 1;
        bool notYet = !fail.Router.Begin().SendJumpComplete(payload, Req(66));
        bool then = fail.Router.Begin().SendJumpComplete(payload, Req(66));
        Check("E15 a transport failure keeps the notice pending; the retry sends it with the same RequestId", notYet && then && fail.Transport.Data.Count == 1
            && Eq(DataPlaneProtocol.DecodeEnvelope(fail.Transport.Data[0]).RequestId, Req(66)));

        EchoRig tele = new EchoRig(); tele.Probe.Ready = true; tele.Source.Endpoint = Owner(7U);
        tele.Router.Begin().Send(1U, U8("SCENARIO_ID:1"));
        Check("E16 the Telemetry type keeps an all-zero RequestId (unchanged)", Eq(DataPlaneProtocol.DecodeEnvelope(tele.Transport.Data[0]).RequestId, new byte[16]));
    }

    // ---- constants shared with the Python side ----------------------------------------------------------------------------------------------
    static void Parity()
    {
        Check("Y01 jump capability constants are the contract values", JumpCapabilities.StationTime == 1U && JumpCapabilities.LocationTime == 2U && JumpCapabilities.RequestId == 4U && JumpCapabilities.Published == 7U);
        Check("Y02 message types are the contract values", DataPlaneMessageTypes.JumpComplete == 5U && DataPlaneMessageTypes.JumpStationTime == 0x100U && DataPlaneMessageTypes.JumpLocationTime == 0x101U);
        Check("Y03 the published capabilities are accepted by the shared codec", DataPlaneProtocol.JumpKnownCapabilities == JumpCapabilities.Published);
    }

    // ---- a REAL endpoint for a REAL Python client (named mapping + loopback UDP), served until stop.flag exists or the time is up -----------
    public static void Serve(string folder, int pid, string instance, uint appPid, int seconds)
    {
        FakeSource src = new FakeSource();
        src.Endpoint = new TelemetryEndpoint((uint)pid, instance, appPid, 40001U, 5U, Token(50), 3U, 7U);
        CurrentJumpEndpoint ep = CurrentJumpEndpoint.Create(pid, src, null);
        try
        {
            File.WriteAllText(Path.Combine(folder, "endpoint.txt"), "port=" + ep.Port + "\r\n", new UTF8Encoding(false));
            DateTime until = DateTime.UtcNow.AddSeconds(seconds);
            string served = Path.Combine(folder, "served.txt");
            while (DateTime.UtcNow < until && !File.Exists(Path.Combine(folder, "stop.flag")))
            {
                List<CurrentJumpCommand> got = new List<CurrentJumpCommand>();
                ep.Drain(got);
                foreach (CurrentJumpCommand c in got) File.AppendAllText(served, c.Text + "|" + Hex(c.RequestId) + "\r\n", new UTF8Encoding(false));
                Thread.Sleep(10);
            }
        }
        finally
        {
            ep.Dispose();
            File.WriteAllText(Path.Combine(folder, "done.txt"), "closed\r\n", new UTF8Encoding(false));
        }
        File.WriteAllText(Path.Combine(folder, "served-summary.txt"), "accepted=" + ep.Validator.Accepted + " rejected=" + ep.Validator.Rejected + "\r\n", new UTF8Encoding(false));
    }

    // ---- C# <-> Python round trip (Python writes commands.txt / identity.txt; this writes results.txt) --------------------------------------
    static void Interop(string folder)
    {
        Dictionary<string, string> id = new Dictionary<string, string>();
        foreach (string line in File.ReadAllLines(Path.Combine(folder, "identity.txt")))
        {
            int p = line.IndexOf('=');
            if (p > 0) id[line.Substring(0, p)] = line.Substring(p + 1);
        }
        uint bvePid = UInt32.Parse(id["bve_pid"], CultureInfo.InvariantCulture);
        string instance = id["instance"];
        uint appPid = UInt32.Parse(id["app_pid"], CultureInfo.InvariantCulture);
        uint jumpGen = UInt32.Parse(id["jump_generation"], CultureInfo.InvariantCulture);
        byte[] jumpToken = FromHex(id["jump_token"]);
        uint telPort = UInt32.Parse(id["telemetry_port"], CultureInfo.InvariantCulture);
        uint telGen = UInt32.Parse(id["telemetry_generation"], CultureInfo.InvariantCulture);
        byte[] telToken = FromHex(id["telemetry_token"]);

        FakeSource src = new FakeSource();
        src.Endpoint = new TelemetryEndpoint(bvePid, instance, appPid, telPort, telGen, telToken, 1U, 7U);
        JumpCommandValidator v = new JumpCommandValidator((int)bvePid, jumpGen, jumpToken, src, null);
        List<string> results = new List<string>();
        foreach (string line in File.ReadAllLines(Path.Combine(folder, "commands.txt")))
        {
            string[] f = line.Split('|');
            if (f.Length != 3) continue;
            string reason;
            CurrentJumpCommand c = v.Validate(FromHex(f[1]), out reason);
            if (c == null) { results.Add(f[0] + "|reject|" + reason); continue; }
            EchoRig r = new EchoRig(); r.Probe.Ready = true; r.Source.Endpoint = src.Endpoint;
            string complete = "JUMP_COMPLETE:" + (c.MessageType == 0x100U ? "STA" : "LOC") + ":3:1000.0:36000000:1";
            bool sent = r.Router.Begin().SendJumpComplete(U8(complete), c.RequestId);
            bool delivered = sent && r.Transport.Data.Count == 1;
            results.Add(f[0] + "|accept|" + c.Text + "|" + (delivered ? Hex(r.Transport.Data[0]) : "none") + "|" + (delivered ? r.Transport.To[0].Port : 0));
        }
        File.WriteAllLines(Path.Combine(folder, "results.txt"), results.ToArray(), new UTF8Encoding(false));
    }
}
