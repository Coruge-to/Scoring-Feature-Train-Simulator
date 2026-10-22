using System;
using System.Globalization;
using System.Text;

// ============================================================================
// PHASE PID-D4JA StationIndex ST-3a - the Jump wire codec, shared by BOTH senders (the BveEX plugin and the AtsEX telemetry DLL will link this one file; ST-3a links it
// into NEITHER project, so no DLL changes). Host independent and pure: no BVE / BveEX / AtsEX name, no file, no socket, no clock, no thread, no state. The Python twin is
// jump_wire.py; tests\jump_wire_vectors.json is the shared specification both are held to (Handshake\Tests\Test-JumpWireST3A.ps1 runs this file against it).
// Written in C# 5 syntax on purpose (the offline tests compile the product files directly).
//
// The wire (the body of the datagram; separator ':'; ASCII; no whitespace; the version is the FIELD COUNT; the RequestId is the Envelope field, never part of the body):
//   request v1 (read only)  JUMP_STA_TIME:<idx>:<time_ms>              JUMP_LOC_TIME:<location>:<time_ms>                                                      3 fields
//   request v2              JUMP_STA_TIME:<idx>:<time_ms>:<scenario_id>:<list_id>:<count>:<location>
//                           JUMP_LOC_TIME:<location>:<time_ms>:<scenario_id>:<list_id>:<count>:<idx>                                                         7 fields
//   completion v1 (read)    JUMP_COMPLETE:<STA|LOC>:<idx or -1>:<location>:<time_ms>:<jump_count>                                                           6 fields
//   completion v2           JUMP_COMPLETE:<STA|LOC>:<selected_idx>:<location>:<time_ms>:<jump_count>:<scenario_id>:<list_id>:<count>                       9 fields
// integers 0 | -?[1-9][0-9]*; list_id 8 characters 0-9 A-F; location -?(0|[1-9][0-9]*)(.[0-9]+)?([eE][+-]?[0-9]+)? with at most 17 significant digits, |x| <= 1e9 and
// (x == 0 or |x| >= 1e-9). -0.0 is normalised to +0.0. A position is read EXACTLY: the .NET Framework Double.Parse and the "R" format are not correctly rounded (measured: about
// one text in a thousand with 11 or more digits is read one unit in the last place away), so this file reads the text with its own integer arithmetic and writes the shortest of "G15", "G16", "G17"
// that reads back exactly (17 digits always do; "R" is not used). The first failing step gives the reason (see jump_wire.py for the order).
// ============================================================================
namespace TSScoringPlugin.DataPlane
{
    /// <summary>The scope in which a StationIndex means anything: (scenario id, list id, count).</summary>
    internal sealed class JumpWireScope
    {
        internal readonly int ScenarioId;
        internal readonly string ListId;
        internal readonly int Count;

        internal JumpWireScope(int scenarioId, string listId, int count)
        {
            ScenarioId = scenarioId;
            ListId = listId;
            Count = count;
        }
    }

    /// <summary>One read request. v1: Scope null; HasStationIndex false for LOC; HasLocation false for STA.</summary>
    internal sealed class JumpWireRequest
    {
        internal int Version;
        internal string Kind;
        internal bool HasStationIndex;
        internal int StationIndex;
        internal int TimeMs;
        internal bool HasLocation;
        internal double Location;
        internal JumpWireScope Scope;
    }

    /// <summary>One read completion. v1: Scope null (and SelectedIndex may be -1 for LOC). v2: everything set, 0 &lt;= SelectedIndex &lt; Scope.Count.</summary>
    internal sealed class JumpWireCompletion
    {
        internal int Version;
        internal string Kind;
        internal int SelectedIndex;
        internal double Location;
        internal int TimeMs;
        internal int JumpCount;
        internal JumpWireScope Scope;
    }

    internal static class JumpWire
    {
        internal const int V1 = 1;
        internal const int V2 = 2;
        internal const string KindSta = "STA";
        internal const string KindLoc = "LOC";
        internal const string PrefixSta = "JUMP_STA_TIME";
        internal const string PrefixLoc = "JUMP_LOC_TIME";
        internal const string PrefixComplete = "JUMP_COMPLETE";
        internal const int Int32Max = 2147483647;
        internal const int MaxSignificantDigits = 17;

