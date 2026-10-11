using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Threading;
using TSScoringPlugin.Telemetry.B1Probe;

// PHASE SI-B1 (B1-probe) offline test fixture. Compiled TOGETHER with probe\B1ProbeCore.cs (Add-Type, one assembly), so it can use the internal core types; its own
// public surface uses primitives only (PowerShell drives it). It contains a small FAKE WORLD (time, location, speed, stations), a FAKE HOST that records every call
// with its thread, a FAKE IO (in memory file, ledger, log, clocks) and a Harness that plays the Extension Tick in the real order: world frame, BeginTick, the telemetry
// session's Tick (simulated), EndTick. No BVE, no AtsEX, no file, no network.
namespace B1Tests
{
    public sealed class Station
    {
        public double Loc;
        public bool Pass;
        public int TimeMs;
    }

    public sealed class FakeWorld
    {
        public int TimeMs = 36000000;
        public double Loc = 1234.5;
        public double SpeedMps = 12.0;
        public bool Created = true;
        public bool DoorsClosed = true;           // BVE opens the doors when Initialize puts the train on a STOPPING station (as the BVE timetable jump does)
        public List<Station> Stations = new List<Station>();

        public FakeWorld()
        {
            Stations.Add(new Station { Loc = 0.0, Pass = false, TimeMs = 35000000 });
            Stations.Add(new Station { Loc = 1000.0, Pass = false, TimeMs = 35100000 });
            Stations.Add(new Station { Loc = 2500.0, Pass = true, TimeMs = 35200000 });
            Stations.Add(new Station { Loc = 4000.0, Pass = false, TimeMs = 35300000 });
        }
    }

    public sealed class FakeHost : IB1ProbeHost
    {
        public readonly FakeWorld World;
        public readonly List<string> Calls = new List<string>();
        public readonly List<int> CallThreads = new List<int>();
        public int SnapshotCalls;
        public int CreatedChecks;
        public bool DisposeBegan;                 // set by the test when Dispose started: any later call is counted
        public int CallsAfterDispose;
        public Action OnInitialize;               // runs INSIDE Initialize* (re-entrancy / dispose-during-call)
        public Action OnSetTime;
        public string ThrowOn = "";               // "initialize" | "settime" | "snapshot"
        public bool NoopSetTime;                  // a SetTime that does nothing
        public double LocError;                   // added to the location Initialize* sets
        public bool LedgerMustContain;            // write-ahead check
        public Func<string, bool> LedgerHas;      // set by the harness
        public string LedgerIdToCheck = "";
        public int LedgerViolations;
        public int Opened, Closed, Created, AtsStarted, DoorOpened, DoorClosed, SignalUpdated, Beacon;
        public int StationCountOverride = -1;
        public bool TimeUnreadable;

        public FakeHost(FakeWorld w)
        {
            World = w;
        }

        private void Touch(string what)
        {
            Calls.Add(what);
            CallThreads.Add(Thread.CurrentThread.ManagedThreadId);
            if (DisposeBegan)
            {
                CallsAfterDispose++;
            }
        }

        private void CheckLedger()
        {
            if (LedgerMustContain && LedgerHas != null && !LedgerHas(LedgerIdToCheck))
            {
                LedgerViolations++;
            }
        }

        bool IB1ProbeHost.IsScenarioCreated()
        {
            CreatedChecks++;
            return World.Created;
        }

        B1Counters IB1ProbeHost.Counters()
        {
            B1Counters c = new B1Counters();
            c.ScenarioOpened = Opened;
            c.ScenarioClosed = Closed;
            c.ScenarioCreated = Created;
            c.NativeStarted = AtsStarted;
            c.NativeDoorOpened = DoorOpened;
            c.NativeDoorClosed = DoorClosed;
            c.NativeSignalUpdated = SignalUpdated;
            c.NativeBeaconPassed = Beacon;
            return c;
        }

