using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO.MemoryMappedFiles;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE PID-D6 (necessary minimum slice) - the Current jump endpoint of the per-PID DataPlane (PID-D0B-1 contract sections 9, 10, 11, 13.3, 15.3).
//
// CURRENT-ONLY code: no BveEx / BVE API, no Legacy type, no Caller type. It is compiled into the Current project only (TsScoringPlugin.csproj); the
// shared DataPlaneProtocol.cs / TelemetryDirectoryReader.cs are used unchanged. Written in C# 5 syntax so that the offline tests can compile it directly
// (Tests\Test-CurrentDataPlaneD6.ps1).
//
// What it does: the managed Python application sends a jump command (JUMP_STA_TIME / JUMP_LOC_TIME) inside an Envelope v1 with a nonzero RequestId to the
// loopback port that Current publishes in the Current Jump Receiver Directory (Local\TSScoringPlugin.v1.<BVE_PID>.CurrentJump). Current validates the
// datagram (contract 10 / 13.3) and hands the unchanged legacy command text, together with the RequestId, to the plugin; the plugin echoes the RequestId in
// the type 5 JUMP_COMPLETE envelope it returns to the Telemetry endpoint (CurrentTelemetryRouter.SendBatch.SendJumpComplete).
// The directory layout, the envelope, the ownership source (AppDirectory), the shutdown order and the Current / Legacy separation are those of D0B-1.
// ============================================================================
namespace TSScoringPlugin.DataPlane
{
    /// <summary>The Current Jump Receiver Directory capability bits of contract section 9 (parity-tested against dataplane_contract.py).</summary>
    internal static class JumpCapabilities
    {
        internal const UInt32 StationTime = 0x1U;
        internal const UInt32 LocationTime = 0x2U;
        internal const UInt32 RequestId = 0x4U;
        internal const UInt32 Published = StationTime | LocationTime | RequestId;
    }

    /// <summary>One validated jump command: the unchanged legacy text and the RequestId that must be echoed in JUMP_COMPLETE.</summary>
    internal sealed class CurrentJumpCommand
    {
        internal readonly string Text;
        internal readonly byte[] RequestId;
        internal readonly UInt32 MessageType;

        internal CurrentJumpCommand(string text, byte[] requestId, UInt32 messageType)
        {
            Text = text;
            RequestId = requestId;
            MessageType = messageType;
        }
    }

    /// <summary>
    /// Contract 10 / 13.3 for the Current jump receiver. Pure apart from the injected endpoint source: no socket, no clock. A rejected datagram changes
    /// nothing but the counters. Thread safe.
    /// </summary>
    internal sealed class JumpCommandValidator
    {
        internal const int RecentCapacity = 64;

        private readonly object gate = new object();
        private readonly int bvePid;
        private readonly UInt32 generation;
        private readonly byte[] token;
        private readonly IEndpointSource source;
        private readonly Action<string> log;
        private readonly Queue<string> recentOrder = new Queue<string>();
        private readonly HashSet<string> recent = new HashSet<string>();
        private readonly Dictionary<string, long> reasons = new Dictionary<string, long>();
        private long accepted;
        private long rejected;
        private bool firstAcceptNoted;

        internal JumpCommandValidator(int bvePid, UInt32 generation, byte[] token, IEndpointSource source, Action<string> log)
        {
            if (bvePid <= 0) throw new ArgumentOutOfRangeException("bvePid");
            if (generation == 0U) throw new ArgumentOutOfRangeException("generation");
            if (token == null || token.Length != 16) throw new ArgumentException("token");
            if (source == null) throw new ArgumentNullException("source");
            this.bvePid = bvePid;
            this.generation = generation;
            this.token = (byte[])token.Clone();
            this.source = source;
            this.log = log;
        }

        internal long Accepted { get { lock (gate) { return accepted; } } }
        internal long Rejected { get { lock (gate) { return rejected; } } }

        internal long ReasonCount(string reason)
        {
            lock (gate)
            {
                long n;
                return reasons.TryGetValue(reason, out n) ? n : 0L;
            }
        }

