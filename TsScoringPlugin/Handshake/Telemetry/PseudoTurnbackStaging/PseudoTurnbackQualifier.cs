// PR-1a prototype (clone only). Pure, host independent, C# 5 compatible.
// Qualifies pseudo-turnback pairs A -> B from the S1-normalised raw station records (PTS-0 Pair contract PQ-13, PQ-15).
// INPUTS ARE FIVE RAW VALUES ONLY: arrival stated, departure stated, raw terminal, pass, and the position in the list (= StationIndex).
// Nothing else is accepted: no names, no positions, no door state, no signal flag, no distance.
using System;
using System.Collections.Generic;

namespace TSScoringPlugin.Telemetry
{
    internal enum PseudoTurnbackCompletionMode
    {
        ContinueScoring = 0,
        CompleteAfterJump = 1
    }

    /// <summary>One raw station record after S1 and before S2. A value is "stated" when the raw time is greater than 0 ms.</summary>
    internal struct PseudoTurnbackRecord
    {
        public bool ArrivalStated;
        public bool DepartureStated;
        public bool RawTerminal;
        public bool IsPass;

        public PseudoTurnbackRecord(bool arrivalStated, bool departureStated, bool rawTerminal, bool isPass)
        {
            ArrivalStated = arrivalStated;
            DepartureStated = departureStated;
            RawTerminal = rawTerminal;
            IsPass = isPass;
        }
    }

    internal sealed class PseudoTurnbackPair
    {
        public readonly int ArrivalStationIndex;
        public readonly int DepartureStationIndex;
        public readonly PseudoTurnbackCompletionMode CompletionMode;

        public PseudoTurnbackPair(int arrival, int departure, PseudoTurnbackCompletionMode mode)
        {
            ArrivalStationIndex = arrival;
            DepartureStationIndex = departure;
            CompletionMode = mode;
        }
    }

    /// <summary>Immutable collection of pairs of one station list. Zero pairs is a valid value (never null).</summary>
    internal sealed class PseudoTurnbackPairSet
    {
        public const string ReasonRange = "range";
        public const string ReasonMode = "mode";
        public const string ReasonOrder = "order";
        public const string ReasonOverlap = "overlap";
        public const string ReasonFinal = "final-structure";
        public const string ReasonLimit = "limit";

        private readonly PseudoTurnbackPair[] pairs;
        public readonly int StationCount;

        private PseudoTurnbackPairSet(int stationCount, PseudoTurnbackPair[] items)
        {
            StationCount = stationCount;
            pairs = items;
        }

        public int Count { get { return pairs.Length; } }
        public PseudoTurnbackPair this[int i] { get { return pairs[i]; } }

        public static PseudoTurnbackPairSet Empty(int stationCount)
        {
            return new PseudoTurnbackPairSet(stationCount < 0 ? 0 : stationCount, new PseudoTurnbackPair[0]);
        }

        /// <summary>Validates with the SAME rules at construction and at decoding (PQ-4). Returns null and a fixed reason word on any violation: no partial adoption.</summary>
        public static PseudoTurnbackPairSet TryCreate(int stationCount, IList<PseudoTurnbackPair> items, out string reason)
        {
            reason = null;
            if (stationCount < 0) { reason = ReasonRange; return null; }
            if (items == null || items.Count == 0) { return Empty(stationCount); }
            if (stationCount == 0) { reason = ReasonRange; return null; }
            if (items.Count > (stationCount - 1) / 2) { reason = ReasonLimit; return null; }
            int previousB = -1;
            int finals = 0;
            for (int i = 0; i < items.Count; i++)
            {
                PseudoTurnbackPair p = items[i];
                if (p == null) { reason = ReasonRange; return null; }
                if (p.CompletionMode != PseudoTurnbackCompletionMode.ContinueScoring && p.CompletionMode != PseudoTurnbackCompletionMode.CompleteAfterJump) { reason = ReasonMode; return null; }
                if (p.ArrivalStationIndex < 1 || p.DepartureStationIndex != p.ArrivalStationIndex + 1 || p.DepartureStationIndex >= stationCount) { reason = ReasonRange; return null; }
                if (i > 0 && p.ArrivalStationIndex < previousB) { reason = ReasonOrder; return null; }
                if (i > 0 && p.ArrivalStationIndex == items[i - 1].ArrivalStationIndex) { reason = ReasonOrder; return null; }
                if (p.ArrivalStationIndex <= previousB && i > 0) { reason = ReasonOverlap; return null; }
                previousB = p.DepartureStationIndex;
                if (p.CompletionMode == PseudoTurnbackCompletionMode.CompleteAfterJump)
                {
                    finals++;
                    if (i != items.Count - 1 || p.DepartureStationIndex != stationCount - 1) { reason = ReasonFinal; return null; }
                }
            }
            if (finals > 1) { reason = ReasonFinal; return null; }
            PseudoTurnbackPair[] copy = new PseudoTurnbackPair[items.Count];
            for (int i = 0; i < copy.Length; i++) copy[i] = new PseudoTurnbackPair(items[i].ArrivalStationIndex, items[i].DepartureStationIndex, items[i].CompletionMode);
            return new PseudoTurnbackPairSet(stationCount, copy);
        }
    }

    internal static class PseudoTurnbackQualifier
    {
        /// <summary>Effective terminal T: the first raw terminal, else the last record (the same rule as the scoring end), -1 for an empty list.</summary>
        internal static int EffectiveTerminal(IList<PseudoTurnbackRecord> records)
        {
            if (records == null || records.Count == 0) return -1;
            for (int i = 0; i < records.Count; i++) if (records[i].RawTerminal) return i;
            return records.Count - 1;
        }

        /// <summary>Pure function of the raw records. Never throws for a valid list; the adapter wraps it in its own try/catch.</summary>
        public static PseudoTurnbackPairSet Qualify(IList<PseudoTurnbackRecord> records)
        {
            int count = records == null ? 0 : records.Count;
            if (count == 0) return PseudoTurnbackPairSet.Empty(0);
            int t = EffectiveTerminal(records);
            bool anyRawTerminal = false;
            for (int i = 0; i < count; i++) if (records[i].RawTerminal) { anyRawTerminal = true; break; }
            List<PseudoTurnbackPair> found = new List<PseudoTurnbackPair>();
            for (int a = 1; a + 1 < count; a++)
            {
                PseudoTurnbackRecord ra = records[a];
                PseudoTurnbackRecord rb = records[a + 1];
                bool aOk = ra.ArrivalStated && !ra.DepartureStated && !ra.IsPass && !ra.RawTerminal && a < t;
                bool bOk = !rb.ArrivalStated && rb.DepartureStated && !rb.IsPass && !rb.RawTerminal && (a + 1) <= t;
                if (!aOk || !bOk) continue;
                PseudoTurnbackCompletionMode mode = (!anyRawTerminal && a + 1 == count - 1) ? PseudoTurnbackCompletionMode.CompleteAfterJump : PseudoTurnbackCompletionMode.ContinueScoring;
                found.Add(new PseudoTurnbackPair(a, a + 1, mode));
            }
            string reason;
            PseudoTurnbackPairSet set = PseudoTurnbackPairSet.TryCreate(count, found, out reason);
            return set != null ? set : PseudoTurnbackPairSet.Empty(count);
        }
    }
}
