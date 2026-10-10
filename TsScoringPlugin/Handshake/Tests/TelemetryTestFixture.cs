// PHASE L3 test fixture (C# 5 on purpose: Windows PowerShell's Add-Type compiles it). Compiled into an assembly NAMED TsScoringLegacyTelemetryTests, which the
// telemetry DLL lets see its internals (InternalsVisibleTo). Nothing here touches BVE, AtsEX, the network or the disk: a fake of the Legacy API, a sink that
// collects datagrams, and a harness that drives the host independent core exactly the way the host adapter does.
using System;
using System.Collections.Generic;
using System.Reflection;
using TSScoringPlugin.Telemetry;

namespace TsScoringLegacyTelemetryTests
{
    public class FakeStation
    {
        public string Name = "S";
        public double Location = 0.0;
        public bool Pass = false;
        public bool IsTerminal = false;
        public int DoorSide = 1;
        public int ArrivalMs = -1;
        public int DepartureMs = -1;
        public int DefaultMs = -1;
        public int StoppageMs = 15000;
        public double MarginMin = -5.0;
        public double MarginMax = 5.0;
    }

    public class FakeApi : ILegacyApi
    {
        public bool Created = true;
        public object Scenario = new object();    // the STABLE source object of the scenario instance (ClassWrapperBase.Src): the identity
        public bool FreshWrapperEachCall = false; // the real host: every access to IBveHacker.Scenario returns a NEW wrapper object of the same source
        public object LastWrapper = null;
        public int WrappersIssued = 0;
        internal Func<LegacyScenarioIdentity> IdentityFactory = null;   // when set, replaces the fake identity (the probe plugs the REAL BveTypes wrappers in)
        public bool SourceUnreadable = false;     // the wrapper exists but its original object cannot be read
        public int TimeMs = 36000000;
        public double Location = 1000.0;
        public double SpeedMps = 10.0;
        public bool DoorsClosed = true;
        public double GradientRatio = 0.0125;     // what the Legacy API returns: a RATIO (0.0125 = 12.5 per mille); the session converts it
        public double SignalMps = 25.0;
        public double ForwardSignalMps = double.PositiveInfinity;
        public bool NextSectionFound = true;
        public double NextSectionLoc = 1500.0;
        public double GroundMps = double.PositiveInfinity;
        public int BrakeKind = 1;                 // 0 none, 1 Ecb, 2 Smee, 3 Cl
        public int BrakeNotches = 8;
        public bool Holding = false;
        public double[] Rates = new double[] { 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0 };
        public double MaxPa = 440000.0;
        public string[] Meta = new string[] { "Title", "Route", "Vehicle", "Author", "Comment" };
        public List<FakeStation> Stations = new List<FakeStation>();

        public HashSet<string> Fail = new HashSet<string>();      // names of Try methods that report "cannot read"
        public string ThrowIn = null;                              // a method that throws
        public Dictionary<string, int> Calls = new Dictionary<string, int>();

        private void Count(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            Calls[name] = n + 1;
        }

        private bool Blocked(string name)
        {
            Count(name);
            if (ThrowIn == name)
            {
                throw new InvalidOperationException("fake failure in " + name);
            }

            return Fail.Contains(name);
        }

        public int CallCount(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            return n;
        }

        bool ILegacyApi.IsScenarioCreated()
        {
            Count("IsScenarioCreated");
            if (ThrowIn == "IsScenarioCreated") { throw new InvalidOperationException("fake"); }
            return Created;
        }

        bool ILegacyApi.TryScenarioIdentity(out LegacyScenarioIdentity identity)
        {
            identity = null;
            if (Blocked("TryScenarioIdentity")) { return false; }
            if (IdentityFactory != null)
            {
                identity = IdentityFactory();
                return identity != null;
            }

            if (Scenario == null || SourceUnreadable) { return false; }
            LegacyScenarioIdentity id = new LegacyScenarioIdentity();
            id.Source = Scenario;
            id.Kind = LegacyScenarioIdentity.KindSourceObject;
            if (FreshWrapperEachCall)
            {
                id.Wrapper = new object();           // a different object on every call, exactly like Scenario.FromSource
                WrappersIssued++;
            }
            else
            {
                id.Wrapper = Scenario;
            }

            LastWrapper = id.Wrapper;
            identity = id;
            return true;
        }

        bool ILegacyApi.TryTimeMs(out int timeMs) { timeMs = 0; if (Blocked("TryTimeMs")) { return false; } timeMs = TimeMs; return true; }
        bool ILegacyApi.TryLocation(out double meters) { meters = 0; if (Blocked("TryLocation")) { return false; } meters = Location; return true; }
        bool ILegacyApi.TrySpeedMps(out double v) { v = 0; if (Blocked("TrySpeedMps")) { return false; } v = SpeedMps; return true; }
        bool ILegacyApi.TryDoorsClosed(out bool allClosed) { allClosed = false; if (Blocked("TryDoorsClosed")) { return false; } allClosed = DoorsClosed; return true; }
        bool ILegacyApi.TryGradientRatio(double location, out double ratio) { ratio = 0; if (Blocked("TryGradientRatio")) { return false; } ratio = GradientRatio; return true; }
        bool ILegacyApi.TryStationCount(out int count) { count = 0; if (Blocked("TryStationCount")) { return false; } count = Stations.Count; return true; }

