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
// Phase LI0 (observation only, diagnostic log only - nothing below is sent to the telemetry stream), read on the Tick thread only:
//   PluginBase.Native (the public INative of the plugin; no hook, no private member): VehicleSpec.BrakeNotches / PowerNotches / B67Notch, VehicleState.BcPressure / BpPressure
//   Scenario.Vehicle.Instruments.Cab (runtime type) .Handles: ReverserPosition / PowerNotch / BrakeNotch / NotchInfo (counts, EmergencyBrakeNotch, B67Notch, HasHoldingSpeedBrake)
//   Scenario.Vehicle.Panel.StateStore.BcPressure / BpPressure (arrays, logged as they are)
//
// Phase SI-0 (scoring-integration observation, diagnostic log only - nothing below is sent to the telemetry stream), read on the Tick thread only. READ ONLY:
// no method of the host that moves, re-times, initialises or jumps anything is called (Scenario.Initialize, InitializeTimeAndLocation, TimeManager.SetTime and the
// list navigation members GoTo / CurrentIndex are deliberately NOT used):
//   Scenario.Vehicle.Instruments.BrakeSystem.BrakeController (Smee / Cl BpInitialPressure) and BrakeSystem.Smee / .Cl (the route the Current sender takes)
//   Scenario.Vehicle.Dynamics.CarLength / FirstCar.Count / MotorCar.Count / TrailerCar.Count
//   Scenario.Route.SpeedLimits (Count, the indexer, MapObjectBase.Location, ValueNode<double>.Value)
//
// Phase SI-1 (SENT to the telemetry stream: TRAINLEN, MAPLIMITS, CLEARDIST, and the head limit of MAPHEAD), the same READ ONLY public values as the SI-0 observation:
//   Scenario.Vehicle.Dynamics.CarLength / MotorCar.Count / TrailerCar.Count  (FirstCar is not read: it is not part of the length)
//   Scenario.Route.SpeedLimits (Count, the indexer, MapObjectBase.Location, ValueNode<double>.Value)
//
// Phase PID-D4 / Slice 1 (the transport, not the reads): the session's texts go through LegacyDataPlaneSink (src\LegacyDataPlaneSink.cs, host independent). NORMAL mode =
// the plain text to the fixed legacy port as always; MANAGED mode = an Envelope v1 to the Directory-published endpoint of this BVE process, fail closed, no fixed-port
// fallback. This file only creates the sink for the BVE process id and hands the diagnostic of the routing core to the per-process log; nothing below reads more of the host.
//
// Phase PID-D4 / Legacy Jump 2A-alpha (wiring only): this file builds the Legacy Jump control plane (src\LegacyJumpControlPlane.cs, host independent, no host type) and calls it from
// four places, each inside its own try block: Tick (OnHostTick: start once after the managed mode is confirmed and the scenario events are subscribed, and a liveness check),
// the three scenario events (NoteScenarioBoundary), and Dispose, where the plane is shut down BEFORE the telemetry part (session.OnDispose). The plane runs on a worker of its
// own; it reads no host value, calls no host method and announces nothing. A failure of the plane switches only the plane off.
//
// Phase PID-D4 / Legacy Jump LJX-1 (acceptance build only, behind the build flag LEGACY_JUMP_EXEC): the Tick also runs the Legacy Jump execution. TickPre (claim one accepted
// command, run its host sequence, read back) runs BEFORE the session writes the row of the Tick, TickPost (the JUMP_COMPLETE) AFTER it. The host jump API is named by
// AtsExLegacyJumpHost below and nowhere else. In the default build none of this exists at run time: no runner is built, the Directory carries REQUEST_ID only.
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

        private readonly LegacyDataPlaneSink sink;
        private readonly LegacyTelemetrySession session;
        private readonly FileTelemetryDiag diag = new FileTelemetryDiag();
        private readonly System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
        private IBveHacker hacker;
        private Timer heartbeat;
        private bool subscribed;
        private bool disposedFlag;
        private LegacyJumpControlPlane jump;
        private LegacyJumpTickRunner jumpRunner;

        public TsScoringLegacyTelemetryExtension(PluginBuilder builder)
            : base(builder)
        {
            int bvePid = 0;
            try
            {
                bvePid = FileTelemetryDiag.CurrentProcessId();
            }
            catch
            {
                bvePid = 0;      // the sink then sends nothing (a router needs a process id) and says so once
            }

            sink = LegacyDataPlaneSink.Create(bvePid, LegacyDataPlaneSink.FixedLegacyDestination(), delegate (string text) { diag.Event("TEL_DP", text); });
            AtsExLegacyApi api = new AtsExLegacyApi();
            try
            {
                jump = LegacyJumpControlPlane.CreateProduction(bvePid, delegate (string text) { diag.Event("TEL_JUMP", text); });      // builds objects only: no port, no mapping, no thread
            }
            catch (Exception ex)
            {
                jump = null;      // only the Legacy Jump feature stays off; the telemetry is unaffected
                diag.Event("TEL_JUMP", "event=jump-plane-unavailable type=" + ex.GetType().Name);
            }

            // LJX-1: the row may announce the jump group only through the plane (null in the default build, where the execution is off)
            ILegacyJumpAvailability jumpAvail = null;
            try
            {
                if (jump != null && jump.ExecutionEnabledByBuild)
                {
                    jumpAvail = jump;
                }
            }
            catch
            {
                jumpAvail = null;
            }

            session = new LegacyTelemetrySession(api, sink, delegate { return clock.ElapsedMilliseconds; }, delegate { return DateTime.UtcNow.Ticks; }, diag, api, api, api, jumpAvail);
            try
            {
                api.AttachNative(Native);      // PluginBase.Native: the public route to INative; only held here, read on the Tick thread
            }
            catch
            {
                // without it the native group is reported as unavailable (native-null); everything else is unaffected
            }

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

            try
            {
                // LJX-1 (acceptance build only): the host adapter and the Tick runner. Without them the plane never announces the execution contract.
                if (jump != null && jump.ExecutionEnabledByBuild)
                {
                    AtsExLegacyJumpHost jumpHost = new AtsExLegacyJumpHost(BveHacker);
                    jumpRunner = new LegacyJumpTickRunner(jump, new LegacyJumpExecutor(jumpHost, jump.Clock), jumpHost, session, sink);
                }
            }
            catch (Exception ex)
            {
                jumpRunner = null;
                diag.Event("TEL_JUMP", "event=jump-runner-unavailable type=" + ex.GetType().Name);
            }

            diag.Event("TEL_INIT", "ver=" + FileTelemetryDiag.Version + " bitness=" + (IntPtr.Size * 8) + " host=AtsExLegacy identity=" + LegacyScenarioIdentity.KindSourceObject
                + " events=" + (subscribed ? "yes" : "no") + " heartbeat=" + (heartbeat != null ? "yes" : "no") + " sink=dataplane bvepid=" + bvePid);
            try { session.NoteInit("events=" + (subscribed ? "yes" : "no") + " heartbeat=" + (heartbeat != null ? "yes" : "no")); } catch { }
        }

        public override TickResult Tick(TimeSpan elapsed)
        {
            try
            {
                // LJX-1 (acceptance build only): claim, execute and read back BEFORE the session writes the row of this Tick; the completion follows AFTER it
                if (jumpRunner != null && jump != null && jump.ExecutionActive)
                {
                    jumpRunner.TickPre();
                }
            }
            catch
            {
            }

            try
            {
                session.OnTick(elapsed);
            }
            catch
            {
            }

            try
            {
                if (jumpRunner != null && jump != null && jump.ExecutionActive)
                {
                    jumpRunner.TickPost();
                }
            }
            catch
            {
            }

            try
            {
                // the start condition is a fact the telemetry already holds: the sender mode latch says managed. The plane starts once and only then (and only with the events subscribed).
                if (jump != null)
                {
                    jump.OnHostTick(sink.Router != null && sink.Router.Mode == TSScoringPlugin.DataPlane.CurrentSenderMode.Managed, subscribed);
                }
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

            try
            {
                // decision D-5: the Jump plane is shut down completely (stop, expire, bounded Join, WITHDRAWING, port close, CLOSED, release) before the telemetry shuts down
                if (jump != null)
                {
                    jump.Dispose();
                }
            }
            catch
            {
            }

            try { session.OnDispose(); } catch { }
            diag.Event("TEL_FINAL", "udpSent=" + sink.Sent + " udpFailed=" + sink.Failed + " mode=" + sink.ModeText);
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
            try { if (jump != null) { jump.NoteScenarioBoundary(); } } catch { }
        }

        private void OnScenarioClosed(EventArgs e)
        {
            try { session.OnScenarioClosed(); } catch { }
            try { if (jump != null) { jump.NoteScenarioBoundary(); } } catch { }
        }

        private void OnScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { session.OnScenarioCreated(); } catch { }
            try { if (jump != null) { jump.NoteScenarioBoundary(); } } catch { }
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

    /// <summary>
    /// Phase LJX-1: the host seam of the Legacy Jump executor (ILegacyJumpHost) on the AtsEX Legacy API. THIS TYPE IS THE ONLY PLACE OF THE PROJECT THAT NAMES THE HOST JUMP API:
    /// Scenario.Initialize(int), Scenario.InitializeTimeAndLocation(double, int) and TimeManager.SetTime(int), one call instruction each (the sequence order and the read back
    /// were verified on the real host by the SI-B1 probe). Every method is called on the host Tick thread by LegacyJumpExecutor only, which is reachable from Tick only. The
    /// reads catch everything (null / NaN = not readable); the three calls let the host exception through (the executor turns it into a failed command).
    /// </summary>
    internal sealed class AtsExLegacyJumpHost : ILegacyJumpHost
    {
        private readonly IBveHacker hacker;

        internal AtsExLegacyJumpHost(IBveHacker hacker)
        {
            if (ReferenceEquals(hacker, null))
            {
                throw new ArgumentNullException("hacker");
            }

            this.hacker = hacker;
        }

        public bool IsScenarioCreated()
        {
            try { return hacker.IsScenarioCreated; }
            catch { return false; }
        }

        public LegacyJumpReadBack ReadBack()
        {
            try
            {
                Scenario sc = hacker.Scenario;
                if (ReferenceEquals(sc, null))
                {
                    return null;
                }

                LegacyJumpReadBack r = new LegacyJumpReadBack();
                r.TimeMs = sc.TimeManager.TimeMilliseconds;
                r.Location = sc.LocationManager.Location;
                r.StationCount = sc.Route.Stations.Count;
                return r;
            }
            catch
            {
                return null;
            }
        }

        public double StationLocation(int index)
        {
            try
            {
                StationList list = hacker.Scenario.Route.Stations;
                Station st = list[index] as Station;
                return ReferenceEquals(st, null) ? double.NaN : st.Location;
            }
            catch
            {
                return double.NaN;
            }
        }

        public void MoveToStation(int index)
        {
            hacker.Scenario.Initialize(index);
        }

        public void MoveToLocation(double location, int timeMs)
        {
            hacker.Scenario.InitializeTimeAndLocation(location, timeMs);
        }

        public void SetClockMs(int timeMs)
        {
            hacker.Scenario.TimeManager.SetTime(timeMs);
        }
    }

    /// <summary>The Legacy API read into ILegacyApi. Every Try method catches everything: an unreadable value is "not available", never a default.</summary>
    internal sealed class AtsExLegacyApi : ILegacyApi, ILegacyInputApi, ILegacyScoringApi, ILegacyGroundApi
    {
        private IBveHacker hacker;
        private INative nativeHost;
        private Scenario current;
        private SpeedLimitList limitList;       // Phase SI-0: the list of this Tick only (reset with every new wrapper in TryScenarioIdentity)
        private int sectionCursor;
        private object sectionOwner;

        internal void Attach(IBveHacker h)
        {
            hacker = h;
        }

        internal void AttachNative(INative n)
        {
            nativeHost = n;
        }

        public bool IsScenarioCreated()
        {
            return hacker != null && hacker.IsScenarioCreated;
        }

        public bool TryScenarioIdentity(out LegacyScenarioIdentity identity)
        {
            identity = null;
            current = null;
            limitList = null;
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

                kind = KindOf(controller);
                return kind != LegacyBrakeKind.None;
            }
            catch
            {
                kind = LegacyBrakeKind.None;
                return false;
            }
        }

        private static LegacyBrakeKind KindOf(BrakeControllerBase controller)
        {
            if (controller is Smee)
            {
                return LegacyBrakeKind.Smee;
            }

            if (controller is Cl)
            {
                return LegacyBrakeKind.Cl;
            }

            if (controller is Ecb)
            {
                return LegacyBrakeKind.Ecb;
            }

            return LegacyBrakeKind.None;
        }

        // -- Phase LI0: the scoring-input observation (ILegacyInputApi). Tick thread only; every Try method turns any exception into a fixed reason. ----------
        bool ILegacyInputApi.NativeReachable
        {
            get { return nativeHost != null; }
        }

        bool ILegacyInputApi.TryHandles(out LegacyHandleSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (ReferenceEquals(current, null)) { reason = LegacyInputReason.ScenarioNull; return false; }
                Vehicle vehicle = current.Vehicle;
                if (ReferenceEquals(vehicle, null)) { reason = LegacyInputReason.VehicleNull; return false; }
                VehicleInstrumentSet instruments = vehicle.Instruments;
                if (ReferenceEquals(instruments, null)) { reason = LegacyInputReason.InstrumentsNull; return false; }
                CabBase cab = instruments.Cab;
                if (ReferenceEquals(cab, null)) { reason = LegacyInputReason.CabNull; return false; }
                HandleSet handles = cab.Handles;
                if (ReferenceEquals(handles, null)) { reason = LegacyInputReason.HandlesNull; return false; }

                LegacyHandleSnapshot s = new LegacyHandleSnapshot();
                Type cabType = cab.GetType();
                s.CabTypeName = LegacyInputProbe.SafeTypeName(cabType);
                s.HandleType = LegacyInputProbe.ClassifyCabType(cabType);
                try
                {
                    BrakeControllerBase controller = instruments.BrakeSystem.BrakeController;
                    s.BrakeKind = ReferenceEquals(controller, null) ? LegacyBrakeKind.None : KindOf(controller);
                }
                catch
                {
                    s.BrakeKind = LegacyBrakeKind.None;
                }

                try { s.Reverser = (int)handles.ReverserPosition; } catch { }
                try { s.Power = handles.PowerNotch; } catch { }
                try { s.Brake = handles.BrakeNotch; } catch { }
                NotchInfo info = null;
                try { info = handles.NotchInfo; } catch { }
                if (!ReferenceEquals(info, null))
                {
                    try { s.PowerNotchCount = info.PowerNotchCount; } catch { }
                    try { s.BrakeNotchCount = info.BrakeNotchCount; } catch { }
                    try { s.EmergencyBrakeNotch = info.EmergencyBrakeNotch; } catch { }
                    try { s.HasHoldingSpeedBrake = info.HasHoldingSpeedBrake; } catch { }
                    try { s.HoldingSpeedNotchCount = info.HoldingSpeedNotchCount; } catch { }
                    try { s.B67Notch = info.B67Notch; } catch { }
                }

                snapshot = s;
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        bool ILegacyInputApi.TryNativeSpec(out LegacySpecSnapshot spec, out string reason)
        {
            spec = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                INative n = nativeHost;
                if (n == null) { reason = LegacyInputReason.NativeNull; return false; }
                AtsEx.PluginHost.Native.VehicleSpec native = n.VehicleSpec;
                if (native == null) { reason = LegacyInputReason.SpecNull; return false; }

                LegacySpecSnapshot s = new LegacySpecSnapshot();
                try { s.BrakeNotches = native.BrakeNotches; } catch { }
                try { s.PowerNotches = native.PowerNotches; } catch { }
                try { s.B67Notch = native.B67Notch; } catch { }
                spec = s;
                return true;
            }
            catch
            {
                spec = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        bool ILegacyInputApi.TryNativePressure(out LegacyNativePressure pressure, out string reason)
        {
            pressure = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                INative n = nativeHost;
                if (n == null) { reason = LegacyInputReason.NativeNull; return false; }
                AtsEx.PluginHost.Native.VehicleState state = n.VehicleState;
                if (state == null) { reason = LegacyInputReason.StateNull; return false; }

                LegacyNativePressure p = new LegacyNativePressure();
                p.Bc = state.BcPressure;
                p.Bp = state.BpPressure;
                pressure = p;
                return true;
            }
            catch
            {
                pressure = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        bool ILegacyInputApi.TryStorePressure(out LegacyStorePressure pressure, out string reason)
        {
            pressure = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (ReferenceEquals(current, null)) { reason = LegacyInputReason.ScenarioNull; return false; }
                Vehicle vehicle = current.Vehicle;
                if (ReferenceEquals(vehicle, null)) { reason = LegacyInputReason.VehicleNull; return false; }
                VehiclePanel panel = vehicle.Panel;
                if (ReferenceEquals(panel, null)) { reason = LegacyInputReason.PanelNull; return false; }
                VehicleStateStore store = panel.StateStore;
                if (ReferenceEquals(store, null)) { reason = LegacyInputReason.StoreNull; return false; }

                LegacyStorePressure p = new LegacyStorePressure();
                try { p.Bc = store.BcPressure; } catch { }
                try { p.Bp = store.BpPressure; } catch { }
                if (p.Bc == null && p.Bp == null) { reason = LegacyInputReason.ArrayNull; return false; }
                pressure = p;
                return true;
            }
            catch
            {
                pressure = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        // -- Phase SI-0: the scoring-integration observation (ILegacyScoringApi). Tick thread only; READ ONLY; every Try method turns any exception into a fixed reason. ----
        string ILegacyScoringApi.HostTypesVersion
        {
            get
            {
                try { return typeof(Scenario).Assembly.GetName().Version.ToString(); }
                catch { return "na"; }
            }
        }

        bool ILegacyScoringApi.TryBpInitial(out LegacyBpInitialSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                if (ReferenceEquals(current, null)) { reason = LegacyScoringReason.ScenarioNull; return false; }
                Vehicle vehicle = current.Vehicle;
                if (ReferenceEquals(vehicle, null)) { reason = LegacyScoringReason.VehicleNull; return false; }
                VehicleInstrumentSet instruments = vehicle.Instruments;
                if (ReferenceEquals(instruments, null)) { reason = LegacyScoringReason.InstrumentsNull; return false; }
                BrakeSystem system = instruments.BrakeSystem;
                if (ReferenceEquals(system, null)) { reason = LegacyScoringReason.BrakeSystemNull; return false; }

                LegacyBpInitialSnapshot s = new LegacyBpInitialSnapshot();
                BrakeControllerBase controller = null;
                try { controller = system.BrakeController; } catch { }
                if (ReferenceEquals(controller, null))
                {
                    s.ActiveKind = LegacyBrakeKind.None;
                    s.ControllerReason = LegacyScoringReason.ControllerNull;
                }
                else
                {
                    s.ActiveKind = KindOf(controller);
                    Smee smee = controller as Smee;
                    Cl cl = controller as Cl;
                    if (!ReferenceEquals(smee, null))
                    {
                        try { s.ControllerRawPa = smee.BpInitialPressure; } catch { s.ControllerReason = LegacyScoringReason.ReadException; }
                    }
                    else if (!ReferenceEquals(cl, null))
                    {
                        try { s.ControllerRawPa = cl.BpInitialPressure; } catch { s.ControllerReason = LegacyScoringReason.ReadException; }
                    }
                    else
                    {
                        s.ControllerReason = LegacyScoringReason.NotApplicable;      // an Ecb has no such property
                    }
                }

                // the route the Current sender takes (BrakeSystem.Smee.BpInitialPressure): logged next to the controller route so that the two can be compared
                try
                {
                    Smee smeeProperty = system.Smee;
                    if (!ReferenceEquals(smeeProperty, null))
                    {
                        s.SmeePropertyPresent = true;
                        try { s.SmeePropertyRawPa = smeeProperty.BpInitialPressure; } catch { }
                    }
                }
                catch
                {
                }

                try
                {
                    Cl clProperty = system.Cl;
                    if (!ReferenceEquals(clProperty, null))
                    {
                        s.ClPropertyPresent = true;
                        try { s.ClPropertyRawPa = clProperty.BpInitialPressure; } catch { }
                    }
                }
                catch
                {
                }

                snapshot = s;
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        bool ILegacyScoringApi.TryVehicleLength(out LegacyVehicleLengthSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                if (ReferenceEquals(current, null)) { reason = LegacyScoringReason.ScenarioNull; return false; }
                Vehicle vehicle = current.Vehicle;
                if (ReferenceEquals(vehicle, null)) { reason = LegacyScoringReason.VehicleNull; return false; }
                VehicleDynamics dynamics = vehicle.Dynamics;
                if (ReferenceEquals(dynamics, null)) { reason = LegacyScoringReason.DynamicsNull; return false; }

                LegacyVehicleLengthSnapshot s = new LegacyVehicleLengthSnapshot();
                try { s.CarLength = dynamics.CarLength; } catch { }
                try { CarInfo first = dynamics.FirstCar; if (!ReferenceEquals(first, null)) { s.FirstCount = first.Count; } } catch { }
                try { CarInfo motor = dynamics.MotorCar; if (!ReferenceEquals(motor, null)) { s.MotorCount = motor.Count; } } catch { }
                try { CarInfo trailer = dynamics.TrailerCar; if (!ReferenceEquals(trailer, null)) { s.TrailerCount = trailer.Count; } } catch { }
                snapshot = s;
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        /// <summary>The ground limit list of this Tick (fetched once per Tick: the wrappers are rebuilt on every access). Reads only.</summary>
        private SpeedLimitList LimitListOrNull(out string reason)
        {
            reason = LegacyScoringReason.ReadException;
            if (!ReferenceEquals(limitList, null))
            {
                return limitList;
            }

            if (ReferenceEquals(current, null)) { reason = LegacyScoringReason.ScenarioNull; return null; }
            Route route = current.Route;
            if (ReferenceEquals(route, null)) { reason = LegacyScoringReason.RouteNull; return null; }
            SpeedLimitList list = route.SpeedLimits;
            if (ReferenceEquals(list, null)) { reason = LegacyScoringReason.LimitsNull; return null; }
            limitList = list;
            return list;
        }

        bool ILegacyScoringApi.TryLimitCount(out int count, out string reason)
        {
            count = 0;
            reason = LegacyScoringReason.ReadException;
            try
            {
                SpeedLimitList list = LimitListOrNull(out reason);
                if (ReferenceEquals(list, null)) { return false; }
                count = list.Count;
                return true;
            }
            catch
            {
                count = 0;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        bool ILegacyScoringApi.TryLimitElement(int index, out LegacyLimitElement element, out string reason)
        {
            element = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                SpeedLimitList list = LimitListOrNull(out reason);
                if (ReferenceEquals(list, null)) { return false; }
                if (index < 0 || index >= list.Count) { reason = LegacyScoringReason.IndexRange; return false; }
                MapObjectBase item = list[index];
                if (ReferenceEquals(item, null)) { reason = LegacyScoringReason.ElementNull; return false; }

                LegacyLimitElement e = new LegacyLimitElement();
                e.TypeName = LegacyScoringProbe.TypeWord(item.GetType());
                e.Location = item.Location;
                e.Value = double.NaN;
                ValueNode<double> node = item as ValueNode<double>;
                if (!ReferenceEquals(node, null))
                {
                    e.Value = node.Value;
                    e.IsValueNode = true;
                }

                element = e;
                return true;
            }
            catch
            {
                element = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        // -- Phase SI-1: the ground limit contract (ILegacyGroundApi). Tick thread only; READ ONLY. The list reads are the ones of the SI-0 observation (one list wrapper per Tick). ----
        bool ILegacyGroundApi.TryCarSpec(out LegacyVehicleLengthSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                if (ReferenceEquals(current, null)) { reason = LegacyScoringReason.ScenarioNull; return false; }
                Vehicle vehicle = current.Vehicle;
                if (ReferenceEquals(vehicle, null)) { reason = LegacyScoringReason.VehicleNull; return false; }
                VehicleDynamics dynamics = vehicle.Dynamics;
                if (ReferenceEquals(dynamics, null)) { reason = LegacyScoringReason.DynamicsNull; return false; }

                // the train is CarLength x (MotorCar + TrailerCar); FirstCar is not part of it (SI-0 live check). A number that cannot be read stays null.
                LegacyVehicleLengthSnapshot s = new LegacyVehicleLengthSnapshot();
                try { s.CarLength = dynamics.CarLength; } catch { }
                try { CarInfo motor = dynamics.MotorCar; if (!ReferenceEquals(motor, null)) { s.MotorCount = motor.Count; } } catch { }
                try { CarInfo trailer = dynamics.TrailerCar; if (!ReferenceEquals(trailer, null)) { s.TrailerCount = trailer.Count; } } catch { }
                snapshot = s;
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        bool ILegacyGroundApi.TryLimitCount(out int count, out string reason)
        {
            return ((ILegacyScoringApi)this).TryLimitCount(out count, out reason);
        }

        bool ILegacyGroundApi.TryLimitElement(int index, out LegacyLimitElement element, out string reason)
        {
            return ((ILegacyScoringApi)this).TryLimitElement(index, out element, out reason);
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
    /// The dedicated diagnostic log of this DLL (state changes and the final totals only - never per Tick): one text file PER BVE PROCESS in the Downloads folder of
    /// the user profile, TSScoring-LegacyTelemetry-P&lt;pid&gt;-T&lt;start&gt;.log (pid = the BVE process id, start = its start time, UTC, yyyyMMddHHmmss; Phase PID-D4 replaced the
    /// old fixed name that two BVE processes shared). The first line this process writes starts a fresh file (a new BVE process never appends to an older run, and
    /// never touches the file of another process); the file is capped. It is dedicated because the shared observation log belongs to the Handshake control plane and
    /// needs its mutex and its named objects, which this DLL deliberately does not link. Line: HH:mm:ss.fff P=pid I=instance EVENT key=value ... Only numbers, ids and
    /// fixed words are written: no path, no scenario / route / vehicle text. Nothing in here can throw into BVE.
    /// </summary>
    internal sealed class FileTelemetryDiag : ITelemetryDiag
    {
        internal const string FileNamePrefix = "TSScoring-LegacyTelemetry-";
        private const long MaxBytes = 1024 * 1024;

        private static readonly object sync = new object();
        private static readonly HashSet<string> started = new HashSet<string>(StringComparer.OrdinalIgnoreCase);   // files this process already began (truncated)
        private static readonly HashSet<string> capped = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static int instances;
        private static string defaultPathCache;
        private static int processIdCache;

        private readonly int instance;
        private readonly string pathOverride;
        private readonly int processId;       // 0 = this process (production); a number only for the offline tests of the per-process naming

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

        /// <summary>Offline tests of the per-process naming: the file of an imagined BVE process (its id and start time) in a folder the test owns.</summary>
        internal FileTelemetryDiag(int processId, DateTime processStartUtc, string directory)
            : this(System.IO.Path.Combine(directory, NameFor(processId, StartStamp(processStartUtc))))
        {
            this.processId = processId;
        }

        /// <summary>The start time of a process as it appears in the file name (UTC, to the second).</summary>
        internal static string StartStamp(DateTime startUtc)
        {
            return startUtc.ToUniversalTime().ToString("yyyyMMddHHmmss", System.Globalization.CultureInfo.InvariantCulture);
        }

        /// <summary>TSScoring-LegacyTelemetry-P&lt;pid&gt;-T&lt;start&gt;.log</summary>
        internal static string NameFor(int processId, string startStamp)
        {
            return FileNamePrefix + "P" + processId.ToString(System.Globalization.CultureInfo.InvariantCulture) + "-T" + startStamp + ".log";
        }

        internal static int CurrentProcessId()
        {
            int cached = processIdCache;
            if (cached > 0)
            {
                return cached;
            }

            using (System.Diagnostics.Process process = System.Diagnostics.Process.GetCurrentProcess())
            {
                processIdCache = process.Id;
                return processIdCache;
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

        /// <summary>The production path: Downloads\TSScoring-LegacyTelemetry-P&lt;this BVE process id&gt;-T&lt;its start time&gt;.log, worked out once. null when it cannot be (then nothing is logged).</summary>
        internal static string DefaultPath()
        {
            string cached = defaultPathCache;
            if (cached != null)
            {
                return cached;
            }

            try
            {
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (string.IsNullOrEmpty(profile))
                {
                    return null;
                }

                string stamp = "0";
                try
                {
                    using (System.Diagnostics.Process process = System.Diagnostics.Process.GetCurrentProcess())
                    {
                        stamp = StartStamp(process.StartTime);
                    }
                }
                catch
                {
                    stamp = "0";
                }

                defaultPathCache = System.IO.Path.Combine(System.IO.Path.Combine(profile, "Downloads"), NameFor(CurrentProcessId(), stamp));
                return defaultPathCache;
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

                    int pid = processId;
                    if (pid <= 0)
                    {
                        try { pid = CurrentProcessId(); } catch { }
                    }
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
