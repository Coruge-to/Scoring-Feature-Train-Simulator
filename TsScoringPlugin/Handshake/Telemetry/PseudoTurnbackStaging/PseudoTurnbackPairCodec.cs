// PR-1b prototype (clone only). PTPAIR codec: PTPAIR:1:<list_id>:<station_count>:<pair_count>:<entries>  (PTS-0 PTPAIR addendum XL-PT-2, XL-PT-4).
// Atomic: any violation invalidates the whole key (no partial adoption). C# 5 compatible, pure.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace TSScoringPlugin.Telemetry
{
    internal static class PseudoTurnbackPairCodec
    {
        internal const string Key = "PTPAIR";
        internal const int Version = 1;
        internal const string EmptyListId = "00000000";

        public const string ReasonParts = "parts";
        public const string ReasonVersion = "version";
        public const string ReasonListId = "list-id";
        public const string ReasonInteger = "integer";
        public const string ReasonCount = "count-mismatch";
        public const string ReasonStationCount = "station-count";

        public static string Encode(PseudoTurnbackPairSet set, string listId)
        {
            string id = IsHash(listId) ? listId.ToUpperInvariant() : EmptyListId;
            if (set.StationCount == 0) id = EmptyListId;
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < set.Count; i++)
            {
                if (i > 0) sb.Append(';');
                sb.Append(set[i].ArrivalStationIndex.ToString(CultureInfo.InvariantCulture)).Append('-')
                  .Append(set[i].DepartureStationIndex.ToString(CultureInfo.InvariantCulture)).Append('-')
                  .Append(((int)set[i].CompletionMode).ToString(CultureInfo.InvariantCulture));
            }
            return Key + ":" + Version.ToString(CultureInfo.InvariantCulture) + ":" + id + ":" + set.StationCount.ToString(CultureInfo.InvariantCulture) + ":" + set.Count.ToString(CultureInfo.InvariantCulture) + ":" + sb.ToString();
        }

        /// <summary>Decodes and validates the whole key. expectedStationCount &lt; 0 skips the station count check (the adapter side); Python-side use passes the current count.</summary>
        public static PseudoTurnbackPairSet TryDecode(string text, int expectedStationCount, out string listId, out string reason)
        {
            listId = null; reason = null;
            if (text == null) { reason = ReasonParts; return null; }
            string[] p = text.Split(':');
            if (p.Length != 6 || p[0] != Key) { reason = ReasonParts; return null; }
            if (p[1] != "1") { reason = ReasonVersion; return null; }
            if (!IsHash(p[2])) { reason = ReasonListId; return null; }
            int stationCount, pairCount;
            if (!TryCanonicalInt(p[3], out stationCount) || !TryCanonicalInt(p[4], out pairCount)) { reason = ReasonInteger; return null; }
            if (stationCount == 0 && p[2] != EmptyListId) { reason = ReasonListId; return null; }
            if (expectedStationCount >= 0 && stationCount != expectedStationCount) { reason = ReasonStationCount; return null; }
            List<PseudoTurnbackPair> items = new List<PseudoTurnbackPair>();
            if (p[5].Length > 0)
            {
                string[] entries = p[5].Split(';');
                for (int i = 0; i < entries.Length; i++)
                {
                    string[] f = entries[i].Split('-');
                    int a, b, m;
                    if (f.Length != 3) { reason = ReasonParts; return null; }
                    if (!TryCanonicalInt(f[0], out a) || !TryCanonicalInt(f[1], out b) || !TryCanonicalInt(f[2], out m)) { reason = ReasonInteger; return null; }
                    if (m != 0 && m != 1) { reason = PseudoTurnbackPairSet.ReasonMode; return null; }
                    items.Add(new PseudoTurnbackPair(a, b, (PseudoTurnbackCompletionMode)m));
                }
            }
            if (items.Count != pairCount) { reason = ReasonCount; return null; }
            PseudoTurnbackPairSet set = PseudoTurnbackPairSet.TryCreate(stationCount, items, out reason);
            if (set == null) return null;
            listId = p[2].ToUpperInvariant();
            return set;
        }

        private static bool IsHash(string s)
        {
            if (s == null || s.Length != 8) return false;
            for (int i = 0; i < 8; i++)
            {
                char c = s[i];
                bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f');
                if (!ok) return false;
            }
            return true;
        }

        /// <summary>Digits only, no sign, no leading zeros (except "0"), fits int.</summary>
        private static bool TryCanonicalInt(string s, out int v)
        {
            v = 0;
            if (string.IsNullOrEmpty(s) || s.Length > 9) return false;
            if (s.Length > 1 && s[0] == '0') return false;
            for (int i = 0; i < s.Length; i++) if (s[i] < '0' || s[i] > '9') return false;
            v = int.Parse(s, CultureInfo.InvariantCulture);
            return true;
        }
    }
}
