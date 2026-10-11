using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Threading;
using AtsEx.PluginHost;
using BveTypes.ClassWrappers;

// ============================================================================
// PHASE SI-B1 - B1-probe: the AtsEX Legacy adapter. OBSERVATION ONLY, built only into the probe DLL.
//
// This is the ONLY probe file that names an AtsEx / BveTypes type and the ONLY place where Scenario.Initialize / Scenario.InitializeTimeAndLocation /
// TimeManager.SetTime are called. Those three calls are reachable only through B1ProbeEngine.TryExecute, which is reached only from
// B1ProbeEngine.BeginTick, which is called only from the Extension Tick (B1ProbeHook.BeginTick, inserted into the generated probe copy of
// LegacyTelemetryExtension.cs by Tools\New-B1ProbeExtension.ps1). No timer thread, no event handler and no Dispose path ever calls them.
//
// The event handlers below only increment counters (Interlocked); they read nothing from BVE.
// Nothing here sends anything to UDP 54321 / 54322, announces "jump" in AVAIL, answers a COMPLETE or starts scoring.
// ============================================================================
namespace TSScoringPlugin.Telemetry.B1Probe
{
    /// <summary>Records the telemetry datagrams the session sends (the session is given this sink, which forwards to the real one). Reads nothing from BVE.</summary>
    internal sealed class B1TapSink : ITelemetrySink
    {
        private readonly ITelemetrySink inner;
        private readonly object gate = new object();
        private string lastLine;
        private long lineSeq;

        internal B1TapSink(ITelemetrySink inner)
        {
            this.inner = inner;
        }

        internal string LastLine
        {
            get { lock (gate) { return lastLine; } }
        }

        internal long LineSeq
        {
            get { lock (gate) { return lineSeq; } }
        }

        public void Send(string text)
        {
            try
            {
                if (text != null && text.StartsWith("SCENARIO_ID:", StringComparison.Ordinal))
                {
                    lock (gate)
                    {
                        lastLine = text;
                        lineSeq++;
                    }
                }
            }
            catch
            {
            }

            inner.Send(text);
        }

        public void Close()
        {
            inner.Close();
        }
    }

    /// <summary>The real host: reads the Legacy API into B1Snapshot and makes the three observed calls. Tick thread only (see the header).</summary>
    internal sealed class AtsExProbeHost : IB1ProbeHost
    {
        private readonly IBveHacker hacker;
        private readonly INative native;
        private int opened;
        private int closed;
        private int created;
        private int nativeStarted;
        private int nativeDoorOpened;
        private int nativeDoorClosed;
        private int nativeSignal;
        private int nativeBeacon;

        internal AtsExProbeHost(IBveHacker hacker, INative native)
        {
            this.hacker = hacker;
            this.native = native;
        }

        internal void Subscribe()
        {
            try
            {
                hacker.ScenarioOpened += OnOpened;
                hacker.ScenarioClosed += OnClosed;
                hacker.ScenarioCreated += OnCreated;
            }
            catch
            {
            }

            try
            {
                if (native != null)
                {
                    native.Started += OnNativeStarted;
                    native.DoorOpened += OnNativeDoorOpened;
                    native.DoorClosed += OnNativeDoorClosed;
                    native.SignalUpdated += OnNativeSignal;
                    native.BeaconPassed += OnNativeBeacon;
                }
            }
            catch
            {
            }
        }

        internal void Unsubscribe()
        {
            try
            {
                hacker.ScenarioOpened -= OnOpened;
                hacker.ScenarioClosed -= OnClosed;
                hacker.ScenarioCreated -= OnCreated;
            }
            catch
            {
            }

            try
            {
                if (native != null)
                {
                    native.Started -= OnNativeStarted;
                    native.DoorOpened -= OnNativeDoorOpened;
                    native.DoorClosed -= OnNativeDoorClosed;
                    native.SignalUpdated -= OnNativeSignal;
                    native.BeaconPassed -= OnNativeBeacon;
                }
            }
            catch
            {
            }
        }

        private void OnOpened(ScenarioOpenedEventArgs e) { Interlocked.Increment(ref opened); }

        private void OnClosed(EventArgs e) { Interlocked.Increment(ref closed); }

        private void OnCreated(ScenarioCreatedEventArgs e) { Interlocked.Increment(ref created); }

        private void OnNativeStarted(AtsEx.PluginHost.Native.StartedEventArgs e) { Interlocked.Increment(ref nativeStarted); }

        private void OnNativeDoorOpened(AtsEx.PluginHost.Native.DoorEventArgs e) { Interlocked.Increment(ref nativeDoorOpened); }

        private void OnNativeDoorClosed(AtsEx.PluginHost.Native.DoorEventArgs e) { Interlocked.Increment(ref nativeDoorClosed); }

