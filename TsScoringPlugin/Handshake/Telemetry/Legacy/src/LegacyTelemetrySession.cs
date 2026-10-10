using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE L3 - the AtsEX LEGACY telemetry sender, host independent part.
//
// What it does, per Tick, in the order of the Current sender: STALIST (once at the start of a scenario instance, then every second), META (same
// cadence), then the telemetry line. The line carries ONLY what could be read from the Legacy API in this Tick, expressed in the units and
// sentinels of the telemetry contract, and an AVAIL part that names exactly those data groups. Nothing is guessed, defaulted or carried over:
//
//   * a value that cannot be read is not written, and its token is not in AVAIL;
//   * data that does not exist in the Legacy API (the ground limit look-ahead, the vehicle length derivation, the jump) has no token and no key, ever;
//   * Phase LI1: the handle group (generic texts built from the handle numbers) and the brake pressures (StateStore, kPa) are offered by LegacyInputTelemetry
//     from the same all-or-nothing rule: a group that cannot be built completely in this Tick is neither written nor announced;
//   * a new scenario instance (ScenarioOpened / ScenarioClosed / ScenarioCreated, a different ORIGINAL Scenario object, IsScenarioCreated false) ends the
//     old one at once: new SCENARIO_ID, the station state machine, the acceleration reference and the datagram cadence all start from nothing;
//   * "the same scenario" is decided by the reference identity of the original BVE Scenario object (LegacyScenarioIdentity.Source), NEVER by the wrapper:
//     the host hands out a new wrapper on every access, so a wrapper comparison would start a new instance (and a new SCENARIO_ID) on every Tick. The
//     lifecycle events end the instance on their own, so a reload of identical content is a new instance even if an object were ever reused;
//   * Pause: the host stops calling Tick, so nothing is sent; the heartbeat (STATUS) reports PAUSED from a timer using only the fields below.
//
// Threads: OnTick / OnScenario* / Dispose run on the host's Tick thread (the only thread that touches the Legacy API). ComposeHeartbeat is called
// from a timer thread and reads only the two fields written with Interlocked / volatile below - it never touches a BVE object.
// No exception leaves any public member.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// Where the sender reports its state CHANGES (never per Tick). Implementations must not throw; the session guards every call anyway.
    /// Only numbers, ids and fixed words are passed: no path, no scenario / vehicle / route text.
    /// </summary>
    internal interface ITelemetryDiag
    {
        void Event(string name, string detail);
    }

    internal sealed class LegacyTelemetrySession
    {
        private const double JumpToleranceMs = 300.0;
        private const long StaListIntervalMs = 1000;
        private const long PausedAfterMs = 100;

        private readonly ILegacyApi api;
        private readonly ITelemetrySink sink;
        private readonly Func<long> nowMs;          // monotonic milliseconds
        private readonly Func<long> idSeed;         // any increasing number (UTC ticks in production); only used to derive a scenario id
        private readonly LegacyStationTimeline timeline = new LegacyStationTimeline();

        // written on the Tick thread, read by the heartbeat thread
        private volatile bool scenarioActive;
        private long lastTickMs;
        private volatile bool disposed;

        private readonly ITelemetryDiag diag;

        // per scenario instance (Tick thread only)
        private object scenarioToken;           // LegacyScenarioIdentity.Source of the active instance (compared by reference)
        private string identityKind = "none";
        private string endReason = "first-tick";  // why the previous instance ended (the reason the next one begins)
        private bool identityUnavailable;
        private int epochLines;
        private bool epochUdpLogged;
        private bool epochActive;
        private int scenarioId;
        private int lastScenarioId;
        private int lastTimeMs;
        private double lastSpeedMps;
        private bool haveLastSample;
        private long lastStaListMs;
        private bool staListSent;
        private long lastMetaMs;
        private bool metaSent;
        private bool gradientFirstLogged;       // the gradient unit diagnostic of this instance (see ReportGradient)
        private bool gradientNonZeroLogged;
        private readonly LegacyInputProbe inputProbe;   // Phase LI0 observation (Tick thread only); null when not wired
        private readonly LegacyInputTickCache inputCache;           // Phase LI1: one read of the input surface per Tick for both consumers below; null when no input is wired
        private readonly LegacyInputTelemetry inputTelemetry;       // Phase LI1: the handle group and the pressures of the line; null when no input is wired
        private readonly LegacyScoringProbe scoringProbe;           // Phase SI-0: the scoring-integration observation (Tick thread only, diagnostic log only); null when not wired
        private readonly LegacyOrderRecorder order;                 // Phase SI-0: the order of events / first Tick / heartbeat status / first line (any thread, diagnostic log only); null when not wired
        private const long TickGapNoteMs = 250;                     // a Tick after a longer silence is noted as a resume (the Pause side of the order)
        private bool anyTick;                                       // Tick thread only
        private long prevTickMs;                                    // Tick thread only
        private bool lastCreated;                                   // Tick thread only
        private volatile int heartbeatStatus;                       // 0 nothing noted yet, 1 running, 2 paused, 3 idle = no active instance (heartbeat thread writes, the Tick thread resets)

        // diagnostics (tests, and a future log)
        internal int Epochs { get; private set; }
        internal int LinesSent { get; private set; }
        internal int LinesSkipped { get; private set; }
        internal int Discontinuities { get; private set; }
        internal string LastAvail { get; private set; }

        internal LegacyTelemetrySession(ILegacyApi api, ITelemetrySink sink, Func<long> nowMs, Func<long> idSeed)
            : this(api, sink, nowMs, idSeed, null)
        {
        }

        internal LegacyTelemetrySession(ILegacyApi api, ITelemetrySink sink, Func<long> nowMs, Func<long> idSeed, ITelemetryDiag diag)
            : this(api, sink, nowMs, idSeed, diag, null)
        {
        }

        /// <summary>
        /// input = the read surface of the scoring inputs. Phase LI1: the handle group and the brake pressures of the line come from it (LegacyInputTelemetry);
        /// null = no input wired, none of those groups is ever written or announced. Phase LI0: with a diagnostic as well, the read-only observation
        /// (diagnostic log only) runs on the same reads.
        /// </summary>
        internal LegacyTelemetrySession(ILegacyApi api, ITelemetrySink sink, Func<long> nowMs, Func<long> idSeed, ITelemetryDiag diag, ILegacyInputApi input)
            : this(api, sink, nowMs, idSeed, diag, input, null)
        {
        }

        /// <summary>
        /// scoring = the read surface of the Phase SI-0 observation. With a diagnostic as well, the scoring-integration observation and the order recorder run
        /// (diagnostic log only: nothing of them enters the telemetry line, AVAIL or the heartbeat). null = not wired.
        /// </summary>
        internal LegacyTelemetrySession(ILegacyApi api, ITelemetrySink sink, Func<long> nowMs, Func<long> idSeed, ITelemetryDiag diag, ILegacyInputApi input, ILegacyScoringApi scoring)
        {
            this.api = api;
            this.sink = sink;
            this.nowMs = nowMs;
            this.idSeed = idSeed;
            this.diag = diag;
            lastScenarioId = -1;
            if (input != null)
            {
                inputCache = new LegacyInputTickCache(input);
                inputTelemetry = new LegacyInputTelemetry(inputCache, Log);
                if (diag != null)
                {
                    inputProbe = new LegacyInputProbe(inputCache, Log);
                }
            }

            if (scoring != null && diag != null)
            {
                scoringProbe = new LegacyScoringProbe(scoring, Log);
                order = new LegacyOrderRecorder(nowMs, Log);
            }
        }

        private void Log(string name, string detail)
        {
            try
            {
                if (diag != null)
                {
                    diag.Event(name, detail);
                }
            }
            catch
            {
                // a diagnostic can never affect the telemetry or BVE
            }
        }

        internal bool ScenarioActive { get { return scenarioActive; } }

        internal int ScenarioId { get { return scenarioId; } }

        internal bool IsDisposed { get { return disposed; } }

        // -- lifecycle events (Tick thread) ---------------------------------------------------------------------------------------------------
        internal void OnScenarioOpened(bool isReload)
        {
            NoteEvent("evt-opened", "reload=" + (isReload ? "1" : "0"));
            EndEpoch(isReload ? "scenario-opened-reload" : "scenario-opened");
        }

        internal void OnScenarioClosed()
        {
            NoteEvent("evt-closed", null);
            EndEpoch("scenario-closed");
        }

        internal void OnScenarioCreated()
        {
            NoteEvent("evt-created", null);
            // the new scenario instance is recognised by the next Tick; nothing of the old one may continue until then
            EndEpoch("scenario-created");
        }

        /// <summary>Phase SI-0: the host adapter reports that the extension is set up (called once, from the constructor, on the host's thread).</summary>
        internal void NoteInit(string detail)
        {
            NoteEvent("init", detail);
        }

        /// <summary>Phase SI-0 (order): one host event with the scenario-created flag read at that moment. Reads IsScenarioCreated only, inside the host's own event.</summary>
        private void NoteEvent(string word, string detail)
        {
            if (order == null)
            {
                return;
            }

            string created;
            try { created = api.IsScenarioCreated() ? "1" : "0"; }
            catch { created = "na"; }
            order.Note(word, (string.IsNullOrEmpty(detail) ? string.Empty : detail + " ") + "created=" + created);
        }

        internal void OnDispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            if (order != null) { order.Note("dispose", "epochs=" + Epochs); }
            EndEpoch("dispose");
            Log("TEL_DISPOSE", "epochs=" + Epochs + " lines=" + LinesSent + " skipped=" + LinesSkipped + " discontinuities=" + Discontinuities);
            try { sink.Close(); } catch { }
        }

        /// <summary>Ends the active scenario instance (if any) for the given reason; the reason is what the next instance reports as the reason it began.</summary>
        private void EndEpoch(string reason)
        {
            if (epochActive)
            {
                EndInputProbe();
                Log("TEL_EPOCH_END", "scenarioId=" + scenarioId + " lines=" + epochLines + " reason=" + reason);
                if (order != null) { order.Note("epoch-end", "scenarioId=" + scenarioId + " lines=" + epochLines + " reason=" + reason); }
                heartbeatStatus = 0;     // the heartbeat of the next instance starts from nothing (a repeated EndEpoch while no instance is active changes nothing)
                endReason = reason;      // the FIRST cause is the reason; later events of the same reload (Opened, then Created) do not overwrite it
            }

            ResetEpochState();
        }

        private void EndInputProbe()
        {
            try { if (inputProbe != null) { inputProbe.EndGeneration(); } } catch { }
            try { if (inputTelemetry != null) { inputTelemetry.End(); } } catch { }
            try { if (scoringProbe != null) { scoringProbe.EndGeneration(); } } catch { }
        }

        /// <summary>The observation of the scoring inputs (diagnostic log only). It never changes the telemetry line and can never throw out of here.</summary>
        private void ObserveInput()
        {
            try { if (inputProbe != null) { inputProbe.Observe(); } } catch { }
        }

        private void ResetEpochState()
        {
            scenarioActive = false;
            epochActive = false;
            scenarioToken = null;
            timeline.Reset();
            lastTimeMs = 0;
            lastSpeedMps = 0.0;
            haveLastSample = false;
            staListSent = false;
            metaSent = false;
            lastStaListMs = 0;
            lastMetaMs = 0;
            gradientFirstLogged = false;
            gradientNonZeroLogged = false;
        }

        private void StartEpoch(LegacyScenarioIdentity identity)
        {
            // an instance still active here means the original Scenario object changed without any lifecycle event
            string reason = epochActive ? "identity-changed" : endReason;
            if (epochActive)
            {
                EndInputProbe();
                Log("TEL_EPOCH_END", "scenarioId=" + scenarioId + " lines=" + epochLines + " reason=" + reason);
                if (order != null) { order.Note("epoch-end", "scenarioId=" + scenarioId + " lines=" + epochLines + " reason=" + reason); }
            }

            ResetEpochState();
            heartbeatStatus = 0;
            scenarioToken = identity.Source;
            identityKind = identity.Kind ?? "unknown";
            epochActive = true;
            epochLines = 0;
            epochUdpLogged = false;
            Epochs++;
            int id = (int)(idSeed() % 100000000L);
            if (id < 0)
            {
                id = -id;
            }

            if (id == lastScenarioId)
            {
                id = (id + 1) % 100000000;       // two instances never share an id, so the receiver can tell them apart
            }

            scenarioId = id;
            lastScenarioId = id;
            scenarioActive = true;
            Log("TEL_EPOCH_BEGIN", "n=" + Epochs + " scenarioId=" + id + " reason=" + reason + " identity=" + identityKind);
            if (order != null) { order.Note("epoch-begin", "n=" + Epochs + " scenarioId=" + id + " reason=" + reason); }
            try { if (inputProbe != null) { inputProbe.Begin(id); } } catch { }
            try { if (inputTelemetry != null) { inputTelemetry.Begin(id); } } catch { }
            try { if (scoringProbe != null) { scoringProbe.Begin(id); } } catch { }
        }

        // -- the gradient unit ----------------------------------------------------------------------------------------------------------------
        /// <summary>The one conversion of the gradient: the Legacy API ratio (0.01) to the per mille of the contract (10). false = no valid value (NaN / Infinity before or after).</summary>
        internal static bool GradientRatioToPermille(double ratio, out double permille)
        {
            permille = 0.0;
            if (!TelemetryContract.Finite(ratio))
            {
                return false;
            }

            double converted = ratio * 1000.0;
            if (!TelemetryContract.Finite(converted))
            {
                return false;
            }

            permille = converted;
            return true;
        }

        /// <summary>
        /// Diagnostic for the live check of the unit: per scenario instance, the first valid gradient (raw API value, value after x1000) - and, only if that one
        /// was exactly 0, the first non-zero one after it. At most two lines per instance, never per Tick; numbers and fixed words only.
        /// </summary>
        private void ReportGradient(double raw, double permille)
        {
            if (!gradientFirstLogged)
            {
                gradientFirstLogged = true;
                gradientNonZeroLogged = raw != 0.0;
                Log("TEL_GRADIENT_FIRST", "raw=" + TelemetryContract.D(raw) + " permille=" + TelemetryContract.D(permille) + " reason=api-ratio-x1000");
            }
            else if (!gradientNonZeroLogged && raw != 0.0)
            {
                gradientNonZeroLogged = true;
                Log("TEL_GRADIENT_NONZERO", "raw=" + TelemetryContract.D(raw) + " permille=" + TelemetryContract.D(permille) + " reason=api-ratio-x1000");
            }
        }

        // -- the heartbeat (any thread) -------------------------------------------------------------------------------------------------------
        /// <summary>STATUS:LOADED:RUNNING / PAUSED while a scenario instance is active, else null. Reads no BVE object.</summary>
        internal string ComposeHeartbeat()
        {
            if (disposed)
            {
                return null;
            }

            if (!scenarioActive)
            {
                NoteHeartbeatIdle();
                return null;
            }

            long age = nowMs() - Interlocked.Read(ref lastTickMs);
            bool paused = age > PausedAfterMs;
            NoteHeartbeat(paused, age);
            return paused ? "STATUS:LOADED:PAUSED" : "STATUS:LOADED:RUNNING";
        }

        /// <summary>Phase SI-0 (order): the heartbeat timer is alive but there is no active scenario instance (so nothing is sent), noted once per idle period. Heartbeat thread: reads its own fields only.</summary>
        private void NoteHeartbeatIdle()
        {
            if (order == null || heartbeatStatus == 3)
            {
                return;
            }

            heartbeatStatus = 3;
            order.Note("hb-idle", "scenarioId=" + scenarioId);
        }

        /// <summary>Phase SI-0 (order): the status words of the heartbeat, noted when the status of this scenario instance changes (first running, first paused, running again). Heartbeat thread: reads its own fields only.</summary>
        private void NoteHeartbeat(bool paused, long ageMs)
        {
            if (order == null)
            {
                return;
            }

            int status = paused ? 2 : 1;
            if (heartbeatStatus == status)
            {
                return;
            }

            bool first = heartbeatStatus == 0 || heartbeatStatus == 3;
            heartbeatStatus = status;
            order.Note(paused ? "hb-paused" : (first ? "hb-first-running" : "hb-running-again"), "scenarioId=" + scenarioId + " ageMs=" + ageMs);
        }

        // -- the Tick -------------------------------------------------------------------------------------------------------------------------
        internal void OnTick(TimeSpan elapsed)
        {
            if (disposed)
            {
                return;
            }

            try
            {
                Interlocked.Exchange(ref lastTickMs, nowMs());
                TickCore(elapsed);
            }
            catch
            {
                // BVE must not be affected; the next Tick starts again from what can be read
                LinesSkipped++;
            }
        }

        private void TickCore(TimeSpan elapsed)
        {
            bool created;
            try { created = api.IsScenarioCreated(); }
            catch { created = false; }
            NoteTickOrder(created);
            if (!created)
            {
                EndEpoch("not-created");
                return;
            }

            // the identity of the scenario instance is the ORIGINAL BVE object behind the host's wrapper; the wrapper itself is new on every access and is ignored
            LegacyScenarioIdentity identity;
            bool haveIdentity;
            try { haveIdentity = api.TryScenarioIdentity(out identity); }
            catch { haveIdentity = false; identity = null; }
            if (!haveIdentity || identity == null || identity.Source == null)
            {
                if (!identityUnavailable)
                {
                    identityUnavailable = true;
                    Log("TEL_IDENTITY_UNAVAILABLE", "kind=" + identityKind);
                }

                EndEpoch("scenario-unreadable");
                return;
            }

            identityUnavailable = false;
            if (!epochActive || !ReferenceEquals(identity.Source, scenarioToken))
            {
                StartEpoch(identity);
            }

            // Phase LI1: the input surface is read at most once per Tick; the observation below (diagnostic log only) and the input groups of the line share that read
            try { if (inputCache != null) { inputCache.BeginTick(); } } catch { }

            // Phase LI0: observe the scoring-input candidates (handles, notch layout, pressures) into the diagnostic log; nothing of it enters the line below
            ObserveInput();

            // the core: without time, position and speed there is no telemetry line at all
            int timeMs;
            double location;
            double speedMps;
            if (!api.TryTimeMs(out timeMs) || !api.TryLocation(out location) || !api.TrySpeedMps(out speedMps)
                || !TelemetryContract.Finite(location) || !TelemetryContract.Finite(speedMps))
            {
                LinesSkipped++;
                ObserveScoring(false, 0.0, null);
                return;
            }

            double speedKmh = TelemetryContract.Kmh(speedMps);

            // the simulation time jumped (a jump, a rewind, a hitch): the references of the previous Tick are void
            bool discontinuity = lastTimeMs != 0 && Math.Abs(timeMs - lastTimeMs - elapsed.TotalMilliseconds) > JumpToleranceMs;
            if (discontinuity)
            {
                Discontinuities++;
                timeline.MarkDiscontinuity();
                haveLastSample = false;
            }

            LineBuilder lb = new LineBuilder();
            lb.Token(TelemetryContract.TokTime);
            lb.Token(TelemetryContract.TokSpeed);
            lb.Token(TelemetryContract.TokLoc);
            long now = nowMs();

            // Every optional group below is added ALL OR NOTHING: a value that cannot be read (or an exception) leaves the group out of the line and out
            // of AVAIL, and never affects another group.

            // GRADIENT: the Legacy API value is a ratio; the contract is per mille. The conversion is here and only here; no value is invented.
            try
            {
                double ratio;
                double gradient;
                if (api.TryGradientRatio(location, out ratio) && GradientRatioToPermille(ratio, out gradient))
                {
                    lb.Group(TelemetryContract.TokGrad, "GRADIENT", TelemetryContract.D(gradient));
                    ReportGradient(ratio, gradient);
                }
            }
            catch
            {
            }

            // stations + doors (the next-station state machine needs the door state: without it neither group is announced)
            bool doorsClosed = false;
            bool haveDoors = false;
            string staList = null;
            try
            {
                haveDoors = api.TryDoorsClosed(out doorsClosed);
                IList<LegacyStationRaw> stations = null;
                int stationCount = 0;
                // the stations themselves are read only when the timeline has to be (re)built; every Tick only their number is checked
                bool haveStations = haveDoors && api.TryStationCount(out stationCount) && stationCount >= 0
                    && (!timeline.NeedsBuild(stationCount) || (api.TryStations(out stations) && stations != null && stations.Count == stationCount));
                if (haveStations)
                {
                    StationValues sv = timeline.Step(stations, stationCount, location, speedKmh, timeMs, doorsClosed);
                    lb.Group(TelemetryContract.TokStation,
                        "NEXTLOC", TelemetryContract.D(sv.NextLoc),
                        "NEXTTIME", TelemetryContract.I(sv.NextTime),
                        "ISPASS", TelemetryContract.I(sv.IsPass),
                        "ISTIMING", TelemetryContract.I(sv.IsTiming),
                        "MARGINB", TelemetryContract.D(sv.MarginBack),
                        "MARGINF", TelemetryContract.D(sv.MarginFront),
                        "DOORDIR", TelemetryContract.I(sv.DoorDir),
                        "TERM", TelemetryContract.I(sv.Term),
                        "STATNAME", sv.Name == null ? TelemetryContract.StationName(null) : sv.Name.Replace(",", string.Empty));
                    if (!staListSent || now - lastStaListMs >= StaListIntervalMs)
                    {
                        staList = timeline.ComposeStaList();
                    }
                }
            }
            catch
            {
                staList = null;
            }

            if (haveDoors)
            {
                lb.Group(TelemetryContract.TokDoor, "DOOR", doorsClosed ? "0" : "1");
            }

            // signal limits
            try
            {
                double sig;
                if (api.TrySignalLimitMps(out sig) && !double.IsNaN(sig))
                {
                    lb.Group(TelemetryContract.TokSigLimit, "SIGLIMIT", TelemetryContract.D(TelemetryContract.SignalLimitKmh(sig)));
                }
            }
            catch
            {
            }

            try
            {
                double fwd;
                bool foundSection;
                double sectionLoc;
                if (api.TryForwardSignalLimitMps(out fwd) && !double.IsNaN(fwd) && api.TryNextSectionLocation(location, out foundSection, out sectionLoc))
                {
                    lb.Group(TelemetryContract.TokSigLimitAhead,
                        "FWDSIGLIMIT", TelemetryContract.D(TelemetryContract.SignalLimitKmh(fwd)),
                        "FWDSIGLOC", TelemetryContract.D(foundSection ? sectionLoc : -1.0));
                }
            }
            catch
            {
            }

            // ground limit: the limit in force now. HEAD and TAIL are the same real value; the look-ahead list does not exist in the Legacy API
            double? groundForProbe = null;       // Phase SI-0: the value of this very read, handed to the observation (nothing is read twice)
            try
            {
                double ground;
                if (api.TryGroundLimitMps(out ground) && !double.IsNaN(ground))
                {
                    string kmh = TelemetryContract.D(TelemetryContract.GroundLimitKmh(ground));
                    lb.Group(TelemetryContract.TokMapLimit, "MAPHEAD", kmh, "MAPTAIL", kmh);
                    groundForProbe = ground;
                }
            }
            catch
            {
            }

            // acceleration from two samples of THIS scenario instance; the first sample has no reference and says nothing
            if (haveLastSample)
            {
                double g = 0.0;
                if (timeMs > lastTimeMs && timeMs - lastTimeMs < 1000)
                {
                    double dt = (timeMs - lastTimeMs) / 1000.0;
                    g = ((speedMps - lastSpeedMps) / dt) / TelemetryContract.GravityMps2;
                }

                lb.Group(TelemetryContract.TokCalcG, "CALCG", TelemetryContract.F(g, "F5"));
            }

            try
            {
                LegacyBrakeKind kind;
                if (api.TryBrakeKind(out kind) && kind != LegacyBrakeKind.None)
                {
                    lb.Group(TelemetryContract.TokBrakeType, "BTYPE", kind == LegacyBrakeKind.Smee ? "Smee" : kind == LegacyBrakeKind.Cl ? "Cl" : "Ecb");
                }
            }
            catch
            {
            }

            try
            {
                int notches;
                bool holding;
                if (api.TryBrakeNotches(out notches, out holding) && notches > 0)
                {
                    lb.Group(TelemetryContract.TokBrakeCab, "CAB", TelemetryContract.I(notches) + ":" + (holding ? "1" : "0"));
                }
            }
            catch
            {
            }

            try
            {
                double[] rates;
                double maxPa;
                if (api.TryPressureRates(out rates, out maxPa) && rates != null && rates.Length > 0 && TelemetryContract.Finite(maxPa) && AllFinite(rates))
                {
                    StringBuilder r = new StringBuilder();
                    for (int i = 0; i < rates.Length; i++)
                    {
                        if (i > 0)
                        {
                            r.Append('_');
                        }

                        r.Append(TelemetryContract.D(rates[i]));
                    }

                    lb.Group(TelemetryContract.TokPRates, "PRATES", r.ToString() + ":" + TelemetryContract.F(maxPa / 1000.0, "F1"));
                }
            }
            catch
            {
            }

            // Phase LI1: the handle group and the brake pressures. Each group is offered only when it could be built completely from what the host gave in this
            // Tick (the group, its keys and its AVAIL token appear together or not at all); see LegacyInputTelemetry
            try
            {
                if (inputTelemetry != null)
                {
                    inputTelemetry.Compose(delegate (string token, string[] pairs) { lb.Group(token, pairs); });
                }
            }
            catch
            {
            }

            // META (a datagram of its own, same cadence as STALIST)
            string metaPacket = null;
            try
            {
                LegacyScenarioMeta meta;
                if (api.TryScenarioMeta(out meta) && meta != null)
                {
                    lb.Token(TelemetryContract.TokMeta);
                    if (!metaSent || now - lastMetaMs >= StaListIntervalMs)
                    {
                        metaPacket = "META:" + TelemetryContract.SanitizeMeta(meta.Title) + ":" + TelemetryContract.SanitizeMeta(meta.RouteTitle) + ":"
                            + TelemetryContract.SanitizeMeta(meta.VehicleTitle) + ":" + TelemetryContract.SanitizeMeta(meta.Author) + ":"
                            + TelemetryContract.SanitizeMeta(meta.Comment);
                    }
                }
            }
            catch
            {
                metaPacket = null;
            }
            string avail = TelemetryContract.FormatAvail(lb.Tokens);
            LastAvail = avail;
            string line = "SCENARIO_ID:" + TelemetryContract.I(scenarioId) + "," + avail + ",SPEED:" + TelemetryContract.D(speedKmh) + ",TIME:"
                + TelemetryContract.I(timeMs) + ",LOCATION:" + TelemetryContract.D(location) + lb.Body;

            if (staList != null)
            {
                sink.Send(staList);
                staListSent = true;
                lastStaListMs = now;
            }

            if (metaPacket != null)
            {
                sink.Send(metaPacket);
                metaSent = true;
                lastMetaMs = now;
            }

            sink.Send(line);
            LinesSent++;
            epochLines++;
            if (!epochUdpLogged)
            {
                epochUdpLogged = true;
                Log("TEL_UDP_BEGIN", "scenarioId=" + scenarioId);
                if (order != null) { order.Note("line-first", "scenarioId=" + scenarioId); }
            }

            lastTimeMs = timeMs;
            lastSpeedMps = speedMps;
            haveLastSample = true;

            // Phase SI-0: the scoring-integration observation (diagnostic log only). It runs after the line was sent and changes nothing of it.
            ObserveScoring(true, location, groundForProbe);
        }

        /// <summary>Phase SI-0 (order): the first Tick of the process, a Tick after a long silence (a resume from Pause), and the scenario-created flag as the Tick sees it.</summary>
        private void NoteTickOrder(bool created)
        {
            if (order == null)
            {
                return;
            }

            long now = nowMs();
            if (!anyTick)
            {
                anyTick = true;
                order.Note("tick-first-process", "created=" + (created ? "1" : "0") + " epochs=" + Epochs);
            }
            else if (now - prevTickMs > TickGapNoteMs)
            {
                order.Note("tick-resume", "gapMs=" + (now - prevTickMs) + " created=" + (created ? "1" : "0"));
            }

            prevTickMs = now;
            if (created != lastCreated)
            {
                lastCreated = created;
                order.Note("created-changed", "created=" + (created ? "1" : "0"));
            }
        }

        /// <summary>Phase SI-0: hands the Tick to the scoring observation. Nothing it does can throw out of here or reach the line.</summary>
        private void ObserveScoring(bool coreOk, double location, double? groundMps)
        {
            if (scoringProbe == null)
            {
                return;
            }

            try
            {
                scoringProbe.Observe(coreOk, location, groundMps, LegacyScoringProbe.PresentBpKpa(inputCache));
            }
            catch
            {
            }
        }

        /// <summary>The telemetry line under construction: tokens and the keys that belong to them, added together or not at all.</summary>
        private sealed class LineBuilder
        {
            private readonly List<string> tokens = new List<string>();
            private readonly StringBuilder body = new StringBuilder();

            internal IEnumerable<string> Tokens { get { return tokens; } }

            internal string Body { get { return body.ToString(); } }

            internal void Token(string token)
            {
                tokens.Add(token);
            }

            internal void Group(string token, params string[] keyValuePairs)
            {
                StringBuilder part = new StringBuilder();
                for (int i = 0; i + 1 < keyValuePairs.Length; i += 2)
                {
                    part.Append(',').Append(keyValuePairs[i]).Append(':').Append(keyValuePairs[i + 1]);
                }

                tokens.Add(token);
                body.Append(part.ToString());
            }
        }
        private static bool AllFinite(double[] values)
        {
            for (int i = 0; i < values.Length; i++)
            {
                if (!TelemetryContract.Finite(values[i]))
                {
                    return false;
                }
            }

            return true;
        }
    }
}
