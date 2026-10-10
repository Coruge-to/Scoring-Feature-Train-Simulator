using System;
using System.Collections.Generic;

// ============================================================================
// PHASE LI1 - the Legacy INPUT telemetry: the handle group (REV POW BRK HTYPE ALLTXT) and the brake pressures (BCP, BPP) of the telemetry line.
// Host independent: the host is reached only through ILegacyInputApi (implemented by the one adapter file, LegacyTelemetryExtension.cs).
//
// Every Tick, on the host's Tick thread only, this class reads what the Legacy host gives and hands the groups it could build COMPLETELY to the line
// builder of the session; the session announces exactly those groups in AVAIL (handle / bcp / bpp). Nothing is guessed, defaulted or carried over:
//   * the handle group is built by LegacyHandleContract (the generic texts of the Current format) or it is not written and "handle" is not announced;
//   * BCP / BPP are the element 0 of the StateStore array and only when the array has exactly ONE element and it is finite. A missing, empty, longer or
//     non finite array is "not available": no key, no token, and an array of 2 or more elements is NOT reduced to its first element (its meaning is unknown);
//   * the unit is kPa as the host gives it and is written unchanged (no x1000, no /1000); the format is the one of the Current sender (one decimal);
//   * the reads are repeated every Tick, so a value or an availability of an earlier Tick (or of an earlier scenario generation) can never be re-used;
//   * bp_initial, the pressure rates, the virtual emergency brake, scores, vehicle length and map limits are NOT sent.
//
// Diagnostics (the dedicated diagnostic log only, never per Tick): one line per STATE CHANGE of a group (sent / dropped with a fixed reason), capped per
// scenario generation, and one summary line per generation. Only numbers and fixed words are written.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// Reads the input surface at most ONCE per Tick and gives every consumer of that Tick (the LI0 observation and the LI1 telemetry) the same answer, including
    /// a failure. BeginTick() is called by the session on the Tick thread before the first consumer. The native groups are passed through (the observation reads
    /// them only; they are not part of the telemetry).
    /// </summary>
    internal sealed class LegacyInputTickCache : ILegacyInputApi
    {
        private readonly ILegacyInputApi inner;
        private bool handlesRead;
        private bool handlesOk;
        private LegacyHandleSnapshot handlesValue;
        private string handlesReason;
        private bool storeRead;
        private bool storeOk;
        private LegacyStorePressure storeValue;
        private string storeReason;

        internal LegacyInputTickCache(ILegacyInputApi inner)
        {
            this.inner = inner;
        }

        internal void BeginTick()
        {
            handlesRead = false;
            handlesValue = null;
            storeRead = false;
            storeValue = null;
        }

        public bool NativeReachable
        {
            get { return inner.NativeReachable; }
        }

        public bool TryHandles(out LegacyHandleSnapshot snapshot, out string reason)
        {
            if (!handlesRead)
            {
                handlesRead = true;
                try
                {
                    handlesOk = inner.TryHandles(out handlesValue, out handlesReason);
                }
                catch
                {
                    handlesOk = false;
                    handlesValue = null;
                    handlesReason = LegacyInputReason.ReadException;
                }
            }

            snapshot = handlesValue;
            reason = handlesReason;
            return handlesOk;
        }

        public bool TryNativeSpec(out LegacySpecSnapshot spec, out string reason)
        {
            return inner.TryNativeSpec(out spec, out reason);
        }

        public bool TryNativePressure(out LegacyNativePressure pressure, out string reason)
        {
            return inner.TryNativePressure(out pressure, out reason);
        }

        public bool TryStorePressure(out LegacyStorePressure pressure, out string reason)
        {
            if (!storeRead)
            {
                storeRead = true;
                try
                {
                    storeOk = inner.TryStorePressure(out storeValue, out storeReason);
                }
                catch
                {
                    storeOk = false;
                    storeValue = null;
                    storeReason = LegacyInputReason.ReadException;
                }
            }

            pressure = storeValue;
            reason = storeReason;
            return storeOk;
        }
    }

    internal static class LegacyPressureContract
    {
        internal const string ReasonArrayNull = "array-null";
        internal const string ReasonArrayEmpty = "array-empty";
        internal const string ReasonArrayMulti = "array-multi";
        internal const string ReasonNonFinite = "nonfinite";

        /// <summary>
        /// The one value of a StateStore pressure array, in kPa as the host gives it. true only for an array of exactly ONE finite element. An array of two or
        /// more elements has no known meaning and is never reduced to an element; the reason is a fixed word and length is -1 for no array.
        /// </summary>
        internal static bool TryValue(double[] array, out double kPa, out string reason, out int length)
        {
            kPa = 0.0;
            reason = ReasonArrayNull;
            length = -1;
            if (array == null)
            {
                return false;
            }

            length = array.Length;
            if (array.Length == 0)
            {
                reason = ReasonArrayEmpty;
                return false;
            }

            if (array.Length > 1)
            {
                reason = ReasonArrayMulti;
                return false;
            }

            if (!TelemetryContract.Finite(array[0]))
            {
                reason = ReasonNonFinite;
                return false;
            }

            kPa = array[0];
            reason = null;
            return true;
        }

        /// <summary>The pressure as the Current sender writes it (one decimal, invariant culture). The value is never scaled.</summary>
        internal static string Format(double kPa)
        {
            return TelemetryContract.F(kPa, "F1");
        }
    }

    internal sealed class LegacyInputTelemetry
    {
        internal const int MaxLinesPerGeneration = 24;

        internal const string NameHandleSend = "TEL_HANDLE_SEND";
        internal const string NameHandleDrop = "TEL_HANDLE_DROP";
        internal const string NamePressureSend = "TEL_PRESSURE_SEND";
        internal const string NamePressureDrop = "TEL_PRESSURE_DROP";
        internal const string NameSummary = "TEL_INPUT_PUBLISH";

        private const string GroupHandle = "handle";
        private const string GroupBcp = "bcp";
        private const string GroupBpp = "bpp";

        private readonly ILegacyInputApi input;
        private readonly Action<string, string> log;
        private readonly Dictionary<string, string> lastState = new Dictionary<string, string>();

        private bool active;
        private int generation;
        private int ticks;
        private int lines;
        private int suppressed;
        private int handleSent;
        private int handleDropped;
        private int bcpSent;
        private int bcpDropped;
        private int bppSent;
        private int bppDropped;

        internal LegacyInputTelemetry(ILegacyInputApi input, Action<string, string> log)
        {
            this.input = input;
            this.log = log;
        }

        // -- the generation ---------------------------------------------------------------------------------------------------------------
        /// <summary>A new scenario generation: nothing of the previous one (no state, no counter, no remembered availability) is kept.</summary>
        internal void Begin(int scenarioId)
        {
            active = true;
            generation = scenarioId;
            ticks = 0;
            lines = 0;
            suppressed = 0;
            handleSent = 0;
            handleDropped = 0;
            bcpSent = 0;
            bcpDropped = 0;
            bppSent = 0;
            bppDropped = 0;
            lastState.Clear();
        }

        /// <summary>The generation ends: one summary line (when at least one Tick was composed), then idle until the next Begin.</summary>
        internal void End()
        {
            if (!active)
            {
                return;
            }

            active = false;
            lastState.Clear();
            if (ticks == 0)
            {
                return;
            }

            Write(NameSummary, "ticks=" + TelemetryContract.I(ticks) + " handleSent=" + TelemetryContract.I(handleSent) + " handleDropped=" + TelemetryContract.I(handleDropped)
                + " bcpSent=" + TelemetryContract.I(bcpSent) + " bcpDropped=" + TelemetryContract.I(bcpDropped)
                + " bppSent=" + TelemetryContract.I(bppSent) + " bppDropped=" + TelemetryContract.I(bppDropped) + " suppressed=" + TelemetryContract.I(suppressed));
        }

        // -- one Tick (Tick thread) -----------------------------------------------------------------------------------------------------------
        /// <summary>
        /// Reads the handles and the pressures now and calls group(token, key/value pairs) for every group that could be built completely. A group that
        /// cannot be built is simply not offered (so it is neither written nor announced).
        /// </summary>
        internal void Compose(Action<string, string[]> group)
        {
            if (!active)
            {
                return;
            }

            ticks++;
            try { ComposeHandle(group); } catch { Dropped(GroupHandle, LegacyInputReason.ReadException, -1); }
            try { ComposePressure(group); } catch { Dropped(GroupBcp, LegacyInputReason.ReadException, -1); Dropped(GroupBpp, LegacyInputReason.ReadException, -1); }
        }

        private void ComposeHandle(Action<string, string[]> group)
        {
            LegacyHandleSnapshot snapshot = null;
            string reason = null;
            bool ok;
            try { ok = input.TryHandles(out snapshot, out reason); }
            catch { ok = false; snapshot = null; reason = LegacyInputReason.ReadException; }
            if (!ok || snapshot == null)
            {
                Dropped(GroupHandle, SafeWord(reason, LegacyInputReason.SnapshotNull), -1);
                return;
            }

            LegacyHandleLine line;
            string why;
            if (!LegacyHandleContract.TryBuild(snapshot, out line, out why))
            {
                Dropped(GroupHandle, SafeWord(why, LegacyInputReason.ReadException), -1, HoldDetail(snapshot, why));
                return;
            }

            group(TelemetryContract.TokHandle, line.Pairs());
            handleSent++;
            // LI2: the independent holding speed notches (two-lever cab: holdN = the value the host reports, negated count, and holdPos=1 while the power handle is below zero)
            // are named in the same line; a layout without them writes exactly the LI1 line. The state includes holdPos, so entering / leaving a holding speed notch is one line each.
            // A value that is not a count (holdValidity != ok) is named too, whatever the layout.
            bool holdUsable = line.HoldRaw.HasValue && line.HoldRaw.Value != 0 && line.HoldValidity == LegacyHandleContract.HoldValidityOk;
            string extra = (holdUsable ? " holdN=" + TelemetryContract.I(line.HoldRaw.Value) : string.Empty) + (line.HoldPosition ? " holdPos=1" : string.Empty)
                + (line.HoldValidity != LegacyHandleContract.HoldValidityOk ? " holdN=" + HoldRawText(line.HoldRaw) + " holdValidity=" + line.HoldValidity : string.Empty);
            Changed(GroupHandle, "sent:" + line.Layout + (line.HoldPosition ? ":h" : string.Empty) + ":" + line.HoldValidity, NameHandleSend, "layout=" + line.Layout + " powN=" + TelemetryContract.I(PowerCount(snapshot))
                + " brkN=" + TelemetryContract.I(BrakeCount(snapshot)) + " ebN=" + TelemetryContract.I(line.BrkMax) + extra);
        }

        /// <summary>The raw value the host reported for HoldingSpeedNotchCount, or the word missing.</summary>
        internal static string HoldRawText(int? raw)
        {
            return raw.HasValue ? TelemetryContract.I(raw.Value) : "missing";
        }

        /// <summary>
        /// The detail of a handle drop whose reason is the holding speed count (holdn-missing / hold-range): the value, where it is read from and its validity, as fixed words and a number.
        /// Any other reason adds nothing.
        /// </summary>
        private static string HoldDetail(LegacyHandleSnapshot s, string why)
        {
            if (why != LegacyHandleContract.ReasonHoldNMissing && why != LegacyHandleContract.ReasonHoldNRange)
            {
                return string.Empty;
            }

            int? raw = s == null ? (int?)null : s.HoldingSpeedNotchCount;
            return " holdN=" + HoldRawText(raw) + " holdSource=" + LegacyHandleContract.HoldSource + " holdValidity=" + LegacyHandleContract.HoldValidity(raw);
        }

        private static int PowerCount(LegacyHandleSnapshot s) { return s.PowerNotchCount.HasValue ? s.PowerNotchCount.Value : -1; }

        private static int BrakeCount(LegacyHandleSnapshot s) { return s.BrakeNotchCount.HasValue ? s.BrakeNotchCount.Value : -1; }

        private void ComposePressure(Action<string, string[]> group)
        {
            LegacyStorePressure store = null;
            string reason = null;
            bool ok;
            try { ok = input.TryStorePressure(out store, out reason); }
            catch { ok = false; store = null; reason = LegacyInputReason.ReadException; }
            if (!ok || store == null)
            {
                string word = SafeWord(reason, LegacyInputReason.StoreNull);
                Dropped(GroupBcp, word, -1);
                Dropped(GroupBpp, word, -1);
                return;
            }

            double bc;
            string bcReason;
            int bcLength;
            if (LegacyPressureContract.TryValue(store.Bc, out bc, out bcReason, out bcLength))
            {
                group(TelemetryContract.TokBcp, new string[] { "BCP", LegacyPressureContract.Format(bc) });
                bcpSent++;
                Changed(GroupBcp, "sent", NamePressureSend, "group=bcp");
            }
            else
            {
                Dropped(GroupBcp, bcReason, bcLength);
            }

            double bp;
            string bpReason;
            int bpLength;
            if (LegacyPressureContract.TryValue(store.Bp, out bp, out bpReason, out bpLength))
            {
                group(TelemetryContract.TokBpp, new string[] { "BPP", LegacyPressureContract.Format(bp) });
                bppSent++;
                Changed(GroupBpp, "sent", NamePressureSend, "group=bpp");
            }
            else
            {
                Dropped(GroupBpp, bpReason, bpLength);
            }
        }

        // -- diagnostics ----------------------------------------------------------------------------------------------------------------------
        private void Dropped(string groupName, string reason, int length)
        {
            Dropped(groupName, reason, length, string.Empty);
        }

        /// <summary>extra = fixed " key=value" words appended to the line (and part of the state, so a different value is a different line).</summary>
        private void Dropped(string groupName, string reason, int length, string extra)
        {
            if (groupName == GroupHandle) { handleDropped++; }
            else if (groupName == GroupBcp) { bcpDropped++; }
            else { bppDropped++; }

            string word = SafeWord(reason, LegacyInputReason.ReadException);
            string state = "drop:" + word + (length >= 0 ? ":" + TelemetryContract.I(length) : string.Empty) + extra;
            string detail = (groupName == GroupHandle ? "reason=" : "group=" + groupName + " reason=") + word + (length >= 0 ? " len=" + TelemetryContract.I(length) : string.Empty) + extra;
            Changed(groupName, state, groupName == GroupHandle ? NameHandleDrop : NamePressureDrop, detail);
        }

        /// <summary>A line only when the state of the group differs from the last one written (never per Tick), within the per-generation cap.</summary>
        private void Changed(string groupName, string state, string name, string detail)
        {
            string previous;
            if (lastState.TryGetValue(groupName, out previous) && previous == state)
            {
                return;
            }

            lastState[groupName] = state;
            if (lines >= MaxLinesPerGeneration)
            {
                suppressed++;
                return;
            }

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

        /// <summary>Letters, digits, underscore and hyphen only (at most 40 characters); anything else becomes the fallback.</summary>
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
    }
}
