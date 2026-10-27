using System;
using System.Globalization;
using System.Text;

// ============================================================================
// PHASE PID-D4JA StationIndex ST-1A - the identity of a station list and the wire form of the STIDX telemetry part, shared by BOTH senders
// (the BveEX Current plugin links this file, the AtsEX Legacy telemetry DLL links the same file). Host independent: no BVE, no AtsEX, no BveEX name.
//
//     STIDX:1:<tgt>:<arr>:<arrseq>:<count>:<hash>
//
//   tgt     index (0..count-1) of the station the NEXTLOC / NEXTTIME / ... of the same line belong to; -1 = no next station
//   arr     index of the station at which the last ARRIVAL CANDIDATE EVENT happened (the sender's door-open / operational-stop flag went false -> true
//           for that target); -1 = none yet. It does NOT say that the arrival succeeded: the physical rules stay in the application
//   arrseq  number of arrival candidate events since the scenario instance began (0 = none); +1 per event
//   count   number of stations of the list the line was written for
//   hash    CRC-32 (IEEE 802.3, reflected, init FFFFFFFF, final xor FFFFFFFF) of the UTF-8 bytes of the STALIST payload (the text after "STALIST:"),
//           as 8 upper-case hex digits; an empty list is 00000000
//
// The Python twin is station_index_contract.py; tests\stidx_vectors_st0.json is the shared vector table both are held to. A sender can only write
// well formed values: anything outside the contract is normalised to the "none" form here, so a line that violates the contract can not be produced.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    internal static class StationListIdentity
    {
        internal const string EmptyId = "00000000";

        private static readonly uint[] Table = BuildTable();

        private static uint[] BuildTable()
        {
            uint[] table = new uint[256];
            for (uint n = 0; n < 256; n++)
            {
                uint c = n;
                for (int k = 0; k < 8; k++)
                {
                    c = (c & 1) != 0 ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
                }

                table[n] = c;
            }

            return table;
        }

        /// <summary>CRC-32 of the bytes.</summary>
        internal static uint Crc32(byte[] bytes)
        {
            uint crc = 0xFFFFFFFFu;
            for (int i = 0; i < bytes.Length; i++)
            {
                crc = Table[(crc ^ bytes[i]) & 0xFF] ^ (crc >> 8);
            }

            return crc ^ 0xFFFFFFFFu;
        }

        /// <summary>The identity of a station list: CRC-32 of the UTF-8 text of the STALIST payload, 8 upper-case hex digits. null or empty gives 00000000.</summary>
        internal static string Compute(string payload)
        {
            if (string.IsNullOrEmpty(payload))
            {
                return EmptyId;
            }

            return Crc32(new UTF8Encoding(false).GetBytes(payload)).ToString("X8", CultureInfo.InvariantCulture);
        }
    }

    internal static class StationIndexWire
    {
        internal const string Key = "STIDX";
        internal const int Version = 1;
        internal const int NoStation = -1;

        /// <summary>The five fields after the version: tgt, arr, arrseq, count, hash. Values outside the contract become the "none" form.</summary>
        internal static string Fields(int target, int arrival, int arrivalSeq, int count, string listId)
        {
            int n = count < 0 ? 0 : count;
            int tgt = (target >= 0 && target < n) ? target : NoStation;
            int arr = (arrival >= 0 && arrival < n) ? arrival : NoStation;
            int seq = arrivalSeq < 0 ? 0 : arrivalSeq;
            string hash = IsHash(listId) ? listId.ToUpperInvariant() : StationListIdentity.EmptyId;
            return tgt.ToString(CultureInfo.InvariantCulture) + ":" + arr.ToString(CultureInfo.InvariantCulture) + ":" + seq.ToString(CultureInfo.InvariantCulture)
                + ":" + n.ToString(CultureInfo.InvariantCulture) + ":" + hash;
        }

        /// <summary>The value of the STIDX part (everything after "STIDX:"): version, tgt, arr, arrseq, count, hash.</summary>
        internal static string Value(int target, int arrival, int arrivalSeq, int count, string listId)
        {
            return Version.ToString(CultureInfo.InvariantCulture) + ":" + Fields(target, arrival, arrivalSeq, count, listId);
        }

        /// <summary>The whole part as it stands in the telemetry line.</summary>
        internal static string Part(int target, int arrival, int arrivalSeq, int count, string listId)
        {
            return Key + ":" + Value(target, arrival, arrivalSeq, count, listId);
        }

        private static bool IsHash(string s)
        {
            if (s == null || s.Length != 8)
            {
                return false;
            }

            for (int i = 0; i < 8; i++)
            {
                char c = s[i];
                bool hex = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f');
                if (!hex)
                {
                    return false;
                }
            }

            return true;
        }
    }

    // ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
    // Phase SI-R2.2-S2b - the OFFICIAL next-station target of the host (Conductor.Stations: CurrentIndex, Count and the station CurrentIndex + 1), shared by BOTH senders.
    //
    //     OFFTGT:1:<s>:<idx>:<count>:<hash>:<loc>:<mb>:<mf>        s = K (known) / T (terminal: no next station) / N (the list is empty) / U (host not ready) / F (read failed)
    //
    // The Python twin is official_target_contract.py (S2a). The host is only READ: there is no delegate that writes. Nothing is kept between two Ticks (no field, no static): a Tick that
    // cannot read the target says U or F, it never repeats an earlier K. C# 5 compatible (the PowerShell test path compiles this file with it).
    // ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

    /// <summary>One read of the host's official target (plain data, filled by OfficialTargetReader). A value that could not be read keeps its Ok flag false.</summary>
    internal sealed class OfficialTargetReading
    {
        internal bool HostNull;         // Scenario / Vehicle / Conductor / Stations was null: the host is not ready (U)
        internal bool CursorOk;
        internal int Cursor;            // Conductor.Stations.CurrentIndex
        internal bool CountOk;
        internal int Count;             // Conductor.Stations.Count
        internal bool NextOk;
        internal double NextLocation;   // Location of the station CurrentIndex + 1
        internal double MarginMin;
        internal double MarginMax;
        internal string Error = "-";    // the exception TYPE name of the last failed read (diagnostic only; it never enters the wire)
    }

    internal sealed class OfficialTargetStation
    {
        internal double Location;
        internal double MarginMin;
        internal double MarginMax;
    }

    /// <summary>The host's READ-ONLY accessors as delegates (each sender fills them with one-line typed reads; this file never names a host type).</summary>
    internal sealed class OfficialTargetHost
    {
        internal Func<object> GetStations;                                  // the conductor's station list; null while the host is not ready; may throw
        internal Func<object, int> GetCursor;
        internal Func<object, int> GetCount;
        internal Func<object, int, OfficialTargetStation> ReadStation;
    }

    internal static class OfficialTargetReader
    {
        /// <summary>Reads CurrentIndex, Count and the station CurrentIndex + 1, each read inside a try / catch of its own. Only values of the host's station list are looked at.</summary>
        internal static OfficialTargetReading Read(OfficialTargetHost host)
        {
            OfficialTargetReading r = new OfficialTargetReading();
            object stations;
            try
            {
                stations = host.GetStations();
            }
            catch (Exception ex)
            {
                r.Error = ex.GetType().Name;
                return r;
            }

            if (stations == null)
            {
                r.HostNull = true;
                return r;
            }

            try
            {
                r.Cursor = host.GetCursor(stations);
                r.CursorOk = true;
            }
            catch (Exception ex)
            {
                r.Error = ex.GetType().Name;
            }

            try
            {
                r.Count = host.GetCount(stations);
                r.CountOk = true;
            }
            catch (Exception ex)
            {
                r.Error = ex.GetType().Name;
            }

            if (r.CursorOk && r.CountOk)
            {
                int next = r.Cursor + 1;
                if (next >= 0 && next < r.Count)
                {
                    try
                    {
                        OfficialTargetStation s = host.ReadStation(stations, next);
                        r.NextLocation = s.Location;
                        r.MarginMin = s.MarginMin;
                        r.MarginMax = s.MarginMax;
                        r.NextOk = true;
                    }
                    catch (Exception ex)
                    {
                        r.Error = ex.GetType().Name;
                    }
                }
            }

            return r;
        }
    }

    /// <summary>
    /// The wire form of the OFFTGT telemetry part, shared by BOTH senders. A pure function of one reading and the list identity. Numbers are written in the shortest canonical form
    /// the receiver accepts (no exponent, no trailing zero, no "-0", invariant culture); a value that has no such form is not written: the state is F.
    /// </summary>
    internal static class OfficialTargetWire
    {
        internal const string Key = "OFFTGT";
        internal const int Version = 1;

        /// <summary>The value of the part (everything after "OFFTGT:"): version, state, idx, count, hash, loc, mb, mf. Order of the decision: U, F, N, F, T, K.</summary>
        internal static string Value(OfficialTargetReading r, string listId)
        {
            if (r == null || r.HostNull)
            {
                return Placeholder("U");
            }

            if (!r.CursorOk || !r.CountOk)
            {
                return Placeholder("F");
            }

            if (r.Count == 0)
            {
                return Build("N", -1, 0, StationListIdentity.EmptyId, "-1", "-1", "-1");
            }

            if (r.Count < 0 || r.Cursor < -1 || r.Cursor > r.Count - 1)
            {
                return Placeholder("F");
            }

            string hash = IsHash(listId) ? listId.ToUpperInvariant() : StationListIdentity.EmptyId;
            if (r.Cursor + 1 >= r.Count)
            {
                return Build("T", -1, r.Count, hash, "-1", "-1", "-1");
            }

            if (!r.NextOk || r.MarginMax < 0.0)
            {
                return Placeholder("F");
            }

            string loc;
            string mb;
            string mf;
            if (!TryReal(r.NextLocation, out loc) || !TryReal(Math.Abs(r.MarginMin), out mb) || !TryReal(r.MarginMax, out mf))
            {
                return Placeholder("F");
            }

            return Build("K", r.Cursor + 1, r.Count, hash, loc, mb, mf);
        }

        /// <summary>The fixed form of a state that carries no station: "U" (temporarily unavailable); any other word is written as "F" (read failed).</summary>
        internal static string Placeholder(string state)
        {
            return Build(state == "U" ? "U" : "F", -1, -1, StationListIdentity.EmptyId, "-1", "-1", "-1");
        }

        /// <summary>The whole part as it stands in the telemetry line.</summary>
        internal static string Part(OfficialTargetReading r, string listId)
        {
            return Key + ":" + Value(r, listId);
        }

        private static string Build(string state, int idx, int count, string hash, string loc, string mb, string mf)
        {
            return Version.ToString(CultureInfo.InvariantCulture) + ":" + state + ":" + idx.ToString(CultureInfo.InvariantCulture) + ":" + count.ToString(CultureInfo.InvariantCulture)
                + ":" + hash + ":" + loc + ":" + mb + ":" + mf;
        }

        /// <summary>The canonical decimal text of v: -?(0|[1-9][0-9]{0,14})(.[0-9]{0,16}[1-9])?. false = v has no such text (NaN, Infinity, 1e15 or more, or a non-zero value that rounds to zero).</summary>
        internal static bool TryReal(double v, out string text)
        {
            text = null;
            if (double.IsNaN(v) || double.IsInfinity(v) || Math.Abs(v) >= 1e15)
            {
                return false;
            }

            if (v == 0.0)
            {
                text = "0";
                return true;
            }

            // The shortest of 15, 16 and 17 significant digits that reads back as v. ("R" is not used: on a 64-bit .NET Framework it can stop at 15 digits for a value that needs 16 or 17.)
            string s = null;
            for (int digits = 15; digits <= 17; digits++)
            {
                s = v.ToString("G" + digits.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
                double back;
                if (double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out back) && back == v)
                {
                    break;
                }
            }

            if (s.IndexOf('E') >= 0 || s.IndexOf('e') >= 0 || FractionDigits(s) > 17)
            {
                s = v.ToString("0.#################", CultureInfo.InvariantCulture);
            }

            if (s == "0" || s == "-0")
            {
                return false;
            }

            text = s;
            return true;
        }

        private static int FractionDigits(string s)
        {
            int dot = s.IndexOf('.');
            return dot < 0 ? 0 : s.Length - dot - 1;
        }

        private static bool IsHash(string s)
        {
            if (s == null || s.Length != 8)
            {
                return false;
            }

            for (int i = 0; i < 8; i++)
            {
                char c = s[i];
                bool hex = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f');
                if (!hex)
                {
                    return false;
                }
            }

            return true;
        }
    }
}
