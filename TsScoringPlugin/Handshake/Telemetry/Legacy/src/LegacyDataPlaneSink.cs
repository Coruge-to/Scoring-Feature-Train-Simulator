using System;
using System.Net;
using System.Text;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / SLICE 1 - the AtsEX LEGACY telemetry sender's side of the per-PID DataPlane (PID-D0B-1 contract sections 10-13).
//
// HOST INDEPENDENT: no AtsEX / BveTypes name appears in this file (LegacyTelemetryExtension.cs stays the only file that names them). It replaces the plain UDP
// sink of the earlier phases (UdpTelemetrySink, fixed 127.0.0.1:54321) with a sink that routes every text of LegacyTelemetrySession through the Current sender's
// verified routing core (CurrentDataPlane.cs, linked unchanged): CurrentModeLatch + CurrentTelemetryRouter.
//
// Two modes, never mixed (decided by the router, see CurrentDataPlane.cs):
//   MANAGED  the Caller is active in this BVE process (the existing control plane event Enabled or Ready was observed; latched). Every text goes ONLY to the
//            Directory-published loopback endpoint of THIS BVE's managed application, inside an Envelope v1 (type 1 telemetry, 2 heartbeat, 3 STALIST, 4 META).
//            Directory unresolved / not READY / ownership mismatch = nothing is sent (fail closed). There is NO fixed 54321 fallback.
//   NORMAL   neither Enabled nor Ready was observed during the hold-off: the plain UTF-8 text to the fixed legacy destination, byte for byte as before.
//   UNDETERMINED  the hold-off after the first send attempt: nothing is sent.
//
// This file adds only the message classification and the socket owner; it does not change what the session writes.
// No exception leaves any member.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>Maps the texts of LegacyTelemetrySession to the envelope MessageType of contract section 11 (the Current sender uses the same four values).</summary>
    internal static class LegacyMessageClassifier
    {
        internal const UInt32 Unknown = 0U;

        internal static UInt32 Classify(string text)
        {
            if (text == null)
            {
                return Unknown;
            }

            if (text.StartsWith("SCENARIO_ID:", StringComparison.Ordinal))
            {
                return DataPlaneMessageTypes.Telemetry;
            }

            if (text.StartsWith("STATUS:", StringComparison.Ordinal))
            {
                return DataPlaneMessageTypes.Heartbeat;
            }

            if (text.StartsWith("STALIST:", StringComparison.Ordinal))
            {
                return DataPlaneMessageTypes.StationList;
            }

            if (text.StartsWith("META:", StringComparison.Ordinal))
            {
                return DataPlaneMessageTypes.Metadata;
            }

            return Unknown;
        }
    }

    /// <summary>The datagram transport of the Legacy sender: ONE unbound UdpClient (the destination is chosen per datagram by the router), closed on Dispose. A send after Close throws and is counted by the caller.</summary>
    internal sealed class LegacyUdpTransport : ITelemetryTransport
    {
        private readonly object gate = new object();
        private System.Net.Sockets.UdpClient client;

        internal LegacyUdpTransport()
        {
            try
            {
                client = new System.Net.Sockets.UdpClient();
            }
            catch
            {
                client = null;
            }
        }

        public void Send(byte[] data, IPEndPoint destination)
        {
            lock (gate)
            {
                if (client == null)
                {
                    throw new ObjectDisposedException("UdpClient");
                }

                client.Send(data, data.Length, destination);
            }
        }

        internal void Close()
        {
            lock (gate)
            {
                try { if (client != null) { client.Close(); } } catch { }
                client = null;
            }
        }
    }

    /// <summary>
    /// The sink of LegacyTelemetrySession in the PID-D4 world. Thread safe: the Tick thread and the heartbeat timer thread both call Send (the router has its own gate,
    /// the transport serialises the socket). After Close nothing is sent any more.
    /// </summary>
    internal sealed class LegacyDataPlaneSink : ITelemetrySink, ILegacyJumpCompleteSender
    {
        private readonly CurrentTelemetryRouter router;
        private readonly LegacyUdpTransport transport;
        private readonly Action<string> log;
        private readonly object gate = new object();
        private volatile bool closed;
        private long failed;
        private long unclassifiedDropped;
        private bool unclassifiedNoted;

        internal LegacyDataPlaneSink(CurrentTelemetryRouter router, LegacyUdpTransport transport, Action<string> log)
        {
            this.router = router;
            this.transport = transport;
            this.log = log;
        }

        /// <summary>
        /// The production wiring: the router for THIS BVE process (Enabled / Ready probe by PID, the shared Directory reader), the plain destination (the fixed legacy
        /// port, used in NORMAL mode only) and the transport. legacyDestination is a parameter only so that the offline tests never touch the real port. Returns a sink
        /// that sends nothing (and says so once) when the router cannot be built.
        /// </summary>
        internal static LegacyDataPlaneSink Create(int bvePid, IPEndPoint legacyDestination, Action<string> log)
        {
            LegacyUdpTransport transport = new LegacyUdpTransport();
            CurrentTelemetryRouter router = null;
            try
            {
                router = CurrentTelemetryRouter.CreateProduction(bvePid, transport, legacyDestination, log);
            }
            catch
            {
                router = null;
                Emit(log, "event=sender-init-failed");
            }

            return new LegacyDataPlaneSink(router, transport, log);
        }

        internal static IPEndPoint FixedLegacyDestination()
        {
            return new IPEndPoint(IPAddress.Parse(TelemetryContract.LoopbackAddress), TelemetryContract.Port);
        }

        internal CurrentTelemetryRouter Router { get { return router; } }

        /// <summary>The mode word for the diagnostic: managed / normal / undetermined, or none when no router could be built.</summary>
        internal string ModeText
        {
            get
            {
                try { return router == null ? "none" : router.Mode.ToString().ToLowerInvariant(); }
                catch { return "none"; }
            }
        }

        internal long Sent { get { return router == null ? 0L : router.PlainSent + router.WrappedSent; } }

        internal long Failed { get { return System.Threading.Interlocked.Read(ref failed) + (router == null ? 0L : router.SendFailures); } }

        internal long UnclassifiedDropped { get { return System.Threading.Interlocked.Read(ref unclassifiedDropped); } }

        public void Send(string text)
        {
            try
            {
                if (closed || router == null || text == null)
                {
                    return;
                }

                byte[] bytes = Encoding.UTF8.GetBytes(text);
                UInt32 type = LegacyMessageClassifier.Classify(text);
                CurrentTelemetryRouter.SendBatch batch = router.Begin();
                if (type == LegacyMessageClassifier.Unknown)
                {
                    // a text that is none of the four kinds: NORMAL mode sends it exactly as the old sink did (plain, untouched); in every other mode it has no
                    // message type and is dropped (never invented as a telemetry line, never sent plain)
                    if (batch.Mode == CurrentSenderMode.Normal)
                    {
                        batch.Send(type, bytes);
                    }
                    else
                    {
                        NoteUnclassified();
                    }

                    return;
                }

                batch.Send(type, bytes);
            }
            catch
            {
                // nothing may reach BVE; the receiving application may simply not be running (the NORMAL path of the router lets a transport exception through, as before)
                System.Threading.Interlocked.Increment(ref failed);
            }
        }

        /// <summary>
        /// Phase LJX-1: the JUMP_COMPLETE of an executed official jump, as a type 5 envelope that echoes the RequestId, through the same routing core as every other text (the
        /// destination is the Directory-published Telemetry endpoint of THIS BVE process and nothing else; there is no fixed-port fallback). It does not go through the
        /// message classifier (an unclassified text is dropped in managed mode). Returns Sent when a datagram left, Excluded when the core consumed it without one (the
        /// endpoint has no JUMP_COMPLETE capability, or the sender is in normal mode), Held when nothing was consumed (hold-off, endpoint not resolvable, send failure, closed).
        /// </summary>
        public int SendJumpComplete(byte[] payload, byte[] requestId)
        {
            try
            {
                if (closed || router == null || payload == null || requestId == null)
                {
                    return LegacyJumpSend.Held;
                }

                long sentBefore = router.JumpCompleteSent;
                CurrentTelemetryRouter.SendBatch batch = router.Begin();
                if (!batch.SendJumpComplete(payload, requestId))
                {
                    return LegacyJumpSend.Held;
                }

                return router.JumpCompleteSent > sentBefore ? LegacyJumpSend.Sent : LegacyJumpSend.Excluded;
            }
            catch
            {
                System.Threading.Interlocked.Increment(ref failed);
                return LegacyJumpSend.Held;
            }
        }

        public void Close()
        {
            lock (gate)
            {
                if (closed)
                {
                    return;
                }

                closed = true;
            }

            try { if (router != null) { router.Close(); } } catch { }
            try { transport.Close(); } catch { }
        }

        private void NoteUnclassified()
        {
            bool first;
            lock (gate)
            {
                first = !unclassifiedNoted;
                unclassifiedNoted = true;
            }

            System.Threading.Interlocked.Increment(ref unclassifiedDropped);
            if (first)
            {
                Emit(log, "event=unclassified-text-dropped");
            }
        }

        private static void Emit(Action<string> log, string text)
        {
            try { if (log != null) { log(text); } } catch { }
        }
    }
}