        B1Snapshot IB1ProbeHost.Snapshot(int stationIndexOfInterest)
        {
            SnapshotCalls++;
            if (DisposeBegan)
            {
                CallsAfterDispose++;
            }

            if (ThrowOn == "snapshot")
            {
                throw new InvalidOperationException("snapshot failed at C:\\Users\\someone\\secret.txt someone@example.com");
            }

            B1Snapshot s = new B1Snapshot();
            s.ScenarioCreated = World.Created;
            s.ScenarioObjectId = 4242;
            if (!TimeUnreadable)
            {
                s.TimeMs = World.TimeMs;
            }

            s.Location = World.Loc;
            s.SpeedMps = World.SpeedMps;
            s.DoorsClosed = World.DoorsClosed;
            s.Power = 0;
            s.Brake = 3;
            s.Reverser = 1;
            int count = StationCountOverride >= 0 ? StationCountOverride : World.Stations.Count;
            s.StationCount = count;
            int at = -1, prev = -1, next = -1;
            for (int i = 0; i < World.Stations.Count; i++)
            {
                double sl = World.Stations[i].Loc;
                if (i == stationIndexOfInterest)
                {
                    s.ReqStationLocation = sl;
                    s.ReqStationPass = World.Stations[i].Pass;
                }

                if (Math.Abs(sl - World.Loc) <= 0.5 && at < 0) { at = i; }
                if (sl <= World.Loc) { prev = i; }
                if (sl > World.Loc && next < 0)
                {
                    next = i;
                    s.NextStationLocation = sl;
                    s.NextStationPass = World.Stations[i].Pass;
                }
            }

            s.StationAtIndex = at;
            s.PrevStationIndex = prev;
            s.NextStationIndex = next;
            s.SignalLimitMps = 25.0;
            s.ForwardSignalLimitMps = 25.0;
            s.GroundLimitMps = double.PositiveInfinity;
            s.NativeLocation = World.Loc;
            s.NativeSpeedKmh = World.SpeedMps * 3.6;
            s.NativeTimeMs = World.TimeMs;
            s.NativeBcKpa = 0.0;
            s.NativeBpKpa = 490.0;
            s.NativePower = 0;
            s.NativeBrake = 3;
            s.NativeReverser = 1;
            return s;
        }

        void IB1ProbeHost.SetTime(int timeMs)
        {
            Touch("SetTime:" + timeMs.ToString(CultureInfo.InvariantCulture));
            CheckLedger();
            if (OnSetTime != null) { OnSetTime(); }
            if (ThrowOn == "settime") { throw new InvalidOperationException("SetTime failed"); }
            if (!NoopSetTime) { World.TimeMs = timeMs; }
        }

        void IB1ProbeHost.InitializeStation(int stationIndex)
        {
            Touch("InitializeStation:" + stationIndex.ToString(CultureInfo.InvariantCulture));
            CheckLedger();
            if (OnInitialize != null) { OnInitialize(); }
            if (ThrowOn == "initialize") { throw new InvalidOperationException("Initialize failed"); }
            Station st = World.Stations[stationIndex];
            World.Loc = st.Loc + LocError;
            World.SpeedMps = st.Pass ? 10.0 : 0.0;
            World.DoorsClosed = st.Pass;
            World.TimeMs = st.TimeMs;
        }

        void IB1ProbeHost.InitializeLocation(double location, int timeMs)
        {
            Touch("InitializeLocation:" + location.ToString("0.###", CultureInfo.InvariantCulture) + ":" + timeMs.ToString(CultureInfo.InvariantCulture));
            CheckLedger();
            if (OnInitialize != null) { OnInitialize(); }
            if (ThrowOn == "initialize") { throw new InvalidOperationException("Initialize failed"); }
            World.Loc = location + LocError;
            World.SpeedMps = 0.0;
            World.DoorsClosed = true;
            World.TimeMs = timeMs;
        }
    }

    public sealed class FakeIo : IB1ProbeIo
    {
        public string RequestText;                       // null = no file
        public bool FailLedger;
        public bool FailRetire;
        public readonly List<string> Retired = new List<string>();
        public readonly HashSet<string> Ledger = new HashSet<string>();
        public readonly List<string> Lines = new List<string>();
        public int ExistsChecks;
        public DateTime Now = new DateTime(2026, 10, 11, 12, 0, 0, DateTimeKind.Utc);
        public DateTime Start = new DateTime(2026, 10, 11, 11, 50, 0, DateTimeKind.Utc);
        public long Mono;
        public int Pid = 4711;
        private readonly object gate = new object();

        bool IB1ProbeIo.RequestExists()
        {
            ExistsChecks++;
            return RequestText != null;
        }

        string IB1ProbeIo.ReadRequest()
        {
            return RequestText;
        }

