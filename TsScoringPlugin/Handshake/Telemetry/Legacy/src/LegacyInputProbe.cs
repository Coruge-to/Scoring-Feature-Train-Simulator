using System;
using System.Collections.Generic;
using System.Text;

// ============================================================================
// PHASE LI0 - AtsEX LEGACY scoring-input compatibility OBSERVATION (read only, diagnostic log only).
//
// Question: does the Legacy host give the same scoring inputs as the Current host (the handles, the brake / power notch layout, the brake cylinder /
// brake pipe pressure)? This probe only READS those candidates and writes a few fixed-format lines to the dedicated diagnostic log. It sends NOTHING
// to the telemetry stream (no REV, POW, BRK, ALLTXT, HTYPE, BCP, BPP, no AVAIL token), and it converts nothing into a display text or a score:
//   * a brake kind of Cl is only a word in the log;
//   * the emergency brake notch is read from the host (NotchInfo.EmergencyBrakeNotch), never derived from the brake notch count;
//   * the StateStore pressure arrays are logged as they are (length + the first few finite values); no element is chosen, no array is reduced to
//     the single value of the Current API.
//
// This file is host independent: the host API is reached only through ILegacyInputApi (implemented by the one adapter file, LegacyTelemetryExtension.cs).
// Threads: Begin / Observe / EndGeneration are called on the host's Tick thread only (Observe is the only caller of ILegacyInputApi). The heartbeat
// thread never reaches this class.
//
// Log rules: one scenario generation = one Begin..EndGeneration. Lines are written on the FIRST success of a group, on a SEMANTIC change (a handle
// position, a notch layout, a shape change, a pressure that doubled / halved), and once per unavailable reason. Hard caps per line kind and in total
// bound the output of a generation; what a cap swallowed is counted in the summary line. Only numbers, class names of the host's own wrappers and fixed
// words are written: no path, no vehicle / route / scenario text. A value that is NaN or Infinity is never "available".
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>How many levers the cab has (the runtime type of Vehicle.Instruments.Cab). Unknown = neither of the two known cab types.</summary>
    internal enum LegacyHandleType
    {
        Unknown = 0,
        OneLever = 1,
        TwoLever = 2
    }

    /// <summary>Fixed reason codes of "cannot be read". Nothing else is ever written as a reason (no exception text).</summary>
    internal static class LegacyInputReason
    {
        internal const string ScenarioNull = "scenario-null";
        internal const string VehicleNull = "vehicle-null";
        internal const string InstrumentsNull = "instruments-null";
        internal const string CabNull = "cab-null";
        internal const string HandlesNull = "handles-null";
        internal const string NativeNull = "native-null";
        internal const string SpecNull = "spec-null";
        internal const string StateNull = "state-null";
        internal const string PanelNull = "panel-null";
        internal const string StoreNull = "store-null";
        internal const string ArrayNull = "array-null";
        internal const string NonFinite = "nonfinite";
        internal const string SnapshotNull = "snapshot-null";
        internal const string ReadException = "read-exception";
    }

    /// <summary>The handles of the cab and the notch layout, as the Legacy wrappers give them. A null member = that one value could not be read.</summary>
    internal sealed class LegacyHandleSnapshot
    {
        internal string CabTypeName;                  // runtime class name of the cab (a wrapper class of the host); null = unreadable
        internal LegacyHandleType HandleType;
        internal LegacyBrakeKind BrakeKind;           // None = could not be told
        internal int? Reverser;                       // the raw value of HandleSet.ReverserPosition
        internal int? Power;                          // HandleSet.PowerNotch
        internal int? Brake;                          // HandleSet.BrakeNotch
        internal int? PowerNotchCount;
        internal int? BrakeNotchCount;
        internal int? EmergencyBrakeNotch;            // NotchInfo.EmergencyBrakeNotch as the host reports it (NEVER BrakeNotchCount + 1)
        internal bool? HasHoldingSpeedBrake;          // NotchInfo.HasHoldingSpeedBrake: the FIRST BRAKE position is the holding speed brake (NOT the independent holding speed notches)
        internal int? HoldingSpeedNotchCount;         // NotchInfo.HoldingSpeedNotchCount EXACTLY as the host reports it: the independent holding speed notches H1..Hn of a two-lever cab are -n (NOT HasHoldingSpeedBrake)
        internal int? B67Notch;
    }

    /// <summary>INative.VehicleSpec (static for a vehicle). A null member = that one value could not be read.</summary>
    internal sealed class LegacySpecSnapshot
    {
        internal int? BrakeNotches;
        internal int? PowerNotches;
        internal int? B67Notch;
    }

    /// <summary>INative.VehicleState pressures, UNCHANGED (single values, kPa according to the host's documentation).</summary>
    internal sealed class LegacyNativePressure
    {
        internal double Bc;
        internal double Bp;
    }

    /// <summary>Scenario.Vehicle.Panel.StateStore pressure arrays, UNCHANGED (the live arrays of the host; the probe only reads them and keeps no reference). An array may be null.</summary>
    internal sealed class LegacyStorePressure
    {
        internal double[] Bc;
        internal double[] Bp;
    }

    /// <summary>
    /// The read surface of the input observation. Contract of every Try method: true = something was read now (members may still be null where one value
    /// failed); false = nothing can be read, with a fixed reason from LegacyInputReason. May throw (the probe treats an exception as read-exception).
    /// All methods are called on the host's Tick thread only.
    /// </summary>
    internal interface ILegacyInputApi
    {
        /// <summary>Whether the adapter holds a reference to INative (PluginBase.Native); false = the native group cannot be observed at all.</summary>
        bool NativeReachable { get; }

        bool TryHandles(out LegacyHandleSnapshot snapshot, out string reason);

        bool TryNativeSpec(out LegacySpecSnapshot spec, out string reason);

        bool TryNativePressure(out LegacyNativePressure pressure, out string reason);

        bool TryStorePressure(out LegacyStorePressure pressure, out string reason);
    }

    internal sealed class LegacyInputProbe
    {
        // -- limits ------------------------------------------------------------------------------------------------------------------
        internal const int MaxLinesPerGeneration = 80;       // everything below included; one line is always kept for the summary
        internal const int RetryEveryTicks = 30;             // a group that could not be read is tried again only this often
        internal const int HeadCount = 3;                    // the first values of a StateStore array that are written

        internal const int CapCapability = 1;
        internal const int CapHandleFirst = 1;
        internal const int CapHandleChange = 36;
        internal const int CapSpecFirst = 1;
        internal const int CapSpecChange = 4;
        internal const int CapPressureFirst = 2;             // one per source (native, store)
        internal const int CapPressureChange = 24;
        internal const int CapUnavailable = 8;

        internal const string NameCapability = "TEL_INPUT_CAPABILITY";
        internal const string NameHandleFirst = "TEL_HANDLE_FIRST";
        internal const string NameHandleChange = "TEL_HANDLE_CHANGE";
        internal const string NameSpecFirst = "TEL_SPEC_FIRST";
        internal const string NameSpecChange = "TEL_SPEC_CHANGE";
        internal const string NamePressureFirst = "TEL_PRESSURE_FIRST";
        internal const string NamePressureChange = "TEL_PRESSURE_CHANGE";
        internal const string NameUnavailable = "TEL_INPUT_UNAVAILABLE";
        internal const string NameSummary = "TEL_INPUT_SUMMARY";

        private readonly ILegacyInputApi api;
        private readonly Action<string, string> log;

        // -- per generation (reset by Begin) -----------------------------------------------------------------------------------------
        private bool active;
        private bool summaryDone;
        private int generation;
        private int ticks;
        private bool capabilityDone;
        private int lines;
        private int suppressed;
        private int handleChangesSeen;
        private int pressureChangesSeen;
        private readonly Dictionary<string, int> perName = new Dictionary<string, int>();
        private readonly HashSet<string> unavailableLogged = new HashSet<string>();

        private int handlesRetryAt;
        private int specRetryAt;
        private int nativeRetryAt;
        private int storeRetryAt;

        private bool handlesSeen;
        private string lastStatic;
        private string lastDynamic;
        private bool specSeen;
        private string lastSpec;
        private bool nativeSeen;
        private double lastNativeBc;
        private double lastNativeBp;
        private bool storeSeen;
        private int lastBcLen;
        private int lastBpLen;
        private double[] lastBcHead;
        private double[] lastBpHead;

        internal LegacyInputProbe(ILegacyInputApi api, Action<string, string> log)
        {
            this.api = api;
            this.log = log;
        }

        // -- the classification of the cab (pure; the adapter hands over the runtime type) ----------------------------------------------
        /// <summary>One lever / two lever by the class name of the cab or of one of its base classes (OneLeverCab / TwoLeverCab). Anything else is Unknown.</summary>
        internal static LegacyHandleType ClassifyCabType(Type type)
        {
            for (Type t = type; t != null; t = t.BaseType)
            {
                if (t.Name == "OneLeverCab")
                {
                    return LegacyHandleType.OneLever;
                }

                if (t.Name == "TwoLeverCab")
                {
                    return LegacyHandleType.TwoLever;
                }
            }

            return LegacyHandleType.Unknown;
        }

        /// <summary>The class name for the log: letters, digits and underscore only, at most 40 characters; anything else is written as "other".</summary>
        internal static string SafeTypeName(Type type)
        {
            string name = type == null ? null : type.Name;
            if (string.IsNullOrEmpty(name) || name.Length > 40)
            {
                return "other";
            }

            for (int i = 0; i < name.Length; i++)
            {
                char c = name[i];
                if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'))
                {
                    return "other";
                }
            }

            return name;
        }

        // -- the generation --------------------------------------------------------------------------------------------------------
        /// <summary>A new scenario generation starts: every state of the previous one is dropped.</summary>
        internal void Begin(int scenarioId)
        {
            active = true;
            summaryDone = false;
            generation = scenarioId;
            ticks = 0;
            capabilityDone = false;
            lines = 0;
            suppressed = 0;
            handleChangesSeen = 0;
            pressureChangesSeen = 0;
            perName.Clear();
            unavailableLogged.Clear();
            handlesRetryAt = 0;
            specRetryAt = 0;
            nativeRetryAt = 0;
            storeRetryAt = 0;
            handlesSeen = false;
            lastStatic = null;
            lastDynamic = null;
            specSeen = false;
            lastSpec = null;
            nativeSeen = false;
            lastNativeBc = double.NaN;
            lastNativeBp = double.NaN;
            storeSeen = false;
            lastBcLen = -1;
            lastBpLen = -1;
            lastBcHead = null;
            lastBpHead = null;
        }

        /// <summary>The generation ends (scenario closed / reloaded / disposed): one summary line, then the probe is idle until the next Begin.</summary>
        internal void EndGeneration()
        {
            if (!active)
            {
                return;
            }

            active = false;
            if (summaryDone || ticks == 0)
            {
                return;
            }

            summaryDone = true;
            Write(NameSummary, "ticks=" + TelemetryContract.I(ticks) + " handleChanges=" + TelemetryContract.I(handleChangesSeen)
                + " pressureChanges=" + TelemetryContract.I(pressureChangesSeen) + " suppressed=" + TelemetryContract.I(suppressed)
                + " lines=" + TelemetryContract.I(lines + 1));
        }

        // -- the observation (Tick thread) ---------------------------------------------------------------------------------------------
        internal void Observe()
        {
            if (!active)
            {
                return;
            }

            ticks++;
            bool firstPass = !capabilityDone;

            LegacyHandleSnapshot handles = null;
            string handlesReason = null;
            bool handlesTried = firstPass || ticks >= handlesRetryAt;
            bool handlesOk = handlesTried && ReadHandles(out handles, out handlesReason);

            LegacySpecSnapshot spec = null;
            string specReason = null;
            bool specTried = firstPass || ticks >= specRetryAt;
            bool specOk = specTried && ReadSpec(out spec, out specReason);

            LegacyNativePressure native = null;
            string nativeReason = null;
            bool nativeTried = firstPass || ticks >= nativeRetryAt;
            bool nativeOk = nativeTried && ReadNative(out native, out nativeReason);

            LegacyStorePressure store = null;
            string storeReason = null;
            bool storeTried = firstPass || ticks >= storeRetryAt;
            bool storeOk = storeTried && ReadStore(out store, out storeReason);

            if (firstPass)
            {
                capabilityDone = true;
                bool nativeReachable = false;
                try { nativeReachable = api.NativeReachable; } catch { }
                Emit(NameCapability, CapCapability, "native=" + Flag(nativeReachable) + " handles=" + Flag(handlesOk) + " spec=" + Flag(specOk)
                    + " nativeState=" + Flag(nativeOk) + " store=" + Flag(storeOk));
            }

            if (handlesTried)
            {
                handlesRetryAt = handlesOk ? 0 : ticks + RetryEveryTicks;
                if (handlesOk) { ProcessHandles(handles); } else { ReportUnavailable("handles", handlesReason); }
            }

            if (specTried)
            {
                specRetryAt = specOk ? 0 : ticks + RetryEveryTicks;
                if (specOk) { ProcessSpec(spec); } else { ReportUnavailable("spec", specReason); }
            }

            if (nativeTried)
            {
                nativeRetryAt = nativeOk ? 0 : ticks + RetryEveryTicks;
                if (nativeOk) { ProcessNative(native); } else { ReportUnavailable("nativeState", nativeReason); }
            }

            if (storeTried)
            {
                storeRetryAt = storeOk ? 0 : ticks + RetryEveryTicks;
                if (storeOk) { ProcessStore(store); } else { ReportUnavailable("store", storeReason); }
            }
        }

        // -- reads (every exception becomes a fixed reason) --------------------------------------------------------------------------------
        private bool ReadHandles(out LegacyHandleSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (!api.TryHandles(out snapshot, out reason)) { snapshot = null; return Failed(ref reason); }
                if (snapshot == null) { reason = LegacyInputReason.SnapshotNull; return false; }
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        private bool ReadSpec(out LegacySpecSnapshot spec, out string reason)
        {
            spec = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (!api.TryNativeSpec(out spec, out reason)) { spec = null; return Failed(ref reason); }
                if (spec == null) { reason = LegacyInputReason.SnapshotNull; return false; }
                return true;
            }
            catch
            {
                spec = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        private bool ReadNative(out LegacyNativePressure pressure, out string reason)
        {
            pressure = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (!api.TryNativePressure(out pressure, out reason)) { pressure = null; return Failed(ref reason); }
                if (pressure == null) { reason = LegacyInputReason.SnapshotNull; return false; }
                return true;
            }
            catch
            {
                pressure = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        private bool ReadStore(out LegacyStorePressure pressure, out string reason)
        {
            pressure = null;
            reason = LegacyInputReason.ReadException;
            try
            {
                if (!api.TryStorePressure(out pressure, out reason)) { pressure = null; return Failed(ref reason); }
                if (pressure == null) { reason = LegacyInputReason.SnapshotNull; return false; }
                return true;
            }
            catch
            {
                pressure = null;
                reason = LegacyInputReason.ReadException;
                return false;
            }
        }

        private static bool Failed(ref string reason)
        {
            if (string.IsNullOrEmpty(reason))
            {
                reason = LegacyInputReason.ReadException;
            }

            return false;
        }

        // -- handles ----------------------------------------------------------------------------------------------------------------------
        private void ProcessHandles(LegacyHandleSnapshot h)
        {
            string stat = StaticText(h);
            string dyn = DynamicText(h);
            if (!handlesSeen)
            {
                handlesSeen = true;
                lastStatic = stat;
                lastDynamic = dyn;
                Emit(NameHandleFirst, CapHandleFirst, stat + " " + dyn);
                return;
            }

            if (stat != lastStatic)
            {
                lastStatic = stat;
                handleChangesSeen++;
                Emit(NameHandleChange, CapHandleChange, "what=layout " + stat);
            }

            if (dyn != lastDynamic)
            {
                lastDynamic = dyn;
                handleChangesSeen++;
                Emit(NameHandleChange, CapHandleChange, "what=position " + dyn);
            }
        }

        private static string StaticText(LegacyHandleSnapshot h)
        {
            return "cab=" + SafeToken(h.CabTypeName, "na") + " htype=" + HandleTypeText(h.HandleType) + " brake=" + BrakeText(h.BrakeKind)
                + " combo=" + ComboText(h.HandleType, h.BrakeKind)
                + " powN=" + Num(h.PowerNotchCount) + " brkN=" + Num(h.BrakeNotchCount) + " ebN=" + Num(h.EmergencyBrakeNotch)
                + " hold=" + Num(h.HasHoldingSpeedBrake) + " b67=" + Num(h.B67Notch)
                + " holdN=" + (h.HoldingSpeedNotchCount.HasValue ? TelemetryContract.I(h.HoldingSpeedNotchCount.Value) : "missing") + " holdBrake=" + Num(h.HasHoldingSpeedBrake)
                + " holdSource=" + LegacyHandleContract.HoldSource + " holdValidity=" + LegacyHandleContract.HoldValidity(h.HoldingSpeedNotchCount);
        }

        private static string DynamicText(LegacyHandleSnapshot h)
        {
            return "rev=" + Num(h.Reverser) + " pow=" + Num(h.Power) + " brk=" + Num(h.Brake);
        }

        internal static string HandleTypeText(LegacyHandleType t)
        {
            return t == LegacyHandleType.OneLever ? "one-lever" : t == LegacyHandleType.TwoLever ? "two-lever" : "unknown";
        }

        internal static string BrakeText(LegacyBrakeKind k)
        {
            return k == LegacyBrakeKind.Ecb ? "Ecb" : k == LegacyBrakeKind.Smee ? "Smee" : k == LegacyBrakeKind.Cl ? "Cl" : "unknown";
        }

        /// <summary>Observation only: a one-lever cab with a Cl brake is outside the supported set. Nothing is displayed or scored from it.</summary>
        internal static string ComboText(LegacyHandleType t, LegacyBrakeKind k)
        {
            if (t == LegacyHandleType.Unknown || k == LegacyBrakeKind.None)
            {
                return "unknown";
            }

            return t == LegacyHandleType.OneLever && k == LegacyBrakeKind.Cl ? "unexpected" : "supported";
        }

        // -- spec -------------------------------------------------------------------------------------------------------------------------
        private void ProcessSpec(LegacySpecSnapshot s)
        {
            string text = "powN=" + Num(s.PowerNotches) + " brkN=" + Num(s.BrakeNotches) + " b67=" + Num(s.B67Notch);
            if (!specSeen)
            {
                specSeen = true;
                lastSpec = text;
                Emit(NameSpecFirst, CapSpecFirst, text);
            }
            else if (text != lastSpec)
            {
                lastSpec = text;
                Emit(NameSpecChange, CapSpecChange, text);
            }
        }

        // -- pressure: native (single values) ----------------------------------------------------------------------------------------------
        /// <summary>When neither value is finite the group is reported as unavailable (nonfinite) and stays "not seen".</summary>
        private void ProcessNative(LegacyNativePressure p)
        {
            bool bcOk = TelemetryContract.Finite(p.Bc);
            bool bpOk = TelemetryContract.Finite(p.Bp);
            if (!bcOk && !bpOk)
            {
                ReportUnavailable("nativeState", LegacyInputReason.NonFinite);
                return;
            }

            double bc = bcOk ? p.Bc : double.NaN;
            double bp = bpOk ? p.Bp : double.NaN;
            string text = "src=native bc=" + ValueText(bc) + " bp=" + ValueText(bp);
            if (!nativeSeen)
            {
                nativeSeen = true;
                lastNativeBc = bc;
                lastNativeBp = bp;
                Emit(NamePressureFirst, CapPressureFirst, text);
                return;
            }

            if (Moved(bc, lastNativeBc) || Moved(bp, lastNativeBp))
            {
                lastNativeBc = bc;
                lastNativeBp = bp;
                pressureChangesSeen++;
                Emit(NamePressureChange, CapPressureChange, text);
            }
        }

        // -- pressure: StateStore arrays (never reduced to one value, no element chosen) -----------------------------------------------------
        private void ProcessStore(LegacyStorePressure p)
        {
            int bcLen = p.Bc == null ? -1 : p.Bc.Length;
            int bpLen = p.Bp == null ? -1 : p.Bp.Length;
            double[] bcHead = HeadOf(p.Bc);
            double[] bpHead = HeadOf(p.Bp);
            string text = "src=store bcN=" + LengthText(bcLen) + " bcHead=" + HeadText(p.Bc) + " bpN=" + LengthText(bpLen) + " bpHead=" + HeadText(p.Bp);
            if (!storeSeen)
            {
                storeSeen = true;
                Remember(bcLen, bpLen, bcHead, bpHead);
                Emit(NamePressureFirst, CapPressureFirst, text);
                return;
            }

            if (bcLen != lastBcLen || bpLen != lastBpLen || HeadMoved(bcHead, lastBcHead) || HeadMoved(bpHead, lastBpHead))
            {
                Remember(bcLen, bpLen, bcHead, bpHead);
                pressureChangesSeen++;
                Emit(NamePressureChange, CapPressureChange, text);
            }
        }

        private void Remember(int bcLen, int bpLen, double[] bcHead, double[] bpHead)
        {
            lastBcLen = bcLen;
            lastBpLen = bpLen;
            lastBcHead = bcHead;
            lastBpHead = bpHead;
        }

        private static double[] HeadOf(double[] a)
        {
            double[] head = new double[HeadCount];
            for (int i = 0; i < HeadCount; i++)
            {
                head[i] = (a != null && i < a.Length && TelemetryContract.Finite(a[i])) ? a[i] : double.NaN;
            }

            return head;
        }

        private static bool HeadMoved(double[] current, double[] reference)
        {
            for (int i = 0; i < HeadCount; i++)
            {
                if (Moved(current[i], reference[i]))
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>
        /// A "semantic" change of a pressure: it became (un)available, or it moved by at least half of the larger of the two values (so it roughly doubled or halved;
        /// the larger value counts as at least 1, which makes 0.5 the smallest step). The unit of the StateStore arrays is not known, so no unit-bound threshold is used;
        /// a continuous ramp therefore writes a handful of lines, not one per Tick. The comparison is symmetric: rising and falling are judged alike.
        /// </summary>
        internal static bool Moved(double current, double reference)
        {
            bool currentOk = !double.IsNaN(current);
            bool referenceOk = !double.IsNaN(reference);
            if (currentOk != referenceOk)
            {
                return true;
            }

            if (!currentOk)
            {
                return false;
            }

            return Math.Abs(current - reference) >= 0.5 * Math.Max(Math.Max(Math.Abs(current), Math.Abs(reference)), 1.0);
        }

        private static string LengthText(int length)
        {
            return length < 0 ? "na" : TelemetryContract.I(length);
        }

        /// <summary>The first HeadCount values of the array: a finite number as it is, anything else as x. na = no array, - = an empty array.</summary>
        internal static string HeadText(double[] a)
        {
            if (a == null)
            {
                return "na";
            }

            if (a.Length == 0)
            {
                return "-";
            }

            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < a.Length && i < HeadCount; i++)
            {
                if (i > 0)
                {
                    sb.Append('_');
                }

                sb.Append(TelemetryContract.Finite(a[i]) ? TelemetryContract.D(a[i]) : "x");
            }

            return sb.ToString();
        }

        private static string ValueText(double v)
        {
            return double.IsNaN(v) ? "x" : TelemetryContract.D(v);
        }

        // -- writing ----------------------------------------------------------------------------------------------------------------------
        private void ReportUnavailable(string group, string reason)
        {
            string r = SafeToken(reason, LegacyInputReason.ReadException);
            if (unavailableLogged.Add(group + ":" + r))
            {
                Emit(NameUnavailable, CapUnavailable, "group=" + group + " reason=" + r);
            }
        }

        /// <summary>A line subject to the per-kind cap and the total cap (one line stays free for the summary). A swallowed line is only counted.</summary>
        private void Emit(string name, int cap, string detail)
        {
            int used;
            perName.TryGetValue(name, out used);
            if (used >= cap || lines >= MaxLinesPerGeneration - 1)
            {
                suppressed++;
                return;
            }

            perName[name] = used + 1;
            lines++;
            Write(name, detail);
        }

        private void Write(string name, string detail)
        {
            try
            {
                if (log != null)
                {
                    log(name, "gen=" + TelemetryContract.I(generation) + " " + detail);
                }
            }
            catch
            {
                // a diagnostic can never affect the telemetry or BVE
            }
        }

        private static string Flag(bool value)
        {
            return value ? "1" : "0";
        }

        private static string Num(int? value)
        {
            return value.HasValue ? TelemetryContract.I(value.Value) : "na";
        }

        private static string Num(bool? value)
        {
            return value.HasValue ? (value.Value ? "1" : "0") : "na";
        }

        /// <summary>Letters, digits, underscore and hyphen only (at most 40 characters); anything else (or empty) becomes the fallback.</summary>
        private static string SafeToken(string text, string fallback)
        {
            if (string.IsNullOrEmpty(text) || text.Length > 40)
            {
                return fallback;
            }

            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
                {
                    return fallback;
                }
            }

            return text;
        }
    }
}
