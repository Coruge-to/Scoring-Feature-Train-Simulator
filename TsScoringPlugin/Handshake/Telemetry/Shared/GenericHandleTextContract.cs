using System;
using System.Text;

namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// Host-independent generic handle text contract shared by the Current and AtsEX Legacy telemetry adapters.
    /// This class formats display text only. It does not change telemetry numbers, scoring state, or author-defined text.
    /// </summary>
    internal static class GenericHandleTextContract
    {
        internal const int MaxNotches = 99;

        internal const string RevBack = "後";
        internal const string RevOff = "切";
        internal const string RevForward = "前";
        internal const string ClRun = "運転";
        internal const string ClLap = "重なり";
        internal const string ClService = "常用";
        internal const string ClEmergency = "非常";
        internal const string HoldBrake = "抑速";
        internal const string TextNeutral = "N";
        internal const string TextEmergency = "EB";

        internal static string ReverserText(int position)
        {
            return position < 0 ? RevBack : position == 0 ? RevOff : RevForward;
        }

        internal static string AllReverserTexts()
        {
            return RevBack + "_" + RevOff + "_" + RevForward;
        }

        internal static string PowerText(int notch, bool oneLever, bool cl)
        {
            if (notch < 0)
            {
                return "H" + (-notch).ToString(System.Globalization.CultureInfo.InvariantCulture);
            }

            if (notch == 0 && oneLever)
            {
                return cl ? ClRun : TextNeutral;
            }

            return "P" + notch.ToString(System.Globalization.CultureInfo.InvariantCulture);
        }

        internal static string AllPowerTexts(int powerNotches, bool oneLever, bool cl)
        {
            StringBuilder builder = new StringBuilder();
            for (int notch = 0; notch <= powerNotches; notch++)
            {
                if (notch > 0)
                {
                    builder.Append('_');
                }
                builder.Append(PowerText(notch, oneLever, cl));
            }
            return builder.ToString();
        }

        internal static string AllHoldingTexts(int holdingNotches)
        {
            StringBuilder builder = new StringBuilder();
            for (int notch = 1; notch <= holdingNotches; notch++)
            {
                if (notch > 1)
                {
                    builder.Append('_');
                }
                builder.Append('H').Append(notch.ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
            return builder.ToString();
        }

        internal static string BrakeText(int notch, bool oneLever)
        {
            return notch == 0 && oneLever
                ? TextNeutral
                : "B" + notch.ToString(System.Globalization.CultureInfo.InvariantCulture);
        }

        internal static string AllBrakeTexts(int emergencyNotch, bool oneLever)
        {
            StringBuilder builder = new StringBuilder(BrakeText(0, oneLever));
            for (int notch = 1; notch < emergencyNotch; notch++)
            {
                builder.Append("_B").Append(notch.ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
            builder.Append('_').Append(TextEmergency);
            return builder.ToString();
        }

        internal static string HoldBrakeBrakeText(int brakeNotch, int emergencyNotch, bool oneLever)
        {
            if (brakeNotch >= emergencyNotch)
            {
                return TextEmergency;
            }
            if (brakeNotch == 0)
            {
                return BrakeText(0, oneLever);
            }
            if (brakeNotch == 1)
            {
                return HoldBrake;
            }
            return "B" + (brakeNotch - 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
        }

        internal static string AllHoldBrakeTexts(int emergencyNotch, bool oneLever)
        {
            StringBuilder builder = new StringBuilder(BrakeText(0, oneLever) + "_" + HoldBrake);
            for (int notch = 2; notch < emergencyNotch; notch++)
            {
                builder.Append("_B").Append((notch - 1).ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
            builder.Append('_').Append(TextEmergency);
            return builder.ToString();
        }

        internal static string ClBrakeText(int brakeNotch, int emergencyNotch, bool hasHoldingSpeedBrake)
        {
            if (brakeNotch >= emergencyNotch)
            {
                return ClEmergency;
            }
            if (brakeNotch == 0)
            {
                return ClRun;
            }
            if (brakeNotch == 1)
            {
                return hasHoldingSpeedBrake ? HoldBrake : ClLap;
            }
            return ClService;
        }

        internal static string AllClBrakeTexts(bool hasHoldingSpeedBrake)
        {
            return ClRun + "_" + (hasHoldingSpeedBrake ? HoldBrake : ClLap) + "_" + ClService + "_" + ClEmergency;
        }
    }
}