        string IB1ProbeIo.RequestSignature()
        {
            return RequestText == null ? null : RequestText.Length.ToString(CultureInfo.InvariantCulture) + ":" + RequestText.GetHashCode().ToString(CultureInfo.InvariantCulture);
        }

        bool IB1ProbeIo.Retire(string word)
        {
            if (FailRetire)
            {
                return false;
            }

            Retired.Add(word);
            RequestText = null;
            return true;
        }

        bool IB1ProbeIo.LedgerContains(string requestId)
        {
            return Ledger.Contains(requestId);
        }

        bool IB1ProbeIo.LedgerAppend(string requestId)
        {
            if (FailLedger)
            {
                return false;
            }

            Ledger.Add(requestId);
            return true;
        }

        void IB1ProbeIo.WriteLine(string line)
        {
            lock (gate)
            {
                Lines.Add(line);
            }
        }

        DateTime IB1ProbeIo.UtcNow { get { return Now; } }

        DateTime IB1ProbeIo.NowLocal { get { return Now.ToLocalTime(); } }

        DateTime IB1ProbeIo.ProcessStartUtc { get { return Start; } }

        int IB1ProbeIo.ProcessId { get { return Pid; } }

        int IB1ProbeIo.ThreadId { get { return Thread.CurrentThread.ManagedThreadId; } }

        long IB1ProbeIo.MonotonicMs { get { return Mono; } }

        string IB1ProbeIo.ProcessMetrics()
        {
            return "procThreads=40 procHandles=900";
        }
    }

    /// <summary>Plays the Extension Tick: world frame, probe BeginTick, the (simulated) telemetry session Tick, probe EndTick.</summary>
    public sealed class Harness
    {
        public readonly FakeWorld World = new FakeWorld();
        public readonly FakeHost Host;
        public readonly FakeIo Io = new FakeIo();
        internal B1ProbeEngine Engine;
        internal readonly B1Config Config = new B1Config();

        // simulated telemetry session state (what B1SessionView exposes)
        public bool SessionActive = true;
        public int SessionScenarioId = 7001;
        public int Discontinuities;
        public int LinesSent;
        public int LinesSkipped;
        // calcg is computed by the session from two consecutive samples: the line of a Tick in which a discontinuity is detected does not carry it (LegacyTelemetrySession)
        public string Avail = "AVAIL:1:bcp+bpp+calcg+door+grad+handle+loc+maplimit+speed+station+time";
        public string LastLine;
        public bool SessionSendsNoLine;
        public bool DropGroupAfterJump;
        public bool DropCalcgInCallTick;          // a fault: calcg lost in the call Tick although the session saw NO discontinuity there
        public bool HoldTimeAfterCall = true;     // real BVE: the Tick right after an API call returns the SAME time / location as the call (it advances from the second Tick)
        public bool BackstepAfterCall;            // a fault: the world time steps back in Tick N+1
        public bool RepeatDiscontinuityNextTick;  // real BVE5 Legacy, SetTime alone: the session also counts a discontinuity in Tick N+1 (AtsEX elapsed > 300 ms)
        public int FrameMs = 16;
        private int lastTime;
        private bool jumped;
        private string lastLineAvail;
        private bool holdNextFrame;
        private bool secondDiscontinuityPending;
        private bool calledThisTick;

        public Harness()
        {
            Host = new FakeHost(World);
            Host.LedgerHas = delegate (string id) { return Io.Ledger.Contains(id); };
            Engine = new B1ProbeEngine(Host, Io, View, Config);
        }

        /// <summary>For the mutation / restart tests: a fresh engine on the SAME io (and ledger), as after a BVE restart.</summary>
        public void RestartEngine()
        {
            Engine = new B1ProbeEngine(Host, Io, View, Config);
        }

        internal B1SessionView View()
        {
            B1SessionView v = new B1SessionView();
            v.ScenarioActive = SessionActive;
            v.ScenarioId = SessionScenarioId;
            v.Discontinuities = Discontinuities;
            v.LinesSent = LinesSent;
            v.LinesSkipped = LinesSkipped;
            v.LastAvail = lastLineAvail ?? Avail;
            v.LastLine = LastLine;
            v.LineSeq = LinesSent;
            return v;
        }