        bool ILegacyApi.TryStations(out IList<LegacyStationRaw> stations)
        {
            stations = null;
            if (Blocked("TryStations")) { return false; }
            List<LegacyStationRaw> list = new List<LegacyStationRaw>();
            foreach (FakeStation f in Stations)
            {
                LegacyStationRaw r = new LegacyStationRaw();
                r.Name = f.Name;
                r.Location = f.Location;
                r.Pass = f.Pass;
                r.IsTerminal = f.IsTerminal;
                r.DoorSide = f.DoorSide;
                r.ArrivalMs = f.ArrivalMs;
                r.DepartureMs = f.DepartureMs;
                r.DefaultMs = f.DefaultMs;
                r.StoppageMs = f.StoppageMs;
                r.MarginMin = f.MarginMin;
                r.MarginMax = f.MarginMax;
                list.Add(r);
            }

            stations = list;
            return true;
        }

        bool ILegacyApi.TrySignalLimitMps(out double v) { v = 0; if (Blocked("TrySignalLimitMps")) { return false; } v = SignalMps; return true; }
        bool ILegacyApi.TryForwardSignalLimitMps(out double v) { v = 0; if (Blocked("TryForwardSignalLimitMps")) { return false; } v = ForwardSignalMps; return true; }

        bool ILegacyApi.TryNextSectionLocation(double location, out bool found, out double sectionLocation)
        {
            found = false;
            sectionLocation = 0;
            if (Blocked("TryNextSectionLocation")) { return false; }
            found = NextSectionFound;
            sectionLocation = NextSectionLoc;
            return true;
        }

        bool ILegacyApi.TryGroundLimitMps(out double v) { v = 0; if (Blocked("TryGroundLimitMps")) { return false; } v = GroundMps; return true; }

        bool ILegacyApi.TryBrakeKind(out LegacyBrakeKind kind)
        {
            kind = LegacyBrakeKind.None;
            if (Blocked("TryBrakeKind")) { return false; }
            kind = (LegacyBrakeKind)BrakeKind;
            return kind != LegacyBrakeKind.None;
        }

        bool ILegacyApi.TryBrakeNotches(out int count, out bool holding)
        {
            count = 0;
            holding = false;
            if (Blocked("TryBrakeNotches")) { return false; }
            count = BrakeNotches;
            holding = Holding;
            return true;
        }

        bool ILegacyApi.TryPressureRates(out double[] rates, out double maxPa)
        {
            rates = null;
            maxPa = 0;
            if (Blocked("TryPressureRates")) { return false; }
            rates = Rates;
            maxPa = MaxPa;
            return true;
        }

        bool ILegacyApi.TryScenarioMeta(out LegacyScenarioMeta meta)
        {
            meta = null;
            if (Blocked("TryScenarioMeta")) { return false; }
            if (Meta == null) { return false; }
            LegacyScenarioMeta m = new LegacyScenarioMeta();
            m.Title = Meta[0];
            m.RouteTitle = Meta[1];
            m.VehicleTitle = Meta[2];
            m.Author = Meta[3];
            m.Comment = Meta[4];
            meta = m;
            return true;
        }
    }

    public class CollectDiag : ITelemetryDiag
    {
        public List<string> Events = new List<string>();
        public bool Throw = false;

        public void Event(string name, string detail)
        {
            if (Throw) { throw new InvalidOperationException("diag failure"); }
            Events.Add(string.IsNullOrEmpty(detail) ? name : name + " " + detail);
        }

        public List<string> Named(string name)
        {
            List<string> l = new List<string>();
            foreach (string e in Events) { if (e == name || e.StartsWith(name + " ")) { l.Add(e); } }
            return l;
        }
    }

    public class CollectSink : ITelemetrySink
    {
        public List<string> Sent = new List<string>();
        public bool Closed = false;
        public int SendsAfterClose = 0;

        public void Send(string text)
        {
            if (Closed) { SendsAfterClose++; }
            Sent.Add(text);
        }

        public void Close() { Closed = true; }

        public void Clear() { Sent.Clear(); }

        public string LastLine()
        {
            for (int i = Sent.Count - 1; i >= 0; i--)
            {
                if (Sent[i].StartsWith("SCENARIO_ID:")) { return Sent[i]; }
            }

            return null;
        }

        public List<string> Lines()
        {
            List<string> l = new List<string>();
            foreach (string s in Sent) { if (s.StartsWith("SCENARIO_ID:")) { l.Add(s); } }
            return l;
        }