        // the position contract, built from the IEEE-754 bits so that no compiler literal parse is involved: 1e9 and 1e-9
        internal static readonly double LocationMaxAbs = BitConverter.Int64BitsToDouble(0x41CDCD6500000000L);
        internal static readonly double LocationMinAbs = BitConverter.Int64BitsToDouble(0x3E112E0BE826D695L);

        // the reason words (fixed; they contain no value)
        internal const string REmpty = "empty";
        internal const string RPrefix = "prefix";
        internal const string RFieldCount = "field-count";
        internal const string RKind = "kind";
        internal const string RStationIndexSyntax = "station-index-syntax";
        internal const string RSelectedIdxSyntax = "selected-idx-syntax";
        internal const string RTimeSyntax = "time-syntax";
        internal const string RScenarioIdSyntax = "scenario-id-syntax";
        internal const string RListIdSyntax = "list-id-syntax";
        internal const string RCountSyntax = "count-syntax";
        internal const string RLocationSyntax = "location-syntax";
        internal const string RLocationPrecision = "location-precision";
        internal const string RJumpCountSyntax = "jump-count-syntax";
        internal const string RTimeRange = "time-range";
        internal const string RJumpCountRange = "jump-count-range";
        internal const string RScenarioIdRange = "scenario-id-range";
        internal const string RCountRange = "count-range";
        internal const string RLocationRange = "location-range";
        internal const string RStationIndexRange = "station-index-range";
        internal const string RSelectedIdxRange = "selected-idx-range";
        internal const string RScopeIncomplete = "scope-incomplete";

        internal static readonly string[] Reasons = new string[]
        {
            REmpty, RPrefix, RFieldCount, RKind, RStationIndexSyntax, RSelectedIdxSyntax, RTimeSyntax, RScenarioIdSyntax, RListIdSyntax, RCountSyntax,
            RLocationSyntax, RLocationPrecision, RJumpCountSyntax, RTimeRange, RJumpCountRange, RScenarioIdRange, RCountRange, RLocationRange,
            RStationIndexRange, RSelectedIdxRange, RScopeIncomplete
        };

        // -- the fields, by number ---------------------------------------------------------------------------------------------------------------------
        private const int FIdx = 0;
        private const int FSel = 1;
        private const int FTime = 2;
        private const int FScen = 3;
        private const int FList = 4;
        private const int FCount = 5;
        private const int FLoc = 6;
        private const int FJump = 7;
        private const int FieldTotal = 8;

        private static readonly string[] SyntaxReason = new string[]
        {
            RStationIndexSyntax, RSelectedIdxSyntax, RTimeSyntax, RScenarioIdSyntax, RListIdSyntax, RCountSyntax, RLocationSyntax, RJumpCountSyntax
        };

        private static readonly string[] RangeReason = new string[]
        {
            RStationIndexRange, RSelectedIdxRange, RTimeRange, RScenarioIdRange, null, RCountRange, RLocationRange, RJumpCountRange
        };

        // the layouts are in TEXTUAL order; the range orders are the order of the range phase
        private static readonly int[] LayoutReqV1Sta = new int[] { FIdx, FTime };
        private static readonly int[] LayoutReqV1Loc = new int[] { FLoc, FTime };
        private static readonly int[] LayoutReqV2Sta = new int[] { FIdx, FTime, FScen, FList, FCount, FLoc };
        private static readonly int[] LayoutReqV2Loc = new int[] { FLoc, FTime, FScen, FList, FCount, FIdx };
        private static readonly int[] LayoutCompV1 = new int[] { FSel, FLoc, FTime, FJump };
        private static readonly int[] LayoutCompV2 = new int[] { FSel, FLoc, FTime, FJump, FScen, FList, FCount };
        private static readonly int[] OrderReqV1Sta = new int[] { FTime, FIdx };
        private static readonly int[] OrderReqV1Loc = new int[] { FTime, FLoc };
        private static readonly int[] OrderReqV2 = new int[] { FTime, FScen, FCount, FLoc, FIdx };
        private static readonly int[] OrderCompV1 = new int[] { FTime, FJump, FLoc, FSel };
        private static readonly int[] OrderCompV2 = new int[] { FTime, FJump, FScen, FCount, FLoc, FSel };

