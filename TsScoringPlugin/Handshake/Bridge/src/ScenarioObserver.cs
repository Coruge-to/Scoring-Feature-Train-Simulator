using System;
using System.Collections.Generic;

// ============================================================================
// PHASE C1 OBSERVATION BUILD - Track A: scenario life-cycle observer. It only WRITES LOG LINES.
// It is NOT ScenarioReady: nothing here creates a named Event, a public state, a notification or a callback to the Caller / Python.
// A "candidate" below is a moment at which a possible future ScenarioReady condition would be true; the log records when each
// candidate would have fired so that the real BVE order can be compared later.
//
// The class knows nothing about BveEX types (the Bridge feeds it plain calls and two small readers), so the offline tests can drive
// it with fakes. All calls are expected on BVE's life-cycle thread; a lock keeps it safe if BveEX ever calls from elsewhere.
// Output policy: state changes only. A normal frame produces NO line. No scenario / vehicle names are ever read or logged.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>Candidate ids (fixed vocabulary of the C1 log).</summary>
    internal static class ScenarioReadyCandidates
    {
        public const string A = "A"; // ScenarioCreated received
        public const string B = "B"; // IsScenarioCreated became true
        public const string C = "C"; // first Tick after ScenarioCreated
        public const string D = "D"; // IsScenarioCreated true AND the first Tick after ScenarioCreated
        public const string E = "E"; // first Tick after ScenarioCreated at which the BVE objects we would need could be read safely
        public const string F = "F"; // first PostTick (frame finished, after every extension's Tick) with the E conditions - found in the API survey (IBveHacker.PostTick)

        public static string Describe(string id)
        {
            switch (id)
            {
                case A: return "ScenarioCreated-event";
                case B: return "IsScenarioCreated-true";
                case C: return "first-Tick-after-ScenarioCreated";
                case D: return "IsScenarioCreated-true-and-first-Tick-after-ScenarioCreated";
                case E: return "first-Tick-with-BVE-info-readable";
                case F: return "first-PostTick-with-BVE-info-readable";
                default: return "unknown";
            }
        }
    }

    internal sealed class ScenarioObserver
    {
        internal const string TrackA = "A";
        internal const string TrackAB = "AB";

        /// <summary>A Tick gap longer than this is reported once when the Ticks resume (BveEX stops calling Tick e.g. while paused).</summary>
        internal const int TickGapReportMs = 1000;

        private readonly object gate = new object();
        private readonly Action<string, string, string> log;     // (track, event, detail)
        private readonly Func<int> readIsCreated;                // 1 true, 0 false, -1 unreadable
        private readonly Func<string> probeBveInfo;              // null = readable now; otherwise a short reason code
        private readonly Func<string> readyState;                // "Y" / "N" (the Phase B Ready event is published or not)
        private readonly Func<long> nowMs;                       // monotonic clock (injectable for the tests)

        // life-cycle state
        private int scenarioGeneration;       // "ScenarioGeneration": +1 at every ScenarioOpened (or implicit start); candidates are per generation
        private bool generationOpen;
        private bool lateAttach;              // this generation was joined after ScenarioCreated had already happened
        private long ticksTotal;
        private long ticksGen, preTicksGen, postTicksGen;
        private bool firstTickLogged;
        private long lastTickMs = -1;
        private int lastIsCreated = -2;       // -2 = never read
        private bool orphanTickLogged;

        // per generation
        private bool openedSeen, previewSeen, createdSeen, createdEventSeen;
        private bool candA, candB, candC, candD, candE, candF;
        private bool tickAfterCreatedDone, dMissedLogged;
        private string lastEPending, lastFPending;
        private readonly List<string> frameOrder = new List<string>(3);
        private bool frameOrderLogged;
        private bool isCreatedAtOpen;

        internal ScenarioObserver(Action<string, string, string> log, Func<int> readIsCreated, Func<string> probeBveInfo, Func<string> readyState, Func<long> nowMs)
        {
            this.log = log ?? delegate { };
            this.readIsCreated = readIsCreated ?? delegate { return -1; };
            this.probeBveInfo = probeBveInfo ?? delegate { return "no-probe"; };
            this.readyState = readyState ?? delegate { return "?"; };
            this.nowMs = nowMs ?? delegate { return Environment.TickCount; };
        }

        internal int ScenarioGeneration { get { lock (gate) { return scenarioGeneration; } } }
        internal long TicksTotal { get { lock (gate) { return ticksTotal; } } }

        // ---- public entry points (each one is exception-safe) ----

        public void OnAllExtensionsLoaded()
        {
            Safe(delegate
            {
                lock (gate) { Emit(TrackA, "ALL_EXT_LOADED", Common() + " isCreated=" + Tri(Read())); }
            });
        }

        public void OnScenarioOpened(bool isReload)
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (generationOpen)
                    {
                        SummariseLocked("replaced-by-open"); // the previous generation never saw a ScenarioClosed
                    }

                    BeginGenerationLocked("ScenarioOpened");
                    openedSeen = true;
                    int v = Read();
                    isCreatedAtOpen = v == 1;
                    ObserveIsCreatedLocked(v, "Open", false);
                    Emit(TrackA, "SCN_OPENED", Common() + " isReload=" + (isReload ? "yes" : "no") + " isCreated=" + Tri(v) + (isCreatedAtOpen ? " staleIsCreated=yes" : ""));
                }
            });
        }

        public void OnPreviewScenarioCreated()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    EnsureGenerationLocked("PreviewScenarioCreated-without-open");
                    previewSeen = true;
                    int v = Read();
                    Emit(TrackA, "SCN_PREVIEW_CREATED", Common() + " isCreated=" + Tri(v) + " ticksSoFar=" + ticksGen);
                    ObserveIsCreatedLocked(v, "Preview", true);
                }
            });
        }

        public void OnScenarioCreated()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    EnsureGenerationLocked("ScenarioCreated-without-open");
                    createdSeen = true;
                    createdEventSeen = true;
                    int v = Read();
                    Emit(TrackA, "SCN_CREATED", Common() + " isCreated=" + Tri(v) + " previewSeen=" + YN(previewSeen) + " ticksSoFar=" + ticksGen + " ready=" + readyState());
                    if (!candA)
                    {
                        candA = true;
                        Candidate(ScenarioReadyCandidates.A, "at=event");
                    }

                    ObserveIsCreatedLocked(v, "Created", true);
                }
            });
        }

        public void OnScenarioClosed()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    int v = Read();
                    ObserveIsCreatedLocked(v, "Closed", false);
                    if (generationOpen)
                    {
                        SummariseLocked("closed");
                    }

                    generationOpen = false;
                    orphanTickLogged = false;
                    Emit(TrackA, "SCN_CLOSED", Common() + " isCreated=" + Tri(v));
                }
            });
        }

        /// <summary>The extension's own Tick (BveEX calls it every frame while a scenario is driven).</summary>
        public void OnTick()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    long now = nowMs();
                    ticksTotal++;
                    if (!firstTickLogged)
                    {
                        firstTickLogged = true; // the first-Tick line itself is written by the Bridge (it also knows BridgeAvailable / Ready)
                    }
                    else if (lastTickMs >= 0 && now - lastTickMs > TickGapReportMs)
                    {
                        Emit(TrackA, "TICK_GAP", Common() + " gapMs=" + (now - lastTickMs) + " (Tick resumed; BveEX stops Tick e.g. while paused or outside a running scenario)");
                    }

                    lastTickMs = now;
                    ticksGen++;

                    int v = Read();
                    ObserveIsCreatedLocked(v, "Tick", true);

                    if (!generationOpen)
                    {
                        if (v == 1)
                        {
                            // BveEX loaded this Bridge after the scenario already exists (no Opened / Created seen): join late.
                            BeginGenerationLocked("late-attach-IsScenarioCreated");
                            lateAttach = true;
                            createdSeen = true;
                            Emit(TrackA, "LATE_ATTACH", Common() + " (ScenarioOpened / ScenarioCreated were not seen for this scenario)");
                            ObserveIsCreatedLocked(v, "Tick", true);
                        }
                        else if (!orphanTickLogged)
                        {
                            orphanTickLogged = true;
                            Emit(TrackA, "TICK_OUTSIDE_GENERATION", Common() + " isCreated=" + Tri(v) + " (Tick with no open scenario generation; logged once per stretch)");
                        }
                    }

                    if (generationOpen)
                    {
                        NoteFrame("Tick");

                        if (createdSeen && !tickAfterCreatedDone)
                        {
                            tickAfterCreatedDone = true;
                            if (!candC)
                            {
                                candC = true;
                                Candidate(ScenarioReadyCandidates.C, "isCreated=" + Tri(v) + (lateAttach ? " lateAttach=yes" : ""));
                            }

                            if (v == 1)
                            {
                                if (!candD)
                                {
                                    candD = true;
                                    Candidate(ScenarioReadyCandidates.D, (lateAttach ? "lateAttach=yes" : "at=first-tick"));
                                }
                            }
                            else if (!dMissedLogged)
                            {
                                dMissedLogged = true;
                                Emit(TrackA, "CAND_D_NOT_MET", Common() + " isCreated=" + Tri(v) + " (IsScenarioCreated was not true at the first Tick after ScenarioCreated)");
                            }
                        }

                        if (createdSeen && !candE && v == 1)
                        {
                            string reason = Probe();
                            if (reason == null)
                            {
                                candE = true;
                                Candidate(ScenarioReadyCandidates.E, "tickInGen=" + ticksGen);
                            }
                            else if (reason != lastEPending)
                            {
                                lastEPending = reason;
                                Emit(TrackA, "CAND_E_PENDING", Common() + " reason=" + reason + " tickInGen=" + ticksGen);
                            }
                        }
                    }
                }
            });
        }

        /// <summary>BveHacker.PreviewTick: right before BveEX starts calling the extensions' Tick for this frame.</summary>
        public void OnPreviewTick()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (generationOpen)
                    {
                        preTicksGen++;
                        NoteFrame("PreviewTick");
                    }
                }
            });
        }

        /// <summary>BveHacker.PostTick: every extension's Tick of this frame has run.</summary>
        public void OnPostTick()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (!generationOpen)
                    {
                        return;
                    }

                    postTicksGen++;
                    NoteFrame("PostTick");
                    if (createdSeen && !candF)
                    {
                        int v = Read();
                        if (v == 1)
                        {
                            string reason = Probe();
                            if (reason == null)
                            {
                                candF = true;
                                Candidate(ScenarioReadyCandidates.F, "postTickInGen=" + postTicksGen + (lateAttach ? " lateAttach=yes" : ""));
                            }
                            else if (reason != lastFPending)
                            {
                                lastFPending = reason;
                                Emit(TrackA, "CAND_F_PENDING", Common() + " reason=" + reason + " postTickInGen=" + postTicksGen);
                            }
                        }
                    }
                }
            });
        }

        public void OnDispose()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (generationOpen)
                    {
                        SummariseLocked("dispose-with-open-generation");
                    }

                    Emit(TrackAB, "OBSERVER_DISPOSE", Common() + " ticksTotal=" + ticksTotal + " generations=" + scenarioGeneration + " isCreated=" + Tri(Read()));
                }
            });
        }

        // ---- internals (gate held) ----

        private void BeginGenerationLocked(string source)
        {
            scenarioGeneration++;
            generationOpen = true;
            lateAttach = false;
            openedSeen = previewSeen = createdSeen = createdEventSeen = false;
            candA = candB = candC = candD = candE = candF = false;
            tickAfterCreatedDone = dMissedLogged = false;
            lastEPending = lastFPending = null;
            ticksGen = preTicksGen = postTicksGen = 0;
            frameOrder.Clear();
            frameOrderLogged = false;
            isCreatedAtOpen = false;
            orphanTickLogged = false;
            Emit(TrackA, "GEN_BEGIN", Common() + " source=" + source);
        }

        private void EnsureGenerationLocked(string source)
        {
            if (!generationOpen)
            {
                BeginGenerationLocked(source);
            }
        }

        /// <summary>Records the IsScenarioCreated value; logs only when it differs from the last value read.</summary>
        private void ObserveIsCreatedLocked(int value, string where, bool allowCandidateB)
        {
            if (value != lastIsCreated)
            {
                int previous = lastIsCreated;
                lastIsCreated = value;
                Emit(TrackA, "IS_CREATED_CHANGED", Common() + " from=" + Tri(previous) + " to=" + Tri(value) + " where=" + where);
            }

            if (allowCandidateB && value == 1 && generationOpen && !candB)
            {
                candB = true;
                Candidate(ScenarioReadyCandidates.B, "where=" + where + " beforeCreatedEvent=" + YN(!createdEventSeen) + (isCreatedAtOpen ? " staleSuspect=yes" : ""));
            }
        }

        private void NoteFrame(string kind)
        {
            if (createdSeen && !frameOrderLogged)
            {
                frameOrder.Add(kind);
                if (frameOrder.Count >= 3)
                {
                    frameOrderLogged = true;
                    Emit(TrackA, "FRAME_ORDER", Common() + " firstThreeFrameEventsAfterCreated=" + string.Join(">", frameOrder.ToArray()));
                }
            }
        }

        private void SummariseLocked(string reason)
        {
            string flags = (candA ? "A" : "-") + (candB ? "B" : "-") + (candC ? "C" : "-") + (candD ? "D" : "-") + (candE ? "E" : "-") + (candF ? "F" : "-");
            Emit(TrackA, "GEN_SUMMARY", Common() + " reason=" + reason + " candidates=" + flags + " ticks=" + ticksGen + " preTicks=" + preTicksGen + " postTicks=" + postTicksGen
                + " opened=" + YN(openedSeen) + " preview=" + YN(previewSeen) + " created=" + YN(createdEventSeen) + " lateAttach=" + YN(lateAttach));
            if (createdSeen && !frameOrderLogged && frameOrder.Count > 0)
            {
                frameOrderLogged = true;
                Emit(TrackA, "FRAME_ORDER", Common() + " firstFrameEventsAfterCreated=" + string.Join(">", frameOrder.ToArray()) + " (fewer than three seen)");
            }
        }

        private void Candidate(string id, string extra)
        {
            Emit(TrackA, "CAND_" + id, Common() + " name=" + ScenarioReadyCandidates.Describe(id) + " ticksTotal=" + ticksTotal + " ready=" + readyState() + " " + extra);
        }

        private string Common()
        {
            return "ScenarioGeneration=" + scenarioGeneration;
        }

        private int Read()
        {
            try { return readIsCreated(); }
            catch { return -1; }
        }

        private string Probe()
        {
            try
            {
                string reason = probeBveInfo();
                return string.IsNullOrEmpty(reason) ? null : reason; // null or empty both mean "readable"
            }
            catch (Exception ex)
            {
                return "probe-exc-" + ex.GetType().Name;
            }
        }

        private void Emit(string track, string evt, string detail)
        {
            log(track, evt, detail);
        }

        private static string Tri(int v)
        {
            return v == 1 ? "1" : v == 0 ? "0" : v == -2 ? "never" : "unreadable";
        }

        private static string YN(bool b)
        {
            return b ? "yes" : "no";
        }

        private static void Safe(Action action)
        {
            try { action(); }
            catch { }
        }
    }
}
