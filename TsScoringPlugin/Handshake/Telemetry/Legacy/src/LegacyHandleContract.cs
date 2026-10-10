using System;
using System.Text;

// ============================================================================
// PHASE LI1 / LI2 - the handle group of the telemetry line (REV, POW, BRK, HTYPE, ALLTXT) for the AtsEX LEGACY sender, host independent.
//
// The CURRENT sender (BveEX, TsScoringPlugin\Class1.cs) writes these keys from the texts the vehicle defines. The Legacy host does not give those
// texts, so this file builds the generic texts from the NUMBERS the host does give (handle positions and the notch layout) and writes them in
// EXACTLY the Current format - the Python reader, the HUD and the AVAIL token "handle" are the Current ones, unchanged:
//
//     REV:<text>:<-1|0|1>                       POW:<text>:<notch>                    BRK:<text>:<notch>:<emergency notch>
//     HTYPE:<1 one lever | 2 two lever>         ALLTXT:<rev texts>:<power texts>:<brake texts>:<holding speed texts>      (texts joined by '_')
//
// Generic texts (nothing else is ever written):
//     reverser            -1 back, 0 off, 1 forward                                    (the three Japanese words below)
//     one lever  Ecb/Smee power N (position 0), P1..Pn      brake N, B1..B(e-1), EB     the handle shows the power text, else the brake text
//     one lever  Cl       power Run (position 0), P1..Pn    brake Run, Lap, Service, Emergency
//     two lever  Ecb/Smee power P0..Pn                      brake B0, B1..B(e-1), EB
//     two lever  Cl       power P0..Pn                      brake Run, Lap, Service, Emergency (EB notch and above emergency)
//     HoldingSpeedBrake   the brake position 1 is the holding speed brake, any cab / brake kind:
//                         Ecb/Smee one lever  N, HoldBrake, B1..B(b-1), EB      two lever  B0, HoldBrake, B1..B(b-1), EB      Cl (one and two lever)  Run, HoldBrake, Service, Emergency
//     TWO lever only (any brake kind, with or without the holding speed brake): independent holding speed notches (HoldingSpeedNotchCount = -h, h > 0):
//                         power H1..Hh at POW = -1..-h, holding texts H1_..._Hh
// where n = NotchInfo.PowerNotchCount, b = NotchInfo.BrakeNotchCount and e = NotchInfo.EmergencyBrakeNotch (the emergency boundary is what the host
// reports, never derived).
//
// THE 24 COMBINATIONS (cab one / two lever x Ecb / Smee / Cl x HoldingSpeedNotchCount 0 / set x HoldingSpeedBrake false / true) were all observed on the
// real BVE5 (artificial vehicles included); the two features below are independent of each other and of the brake kind:
//     * HasHoldingSpeedBrake ("holding speed brake"): the first BRAKE position (brk = 1) is the holding speed brake; shown as the Japanese word below
//       in the BRAKE column, never as H1. It is NOT HoldingSpeedNotchCount = 1. It is valid for every cab and brake kind.
//     * HoldingSpeedNotchCount != 0 ("independent holding speed notches"): the POWER side of a TWO-lever cab goes below zero (POW = -1..-h), shown as H1..Hh.
//       The host reports the count NEGATED (the lower bound of POW: a car with 5 notches reports -5; confirmed on the real machine and in the BVE5 vehicle loader),
//       so h = -HoldingSpeedNotchCount. The BRAKE side is not touched by it. It is valid for every brake kind (Cl included) and together with the holding speed brake.
//   A ONE-lever cab with a HoldingSpeedNotchCount is an ordinary one-lever cab (the host never reports POW < 0 for it; the notches are not operable there).
//   The setting alone is never a reason to refuse it.
//
// What is NOT built (the group is then not written at all and "handle" is not announced - no placeholder, no guess):
//     * an unknown cab type / brake kind, a missing or out-of-range value, a layout that is not one described above (Cl: brake notches 2, emergency notch 3)
//     * POW above n; POW below zero on a ONE-lever cab; POW below -h on a two-lever cab, or POW below zero there when the count is unreadable / not a count
//       (holdn-missing / hold-range): only those positions, not the whole cab
//     * BRK below zero or above the emergency notch; a ONE-lever cab with power and brake both positive (a single handle cannot hold both)
// The reasons are fixed words; no exception text, no vehicle text. (The former reasons holding-unconfirmed / holding-cl are gone: every holding speed brake combination is built.)
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>The handle group as the Current format wants it. Every member is the final wire text or the number it came from.</summary>
    internal sealed class LegacyHandleLine
    {
        internal int HandleType;             // HTYPE: 1 one lever, 2 two lever
        internal string RevText;
        internal int RevPos;
        internal string PowText;
        internal int PowNotch;
        internal string BrkText;
        internal int BrkNotch;
        internal int BrkMax;                 // the emergency brake notch of the host
        internal string AllRev;
        internal string AllPow;
        internal string AllBrk;
        internal string AllHold = string.Empty;   // the independent holding speed texts H1_..._Hh (empty when there are none)
        internal string Layout;              // fixed words for the diagnostic log: one-lever-ecb, two-lever-cl, two-lever-ecb-holdbrake, ...
        internal int HoldNotchCount;         // the number of independent holding speed notches (-HoldingSpeedNotchCount when it is -1..-99, else 0); the display uses it on a two-lever cab only (any brake kind)
        internal int? HoldRaw;               // HoldingSpeedNotchCount exactly as the host reports it (null = unreadable); diagnostic only
        internal string HoldValidity;        // ok / missing / range of HoldRaw; diagnostic only
        internal bool HoldPosition;          // the power handle is at an independent holding speed notch (POW below zero); diagnostic only

        /// <summary>The key / value pairs in the order of the Current line (HTYPE before ALLTXT: the reader needs the handle type to size the brake texts).</summary>
        internal string[] Pairs()
        {
            return new string[]
            {
                "REV", RevText + ":" + TelemetryContract.I(RevPos),
                "POW", PowText + ":" + TelemetryContract.I(PowNotch),
                "BRK", BrkText + ":" + TelemetryContract.I(BrkNotch) + ":" + TelemetryContract.I(BrkMax),
                "HTYPE", TelemetryContract.I(HandleType),
                "ALLTXT", AllRev + ":" + AllPow + ":" + AllBrk + ":" + AllHold
            };
        }
    }

    internal static class LegacyHandleContract
    {
        /// <summary>A layout beyond this is not a vehicle of this product; it also bounds the length of the generated texts.</summary>
        internal const int MaxNotches = 99;

        // the Japanese words of the generic display (escaped: the source is read the same way whatever the code page)
        internal const string RevBack = "後";  // back
        internal const string RevOff = "切";  // reverser off
        internal const string RevForward = "前";  // forward
        internal const string ClRun = "運転";  // Cl brake position 0 (running); also the one-lever Cl handle at rest
        internal const string ClLap = "重なり";  // lap
        internal const string ClService = "常用";  // service
        internal const string ClEmergency = "非常";  // emergency
        internal const string HoldBrake = "抑速";  // the holding speed BRAKE position (brake position 1); not H1

        internal const string TextNeutral = "N";
        internal const string TextEmergency = "EB";

        // fixed reason words
        internal const string ReasonSnapshotNull = "snapshot-null";
        internal const string ReasonTypeUnknown = "type-unknown";
        internal const string ReasonBrakeUnknown = "brake-unknown";
        internal const string ReasonRevMissing = "rev-missing";
        internal const string ReasonRevRange = "rev-range";
        internal const string ReasonPowMissing = "pow-missing";
        internal const string ReasonPowRange = "pow-range";
        internal const string ReasonBrkMissing = "brk-missing";
        internal const string ReasonBrkRange = "brk-range";
        internal const string ReasonLayoutMissing = "layout-missing";
        internal const string ReasonLayoutRange = "layout-range";
        internal const string ReasonEbLayout = "eb-layout";
        internal const string ReasonClLayout = "cl-layout";
        internal const string ReasonHoldMissing = "hold-missing";
        internal const string ReasonHoldNMissing = "holdn-missing";            // HoldingSpeedNotchCount cannot be read (never replaced by PowerNotchCount)
        internal const string ReasonHoldNRange = "hold-range";
        internal const string ReasonPowBrkBoth = "pow-brk-both";               // a one-lever cab with power and brake both positive

        // NotchInfo.HoldingSpeedNotchCount as the host reports it: 0 = no independent holding speed notches, -n = n of them (-1..-MaxNotches)
        internal const string HoldSource = "notchinfo";            // the one public API member the count is read from (never PowerNotchCount)
        internal const string HoldValidityOk = "ok";
        internal const string HoldValidityMissing = "missing";     // the property could not be read
        internal const string HoldValidityRange = "range";         // above 0 or below -MaxNotches: not a count

        /// <summary>The validity word of a raw HoldingSpeedNotchCount: ok (-MaxNotches..0), missing (unreadable) or range.</summary>
        internal static string HoldValidity(int? raw)
        {
            if (!raw.HasValue)
            {
                return HoldValidityMissing;
            }

            return raw.Value > 0 || raw.Value < -MaxNotches ? HoldValidityRange : HoldValidityOk;
        }

        internal static string ReverserText(int position)
        {
            return position < 0 ? RevBack : position == 0 ? RevOff : RevForward;
        }

        /// <summary>
        /// The handle group of one Tick from the snapshot of the host, or false with a fixed reason. All or nothing: a group that cannot be built completely
        /// is not written. The reverser is -1, 0 or 1 only; an emergency position is any brake position at or above the emergency notch of the host.
        /// </summary>
        internal static bool TryBuild(LegacyHandleSnapshot h, out LegacyHandleLine line, out string reason)
        {
            line = null;
            reason = ReasonSnapshotNull;
            if (h == null)
            {
                return false;
            }

            if (h.HandleType != LegacyHandleType.OneLever && h.HandleType != LegacyHandleType.TwoLever)
            {
                reason = ReasonTypeUnknown;
                return false;
            }

            if (h.BrakeKind != LegacyBrakeKind.Ecb && h.BrakeKind != LegacyBrakeKind.Smee && h.BrakeKind != LegacyBrakeKind.Cl)
            {
                reason = ReasonBrakeUnknown;
                return false;
            }

            bool oneLever = h.HandleType == LegacyHandleType.OneLever;
            bool cl = h.BrakeKind == LegacyBrakeKind.Cl;

            if (!h.Reverser.HasValue) { reason = ReasonRevMissing; return false; }
            if (!h.Power.HasValue) { reason = ReasonPowMissing; return false; }
            if (!h.Brake.HasValue) { reason = ReasonBrkMissing; return false; }
            if (!h.PowerNotchCount.HasValue || !h.BrakeNotchCount.HasValue || !h.EmergencyBrakeNotch.HasValue) { reason = ReasonLayoutMissing; return false; }
            if (!h.HasHoldingSpeedBrake.HasValue) { reason = ReasonHoldMissing; return false; }

            bool holdBrake = h.HasHoldingSpeedBrake.Value;       // valid for every cab and brake kind (all 24 combinations were observed)

            int rev = h.Reverser.Value;
            int pow = h.Power.Value;
            int brk = h.Brake.Value;
            int powN = h.PowerNotchCount.Value;
            int brkN = h.BrakeNotchCount.Value;
            int ebN = h.EmergencyBrakeNotch.Value;

            if (powN < 0 || powN > MaxNotches || brkN < 1 || brkN > MaxNotches || ebN < 1 || ebN > MaxNotches + 1) { reason = ReasonLayoutRange; return false; }
            if (cl)
            {
                // the only Cl layout seen on the host (one lever and two lever): 2 service positions (lap, service) and the emergency position 3
                if (brkN != 2 || ebN != 3) { reason = ReasonClLayout; return false; }
            }
            else if (ebN != brkN + 1)
            {
                reason = ReasonEbLayout;         // B1..Bn and EB only fit when the emergency notch directly follows the service notches
                return false;
            }

            if (rev < -1 || rev > 1) { reason = ReasonRevRange; return false; }

            // independent holding speed notches: on a TWO-lever cab, every brake kind, with or without the holding speed brake. On a one-lever cab POW below zero is not a known state.
            // NotchInfo.HoldingSpeedNotchCount is the LOWER BOUND of POW as the host stores it: BVE5 reads the vehicle's count n and keeps -n (real machine: 5 notches = -5),
            // so the number of notches is the negated value. A value that is missing, above 0 or below -MaxNotches is not a count: it is never repaired or guessed.
            // An unusable count takes only the POW-below-zero positions away; no count is guessed for them.
            bool independent = !oneLever;
            int holdN = 0;
            string holdWhy = null;
            if (independent)
            {
                string validity = HoldValidity(h.HoldingSpeedNotchCount);
                if (validity == HoldValidityMissing) { holdWhy = ReasonHoldNMissing; }
                else if (validity == HoldValidityRange) { holdWhy = ReasonHoldNRange; }
                else { holdN = -h.HoldingSpeedNotchCount.Value; }
            }

            // POW below zero needs a readable count; POW 0 and above (and the brake) are independent of it, so an unreadable count takes only the H positions away
            if (pow < 0 && holdWhy != null) { reason = holdWhy; return false; }
            if (pow < -holdN || pow > powN) { reason = ReasonPowRange; return false; }
            if (brk < 0 || brk > ebN) { reason = ReasonBrkRange; return false; }      // at the emergency notch is EB / the emergency word; beyond it is not a position
            if (oneLever && pow > 0 && brk > 0) { reason = ReasonPowBrkBoth; return false; }   // a single handle cannot hold power and brake

            LegacyHandleLine l = new LegacyHandleLine();
            l.HandleType = oneLever ? 1 : 2;
            l.RevPos = rev;
            l.RevText = ReverserText(rev);
            l.AllRev = RevBack + "_" + RevOff + "_" + RevForward;
            l.PowNotch = pow;
            l.PowText = PowerText(pow, oneLever, cl);
            l.AllPow = AllPowerTexts(powN, oneLever, cl);
            l.BrkNotch = brk;
            l.BrkMax = ebN;
            if (cl)
            {
                // Run, Lap (or the holding speed brake word at position 1), Service, Emergency; one lever: position 0 is the handle at rest (index 0 of the list;
                // the reader leaves it out of the width of a one-lever handle)
                string second = holdBrake ? HoldBrake : ClLap;
                l.BrkText = brk >= ebN ? ClEmergency : brk == 0 ? ClRun : brk == 1 ? second : ClService;
                l.AllBrk = ClRun + "_" + second + "_" + ClService + "_" + ClEmergency;
            }
            else if (holdBrake)
            {
                l.BrkText = HoldBrakeBrakeText(brk, ebN, oneLever);
                l.AllBrk = AllHoldBrakeTexts(ebN, oneLever);
            }
            else
            {
                l.BrkText = brk >= ebN ? TextEmergency : BrakeText(brk, oneLever);
                l.AllBrk = AllBrakeTexts(ebN, oneLever);
            }

            if (independent && holdN > 0)
            {
                l.AllHold = AllHoldingTexts(holdN);
            }

            // diagnostic only: the value as the host reports it (-1..-99 = that many notches) and its validity, named in the log of any layout so that a setting that is ignored
            // (one lever, holding speed brake) or an unusable value (the independent layout without a readable count) is visible too
            l.HoldRaw = h.HoldingSpeedNotchCount;
            l.HoldValidity = HoldValidity(h.HoldingSpeedNotchCount);
            l.HoldNotchCount = h.HoldingSpeedNotchCount.HasValue && l.HoldValidity == HoldValidityOk ? -h.HoldingSpeedNotchCount.Value : 0;
            l.HoldPosition = pow < 0;
            l.Layout = (oneLever ? "one-lever-" : "two-lever-") + (cl ? "cl" : h.BrakeKind == LegacyBrakeKind.Smee ? "smee" : "ecb") + (holdBrake ? "-holdbrake" : string.Empty);
            line = l;
            reason = null;
            return true;
        }

        /// <summary>One lever: position 0 is the neutral N (Ecb / Smee) or the run word (Cl) of the single handle. Two lever: P0..Pn. Below zero (two lever only): H1..Hh.</summary>
        internal static string PowerText(int notch, bool oneLever, bool cl)
        {
            if (notch < 0)
            {
                return "H" + TelemetryContract.I(-notch);
            }

            if (notch == 0 && oneLever)
            {
                return cl ? ClRun : TextNeutral;
            }

            return "P" + TelemetryContract.I(notch);
        }

        internal static string AllPowerTexts(int powN, bool oneLever, bool cl)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i <= powN; i++)
            {
                if (i > 0)
                {
                    sb.Append('_');
                }

                sb.Append(PowerText(i, oneLever, cl));
            }

            return sb.ToString();
        }

        /// <summary>H1_H2_..._Hh: the independent holding speed notches in the order of the handle (the "holding speed texts" of the Current ALLTXT).</summary>
        internal static string AllHoldingTexts(int holdN)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 1; i <= holdN; i++)
            {
                if (i > 1)
                {
                    sb.Append('_');
                }

                sb.Append('H').Append(TelemetryContract.I(i));
            }

            return sb.ToString();
        }

        /// <summary>One lever: position 0 is the neutral N of the single handle. Two lever: the brake handle shows B0..B(e-1) (emergency is handled by the caller).</summary>
        internal static string BrakeText(int notch, bool oneLever)
        {
            return notch == 0 && oneLever ? TextNeutral : "B" + TelemetryContract.I(notch);
        }

        /// <summary>One lever N, B1..B(e-1), EB; two lever B0, B1..B(e-1), EB - for the emergency brake notch e.</summary>
        internal static string AllBrakeTexts(int ebN, bool oneLever)
        {
            StringBuilder sb = new StringBuilder(BrakeText(0, oneLever));
            for (int i = 1; i < ebN; i++)
            {
                sb.Append("_B").Append(TelemetryContract.I(i));
            }

            sb.Append('_').Append(TextEmergency);
            return sb.ToString();
        }

        /// <summary>Ecb / Smee with the holding speed brake: 0 B0 (one lever N), 1 the holding speed brake word, 2..(e-1) B1..B(e-2), e and above EB.</summary>
        internal static string HoldBrakeBrakeText(int brk, int ebN, bool oneLever)
        {
            if (brk >= ebN)
            {
                return TextEmergency;
            }

            return brk == 0 ? BrakeText(0, oneLever) : brk == 1 ? HoldBrake : "B" + TelemetryContract.I(brk - 1);
        }

        /// <summary>B0 (one lever N), the holding speed brake word, B1..B(e-2), EB: e + 1 entries, indexed by the brake position.</summary>
        internal static string AllHoldBrakeTexts(int ebN, bool oneLever)
        {
            StringBuilder sb = new StringBuilder(BrakeText(0, oneLever) + "_");
            sb.Append(HoldBrake);
            for (int i = 2; i < ebN; i++)
            {
                sb.Append("_B").Append(TelemetryContract.I(i - 1));
            }

            sb.Append('_').Append(TextEmergency);
            return sb.ToString();
        }
    }
}