        public List<string> Starting(string prefix)
        {
            List<string> l = new List<string>();
            foreach (string s in Sent) { if (s.StartsWith(prefix)) { l.Add(s); } }
            return l;
        }
    }

    // ---- PHASE LI0 (input observation) fakes -------------------------------------------------------------------------------------------------
    // Cab classes with the names of the host's wrappers (the classification is by class name, so the fake types prove it without the host).
    public class CabBase { }
    public class OneLeverCab : CabBase { }
    public class TwoLeverCab : CabBase { }
    public class MyTwoLeverCab : TwoLeverCab { }
    public class UnrelatedCab : CabBase { }

    /// <summary>A fake of the input read surface (ILegacyInputApi). Records the thread of every call.</summary>
    public class FakeInputApi : ILegacyInputApi
    {
        public bool NativeReach = true;

        // handles
        public bool HandlesFail = false;
        public string HandlesReason = "cab-null";
        public bool HandlesThrow = false;
        public string CabName = "OneLeverCab";
        public int HandleTypeValue = 1;           // 0 unknown, 1 one lever, 2 two lever
        public int BrakeKindValue = 1;            // 0 none, 1 Ecb, 2 Smee, 3 Cl
        public int? Rev = 1;
        public int? Pow = 0;
        public int? Brk = 0;
        public int? PowN = 5;
        public int? BrkN = 8;
        public int? EbN = 9;
        public bool? Hold = false;
        public int? HoldN = 0;                 // NotchInfo.HoldingSpeedNotchCount (LI2)
        public int? B67 = -1;

        // native
        public bool SpecFail = false;
        public string SpecReason = "native-null";
        public bool SpecThrow = false;
        public int? SpecBrake = 8;
        public int? SpecPower = 5;
        public int? SpecB67 = -1;
        public bool NativeFail = false;
        public string NativeReason = "native-null";
        public bool NativeThrow = false;
        public double NativeBc = 0.0;
        public double NativeBp = 490.0;

        // store
        public bool StoreFail = false;
        public string StoreReason = "store-null";
        public bool StoreThrow = false;
        public double[] StoreBc = new double[] { 0.0 };
        public double[] StoreBp = new double[] { 490.0 };

        public Dictionary<string, int> Calls = new Dictionary<string, int>();
        public HashSet<int> Threads = new HashSet<int>();

        private void Note(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            Calls[name] = n + 1;
            lock (Threads) { Threads.Add(System.Threading.Thread.CurrentThread.ManagedThreadId); }
        }

        public int CallCount(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            return n;
        }

        public int TotalCalls()
        {
            int t = 0;
            foreach (int v in Calls.Values) { t += v; }
            return t;
        }

        bool ILegacyInputApi.NativeReachable { get { Note("NativeReachable"); return NativeReach; } }

        bool ILegacyInputApi.TryHandles(out LegacyHandleSnapshot snapshot, out string reason)
        {
            Note("TryHandles");
            snapshot = null;
            reason = HandlesReason;
            if (HandlesThrow) { throw new InvalidOperationException("fake failure in handles"); }
            if (HandlesFail) { return false; }
            LegacyHandleSnapshot s = new LegacyHandleSnapshot();
            s.CabTypeName = CabName;
            s.HandleType = (LegacyHandleType)HandleTypeValue;
            s.BrakeKind = (LegacyBrakeKind)BrakeKindValue;
            s.Reverser = Rev;
            s.Power = Pow;
            s.Brake = Brk;
            s.PowerNotchCount = PowN;
            s.BrakeNotchCount = BrkN;
            s.EmergencyBrakeNotch = EbN;
            s.HasHoldingSpeedBrake = Hold;
            s.HoldingSpeedNotchCount = HoldN;
            s.B67Notch = B67;
            snapshot = s;
            return true;
        }

        bool ILegacyInputApi.TryNativeSpec(out LegacySpecSnapshot spec, out string reason)
        {
            Note("TryNativeSpec");
            spec = null;
            reason = SpecReason;
            if (SpecThrow) { throw new InvalidOperationException("fake failure in spec"); }
            if (SpecFail || !NativeReach) { if (!NativeReach) { reason = "native-null"; } return false; }
            LegacySpecSnapshot s = new LegacySpecSnapshot();
            s.BrakeNotches = SpecBrake;
            s.PowerNotches = SpecPower;
            s.B67Notch = SpecB67;
            spec = s;
            return true;
        }

        bool ILegacyInputApi.TryNativePressure(out LegacyNativePressure pressure, out string reason)
        {
            Note("TryNativePressure");
            pressure = null;
            reason = NativeReason;
            if (NativeThrow) { throw new InvalidOperationException("fake failure in native pressure"); }
            if (NativeFail || !NativeReach) { if (!NativeReach) { reason = "native-null"; } return false; }
            LegacyNativePressure p = new LegacyNativePressure();
            p.Bc = NativeBc;
            p.Bp = NativeBp;
            pressure = p;
            return true;
        }

