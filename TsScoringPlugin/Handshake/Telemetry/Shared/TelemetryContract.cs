using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

// ============================================================================
// PHASE L3 - the telemetry DATA CONTRACT as a sender writes it (host independent: no BVE, no AtsEX, no BveEX name appears in this file).
//
// The wire format is the one the Python application has always read on UDP 127.0.0.1:54321: ONE datagram of comma separated `KEY:value` parts per
// Tick. Phase L3 adds one optional part, AVAIL, the list of the data groups ("tokens") the line really carries:
//
//     AVAIL:1:brake_cab+brake_type+calcg+...        (tokens sorted, joined by '+')
//
// A sender never writes the keys of a token it does not list, and never writes a placeholder for them. The Python side (telemetry_contract.py)
// is the reference reader: both vocabularies are compared by the offline tests.
// This file is shared by the senders of the TS Scoring telemetry (today the Legacy sender; a Current sender can link the same file).
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    internal static class TelemetryContract
    {
        internal const int ProtocolVersion = 1;
        internal const string LoopbackAddress = "127.0.0.1";
        internal const int Port = 54321;

        // the data groups (tokens) of the line, in the vocabulary of telemetry_contract.TOKEN_KEYS
        internal const string TokTime = "time";
        internal const string TokSpeed = "speed";
        internal const string TokLoc = "loc";
        internal const string TokGrad = "grad";
        internal const string TokStation = "station";
        internal const string TokDoor = "door";
        internal const string TokSigLimit = "siglimit";
        internal const string TokSigLimitAhead = "siglimit_ahead";
        internal const string TokMapLimit = "maplimit";
        internal const string TokHandle = "handle";          // Phase LI1: REV POW BRK HTYPE ALLTXT, all or nothing
        internal const string TokBcp = "bcp";                // Phase LI1: BCP (kPa)
        internal const string TokBpp = "bpp";                // Phase LI1: BPP (kPa)
        internal const string TokBrakeType = "brake_type";
        internal const string TokBrakeCab = "brake_cab";
        internal const string TokPRates = "prates";
        internal const string TokCalcG = "calcg";
        internal const string TokMeta = "meta";

        // "no limit" in the km/h of the contract (the value the Python HUD prints as ---)
        internal const double NoLimitKmh = 1000.0;
        internal const double GravityMps2 = 9.80665;

        internal static string FormatAvail(IEnumerable<string> tokens)
        {
            List<string> sorted = new List<string>(tokens);
            sorted.Sort(StringComparer.Ordinal);
            return "AVAIL:" + ProtocolVersion.ToString(CultureInfo.InvariantCulture) + ":" + string.Join("+", sorted);
        }

        /// <summary>Round-trip text with the invariant culture (the contract is culture independent; the Python side reads it with float()).</summary>
        internal static string D(double v)
        {
            return v.ToString("R", CultureInfo.InvariantCulture);
        }

        internal static string F(double v, string format)
        {
            return v.ToString(format, CultureInfo.InvariantCulture);
        }

        internal static string I(int v)
        {
            return v.ToString(CultureInfo.InvariantCulture);
        }

        internal static bool Finite(double v)
        {
            return !double.IsNaN(v) && !double.IsInfinity(v);
        }

        /// <summary>m/s to the km/h of the contract.</summary>
        internal static double Kmh(double metersPerSecond)
        {
            return metersPerSecond * 3.6;
        }

        /// <summary>
        /// A signal speed limit [m/s] to the km/h of the contract: infinite or above 999 m/s means "no limit" (1000); 0 is a real limit (a stop signal).
        /// Same rule the Current sender has always applied.
        /// </summary>
        internal static double SignalLimitKmh(double metersPerSecond)
        {
            if (double.IsInfinity(metersPerSecond) || metersPerSecond > 999.0)
            {
                return NoLimitKmh;
            }

            return Kmh(metersPerSecond);
        }

        /// <summary>A ground speed limit [m/s] to km/h: infinite, above 999 m/s or not positive means "no limit" (same rule as the Current sender's map limits).</summary>
        internal static double GroundLimitKmh(double metersPerSecond)
        {
            if (double.IsInfinity(metersPerSecond) || metersPerSecond > 999.0 || metersPerSecond <= 0)
            {
                return NoLimitKmh;
            }

            return Kmh(metersPerSecond);
        }

        /// <summary>The text parts of the META datagram must not contain the separators of the contract.</summary>
        internal static string SanitizeMeta(string s)
        {
            if (string.IsNullOrEmpty(s))
            {
                return string.Empty;
            }

            return s.Replace(":", "：").Replace(",", "、").Replace("\r", string.Empty).Replace("\n", " ");
        }

        /// <summary>A station name inside STALIST: no ',' and no '='.</summary>
        internal static string StationName(string name)
        {
            return string.IsNullOrEmpty(name) ? "不明な駅" : name.Replace(",", string.Empty).Replace("=", string.Empty);
        }
    }

    /// <summary>Where a finished datagram goes. The production sink is UDP; the offline tests collect the texts.</summary>
    internal interface ITelemetrySink
    {
        void Send(string text);
        void Close();
    }

    internal sealed class UdpTelemetrySink : ITelemetrySink
    {
        private readonly object gate = new object();
        private readonly System.Net.IPEndPoint endPoint;
        private System.Net.Sockets.UdpClient client;
        private long sent;
        private long failed;

        internal UdpTelemetrySink()
            : this(new System.Net.IPEndPoint(System.Net.IPAddress.Parse(TelemetryContract.LoopbackAddress), TelemetryContract.Port))
        {
        }

        internal UdpTelemetrySink(System.Net.IPEndPoint target)
        {
            endPoint = target;
            try
            {
                client = new System.Net.Sockets.UdpClient();
            }
            catch
            {
                client = null;
            }
        }

        internal long Sent { get { return System.Threading.Interlocked.Read(ref sent); } }

        internal long Failed { get { return System.Threading.Interlocked.Read(ref failed); } }

        public void Send(string text)
        {
            try
            {
                byte[] bytes = Encoding.UTF8.GetBytes(text);
                lock (gate)
                {
                    if (client == null)
                    {
                        System.Threading.Interlocked.Increment(ref failed);
                        return;
                    }

                    client.Send(bytes, bytes.Length, endPoint);
                }

                System.Threading.Interlocked.Increment(ref sent);
            }
            catch
            {
                // nothing may reach BVE; the receiving application may simply not be running
                System.Threading.Interlocked.Increment(ref failed);
            }
        }

        public void Close()
        {
            lock (gate)
            {
                try { if (client != null) { client.Close(); } } catch { }
                client = null;
            }
        }
    }
}
