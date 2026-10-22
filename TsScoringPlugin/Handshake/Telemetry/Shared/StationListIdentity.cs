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
}