        internal string Summary()
        {
            lock (gate)
            {
                List<string> keys = new List<string>(reasons.Keys);
                keys.Sort(StringComparer.Ordinal);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < keys.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(keys[i]).Append(':').Append(reasons[keys[i]]);
                }
                return "event=jump-endpoint-summary accepted=" + accepted + " rejected=" + rejected + " reasons=" + (reasons.Count == 0 ? "-" : sb.ToString());
            }
        }

        /// <summary>The validated command, or null with the stable rejection reason. Never throws.</summary>
        internal CurrentJumpCommand Validate(byte[] datagram, out string reason)
        {
            try
            {
                CurrentJumpCommand command = ValidateCore(datagram, out reason);
                if (command == null) Reject(reason);
                return command;
            }
            catch
            {
                reason = "malformed";
                Reject(reason);
                return null;
            }
        }

        private CurrentJumpCommand ValidateCore(byte[] datagram, out string reason)
        {
            Envelope env;
            try
            {
                env = DataPlaneProtocol.DecodeEnvelope(datagram);                   // steps 1-4, the request-id rule and the known message type
            }
            catch (ArgumentException ex)
            {
                reason = "envelope-" + ex.Message;
                return null;
            }
            if (env.BvePid != (UInt32)bvePid) { reason = "bve-pid-mismatch"; return null; }                 // step 5

            TelemetryEndpoint owner;                                                                          // step 6: the current usable AppDirectory identity
            string why;
            bool resolved;
            try { resolved = source.TryResolve(bvePid, out owner, out why); }
            catch { owner = null; why = "resolve-error"; resolved = false; }
            if (!resolved || owner == null) { reason = "owner-" + why; return null; }
            if (!String.Equals(env.AppInstance, owner.AppInstance, StringComparison.Ordinal)) { reason = "app-instance-mismatch"; return null; }

            if (env.Generation != generation) { reason = "generation-mismatch"; return null; }               // step 7
            if (!ConstantTimeEquals(env.Token, token)) { reason = "token-mismatch"; return null; }
            if (env.MessageType != DataPlaneMessageTypes.JumpStationTime && env.MessageType != DataPlaneMessageTypes.JumpLocationTime)
            {
                reason = "message-type-not-allowed";                                                          // step 8
                return null;
            }
            if (env.SenderPid != owner.AppProcessId) { reason = "sender-pid-mismatch"; return null; }        // contract 11: the managed application sends commands

            string text;
            try { text = new UTF8Encoding(false, true).GetString(env.Payload); }
            catch { reason = "payload-grammar"; return null; }
            if (!ValidGrammar(env.MessageType, text)) { reason = "payload-grammar"; return null; }           // step 10

            string key = Convert.ToBase64String(env.RequestId);
            lock (gate)
            {
                if (recent.Contains(key)) { reason = "duplicate-request-id"; return null; }                  // contract 13.3: bounded recent-request cache
                recent.Add(key);
                recentOrder.Enqueue(key);
                while (recentOrder.Count > RecentCapacity) recent.Remove(recentOrder.Dequeue());
                accepted++;
                if (!firstAcceptNoted)
                {
                    firstAcceptNoted = true;
                    Emit("event=jump-command-first-accept type=0x" + env.MessageType.ToString("x") + " id=" + Hex8(env.RequestId));
                }
            }
            reason = null;
            return new CurrentJumpCommand(text, (byte[])env.RequestId.Clone(), env.MessageType);
        }