        private void SessionTick()
        {
            if (!SessionActive)
            {
                return;
            }

            if (SessionSendsNoLine)
            {
                LinesSkipped++;
                return;
            }

            bool discontinuityNow = false;
            if (lastTime != 0 && Math.Abs(World.TimeMs - lastTime - FrameMs) > 300)
            {
                Discontinuities++;
                jumped = true;
                discontinuityNow = true;
            }

            if (secondDiscontinuityPending)
            {
                secondDiscontinuityPending = false;
                Discontinuities++;
                discontinuityNow = true;
            }

            if (DropGroupAfterJump && jumped)
            {
                Avail = Avail.Replace("+door", string.Empty);
            }

            string lineAvail = (discontinuityNow || (DropCalcgInCallTick && calledThisTick)) ? Avail.Replace("+calcg", string.Empty) : Avail;
            lastLineAvail = lineAvail;
            LinesSent++;
            LastLine = "SCENARIO_ID:" + SessionScenarioId + "," + lineAvail + ",SPEED:" + (World.SpeedMps * 3.6).ToString("0.###", CultureInfo.InvariantCulture) + ",TIME:" + World.TimeMs
                + ",LOCATION:" + World.Loc.ToString("0.###", CultureInfo.InvariantCulture) + ",NEXTLOC:9999";
            lastTime = World.TimeMs;
        }

        public void Frame()
        {
            if (holdNextFrame)
            {
                holdNextFrame = false;      // the world does not advance in the frame right after an API call (real BVE), the wall clock does
                if (BackstepAfterCall)
                {
                    World.TimeMs -= 100;    // a fault: time goes BACKWARDS in the Tick right after the call
                }
            }
            else
            {
                World.TimeMs += FrameMs;
                World.Loc += World.SpeedMps * FrameMs / 1000.0;
            }

            Io.Mono += FrameMs;
            Io.Now = Io.Now.AddMilliseconds(FrameMs);
        }

        /// <summary>One host frame + the Extension Tick.</summary>
        public void Tick()
        {
            Frame();
            int callsBefore = Host.Calls.Count;
            Engine.BeginTick(FrameMs);
            bool called = Host.Calls.Count > callsBefore;
            calledThisTick = called;
            SessionTick();
            if (called)
            {
                holdNextFrame = HoldTimeAfterCall;
                secondDiscontinuityPending = RepeatDiscontinuityNextTick;       // applies from the NEXT Tick
            }

            Engine.EndTick();
        }

        public void Ticks(int n)
        {
            for (int i = 0; i < n; i++) { Tick(); }
        }

        /// <summary>A fault: the end-of-Tick hook runs twice in one Tick (two samples that belong to the same Tick).</summary>
        public void ExtraEndTick() { Engine.EndTick(); }

        /// <summary>A silence of N ms with no Tick at all (Pause): the host time does not move either.</summary>
        public void Pause(int ms)
        {
            Io.Mono += ms;
            Io.Now = Io.Now.AddMilliseconds(ms);
        }

        public static string Request(string testId, string requestId, string op, int station, string loc, int timeMs, string createdAt, string extra)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("B1PROBE-REQUEST 1\n");
            sb.Append("TestId=").Append(testId).Append('\n');
            sb.Append("RequestId=").Append(requestId).Append('\n');
            sb.Append("Operation=").Append(op).Append('\n');
            if (station >= 0) { sb.Append("StationIndex=").Append(station).Append('\n'); }
            if (!string.IsNullOrEmpty(loc)) { sb.Append("LocationM=").Append(loc).Append('\n'); }
            sb.Append("TimeMs=").Append(timeMs).Append('\n');
            sb.Append("CreatedAtUtc=").Append(createdAt).Append('\n');
            sb.Append("ExecuteOnce=true\n");
            if (!string.IsNullOrEmpty(extra)) { sb.Append(extra); }
            return sb.ToString();
        }

        public string Created(double secondsBeforeNow)
        {
            return Io.Now.AddSeconds(-secondsBeforeNow).ToString(B1RequestParser.TimeFormat, CultureInfo.InvariantCulture);
        }

        public void Place(string testId, string requestId, string op, int station, string loc, int timeMs)
        {
            Io.RequestText = Request(testId, requestId, op, station, loc, timeMs, Created(5.0), null);
        }