        private const long Overflow = 1L << 40;               // stands for "an integer text longer than 11 characters": far outside Int32

        private sealed class Fields
        {
            internal readonly long[] I = new long[FieldTotal];
            internal string ListId;
            internal double Loc;
            internal string LocReason;                        // null, or location-range kept for the range phase
        }

        // -- reading ------------------------------------------------------------------------------------------------------------------------------------
        /// <summary>The v1 (3 fields) or v2 (7 fields) request, or null with the reason word. Never throws.</summary>
        internal static JumpWireRequest ParseRequest(string text, out string reason)
        {
            try
            {
                return ParseRequestCore(text, out reason);
            }
            catch
            {
                reason = RLocationRange;
                return null;
            }
        }

        private static JumpWireRequest ParseRequestCore(string text, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(text)) { reason = REmpty; return null; }
            string[] parts = text.Split(':');
            string kind;
            if (string.Equals(parts[0], PrefixSta, StringComparison.Ordinal)) kind = KindSta;
            else if (string.Equals(parts[0], PrefixLoc, StringComparison.Ordinal)) kind = KindLoc;
            else { reason = RPrefix; return null; }

            int version;
            int[] layout;
            int[] order;
            if (parts.Length == 3)
            {
                version = V1;
                layout = kind == KindSta ? LayoutReqV1Sta : LayoutReqV1Loc;
                order = kind == KindSta ? OrderReqV1Sta : OrderReqV1Loc;
            }
            else if (parts.Length == 7)
            {
                version = V2;
                layout = kind == KindSta ? LayoutReqV2Sta : LayoutReqV2Loc;
                order = OrderReqV2;
            }
            else { reason = RFieldCount; return null; }

            Fields f = new Fields();
            reason = ReadFields(layout, parts, 1, f);
            if (reason != null) return null;
            reason = CheckRanges(order, f, version);
            if (reason != null) return null;

            JumpWireRequest r = new JumpWireRequest();
            r.Version = version;
            r.Kind = kind;
            r.TimeMs = (int)f.I[FTime];
            r.HasStationIndex = Has(layout, FIdx);
            if (r.HasStationIndex) r.StationIndex = (int)f.I[FIdx];
            r.HasLocation = Has(layout, FLoc);
            if (r.HasLocation) r.Location = f.Loc;
            if (version == V2) r.Scope = new JumpWireScope((int)f.I[FScen], f.ListId, (int)f.I[FCount]);
            return r;
        }

        /// <summary>The v1 (6 fields) or v2 (9 fields) completion, or null with the reason word. Never throws.</summary>
        internal static JumpWireCompletion ParseCompletion(string text, out string reason)
        {
            try
            {
                return ParseCompletionCore(text, out reason);
            }
            catch
            {
                reason = RLocationRange;
                return null;
            }
        }

        private static JumpWireCompletion ParseCompletionCore(string text, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(text)) { reason = REmpty; return null; }
            string[] parts = text.Split(':');
            if (!string.Equals(parts[0], PrefixComplete, StringComparison.Ordinal)) { reason = RPrefix; return null; }
            int version;
            int[] layout;
            int[] order;
            if (parts.Length == 6) { version = V1; layout = LayoutCompV1; order = OrderCompV1; }
            else if (parts.Length == 9) { version = V2; layout = LayoutCompV2; order = OrderCompV2; }
            else { reason = RFieldCount; return null; }
            if (!string.Equals(parts[1], KindSta, StringComparison.Ordinal) && !string.Equals(parts[1], KindLoc, StringComparison.Ordinal)) { reason = RKind; return null; }

            Fields f = new Fields();
            reason = ReadFields(layout, parts, 2, f);
            if (reason != null) return null;
            reason = CheckRanges(order, f, version);
            if (reason != null) return null;

