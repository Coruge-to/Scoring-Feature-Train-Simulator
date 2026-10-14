using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.AccessControl;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE PID-D3 - the Current Telemetry sender's side of the per-PID DataPlane (PID-D0B-1 contract sections 10-13).
//
// CURRENT-ONLY code: no BveEX / BVE API, no Legacy type, no Caller type. It is compiled into the Current project only (TsScoringPlugin.csproj); the
// shared DataPlaneProtocol.cs / TelemetryDirectoryReader.cs are used unchanged. Written in C# 5 syntax so that the offline tests can compile it
// directly (Tests\Test-CurrentDataPlaneD3.ps1).
//
// Two modes, never mixed:
//   MANAGED  the Caller is active in this BVE process: the control plane object Enabled or Ready (existing objects, created by the Caller / the Bridge)
//            was observed at least once. Latched for the life of the plugin: a later loss of Enabled / Ready never returns the sender to normal mode.
//            Telemetry goes ONLY to the Directory-published loopback endpoint of THIS BVE's managed application, inside an Envelope v1. Directory
//            unresolved / not READY / ownership mismatch / unsupported capabilities = nothing is sent (fail closed). There is NO fixed-port fallback.
//   NORMAL   neither Enabled nor Ready was observed during the hold-off: the pre-migration behaviour (plain UTF-8 text to the fixed legacy
//            destination given by the owner of this class) is unchanged, byte for byte.
//   UNDETERMINED  the hold-off after the first send attempt: nothing is sent.
// The mode never depends on whether a Directory exists.
//
// JUMP_COMPLETE (PID-D6): a jump command that arrived through the Current Jump endpoint (CurrentJumpEndpoint.cs) carries a RequestId; its completion is
// sent to the Telemetry endpoint as a type 5 envelope that echoes that RequestId (needs the JUMP_COMPLETE_V1 capability). A completion WITHOUT a RequestId
// (a plain command) is still consumed without any datagram in managed mode (it can no longer happen: plain commands are not executed in managed mode).
// ============================================================================
namespace TSScoringPlugin.DataPlane
{
    /// <summary>The Telemetry Receiver Directory capability bits of contract section 8 (parity-tested against dataplane_contract.py).</summary>
    internal static class TelemetryCapabilities
    {
        internal const UInt32 EnvelopeV1 = 0x1U;
        internal const UInt32 LegacyTextPayload = 0x2U;
        internal const UInt32 JumpCompleteV1 = 0x4U;
        internal const UInt32 Known = EnvelopeV1 | LegacyTextPayload | JumpCompleteV1;
    }

    /// <summary>The envelope MessageType values the Current Telemetry sender uses (contract section 11).</summary>
    internal static class DataPlaneMessageTypes
    {
        internal const UInt32 Telemetry = 1U;
        internal const UInt32 Heartbeat = 2U;
        internal const UInt32 StationList = 3U;
        internal const UInt32 Metadata = 4U;
        internal const UInt32 JumpComplete = 5U;
        internal const UInt32 JumpStationTime = 0x100U;
        internal const UInt32 JumpLocationTime = 0x101U;
    }

    internal enum CurrentSenderMode
    {
        Undetermined = 0,
        Normal = 1,
        Managed = 2
    }

    internal interface ICallerProbe
    {
        bool EnabledExists();
        bool ReadyExists();
    }

    internal interface ITelemetryTransport
    {
        void Send(byte[] data, IPEndPoint destination);
    }