        // ---- primitive views for PowerShell -------------------------------------------------------------------------------------------
        public int Accepted { get { return Engine.Status.Accepted; } }
        public int Rejected { get { return Engine.Status.Rejected; } }
        public int Executed { get { return Engine.Status.Executed; } }
        public int Duplicates { get { return Engine.Status.Duplicates; } }
        public int ReentrantTicks { get { return Engine.Status.ReentrantTicks; } }
        public int ApiAfterDispose { get { return Engine.Status.ApiCallsAfterDispose; } }
        public int Exceptions { get { return Engine.Status.Exceptions; } }
        public int HostCalls { get { return Engine.Status.HostCalls; } }
        public bool HasPending { get { return Engine.HasPending; } }
        public bool IsObserving { get { return Engine.IsObserving; } }
        public int Generation { get { return Engine.Generation; } }
        public string Joined { get { lock (Io.Lines) { return string.Join("\n", Io.Lines.ToArray()); } } }

        public string[] Events(string name)
        {
            List<string> r = new List<string>();
            lock (Io.Lines)
            {
                foreach (string l in Io.Lines)
                {
                    if (l.Contains(" " + name + " ")) { r.Add(l); }
                }
            }

            return r.ToArray();
        }

        // ---- hooks that run INSIDE the fake host calls (C# delegates: they run on the Tick thread, which PowerShell script blocks cannot) -------------------------
        public void ArmDisposeDuringInitialize() { Host.OnInitialize = delegate { Host.DisposeBegan = true; Engine.OnDispose(); }; }

        public void ArmReenterDuringInitialize() { bool done = false; Host.OnInitialize = delegate { if (done) { return; } done = true; Engine.BeginTick(FrameMs); Engine.EndTick(); }; }

        public void ArmHoldInitialize(int ms) { Host.OnInitialize = delegate { new ManualResetEvent(false).WaitOne(ms); }; }

        public void ArmLifecycleDuringInitialize() { Host.OnInitialize = delegate { Host.Closed++; }; }

        public void ArmAtsStartedDuringInitialize() { Host.OnInitialize = delegate { Host.AtsStarted++; }; }

        public void ArmSpeedChangeDuringSetTime() { Host.OnSetTime = delegate { World.SpeedMps += 1.0; }; }

        public void DisposeNow() { Host.DisposeBegan = true; Engine.OnDispose(); }

