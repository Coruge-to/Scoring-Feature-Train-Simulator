using System;
using System.Collections.Generic;
using System.Text;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE L3 - the station part of the telemetry line for the Legacy sender (host independent).
//
// It turns the stations the Legacy API gives (LegacyStationRaw) into what the HUD reads: the STALIST datagram (with the timing flags the user can
// switch) and the per-Tick "next station" values (NEXTLOC, NEXTTIME, ISPASS, ISTIMING, MARGINB/F, DOORDIR, TERM, STATNAME).
//
// The rules are the rules the Current sender (TsScoringPlugin\Class1.cs) has always applied to the same data, written again here because that file
// is bound to the BveEX host and is not touched by Phase L3: terminal station detection, the stopping time fill-in, the default-time anchors, the
// interpolation of the stations without a timetable entry, and the next-station state machine (pass / operating stop / normal stop / terminal).
// The inputs are values of the Legacy API (nothing is guessed); only the source of the terminal flag differs: the Legacy API states it
// (Station.IsTerminal), the Current sender derives it from the departure time sentinel.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    internal sealed class StationEntry
    {
        internal string Name;
        internal double Location;
        internal int ArrTime;
        internal int DepTime;
        internal int RawArrTime;
        internal int RawDepTime;
        internal int DefaultTime;
        internal int DoorDir;
        internal bool IsPass;
        internal bool IsTerminal;
        internal bool HasTimeDef;
        internal bool IsScoring;
        internal int InterpolatedTime;
        internal int StoppageTime;
        internal double MarginMin;
        internal double MarginMax;
    }

    /// <summary>The "next station" values of one Tick, in the units of the contract.</summary>
    internal struct StationValues
    {
        internal double NextLoc;
        internal int NextTime;
        internal int IsPass;
        internal int IsTiming;
        internal double MarginBack;
        internal double MarginFront;
        internal int DoorDir;
        internal int Term;
        internal string Name;
        /// <summary>Phase ST-1A: the index of the station the values above belong to (-1 = none). It is the TGT of the STIDX part.</summary>
        internal int Index;
    }

    internal sealed class LegacyStationTimeline
    {
        private const int NoTime = -2000000000;

        private readonly List<StationEntry> list = new List<StationEntry>();
        private int target;
        private bool hasDoorOpenedAtTarget;
        private bool isInitialized;
        private int opStopDelayStartMs = -1;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened;

        // Phase ST-1A (observation only, nothing above reads these): the arrival candidate events and the identity of the list of the STIDX part
        private const string StaListPrefix = "STALIST:";
        private int arrivalIndex = -1;
        private int arrivalSeq;
        private string listId = StationListIdentity.EmptyId;

        // Phase ST-3c: the ONE-SHOT requested target of an official (v2) jump. The executor adopted a StationIndex; the re-initialisation that follows the jump targets exactly that station and
        // never searches by position. It is consumed by the first selection (whatever the verdict), expires at the end of the Tick that carried it, and is cleared by Reset(). A
        // discontinuity without a request (the first Tick, a manual time jump, a changed station count, a new scenario) keeps the 50 m search below.
        internal const string RefusalIndexRange = "reinit-index-range";
        internal const string RefusalLocationMismatch = "reinit-location-mismatch";
        internal const string RefusalNotApplied = "reinit-not-applied";             // the Tick that carried the request never reached a selection (the station part was skipped): the target was NOT set as requested
        private bool requestedTargetActive;
        private int requestedTargetIndex = -1;
        private double requestedTargetLocation;
        private string requestRefusal;

        internal int Count { get { return list.Count; } }

        internal int TargetIndex { get { return target; } }

        /// <summary>Phase ST-1A: the station of the last arrival candidate event (the door-open / operational-stop flag went false -> true for the target); -1 = none.</summary>
        internal int ArrivalIndex { get { return arrivalIndex; } }

        /// <summary>Phase ST-1A: the number of arrival candidate events since the last Reset (the scenario instance).</summary>
        internal int ArrivalSeq { get { return arrivalSeq; } }

        /// <summary>Phase ST-1A: CRC-32 of the STALIST payload of the list as it was built (00000000 for an empty list).</summary>
        internal string ListId { get { return listId; } }

        internal IList<StationEntry> Entries { get { return list; } }

        internal bool IsInitialized { get { return isInitialized; } }

        /// <summary>A new scenario instance: nothing of the previous one is kept.</summary>
        internal void Reset()
        {
            list.Clear();
            target = 0;
            hasDoorOpenedAtTarget = false;
            isInitialized = false;
            opStopDelayStartMs = -1;
            terminalFrozenDiffSeconds = -999;
            wasTerminalDoorOpened = false;
            arrivalIndex = -1;
            arrivalSeq = 0;
            listId = StationListIdentity.EmptyId;
            requestedTargetActive = false;
            requestedTargetIndex = -1;
            requestedTargetLocation = 0.0;
            requestRefusal = null;
        }

        /// <summary>
        /// Phase ST-3c: the next selection targets `index` (the station an official jump adopted, whose list location was `location`) instead of searching by position. One shot: see the
        /// fields above. Nothing reads the vehicle position to make this choice.
        /// </summary>
        internal void RequestTarget(int index, double location)
        {
            requestedTargetActive = true;
            requestedTargetIndex = index;
            requestedTargetLocation = location;
            requestRefusal = null;
        }

        /// <summary>
        /// Phase ST-3c: the request did not reach a selection in the Tick that carried it: it is gone (never kept for a later, unrelated discontinuity). Returns true when a request was still pending,
        /// i.e. the target was NOT set as requested: the refusal reinit-not-applied is then reported like any other (TakeRequestRefusal), so that no completion announces a target that was not set.
        /// </summary>
        internal bool ExpireRequestedTarget()
        {
            bool wasPending = requestedTargetActive;
            requestedTargetActive = false;
            requestedTargetIndex = -1;
            requestedTargetLocation = 0.0;
            if (wasPending) requestRefusal = RefusalNotApplied;
            return wasPending;
        }

        /// <summary>Phase ST-3c: why the rebuilt list could not carry the requested target (reinit-index-range / reinit-location-mismatch), or null; taken once.</summary>
        internal string TakeRequestRefusal()
        {
            string r = requestRefusal;
            requestRefusal = null;
            return r;
        }

        /// <summary>The simulation time jumped: the next station is chosen again from the vehicle position.</summary>
        internal void MarkDiscontinuity()
        {
            isInitialized = false;
            terminalFrozenDiffSeconds = -999;
            wasTerminalDoorOpened = false;
            opStopDelayStartMs = -1;
        }

        private static int Clean(int t)
        {
            return t <= NoTime ? -1 : t;
        }

        /// <summary>One Tick: (re)builds the list when needed, advances the next-station state machine and returns the values of this Tick.</summary>
        internal bool NeedsBuild(int rawCount)
        {
            return !isInitialized || rawCount != list.Count;
        }

        /// <summary>raw may be null when NeedsBuild(rawCount) is false (the list built earlier still stands).</summary>
        internal StationValues Step(IList<LegacyStationRaw> raw, int rawCount, double location, double speedKmh, int timeMs, bool areDoorsClosed)
        {
            if (NeedsBuild(rawCount))
            {
                Build(raw);
                SelectTarget(location, areDoorsClosed);
                isInitialized = true;
            }

            StationValues v = new StationValues();
            v.NextLoc = -1;
            v.NextTime = -1;
            v.IsPass = 0;
            v.IsTiming = 0;
            v.MarginBack = 5.0;
            v.MarginFront = 5.0;
            v.DoorDir = 1;
            v.Term = 0;
            v.Name = null;
            v.Index = -1;

            if (target < list.Count)
            {
                int before = target;
                StationEntry st = list[target];
                double nextStationLoc = st.Location;
                int isPass = st.IsPass ? 1 : 0;
                int isTiming = st.IsScoring ? 1 : 0;
                double marginBack = st.MarginMin;
                double marginFront = st.MarginMax;
                bool isTerminal = st.IsTerminal;
                bool doorOpenedBefore = hasDoorOpenedAtTarget;      // Phase ST-1A: read-only snapshots for the STIDX part; nothing of the state machine below changed
                int shownIndex = before;

                if (st.IsPass)
                {
                    if (location > nextStationLoc && !isTerminal)
                    {
                        target++;
                        hasDoorOpenedAtTarget = false;
                        opStopDelayStartMs = -1;
                    }
                }
                else if (st.DoorDir == 0)
                {
                    double distToStop = nextStationLoc - location;
                    bool isInMargin = distToStop >= -marginFront && distToStop <= marginBack;
                    bool isStopped = Math.Abs(speedKmh) < 0.1;
                    int depTime = st.DepTime > 0 ? st.DepTime : st.InterpolatedTime;

                    if (isStopped && isInMargin)
                    {
                        hasDoorOpenedAtTarget = true;
                    }

                    if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal)
                    {
                        if (opStopDelayStartMs < 0)
                        {
                            opStopDelayStartMs = timeMs;
                        }
                        else if (timeMs >= opStopDelayStartMs + 300)
                        {
                            target++;
                            hasDoorOpenedAtTarget = false;
                            opStopDelayStartMs = -1;
                        }
                    }
                    else
                    {
                        opStopDelayStartMs = -1;
                    }
                }
                else
                {
                    if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0)
                    {
                        hasDoorOpenedAtTarget = true;
                    }

                    if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal)
                    {
                        target++;
                        hasDoorOpenedAtTarget = false;
                        opStopDelayStartMs = -1;
                    }
                }

                // on the Tick of a station change every value is derived from the NEW station (nothing of the old one stays in the line)
                if (target != before && target < list.Count)
                {
                    st = list[target];
                    nextStationLoc = st.Location;
                    isPass = st.IsPass ? 1 : 0;
                    isTiming = st.IsScoring ? 1 : 0;
                    marginBack = st.MarginMin;
                    marginFront = st.MarginMax;
                    isTerminal = st.IsTerminal;
                    shownIndex = target;
                }

                // Phase ST-1A: an arrival candidate event = the door-open / operational-stop flag went false -> true for THIS target on this Tick (the flag set by
                // the (re)selection of the target is not an event: it was already true when the snapshot was taken)
                if (!doorOpenedBefore && hasDoorOpenedAtTarget && target == before)
                {
                    arrivalIndex = before;
                    arrivalSeq++;
                }

                int nextStationTime = -1;
                if (isTerminal)
                {
                    if (hasDoorOpenedAtTarget)
                    {
                        if (!wasTerminalDoorOpened)
                        {
                            int arrTime = st.ArrTime > 0 ? st.ArrTime : st.InterpolatedTime;
                            terminalFrozenDiffSeconds = (arrTime - timeMs) / 1000;
                            wasTerminalDoorOpened = true;
                        }

                        nextStationTime = timeMs + (terminalFrozenDiffSeconds * 1000);
                    }
                    else
                    {
                        nextStationTime = st.ArrTime > 0 ? st.ArrTime : st.InterpolatedTime;
                    }
                }
                else
                {
                    if (st.IsPass)
                    {
                        nextStationTime = st.ArrTime > 0 ? st.ArrTime : st.InterpolatedTime;
                    }
                    else
                    {
                        bool isReadyToDepart;
                        if (st.DoorDir == 0)
                        {
                            isReadyToDepart = hasDoorOpenedAtTarget;
                        }
                        else
                        {
                            isReadyToDepart = hasDoorOpenedAtTarget && !areDoorsClosed;
                        }

                        if (isReadyToDepart)
                        {
                            nextStationTime = st.DepTime > 0 ? st.DepTime : st.InterpolatedTime;
                        }
                        else
                        {
                            nextStationTime = st.ArrTime > 0 ? st.ArrTime : st.InterpolatedTime;
                        }
                    }
                }

                v.NextLoc = nextStationLoc;
                v.NextTime = nextStationTime;
                v.IsPass = isPass;
                v.IsTiming = isTiming;
                v.MarginBack = marginBack;
                v.MarginFront = marginFront;
                v.Index = shownIndex;
            }

            if (list.Count > 0 && target < list.Count)
            {
                StationEntry cur = list[target];
                v.Name = cur.Name;
                v.DoorDir = cur.DoorDir;
                v.Term = cur.IsTerminal ? 1 : 0;
            }

            return v;
        }

        /// <summary>The STALIST datagram, or null when there is no station.</summary>
        internal string ComposeStaList()
        {
            if (list.Count == 0)
            {
                return null;
            }

            StringBuilder sb = new StringBuilder("STALIST:");
            for (int i = 0; i < list.Count; i++)
            {
                StationEntry st = list[i];
                if (i > 0)
                {
                    sb.Append(',');
                }

                sb.Append(TelemetryContract.StationName(st.Name)).Append('=')
                  .Append(st.IsScoring ? "1" : "0").Append('=')
                  .Append(LocationText(st.Location)).Append('=')
                  .Append(TelemetryContract.I(st.ArrTime)).Append('=')
                  .Append(TelemetryContract.I(st.DepTime)).Append('=')
                  .Append(TelemetryContract.I(st.DefaultTime)).Append('=')
                  .Append(TelemetryContract.I(st.StoppageTime)).Append('=')
                  .Append(st.IsPass ? "1" : "0").Append('=')
                  .Append(st.IsTerminal ? "1" : "0");
            }

            return sb.ToString();
        }

        /// <summary>
        /// Phase ST-3c: the position of a station in the STALIST text: the shortest text that reads back to exactly the same double (the shared JumpWire codec, invariant culture), so that the
        /// receiver holds the very value that a v2 jump command is compared with. A value outside the contract of the codec keeps the earlier plain form (such a station can not be the
        /// target of a v2 command).
        /// </summary>
        private static string LocationText(double value)
        {
            string reason;
            string text = JumpWire.FormatLocation(value, out reason);
            return text == null ? TelemetryContract.D(value) : text;
        }

        private void SelectTarget(double location, bool areDoorsClosed)
        {
            if (requestedTargetActive)
            {
                SelectRequestedTarget(location, areDoorsClosed);
                return;
            }

            target = list.Count;     // no station at or after the vehicle (within 50 m behind it): there is no next station
            hasDoorOpenedAtTarget = false;
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i].Location >= location - 50.0)
                {
                    target = i;
                    hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(list[i].Location - location) < 50.0;
                    break;
                }
            }
        }

        /// <summary>
        /// Phase ST-3c: the ONE selection that follows an official jump: the adopted index, or a refusal with a reason. It consumes the request whatever the verdict, never looks at the
        /// vehicle position to choose a station and never falls back to the search: a list (re-read after the jump) that can no longer carry the index or its location leaves the target as it
        /// was and reports why (TakeRequestRefusal). The door state of the chosen station is the one the position search gives its station.
        /// </summary>
        private void SelectRequestedTarget(double location, bool areDoorsClosed)
        {
            int index = requestedTargetIndex;
            double expected = requestedTargetLocation;
            requestedTargetActive = false;
            requestedTargetIndex = -1;
            requestedTargetLocation = 0.0;
            if (index < 0 || index >= list.Count)
            {
                requestRefusal = RefusalIndexRange;
                return;
            }

            if (list[index].Location != expected)
            {
                requestRefusal = RefusalLocationMismatch;
                return;
            }

            target = index;
            hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(list[index].Location - location) < 50.0;
        }

        private void Build(IList<LegacyStationRaw> raw)
        {
            list.Clear();
            for (int i = 0; i < raw.Count; i++)
            {
                LegacyStationRaw r = raw[i];
                StationEntry sd = new StationEntry();
                sd.Name = r.Name;
                sd.Location = r.Location;
                sd.IsPass = r.Pass;
                sd.DoorDir = r.DoorSide;
                sd.RawArrTime = Clean(r.ArrivalMs);
                sd.RawDepTime = -1;
                sd.IsTerminal = r.IsTerminal;
                // Time Fix A: the departure time is judged by its VALUE (-1 = undefined, a time below Int32.MaxValue = usable; the terminal sentinel is Int32.MaxValue for BVE6 and does not fit
                // an Int32 for BVE5, so it arrives as Int32.MaxValue or wrapped, and is refused here), not by the role the API states for the station
                if (r.DepartureMs >= -1 && r.DepartureMs < int.MaxValue)
                {
                    sd.RawDepTime = r.DepartureMs;
                }

                sd.DefaultTime = Clean(r.DefaultMs);
                sd.RawDepTime = Clean(sd.RawDepTime);
                sd.ArrTime = sd.RawArrTime;
                sd.DepTime = sd.RawDepTime;
                sd.StoppageTime = r.StoppageMs;
                sd.HasTimeDef = sd.ArrTime > 0 || sd.DepTime > 0;
                sd.IsScoring = sd.HasTimeDef;
                sd.MarginMin = Math.Abs(r.MarginMin);
                sd.MarginMax = r.MarginMax;
                list.Add(sd);
            }

            // several terminal stations: only the first one is the terminal
            bool explicitTerminalFound = false;
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i].IsTerminal)
                {
                    if (!explicitTerminalFound)
                    {
                        explicitTerminalFound = true;
                    }
                    else
                    {
                        list[i].IsTerminal = false;
                    }
                }
            }

            // none stated: the last station is the terminal
            if (!explicitTerminalFound && list.Count > 0)
            {
                list[list.Count - 1].IsTerminal = true;
            }

            // the first station is never a timing station
            if (list.Count > 0)
            {
                list[0].IsScoring = false;
            }

            for (int i = 0; i < list.Count; i++)
            {
                if (!list[i].HasTimeDef)
                {
                    continue;
                }

                if (!list[i].IsTerminal && list[i].ArrTime > 0 && list[i].DepTime <= 0)
                {
                    list[i].DepTime = list[i].ArrTime + list[i].StoppageTime;
                }
                else if (list[i].DepTime > 0 && list[i].DepTime < int.MaxValue && list[i].ArrTime <= 0)
                {
                    // Time Fix A: the arrival is filled in from a USABLE departure time whatever the role of the station (a terminal included); an undefined or sentinel departure never reaches here.
                    list[i].ArrTime = list[i].DepTime - list[i].StoppageTime;
                    if (list[i].ArrTime < 0)
                    {
                        list[i].ArrTime = 0;
                    }
                }
            }

            // stations without a timetable entry but with a default time, before the first or after the last anchor
            for (int i = 0; i < list.Count; i++)
            {
                if (!list[i].HasTimeDef && list[i].DefaultTime > 0)
                {
                    bool hasPrevAnchor = false;
                    for (int j = i - 1; j >= 0; j--)
                    {
                        if (list[j].HasTimeDef)
                        {
                            hasPrevAnchor = true;
                            break;
                        }
                    }

                    bool hasNextAnchor = false;
                    for (int j = i + 1; j < list.Count; j++)
                    {
                        if (list[j].HasTimeDef)
                        {
                            hasNextAnchor = true;
                            break;
                        }
                    }

                    if (!hasPrevAnchor || !hasNextAnchor)
                    {
                        list[i].ArrTime = list[i].DefaultTime;
                        if (list[i].IsTerminal)
                        {
                            list[i].DepTime = -1;
                            list[i].InterpolatedTime = list[i].ArrTime;
                        }
                        else
                        {
                            list[i].DepTime = list[i].DefaultTime + list[i].StoppageTime;
                            list[i].InterpolatedTime = list[i].DepTime;
                        }

                        list[i].HasTimeDef = true;
                        list[i].IsScoring = true;
                    }
                }
            }

            // stations between two anchors: the time is interpolated along the distance
            int lastTimingIdx = -1;
            for (int i = 0; i < list.Count; i++)
            {
                if (list[i].HasTimeDef)
                {
                    lastTimingIdx = i;
                    continue;
                }

                int nextTimingIdx = -1;
                for (int j = i + 1; j < list.Count; j++)
                {
                    if (list[j].HasTimeDef)
                    {
                        nextTimingIdx = j;
                        break;
                    }
                }

                if (lastTimingIdx < 0 || nextTimingIdx < 0)
                {
                    continue;
                }

                double loc0 = list[lastTimingIdx].Location;
                double loc1 = list[nextTimingIdx].Location;
                int time0 = list[lastTimingIdx].DepTime;
                int time1 = list[nextTimingIdx].ArrTime;

                int totalStopTime = 0;
                for (int k = lastTimingIdx + 1; k < nextTimingIdx; k++)
                {
                    if (!list[k].IsPass)
                    {
                        totalStopTime += list[k].StoppageTime;
                    }
                }

                int runTime = (time1 - time0) - totalStopTime;
                if (runTime < 0)
                {
                    runTime = time1 - time0;
                }

                double locT = list[i].Location;
                double ratio = loc1 > loc0 ? (locT - loc0) / (loc1 - loc0) : 0;

                int accStopTime = 0;
                for (int k = lastTimingIdx + 1; k < i; k++)
                {
                    if (!list[k].IsPass)
                    {
                        accStopTime += list[k].StoppageTime;
                    }
                }

                int estArrTime = time0 + (int)(runTime * ratio) + accStopTime;
                list[i].ArrTime = estArrTime;

                if (list[i].IsTerminal)
                {
                    list[i].DepTime = -1;
                    list[i].InterpolatedTime = list[i].ArrTime;
                }
                else if (list[i].IsPass)
                {
                    list[i].DepTime = estArrTime;
                    list[i].InterpolatedTime = list[i].DepTime;
                }
                else
                {
                    list[i].DepTime = estArrTime + list[i].StoppageTime;
                    list[i].InterpolatedTime = list[i].DepTime;
                }
            }

            // Phase ST-1A: the identity of the list as the STALIST will state it (the same text, hashed once per build; nothing above reads it)
            string payload = ComposeStaList();
            listId = payload == null ? StationListIdentity.EmptyId : StationListIdentity.Compute(payload.Substring(StaListPrefix.Length));
        }
    }
}
