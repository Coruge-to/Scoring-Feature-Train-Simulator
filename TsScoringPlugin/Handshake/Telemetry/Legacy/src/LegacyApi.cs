using System;
using System.Collections.Generic;

// ============================================================================
// PHASE L3 - the READ SURFACE of the AtsEX Legacy telemetry sender.
//
// ILegacyApi is everything the sender asks the Legacy host for, expressed in plain values and in the units the Legacy API documents. It is the only
// seam between the host (LegacyTelemetryExtension.cs, the one file that names AtsEx / BveTypes types) and the host independent core
// (LegacyTelemetrySession, LegacyStationTimeline, the normalisation to the telemetry contract). The offline tests drive the core with a fake of this
// interface; the real implementation is a thin reader.
//
// Contract of every Try method: true = the value was read now and is finite where it is a number; false = it cannot be read (null, exception,
// NaN, Infinity). There is NO default value: a value that cannot be read is simply not sent (and its token is not announced in AVAIL).
// All Try methods are called on the host's Tick thread only.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>One station of the Legacy route, as the Legacy API gives it (times in ms, distances in m).</summary>
    internal sealed class LegacyStationRaw
    {
        internal string Name;
        internal double Location;
        internal bool Pass;
        internal bool IsTerminal;
        internal int DoorSide;
        internal int ArrivalMs;
        internal int DepartureMs;
        internal int DefaultMs;
        internal int StoppageMs;
        internal double MarginMin;
        internal double MarginMax;
    }

    internal sealed class LegacyScenarioMeta
    {
        internal string Title;
        internal string RouteTitle;
        internal string VehicleTitle;
        internal string Author;
        internal string Comment;
    }

    /// <summary>Which of the three brake systems the vehicle uses. None = it could not be told.</summary>
    internal enum LegacyBrakeKind
    {
        None = 0,
        Ecb = 1,
        Smee = 2,
        Cl = 3
    }

    /// <summary>
    /// Who the current scenario instance is. IBveHacker.Scenario returns a NEW wrapper object on every access (Scenario.FromSource), so the wrapper is
    /// never the identity. The identity is Source: the original BVE Scenario object the wrapper holds (ClassWrapperBase.Src), which is the same object for
    /// the whole life of one loaded scenario and a different object once the scenario is loaded again.
    /// </summary>
    internal sealed class LegacyScenarioIdentity
    {
        /// <summary>Identity kind: the original BVE object behind the wrapper, compared by reference.</summary>
        internal const string KindSourceObject = "src-object";

        /// <summary>The original BVE Scenario object (ClassWrapperBase.Src). Compared by reference. Never null in a valid identity.</summary>
        internal object Source;

        /// <summary>The wrapper of this access. NOT an identity (a different object on every access); only carried so that the tests can prove it is ignored.</summary>
        internal object Wrapper;

        /// <summary>How Source was obtained (one of the Kind constants); written to the diagnostic log.</summary>
        internal string Kind;
    }

    internal interface ILegacyApi
    {
        /// <summary>IBveHacker.IsScenarioCreated. May throw; the caller treats an exception as "not created".</summary>
        bool IsScenarioCreated();

        /// <summary>
        /// The identity of the current scenario instance (see LegacyScenarioIdentity). false = it cannot be read now; nothing is sent then (no identity is guessed).
        /// </summary>
        bool TryScenarioIdentity(out LegacyScenarioIdentity identity);

        /// <summary>Scenario.TimeManager.TimeMilliseconds (ms since 0:00).</summary>
        bool TryTimeMs(out int timeMs);

        /// <summary>Scenario.LocationManager.Location (m).</summary>
        bool TryLocation(out double meters);

        /// <summary>Scenario.LocationManager.SpeedMeterPerSecond (m/s).</summary>
        bool TrySpeedMps(out double metersPerSecond);

        /// <summary>Scenario.Vehicle.Doors.AreAllClosed.</summary>
        bool TryDoorsClosed(out bool allClosed);

        /// <summary>Scenario.Route.MyTrack.Gradients.GetValueAt(location): the gradient as the map authored it (per mille).</summary>
        bool TryGradientPermille(double location, out double permille);

        /// <summary>Scenario.Route.Stations.Count (read every Tick; the stations themselves only when the list has to be built).</summary>
        bool TryStationCount(out int count);

        /// <summary>Scenario.Route.Stations (all of them, in route order). An empty list is a valid answer.</summary>
        bool TryStations(out IList<LegacyStationRaw> stations);

        /// <summary>Scenario.SectionManager.CurrentSectionSpeedLimit (m/s); infinity is a valid value (no limit).</summary>
        bool TrySignalLimitMps(out double metersPerSecond);

        /// <summary>Scenario.SectionManager.ForwardSectionSpeedLimit (m/s); infinity is a valid value.</summary>
        bool TryForwardSignalLimitMps(out double metersPerSecond);

        /// <summary>The Location of the first section boundary ahead of the given location (m); found=false when there is none ahead.</summary>
        bool TryNextSectionLocation(double location, out bool found, out double sectionLocation);

        /// <summary>Scenario.Route.SpeedLimits.CurrentLimit (m/s); infinity is a valid value (no limit).</summary>
        bool TryGroundLimitMps(out double metersPerSecond);

        bool TryBrakeKind(out LegacyBrakeKind kind);

        /// <summary>Handles.NotchInfo.BrakeNotchCount and HasHoldingSpeedBrake.</summary>
        bool TryBrakeNotches(out int brakeNotchCount, out bool hasHoldingSpeedBrake);

        /// <summary>The current brake controller's PressureRates (ratios) and MaximumPressure (Pa). rates is null/empty when the system has none.</summary>
        bool TryPressureRates(out double[] rates, out double maximumPressurePa);

        bool TryScenarioMeta(out LegacyScenarioMeta meta);
    }
}
