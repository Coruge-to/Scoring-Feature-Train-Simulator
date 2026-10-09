using System;
using System.IO.MemoryMappedFiles;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE E4 - the Session / Driving state of one Caller instance, published to its managed application.
//
// What is published (and nothing else): Session (= ScenarioReady is published for the current ScenarioGeneration), Driving (= the D1
// DrivingActive result, only ever ON while Session is ON), the ScenarioGeneration both belong to, a change counter and a Closed flag.
// The Caller side of the contract is the same for BVE6 Current, BVE5 Current and BVE5 Legacy: the application never sees which host API
// produced the two levels.
//
// Why a state block and not the two named events E0 sketched: an event carries one bit, so the ScenarioGeneration could not be told to the
// application, Session and Driving could not be read as ONE consistent pair (a hard OFF would show as two separate events) and the
// application would need a wait per level. One small named memory block per managed instance gives all of it in one lock-free read, converges
// to the current value however many changes were missed, and is written only when the state really changes.
//
// The block belongs to ONE managed instance (INST is new for every launch, never reused) of ONE BVE process: the object name carries both
// (Local\TSScoringPlugin.v1.<BVE PID>.App.<INST>.State) and the header repeats them, so a block of another instance / BVE process is never
// mistaken for ours. It is created by the Caller BEFORE the application is launched (like Stop), so the application reads the CURRENT value
// at start-up; before that moment the latest state is only remembered. At Dispose the Caller first publishes Session OFF / Driving OFF and
// then sets Closed, and only then signals Stop.
//
// Layout (fixed 64 bytes, little endian, identical in a 32-bit and a 64-bit process; numbers and the 16 hex digits of the instance only: no
// scenario / vehicle / user name, no path):
//   0  uint32  Magic 0x53415354 ("TSAS")      4  uint32  Version = 1       8  uint32  Size = 64     12 uint32  BVE process id
//   16 char[16] first 16 lower-case hex digits of the instance id (ASCII)
//   32 uint32  Head   seqlock: odd while the Caller is writing, even and different after every completed write
//   36 uint32  Flags  bit0 Session, bit1 Driving, bit2 Closed
//   40 int32   ScenarioGeneration (0 = none seen yet)
//   44 uint32  ChangeCount: number of completed state writes (the initial state is write 0)
//   48..59     reserved, zero
//   60 uint32  Tail   equals Head after a completed write (a reader accepts a copy only when Head == Tail and Head is even)
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>The fixed layout of the E4 state block (the single place of the offsets; managed_state.py mirrors it).</summary>
    internal static class AppStateLayout
    {
        public const int Size = 64;
        public const uint Magic = 0x53415354;
        public const uint Version = 1;
        public const int InstanceChars = 16;

        public const int OffMagic = 0;
        public const int OffVersion = 4;
        public const int OffSize = 8;
        public const int OffPid = 12;
        public const int OffInstance = 16;
        public const int OffHead = 32;
        public const int OffFlags = 36;
        public const int OffGeneration = 40;
        public const int OffChangeCount = 44;
        public const int OffTail = 60;

        public const uint FlagSession = 1;
        public const uint FlagDriving = 2;
        public const uint FlagClosed = 4;

        public static string InstancePrefix(string instance)
        {
            return instance.Length >= InstanceChars ? instance.Substring(0, InstanceChars) : instance.PadRight(InstanceChars, '0');
        }
    }

    /// <summary>What one successful write did (for the diagnostics).</summary>
    internal struct AppStateWrite
    {
        public bool Written;
        public bool Session;
        public bool Driving;
        public int Generation;
        public uint ChangeCount;
        public uint Head;
    }

    /// <summary>
    /// The writer of one managed instance's state block. Not thread-safe by itself: AppProcessManager serialises every call under its lock.
    /// A write that would not change anything is not made (the caller counts it as suppressed).
    /// </summary>
    internal sealed class AppStatePublisher
    {
        private MemoryMappedFile file;
        private MemoryMappedViewAccessor view;
        private uint head;
        private uint changeCount;
        private bool session;
        private bool driving;
        private int generation;
        private bool closed;

        private AppStatePublisher()
        {
        }

        public bool IsClosed { get { return closed; } }

        public uint ChangeCount { get { return changeCount; } }

        /// <summary>Creates the named block (it must not exist yet) and writes the valid, all-OFF header. Throws when that is impossible.</summary>
        public static AppStatePublisher Create(string name, int bveProcessId, string instance)
        {
            AppStatePublisher p = new AppStatePublisher();
            MemoryMappedFile f = null;
            MemoryMappedViewAccessor v = null;
            try
            {
                f = MemoryMappedFile.CreateNew(name, AppStateLayout.Size, MemoryMappedFileAccess.ReadWrite);
                v = f.CreateViewAccessor(0, AppStateLayout.Size, MemoryMappedFileAccess.ReadWrite);
                byte[] id = Encoding.ASCII.GetBytes(AppStateLayout.InstancePrefix(instance));
                v.Write(AppStateLayout.OffMagic, AppStateLayout.Magic);
                v.Write(AppStateLayout.OffVersion, AppStateLayout.Version);
                v.Write(AppStateLayout.OffSize, (uint)AppStateLayout.Size);
                v.Write(AppStateLayout.OffPid, (uint)bveProcessId);
                v.WriteArray(AppStateLayout.OffInstance, id, 0, AppStateLayout.InstanceChars);
                v.Write(AppStateLayout.OffFlags, 0u);
                v.Write(AppStateLayout.OffGeneration, 0);
                v.Write(AppStateLayout.OffChangeCount, 0u);
                Thread.MemoryBarrier();
                v.Write(AppStateLayout.OffTail, 0u);
                v.Write(AppStateLayout.OffHead, 0u);
                p.file = f;
                p.view = v;
                return p;
            }
            catch
            {
                if (v != null)
                {
                    try { v.Dispose(); } catch { }
                }

                if (f != null)
                {
                    try { f.Dispose(); } catch { }
                }

                throw;
            }
        }

        /// <summary>Publishes the state if it differs from the one in the block. Session OFF forces Driving OFF. After Close nothing is written.</summary>
        public AppStateWrite Write(bool newSession, bool newDriving, int newGeneration)
        {
            AppStateWrite r = new AppStateWrite();
            if (closed || view == null)
            {
                return r;
            }

            bool drv = newSession && newDriving;
            if (session == newSession && driving == drv && generation == newGeneration)
            {
                return r; // the block already says exactly this (the fresh header says all OFF / generation 0)
            }

            WriteBlock(newSession, drv, newGeneration, false);
            r.Written = true;
            r.Session = session;
            r.Driving = driving;
            r.Generation = generation;
            r.ChangeCount = changeCount;
            r.Head = head;
            return r;
        }

        /// <summary>Withdraws everything (Session OFF, Driving OFF) and sets Closed. Idempotent; returns the write that was made (Written=false if already closed).</summary>
        public AppStateWrite Close()
        {
            AppStateWrite r = new AppStateWrite();
            if (closed || view == null)
            {
                return r;
            }

            WriteBlock(false, false, generation, true);
            closed = true;
            r.Written = true;
            r.Session = false;
            r.Driving = false;
            r.Generation = generation;
            r.ChangeCount = changeCount;
            r.Head = head;
            return r;
        }

        /// <summary>Releases the block (the application may still hold its own view; the name disappears when it lets go).</summary>
        public void Dispose()
        {
            MemoryMappedViewAccessor v = view;
            MemoryMappedFile f = file;
            view = null;
            file = null;
            if (v != null)
            {
                try { v.Dispose(); } catch { }
            }

            if (f != null)
            {
                try { f.Dispose(); } catch { }
            }
        }

        private void WriteBlock(bool newSession, bool newDriving, int newGeneration, bool close)
        {
            uint writing = unchecked(head + 1);
            uint finalHead = unchecked(head + 2);
            uint next = unchecked(changeCount + 1);
            uint flags = (newSession ? AppStateLayout.FlagSession : 0u) | (newDriving ? AppStateLayout.FlagDriving : 0u) | (close ? AppStateLayout.FlagClosed : 0u);

            view.Write(AppStateLayout.OffHead, writing);       // odd: readers retry / reject
            Thread.MemoryBarrier();
            view.Write(AppStateLayout.OffFlags, flags);
            view.Write(AppStateLayout.OffGeneration, newGeneration);
            view.Write(AppStateLayout.OffChangeCount, next);
            Thread.MemoryBarrier();
            view.Write(AppStateLayout.OffTail, finalHead);
            Thread.MemoryBarrier();
            view.Write(AppStateLayout.OffHead, finalHead);     // even: stable

            head = finalHead;
            changeCount = next;
            session = newSession;
            driving = newDriving;
            generation = newGeneration;
        }
    }
}