        private void OnNativeSignal(AtsEx.PluginHost.Native.SignalUpdatedEventArgs e) { Interlocked.Increment(ref nativeSignal); }

        private void OnNativeBeacon(AtsEx.PluginHost.Native.BeaconPassedEventArgs e) { Interlocked.Increment(ref nativeBeacon); }

        public B1Counters Counters()
        {
            B1Counters c = new B1Counters();
            c.ScenarioOpened = Thread.VolatileRead(ref opened);
            c.ScenarioClosed = Thread.VolatileRead(ref closed);
            c.ScenarioCreated = Thread.VolatileRead(ref created);
            c.NativeStarted = Thread.VolatileRead(ref nativeStarted);
            c.NativeDoorOpened = Thread.VolatileRead(ref nativeDoorOpened);
            c.NativeDoorClosed = Thread.VolatileRead(ref nativeDoorClosed);
            c.NativeSignalUpdated = Thread.VolatileRead(ref nativeSignal);
            c.NativeBeaconPassed = Thread.VolatileRead(ref nativeBeacon);
            return c;
        }

        public bool IsScenarioCreated()
        {
            return hacker != null && hacker.IsScenarioCreated;
        }

        private static bool Finite(double v)
        {
            return !double.IsNaN(v) && !double.IsInfinity(v);
        }

        public B1Snapshot Snapshot(int stationIndexOfInterest)
        {
            B1Snapshot s = new B1Snapshot();
            List<string> bad = new List<string>();
            Scenario sc = null;
            try
            {
                s.ScenarioCreated = hacker.IsScenarioCreated;
                sc = hacker.Scenario;
            }
            catch
            {
                bad.Add("scenario");
            }

            if (ReferenceEquals(sc, null))
            {
                s.FailedReads = string.Join(",", bad.ToArray());
                return s;
            }

            try { object src = sc.Src; s.ScenarioObjectId = RuntimeHelpers.GetHashCode(src); } catch { bad.Add("src"); }
            try { s.TimeMs = sc.TimeManager.TimeMilliseconds; } catch { bad.Add("time"); }
            try { double v = sc.LocationManager.Location; if (Finite(v)) { s.Location = v; } else { bad.Add("loc-nan"); } } catch { bad.Add("loc"); }
            try { double v = sc.LocationManager.SpeedMeterPerSecond; if (Finite(v)) { s.SpeedMps = v; } else { bad.Add("speed-nan"); } } catch { bad.Add("speed"); }
            try { s.DoorsClosed = sc.Vehicle.Doors.AreAllClosed; } catch { bad.Add("door"); }
            try
            {
                HandleSet handles = sc.Vehicle.Instruments.Cab.Handles;
                try { s.Reverser = (int)handles.ReverserPosition; } catch { bad.Add("rev"); }
                try { s.Power = handles.PowerNotch; } catch { bad.Add("pwr"); }
                try { s.Brake = handles.BrakeNotch; } catch { bad.Add("brk"); }
            }
            catch
            {
                bad.Add("handles");
            }

            try
            {
                StationList list = sc.Route.Stations;
                int count = list.Count;
                s.StationCount = count;
                double loc = s.Location.HasValue ? s.Location.Value : double.NaN;
                int at = -1;
                int prev = -1;
                int next = -1;
                for (int i = 0; i < count; i++)
                {
                    Station st = list[i] as Station;
                    if (st == null)
                    {
                        bad.Add("station-type");
                        break;
                    }

                    double sl = st.Location;
                    if (i == stationIndexOfInterest)
                    {
                        s.ReqStationLocation = sl;
                        s.ReqStationPass = st.Pass;
                    }

                    if (!Finite(loc))
                    {
                        continue;
                    }

                    if (Math.Abs(sl - loc) <= 0.5 && at < 0) { at = i; }
                    if (sl <= loc) { prev = i; }
                    if (sl > loc && next < 0)
                    {
                        next = i;
                        s.NextStationLocation = sl;
                        s.NextStationPass = st.Pass;
                    }
                }

                if (Finite(loc))
                {
                    s.StationAtIndex = at;
                    s.PrevStationIndex = prev;
                    s.NextStationIndex = next;
                }
            }
            catch
            {
                bad.Add("stations");
            }

            try { double v = sc.SectionManager.CurrentSectionSpeedLimit; if (!double.IsNaN(v)) { s.SignalLimitMps = v; } } catch { bad.Add("siglimit"); }
            try { double v = sc.SectionManager.ForwardSectionSpeedLimit; if (!double.IsNaN(v)) { s.ForwardSignalLimitMps = v; } } catch { bad.Add("fwdsig"); }
            try { double v = sc.Route.SpeedLimits.CurrentLimit; if (!double.IsNaN(v)) { s.GroundLimitMps = v; } } catch { bad.Add("ground"); }

            try
            {
                if (native != null)
                {
                    AtsEx.PluginHost.Native.VehicleState vs = native.VehicleState;
                    if (vs != null)
                    {
                        try { double v = vs.Location; if (Finite(v)) { s.NativeLocation = v; } } catch { bad.Add("nat-loc"); }
                        try { double v = vs.Speed; if (Finite(v)) { s.NativeSpeedKmh = v; } } catch { bad.Add("nat-spd"); }
                        try { s.NativeTimeMs = (int)Math.Round(vs.Time.TotalMilliseconds); } catch { bad.Add("nat-time"); }
                        try { double v = vs.BcPressure; if (Finite(v)) { s.NativeBcKpa = v; } } catch { bad.Add("nat-bc"); }
                        try { double v = vs.BpPressure; if (Finite(v)) { s.NativeBpKpa = v; } } catch { bad.Add("nat-bp"); }
                    }

                    AtsEx.PluginHost.Handles.HandleSet nh = native.Handles;
                    if (nh != null)
                    {
                        try { s.NativePower = nh.Power.Notch; } catch { bad.Add("nat-pwr"); }
                        try { s.NativeBrake = nh.Brake.Notch; } catch { bad.Add("nat-brk"); }
                        try { s.NativeReverser = (int)nh.Reverser.Position; } catch { bad.Add("nat-rev"); }
                    }
                }
            }
            catch
            {
                bad.Add("native");
            }

            s.FailedReads = string.Join(",", bad.ToArray());
            return s;
        }

