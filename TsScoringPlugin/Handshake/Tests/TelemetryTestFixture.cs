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

    /// <summary>Drives the core the way the host adapter does: events, Ticks, the heartbeat, Dispose. Time is a number the test moves.</summary>
    public class Harness
    {
        public FakeApi Api = new FakeApi();
        public CollectSink Sink = new CollectSink();
        public CollectDiag Diag = new CollectDiag();
        public long Now = 1000;
        public long Seed = 5000000000L;
        private LegacyTelemetrySession session;

        public Harness()
        {
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, Diag);
        }

        /// <summary>Replaces the diagnostic with the REAL file diagnostic of the DLL, writing to a path the test owns.</summary>
        public void UseFileDiag(string path)
        {
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, new FileTelemetryDiag(path));
        }

        /// <summary>A new extension instance after the previous one was disposed (a new session over the same fake host, a fresh sink).</summary>
        public void Reinitialize()
        {
            Sink = new CollectSink();
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, Diag);
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

        public LiveHarness()
        {
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; });
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
