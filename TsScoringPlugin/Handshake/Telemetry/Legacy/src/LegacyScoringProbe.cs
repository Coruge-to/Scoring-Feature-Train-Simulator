using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE SI-0 - AtsEX LEGACY scoring-integration OBSERVATION (read only, diagnostic log only).
//
// Questions this observation answers on the real machine, before any scoring is wired to the Legacy host:
//   O-A  Can the public Legacy API give the brake pipe pressure of a released brake (BpInitialPressure of Smee / Cl)? Raw value, kPa, missing, which way.
//   O-B  Is there ONE public way to the vehicle length (the TRAINLEN of the Current sender)? Candidate values, units, stability over scenario generations.
//   O-C  Can the public Legacy API give the ground speed limit LIST (the MAPLIMITS / CLEARDIST data of the Current sender), and does the host's current limit
//        follow the HEAD or the TAIL of the train?
//   O-D  In which ORDER do the host events, the first Tick, the heartbeat (running / paused) and the first telemetry line of a scenario instance happen?
//        (The Ready / ScenarioReady side of that order lives in the control plane's own log; both logs carry wall clock times.)
//
// This file only READS and writes a few fixed-format lines to the dedicated diagnostic log. It sends NOTHING to the telemetry stream (no key, no AVAIL token),
// converts nothing into a score, a display text or a decision, and calls no method of the host that changes anything (no jump, no time change, no position change).
// The jump methods of the host (O-E) are NOT called anywhere: their metadata is audited offline (see the SI-0 documents).
//
// Host independence: the host is reached only through ILegacyScoringApi (implemented by the one adapter file, LegacyTelemetryExtension.cs).
// Threads: LegacyScoringProbe is used on the host's Tick thread only (the only caller of ILegacyScoringApi). LegacyOrderRecorder.Note may be called from
// any thread (it touches no host object: a counter, a clock and the diagnostic log); the heartbeat thread uses it for its two status words only.
//
// Log rules: one scenario generation = one Begin..EndGeneration. Lines are written on the FIRST success of a group, on a SEMANTIC change, and once per
// unavailable reason. Hard caps per line kind and in total bound the output of a generation and of the process. Only numbers, class names of the host's own
// wrappers and fixed words are written: no path, no vehicle / route / scenario / station text. NaN and Infinity are never written as numbers.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>Fixed reason codes of "cannot be read". Nothing else is ever written as a reason (no exception text).</summary>
    internal static class LegacyScoringReason
    {
        internal const string ScenarioNull = "scenario-null";
        internal const string VehicleNull = "vehicle-null";
        internal const string InstrumentsNull = "instruments-null";
        internal const string BrakeSystemNull = "brakesystem-null";
        internal const string ControllerNull = "controller-null";
        internal const string DynamicsNull = "dynamics-null";
        internal const string RouteNull = "route-null";
        internal const string LimitsNull = "limits-null";
        internal const string ElementNull = "element-null";
        internal const string IndexRange = "index-range";
        internal const string NotApplicable = "not-applicable";
        internal const string NonFinite = "nonfinite";
        internal const string ReadException = "read-exception";
    }

    /// <summary>The brake pipe pressure of a released brake, as the host gives it (Pa). A null member = that one value could not be read.</summary>
    internal sealed class LegacyBpInitialSnapshot
    {
        internal LegacyBrakeKind ActiveKind;       // the runtime kind of Vehicle.Instruments.BrakeSystem.BrakeController; None = could not be told
        internal double? ControllerRawPa;          // BpInitialPressure of the ACTIVE controller (only a Smee or a Cl has it), unchanged
        internal string ControllerReason;          // fixed word: why ControllerRawPa is null
        internal bool SmeePropertyPresent;         // BrakeSystem.Smee was not null (the route the Current sender takes)
        internal double? SmeePropertyRawPa;
        internal bool ClPropertyPresent;           // BrakeSystem.Cl was not null
        internal double? ClPropertyRawPa;
    }

    /// <summary>The numbers a vehicle length could be derived from. All unchanged, each null = could not be read. Nothing here is a decision.</summary>
    internal sealed class LegacyVehicleLengthSnapshot
    {
        internal double? CarLength;                // VehicleDynamics.CarLength: the length of ONE car [m]
        internal double? FirstCount;               // VehicleDynamics.FirstCar.Count
        internal double? MotorCount;               // VehicleDynamics.MotorCar.Count
        internal double? TrailerCount;             // VehicleDynamics.TrailerCar.Count
    }

    /// <summary>One element of the ground speed limit list: where it starts and its value (m/s, unchanged). IsValueNode = the host gave a value carrying wrapper.</summary>
    internal sealed class LegacyLimitElement
    {
        internal double Location;
        internal double Value;
        internal bool IsValueNode;
        internal string TypeName;                  // a LegacyScoringProbe.TypeWord
    }

    /// <summary>
    /// The read surface of the scoring observation. Contract of every Try method: true = it was read now; false = it cannot be read, with a fixed reason from
    /// LegacyScoringReason. May throw (the probe treats an exception as read-exception). All members are called on the host's Tick thread only.
    /// </summary>
    internal interface ILegacyScoringApi
    {
        /// <summary>The version of the host's wrapper library, as a plain version text; "na" when it cannot be read.</summary>
        string HostTypesVersion { get; }

        bool TryBpInitial(out LegacyBpInitialSnapshot snapshot, out string reason);

        bool TryVehicleLength(out LegacyVehicleLengthSnapshot snapshot, out string reason);

        /// <summary>The number of elements of Scenario.Route.SpeedLimits (the list the Current sender walks for MAPLIMITS).</summary>
        bool TryLimitCount(out int count, out string reason);

        bool TryLimitElement(int index, out LegacyLimitElement element, out string reason);
    }

    /// <summary>
    /// The order in which things happen, as numbered fixed-word lines: SI0_ORDER seq=N t=ms th=thread ev=word key=value ... "seq" is the true order (it is taken
    /// before the line is written, so lines of two threads may appear in the file in another order than their seq); "t" is the monotonic milliseconds of the
    /// sender; "th" the managed thread id. The recorder touches no host object and is safe to call from any thread.
    /// </summary>
    internal sealed class LegacyOrderRecorder
    {
        internal const string Name = "SI0_ORDER";
        internal const int MaxLinesPerProcess = 400;
        internal const int MaxPerWord = 60;

        private readonly Func<long> nowMs;
        private readonly Action<string, string> log;
        private readonly object gate = new object();
        private readonly Dictionary<string, int> perWord = new Dictionary<string, int>();
        private int seq;
        private int lines;
        private int suppressed;

        internal LegacyOrderRecorder(Func<long> nowMs, Action<string, string> log)
        {
            this.nowMs = nowMs;
            this.log = log;
        }

        internal int Suppressed
        {
            get { lock (gate) { return suppressed; } }
        }

        internal int Lines
        {
            get { lock (gate) { return lines; } }
        }

        internal void Note(string word, string detail)
        {
            try
            {
                int number = Interlocked.Increment(ref seq);
                long t = nowMs();
                bool write;
                lock (gate)
                {
                    int used;
                    perWord.TryGetValue(word, out used);
                    if (used >= MaxPerWord || lines >= MaxLinesPerProcess)
                    {
                        suppressed++;
                        write = false;
                    }
                    else
                    {
                        perWord[word] = used + 1;
                        lines++;
                        write = true;
                    }
                }

                if (!write || log == null)
                {
                    return;
                }

                log(Name, "seq=" + TelemetryContract.I(number) + " t=" + TelemetryContract.D((double)t) + " th=" + TelemetryContract.I(Thread.CurrentThread.ManagedThreadId)
                    + " ev=" + word + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail));
            }
            catch
            {
                // a diagnostic can never affect the telemetry or BVE
            }
        }
    }

    internal sealed class LegacyScoringProbe
    {
        // -- limits ------------------------------------------------------------------------------------------------------------------
        internal const int MaxLinesPerGeneration = 64;       // everything below included; one line is always kept for the summary
        internal const int RetryEveryTicks = 30;             // a group that could not be read is tried again only this often
        internal const int RecheckEveryTicks = 30;           // a group that was read is looked at again this often (other plugins may change a vehicle value)
        internal const int ScanPerTick = 400;                // elements of the limit list read per Tick (the list is walked in slices, never in one frame)
        internal const int MaxScanElements = 5000;
        internal const double AheadWindowMeters = 3000.0;    // the look-ahead of the Current sender's MAPLIMITS
        internal const double DeltaTolerance = 0.001;        // km/h: two limit values closer than this are the same value

        internal const int CapCapability = 1;
        internal const int CapBpFirst = 1;
        internal const int CapBpChange = 4;
        internal const int CapVehFirst = 1;
        internal const int CapVehChange = 4;
        internal const int CapList = 1;
        internal const int CapAhead = 1;
        internal const int CapLimitChange = 24;
        internal const int CapUnavailable = 8;

        internal const string NameCapability = "SI0_CAPABILITY";
        internal const string NameBpFirst = "SI0_BPINIT_FIRST";
        internal const string NameBpChange = "SI0_BPINIT_CHANGE";
        internal const string NameVehFirst = "SI0_VEHLEN_FIRST";
        internal const string NameVehChange = "SI0_VEHLEN_CHANGE";
        internal const string NameList = "SI0_LIMITS_LIST";
        internal const string NameAhead = "SI0_LIMITS_AHEAD";
        internal const string NameLimitChange = "SI0_LIMIT_CHANGE";
        internal const string NameUnavailable = "SI0_UNAVAILABLE";
        internal const string NameSummary = "SI0_SUMMARY";

        private readonly ILegacyScoringApi api;
        private readonly Action<string, string> log;

        // -- per generation (reset by Begin) -----------------------------------------------------------------------------------------
        private bool active;
        private bool summaryDone;
        private int generation;
        private int ticks;
        private bool capabilityDone;
        private int lines;
        private int suppressed;
        private readonly Dictionary<string, int> perName = new Dictionary<string, int>();
        private readonly HashSet<string> unavailableLogged = new HashSet<string>();

        private int bpRetryAt;
        private int vehRetryAt;
        private int listRetryAt;
        private bool bpSeen;
        private string lastBpState;
        private double? bpInitKpa;
        private bool bpNowSeen;
        private double bpNowMax;
        private bool vehSeen;
        private string lastVehState;
        private double? candTotal;
        private double? candMotorTrailer;

        private bool listSeen;
        private int listCount;
        private int scanned;
        private int valueNodes;
        private int otherNodes;
        private int readFail;
        private bool sorted;
        private bool listFinished;
        private string pendingList;                // the finished list line, written after the capability line of the same Tick
        private long scanTicks;
        private string firstType;
        private readonly List<double> limitLoc = new List<double>();
        private readonly List<double> limitKmh = new List<double>();
        private readonly StringBuilder firstText = new StringBuilder();
        private int firstTextCount;

        private bool aheadDone;
        private bool groundSeen;
        private double lastGroundKmh;
        private int limitChanges;

        // -- kept across generations: the comparison with the previous generation's vehicle numbers ("is it stable?") ------------------------------
        private string previousVehNumbers;

        internal LegacyScoringProbe(ILegacyScoringApi api, Action<string, string> log)
        {
            this.api = api;
            this.log = log;
        }

        // -- pure helpers (tested directly) -------------------------------------------------------------------------------------------------
        /// <summary>A class name for the log: letters, digits and underscore only (a generic marker ` becomes _), at most 40 characters; anything else is "other".</summary>
        internal static string TypeWord(Type type)
        {
            string name = type == null ? null : type.Name;
            if (string.IsNullOrEmpty(name) || name.Length > 40)
            {
                return "other";
            }

            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < name.Length; i++)
            {
                char c = name[i];
                if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')
                {
                    sb.Append(c);
                }
                else if (c == '`')
                {
                    sb.Append('_');
                }
                else
                {
                    return "other";
                }
            }

            return sb.ToString();
        }

        /// <summary>A number for the log in fixed notation (no exponent, no plus sign). NaN / Infinity are x, absurdly large values are big.</summary>
        internal static string Num(double v)
        {
            if (!TelemetryContract.Finite(v))
            {
                return "x";
            }

            if (Math.Abs(v) > 1e12)
            {
                return "big";
            }

            return TelemetryContract.F(v, "0.######");
        }

        internal static string Num(double? v)
        {
            return v.HasValue ? Num(v.Value) : "na";
        }

        /// <summary>Letters, digits, underscore and hyphen only (at most 40 characters); anything else (or empty) becomes the fallback.</summary>
        internal static string SafeWord(string text, string fallback)
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

        /// <summary>
        /// The present brake pipe pressure (kPa) as the telemetry takes it: the single value of the state store array (the shared per-Tick read of the input surface,
        /// no second host call). null when there is no input surface, no array, or not exactly one finite element. Only used to put the bp_initial candidate next to
        /// what the pipe really reads; it is never an estimate of bp_initial.
        /// </summary>
        internal static double? PresentBpKpa(ILegacyInputApi input)
        {
            try
            {
                LegacyStorePressure store;
                string storeReason;
                if (input != null && input.TryStorePressure(out store, out storeReason) && store != null)
                {
                    double kpa;
                    string reason;
                    int length;
                    if (LegacyPressureContract.TryValue(store.Bp, out kpa, out reason, out length))
                    {
                        return kpa;
                    }
                }
            }
            catch
            {
            }

            return null;
        }

        /// <summary>A version text for the log: digits and dots only (at most 24 characters); anything else is "na".</summary>
        internal static string SafeVersion(string text)
        {
            if (string.IsNullOrEmpty(text) || text.Length > 24)
            {
                return "na";
            }

            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (!((c >= '0' && c <= '9') || c == '.'))
                {
                    return "na";
                }
            }

            return text;
        }

        /// <summary>
        /// The two limits the Current sender derives from the list (Class1.cs, MAPHEAD / MAPTAIL): the value in force at the head of the train, and the lowest value
        /// anywhere between the tail and the head. Same walk, same sentinels (1000 = no limit), same order dependence (the last element at or before a location wins).
        /// Values are km/h of the contract.
        /// </summary>
        internal static void HeadTail(double location, double trainLength, IList<double> locs, IList<double> kmh, out double head, out double tail)
        {
            double tailLoc = location - trainLength;
            double limitAtTail = TelemetryContract.NoLimitKmh;
            double limitAtHead = TelemetryContract.NoLimitKmh;
            int n = locs.Count;
            for (int i = 0; i < n; i++)
            {
                if (locs[i] <= tailLoc)
                {
                    limitAtTail = kmh[i];
                }

                if (locs[i] <= location)
                {
                    limitAtHead = kmh[i];
                }
            }

            double minOccupied = limitAtTail;
            for (int i = 0; i < n; i++)
            {
                if (locs[i] > tailLoc && locs[i] <= location && kmh[i] < minOccupied)
                {
                    minOccupied = kmh[i];
                }
            }

            head = limitAtHead;
            tail = minOccupied;
        }

        /// <summary>The list entries ahead of the location within the look-ahead, in the notation of the Current sender's MAPLIMITS (location F1 = limit F1). Count and a sample of the first three.</summary>
        internal static int Ahead(double location, IList<double> locs, IList<double> kmh, out string sample)
        {
            int count = 0;
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < locs.Count; i++)
            {
                if (locs[i] > location && locs[i] <= location + AheadWindowMeters)
                {
                    if (count < 3)
                    {
                        if (count > 0)
                        {
                            sb.Append('_');
                        }

                        sb.Append('L').Append(TelemetryContract.F(locs[i], "F1")).Append('V').Append(TelemetryContract.F(kmh[i], "F1"));
                    }

                    count++;
                }
            }

            sample = count == 0 ? "-" : sb.ToString();
            return count;
        }

        // -- the generation --------------------------------------------------------------------------------------------------------
        /// <summary>A new scenario generation starts: every state of the previous one is dropped (only the previous vehicle numbers stay, for the stability comparison).</summary>
        internal void Begin(int scenarioId)
        {
            active = true;
            summaryDone = false;
            generation = scenarioId;
            ticks = 0;
            capabilityDone = false;
            lines = 0;
            suppressed = 0;
            perName.Clear();
            unavailableLogged.Clear();
            bpRetryAt = 0;
            vehRetryAt = 0;
            listRetryAt = 0;
            bpSeen = false;
            lastBpState = null;
            bpInitKpa = null;
            bpNowSeen = false;
            bpNowMax = 0.0;
            vehSeen = false;
            lastVehState = null;
            candTotal = null;
            candMotorTrailer = null;
            listSeen = false;
            listCount = 0;
            scanned = 0;
            valueNodes = 0;
            otherNodes = 0;
            readFail = 0;
            sorted = true;
            listFinished = false;
            pendingList = null;
            scanTicks = 0;
            firstType = null;
            limitLoc.Clear();
            limitKmh.Clear();
            firstText.Length = 0;
            firstTextCount = 0;
            aheadDone = false;
            groundSeen = false;
            lastGroundKmh = 0.0;
            limitChanges = 0;
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
            Write(NameSummary, "ticks=" + TelemetryContract.I(ticks) + " bpInit=" + (bpSeen ? "seen" : "none") + " vehLen=" + (vehSeen ? "seen" : "none")
                + " limitList=" + (listFinished ? "seen" : listSeen ? "partial" : "none") + " limitChanges=" + TelemetryContract.I(limitChanges)
                + " bpInitKpa=" + Num(bpInitKpa) + " bpNowMaxKpa=" + (bpNowSeen ? Num(bpNowMax) : "na")
                + " suppressed=" + TelemetryContract.I(suppressed) + " lines=" + TelemetryContract.I(lines + 1));
        }

        // -- the observation (Tick thread) ---------------------------------------------------------------------------------------------
        /// <summary>
        /// coreOk = the Tick has a valid location (the telemetry core could read time, position and speed); location is meaningless otherwise.
        /// groundMps = the host's current ground limit this Tick as the telemetry reads it (m/s, infinity = no limit), null when it could not be read.
        /// bpNowKpa = the present brake pipe pressure (the single value of the state store, kPa), null when the telemetry could not take it.
        /// </summary>
        internal void Observe(bool coreOk, double location, double? groundMps, double? bpNowKpa)
        {
            if (!active)
            {
                return;
            }

            ticks++;
            if (bpNowKpa.HasValue && TelemetryContract.Finite(bpNowKpa.Value) && (!bpNowSeen || bpNowKpa.Value > bpNowMax))
            {
                bpNowSeen = true;
                bpNowMax = bpNowKpa.Value;
            }

            bool firstPass = !capabilityDone;

            LegacyBpInitialSnapshot bp = null;
            string bpReason = null;
            bool bpTried = Due(bpSeen, bpRetryAt, firstPass);
            bool bpOk = bpTried && ReadBp(out bp, out bpReason);

            LegacyVehicleLengthSnapshot veh = null;
            string vehReason = null;
            bool vehTried = Due(vehSeen, vehRetryAt, firstPass);
            bool vehOk = vehTried && ReadVeh(out veh, out vehReason);

            string listReason = null;
            bool listTried = !listFinished && (firstPass || listSeen || ticks >= listRetryAt);
            bool listOk = listTried && ScanSlice(out listReason);

            if (firstPass)
            {
                capabilityDone = true;
                string version = "na";
                try { version = SafeVersion(api.HostTypesVersion); } catch { }
                Emit(NameCapability, CapCapability, "bpInit=" + Flag(bpOk) + " vehLen=" + Flag(vehOk) + " limitList=" + Flag(listOk) + " hostTypes=" + version);
            }

            if (pendingList != null)
            {
                string text = pendingList;
                pendingList = null;
                Emit(NameList, CapList, text);
            }

            if (bpTried)
            {
                bpRetryAt = bpOk ? 0 : ticks + RetryEveryTicks;
                if (bpOk) { ProcessBp(bp, bpNowKpa); } else { ReportUnavailable("bpInit", bpReason); }
            }

            if (vehTried)
            {
                vehRetryAt = vehOk ? 0 : ticks + RetryEveryTicks;
                if (vehOk) { ProcessVeh(veh); } else { ReportUnavailable("vehLen", vehReason); }
            }

            if (listTried)
            {
                if (listOk) { listRetryAt = 0; } else { listRetryAt = ticks + RetryEveryTicks; ReportUnavailable("limitList", listReason); }
            }

            if (coreOk && TelemetryContract.Finite(location))
            {
                ProcessLimits(location, groundMps);
            }
        }

        private bool Due(bool seen, int retryAt, bool firstPass)
        {
            if (firstPass)
            {
                return true;
            }

            return seen ? (ticks % RecheckEveryTicks == 0) : ticks >= retryAt;
        }

        // -- reads (every exception becomes a fixed reason) --------------------------------------------------------------------------------
        private bool ReadBp(out LegacyBpInitialSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                if (!api.TryBpInitial(out snapshot, out reason)) { snapshot = null; return Failed(ref reason); }
                if (snapshot == null) { reason = LegacyScoringReason.ReadException; return false; }
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        private bool ReadVeh(out LegacyVehicleLengthSnapshot snapshot, out string reason)
        {
            snapshot = null;
            reason = LegacyScoringReason.ReadException;
            try
            {
                if (!api.TryVehicleLength(out snapshot, out reason)) { snapshot = null; return Failed(ref reason); }
                if (snapshot == null) { reason = LegacyScoringReason.ReadException; return false; }
                return true;
            }
            catch
            {
                snapshot = null;
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        private static bool Failed(ref string reason)
        {
            if (string.IsNullOrEmpty(reason))
            {
                reason = LegacyScoringReason.ReadException;
            }

            return false;
        }

        // -- O-A: the brake pipe pressure of a released brake ---------------------------------------------------------------------------------
        private void ProcessBp(LegacyBpInitialSnapshot s, double? bpNowKpa)
        {
            string status;
            string method;
            double? kpa = null;
            string reasonPart = string.Empty;
            if (s.ActiveKind == LegacyBrakeKind.Smee || s.ActiveKind == LegacyBrakeKind.Cl)
            {
                method = s.ActiveKind == LegacyBrakeKind.Smee ? "controller-smee" : "controller-cl";
                if (s.ControllerRawPa.HasValue)
                {
                    if (TelemetryContract.Finite(s.ControllerRawPa.Value))
                    {
                        status = "ok";
                        kpa = s.ControllerRawPa.Value / 1000.0;
                    }
                    else
                    {
                        status = LegacyScoringReason.NonFinite;
                    }
                }
                else
                {
                    status = "unreadable";
                    reasonPart = " reason=" + SafeWord(s.ControllerReason, LegacyScoringReason.ReadException);
                }
            }
            else if (s.ActiveKind == LegacyBrakeKind.Ecb)
            {
                method = "none";
                status = LegacyScoringReason.NotApplicable;      // an Ecb has no BpInitialPressure: out of scope for bp_initial
            }
            else
            {
                method = "none";
                status = "kind-unknown";
            }

            string raw = s.ControllerRawPa.HasValue ? Num(s.ControllerRawPa.Value) : "na";
            string state = "kind=" + LegacyInputProbe.BrakeText(s.ActiveKind) + " status=" + status + reasonPart + " rawPa=" + raw + " kPa=" + Num(kpa)
                + " method=" + method + " smeeProp=" + PropText(s.SmeePropertyPresent, s.SmeePropertyRawPa) + " clProp=" + PropText(s.ClPropertyPresent, s.ClPropertyRawPa);
            if (kpa.HasValue)
            {
                bpInitKpa = kpa;
            }

            if (!bpSeen)
            {
                bpSeen = true;
                lastBpState = state;
                Emit(NameBpFirst, CapBpFirst, state + " bpNowKpa=" + (bpNowKpa.HasValue && TelemetryContract.Finite(bpNowKpa.Value) ? Num(bpNowKpa.Value) : "na"));
            }
            else if (state != lastBpState)
            {
                lastBpState = state;
                Emit(NameBpChange, CapBpChange, state);
            }
        }

        private static string PropText(bool present, double? raw)
        {
            if (!present)
            {
                return "null";
            }

            return raw.HasValue && TelemetryContract.Finite(raw.Value) ? Num(raw.Value) : "x";
        }

        // -- O-B: the numbers a vehicle length could come from --------------------------------------------------------------------------------
        private void ProcessVeh(LegacyVehicleLengthSnapshot v)
        {
            double? carLen = Clean(v.CarLength);
            double? first = Clean(v.FirstCount);
            double? motor = Clean(v.MotorCount);
            double? trailer = Clean(v.TrailerCount);
            candTotal = null;
            candMotorTrailer = null;
            if (carLen.HasValue && carLen.Value > 0.0)
            {
                if (first.HasValue && motor.HasValue && trailer.HasValue)
                {
                    candTotal = carLen.Value * (first.Value + motor.Value + trailer.Value);
                }

                if (motor.HasValue && trailer.HasValue)
                {
                    candMotorTrailer = carLen.Value * (motor.Value + trailer.Value);
                }
            }

            string numbers = "carLenM=" + Num(carLen) + " first=" + Num(first) + " motor=" + Num(motor) + " trailer=" + Num(trailer);
            string state = numbers + " candTotalM=" + Num(candTotal) + " candMotorTrailerM=" + Num(candMotorTrailer);
            if (!vehSeen)
            {
                vehSeen = true;
                lastVehState = state;
                string same = previousVehNumbers == null ? "na" : (previousVehNumbers == numbers ? "1" : "0");
                previousVehNumbers = numbers;
                Emit(NameVehFirst, CapVehFirst, state + " sameAsPrevGen=" + same);
            }
            else if (state != lastVehState)
            {
                lastVehState = state;
                previousVehNumbers = numbers;
                Emit(NameVehChange, CapVehChange, state);
            }
        }

        private static double? Clean(double? v)
        {
            return v.HasValue && TelemetryContract.Finite(v.Value) ? v : null;
        }

        // -- O-C: the ground limit list ---------------------------------------------------------------------------------------------------------
        /// <summary>Reads the next slice of the list (the count first). true = the count is known (the walk is under way or finished); false = the list cannot be read now.</summary>
        private bool ScanSlice(out string reason)
        {
            reason = null;
            Stopwatch clock = Stopwatch.StartNew();
            try
            {
                if (!listSeen)
                {
                    int count;
                    string r;
                    bool ok;
                    try { ok = api.TryLimitCount(out count, out r); } catch { ok = false; count = 0; r = LegacyScoringReason.ReadException; }
                    if (!ok)
                    {
                        reason = SafeWord(r, LegacyScoringReason.ReadException);
                        return false;
                    }

                    listSeen = true;
                    listCount = count < 0 ? 0 : count;
                    scanned = 0;
                }

                int limit = Math.Min(listCount, MaxScanElements);
                int budget = ScanPerTick;
                while (scanned < limit && budget > 0)
                {
                    int index = scanned;
                    scanned++;
                    budget--;
                    LegacyLimitElement e = null;
                    string er = null;
                    bool eok;
                    try { eok = api.TryLimitElement(index, out e, out er); } catch { eok = false; e = null; }
                    if (!eok || e == null)
                    {
                        readFail++;
                        continue;
                    }

                    if (firstType == null)
                    {
                        firstType = SafeWord(e.TypeName, "other");
                    }

                    if (!TelemetryContract.Finite(e.Location))
                    {
                        readFail++;
                        continue;
                    }

                    if (!e.IsValueNode || double.IsNaN(e.Value))
                    {
                        otherNodes++;
                        continue;
                    }

                    if (limitLoc.Count > 0 && e.Location < limitLoc[limitLoc.Count - 1])
                    {
                        sorted = false;
                    }

                    double kmh = TelemetryContract.GroundLimitKmh(e.Value);
                    limitLoc.Add(e.Location);
                    limitKmh.Add(kmh);
                    valueNodes++;
                    if (firstTextCount < 3)
                    {
                        if (firstTextCount > 0)
                        {
                            firstText.Append('_');
                        }

                        firstText.Append('L').Append(Num(e.Location)).Append('V').Append(Num(kmh));
                        firstTextCount++;
                    }
                }

                scanTicks += clock.ElapsedTicks;
                if (scanned >= limit && !listFinished)
                {
                    listFinished = true;
                    double ms = scanTicks * 1000.0 / Stopwatch.Frequency;
                    pendingList = "count=" + TelemetryContract.I(listCount) + " scanned=" + TelemetryContract.I(scanned) + " valueNodes=" + TelemetryContract.I(valueNodes)
                        + " other=" + TelemetryContract.I(otherNodes) + " readFail=" + TelemetryContract.I(readFail) + " sorted=" + Flag(sorted)
                        + " truncated=" + Flag(listCount > MaxScanElements) + " type=" + (firstType ?? "na") + " first=" + (firstTextCount == 0 ? "-" : firstText.ToString())
                        + " scanMs=" + TelemetryContract.F(ms, "F1");
                }

                return true;
            }
            catch
            {
                reason = LegacyScoringReason.ReadException;
                return false;
            }
        }

        private void ProcessLimits(double location, double? groundMps)
        {
            if (!listFinished)
            {
                return;
            }

            if (!aheadDone)
            {
                aheadDone = true;
                string sample;
                int n = Ahead(location, limitLoc, limitKmh, out sample);
                string current = "na";
                string headText = "na";
                string headMatch = "na";
                if (groundMps.HasValue && !double.IsNaN(groundMps.Value))
                {
                    // the host's limit at this very Tick next to what the list says is in force at the head: a first, change-free look at the head / tail question
                    double nowKmh = TelemetryContract.GroundLimitKmh(groundMps.Value);
                    double aheadHead;
                    double aheadTail;
                    HeadTail(location, 0.0, limitLoc, limitKmh, out aheadHead, out aheadTail);
                    current = Num(nowKmh);
                    headText = Num(aheadHead);
                    headMatch = Flag(Math.Abs(aheadHead - nowKmh) <= DeltaTolerance);
                }

                Emit(NameAhead, CapAhead, "loc=" + Num(location) + " n=" + TelemetryContract.I(n) + " sample=" + sample + " cur=" + current + " head=" + headText + " headMatch=" + headMatch);
            }

            if (!groundMps.HasValue || double.IsNaN(groundMps.Value))
            {
                return;
            }

            double now = TelemetryContract.GroundLimitKmh(groundMps.Value);
            if (!groundSeen)
            {
                groundSeen = true;
                lastGroundKmh = now;
                return;
            }

            if (Math.Abs(now - lastGroundKmh) <= DeltaTolerance)
            {
                return;
            }

            double from = lastGroundKmh;
            lastGroundKmh = now;
            limitChanges++;
            int used;
            perName.TryGetValue(NameLimitChange, out used);
            if (used >= CapLimitChange || lines >= MaxLinesPerGeneration - 1)
            {
                suppressed++;
                return;
            }

            double head;
            double tail;
            HeadTail(location, 0.0, limitLoc, limitKmh, out head, out tail);
            StringBuilder sb = new StringBuilder();
            sb.Append("loc=").Append(Num(location)).Append(" from=").Append(Num(from)).Append(" to=").Append(Num(now));
            sb.Append(" head=").Append(Num(head)).Append(" headMatch=").Append(Flag(Math.Abs(head - now) <= DeltaTolerance));
            AppendTailCandidate(sb, "A", candTotal, location, now);
            AppendTailCandidate(sb, "B", candMotorTrailer, location, now);
            sb.Append(" deltaM=").Append(NearestBehind(location, now));
            Emit(NameLimitChange, CapLimitChange, sb.ToString());
        }

        private void AppendTailCandidate(StringBuilder sb, string label, double? length, double location, double now)
        {
            if (!length.HasValue)
            {
                sb.Append(" tail").Append(label).Append("=na tail").Append(label).Append("Match=na");
                return;
            }

            double head;
            double tail;
            HeadTail(location, length.Value, limitLoc, limitKmh, out head, out tail);
            sb.Append(" tail").Append(label).Append('=').Append(Num(tail)).Append(" tail").Append(label).Append("Match=").Append(Flag(Math.Abs(tail - now) <= DeltaTolerance));
        }

        /// <summary>How far behind the head the nearest list element with the new limit value lies (m); na when there is none. About 0 = the host switched when the HEAD passed it; about the train length = the TAIL.</summary>
        private string NearestBehind(double location, double kmh)
        {
            bool found = false;
            double best = 0.0;
            for (int i = 0; i < limitLoc.Count; i++)
            {
                if (limitLoc[i] <= location && Math.Abs(limitKmh[i] - kmh) <= DeltaTolerance && (!found || limitLoc[i] > best))
                {
                    found = true;
                    best = limitLoc[i];
                }
            }

            return found ? Num(location - best) : "na";
        }

        // -- writing ----------------------------------------------------------------------------------------------------------------------
        private void ReportUnavailable(string group, string reason)
        {
            string r = SafeWord(reason, LegacyScoringReason.ReadException);
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
    }
}