        bool ILegacyInputApi.TryStorePressure(out LegacyStorePressure pressure, out string reason)
        {
            Note("TryStorePressure");
            pressure = null;
            reason = StoreReason;
            if (StoreThrow) { throw new InvalidOperationException("fake failure in store"); }
            if (StoreFail) { return false; }
            LegacyStorePressure p = new LegacyStorePressure();
            p.Bc = StoreBc;
            p.Bp = StoreBp;
            if (p.Bc == null && p.Bp == null) { reason = "array-null"; return false; }
            pressure = p;
            return true;
        }
    }

    /// <summary>The pure parts of the probe and its limits, for the tests.</summary>
    public static class InputInfo
    {
        public static int Classify(Type t) { return (int)LegacyInputProbe.ClassifyCabType(t); }
        public static string Combo(int handleType, int brakeKind) { return LegacyInputProbe.ComboText((LegacyHandleType)handleType, (LegacyBrakeKind)brakeKind); }
        public static string Head(double[] a) { return LegacyInputProbe.HeadText(a); }
        public static bool Moved(double current, double reference) { return LegacyInputProbe.Moved(current, reference); }
        public static string SafeName(Type t) { return LegacyInputProbe.SafeTypeName(t); }
        public static int MaxLines { get { return LegacyInputProbe.MaxLinesPerGeneration; } }
        public static int RetryEvery { get { return LegacyInputProbe.RetryEveryTicks; } }
        public static int CapHandleChange { get { return LegacyInputProbe.CapHandleChange; } }
        public static int CapPressureChange { get { return LegacyInputProbe.CapPressureChange; } }
        public static int HeadCount { get { return LegacyInputProbe.HeadCount; } }
    }

    // ---- PHASE LI1 (handle group and pressures of the line) -------------------------------------------------------------------------------------
    /// <summary>The pure handle contract. Returns { "ok", REV, POW, BRK, HTYPE, ALLTXT } (the values after the key) or { "drop", reason }.</summary>
    public static class HandleInfo
    {
        public static string[] Build(int handleType, int brakeKind, int? rev, int? pow, int? brk, int? powN, int? brkN, int? ebN, bool? hold, int? holdN)
        {
            LegacyHandleSnapshot s = new LegacyHandleSnapshot();
            s.CabTypeName = "x";
            s.HandleType = (LegacyHandleType)handleType;
            s.BrakeKind = (LegacyBrakeKind)brakeKind;
            s.Reverser = rev;
            s.Power = pow;
            s.Brake = brk;
            s.PowerNotchCount = powN;
            s.BrakeNotchCount = brkN;
            s.EmergencyBrakeNotch = ebN;
            s.HasHoldingSpeedBrake = hold;
            s.HoldingSpeedNotchCount = holdN;
            LegacyHandleLine line;
            string reason;
            if (!LegacyHandleContract.TryBuild(s, out line, out reason))
            {
                return new string[] { "drop", reason };
            }

            string[] pairs = line.Pairs();
            string[] result = new string[6];
            result[0] = "ok";
            for (int i = 0; i < 5; i++) { result[i + 1] = pairs[i * 2 + 1]; }
            return result;
        }

        public static string[] Keys()
        {
            LegacyHandleLine line = new LegacyHandleLine();
            line.RevText = "a"; line.PowText = "a"; line.BrkText = "a"; line.AllRev = "a"; line.AllPow = "a"; line.AllBrk = "a";
            string[] pairs = line.Pairs();
            string[] keys = new string[5];
            for (int i = 0; i < 5; i++) { keys[i] = pairs[i * 2]; }
            return keys;
        }

        public static int MaxNotches { get { return LegacyHandleContract.MaxNotches; } }
    }

    /// <summary>The pure pressure contract: "ok:123.4" or "drop:reason:length".</summary>
    public static class PressureInfo
    {
        public static string Try(double[] array)
        {
            double v;
            string reason;
            int length;
            if (LegacyPressureContract.TryValue(array, out v, out reason, out length))
            {
                return "ok:" + LegacyPressureContract.Format(v);
            }

            return "drop:" + reason + ":" + length;
        }

        public static string Format(double v) { return LegacyPressureContract.Format(v); }
    }

    public static class InputTelemetryInfo
    {
        public static int MaxLines { get { return LegacyInputTelemetry.MaxLinesPerGeneration; } }
        public static string SafeWord(string text, string fallback) { return LegacyInputTelemetry.SafeWord(text, fallback); }
    }

