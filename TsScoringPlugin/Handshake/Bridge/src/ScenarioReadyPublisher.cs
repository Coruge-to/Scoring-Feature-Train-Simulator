using System;
using System.IO.MemoryMappedFiles;
using System.Threading;

// ============================================================================
// PHASE C3 - publishes ScenarioReady to other readers of the same BVE process (the Caller now, Python later).
// Two named objects, both carrying the BVE process id so two BVE processes never mix:
//   Local\TSScoringPlugin.v1.<PID>.ScenarioReady   manual-reset event: SET = the current ScenarioGeneration is ScenarioReady
//   Local\TSScoringPlugin.v1.<PID>.ScenarioState   64-byte memory-only block: protocol, PID, ScenarioGeneration, level, sequence, check
// Order: for "ready" the block is written BEFORE the event is set; for "not ready" the event is reset BEFORE the block is written, so a
// reader that sees the event set always finds a block that agrees.
// Close(): event reset, block written with level 0, then both released. No file, registry, pipe or socket; default access rules.
// Phase SI-A6: the block also carries the load marker of the generation (ScenarioState.LoadInfo, bytes 24..35, written in the same seqlock write as the
// level), so that a reader learns "ScenarioCreated was received" without any Tick. The tracker writes it on BVE's own event / Tick thread; nothing here reads BVE.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal sealed class ScenarioReadyPublisher : IScenarioLoadPublisher
    {
        private readonly int pid;
        private EventWaitHandle readyEvent;
        private MemoryMappedFile section;
        private MemoryMappedViewAccessor view;

        internal ScenarioReadyPublisher(int pid)
        {
            this.pid = pid;
        }

        public bool IsOpen { get { return readyEvent != null && view != null; } }

        public void Open(int generation, bool ready)
        {
            OpenCore(generation, ready, 0, false);
        }

        /// <summary>Phase SI-A6: the same, with the load marker of the generation (bit0 ScenarioCreated, bit1 first Tick).</summary>
        public void OpenWithLoad(int generation, bool ready, int loadInfo)
        {
            OpenCore(generation, ready, loadInfo, true);
        }

        private void OpenCore(int generation, bool ready, int loadInfo, bool withLoad)
        {
            if (IsOpen)
            {
                UpdateCore(generation, ready, loadInfo, withLoad);
                return;
            }

            try
            {
                section = MemoryMappedFile.CreateOrOpen(HandshakeProtocol.ScenarioStateName(pid), ScenarioState.Size, MemoryMappedFileAccess.ReadWrite);
                view = section.CreateViewAccessor(0, ScenarioState.Size, MemoryMappedFileAccess.ReadWrite);
                bool created;
                readyEvent = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.ScenarioReadyName(pid), out created);
                readyEvent.Reset();
                UpdateCore(generation, ready, loadInfo, withLoad);
            }
            catch
            {
                ReleaseAll();
                throw;
            }
        }

        public void Update(int generation, bool ready)
        {
            UpdateCore(generation, ready, 0, false);
        }

        /// <summary>Phase SI-A6: the same, with the load marker of the generation (written in the same seqlock write as the level).</summary>
        public void UpdateWithLoad(int generation, bool ready, int loadInfo)
        {
            UpdateCore(generation, ready, loadInfo, true);
        }

        private void UpdateCore(int generation, bool ready, int loadInfo, bool withLoad)
        {
            if (!IsOpen)
            {
                throw new InvalidOperationException("closed");
            }

            if (ready)
            {
                WriteState(generation, true, loadInfo, withLoad);
                readyEvent.Set();
            }
            else
            {
                readyEvent.Reset();
                WriteState(generation, false, loadInfo, withLoad);
            }
        }

        private void WriteState(int generation, bool ready, int loadInfo, bool withLoad)
        {
            if (withLoad)
            {
                ScenarioState.WriteWithLoad(view, pid, generation, ready, loadInfo);
            }
            else
            {
                ScenarioState.Write(view, pid, generation, ready);
            }
        }

        public void Close()
        {
            try
            {
                if (readyEvent != null)
                {
                    readyEvent.Reset();
                }
            }
            catch
            {
            }

            try
            {
                if (view != null)
                {
                    ScenarioState current;
                    int generation = ScenarioState.TryReadView(view, pid, out current) ? current.ScenarioGeneration : 0;
                    ScenarioState.Write(view, pid, generation, false);
                }
            }
            catch
            {
            }

            ReleaseAll();
        }

        private void ReleaseAll()
        {
            EventWaitHandle e = readyEvent;
            readyEvent = null;
            if (e != null)
            {
                try { e.Dispose(); } catch { }
            }

            MemoryMappedViewAccessor v = view;
            view = null;
            if (v != null)
            {
                try { v.Dispose(); } catch { }
            }

            MemoryMappedFile s = section;
            section = null;
            if (s != null)
            {
                try { s.Dispose(); } catch { }
            }
        }
    }
}