        // ---- the three observed host calls (Tick thread, from B1ProbeEngine.TryExecute only) ------------------------------------------------
        public void SetTime(int timeMs)
        {
            hacker.Scenario.TimeManager.SetTime(timeMs);
        }

        public void InitializeStation(int stationIndex)
        {
            hacker.Scenario.Initialize(stationIndex);
        }

        public void InitializeLocation(double location, int timeMs)
        {
            hacker.Scenario.InitializeTimeAndLocation(location, timeMs);
        }
    }

    /// <summary>
    /// The wiring the generated probe copy of the Extension uses (see Tools\New-B1ProbeExtension.ps1): TapSink at construction, Attach once the hacker and Native
    /// exist, BeginTick before and EndTick after the telemetry session's Tick, OnDispose before the session's Dispose. Every member swallows everything.
    /// </summary>
    internal sealed class B1ProbeHook
    {
        private B1TapSink tap;
        private AtsExProbeHost host;
        private B1ProbeEngine engine;
        private LegacyTelemetrySession session;

        internal ITelemetrySink TapSink(ITelemetrySink inner)
        {
            tap = new B1TapSink(inner);
            return tap;
        }

        internal void Attach(IBveHacker hacker, INative native, LegacyTelemetrySession telemetrySession)
        {
            try
            {
                session = telemetrySession;
                host = new AtsExProbeHost(hacker, native);
                host.Subscribe();
                B1ProbeFileIo io = new B1ProbeFileIo(null);
                engine = new B1ProbeEngine(host, io, ViewOfSession, new B1Config());
                string version = "?";
                try { version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString(); } catch { }
                engine.LogInit(version, "native=" + (native != null ? "yes" : "no") + " tap=" + (tap != null ? "yes" : "no"));
            }
            catch
            {
                engine = null;
            }
        }

        private B1SessionView ViewOfSession()
        {
            B1SessionView v = new B1SessionView();
            LegacyTelemetrySession s = session;
            if (s != null)
            {
                v.ScenarioActive = s.ScenarioActive;
                v.ScenarioId = s.ScenarioId;
                v.Discontinuities = s.Discontinuities;
                v.LinesSent = s.LinesSent;
                v.LinesSkipped = s.LinesSkipped;
                v.LastAvail = s.LastAvail;
            }

            B1TapSink t = tap;
            if (t != null)
            {
                v.LastLine = t.LastLine;
                v.LineSeq = t.LineSeq;
            }

            return v;
        }

        internal void BeginTick(TimeSpan elapsed)
        {
            B1ProbeEngine e = engine;
            if (e != null)
            {
                e.BeginTick(elapsed.TotalMilliseconds);
            }
        }

        internal void EndTick()
        {
            B1ProbeEngine e = engine;
            if (e != null)
            {
                e.EndTick();
            }
        }

        internal void OnDispose()
        {
            B1ProbeEngine e = engine;
            try
            {
                if (e != null)
                {
                    e.OnDispose();
                }
            }
            catch
            {
            }

            try
            {
                if (host != null)
                {
                    host.Unsubscribe();
                }
            }
            catch
            {
            }
        }
    }
}
