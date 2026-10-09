using System;
using System.Text;

// ============================================================================
// PHASE LI1 - the handle group of the telemetry line (REV, POW, BRK, HTYPE, ALLTXT) for the AtsEX LEGACY sender, host independent.
//
// The CURRENT sender (BveEX, TsScoringPlugin\Class1.cs) writes these keys from the texts the vehicle defines. The Legacy host does not give those
// texts, so this file builds the generic texts from the NUMBERS the host does give (handle positions and the notch layout) and writes them in
// EXACTLY the Current format - the Python reader, the HUD and the AVAIL token "handle" are the Current ones, unchanged:
//
//     REV:<text>:<-1|0|1>                       POW:<text>:<notch>                    BRK:<text>:<notch>:<emergency notch>
//     HTYPE:<1 one lever | 2 two lever>         ALLTXT:<rev texts>:<power texts>:<brake texts>:<holding speed texts, empty>      (texts joined by '_')
//
// Generic texts (nothing else is ever written):
//     reverser            -1 back, 0 off, 1 forward                                    (the three Japanese words below)
//     one lever  Ecb/Smee power N (position 0), P1..Pn      brake N, B1..B(e-1), EB     the handle shows the power text, else the brake text
//     two lever  Ecb/Smee power P0..Pn                      brake B0, B1..B(e-1), EB
//     two lever  Cl       power P0..Pn                      brake 0 run, 1 lap, 2 service, EB notch and above emergency (the Japanese words below)
// where n = NotchInfo.PowerNotchCount and e = NotchInfo.EmergencyBrakeNotch (the emergency boundary is what the host reports, never derived).
//
// What is NOT built (the group is then not written at all and "handle" is not announced - no placeholder, no guess):
//     * a one-lever cab with a Cl brake (outside the supported set: "one-lever-cl")
//     * an unknown cab type / brake kind, a missing or out-of-range value, a layout that is not the one described above
//     * a vehicle with a holding speed brake: its texts and notch names are not known on this host ("holding-unconfirmed" / "hold-missing")
// The reasons are fixed words; no exception text, no vehicle text.
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
        internal string Layout;              // fixed words for the diagnostic log: one-lever-ecb, two-lever-cl, ...

        /// <summary>The key / value pairs in the order of the Current line (HTYPE before ALLTXT: the reader needs the handle type to size the brake texts).</summary>
        internal string[] Pairs()
        {
            return new string[]
            {
                "REV", RevText + ":" + TelemetryContract.I(RevPos),
                "POW", PowText + ":" + TelemetryContract.I(PowNotch),
                "BRK", BrkText + ":" + TelemetryContract.I(BrkNotch) + ":" + TelemetryContract.I(BrkMax),
                "HTYPE", TelemetryContract.I(HandleType),
                "ALLTXT", AllRev + ":" + AllPow + ":" + AllBrk + ":"
            };
        }
    }

    internal static class LegacyHandleContract
    {
        /// <summary>A layout beyond this is not a vehicle of this product; it also bounds the length of the generated texts.</summary>
        internal const int MaxNotches = 99;

        // the Japanese words of the generic display (escaped: the source is read the same way whatever the code page)
        internal const string RevBack = "\u5f8c";  // back
        internal const string RevOff = "\u5207";  // reverser off
        internal const string RevForward = "\u524d";  // forward
        internal const string ClRun = "\u904b\u8ee2";  // Cl brake position 0 (running)
        internal const string ClLap = "\u91cd\u306a\u308a";  // lap
        internal const string ClService = "\u5e38\u7528";  // service
        internal const string ClEmergency = "\u975e\u5e38";  // emergency

        internal const string TextNeutral = "N";
        internal const string TextEmergency = "EB";

        // fixed reason words
        internal const string ReasonSnapshotNull = "snapshot-null";
        internal const string ReasonTypeUnknown = "type-unknown";
        internal const string ReasonBrakeUnknown = "brake-unknown";
        internal const string ReasonOneLeverCl = "one-lever-cl";
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
        internal const string ReasonHoldUnconfirmed = "holding-unconfirmed";

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
            if (oneLever && cl)
            {
                reason = ReasonOneLeverCl;       // outside the supported set: the handle is not declared, nothing is guessed
                return false;
            }

            if (!h.Reverser.HasValue) { reason = ReasonRevMissing; return false; }
            if (!h.Power.HasValue) { reason = ReasonPowMissing; return false; }
            if (!h.Brake.HasValue) { reason = ReasonBrkMissing; return false; }
            if (!h.PowerNotchCount.HasValue || !h.BrakeNotchCount.HasValue || !h.EmergencyBrakeNotch.HasValue) { reason = ReasonLayoutMissing; return false; }
            if (!h.HasHoldingSpeedBrake.HasValue) { reason = ReasonHoldMissing; return false; }
            if (h.HasHoldingSpeedBrake.Value) { reason = ReasonHoldUnconfirmed; return false; }

            int rev = h.Reverser.Value;
            int pow = h.Power.Value;
            int brk = h.Brake.Value;
            int powN = h.PowerNotchCount.Value;
            int brkN = h.BrakeNotchCount.Value;
            int ebN = h.EmergencyBrakeNotch.Value;

            if (powN < 0 || powN > MaxNotches || brkN < 1 || brkN > MaxNotches || ebN < 1 || ebN > MaxNotches + 1) { reason = ReasonLayoutRange; return false; }
            if (cl)
            {
                // the only Cl layout seen on the host: 2 service positions (lap, service) and the emergency position 3
                if (brkN != 2 || ebN != 3) { reason = ReasonClLayout; return false; }
            }
            else if (ebN != brkN + 1)
            {
                reason = ReasonEbLayout;         // B1..Bn and EB only fit when the emergency notch directly follows the service notches
                return false;
            }

            if (rev < -1 || rev > 1) { reason = ReasonRevRange; return false; }
            if (pow < 0 || pow > powN) { reason = ReasonPowRange; return false; }
            if (brk < 0) { reason = ReasonBrkRange; return false; }

            LegacyHandleLine l = new LegacyHandleLine();
            l.HandleType = oneLever ? 1 : 2;
            l.RevPos = rev;
            l.RevText = ReverserText(rev);
            l.AllRev = RevBack + "_" + RevOff + "_" + RevForward;
            l.PowNotch = pow;
            l.PowText = PowerText(pow, oneLever);
            l.AllPow = AllPowerTexts(powN, oneLever);
            l.BrkNotch = brk;
            l.BrkMax = ebN;
            if (cl)
            {
                l.BrkText = brk >= ebN ? ClEmergency : brk == 0 ? ClRun : brk == 1 ? ClLap : ClService;
                l.AllBrk = ClRun + "_" + ClLap + "_" + ClService + "_" + ClEmergency;
            }
            else
            {
                l.BrkText = brk >= ebN ? TextEmergency : BrakeText(brk, oneLever);
                l.AllBrk = AllBrakeTexts(ebN, oneLever);
            }

            l.Layout = (oneLever ? "one-lever-" : "two-lever-") + (cl ? "cl" : h.BrakeKind == LegacyBrakeKind.Smee ? "smee" : "ecb");
            line = l;
            reason = null;
            return true;
        }

        /// <summary>One lever: position 0 is the neutral N of the single handle. Two lever: the power handle shows P0..Pn.</summary>
        internal static string PowerText(int notch, bool oneLever)
        {
            return notch == 0 && oneLever ? TextNeutral : "P" + TelemetryContract.I(notch);
        }

        internal static string AllPowerTexts(int powN, bool oneLever)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i <= powN; i++)
            {
                if (i > 0)
                {
                    sb.Append('_');
                }

                sb.Append(PowerText(i, oneLever));
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
    }
}