    internal interface IEndpointSource
    {
        bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason);
    }

    /// <summary>Existence of the two existing per-PID control plane events. The names are the ones of HandshakeProtocol.cs (parity-tested); no Caller type is referenced.</summary>
    internal sealed class CallerControlPlaneProbe : ICallerProbe
    {
        private readonly string enabledName;
        private readonly string readyName;

        internal CallerControlPlaneProbe(int bveProcessId)
        {
            enabledName = EnabledName(bveProcessId);
            readyName = ReadyName(bveProcessId);
        }

        internal static string EnabledName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".Enabled"; }
        internal static string ReadyName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".Ready"; }

        public bool EnabledExists() { return Exists(enabledName); }
        public bool ReadyExists() { return Exists(readyName); }

        private static bool Exists(string name)
        {
            try
            {
                EventWaitHandle handle;
                if (EventWaitHandle.TryOpenExisting(name, EventWaitHandleRights.Synchronize, out handle))
                {
                    handle.Close();
                    return true;
                }
            }
            catch
            {
            }
            return false;
        }
    }

    internal sealed class ReaderEndpointSource : IEndpointSource
    {
        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            return TelemetryDirectoryReader.TryResolve(bveProcessId, out endpoint, out reason);
        }
    }

    /// <summary>
    /// Decides managed / normal. Managed = Enabled or Ready observed once, latched. Normal = hold-off elapsed with neither observed (a later observation still
    /// upgrades Normal to Managed; the opposite never happens). Thread safe (Tick and the heartbeat timer both call it).
    /// </summary>
    internal sealed class CurrentModeLatch
    {
        internal const int DefaultHoldOffMs = 2000;
        private const int UndeterminedProbeMs = 50;
        private const int NormalProbeMs = 1000;
        private const int ObserveProbeMs = 250;

        private readonly object gate = new object();
        private readonly ICallerProbe probe;
        private readonly Func<long> clockMs;
        private readonly int holdOffMs;
        private readonly Action<string> log;
        private CurrentSenderMode mode = CurrentSenderMode.Undetermined;
        private long startMs = -1;
        private long lastProbeMs = -1;
        private long enabledSeenMs = -1;
        private long readySeenMs = -1;

        internal CurrentModeLatch(ICallerProbe probe, Func<long> clockMs, int holdOffMs, Action<string> log)
        {
            if (probe == null) throw new ArgumentNullException("probe");
            if (clockMs == null) throw new ArgumentNullException("clockMs");
            if (holdOffMs < 0) throw new ArgumentOutOfRangeException("holdOffMs");
            this.probe = probe;
            this.clockMs = clockMs;
            this.holdOffMs = holdOffMs;
            this.log = log;
        }

        internal CurrentSenderMode Mode { get { lock (gate) { return mode; } } }

        /// <summary>Milliseconds since the first send attempt (the time base of every event line), or -1 before it.</summary>
        internal long ElapsedMs()
        {
            lock (gate)
            {
                return startMs < 0 ? -1L : clockMs() - startMs;
            }
        }

        internal CurrentSenderMode Evaluate()
        {
            lock (gate)
            {
                long now = clockMs();
                if (startMs < 0)
                {
                    startMs = now;
                    Note("first-evaluate", now);
                }

                if (mode == CurrentSenderMode.Managed && enabledSeenMs >= 0 && readySeenMs >= 0)
                {
                    return mode;
                }

                bool expired = mode == CurrentSenderMode.Undetermined && now - startMs >= holdOffMs;
                int interval = mode == CurrentSenderMode.Undetermined ? UndeterminedProbeMs : (mode == CurrentSenderMode.Normal ? NormalProbeMs : ObserveProbeMs);
                if (expired || lastProbeMs < 0 || now - lastProbeMs >= interval)
                {
                    lastProbeMs = now;
                    bool enabled = SafeEnabled();
                    bool ready = SafeReady();
                    if (enabled && enabledSeenMs < 0)
                    {
                        enabledSeenMs = now;
                        Note("enabled-seen", now);
                    }
                    if (ready && readySeenMs < 0)
                    {
                        readySeenMs = now;
                        Note("ready-seen", now);
                    }
                    if ((enabled || ready) && mode != CurrentSenderMode.Managed)
                    {
                        mode = CurrentSenderMode.Managed;
                        Note("mode=managed", now);
                    }
                }

                if (mode == CurrentSenderMode.Undetermined && now - startMs >= holdOffMs)
                {
                    mode = CurrentSenderMode.Normal;
                    Note("mode=normal holdoff-ms=" + holdOffMs, now);
                }
                return mode;
            }
        }

        private bool SafeEnabled() { try { return probe.EnabledExists(); } catch { return false; } }
        private bool SafeReady() { try { return probe.ReadyExists(); } catch { return false; } }

        private void Note(string text, long now)
        {
            if (log == null) return;
            try { log("event=" + text + " t=+" + (now - startMs) + "ms"); } catch { }
        }
    }

    /// <summary>Appends bounded diagnostic lines to one file per BVE process (never truncates another process' file). Never throws.</summary>
    internal sealed class CurrentTelemetryLogFile
    {
        internal const int MaxLines = 400;
        private readonly object gate = new object();
        private readonly string path;
        private readonly int pid;
        private int lines;
        private bool started;

        internal CurrentTelemetryLogFile(int bveProcessId, string directory)
        {
            pid = bveProcessId;
            path = string.IsNullOrEmpty(directory) ? null : Path.Combine(directory, "TSScoring-CurrentTelemetry-P" + bveProcessId + ".log");
        }

        internal static CurrentTelemetryLogFile CreateProduction(int bveProcessId)
        {
            string directory = null;
            try
            {
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (!string.IsNullOrEmpty(profile)) directory = Path.Combine(profile, "Downloads");
            }
            catch
            {
            }
            return new CurrentTelemetryLogFile(bveProcessId, directory);
        }

        internal string FilePath { get { return path; } }

        internal void Write(string text)
        {
            if (path == null) return;
            try
            {
                lock (gate)
                {
                    if (lines >= MaxLines) return;
                    string line = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'") + " [CTEL] bve=" + pid + " " + text + "\r\n";
                    if (!started)
                    {
                        started = true;
                        File.WriteAllText(path, line, new UTF8Encoding(false));
                    }
                    else
                    {
                        File.AppendAllText(path, line, new UTF8Encoding(false));
                    }
                    lines++;
                }
            }
            catch
            {
            }
        }
    }

    /// <summary>
    /// The Current sender's routing: one Begin() per Tick / heartbeat resolves the mode and (managed) the Directory endpoint ONCE, and every datagram of that
    /// batch uses that snapshot, so a STALIST / META / Telemetry group can never be split across two endpoints.
    /// </summary>
    internal sealed class CurrentTelemetryRouter
    {
        internal const int FailureRetryMs = 100;

        private readonly object gate = new object();
        private readonly int bvePid;
        private readonly ITelemetryTransport transport;
        private readonly IPEndPoint legacyDestination;
        private readonly IEndpointSource source;
        private readonly CurrentModeLatch latch;
        private readonly Func<long> clockMs;
        private readonly Action<string> log;
        private readonly byte[] zeroRequestId = new byte[16];

        private TelemetryEndpoint current;
        private string lastReason = "none";
        private long nextResolveMs;
        private bool closed;
        private bool sendFailing;
        private bool jumpCompleteNoted;
        private bool jumpCompleteCapabilityNoted;
        private bool tickNoted;
        private bool firstManagedSendNoted;
        private bool firstPlainSendNoted;

        private long plainSent;
        private long wrappedSent;
        private long held;
        private long failClosed;
        private long sendFailures;
        private long payloadTooLarge;
        private long jumpCompleteExcluded;
        private long jumpCompleteSent;
        private readonly Dictionary<string, long> reasons = new Dictionary<string, long>();
        private readonly Dictionary<UInt32, long> wrappedByType = new Dictionary<UInt32, long>();

        internal CurrentTelemetryRouter(int bvePid, ITelemetryTransport transport, IPEndPoint legacyDestination, IEndpointSource source, CurrentModeLatch latch, Func<long> clockMs, Action<string> log)
        {
            if (bvePid <= 0) throw new ArgumentOutOfRangeException("bvePid");
            if (transport == null) throw new ArgumentNullException("transport");
            if (legacyDestination == null) throw new ArgumentNullException("legacyDestination");
            if (source == null) throw new ArgumentNullException("source");
            if (latch == null) throw new ArgumentNullException("latch");
            if (clockMs == null) throw new ArgumentNullException("clockMs");
            this.bvePid = bvePid;
            this.transport = transport;
            this.legacyDestination = legacyDestination;
            this.source = source;
            this.latch = latch;
            this.clockMs = clockMs;
            this.log = log;
        }

        internal static CurrentTelemetryRouter CreateProduction(int bvePid, ITelemetryTransport transport, IPEndPoint legacyDestination, Action<string> log)
        {
            Func<long> clock = delegate { return Stopwatch.GetTimestamp() * 1000L / Stopwatch.Frequency; };
            CurrentModeLatch latch = new CurrentModeLatch(new CallerControlPlaneProbe(bvePid), clock, CurrentModeLatch.DefaultHoldOffMs, log);
            return new CurrentTelemetryRouter(bvePid, transport, legacyDestination, new ReaderEndpointSource(), latch, clock, log);
        }

        internal long PlainSent { get { lock (gate) { return plainSent; } } }
        internal long WrappedSent { get { lock (gate) { return wrappedSent; } } }
        internal long Held { get { lock (gate) { return held; } } }
        internal long FailClosed { get { lock (gate) { return failClosed; } } }
        internal long SendFailures { get { lock (gate) { return sendFailures; } } }
        internal long PayloadTooLarge { get { lock (gate) { return payloadTooLarge; } } }
        internal long JumpCompleteExcluded { get { lock (gate) { return jumpCompleteExcluded; } } }
        internal long JumpCompleteSent { get { lock (gate) { return jumpCompleteSent; } } }
        internal CurrentSenderMode Mode { get { return latch.Mode; } }

        internal long ReasonCount(string reason)
        {
            lock (gate)
            {
                long n;
                return reasons.TryGetValue(reason, out n) ? n : 0L;
            }
        }

        /// <summary>Diagnostic only: the first Tick of the plugin is written once (its UTC time is the evidence). Never throws.</summary>
        internal void NoteTick()
        {
            bool first;
            lock (gate) { first = !tickNoted; tickNoted = true; }
            if (first) Emit("event=first-tick");
        }

        /// <summary>Diagnostic only: the first datagram of each kind that really left the process (managed: wrapped, to the Directory port; normal: plain).</summary>
        private void NoteFirstSend(bool managed, UInt32 messageType, TelemetryEndpoint endpoint)
        {
            bool first;
            lock (gate)
            {
                if (managed) { first = !firstManagedSendNoted; firstManagedSendNoted = true; }
                else { first = !firstPlainSendNoted; firstPlainSendNoted = true; }
            }
            if (!first) return;
            if (managed) Emit("event=first-send-managed type=" + messageType + " port=" + endpoint.Port + " gen=" + endpoint.Generation + " t=+" + latch.ElapsedMs() + "ms");
            else Emit("event=first-send-plain type=" + messageType + " t=+" + latch.ElapsedMs() + "ms");
        }

        /// <summary>One snapshot for one Tick / heartbeat. Never throws.</summary>
        internal SendBatch Begin()
        {
            try
            {
                CurrentSenderMode mode = latch.Evaluate();
                TelemetryEndpoint endpoint = null;
                string reason = null;
                lock (gate)
                {
                    if (closed) return new SendBatch(this, CurrentSenderMode.Undetermined, null, "closed");
                    if (mode == CurrentSenderMode.Managed) endpoint = ResolveLocked(out reason);
                }
                return new SendBatch(this, mode, endpoint, reason);
            }
            catch
            {
                return new SendBatch(this, CurrentSenderMode.Undetermined, null, "router-error");
            }
        }

        /// <summary>Stops sending for good and writes the aggregate line. Idempotent.</summary>
        internal void Close()
        {
            string summary = null;
            lock (gate)
            {
                if (closed) return;
                closed = true;
                current = null;
                summary = "event=summary mode=" + latch.Mode + " plain=" + plainSent + " wrapped=" + wrappedSent + " types=" + TypesText() + " held=" + held + " failclosed=" + failClosed
                    + " sendfail=" + sendFailures + " toolarge=" + payloadTooLarge + " jumpcomplete-excluded=" + jumpCompleteExcluded + " jumpcomplete-sent=" + jumpCompleteSent + " reasons=" + ReasonsText();
            }
            Emit(summary);
        }

        private string TypesText()
        {
            if (wrappedByType.Count == 0) return "-";
            List<UInt32> keys = new List<UInt32>(wrappedByType.Keys);
            keys.Sort();
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < keys.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(keys[i]).Append(':').Append(wrappedByType[keys[i]]);
            }
            return sb.ToString();
        }

        private string ReasonsText()
        {
            if (reasons.Count == 0) return "-";
            List<string> keys = new List<string>(reasons.Keys);
            keys.Sort(StringComparer.Ordinal);
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < keys.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(keys[i]).Append(':').Append(reasons[keys[i]]);
            }
            return sb.ToString();
        }

        private TelemetryEndpoint ResolveLocked(out string reason)
        {
            long now = clockMs();
            if (current == null && lastReason != "ok" && lastReason != "none" && now < nextResolveMs)
            {
                reason = lastReason;
                return null;
            }

            TelemetryEndpoint endpoint;
            string why;
            bool ok;
            try
            {
                ok = source.TryResolve(bvePid, out endpoint, out why);
            }
            catch
            {
                ok = false;
                endpoint = null;
                why = "resolve-error";
            }
            if (ok && (endpoint == null || (endpoint.Capabilities & TelemetryCapabilities.EnvelopeV1) == 0U))
            {
                ok = false;
                endpoint = null;
                why = "capability-missing";
            }

            if (ok)
            {
                if (current == null || !Same(current, endpoint))
                {
                    bool changed = current != null;
                    current = endpoint;
                    Emit("event=" + (changed ? "endpoint-changed" : "endpoint-adopted") + " port=" + endpoint.Port + " gen=" + endpoint.Generation + " change=" + endpoint.ChangeCount
                        + " inst=" + endpoint.AppInstance.Substring(0, 8) + " t=+" + latch.ElapsedMs() + "ms");
                }
                lastReason = "ok";
                reason = "ok";
                return current;
            }

            if (lastReason != why)
            {
                Emit("event=disconnected reason=" + why + " t=+" + latch.ElapsedMs() + "ms");
            }
            current = null;
            lastReason = why;
            nextResolveMs = now + FailureRetryMs;
            reason = why;
            return null;
        }

        private static bool Same(TelemetryEndpoint a, TelemetryEndpoint b)
        {
            if (a.Port != b.Port || a.Generation != b.Generation || a.AppProcessId != b.AppProcessId || a.BveProcessId != b.BveProcessId) return false;
            if (!string.Equals(a.AppInstance, b.AppInstance, StringComparison.Ordinal)) return false;
            if (a.Token.Length != b.Token.Length) return false;
            for (int i = 0; i < a.Token.Length; i++) if (a.Token[i] != b.Token[i]) return false;
            return true;
        }

        private void Emit(string text)
        {
            if (log == null) return;
            try { log(text); } catch { }
        }

        private void Count(ref long counter, string reason)
        {
            lock (gate)
            {
                counter++;
                if (reason != null)
                {
                    long n;
                    reasons.TryGetValue(reason, out n);
                    reasons[reason] = n + 1;
                }
            }
        }

        internal sealed class SendBatch
        {
            private readonly CurrentTelemetryRouter router;
            private readonly TelemetryEndpoint endpoint;
            private readonly string reason;

            internal SendBatch(CurrentTelemetryRouter router, CurrentSenderMode mode, TelemetryEndpoint endpoint, string reason)
            {
                this.router = router;
                Mode = mode;
                this.endpoint = endpoint;
                this.reason = reason;
            }

            internal CurrentSenderMode Mode { get; private set; }

            /// <summary>True when the datagram was handed to the transport. False = nothing was sent (hold-off, fail closed, encode or send failure).</summary>
            internal bool Send(UInt32 messageType, byte[] payload)
            {
                return SendCore(messageType, payload, router.zeroRequestId);
            }

            private bool SendCore(UInt32 messageType, byte[] payload, byte[] requestId)
            {
                if (payload == null) return false;
                if (Mode == CurrentSenderMode.Normal)
                {
                    // pre-migration behaviour: plain text to the fixed legacy destination; a transport exception propagates exactly as before
                    router.transport.Send(payload, router.legacyDestination);
                    router.Count(ref router.plainSent, null);
                    router.NoteFirstSend(false, messageType, null);
                    return true;
                }
                if (Mode != CurrentSenderMode.Managed)
                {
                    router.Count(ref router.held, null);
                    return false;
                }
                if (endpoint == null)
                {
                    router.Count(ref router.failClosed, reason ?? "unresolved");
                    return false;
                }

                byte[] datagram;
                try
                {
                    datagram = DataPlaneProtocol.EncodeEnvelope(messageType, (UInt32)router.bvePid, (UInt32)router.bvePid, endpoint.Generation, endpoint.AppInstance, endpoint.Token, requestId, payload);
                }
                catch (ArgumentException)
                {
                    bool first;
                    lock (router.gate) { first = router.payloadTooLarge == 0; }
                    router.Count(ref router.payloadTooLarge, "payload-too-large");
                    if (first) router.Emit("event=payload-too-large type=" + messageType + " bytes=" + payload.Length);
                    return false;
                }

                try
                {
                    router.transport.Send(datagram, new IPEndPoint(IPAddress.Loopback, (int)endpoint.Port));
                }
                catch
                {
                    bool first;
                    lock (router.gate) { first = !router.sendFailing; router.sendFailing = true; }
                    router.Count(ref router.sendFailures, "send-failed");
                    if (first) router.Emit("event=send-failed port=" + endpoint.Port);
                    return false;
                }
                lock (router.gate) { router.sendFailing = false; }
                router.Count(ref router.wrappedSent, null);
                lock (router.gate) { long w; router.wrappedByType.TryGetValue(messageType, out w); router.wrappedByType[messageType] = w + 1; }
                router.NoteFirstSend(true, messageType, endpoint);
                return true;
            }

            /// <summary>
            /// The JUMP_COMPLETE notice of a jump command that came through the Current Jump endpoint (PID-D6). requestId == null is the plain command
            /// (see the overload below). Otherwise the notice is a type 5 envelope that echoes requestId, sent to the Telemetry endpoint of this batch.
            /// Returns true when the pending notice is CONSUMED (sent, or dropped because the endpoint cannot carry it); false = keep it pending (hold-off,
            /// endpoint unresolved or a send failure: retried with the next batch).
            /// </summary>
            internal bool SendJumpComplete(byte[] payload, byte[] requestId)
            {
                if (requestId == null) return SendJumpComplete(payload);
                if (payload == null) return true;
                if (Mode == CurrentSenderMode.Undetermined)
                {
                    router.Count(ref router.held, null);
                    return false;
                }
                if (Mode == CurrentSenderMode.Normal)
                {
                    // a RequestId only exists for the managed endpoint: nothing to send in normal mode, consume it
                    router.Count(ref router.jumpCompleteExcluded, "jump-complete-normal-mode");
                    return true;
                }
                if (endpoint == null)
                {
                    router.Count(ref router.failClosed, reason ?? "unresolved");
                    return false;
                }
                if ((endpoint.Capabilities & TelemetryCapabilities.JumpCompleteV1) == 0U)
                {
                    bool first;
                    lock (router.gate) { first = !router.jumpCompleteCapabilityNoted; router.jumpCompleteCapabilityNoted = true; }
                    router.Count(ref router.jumpCompleteExcluded, "jump-complete-capability-missing");
                    if (first) router.Emit("event=jump-complete-excluded reason=capability-missing");
                    return true;
                }
                if (!SendCore(DataPlaneMessageTypes.JumpComplete, payload, requestId)) return false;
                bool firstSent;
                lock (router.gate) { firstSent = router.jumpCompleteSent == 0; router.jumpCompleteSent++; }
                if (firstSent) router.Emit("event=jump-complete-sent id=" + ShortId(requestId) + " port=" + endpoint.Port + " gen=" + endpoint.Generation + " t=+" + router.latch.ElapsedMs() + "ms");
                return true;
            }

            /// <summary>The first 4 bytes of a RequestId as 8 hex characters (diagnostics only; a RequestId is not a secret, a token is never logged).</summary>
            private static string ShortId(byte[] id)
            {
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < 4 && i < id.Length; i++) sb.Append(id[i].ToString("x2"));
                return sb.ToString();
            }

            /// <summary>
            /// The JUMP_COMPLETE notice of a PLAIN command (no RequestId). Returns true when the pending notice is CONSUMED: sent plain in normal mode,
            /// dropped in managed mode. False = keep it pending (hold-off).
            /// </summary>
            internal bool SendJumpComplete(byte[] payload)
            {
                if (Mode == CurrentSenderMode.Normal)
                {
                    router.transport.Send(payload, router.legacyDestination);
                    router.Count(ref router.plainSent, null);
                    router.NoteFirstSend(false, 5U, null);
                    return true;
                }
                if (Mode == CurrentSenderMode.Managed)
                {
                    bool first;
                    lock (router.gate) { first = !router.jumpCompleteNoted; router.jumpCompleteNoted = true; }
                    router.Count(ref router.jumpCompleteExcluded, null);
                    if (first) router.Emit("event=jump-complete-excluded reason=pid-d6-request-id");
                    return true;
                }
                router.Count(ref router.held, null);
                return false;
            }
        }
    }
}