            JumpWireCompletion c = new JumpWireCompletion();
            c.Version = version;
            c.Kind = parts[1];
            c.SelectedIndex = (int)f.I[FSel];
            c.Location = f.Loc;
            c.TimeMs = (int)f.I[FTime];
            c.JumpCount = (int)f.I[FJump];
            if (version == V2) c.Scope = new JumpWireScope((int)f.I[FScen], f.ListId, (int)f.I[FCount]);
            return c;
        }

        private static bool Has(int[] layout, int field)
        {
            for (int i = 0; i < layout.Length; i++) if (layout[i] == field) return true;
            return false;
        }

        /// <summary>The syntax phase: null, or the reason of the first field (in textual order) that is not of its form.</summary>
        private static string ReadFields(int[] layout, string[] parts, int offset, Fields f)
        {
            for (int i = 0; i < layout.Length; i++)
            {
                int field = layout[i];
                string text = parts[offset + i];
                if (field == FList)
                {
                    if (!IsListId(text)) return SyntaxReason[field];
                    f.ListId = text;
                }
                else if (field == FLoc)
                {
                    double value;
                    string why = ParseLocation(text, out value);
                    if (why == RLocationSyntax || why == RLocationPrecision) return why;
                    f.Loc = value;
                    f.LocReason = why;
                }
                else
                {
                    if (!IsIntText(text)) return SyntaxReason[field];
                    f.I[field] = IntValue(text);
                }
            }
            return null;
        }

        /// <summary>The range phase: null, or the reason of the first failing field of `order`.</summary>
        private static string CheckRanges(int[] order, Fields f, int version)
        {
            for (int i = 0; i < order.Length; i++)
            {
                int field = order[i];
                if (field == FLoc)
                {
                    if (f.LocReason != null) return RLocationRange;
                    continue;
                }
                long v = f.I[field];
                bool ok;
                if (version == V1) ok = v >= int.MinValue && v <= Int32Max;
                else if (field == FCount) ok = v >= 1 && v <= Int32Max;
                else if (field == FIdx || field == FSel) ok = v >= 0 && v < f.I[FCount];
                else ok = v >= 0 && v <= Int32Max;
                if (!ok) return RangeReason[field];
            }
            return null;
        }

        // -- integers and the list id ---------------------------------------------------------------------------------------------------------------------
        private static bool IsIntText(string s)
        {
            if (s == null || s.Length == 0) return false;
            int p = 0;
            if (s[0] == '-') p = 1;
            if (p >= s.Length) return false;
            if (s[p] == '0') return p == 0 && s.Length == 1;              // "0" only: no "-0", no leading zero
            for (int i = p; i < s.Length; i++)
            {
                if (s[i] < '0' || s[i] > '9') return false;
            }
            return true;
        }

        private static long IntValue(string s)
        {
            bool neg = s[0] == '-';
            int p = neg ? 1 : 0;
            if (s.Length - p > 10) return neg ? -Overflow : Overflow;
            long v = 0;
            for (int i = p; i < s.Length; i++) v = v * 10 + (s[i] - '0');
            return neg ? -v : v;
        }

        private static bool IsListId(string s)
        {
            if (s == null || s.Length != 8) return false;
            for (int i = 0; i < 8; i++)
            {
                char c = s[i];
                if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'))) return false;
            }
            return true;
        }

        // -- scope ----------------------------------------------------------------------------------------------------------------------------------------
        /// <summary>The scope, or null with the reason: the syntax word of the list id first, then the ranges (scenario id, count).</summary>
        internal static JumpWireScope ValidateScope(int scenarioId, string listId, int count, out string reason)
        {
            reason = null;
            if (!IsListId(listId)) { reason = RListIdSyntax; return null; }
            if (scenarioId < 0) { reason = RScenarioIdRange; return null; }
            if (count < 1) { reason = RCountRange; return null; }
            return new JumpWireScope(scenarioId, listId, count);
        }

        // -- location -------------------------------------------------------------------------------------------------------------------------------------
        /// <summary>The reason word (location-syntax, location-precision, location-range) or null; `value` is the correctly rounded double (0.0 for any zero) when the reason is null.</summary>
        internal static string ParseLocation(string text, out double value)
        {
            value = 0.0;
            if (text == null) return RLocationSyntax;
            int n = text.Length;
            int p = 0;
            bool negative = false;
            if (p < n && text[p] == '-') { negative = true; p++; }
            if (p >= n) return RLocationSyntax;
            int intStart = p;
            if (text[p] == '0') p++;
            else if (text[p] >= '1' && text[p] <= '9') { while (p < n && text[p] >= '0' && text[p] <= '9') p++; }
            else return RLocationSyntax;
            int intEnd = p;
            int fracStart = p;
            int fracEnd = p;
            if (p < n && text[p] == '.')
            {
                p++;
                fracStart = p;
                while (p < n && text[p] >= '0' && text[p] <= '9') p++;
                fracEnd = p;
                if (fracEnd == fracStart) return RLocationSyntax;
            }
            bool expNegative = false;
            int expStart = p;
            int expEnd = p;
            if (p < n && (text[p] == 'e' || text[p] == 'E'))
            {
                p++;
                if (p < n && (text[p] == '+' || text[p] == '-')) { expNegative = text[p] == '-'; p++; }
                expStart = p;
                while (p < n && text[p] >= '0' && text[p] <= '9') p++;
                expEnd = p;
                if (expEnd == expStart) return RLocationSyntax;
            }
            if (p != n) return RLocationSyntax;

            // the significant digits: the integer and the fraction digits without the leading zeros, and without the trailing zeros
            StringBuilder all = new StringBuilder();
            all.Append(text, intStart, intEnd - intStart);
            all.Append(text, fracStart, fracEnd - fracStart);
            string digits = all.ToString().TrimStart('0');
            if (digits.Length == 0) return null;                                        // a zero is a zero whatever its exponent, and never -0.0
            string stripped = digits.TrimEnd('0');
            if (stripped.Length > MaxSignificantDigits) return RLocationPrecision;
            string expDigits = text.Substring(expStart, expEnd - expStart).TrimStart('0');
            if (expDigits.Length > 6) return RLocationRange;
            int exponent = 0;
            for (int i = 0; i < expDigits.Length; i++) exponent = exponent * 10 + (expDigits[i] - '0');
            if (expNegative) exponent = -exponent;
            int fractionLength = fracEnd - fracStart;
            int e10 = exponent - fractionLength + (digits.Length - stripped.Length);       // value = stripped * 10 ^ e10
            int order = stripped.Length + e10;                                              // 10 ^ (order - 1) <= |value| < 10 ^ order
            if (order > 10 || order < -8) return RLocationRange;

            ulong mantissa = 0;
            for (int i = 0; i < stripped.Length; i++) mantissa = mantissa * 10 + (ulong)(stripped[i] - '0');
            double magnitude;
            if (e10 >= 0)
            {
                ulong scaled = mantissa;
                for (int i = 0; i < e10; i++) scaled *= 10;                                // |value| < 1e10: no overflow
                magnitude = (double)scaled;                                                // below 2^53: exact
            }
            else
            {
                magnitude = ExactQuotient(mantissa, -e10);
            }
            if (magnitude > LocationMaxAbs || magnitude < LocationMinAbs) return RLocationRange;
            value = negative ? -magnitude : magnitude;
            return null;
        }

        /// <summary>The position as a number inside the contract (-0.0 becomes 0.0), or the reason (location-range).</summary>
        internal static string NormalizeLocation(double value, out double normalized)
        {
            normalized = 0.0;
            if (double.IsNaN(value) || double.IsInfinity(value)) return RLocationRange;
            if (value == 0.0) return null;
            double a = Math.Abs(value);
            if (a > LocationMaxAbs || a < LocationMinAbs) return RLocationRange;
            normalized = value;
            return null;
        }

        /// <summary>The text of a position that reads back (ParseLocation) to exactly the same double, or null with the reason. The shortest of "G15", "G16", "G17" (invariant culture)
        /// that reads back EXACTLY: 15 digits are enough for every short map value, 17 digits always identify a double. ("R" is not used: it accepts a 15 digit text that the BCL parse
        /// reads back but a correct parse does not.)</summary>
        internal static string FormatLocation(double value, out string reason)
        {
            double x;
            reason = NormalizeLocation(value, out x);
            if (reason != null) return null;
            if (x == 0.0) return "0";
            string[] formats = new string[] { "G15", "G16", "G17" };
            for (int i = 0; i < formats.Length; i++)
            {
                string text = x.ToString(formats[i], CultureInfo.InvariantCulture);
                if (ReadsBack(text, x)) return text;
            }
            reason = RLocationRange;
            return null;
        }
        private static bool ReadsBack(string text, double expected)
        {
            double back;
            string why = ParseLocation(text, out back);
            return why == null && BitConverter.DoubleToInt64Bits(back) == BitConverter.DoubleToInt64Bits(expected);
        }

        // -- exact decimal -> double (no floating point arithmetic, no Double.Parse) -----------------------------------------------------------------------
        private const int Words = 6;                           // 192 bits: the numerator is at most 57 + 139 bits

        /// <summary>mantissa / 10^k (1 &lt;= k &lt;= 25, mantissa &lt; 10^17) rounded to the nearest double, ties to even.</summary>
        private static double ExactQuotient(ulong mantissa, int k)
        {
            uint[] den = new uint[Words];
            den[0] = 1;
            for (int i = 0; i < k; i++) MulSmall(den, 10);
            uint[] num = new uint[Words];
            num[0] = (uint)(mantissa & 0xFFFFFFFFUL);
            num[1] = (uint)(mantissa >> 32);
            int bn = BitLength(num);
            int bd = BitLength(den);
            int s = 56 - (bn - bd);                             // mantissa / 10^k * 2^s lies in (2^55, 2^57)
            uint[] rem = ShiftLeft(num, s);
            ulong q = 0;
            for (int i = 57; i >= 0; i--)
            {
                uint[] t = ShiftLeft(den, i);
                if (Compare(rem, t) >= 0)
                {
                    Subtract(rem, t);
                    q |= 1UL << i;
                }
            }
            bool sticky = !IsZero(rem);
            int bits = 0;
            for (ulong z = q; z != 0; z >>= 1) bits++;
            int drop = bits - 53;                               // 3 or 4
            ulong half = 1UL << (drop - 1);
            ulong low = q & ((1UL << drop) - 1);
            ulong m = q >> drop;
            if (low > half || (low == half && (sticky || (m & 1UL) == 1UL))) m++;
            if (m == (1UL << 53)) { m >>= 1; drop++; }
            int e2 = drop - s;                                  // value = m * 2^e2, 2^52 <= m < 2^53
            long biased = (long)e2 + 52 + 1023;
            long pattern = (biased << 52) | (long)(m & 0xFFFFFFFFFFFFFUL);
            return BitConverter.Int64BitsToDouble(pattern);
        }

        private static void MulSmall(uint[] a, uint m)
        {
            ulong carry = 0;
            for (int i = 0; i < Words; i++)
            {
                ulong v = (ulong)a[i] * m + carry;
                a[i] = (uint)(v & 0xFFFFFFFFUL);
                carry = v >> 32;
            }
        }

        private static uint[] ShiftLeft(uint[] a, int n)
        {
            uint[] r = new uint[Words];
            int ws = n / 32;
            int bs = n % 32;
            for (int i = Words - 1; i >= 0; i--)
            {
                int src = i - ws;
                uint hi = 0;
                uint lo = 0;
                if (src >= 0) hi = a[src] << bs;
                if (bs > 0 && src - 1 >= 0) lo = a[src - 1] >> (32 - bs);
                r[i] = hi | lo;
            }
            return r;
        }

        private static int Compare(uint[] a, uint[] b)
        {
            for (int i = Words - 1; i >= 0; i--)
            {
                if (a[i] != b[i]) return a[i] > b[i] ? 1 : -1;
            }
            return 0;
        }

        private static void Subtract(uint[] a, uint[] b)
        {
            long borrow = 0;
            for (int i = 0; i < Words; i++)
            {
                long v = (long)a[i] - (long)b[i] - borrow;
                if (v < 0) { v += 4294967296L; borrow = 1; } else borrow = 0;
                a[i] = (uint)v;
            }
        }

        private static bool IsZero(uint[] a)
        {
            for (int i = 0; i < Words; i++) if (a[i] != 0) return false;
            return true;
        }

        private static int BitLength(uint[] a)
        {
            for (int i = Words - 1; i >= 0; i--)
            {
                if (a[i] != 0)
                {
                    int b = 0;
                    for (uint z = a[i]; z != 0; z >>= 1) b++;
                    return i * 32 + b;
                }
            }
            return 0;
        }

        // -- writing (v2 only) ----------------------------------------------------------------------------------------------------------------------------
        /// <summary>The v2 request of `kind` (STA / LOC) at `stationIndex` of `scope`, or null with the reason. The one place a request is assembled.</summary>
        internal static string FormatRequestV2(string kind, int stationIndex, int timeMs, JumpWireScope scope, double location, out string reason)
        {
            reason = null;
            if (kind != KindSta && kind != KindLoc) { reason = RKind; return null; }
            if (scope == null) { reason = RScopeIncomplete; return null; }
            int[] layout = kind == KindSta ? LayoutReqV2Sta : LayoutReqV2Loc;
            if (!IsListId(scope.ListId)) { reason = RListIdSyntax; return null; }
            Fields f = new Fields();
            f.I[FIdx] = stationIndex;
            f.I[FTime] = timeMs;
            f.I[FScen] = scope.ScenarioId;
            f.I[FCount] = scope.Count;
            f.ListId = scope.ListId;
            f.LocReason = NormalizeLocation(location, out f.Loc);
            reason = CheckRanges(OrderReqV2, f, V2);
            if (reason != null) return null;
            string locationText = FormatLocation(f.Loc, out reason);
            if (reason != null) return null;
            string[] texts = new string[FieldTotal];
            texts[FIdx] = stationIndex.ToString(CultureInfo.InvariantCulture);
            texts[FTime] = timeMs.ToString(CultureInfo.InvariantCulture);
            texts[FScen] = scope.ScenarioId.ToString(CultureInfo.InvariantCulture);
            texts[FList] = scope.ListId;
            texts[FCount] = scope.Count.ToString(CultureInfo.InvariantCulture);
            texts[FLoc] = locationText;
            return Assemble(kind == KindSta ? PrefixSta : PrefixLoc, null, layout, texts);
        }

        /// <summary>The v2 completion of `kind` that selected `selectedIdx` of `scope`, or null with the reason.</summary>
        internal static string FormatCompletionV2(string kind, int selectedIdx, double location, int timeMs, int jumpCount, JumpWireScope scope, out string reason)
        {
            reason = null;
            if (kind != KindSta && kind != KindLoc) { reason = RKind; return null; }
            if (scope == null) { reason = RScopeIncomplete; return null; }
            if (!IsListId(scope.ListId)) { reason = RListIdSyntax; return null; }
            Fields f = new Fields();
            f.I[FSel] = selectedIdx;
            f.I[FTime] = timeMs;
            f.I[FJump] = jumpCount;
            f.I[FScen] = scope.ScenarioId;
            f.I[FCount] = scope.Count;
            f.ListId = scope.ListId;
            f.LocReason = NormalizeLocation(location, out f.Loc);
            reason = CheckRanges(OrderCompV2, f, V2);
            if (reason != null) return null;
            string locationText = FormatLocation(f.Loc, out reason);
            if (reason != null) return null;
            string[] texts = new string[FieldTotal];
            texts[FSel] = selectedIdx.ToString(CultureInfo.InvariantCulture);
            texts[FLoc] = locationText;
            texts[FTime] = timeMs.ToString(CultureInfo.InvariantCulture);
            texts[FJump] = jumpCount.ToString(CultureInfo.InvariantCulture);
            texts[FScen] = scope.ScenarioId.ToString(CultureInfo.InvariantCulture);
            texts[FList] = scope.ListId;
            texts[FCount] = scope.Count.ToString(CultureInfo.InvariantCulture);
            return Assemble(PrefixComplete, kind, LayoutCompV2, texts);
        }

        private static string Assemble(string prefix, string kind, int[] layout, string[] texts)
        {
            StringBuilder sb = new StringBuilder(prefix);
            if (kind != null) sb.Append(':').Append(kind);
            for (int i = 0; i < layout.Length; i++) sb.Append(':').Append(texts[layout[i]]);
            return sb.ToString();
        }
    }
}