    /// <summary>The REAL host adapter (AtsExLegacyApi) with nothing attached: it must answer with fixed reasons, never throw. Needs the host assemblies to load.</summary>
    public static class AdapterProbe
    {
        public static string[] Run()
        {
            Type adapterType = typeof(ILegacyInputApi).Assembly.GetType("TSScoringPlugin.Telemetry.AtsExLegacyApi", true);
            ILegacyInputApi input = (ILegacyInputApi)Activator.CreateInstance(adapterType, true);
            LegacyHandleSnapshot h; LegacySpecSnapshot s; LegacyNativePressure n; LegacyStorePressure p;
            string rh, rs, rn, rp;
            bool bh = input.TryHandles(out h, out rh);
            bool bs = input.TryNativeSpec(out s, out rs);
            bool bn = input.TryNativePressure(out n, out rn);
            bool bp = input.TryStorePressure(out p, out rp);
            return new string[] { input.NativeReachable.ToString(), bh + ":" + rh, bs + ":" + rs, bn + ":" + rn, bp + ":" + rp };
        }
    }

    /// <summary>Drives the core the way the host adapter does: events, Ticks, the heartbeat, Dispose. Time is a number the test moves.</summary>
    public class Harness
    {
        public FakeApi Api = new FakeApi();
        public CollectSink Sink = new CollectSink();
        public CollectDiag Diag = new CollectDiag();
        public FakeScoringApi Scoring = null;     // Phase SI-0: null = no scoring-integration observation wired
        public FakeInputApi Input = null;         // Phase LI0: null = no input observation wired (the L3 sessions of the earlier tests)
        public long Now = 1000;
        public long Seed = 5000000000L;
        private LegacyTelemetrySession session;

        public Harness()
        {
            session = Make(Diag);
        }

        /// <summary>withInput: the session is created with the input observation (a FakeInputApi in Input).</summary>
        public Harness(bool withInput)
        {
            if (withInput) { Input = new FakeInputApi(); }
            session = Make(Diag);
        }

        /// <summary>Phase LI1: withDiag=false builds the session with NO diagnostic (the observation is then not wired, the handle group and the pressures still are).</summary>
        public Harness(bool withInput, bool withDiag)
        {
            if (withInput) { Input = new FakeInputApi(); }
            session = Make(withDiag ? (ITelemetryDiag)Diag : null);
        }

        /// <summary>Phase SI-0: withScoring wires the scoring-integration observation (a FakeScoringApi in Scoring) next to the input surface.</summary>
        public Harness(bool withInput, bool withDiag, bool withScoring)
        {
            if (withInput) { Input = new FakeInputApi(); }
            if (withScoring) { Scoring = new FakeScoringApi(); }
            session = Make(withDiag ? (ITelemetryDiag)Diag : null);
        }

        private LegacyTelemetrySession Make(ITelemetryDiag d)
        {
            return new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, d, Input, Scoring);
        }

        /// <summary>Phase SI-0: the host adapter reports its set-up (the "init" word of the order).</summary>
        public void NoteInit(string detail) { session.NoteInit(detail); }

        /// <summary>Replaces the diagnostic with the REAL file diagnostic of the DLL, writing to a path the test owns.</summary>
        public void UseFileDiag(string path)
        {
            session = Make(new FileTelemetryDiag(path));
        }

        /// <summary>A new extension instance after the previous one was disposed (a new session over the same fake host, a fresh sink).</summary>
        public void Reinitialize()
        {
            Sink = new CollectSink();
            session = Make(Diag);
        }

        /// <summary>Calls ComposeHeartbeat from a real second thread (the timer thread of the host adapter) the given number of times, and waits for it.</summary>
        public int HeartbeatOnOtherThread(int times)
        {
            int threadId = 0;
            System.Threading.Thread t = new System.Threading.Thread(delegate ()
            {
                threadId = System.Threading.Thread.CurrentThread.ManagedThreadId;
                for (int i = 0; i < times; i++) { session.ComposeHeartbeat(); }
            });
            t.Start();
            t.Join();
            return threadId;
        }

        public void Tick() { Tick(16.0); }

        public void Tick(double elapsedMs)
        {
            session.OnTick(TimeSpan.FromMilliseconds(elapsedMs));
        }

        /// <summary>Advances the clock and the simulation time by the same amount, then ticks (a normal running simulation).</summary>
        public void Run(int ticks, int stepMs)
        {
            for (int i = 0; i < ticks; i++)
            {
                Now += stepMs;
                Api.TimeMs += stepMs;
                Tick((double)stepMs);
            }
        }