        private static bool ValidGrammar(UInt32 messageType, string text)
        {
            string[] parts = text.Split(':');
            if (parts.Length != 3) return false;
            int time;
            if (!Int32.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out time)) return false;
            if (messageType == DataPlaneMessageTypes.JumpStationTime)
            {
                int index;
                return parts[0] == "JUMP_STA_TIME" && Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index);
            }
            double location;
            return parts[0] == "JUMP_LOC_TIME" && Double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out location)
                && !Double.IsNaN(location) && !Double.IsInfinity(location);
        }

        private static bool ConstantTimeEquals(byte[] a, byte[] b)
        {
            if (a == null || b == null || a.Length != b.Length) return false;
            int diff = 0;
            for (int i = 0; i < a.Length; i++) diff |= a[i] ^ b[i];
            return diff == 0;
        }

        internal static string Hex8(byte[] id)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 4 && i < id.Length; i++) sb.Append(id[i].ToString("x2"));
            return sb.ToString();
        }

        private void Reject(string reason)
        {
            bool first;
            lock (gate)
            {
                rejected++;
                long n;
                reasons.TryGetValue(reason, out n);
                first = n == 0;
                reasons[reason] = n + 1;
            }
            if (first) Emit("event=jump-command-reject reason=" + reason);
        }

        private void Emit(string text)
        {
            if (log == null) return;
            try { log(text); } catch { }
        }
    }

    /// <summary>
    /// Writer of the Current Jump Receiver Directory (contract 9). One 128-byte named mapping, head / tail seqlock with the same write discipline as the
    /// AppDirectory publisher. The block is encoded by the shared DataPlaneProtocol codec.
    /// </summary>
    internal sealed class JumpDirectoryPublisher : IDisposable
    {
        private readonly UInt32 bvePid;
        private readonly MemoryMappedFile mapping;
        private readonly MemoryMappedViewAccessor view;
        private UInt32 sequence;
        private UInt32 changeCount;
        private bool disposed;

        internal JumpDirectoryPublisher(UInt32 bvePid, string objectName)
        {
            this.bvePid = bvePid;
            mapping = MemoryMappedFile.CreateNew(objectName, DataPlaneProtocol.DirectorySize, MemoryMappedFileAccess.ReadWrite);
            try
            {
                view = mapping.CreateViewAccessor(0, DataPlaneProtocol.DirectorySize, MemoryMappedFileAccess.ReadWrite);
            }
            catch
            {
                mapping.Dispose();
                throw;
            }
        }

        internal void Publish(UInt32 state, UInt32 port, UInt32 generation, byte[] token, UInt32 capabilities)
        {
            if (disposed) throw new ObjectDisposedException("JumpDirectoryPublisher");
            UInt32 odd = unchecked(sequence + 1U);
            if ((odd & 1U) == 0U) odd = unchecked(odd + 1U);
            UInt32 even = unchecked(odd + 1U);
            changeCount = unchecked(changeCount + 1U);
            byte[] block;
            if (state == DataPlaneProtocol.Closed)
            {
                block = DataPlaneProtocol.EncodeJumpDirectory(bvePid, even, state, 0U, 0U, 0U, new byte[16], changeCount, 0U);
            }
            else
            {
                block = DataPlaneProtocol.EncodeJumpDirectory(bvePid, even, state, bvePid, port, generation, token, changeCount, capabilities);
            }

            view.Write(16, odd);
            Thread.MemoryBarrier();
            view.WriteArray(0, block, 0, 16);
            view.WriteArray(20, block, 20, 104);
            Thread.MemoryBarrier();
            view.Write(124, even);
            Thread.MemoryBarrier();
            view.Write(16, even);
            view.Flush();
            sequence = even;
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            try { view.Dispose(); } catch { }
            try { mapping.Dispose(); } catch { }
        }
    }

    /// <summary>
    /// The production jump endpoint: one loopback UDP socket on port 0, published through the Current Jump Receiver Directory (contract 4.2 / 9 / 15.3).
    /// A failure to create it disables managed jump commands only (the caller catches and logs). Polled from the plugin's Tick; no thread.
    /// </summary>
    internal sealed class CurrentJumpEndpoint : IDisposable
    {
        private readonly object gate = new object();
        private readonly UdpClient client;
        private readonly JumpDirectoryPublisher publisher;
        private readonly JumpCommandValidator validator;
        private readonly byte[] token;
        private readonly UInt32 generation;
        private readonly UInt32 port;
        private readonly Action<string> log;
        private bool disposed;

        private CurrentJumpEndpoint(UdpClient client, JumpDirectoryPublisher publisher, JumpCommandValidator validator, byte[] token, UInt32 generation, UInt32 port, Action<string> log)
        {
            this.client = client;
            this.publisher = publisher;
            this.validator = validator;
            this.token = token;
            this.generation = generation;
            this.port = port;
            this.log = log;
        }

        internal UInt32 Port { get { return port; } }
        internal UInt32 Generation { get { return generation; } }
        internal byte[] TokenCopy { get { return (byte[])token.Clone(); } }
        internal JumpCommandValidator Validator { get { return validator; } }

        internal static CurrentJumpEndpoint Create(int bvePid, IEndpointSource source, Action<string> log)
        {
            return Create(bvePid, source, log, DataPlaneProtocol.JumpName((UInt32)bvePid));
        }

        internal static CurrentJumpEndpoint Create(int bvePid, IEndpointSource source, Action<string> log, string objectName)
        {
            UdpClient client = null;
            JumpDirectoryPublisher publisher = null;
            try
            {
                client = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
                client.Client.Blocking = false;
                UInt32 port = (UInt32)((IPEndPoint)client.Client.LocalEndPoint).Port;

                byte[] token = RandomBytes(16);
                UInt32 generation = BitConverter.ToUInt32(RandomBytes(4), 0);
                if (generation == 0U) generation = 1U;

                JumpCommandValidator validator = new JumpCommandValidator(bvePid, generation, token, source, log);
                publisher = new JumpDirectoryPublisher((UInt32)bvePid, objectName);
                publisher.Publish(DataPlaneProtocol.Published, port, generation, token, JumpCapabilities.Published);                                   // non-ready first
                publisher.Publish(DataPlaneProtocol.Published | DataPlaneProtocol.Ready, port, generation, token, JumpCapabilities.Published);     // then READY
                CurrentJumpEndpoint endpoint = new CurrentJumpEndpoint(client, publisher, validator, token, generation, port, log);
                if (log != null) { try { log("event=jump-endpoint-published port=" + port + " gen=" + generation); } catch { } }
                return endpoint;
            }
            catch
            {
                if (publisher != null) { try { publisher.Dispose(); } catch { } }
                if (client != null) { try { client.Close(); } catch { } }
                throw;
            }
        }

        private static byte[] RandomBytes(int count)
        {
            byte[] b = new byte[count];
            using (RandomNumberGenerator rng = RandomNumberGenerator.Create())
            {
                do { rng.GetBytes(b); } while (IsZero(b));
            }
            return b;
        }

        private static bool IsZero(byte[] b)
        {
            for (int i = 0; i < b.Length; i++) if (b[i] != 0) return false;
            return true;
        }

        /// <summary>Reads every pending datagram and appends the validated commands. Rejected datagrams are dropped (counted). Never throws.</summary>
        internal void Drain(List<CurrentJumpCommand> into)
        {
            try
            {
                lock (gate)
                {
                    if (disposed) return;
                    while (client.Available > 0)
                    {
                        IPEndPoint from = new IPEndPoint(IPAddress.Any, 0);
                        byte[] data = client.Receive(ref from);
                        string reason;
                        CurrentJumpCommand command = validator.Validate(data, out reason);
                        if (command != null) into.Add(command);
                    }
                }
            }
            catch
            {
            }
        }

        /// <summary>Contract 15.3: WITHDRAWING, stop polling, close the socket, CLOSED, release the directory. Idempotent.</summary>
        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
            }
            try { publisher.Publish(DataPlaneProtocol.Published | DataPlaneProtocol.Ready | DataPlaneProtocol.Withdrawing, port, generation, token, JumpCapabilities.Published); } catch { }
            try { client.Close(); } catch { }
            try { publisher.Publish(DataPlaneProtocol.Closed, 0U, 0U, new byte[16], 0U); } catch { }
            try { publisher.Dispose(); } catch { }
            if (log != null) { try { log(validator.Summary()); } catch { } }
        }
    }
}
