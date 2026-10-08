using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;

// ============================================================================
// PHASE B HANDSHAKE PROTOTYPE - shared protocol definition.
// This single source file is compiled into BOTH the input-device Caller and
// the BveEX Bridge (no shared assembly, no shared state except the named
// kernel objects below). Everything here uses public .NET APIs only.
//
// Four separate facts (this prototype implements the first three):
//   Enabled          the user switched TS Scoring ON in BVE's input-device settings          (Caller)
//   BridgeAvailable  BveEX loaded the Bridge extension, so the Bridge exists in the process  (Bridge, at load time)
//   Ready            the Bridge has recognised Enabled: Caller<->Bridge handshake is up      (Bridge)
//   ScenarioReady    the scenario is loaded and BVE data can be read safely                  (future Bridge; NOT in Phase B)
// Ready is NOT ScenarioReady and NOT "the scoring app is up". BveEX's Tick runs only while a scenario is being driven,
// so "Ready is missing" must never be read as "BveEX is missing"; only the absence of BridgeAvailable means that.
//
// Objects (Local\ = per logon session, <PID> = BVE process id):
//   Local\TSScoringPlugin.v1.<PID>.Enabled          manual-reset event, created+set by the Caller while enabled
//   Local\TSScoringPlugin.v1.<PID>.Stop             manual-reset event, created by the Caller, set when the Caller ends
//   Local\TSScoringPlugin.v1.<PID>.BridgeAvailable  manual-reset event, created+set by the Bridge when BveEX loads it
//   Local\TSScoringPlugin.v1.<PID>.Ready            manual-reset event, created+set by the Bridge while the handshake is up
//   Local\TSScoringPlugin.v1.<PID>.BridgeInfo       fixed-size memory-only section with instrumentation numbers
//                                                   (PHASE B MEASUREMENT ONLY - a removal candidate after Phase B)
// The protocol names keep the technical identifier "TSScoringPlugin"; the human-facing product name is "TS Scoring".
// No Global\ names, no files, no registry, no UDP/TCP/pipes, default access rules.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal static class HandshakeProtocol
    {
        public const int Version = 1;

        public static string EnabledName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".Enabled"; }
        public static string StopName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".Stop"; }
        public static string BridgeAvailableName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".BridgeAvailable"; }
        public static string ReadyName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".Ready"; }
        public static string InfoName(int pid) { return "Local\\TSScoringPlugin.v1." + pid + ".BridgeInfo"; }

        public static int CurrentProcessId()
        {
            using (Process process = Process.GetCurrentProcess())
            {
                return process.Id;
            }
        }

        public static double QpcToMs(long qpcTicks)
        {
            return qpcTicks * 1000.0 / Stopwatch.Frequency;
        }
    }

    /// <summary>
    /// THE single source of truth for every timing value (both DLLs read it). Change them here only.
    /// Neither Ready nor ScenarioReady has a timeout: a scenario may take any time to be chosen and loaded.
    /// </summary>
    internal static class HandshakeTiming
    {
        /// <summary>Target: BridgeAvailable should appear within this time after the Caller was enabled (measured, not an error).</summary>
        public static readonly int TargetBridgeAvailableMs = 500;

        /// <summary>
        /// BveEX-dependency notice timeout: the one-time notice is requested only after BridgeAvailable has been missing
        /// for this long without a break (measured on a real BVE6: BridgeAvailable is seen after about 310-320 ms).
        /// </summary>
        public static readonly int BridgeMissingTimeoutMs = 500;

        /// <summary>Caller: interval of its own background monitor thread (never BVE's thread).</summary>
        public static readonly int CallerPollMs = 20;

        /// <summary>Bridge: minimum spacing between two cheap checks made from Tick.</summary>
        public static readonly int BridgePollMs = 100;
    }

    /// <summary>
    /// PHASE B MEASUREMENT BLOCK (removal candidate after Phase B, not for production).
    /// Fixed length, every offset is inside Size. Written by the Bridge while Ready is published; read (best effort) by the Caller.
    /// A missing, short, corrupt or wrong-version block only makes the timing numbers "Unavailable"; neither the handshake nor the
    /// BridgeAvailable decision ever depends on it.
    /// </summary>
    internal struct BridgeInfo
    {
        public const int Size = 128;
        public const int InfoVersion = 3;

        public int ProtocolVersion;          // offset 0
        public int Bitness;                  // 4
        public long BridgeLoadQpc;           // 8
        public long AvailableCreatedQpc;     // 16 latest BridgeAvailable creation
        public long ReadyCreatedQpc;         // 24 latest Ready creation
        public long BridgeLoadUtcTicks;      // 32
        public long ReadyCreatedUtcTicks;    // 40
        public long AvailableDestroyedQpc;   // 48 previous BridgeAvailable destruction (0 = none yet)
        public long ReadyDestroyedQpc;       // 56 previous Ready destruction (0 = none yet)
        public int AvailableCreateCount;     // 64
        public int AvailableDestroyCount;    // 68
        public int ReadyCreateCount;         // 72
        public int ReadyDestroyCount;        // 76
        public long LastEnabledSeenQpc;      // 80
        public long LastStopSeenQpc;         // 88  (96..127 reserved)

        public void WriteTo(MemoryMappedViewAccessor view)
        {
            view.Write(0, ProtocolVersion);
            view.Write(4, Bitness);
            view.Write(8, BridgeLoadQpc);
            view.Write(16, AvailableCreatedQpc);
            view.Write(24, ReadyCreatedQpc);
            view.Write(32, BridgeLoadUtcTicks);
            view.Write(40, ReadyCreatedUtcTicks);
            view.Write(48, AvailableDestroyedQpc);
            view.Write(56, ReadyDestroyedQpc);
            view.Write(64, AvailableCreateCount);
            view.Write(68, AvailableDestroyCount);
            view.Write(72, ReadyCreateCount);
            view.Write(76, ReadyDestroyCount);
            view.Write(80, LastEnabledSeenQpc);
            view.Write(88, LastStopSeenQpc);
        }

        public static bool TryRead(int pid, out BridgeInfo info)
        {
            info = new BridgeInfo();
            try
            {
                using (MemoryMappedFile section = MemoryMappedFile.OpenExisting(HandshakeProtocol.InfoName(pid), MemoryMappedFileRights.Read))
                using (MemoryMappedViewAccessor view = section.CreateViewAccessor(0, Size, MemoryMappedFileAccess.Read))
                {
                    BridgeInfo read = new BridgeInfo();
                    read.ProtocolVersion = view.ReadInt32(0);
                    read.Bitness = view.ReadInt32(4);
                    read.BridgeLoadQpc = view.ReadInt64(8);
                    read.AvailableCreatedQpc = view.ReadInt64(16);
                    read.ReadyCreatedQpc = view.ReadInt64(24);
                    read.BridgeLoadUtcTicks = view.ReadInt64(32);
                    read.ReadyCreatedUtcTicks = view.ReadInt64(40);
                    read.AvailableDestroyedQpc = view.ReadInt64(48);
                    read.ReadyDestroyedQpc = view.ReadInt64(56);
                    read.AvailableCreateCount = view.ReadInt32(64);
                    read.AvailableDestroyCount = view.ReadInt32(68);
                    read.ReadyCreateCount = view.ReadInt32(72);
                    read.ReadyDestroyCount = view.ReadInt32(76);
                    read.LastEnabledSeenQpc = view.ReadInt64(80);
                    read.LastStopSeenQpc = view.ReadInt64(88);

                    if (!read.LooksValid())
                    {
                        return false;
                    }

                    info = read;
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        private bool LooksValid()
        {
            return ProtocolVersion == InfoVersion
                && (Bitness == 32 || Bitness == 64)
                && BridgeLoadQpc > 0
                && AvailableCreatedQpc >= BridgeLoadQpc
                && ReadyCreatedQpc >= AvailableCreatedQpc
                && AvailableCreateCount >= 1 && AvailableCreateCount < 1000000
                && AvailableDestroyCount >= 0 && AvailableDestroyCount < 1000000
                && ReadyCreateCount >= 1 && ReadyCreateCount < 1000000
                && ReadyDestroyCount >= 0 && ReadyDestroyCount < 1000000;
        }
    }
}