        public void Opened(bool reload) { session.OnScenarioOpened(reload); }
        public void Closed() { session.OnScenarioClosed(); }
        public void Created() { session.OnScenarioCreated(); }
        public void Dispose() { session.OnDispose(); }
        public string Heartbeat() { return session.ComposeHeartbeat(); }
        public bool Active { get { return session.ScenarioActive; } }
        public int ScenarioId { get { return session.ScenarioId; } }
        public int Epochs { get { return session.Epochs; } }
        public int LinesSent { get { return session.LinesSent; } }
        public int LinesSkipped { get { return session.LinesSkipped; } }
        public int Discontinuities { get { return session.Discontinuities; } }
        public bool IsDisposed { get { return session.IsDisposed; } }
    }

    /// <summary>The same drive as Harness, but the datagrams go out through the REAL UDP sink to 127.0.0.1:54321 (integration test with the real application).</summary>
    public class LiveHarness
    {
        public FakeApi Api = new FakeApi();
        internal UdpTelemetrySink Sink = new UdpTelemetrySink();
        public long Now = 1000;
        public long Seed = 7000000000L;
        private LegacyTelemetrySession session;

        public FakeInputApi Input = null;         // Phase LI1: null = the sender of Phase L3 (no handle group, no pressures)

        public LiveHarness()
        {
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; });
        }

        /// <summary>withInput: the input surface is wired (a FakeInputApi in Input); the handle group and the pressures go out through the real UDP sink.</summary>
        public LiveHarness(bool withInput)
        {
            if (withInput) { Input = new FakeInputApi(); }
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, null, Input);
        }

        public void Run(int ticks, int stepMs)
        {
            for (int i = 0; i < ticks; i++)
            {
                Now += stepMs;
                Api.TimeMs += stepMs;
                session.OnTick(TimeSpan.FromMilliseconds((double)stepMs));
            }
        }

        public void Opened(bool reload) { session.OnScenarioOpened(reload); }
        public void Closed() { session.OnScenarioClosed(); }
        public void Created() { session.OnScenarioCreated(); }
        public void Dispose() { session.OnDispose(); }
        public string Heartbeat() { return session.ComposeHeartbeat(); }
        public int ScenarioId { get { return session.ScenarioId; } }
        public int Epochs { get { return session.Epochs; } }
        public long Sent { get { return Sink.Sent; } }
        public long Failed { get { return Sink.Failed; } }
        public void SendRaw(string text) { Sink.Send(text); }
    }
    /// <summary>
    /// The REAL wrapper classes of the legacy host, reached by reflection (no compile-time reference: the fixture builds without the host installed, and
    /// Available is false there). Proves, without BVE running, what the identity fix rests on: two wrappers of one source are different objects, they hold the
    /// same original object, and the adapter's identity step returns that original object, not the wrapper.
    /// </summary>
    public static class IdentityProbe
    {
        private static readonly MethodInfo fromSource;
        private static readonly MethodInfo identityOf;

        static IdentityProbe()
        {
            try
            {
                Assembly hostTypes = Assembly.Load("BveTypes");
                Type wrapper = hostTypes.GetType("BveTypes.ClassWrappers.Scenario", true);
                fromSource = wrapper.GetMethod("FromSource", BindingFlags.Public | BindingFlags.Static);
                Type reader = typeof(LegacyScenarioIdentity).Assembly.GetType("TSScoringPlugin.Telemetry.LegacyScenarioIdentityReader", true);
                identityOf = reader.GetMethod("IdentityOf", BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static);
            }
            catch
            {
                fromSource = null;
                identityOf = null;
            }
        }

        public static bool Available { get { return fromSource != null && identityOf != null; } }

        public static object NewWrapper(object source) { return fromSource.Invoke(null, new object[] { source }); }

        public static bool WrapperEquals(object a, object b) { return a.Equals(b); }

        /// <summary>{ Source, Wrapper, Kind } of the adapter's identity, or null.</summary>
        public static object[] IdentityOf(object wrapper)
        {
            LegacyScenarioIdentity id = (LegacyScenarioIdentity)identityOf.Invoke(null, new object[] { wrapper });
            return id == null ? null : new object[] { id.Source, id.Wrapper, id.Kind };
        }

        /// <summary>Makes the fake host behave like the real one: every call builds a NEW real wrapper of api.Scenario and takes the adapter's identity of it.</summary>
        public static void UseRealWrappers(FakeApi api)
        {
            api.IdentityFactory = delegate { return (LegacyScenarioIdentity)identityOf.Invoke(null, new object[] { NewWrapper(api.Scenario) }); };
        }
    }
    public static class DiagInfo
    {
        public static string FileName { get { return FileTelemetryDiag.FileName; } }
        public static string DefaultPathText { get { return FileTelemetryDiag.DefaultPath(); } }
        public static string Version { get { return FileTelemetryDiag.Version; } }
        public static void Write(string path, string name, string detail) { new FileTelemetryDiag(path).Event(name, detail); }
    }
    public static class GradientUnit
    {
        /// <summary>The session's one conversion (ratio to per mille). Returns NaN when there is no valid value.</summary>
        public static double Convert(double ratio)
        {
            double permille;
            return LegacyTelemetrySession.GradientRatioToPermille(ratio, out permille) ? permille : double.NaN;
        }

        public static bool IsValid(double ratio)
        {
            double permille;
            return LegacyTelemetrySession.GradientRatioToPermille(ratio, out permille);
        }
    }

    // ---- PHASE SI-0 (scoring-integration observation) fakes -----------------------------------------------------------------------------------
    public class FakeLimit
    {
        public double Location;
        public double ValueMps;
        public bool IsNode = true;
        public string TypeName = "ValueNode_1";

        public FakeLimit(double location, double valueMps)
        {
            Location = location;
            ValueMps = valueMps;
        }
    }

    /// <summary>A fake of the scoring-integration read surface (ILegacyScoringApi). Records the thread of every call.</summary>
    public class FakeScoringApi : ILegacyScoringApi
    {
        public string Version = "1.0.50314.2";

        // O-A
        public bool BpFail = false;
        public string BpReason = "brakesystem-null";
        public bool BpThrow = false;
        public int KindValue = 2;                  // 0 none, 1 Ecb, 2 Smee, 3 Cl
        public double? ControllerPa = 490000.0;    // BpInitialPressure of the active controller (null = could not be read)
        public string ControllerReason = null;
        public bool SmeeProp = true;
        public double? SmeePa = 490000.0;
        public bool ClProp = false;
        public double? ClPa = null;

        // O-B
        public bool VehFail = false;
        public string VehReason = "dynamics-null";
        public bool VehThrow = false;
        public double? CarLen = 20.0;
        public double? First = 1.0;
        public double? Motor = 4.0;
        public double? Trailer = 3.0;

        // O-C
        public bool LimitsFail = false;
        public string LimitsReason = "limits-null";
        public bool LimitsThrow = false;
        public List<FakeLimit> Limits = new List<FakeLimit>();
        public int FailElementAt = -1;             // the element with this index cannot be read
        public int ThrowElementAt = -1;

        public Dictionary<string, int> Calls = new Dictionary<string, int>();
        public HashSet<int> Threads = new HashSet<int>();

        private void Note(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            Calls[name] = n + 1;
            lock (Threads) { Threads.Add(System.Threading.Thread.CurrentThread.ManagedThreadId); }
        }

        public int CallCount(string name)
        {
            int n;
            Calls.TryGetValue(name, out n);
            return n;
        }

        public int TotalCalls()
        {
            int t = 0;
            foreach (int v in Calls.Values) { t += v; }
            return t;
        }

        string ILegacyScoringApi.HostTypesVersion { get { Note("HostTypesVersion"); return Version; } }

        bool ILegacyScoringApi.TryBpInitial(out LegacyBpInitialSnapshot snapshot, out string reason)
        {
            Note("TryBpInitial");
            snapshot = null;
            reason = BpReason;
            if (BpThrow) { throw new InvalidOperationException("fake failure in bp initial"); }
            if (BpFail) { return false; }
            LegacyBpInitialSnapshot s = new LegacyBpInitialSnapshot();
            s.ActiveKind = (LegacyBrakeKind)KindValue;
            s.ControllerRawPa = ControllerPa;
            s.ControllerReason = ControllerReason;
            s.SmeePropertyPresent = SmeeProp;
            s.SmeePropertyRawPa = SmeePa;
            s.ClPropertyPresent = ClProp;
            s.ClPropertyRawPa = ClPa;
            snapshot = s;
            return true;
        }

        bool ILegacyScoringApi.TryVehicleLength(out LegacyVehicleLengthSnapshot snapshot, out string reason)
        {
            Note("TryVehicleLength");
            snapshot = null;
            reason = VehReason;
            if (VehThrow) { throw new InvalidOperationException("fake failure in vehicle length"); }
            if (VehFail) { return false; }
            LegacyVehicleLengthSnapshot s = new LegacyVehicleLengthSnapshot();
            s.CarLength = CarLen;
            s.FirstCount = First;
            s.MotorCount = Motor;
            s.TrailerCount = Trailer;
            snapshot = s;
            return true;
        }

        bool ILegacyScoringApi.TryLimitCount(out int count, out string reason)
        {
            Note("TryLimitCount");
            count = 0;
            reason = LimitsReason;
            if (LimitsThrow) { throw new InvalidOperationException("fake failure in limits"); }
            if (LimitsFail) { return false; }
            count = Limits.Count;
            return true;
        }

        bool ILegacyScoringApi.TryLimitElement(int index, out LegacyLimitElement element, out string reason)
        {
            Note("TryLimitElement");
            element = null;
            reason = "element-null";
            if (index == ThrowElementAt) { throw new InvalidOperationException("fake failure in element"); }
            if (index == FailElementAt || index < 0 || index >= Limits.Count) { return false; }
            FakeLimit f = Limits[index];
            LegacyLimitElement e = new LegacyLimitElement();
            e.Location = f.Location;
            e.Value = f.IsNode ? f.ValueMps : double.NaN;
            e.IsValueNode = f.IsNode;
            e.TypeName = f.TypeName;
            element = e;
            return true;
        }
    }

    /// <summary>The pure parts of the scoring-integration observation and its limits, for the tests.</summary>
    public static class ScoringInfo
    {
        public static string TypeWord(Type t) { return LegacyScoringProbe.TypeWord(t); }
        public static string Num(double v) { return LegacyScoringProbe.Num(v); }
        public static string SafeWord(string s, string fallback) { return LegacyScoringProbe.SafeWord(s, fallback); }
        public static string SafeVersion(string s) { return LegacyScoringProbe.SafeVersion(s); }
        public static int MaxLines { get { return LegacyScoringProbe.MaxLinesPerGeneration; } }
        public static int ScanPerTick { get { return LegacyScoringProbe.ScanPerTick; } }
        public static int MaxScan { get { return LegacyScoringProbe.MaxScanElements; } }
        public static int CapLimitChange { get { return LegacyScoringProbe.CapLimitChange; } }
        public static int CapBpChange { get { return LegacyScoringProbe.CapBpChange; } }
        public static int CapVehChange { get { return LegacyScoringProbe.CapVehChange; } }
        public static int OrderMaxLines { get { return LegacyOrderRecorder.MaxLinesPerProcess; } }
        public static int OrderMaxPerWord { get { return LegacyOrderRecorder.MaxPerWord; } }

        /// <summary>{ head, tail } km/h as the Current sender derives them from the list.</summary>
        public static double[] HeadTail(double location, double trainLength, double[] locs, double[] kmh)
        {
            double head;
            double tail;
            LegacyScoringProbe.HeadTail(location, trainLength, locs, kmh, out head, out tail);
            return new double[] { head, tail };
        }

        public static string Ahead(double location, double[] locs, double[] kmh)
        {
            string sample;
            int n = LegacyScoringProbe.Ahead(location, locs, kmh, out sample);
            return n + ":" + sample;
        }

    }

    /// <summary>The order recorder on its own: its lines are collected in Lines; Now is the clock the test moves.</summary>
    public class RecorderBox
    {
        internal LegacyOrderRecorder Recorder;
        public List<string> Lines = new List<string>();
        public long Now = 0;
        private readonly object gate = new object();

        public RecorderBox()
        {
            Recorder = new LegacyOrderRecorder(delegate { return Now; }, delegate (string name, string detail) { lock (gate) { Lines.Add(name + " " + detail); } });
        }

        public void Note(string word, string detail) { Recorder.Note(word, detail); }

        /// <summary>Notes from several real threads at once (each thread uses its own word).</summary>
        public void NoteFromThreads(int threads, int each)
        {
            List<System.Threading.Thread> list = new List<System.Threading.Thread>();
            for (int t = 0; t < threads; t++)
            {
                System.Threading.Thread th = new System.Threading.Thread(delegate ()
                {
                    string word = "c" + System.Threading.Thread.CurrentThread.ManagedThreadId;
                    for (int k = 0; k < each; k++) { Recorder.Note(word, "k=1"); }
                });
                list.Add(th);
                th.Start();
            }

            foreach (System.Threading.Thread th in list) { th.Join(); }
        }

        public int Suppressed { get { return Recorder.Suppressed; } }
        public int Written { get { return Recorder.Lines; } }
    }

    /// <summary>The REAL host adapter (AtsExLegacyApi) with nothing attached: it must answer with fixed reasons, never throw. Needs the host assemblies to load.</summary>
    public static class ScoringAdapterProbe
    {
        public static string[] Run()
        {
            Type adapterType = typeof(ILegacyScoringApi).Assembly.GetType("TSScoringPlugin.Telemetry.AtsExLegacyApi", true);
            ILegacyScoringApi scoring = (ILegacyScoringApi)Activator.CreateInstance(adapterType, true);
            LegacyBpInitialSnapshot b; LegacyVehicleLengthSnapshot v; LegacyLimitElement e;
            int count;
            string rb, rv, rc, re;
            bool bb = scoring.TryBpInitial(out b, out rb);
            bool bv = scoring.TryVehicleLength(out v, out rv);
            bool bc = scoring.TryLimitCount(out count, out rc);
            bool be = scoring.TryLimitElement(0, out e, out re);
            return new string[] { scoring.HostTypesVersion, bb + ":" + rb, bv + ":" + rv, bc + ":" + rc, be + ":" + re };
        }
    }

    public static class Contract
    {
        public static string Avail(string[] tokens) { return TelemetryContract.FormatAvail(tokens); }
        public static string D(double v) { return TelemetryContract.D(v); }
        public static double Signal(double mps) { return TelemetryContract.SignalLimitKmh(mps); }
        public static double Ground(double mps) { return TelemetryContract.GroundLimitKmh(mps); }
        public static string Meta(string s) { return TelemetryContract.SanitizeMeta(s); }
        public static string Station(string s) { return TelemetryContract.StationName(s); }
        public static int Version { get { return TelemetryContract.ProtocolVersion; } }
        public static int Port { get { return TelemetryContract.Port; } }
        public static string Address { get { return TelemetryContract.LoopbackAddress; } }
    }
}