        public void SetProcess(int pid, string nowUtcIso, string startUtcIso)
        {
            Io.Pid = pid;
            Io.Now = DateTime.ParseExact(nowUtcIso, B1RequestParser.TimeFormat, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
            Io.Start = DateTime.ParseExact(startUtcIso, B1RequestParser.TimeFormat, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
        }

        public void SetMaxExecutions(int n) { Config.MaxExecutions = n; }

        public void SetMaxPendingTicks(int n) { Config.MaxPendingTicks = n; }

        public void SetDisposeWaitMs(int n) { Config.DisposeWaitMs = n; }

        public void SetMinTicks(int n) { Config.MinTicksInGeneration = n; }

        public void LogInit() { Engine.LogInit("0.4.1.1", "test"); }
        private ManualResetEvent tickDone;
        public int TickThreadId;

        /// <summary>Runs one Tick on a pool thread (the "host Tick thread" of the test; the calling thread is another one).</summary>
        public void StartTickOnNewThread()
        {
            tickDone = new ManualResetEvent(false);
            ThreadPool.QueueUserWorkItem(delegate
            {
                try { TickThreadId = Thread.CurrentThread.ManagedThreadId; Tick(); }
                finally { tickDone.Set(); }
            });
        }

        public void JoinTick() { if (tickDone != null) { tickDone.WaitOne(); } }

        public void DisposeOnOtherThreadAndJoin()
        {
            ManualResetEvent done = new ManualResetEvent(false);
            ThreadPool.QueueUserWorkItem(delegate
            {
                try { Host.DisposeBegan = true; Engine.OnDispose(); }
                finally { done.Set(); }
            });
            done.WaitOne();
        }
        public static string ParseReason(string text)
        {
            B1Request r;
            string reason, tid, rid;
            if (B1RequestParser.TryParse(text, out r, out reason, out tid, out rid))
            {
                return "OK:" + r.Operation + ":" + r.StationIndex + ":" + (double.IsNaN(r.LocationM) ? "na" : r.LocationM.ToString("0.###", CultureInfo.InvariantCulture)) + ":" + r.TimeMs;
            }

            return reason + "|" + (tid ?? "-") + "|" + (rid ?? "-");
        }

        public static string CleanText(string s)
        {
            return B1ProbeEngine.Clean(s);
        }
    }

    /// <summary>Drives the REAL file io (B1ProbeFileIo) in a throw-away folder: primitives only.</summary>
    public sealed class RealIoDriver
    {
        private readonly B1ProbeFileIo io;
        public readonly string Dir;

        public RealIoDriver(string dir)
        {
            Dir = dir;
            io = new B1ProbeFileIo(dir);
        }

        public string RequestPath { get { return System.IO.Path.Combine(Dir, B1ProbeFileIo.RequestFileName); } }

        public string LogPath { get { return System.IO.Path.Combine(Dir, B1ProbeFileIo.LogFileName); } }

        public string LedgerPath { get { return System.IO.Path.Combine(Dir, B1ProbeFileIo.LedgerFileName); } }

        public bool Exists() { return ((IB1ProbeIo)io).RequestExists(); }

        public string Read() { return ((IB1ProbeIo)io).ReadRequest(); }

        public string Signature() { return ((IB1ProbeIo)io).RequestSignature(); }

        public bool Retire(string word) { return ((IB1ProbeIo)io).Retire(word); }

        public bool LedgerAppend(string id) { return ((IB1ProbeIo)io).LedgerAppend(id); }

        public bool LedgerContains(string id) { return ((IB1ProbeIo)io).LedgerContains(id); }

        public void Write(string line) { ((IB1ProbeIo)io).WriteLine(line); }

        public string StartUtcIso { get { return ((IB1ProbeIo)io).ProcessStartUtc.ToString(B1RequestParser.TimeFormat, CultureInfo.InvariantCulture); } }

        public int Pid { get { return ((IB1ProbeIo)io).ProcessId; } }

        public int Tid { get { return ((IB1ProbeIo)io).ThreadId; } }

        public string Metrics() { return ((IB1ProbeIo)io).ProcessMetrics(); }
    }

    /// <summary>The engine on the REAL file io with the fake world / host: an end-to-end run of request file -> execution -> consumed rename -> ledger -> log file.</summary>
    public sealed class RealHarness
    {
        public readonly FakeWorld World = new FakeWorld();
        public readonly FakeHost Host;
        internal readonly B1ProbeEngine Engine;
        public readonly string Dir;
        public int Discontinuities;
        public int LinesSent;
        private int lastTime;

        public RealHarness(string dir)
        {
            Dir = dir;
            Host = new FakeHost(World);
            B1ProbeFileIo io = new B1ProbeFileIo(dir);
            Host.LedgerHas = delegate (string id) { return io.LedgerContains(id); };
            Engine = new B1ProbeEngine(Host, io, View, new B1Config());
            Engine.LogInit("0.4.1.1", "real-io-test");
        }

        internal B1SessionView View()
        {
            B1SessionView v = new B1SessionView();
            v.ScenarioActive = true;
            v.ScenarioId = 5151;
            v.Discontinuities = Discontinuities;
            v.LinesSent = LinesSent;
            v.LastAvail = "AVAIL:1:door+loc+speed+time";
            v.LastLine = "SCENARIO_ID:5151,AVAIL:1:door+loc+speed+time,SPEED:" + (World.SpeedMps * 3.6).ToString("0.###", CultureInfo.InvariantCulture) + ",TIME:" + World.TimeMs + ",LOCATION:" + World.Loc.ToString("0.###", CultureInfo.InvariantCulture);
            v.LineSeq = LinesSent;
            return v;
        }

        public void Tick()
        {
            World.TimeMs += 16;
            World.Loc += World.SpeedMps * 0.016;
            Engine.BeginTick(16);
            if (lastTime != 0 && Math.Abs(World.TimeMs - lastTime - 16) > 300) { Discontinuities++; }
            LinesSent++;
            lastTime = World.TimeMs;
            Engine.EndTick();
        }

        public void Ticks(int n) { for (int i = 0; i < n; i++) { Tick(); } }

        public int Executed { get { return Engine.Status.Executed; } }

        public int Rejected { get { return Engine.Status.Rejected; } }

        public int Duplicates { get { return Engine.Status.Duplicates; } }

        public void Dispose() { Engine.OnDispose(); }

        public static string RequestNow(string testId, string requestId, string op, int station, string loc, int timeMs, double secondsAgo)
        {
            return Harness.Request(testId, requestId, op, station, loc, timeMs, DateTime.UtcNow.AddSeconds(-secondsAgo).ToString(B1RequestParser.TimeFormat, CultureInfo.InvariantCulture), string.Empty);
        }
    }
}