using System;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - one generation of endpoint resources of the Legacy Jump control plane.
//
// The Legacy Jump Directory (Local\TSScoringPlugin.v1.<BVE PID>.LegacyJump, PID-D0B-1 STDJ v1, 128 bytes) tells the managed application where this BVE process
// receives jump commands. This file owns what one published endpoint is made of: the name, the dynamic loopback datagram port, the Directory writer, the generation
// and the 128 bit token of this publication, the shared command validator (Envelope v1 decode, BVE PID / AppInstance / sender PID / generation / token checks,
// duplicate request ids) and the record of the owner that the validator resolved for the datagram it just judged. It is the only file of the project that reads a
// datagram from a port.
//
// The seams (ILegacyJump...) are the five places where the production implementation can be wrapped by a recording or fault injecting double; the production
// implementations are the classes below the interfaces. Nothing in here is a host type: the shared DataPlane sources (linked) are the only dependency.
// The Directory is written through the shared JumpDirectoryPublisher (CreateNew only: an existing mapping is never opened, adopted or overwritten).
// The Capabilities of the 2A-alpha plane are REQUEST_ID only; no command is executed here or anywhere in this project.
//
// NOT thread safe: only the control plane touches an endpoint, always under its single gate. Written in C# 5 syntax on purpose.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>The name of the Legacy Jump Directory of a BVE process. The only definition on the C# side (parity-tested against dataplane_contract.py).</summary>
    internal static class LegacyJumpNames
    {
        internal static string For(int bvePid)
        {
            if (bvePid <= 0) throw new ArgumentOutOfRangeException("bvePid");
            return "Local\\TSScoringPlugin.v1." + bvePid.ToString() + ".LegacyJump";
        }
    }

    /// <summary>A bound loopback datagram port. Reads never block: ReadDatagram is called only while Available is above zero.</summary>
    internal interface ILegacyJumpSocket
    {
        int Port { get; }
        int Available { get; }
        byte[] ReadDatagram();
        void Close();
    }

    internal interface ILegacyJumpSocketFactory
    {
        ILegacyJumpSocket Bind();
    }

    /// <summary>The writer of one Directory mapping.</summary>
    internal interface ILegacyJumpWriter
    {
        void Publish(UInt32 state, UInt32 port, UInt32 generation, byte[] token, UInt32 capabilities);
        void Release();
    }

    internal interface ILegacyJumpWriterFactory
    {
        ILegacyJumpWriter Create(int bvePid, string objectName);
    }

    internal sealed class LegacyJumpUdpPort : ILegacyJumpSocket
    {
        private readonly UdpClient client;
        private readonly int port;

        internal LegacyJumpUdpPort()
        {
            UdpClient c = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));      // the OS chooses the port; loopback only
            try
            {
                c.Client.Blocking = false;
                port = ((IPEndPoint)c.Client.LocalEndPoint).Port;
            }
            catch
            {
                try { c.Close(); } catch { }
                throw;
            }
            client = c;
        }

        public int Port { get { return port; } }

        public int Available { get { return client.Available; } }

        public byte[] ReadDatagram()
        {
            IPEndPoint from = new IPEndPoint(IPAddress.Any, 0);
            return client.Receive(ref from);
        }

        public void Close()
        {
            client.Close();
        }
    }

    internal sealed class LegacyJumpUdpPortFactory : ILegacyJumpSocketFactory
    {
        public ILegacyJumpSocket Bind()
        {
            return new LegacyJumpUdpPort();
        }
    }

    internal sealed class LegacyJumpMappingWriter : ILegacyJumpWriter
    {
        private readonly JumpDirectoryPublisher publisher;

        internal LegacyJumpMappingWriter(int bvePid, string objectName)
        {
            publisher = new JumpDirectoryPublisher((UInt32)bvePid, objectName);       // CreateNew only: it fails when the name is alive
        }

        public void Publish(UInt32 state, UInt32 port, UInt32 generation, byte[] token, UInt32 capabilities)
        {
            publisher.Publish(state, port, generation, token, capabilities);
        }

        public void Release()
        {
            publisher.Dispose();
        }
    }

    internal sealed class LegacyJumpMappingWriterFactory : ILegacyJumpWriterFactory
    {
        public ILegacyJumpWriter Create(int bvePid, string objectName)
        {
            return new LegacyJumpMappingWriter(bvePid, objectName);
        }
    }

    /// <summary>Remembers the owner that the shared validator resolved for the datagram it just validated (the validator asks for the owner exactly once per datagram).</summary>
    internal sealed class RecordingEndpointSource : IEndpointSource
    {
        private readonly IEndpointSource inner;
        internal TelemetryEndpoint LastOwner;

        internal RecordingEndpointSource(IEndpointSource inner)
        {
            this.inner = inner;
        }

        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            bool ok = inner.TryResolve(bveProcessId, out endpoint, out reason);
            LastOwner = ok ? endpoint : null;
            return ok;
        }
    }

    /// <summary>One generation of endpoint resources: port, writer, validator, identity. A new publication is a new instance (new port, generation, token).</summary>
    internal sealed class LegacyJumpEndpoint
    {
        /// <summary>The two fixed ports of the product (the telemetry port and the one above it). An OS chosen port that equals one of them is never used.</summary>
        internal static readonly int[] NeverBindPorts = new int[] { TelemetryContract.Port, TelemetryContract.Port + 1 };

        internal readonly int BvePid;
        internal readonly ILegacyJumpSocket Socket;
        internal readonly ILegacyJumpWriter Writer;
        internal readonly JumpCommandValidator Validator;
        internal readonly RecordingEndpointSource Recording;
        internal readonly UInt32 Generation;
        internal readonly byte[] Token;
        internal readonly UInt32 Port;

        private LegacyJumpEndpoint(int bvePid, ILegacyJumpSocket socket, ILegacyJumpWriter writer, JumpCommandValidator validator, RecordingEndpointSource recording, UInt32 generation, byte[] token, UInt32 port)
        {
            BvePid = bvePid;
            Socket = socket;
            Writer = writer;
            Validator = validator;
            Recording = recording;
            Generation = generation;
            Token = token;
            Port = port;
        }

        /// <summary>
        /// Builds the resources of one publication, in this order: bind a new port, refuse a fixed product port (before any mapping exists), draw a new generation and
        /// a new token (never the previous ones), create the mapping with CreateNew. Nothing is published here. A failure at any step releases what the earlier steps
        /// took (the port) and throws; the caller retries with a completely new attempt.
        /// </summary>
        internal static LegacyJumpEndpoint Open(LegacyJumpEnvironment env, string objectName, UInt32 previousGeneration, byte[] previousToken, Action<string> note)
        {
            ILegacyJumpSocket socket = null;
            ILegacyJumpWriter writer = null;
            try
            {
                socket = env.Sockets.Bind();
                UInt32 port = (UInt32)socket.Port;
                if (IsNeverBind((int)port)) throw new InvalidOperationException("port-vetoed");
                UInt32 generation = NewGeneration(previousGeneration);
                byte[] token = NewToken(previousToken);
                RecordingEndpointSource recording = new RecordingEndpointSource(env.Source);
                JumpCommandValidator validator = new JumpCommandValidator(env.BvePid, generation, token, recording, note, true);      // Phase ST-3c: the shared JumpWire grammar (v1 and v2), the same gate as the Current endpoint
                writer = env.Writers.Create(env.BvePid, objectName);
                return new LegacyJumpEndpoint(env.BvePid, socket, writer, validator, recording, generation, token, port);
            }
            catch
            {
                if (socket != null) { try { socket.Close(); } catch { } }
                if (writer != null) { try { writer.Release(); } catch { } }
                throw;
            }
        }

        /// <summary>
        /// Judges one datagram with the shared validator and hands the result to the queue: a Rejected receipt with the stable reason, or a Queued receipt that fixes the
        /// owner (AppInstance, App PID, telemetry generation / token / port), the receiver generation, the time it was read and the scenario boundary. The command text
        /// and the request id are kept opaquely.
        /// </summary>
        internal void Handle(byte[] datagram, long nowMs, int scenarioEpoch, LegacyJumpCommandQueue queue)
        {
            string reason;
            Recording.LastOwner = null;
            CurrentJumpCommand command = Validator.Validate(datagram, out reason);
            if (command == null)
            {
                LegacyJumpReceipt rejected = new LegacyJumpReceipt();
                rejected.ReceivedAtMs = nowMs;
                rejected.ReceiverGeneration = Generation;
                queue.AddRejected(rejected, reason);
                return;
            }
            TelemetryEndpoint owner = Recording.LastOwner;
            if (owner == null)
            {
                LegacyJumpReceipt unowned = new LegacyJumpReceipt();
                unowned.RequestId = command.RequestId;
                unowned.ReceivedAtMs = nowMs;
                unowned.ReceiverGeneration = Generation;
                queue.AddRejected(unowned, "owner-not-recorded");
                return;
            }
            LegacyJumpReceipt receipt = new LegacyJumpReceipt();
            receipt.RequestId = command.RequestId;
            receipt.MessageType = command.MessageType;
            receipt.Text = command.Text;
            receipt.BvePid = BvePid;
            receipt.AppInstance = owner.AppInstance;
            receipt.AppPid = owner.AppProcessId;
            receipt.TelemetryGeneration = owner.Generation;
            receipt.TelemetryToken = (byte[])owner.Token.Clone();
            receipt.TelemetryPort = owner.Port;
            receipt.ReceiverGeneration = Generation;
            receipt.ReceivedAtMs = nowMs;
            receipt.ScenarioEpoch = scenarioEpoch;
            queue.Enqueue(receipt);
        }

        internal static bool IsNeverBind(int port)
        {
            for (int i = 0; i < NeverBindPorts.Length; i++)
            {
                if (NeverBindPorts[i] == port) return true;
            }
            return false;
        }

        /// <summary>A non-zero generation that differs from the previous one of this plane.</summary>
        internal static UInt32 NewGeneration(UInt32 previous)
        {
            UInt32 g;
            do { g = BitConverter.ToUInt32(RandomBytes(4), 0); } while (g == 0U || g == previous);
            return g;
        }

        /// <summary>A non-zero 16 byte token that differs from the previous one of this plane.</summary>
        internal static byte[] NewToken(byte[] previous)
        {
            byte[] t;
            do { t = RandomBytes(16); } while (previous != null && SameBytes(t, previous));
            return t;
        }

        private static byte[] RandomBytes(int count)
        {
            byte[] b = new byte[count];
            using (RandomNumberGenerator rng = RandomNumberGenerator.Create())
            {
                bool zero;
                do
                {
                    rng.GetBytes(b);
                    zero = true;
                    for (int i = 0; i < b.Length; i++)
                    {
                        if (b[i] != 0) { zero = false; break; }
                    }
                } while (zero);
            }
            return b;
        }

        internal static bool SameBytes(byte[] a, byte[] b)
        {
            if (a == null || b == null || a.Length != b.Length) return false;
            for (int i = 0; i < a.Length; i++)
            {
                if (a[i] != b[i]) return false;
            }
            return true;
        }
    }
}
