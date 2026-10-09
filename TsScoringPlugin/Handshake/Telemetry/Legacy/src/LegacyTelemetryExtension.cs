using System;
using System.Collections.Generic;
using System.Timers;
using AtsEx.PluginHost;
using AtsEx.PluginHost.Plugins;
using AtsEx.PluginHost.Plugins.Extensions;
using BveTypes.ClassWrappers;

// ============================================================================
// PHASE L3 - AtsEX LEGACY telemetry sender: the host adapter.
//
// This is the ONLY file of the telemetry project that names an AtsEX / BveTypes type. It reads the Legacy API into the plain values of ILegacyApi
// and forwards the host's Tick and scenario events to LegacyTelemetrySession, which is host independent. It does not use, link or reference the
// Handshake control plane (Ready, ScenarioReady, the state block): the telemetry is the DATA plane, the Bridge is the CONTROL plane, and each can
// be present, absent, restarted or fail without the other noticing.
//
// It never refers to a BveEX (Current) type: the Current sender (TsScoringPlugin\Class1.cs) is a different product for a different host.
//
// Legacy API used (AtsEx.PluginHost 1.0 / BveTypes of the Legacy host), read on the Tick thread only:
//   IBveHacker.IsScenarioCreated / Scenario / ScenarioInfo, ScenarioOpened / ScenarioClosed / ScenarioCreated
//   ClassWrapperBase.Src (Scenario.Src): the original BVE Scenario object, the identity of a scenario instance (see LegacyScenarioIdentityReader.IdentityOf)
//   Scenario.TimeManager.TimeMilliseconds                          ms
//   Scenario.LocationManager.Location / SpeedMeterPerSecond        m, m/s
//   Scenario.Vehicle.Doors.AreAllClosed
//   Scenario.Route.Stations / MyTrack.Gradients / SpeedLimits.CurrentLimit
//   Scenario.SectionManager.CurrentSectionSpeedLimit / ForwardSectionSpeedLimit / Sections
//   Scenario.Vehicle.Instruments.BrakeSystem / Cab.Handles.NotchInfo
//
// The timer thread (heartbeat) uses the session's own volatile fields only; it never touches BveHacker, a Scenario or any BVE object.
// No exception ever leaves the constructor, Tick, Dispose, an event handler or the timer.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    [Plugin(PluginType.Extension)]
    public class TsScoringLegacyTelemetryExtension : AssemblyPluginBase, IExtension
    {
        private const double HeartbeatIntervalMs = 50;

        private readonly UdpTelemetrySink sink;
        private readonly LegacyTelemetrySession session;
        private readonly FileTelemetryDiag diag = new FileTelemetryDiag();
        private readonly System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
        private IBveHacker hacker;
        private Timer heartbeat;
        private bool subscribed;
        private bool disposedFlag;

        public TsScoringLegacyTelemetryExtension(PluginBuilder builder)
            : base(builder)
        {
            sink = new UdpTelemetrySink();
            AtsExLegacyApi api = new AtsExLegacyApi();
            session = new LegacyTelemetrySession(api, sink, delegate { return clock.ElapsedMilliseconds; }, delegate { return DateTime.UtcNow.Ticks; }, diag);
            try
            {
                hacker = BveHacker;
                api.Attach(hacker);
                hacker.ScenarioOpened += OnScenarioOpened;
                hacker.ScenarioClosed += OnScenarioClosed;
                hacker.ScenarioCreated += OnScenarioCreated;
                subscribed = true;
            }
            catch
            {
                // without the events the Tick still recognises a new scenario instance by the original Scenario object behind the wrapper
            }

            try
            {
                heartbeat = new Timer(HeartbeatIntervalMs);
                heartbeat.Elapsed += OnHeartbeat;
                heartbeat.Start();
            }
            catch
            {
                heartbeat = null;
            }

            diag.Event("TEL_INIT", "ver=" + FileTelemetryDiag.Version + " bitness=" + (IntPtr.Size * 8) + " host=AtsExLegacy identity=" + LegacyScenarioIdentity.KindSourceObject
                + " events=" + (subscribed ? "yes" : "no") + " heartbeat=" + (heartbeat != null ? "yes" : "no"));
        }

        public override TickResult Tick(TimeSpan elapsed)
        {
            try
            {
                session.OnTick(elapsed);
            }
            catch
            {
            }

            return new ExtensionTickResult();
        }

        public override void Dispose()
        {
            disposedFlag = true;
            try
            {
                if (heartbeat != null)
                {
                    heartbeat.Stop();
                    heartbeat.Dispose();
                    heartbeat = null;
                }
            }
            catch
            {
            }

            try
            {
                IBveHacker h = hacker;
                if (subscribed && h != null)
                {
                    subscribed = false;
                    h.ScenarioOpened -= OnScenarioOpened;
                    h.ScenarioClosed -= OnScenarioClosed;
                    h.ScenarioCreated -= OnScenarioCreated;
                }
            }
            catch
            {
            }

            try { session.OnDispose(); } catch { }
            diag.Event("TEL_FINAL", "udpSent=" + sink.Sent + " udpFailed=" + sink.Failed);
        }

        private void OnHeartbeat(object sender, ElapsedEventArgs e)
        {
            try
            {
                if (disposedFlag)
                {
                    return;
                }

                string text = session.ComposeHeartbeat();
                if (text != null)
                {
                    sink.Send(text);
                }
            }
            catch
            {
            }
        }

        private void OnScenarioOpened(ScenarioOpenedEventArgs e)
        {
            bool reload = false;
            try { reload = e.IsReload; } catch { }
            try { session.OnScenarioOpened(reload); } catch { }
        }

        private void OnScenarioClosed(EventArgs e)
        {
            try { session.OnScenarioClosed(); } catch { }
        }

        private void OnScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { session.OnScenarioCreated(); } catch { }
        }
    }

    /// <summary>
    /// The identity of a scenario instance. hacker.Scenario builds a NEW wrapper (Scenario.FromSource) on every access, so wrappers of the very same scenario are
    /// different objects (Equals compares Src). The identity is therefore the original BVE object behind the wrapper (ClassWrapperBase.Src), by reference.
    /// </summary>
    internal static class LegacyScenarioIdentityReader
    {
        internal static LegacyScenarioIdentity IdentityOf(Scenario wrapper)
        {
            if (ReferenceEquals(wrapper, null))      // not "== null": the wrapper classes overload == and it dereferences its left side
            {
                return null;
            }

            object source = wrapper.Src;
            if (source == null)
            {
                return null;
            }

            LegacyScenarioIdentity identity = new LegacyScenarioIdentity();
            identity.Source = source;
            identity.Wrapper = wrapper;
            identity.Kind = LegacyScenarioIdentity.KindSourceObject;
            return identity;
        }
    }

    /// <summary>The Legacy API read into ILegacyApi. Every Try method catches everything: an unreadable value is "not available", never a default.</summary>
    internal sealed class AtsExLegacyApi : ILegacyApi
    {
        private IBveHacker hacker;
        private Scenario current;
        private int sectionCursor;
        private object sectionOwner;

        internal void Attach(IBveHacker h)
        {
            hacker = h;
        }

        public bool IsScenarioCreated()
        {
            return hacker != null && hacker.IsScenarioCreated;
        }

        public bool TryScenarioIdentity(out LegacyScenarioIdentity identity)
        {
            identity = null;
            current = null;
            try
            {
                Scenario s = hacker.Scenario;
                LegacyScenarioIdentity id = LegacyScenarioIdentityReader.IdentityOf(s);
                if (id == null)
                {
                    return false;
                }

                current = s;       // the wrapper of this Tick: used for this Tick's reads only, never compared
                identity = id;
                return true;
            }
            catch
            {
                identity = null;
                return false;
            }
        }

        public bool TryTimeMs(out int timeMs)
        {
            timeMs = 0;
            try { timeMs = current.TimeManager.TimeMilliseconds; return true; }
            catch { return false; }
        }

        public bool TryLocation(out double meters)
        {
            meters = 0;
            try { meters = current.LocationManager.Location; return true; }
            catch { return false; }
        }

        public bool TrySpeedMps(out double metersPerSecond)
        {
            metersPerSecond = 0;
            try { metersPerSecond = current.LocationManager.SpeedMeterPerSecond; return true; }
            catch { return false; }
        }

        public bool TryDoorsClosed(out bool allClosed)
        {
            allClosed = false;
            try { allClosed = current.Vehicle.Doors.AreAllClosed; return true; }
            catch { return false; }
        }

        public bool TryGradientRatio(double location, out double ratio)
        {
            // the raw API value (a ratio, see ILegacyApi.TryGradientRatio); the conversion to per mille is the session's, in one place
            ratio = 0;
            try { ratio = current.Route.MyTrack.Gradients.GetValueAt(location); return true; }
            catch { return false; }
        }

        public bool TryStationCount(out int count)
        {
            count = 0;
            try { count = current.Route.Stations.Count; return true; }
            catch { return false; }
        }

        public bool TryStations(out IList<LegacyStationRaw> stations)
        {
            stations = null;
            try
            {
                StationList list = current.Route.Stations;
                List<LegacyStationRaw> result = new List<LegacyStationRaw>(list.Count);
                for (int i = 0; i < list.Count; i++)
                {
                    Station st = list[i] as Station;
                    if (st == null)
                    {
                        return false;
                    }

                    LegacyStationRaw r = new LegacyStationRaw();
                    r.Name = st.Name;
                    r.Location = st.Location;
                    r.Pass = st.Pass;
                    r.IsTerminal = st.IsTerminal;
                    r.DoorSide = st.DoorSide;
                    r.ArrivalMs = st.ArrivalTimeMilliseconds;
                    r.DepartureMs = st.DepartureTimeMilliseconds;
                    r.DefaultMs = st.DefaultTimeMilliseconds;
                    r.StoppageMs = st.StoppageTimeMilliseconds;
                    r.MarginMin = st.MarginMin;
                    r.MarginMax = st.MarginMax;
                    if (!TelemetryContract.Finite(r.Location) || !TelemetryContract.Finite(r.MarginMin) || !TelemetryContract.Finite(r.MarginMax))
                    {
                        return false;
                    }

                    result.Add(r);
                }

                stations = result;
                return true;
            }
            catch
            {
                stations = null;
                return false;
            }
        }

        public bool TrySignalLimitMps(out double metersPerSecond)
        {
            metersPerSecond = 0;
            try { metersPerSecond = current.SectionManager.CurrentSectionSpeedLimit; return true; }
            catch { return false; }
        }

        public bool TryForwardSignalLimitMps(out double metersPerSecond)
        {
            metersPerSecond = 0;
            try { metersPerSecond = current.SectionManager.ForwardSectionSpeedLimit; return true; }
            catch { return false; }
        }

        public bool TryNextSectionLocation(double location, out bool found, out double sectionLocation)
        {
            found = false;
            sectionLocation = 0;
            try
            {
                MapFunctionList sections = current.SectionManager.Sections;
                if (!ReferenceEquals(sectionOwner, sections))
                {
                    sectionOwner = sections;
                    sectionCursor = 0;
                }

                int count = sections.Count;
                if (sectionCursor > count)
                {
                    sectionCursor = 0;
                }

                // the vehicle only moves forward in practice: the search resumes where it ended, and steps back when the vehicle went back
                while (sectionCursor > 0 && sections[sectionCursor - 1].Location > location)
                {
                    sectionCursor--;
                }

                while (sectionCursor < count && !(sections[sectionCursor].Location > location))
                {
                    sectionCursor++;
                }

                if (sectionCursor < count)
                {
                    found = true;
                    sectionLocation = sections[sectionCursor].Location;
                }

                return true;
            }
            catch
            {
                return false;
            }
        }

        public bool TryGroundLimitMps(out double metersPerSecond)
        {
            metersPerSecond = 0;
            try { metersPerSecond = current.Route.SpeedLimits.CurrentLimit; return true; }
            catch { return false; }
        }

        public bool TryBrakeKind(out LegacyBrakeKind kind)
        {
            kind = LegacyBrakeKind.None;
            try
            {
                BrakeSystem system = current.Vehicle.Instruments.BrakeSystem;
                BrakeControllerBase controller = system.BrakeController;
                if (controller == null)
                {
                    return false;
                }

                if (controller is Smee)
                {
                    kind = LegacyBrakeKind.Smee;
                }
                else if (controller is Cl)
                {
                    kind = LegacyBrakeKind.Cl;
                }
                else if (controller is Ecb)
                {
                    kind = LegacyBrakeKind.Ecb;
                }

                return kind != LegacyBrakeKind.None;
            }
            catch
            {
                kind = LegacyBrakeKind.None;
                return false;
            }
        }

        public bool TryBrakeNotches(out int brakeNotchCount, out bool hasHoldingSpeedBrake)
        {
            brakeNotchCount = 0;
            hasHoldingSpeedBrake = false;
            try
            {
                NotchInfo info = current.Vehicle.Instruments.Cab.Handles.NotchInfo;
                brakeNotchCount = info.BrakeNotchCount;
                hasHoldingSpeedBrake = info.HasHoldingSpeedBrake;
                return true;
            }
            catch
            {
                return false;
            }
        }

        public bool TryPressureRates(out double[] rates, out double maximumPressurePa)
        {
            rates = null;
            maximumPressurePa = 0;
            try
            {
                BrakeControllerBase controller = current.Vehicle.Instruments.BrakeSystem.BrakeController;
                rates = controller.PressureRates;
                maximumPressurePa = controller.MaximumPressure;
                return true;
            }
            catch
            {
                rates = null;
                return false;
            }
        }

        public bool TryScenarioMeta(out LegacyScenarioMeta meta)
        {
            meta = null;
            try
            {
                ScenarioInfo info = hacker.ScenarioInfo;
                if (info == null)
                {
                    return false;
                }

                LegacyScenarioMeta m = new LegacyScenarioMeta();
                m.Title = info.Title;
                m.RouteTitle = info.RouteTitle;
                m.VehicleTitle = info.VehicleTitle;
                m.Author = info.Author;
                m.Comment = info.Comment;
                meta = m;
                return true;
            }
            catch
            {
                meta = null;
                return false;
            }
        }
    }

    /// <summary>
    /// The dedicated diagnostic log of this DLL (state changes and the final totals only - never per Tick): one text file in the Downloads folder of the user
    /// profile, TSScoring-L3-Telemetry.log. The first line this process writes starts a fresh file (a new BVE process never appends to an older run); the file is
    /// capped. It is dedicated because the shared observation log belongs to the Handshake control plane and needs its mutex and its named objects, which this
    /// DLL deliberately does not link. Line: HH:mm:ss.fff P=pid I=instance EVENT key=value ... Only numbers, ids and fixed words are written: no path,
    /// no scenario / route / vehicle text. Nothing in here can throw into BVE.
    /// </summary>
    internal sealed class FileTelemetryDiag : ITelemetryDiag
    {
        internal const string FileName = "TSScoring-L3-Telemetry.log";
        private const long MaxBytes = 1024 * 1024;

        private static readonly object sync = new object();
        private static readonly HashSet<string> started = new HashSet<string>(StringComparer.OrdinalIgnoreCase);   // files this process already began (truncated)
        private static readonly HashSet<string> capped = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static int instances;

        private readonly int instance;
        private readonly string pathOverride;

        internal FileTelemetryDiag()
            : this(null)
        {
        }

        /// <summary>pathOverride is for the offline tests only (null in production: the Downloads folder).</summary>
        internal FileTelemetryDiag(string pathOverride)
        {
            this.pathOverride = pathOverride;
            lock (sync)
            {
                instance = ++instances;
            }
        }

        internal static string Version
        {
            get
            {
                try { return System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString(); }
                catch { return "?"; }
            }
        }

        internal static string DefaultPath()
        {
            try
            {
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (string.IsNullOrEmpty(profile))
                {
                    return null;
                }

                return System.IO.Path.Combine(System.IO.Path.Combine(profile, "Downloads"), FileName);
            }
            catch
            {
                return null;
            }
        }

        public void Event(string name, string detail)
        {
            try
            {
                string path = pathOverride ?? DefaultPath();
                if (path == null)
                {
                    return;
                }

                lock (sync)
                {
                    if (capped.Contains(path))
                    {
                        return;
                    }

                    if (started.Add(path))
                    {
                        System.IO.File.WriteAllText(path, string.Empty);
                    }
                    else if (new System.IO.FileInfo(path).Length > MaxBytes)
                    {
                        capped.Add(path);
                        System.IO.File.AppendAllText(path, DateTime.Now.ToString("HH:mm:ss.fff") + " TEL_LOG_CAP_REACHED\r\n");
                        return;
                    }

                    int pid = 0;
                    try { pid = System.Diagnostics.Process.GetCurrentProcess().Id; } catch { }
                    string line = DateTime.Now.ToString("HH:mm:ss.fff") + " P=" + pid + " I=" + instance + " " + name
                        + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail) + "\r\n";
                    System.IO.File.AppendAllText(path, line);
                }
            }
            catch
            {
                // a diagnostic log never takes BVE down
            }
        }
    }
}
