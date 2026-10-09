using System;
using System.Collections.Generic;
using System.Text;

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

        internal int Count { get { return list.Count; } }

        internal int TargetIndex { get { return target; } }

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
                  .Append(TelemetryContract.D(st.Location)).Append('=')
                  .Append(TelemetryContract.I(st.ArrTime)).Append('=')
                  .Append(TelemetryContract.I(st.DepTime)).Append('=')
                  .Append(TelemetryContract.I(st.DefaultTime)).Append('=')
                  .Append(TelemetryContract.I(st.StoppageTime)).Append('=')
                  .Append(st.IsPass ? "1" : "0").Append('=')
                  .Append(st.IsTerminal ? "1" : "0");
            }

            return sb.ToString();
        }

        private void SelectTarget(double location, bool areDoorsClosed)
        {
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
                if (!r.IsTerminal && r.DepartureMs >= -1 && r.DepartureMs < int.MaxValue)
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
                else if (!list[i].IsTerminal && list[i].DepTime > 0 && list[i].ArrTime <= 0)
                {
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
        }
    }
}
