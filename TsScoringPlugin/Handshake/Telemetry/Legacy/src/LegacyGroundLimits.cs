using System;
using System.Collections.Generic;
using System.Text;

// ============================================================================
// PHASE SI-1 - the AtsEX LEGACY ground speed limit contract of the Current sender: TRAINLEN, MAPLIMITS, CLEARDIST and a MAPHEAD that really is the head.
//
// What the live check of Phase SI-0 settled (documents of that phase, quoted here as the reasons of the rules below):
//   * the Legacy API has no vehicle length. It has CarLength (ONE car) and the car counts; the train is CarLength x (MotorCar + TrailerCar). FirstCar is NOT added.
//     CarInfo.Count is a double (0.5 exists).
//   * Scenario.Route.SpeedLimits is a sorted list of ValueNode<double> (Location, Value in m/s). The host's current limit is "the lowest value in (tail, head]",
//     which is exactly what the Current sender sends as MAPTAIL, so MAPTAIL stays the host value. The HEAD limit (the value in force at the head) is not the
//     host value: a limit that rises is still low at the host until the tail has passed it. It is computed from the list.
//
// What this file does, per Tick (Tick thread only, read only):
//   * TRAINLEN       CarLength x (MotorCar + TrailerCar), read every Tick, all numbers finite, CarLength > 0, counts >= 0, the sum > 0, the product finite.
//   * list           read ONCE per scenario instance (in slices, never in one frame), validated as a whole, then used from memory. A list with ONE unreadable,
//                    non-finite, non-ValueNode or out-of-order element is not used AT ALL (no partial list, ever). The element count is checked every Tick: a list
//                    that changes is dropped and read again.
//   * MAPHEAD        the value in force at the head (the last element at or before the location; no element = 1000), from the list. Not available => the sender falls
//                    back to the old MAPHEAD = MAPTAIL (the Python side then has no tail wait, so no blue is made up).
//   * MAPLIMITS      the elements in (location, location + 3000], in list order, "location F1 = km/h F1" joined by '_' (the Current text); an empty window is empty text.
//   * CLEARDIST      the Current formula (see ClearDist).
//   * AVAIL          trainlen: TRAINLEN. maplimit_ahead: MAPLIMITS and CLEARDIST together, only when the list is usable, the train length is known (CLEARDIST needs
//                    it), the host ground limit (MAPTAIL) is in the same line, and the window fits. Each group is judged alone; a failing group is neither written
//                    nor announced; nothing of an earlier scenario instance survives Begin.
//
// No Current type, no private API, no hook. The host is reached only through ILegacyGroundApi.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// The read surface of the ground limit contract. Contract of every Try method: true = read now; false = cannot be read, with a fixed reason (LegacyScoringReason
    /// words). May throw (treated as read-exception). Called on the host's Tick thread only.
    /// </summary>
    internal interface ILegacyGroundApi
    {
        /// <summary>VehicleDynamics.CarLength and MotorCar.Count / TrailerCar.Count (FirstCount stays null: it is not part of the length).</summary>
        bool TryCarSpec(out LegacyVehicleLengthSnapshot snapshot, out string reason);

        /// <summary>The number of elements of Scenario.Route.SpeedLimits.</summary>
        bool TryLimitCount(out int count, out string reason);

        /// <summary>One element of Scenario.Route.SpeedLimits (Location, and Value when it is a ValueNode of double).</summary>
        bool TryLimitElement(int index, out LegacyLimitElement element, out string reason);
    }

    /// <summary>What one Tick could establish. A false Have* means the group is not written and not announced.</summary>
    internal sealed class LegacyGroundValues
    {
        internal bool HaveTrainLength;
        internal double TrainLength;                 // m
        internal bool HaveHead;
        internal double HeadKmh;                     // km/h of the contract, 1000 = no limit
        internal bool HaveAhead;
        internal string AheadText;                   // the MAPLIMITS value
        internal int AheadCount;
        internal double ClearDist;                   // m
    }

    /// <summary>The pure rules of the ground limit contract (no host, no state). Values are km/h of the contract; 1000 = no limit.</summary>
    internal static class LegacyGroundContract
    {
        internal const double AheadWindowMeters = 3000.0;     // the look-ahead of the Current sender's MAPLIMITS
        internal const int MaxAheadEntries = 500;             // more entries in the window than this: the group is unavailable (a datagram is never cut)

        /// <summary>TRAINLEN = CarLength x (MotorCar + TrailerCar). false = not one finite positive length (nothing is defaulted).</summary>
        internal static bool TryTrainLength(double? carLength, double? motor, double? trailer, out double length)
        {
            length = 0.0;
            if (!carLength.HasValue || !motor.HasValue || !trailer.HasValue)
            {
                return false;
            }

            double c = carLength.Value;
            double m = motor.Value;
            double t = trailer.Value;
            if (!TelemetryContract.Finite(c) || !TelemetryContract.Finite(m) || !TelemetryContract.Finite(t))
            {
                return false;
            }

            if (c <= 0.0 || m < 0.0 || t < 0.0)
            {
                return false;
            }

            double cars = m + t;
            if (!TelemetryContract.Finite(cars) || cars <= 0.0)
            {
                return false;
            }

            double product = c * cars;
            if (!TelemetryContract.Finite(product) || product <= 0.0)
            {
                return false;
            }

            length = product;
            return true;
        }

        /// <summary>
        /// One list value [m/s] to the km/h of the contract, with the rule of the Current sender (infinite, above 999 or not positive = 1000). false = NaN (a corrupt
        /// value: the whole list is then unusable).
        /// </summary>
        internal static bool TryLimitKmh(double metersPerSecond, out double kmh)
        {
            kmh = TelemetryContract.NoLimitKmh;
            if (double.IsNaN(metersPerSecond))
            {
                return false;
            }

            kmh = TelemetryContract.GroundLimitKmh(metersPerSecond);
            return true;
        }

        /// <summary>The number of elements at or before the location in a list sorted by location (= the index of the first element after it). Binary search.</summary>
        internal static int CountAtOrBefore(IList<double> locs, double location)
        {
            int lo = 0;
            int hi = locs.Count;
            while (lo < hi)
            {
                int mid = lo + ((hi - lo) / 2);
                if (locs[mid] <= location)
                {
                    lo = mid + 1;
                }
                else
                {
                    hi = mid;
                }
            }

            return lo;
        }

        /// <summary>The limit in force at the head: the last element at or before the location (the later one wins at an equal location); none = 1000.</summary>
        internal static double HeadKmh(double location, IList<double> locs, IList<double> kmh)
        {
            int n = CountAtOrBefore(locs, location);
            return n == 0 ? TelemetryContract.NoLimitKmh : kmh[n - 1];
        }

        /// <summary>The lowest limit anywhere in (tail, head] including the value in force at the tail: the MAPTAIL of the Current sender. The Legacy sender does NOT send this (it sends the host value); it is here to state the meaning and to test it.</summary>
        internal static double TailKmh(double location, double trainLength, IList<double> locs, IList<double> kmh)
        {
            double tailLoc = location - trainLength;
            int headCount = CountAtOrBefore(locs, location);
            int tailCount = CountAtOrBefore(locs, tailLoc);
            double min = tailCount == 0 ? TelemetryContract.NoLimitKmh : kmh[tailCount - 1];
            for (int i = tailCount; i < headCount; i++)
            {
                if (kmh[i] < min)
                {
                    min = kmh[i];
                }
            }

            return min;
        }

        /// <summary>
        /// The Current formula: tail position = location - train length. When the lowest limit in (tail, head] is lower than the limit at the head, the distance from the
        /// tail to the nearest-to-the-tail element of the run of elements (inside (tail, head]) that carry the head's value, counted back from the head; otherwise 0.
        /// </summary>
        internal static double ClearDist(double location, double trainLength, IList<double> locs, IList<double> kmh)
        {
            double tailLoc = location - trainLength;
            int headCount = CountAtOrBefore(locs, location);
            int tailCount = CountAtOrBefore(locs, tailLoc);
            double limitAtHead = headCount == 0 ? TelemetryContract.NoLimitKmh : kmh[headCount - 1];
            double minOccupied = TailKmh(location, trainLength, locs, kmh);
            if (!(minOccupied < limitAtHead))
            {
                return 0.0;
            }

            double clearanceLoc = location;
            for (int i = headCount - 1; i >= tailCount; i--)
            {
                if (kmh[i] == limitAtHead)
                {
                    clearanceLoc = locs[i];
                }
                else
                {
                    break;
                }
            }

            return clearanceLoc - tailLoc;
        }

        /// <summary>
        /// The MAPLIMITS text: the elements with location &gt; location and &lt;= location + 3000, in list order, "location F1 = km/h F1" joined by '_' (invariant culture).
        /// An empty window gives "" (the Current behaviour). false = more than MaxAheadEntries in the window (nothing is cut).
        /// </summary>
        internal static bool TryAhead(double location, IList<double> locs, IList<double> kmh, out string text, out int count)
        {
            text = null;
            count = 0;
            int start = CountAtOrBefore(locs, location);
            double end = location + AheadWindowMeters;
            int stop = start;
            while (stop < locs.Count && locs[stop] <= end)
            {
                stop++;
            }

            count = stop - start;
            if (count > MaxAheadEntries)
            {
                return false;
            }

            StringBuilder sb = new StringBuilder();
            for (int i = start; i < stop; i++)
            {
                if (i > start)
                {
                    sb.Append('_');
                }

                sb.Append(TelemetryContract.F(locs[i], "F1")).Append('=').Append(TelemetryContract.F(kmh[i], "F1"));
            }

            text = sb.ToString();
            return true;
        }
    }

    /// <summary>
    /// The state of the ground limit contract for the scenario instance that is active (Tick thread only). Begin / End are the generation boundary: both drop the list,
    /// the train length and every remembered value, so a value of an earlier scenario instance can never be written for a later one.
    /// </summary>
    internal sealed class LegacyGroundTelemetry
    {
        internal const int ScanPerTick = 400;           // list elements read per Tick (slices; the list is never walked in one frame beyond this)
        internal const int MaxElements = 20000;         // a longer list is not used (it would take more than fifty Ticks to read)
        internal const int RetryEveryTicks = 60;        // a list that could not be read is tried again this often (from the start, never continued)
        internal const int MaxLogLines = 64;            // per scenario instance, everything included
        internal const int MaxChangeLines = 40;

        internal const string NameList = "TEL_GROUND_LIST";
        internal const string NameUnavailable = "TEL_GROUND_UNAVAILABLE";
        internal const string NameTrain = "TEL_GROUND_TRAINLEN";
        internal const string NameChange = "TEL_GROUND_CHANGE";

        private enum ListState
        {
            Idle,
            Scanning,
            Ready,
            Failed
        }

        private readonly ILegacyGroundApi api;
        private readonly Action<string, string> log;
        private readonly List<double> locs = new List<double>();
        private readonly List<double> kmh = new List<double>();
        private readonly HashSet<string> unavailableLogged = new HashSet<string>();

        private bool active;
        private int generation;
        private int ticks;
        private ListState state;
        private int expectedCount;
        private int retryAt;
        private int scanTicks;
        private int lines;
        private int changeLines;
        private bool trainLogged;
        private double lastTrain;
        private bool haveLastPattern;
        private string lastPattern;

        internal LegacyGroundTelemetry(ILegacyGroundApi api, Action<string, string> log)
        {
            this.api = api;
            this.log = log;
        }

        internal bool ListReady { get { return state == ListState.Ready; } }

        internal int ListCount { get { return state == ListState.Ready ? locs.Count : 0; } }

        /// <summary>A new scenario instance: nothing of the previous one is kept.</summary>
        internal void Begin(int scenarioId)
        {
            Reset();
            active = true;
            generation = scenarioId;
        }

        /// <summary>The scenario instance ended: nothing is kept; the object is idle until the next Begin.</summary>
        internal void End()
        {
            Reset();
            active = false;
        }

        private void Reset()
        {
            ticks = 0;
            state = ListState.Idle;
            expectedCount = 0;
            retryAt = 0;
            scanTicks = 0;
            lines = 0;
            changeLines = 0;
            trainLogged = false;
            lastTrain = 0.0;
            haveLastPattern = false;
            lastPattern = null;
            locs.Clear();
            kmh.Clear();
            unavailableLogged.Clear();
        }

        /// <summary>
        /// One Tick. hostTailKmh = the host's current ground limit of this very Tick (the MAPTAIL of the line), only used for the change log. Never throws; any failure
        /// leaves the affected groups unavailable.
        /// </summary>
        internal LegacyGroundValues Read(double location, double? hostTailKmh)
        {
            LegacyGroundValues v = new LegacyGroundValues();
            if (!active)
            {
                return v;
            }

            try
            {
                ticks++;
                ReadTrainLength(v);
                AdvanceList();
                if (state == ListState.Ready && TelemetryContract.Finite(location))
                {
                    v.HaveHead = true;
                    v.HeadKmh = LegacyGroundContract.HeadKmh(location, locs, kmh);
                    if (v.HaveTrainLength)
                    {
                        string text;
                        int count;
                        if (LegacyGroundContract.TryAhead(location, locs, kmh, out text, out count))
                        {
                            double clear = LegacyGroundContract.ClearDist(location, v.TrainLength, locs, kmh);
                            if (TelemetryContract.Finite(clear) && clear >= 0.0)
                            {
                                v.HaveAhead = true;
                                v.AheadText = text;
                                v.AheadCount = count;
                                v.ClearDist = clear;
                            }
                            else
                            {
                                Unavailable("ahead", LegacyScoringReason.NonFinite);
                            }
                        }
                        else
                        {
                            Unavailable("ahead", "too-many-in-window");
                        }
                    }
                }

                NoteChange(location, v, hostTailKmh);
            }
            catch
            {
                // a failure of any kind leaves the groups out of this Tick's line; the next Tick starts again from what can be read
                v = new LegacyGroundValues();
                state = ListState.Failed;
                locs.Clear();
                kmh.Clear();
                retryAt = ticks + RetryEveryTicks;
            }

            return v;
        }

        /// <summary>The groups of this Tick as (token, key / value pairs). Called only with the values Read returned. MAPLIMITS and CLEARDIST need the host ground limit (MAPTAIL) in the same line.</summary>
        internal void Compose(LegacyGroundValues v, bool hostLimitPresent, Action<string, string[]> add)
        {
            if (v == null)
            {
                return;
            }

            if (v.HaveTrainLength)
            {
                add(TelemetryContract.TokTrainLen, new string[] { "TRAINLEN", TelemetryContract.D(v.TrainLength) });
            }

            if (v.HaveAhead && hostLimitPresent)
            {
                add(TelemetryContract.TokMapLimitAhead, new string[] { "MAPLIMITS", v.AheadText, "CLEARDIST", TelemetryContract.D(v.ClearDist) });
            }
        }

        // -- the train length ---------------------------------------------------------------------------------------------------------
        private void ReadTrainLength(LegacyGroundValues v)
        {
            LegacyVehicleLengthSnapshot snapshot = null;
            string reason = LegacyScoringReason.ReadException;
            bool ok;
            try { ok = api.TryCarSpec(out snapshot, out reason); }
            catch { ok = false; snapshot = null; reason = LegacyScoringReason.ReadException; }
            if (!ok || snapshot == null)
            {
                Unavailable("trainlen", LegacyScoringProbe.SafeWord(reason, LegacyScoringReason.ReadException));
                return;
            }

            double length;
            if (!LegacyGroundContract.TryTrainLength(snapshot.CarLength, snapshot.MotorCount, snapshot.TrailerCount, out length))
            {
                Unavailable("trainlen", "invalid-number");
                return;
            }

            v.HaveTrainLength = true;
            v.TrainLength = length;
            if (!trainLogged || length != lastTrain)
            {
                trainLogged = true;
                lastTrain = length;
                Emit(NameTrain, "lengthM=" + LegacyScoringProbe.Num(length) + " carLenM=" + LegacyScoringProbe.Num(snapshot.CarLength)
                    + " motor=" + LegacyScoringProbe.Num(snapshot.MotorCount) + " trailer=" + LegacyScoringProbe.Num(snapshot.TrailerCount));
            }
        }

        // -- the list -------------------------------------------------------------------------------------------------------------------
        private void AdvanceList()
        {
            if (state == ListState.Failed)
            {
                if (ticks < retryAt)
                {
                    return;
                }

                state = ListState.Idle;
            }

            int count;
            string reason;
            bool ok;
            try { ok = api.TryLimitCount(out count, out reason); }
            catch { ok = false; count = 0; reason = LegacyScoringReason.ReadException; }
            if (!ok)
            {
                FailList(LegacyScoringProbe.SafeWord(reason, LegacyScoringReason.ReadException), RetryEveryTicks);
                return;
            }

            if (state == ListState.Ready || state == ListState.Scanning)
            {
                if (count != expectedCount)
                {
                    // the list changed under us: what was read is void, the list is read again from the start
                    FailList("count-changed", 1);
                    return;
                }
            }

            if (state == ListState.Ready)
            {
                return;
            }

            if (state == ListState.Idle)
            {
                if (count < 0 || count > MaxElements)
                {
                    FailList(count < 0 ? LegacyScoringReason.NonFinite : "too-many", int.MaxValue / 2);
                    return;
                }

                expectedCount = count;
                locs.Clear();
                kmh.Clear();
                scanTicks = 0;
                state = ListState.Scanning;
            }

            scanTicks++;
            int budget = ScanPerTick;
            while (locs.Count < expectedCount && budget > 0)
            {
                budget--;
                int index = locs.Count;
                LegacyLimitElement e = null;
                string er = null;
                bool eok;
                try { eok = api.TryLimitElement(index, out e, out er); }
                catch { eok = false; e = null; er = LegacyScoringReason.ReadException; }
                if (!eok || e == null)
                {
                    FailList(LegacyScoringProbe.SafeWord(er, LegacyScoringReason.ReadException), RetryEveryTicks);
                    return;
                }

                if (!TelemetryContract.Finite(e.Location))
                {
                    FailList(LegacyScoringReason.NonFinite, RetryEveryTicks);
                    return;
                }

                if (!e.IsValueNode)
                {
                    FailList("not-value-node", RetryEveryTicks);
                    return;
                }

                double value;
                if (!LegacyGroundContract.TryLimitKmh(e.Value, out value))
                {
                    FailList(LegacyScoringReason.NonFinite, RetryEveryTicks);
                    return;
                }

                if (locs.Count > 0 && e.Location < locs[locs.Count - 1])
                {
                    FailList("unsorted", RetryEveryTicks);
                    return;
                }

                locs.Add(e.Location);
                kmh.Add(value);
            }

            if (locs.Count >= expectedCount)
            {
                state = ListState.Ready;
                Emit(NameList, "state=ready count=" + TelemetryContract.I(locs.Count) + " scanTicks=" + TelemetryContract.I(scanTicks));
            }
        }

        private void FailList(string reason, int retryAfterTicks)
        {
            state = ListState.Failed;
            locs.Clear();
            kmh.Clear();
            retryAt = retryAfterTicks >= int.MaxValue / 2 ? int.MaxValue : ticks + retryAfterTicks;
            Unavailable("list", reason);
        }

        // -- the log (state changes only, never per Tick) ---------------------------------------------------------------------------
        private void Unavailable(string group, string reason)
        {
            string r = LegacyScoringProbe.SafeWord(reason, LegacyScoringReason.ReadException);
            if (unavailableLogged.Add(group + ":" + r))
            {
                Emit(NameUnavailable, "group=" + group + " reason=" + r);
            }
        }

        private void NoteChange(double location, LegacyGroundValues v, double? hostTailKmh)
        {
            if (log == null)
            {
                return;
            }

            string pattern = (v.HaveTrainLength ? "T" : "t") + (v.HaveHead ? "H" : "h") + (v.HaveAhead ? "A" : "a")
                + (v.HaveHead ? LegacyScoringProbe.Num(v.HeadKmh) : "na") + "|" + (hostTailKmh.HasValue ? LegacyScoringProbe.Num(hostTailKmh.Value) : "na")
                + "|" + (v.HaveAhead ? LegacyScoringProbe.Num(v.ClearDist > 0.0 ? 1.0 : 0.0) : "na");
            if (haveLastPattern && pattern == lastPattern)
            {
                return;
            }

            haveLastPattern = true;
            lastPattern = pattern;
            if (changeLines >= MaxChangeLines)
            {
                return;
            }

            changeLines++;
            Emit(NameChange, "loc=" + LegacyScoringProbe.Num(location) + " trainLen=" + (v.HaveTrainLength ? LegacyScoringProbe.Num(v.TrainLength) : "na")
                + " head=" + (v.HaveHead ? LegacyScoringProbe.Num(v.HeadKmh) : "na") + " tail=" + (hostTailKmh.HasValue ? LegacyScoringProbe.Num(hostTailKmh.Value) : "na")
                + " ahead=" + (v.HaveAhead ? TelemetryContract.I(v.AheadCount) : "na") + " clearM=" + (v.HaveAhead ? LegacyScoringProbe.Num(v.ClearDist) : "na"));
        }

        private void Emit(string name, string detail)
        {
            if (lines >= MaxLogLines)
            {
                return;
            }

            lines++;
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
    }
}
