using BveEx.PluginHost;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Timers;

namespace TsScoringPlugin
{
    public class StationData
    {
        public string Name;
        public double Location;
        public int ArrTime;
        public int DepTime;
        public int RawArrTime;
        public int RawDepTime;
        public int DefaultTime;
        public int DoorDir;
        public bool IsPass;
        public bool IsTerminal;
        public bool HasTimeDef;
        public bool IsScoring;
        public int InterpolatedTime;
        public int StoppageTime;
        public double MarginMin;
        public double MarginMax;
    }

    [Plugin(PluginType.Extension)]
    public class ScoringPlugin : AssemblyPluginBase, IExtension
    {
        private UdpClient udpClient;
        private IPEndPoint endPoint;
        private UdpClient udpReceiver;

        private Timer heartbeatTimer;
        private DateTime lastTickTime = DateTime.MinValue;

        private string lastUdpData = "";
        private string lastStaListPacket = "";
        private object currentScenario = null;
        private int scenarioId = -1;

        private int targetStationIndex = 0;
        private bool hasDoorOpenedAtTarget = false;
        private bool isInitialized = false;

        // Phase U10: set when the stop range of a station could not be read (or is not finite) and the WHOLE station list of this scenario was rejected (RejectStationList). While it is set the station part of the Tick
        // does not run (nothing is built, published or targeted). It ends where the scenario ends (gone / changed): the existing way to a new list.
        private bool stationRangeRejected = false;

        // Phase ST-1A (observation only; nothing of the state machine or of the scoring reads these): the values of the STIDX part of the telemetry line.
        private int stidxArrivalIndex = -1;
        private int stidxArrivalSeq = 0;
        private string stidxListId = TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;
        private int stidxListCount = 0;
        private bool stidxListReady = false;

        private int lastTimeMs = 0;
        private double lastSpeedMps = 0.0;

        private int jumpCounter = 0;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened = false;

        // Pythonから要求された公式ジャンプの完了通知待機状態
        private bool pendingJumpComplete = false;
        private string pendingJumpType = "";
        // Phase ST-3b: the index the jump ADOPTED (the host was called with it), and the location it was checked against; -1 / 0.0 = no pending jump
        private int pendingJumpStationIndex = -1;
        private int pendingJumpRequestedIndex = -1;
        private double pendingJumpRequestedLocation = 0.0;
        // PID-D6: the RequestId of the pending jump (null = a plain command of the normal mode); echoed in the managed JUMP_COMPLETE envelope
        private byte[] pendingJumpRequestId = null;
        // Phase ST-3b: the one-shot StationIndex of the re-initialisation that follows an official jump (-1 = none). Set only by BeginPendingJump (after the host call), consumed by the
        // first re-initialisation, cleared with the pending jump; it is never derived from a position.
        private int requestedTargetIndex = -1;
        private double requestedTargetLocation = 0.0;
        private TSScoringPlugin.DataPlane.CurrentJumpEndpoint jumpEndpoint;
        private int opStopDelayStartMs = -1;
        private int opStopMadeIndex = -1;       // Time Fix B2: the target at which an operational stop was actually MADE (stopped inside the range); -1 = none. Cleared by every (re)selection of the target.
        private bool initialStaListSent = false;
        private DateTime lastStaListSendTime = DateTime.MinValue;
        private DateTime lastHeartbeatTime = DateTime.MinValue;

        private bool isTextsCached = false;
        private string allRevTexts = "切";
        private string allPowTexts = "N";
        private string allBrkTexts = "EB";
        private string allHldTexts = "";
        private int genericPowerNotchCount = 0;
        private int genericHoldingNotchCount = 0;

        // Pythonへ送信するシナリオ情報
        private string metaTitle = "";
        private string metaRoute = "";
        private string metaVehicle = "";
        private string metaAuthor = "";
        private string metaComment = "";
        private string lastMetaPacket = "";
        // BVE5/6ではdepartureTime="t"の内部表現が1ms異なる
        private const long TerminalDepartureTimeBve6Ms =
            int.MaxValue;

        private const long TerminalDepartureTimeBve5Ms =
            (long)int.MaxValue + 1L;

        private List<StationData> stationList = new List<StationData>();

        private string JoinTexts(string[] arr)
        {
            if (arr == null || arr.Length == 0) return "";
            List<string> validTexts = new List<string>();
            foreach (var s in arr) if (!string.IsNullOrWhiteSpace(s)) validTexts.Add(s);
            return string.Join("_", validTexts);
        }

        // PID-D3: the sender's routing (managed DataPlane / normal fixed port), the transport that owns no socket itself, and the per-process diagnostics
        private TSScoringPlugin.DataPlane.CurrentTelemetryRouter router;
        private readonly UdpTransport transport = new UdpTransport();
        private TSScoringPlugin.DataPlane.CurrentTelemetryLogFile diagnostics;

        /// <summary>The datagram transport of the Current sender: the plugin's own UdpClient, detached on Dispose (a send after that fails and is swallowed by the caller).</summary>
        private sealed class UdpTransport : TSScoringPlugin.DataPlane.ITelemetryTransport
        {
            internal volatile UdpClient Client;

            public void Send(byte[] data, IPEndPoint destination)
            {
                UdpClient client = Client;
                if (client == null) throw new ObjectDisposedException("UdpClient");
                client.Send(data, data.Length, destination);
            }
        }

        private static int CurrentProcessId()
        {
            using (var process = System.Diagnostics.Process.GetCurrentProcess())
            {
                return process.Id;
            }
        }

        public ScoringPlugin(PluginBuilder builder) : base(builder)
        {
            int bvePid = 0;
            try { bvePid = CurrentProcessId(); } catch { }

            // Each part below is independent: one failure never prevents another (PID-D0B-1 contract 15.3, DPC-T-001).
            Action<string> log = null;
            try
            {
                diagnostics = TSScoringPlugin.DataPlane.CurrentTelemetryLogFile.CreateProduction(bvePid);
                log = diagnostics.Write;
                log("event=init pid=" + bvePid);
            }
            catch { }

            try
            {
                udpClient = new UdpClient();
                endPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 54321);
                transport.Client = udpClient;
                router = TSScoringPlugin.DataPlane.CurrentTelemetryRouter.CreateProduction(bvePid, transport, endPoint, log);
            }
            catch (Exception ex)
            {
                if (log != null) log("event=sender-init-failed error=" + ex.GetType().Name);
            }

            try
            {
                heartbeatTimer = new Timer(50); // 0.5秒間隔
                heartbeatTimer.Elapsed += HeartbeatTimer_Elapsed;
                heartbeatTimer.Start();
            }
            catch (Exception ex)
            {
                if (log != null) log("event=heartbeat-init-failed error=" + ex.GetType().Name);
            }

            // The jump command receiver (fixed 54322, unchanged by PID-D3). A bind failure (for instance a second BVE) only disables jump commands.
            try
            {
                udpReceiver = new UdpClient(54322);
                udpReceiver.Client.Blocking = false;
            }
            catch (Exception ex)
            {
                if (udpReceiver != null) { try { udpReceiver.Close(); } catch { } udpReceiver = null; }
                if (log != null) log("event=jump-receiver-bind-failed error=" + ex.GetType().Name);
            }

            // PID-D6: the Current Jump endpoint of the per-PID DataPlane (contract 15.3). A failure only disables managed jump commands.
            try
            {
                jumpEndpoint = TSScoringPlugin.DataPlane.CurrentJumpEndpoint.Create(bvePid, new TSScoringPlugin.DataPlane.ReaderEndpointSource(), log);
            }
            catch (Exception ex)
            {
                jumpEndpoint = null;
                if (log != null) log("event=jump-endpoint-failed error=" + ex.GetType().Name);
            }
        }
        private void HeartbeatTimer_Elapsed(object sender, ElapsedEventArgs e)
        {
            try
            {
                // BVEがポーズ中でも、ScenarioCreatedがTrueなら送信！
                if (BveHacker.IsScenarioCreated)
                {
                    bool isPaused = (DateTime.Now - lastTickTime).TotalMilliseconds > 100;
                    string statusSuffix = isPaused ? "PAUSED" : "RUNNING";
                    byte[] hbBytes = Encoding.UTF8.GetBytes($"STATUS:LOADED:{statusSuffix}");
                    var currentRouter = router;
                    if (udpClient != null && currentRouter != null) currentRouter.Begin().Send(TSScoringPlugin.DataPlane.DataPlaneMessageTypes.Heartbeat, hbBytes);
                }
            }
            catch { }
        }
        public override void Dispose()
        {
            try
            {
                if (heartbeatTimer != null)
                {
                    heartbeatTimer.Stop();
                    heartbeatTimer.Dispose();
                    heartbeatTimer = null;
                }
            }
            catch { }
            try { if (router != null) router.Close(); } catch { }
            transport.Client = null;
            try { if (udpClient != null) { udpClient.Close(); udpClient = null; } } catch { }
            try { if (udpReceiver != null) { udpReceiver.Close(); udpReceiver = null; } } catch { }
            try { if (jumpEndpoint != null) { jumpEndpoint.Dispose(); jumpEndpoint = null; } } catch { }
        }

        /// <summary>
        /// The jump commands of this Tick. Normal mode: the plain datagrams of the fixed jump port, exactly as before. Managed mode (and the hold-off): the
        /// fixed port is drained and NOT executed (no plain fallback); only the validated commands of the Current Jump endpoint (Envelope v1 + RequestId)
        /// are returned.
        /// </summary>
        private List<JumpInput> CollectJumpCommands()
        {
            List<JumpInput> commands = new List<JumpInput>();
            bool normal = false;
            try { normal = router != null && router.Mode == TSScoringPlugin.DataPlane.CurrentSenderMode.Normal; } catch { }
            try
            {
                if (udpReceiver != null)
                {
                    while (udpReceiver.Available > 0)
                    {
                        IPEndPoint ep = new IPEndPoint(IPAddress.Any, 0);
                        byte[] rData = udpReceiver.Receive(ref ep);
                        if (normal) commands.Add(new JumpInput(Encoding.UTF8.GetString(rData), null));
                    }
                }
            }
            catch { }
            try
            {
                if (jumpEndpoint != null)
                {
                    List<TSScoringPlugin.DataPlane.CurrentJumpCommand> validated = new List<TSScoringPlugin.DataPlane.CurrentJumpCommand>();
                    jumpEndpoint.Drain(validated);
                    foreach (var c in validated) commands.Add(new JumpInput(c.Text, c.RequestId));
                }
            }
            catch { }
            return commands;
        }

        private sealed class JumpInput
        {
            internal readonly string Text;
            internal readonly byte[] RequestId;
            internal JumpInput(string text, byte[] requestId) { Text = text; RequestId = requestId; }
        }

        // ---- Phase ST-3b: the Current jump transaction. Every DECISION (grammar, version, scope, index, location, the target to re-initialise, the numbers written) is
        // CurrentJumpExecution's, a pure unit held by compiled tests; what follows is the plugin's own state and the one diagnostic channel (one line per request, never per Tick).

        private TSScoringPlugin.DataPlane.CurrentJumpView BuildJumpView()
        {
            TSScoringPlugin.DataPlane.CurrentJumpView view = new TSScoringPlugin.DataPlane.CurrentJumpView();
            view.ScenarioId = scenarioId;
            view.ListReady = stidxListReady;
            view.ListId = stidxListId;
            view.ListCount = stidxListCount;
            view.Locations = StationLocations();
            return view;
        }

        private double[] StationLocations()
        {
            double[] locations = new double[stationList.Count];
            for (int i = 0; i < locations.Length; i++) locations[i] = stationList[i].Location;
            return locations;
        }

        private void JumpDiag(string line)
        {
            try { if (diagnostics != null) diagnostics.Write(line); } catch { }
        }

        private void JumpRefused(byte[] requestId, TSScoringPlugin.DataPlane.CurrentJumpDecision decision, string reason, string detail)
        {
            JumpDiag(TSScoringPlugin.DataPlane.CurrentJumpExecution.RefusedLine(requestId, decision, reason, detail));
        }

        /// <summary>The only place that empties the pending jump: after the completion was sent, or when it will never be sent.</summary>
        private void ClearPendingJump()
        {
            pendingJumpComplete = false;
            pendingJumpRequestId = null;
            pendingJumpType = "";
            pendingJumpStationIndex = -1;
            pendingJumpRequestedIndex = -1;
            pendingJumpRequestedLocation = 0.0;
            requestedTargetIndex = -1;
            requestedTargetLocation = 0.0;
        }

        /// <summary>A jump that was executed but will not be completed (superseded, scenario gone, the list can not carry it, the numbers can not be read or written): one line, no completion.</summary>
        private void AbandonPendingJump(string reason, string detail)
        {
            if (pendingJumpComplete) JumpDiag(TSScoringPlugin.DataPlane.CurrentJumpExecution.AbortedLine(pendingJumpRequestId, pendingJumpType, pendingJumpStationIndex, reason, detail));
            ClearPendingJump();
        }

        /// <summary>The jump was executed with the ADOPTED index: remember it (for the completion and for the one re-initialisation) after the host call, never before.</summary>
        private void BeginPendingJump(string kind, byte[] requestId, TSScoringPlugin.DataPlane.CurrentJumpDecision decision)
        {
            if (pendingJumpComplete) AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RSuperseded, "-");
            pendingJumpComplete = true;
            pendingJumpRequestId = requestId;
            pendingJumpType = kind;
            pendingJumpStationIndex = decision.StationIndex;
            pendingJumpRequestedIndex = decision.RequestedIndex;
            pendingJumpRequestedLocation = decision.Location;
            requestedTargetIndex = decision.StationIndex;
            requestedTargetLocation = decision.Location;
        }

        private void ReinitializeTargetStateAfterJump()
        {
            isInitialized = false;
            hasDoorOpenedAtTarget = false;
            opStopDelayStartMs = -1;
            terminalFrozenDiffSeconds = -999;
            wasTerminalDoorOpened = false;
        }

        /// <summary>The time field of the BVE time manager, found BEFORE the host is called (a jump whose time can not be set is not started); null when any step is missing.</summary>
        private static System.Reflection.FieldInfo FindJumpTimeField(object scenario, System.Reflection.BindingFlags flags, out object rawTimeMgr)
        {
            rawTimeMgr = null;
            var timeMgr = scenario.GetType().GetProperty("TimeManager", flags)?.GetValue(scenario);
            if (timeMgr == null) return null;
            rawTimeMgr = timeMgr.GetType().GetProperty("Src", flags)?.GetValue(timeMgr);
            if (rawTimeMgr == null) return null;
            return rawTimeMgr.GetType().GetField("c", flags);
        }

        /// <summary>The target after an official jump: the ADOPTED StationIndex. No position is searched.</summary>
        private void SelectTargetByRequestedIndex(int requestedStationIndex, double location, bool areDoorsClosed)
        {
            targetStationIndex = requestedStationIndex;
            hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[requestedStationIndex].Location - location) < 50.0;
        }

        /// <summary>The target of every re-initialisation that carries NO StationIndex (first Tick, scenario change, manual time jump, a changed station count): the first station that is not more
        /// than 50 m behind the vehicle. Never reached on the path of an official jump.</summary>
        private void SelectTargetByPosition(double location, bool areDoorsClosed)
        {
            for (int i = 0; i < stationList.Count; i++)
            {
                if (stationList[i].Location >= location - 50.0)
                {
                    targetStationIndex = i;
                    hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[i].Location - location) < 50.0;
                    break;
                }
            }
        }

        /// <summary>Phase U10: the stop range of one host station, read ONCE and strictly. Returns null when both members were read and are finite (sd.MarginMin = |MarginMin|, sd.MarginMax = MarginMax, exactly as before);
        /// otherwise the stage that failed (min-read / max-read / min-invalid / max-invalid) and, for a read, the type of the exception. A range is never replaced by a stand-in value.</summary>
        private static string ReadStationRange(object station, StationData sd, out string exceptionType)
        {
            dynamic st = station;
            exceptionType = "-";
            try { sd.MarginMin = Math.Abs((double)st.MarginMin); } catch (Exception minEx) { exceptionType = minEx.GetType().Name; return "min-read"; }
            try { sd.MarginMax = (double)st.MarginMax; } catch (Exception maxEx) { exceptionType = maxEx.GetType().Name; return "max-read"; }
            if (double.IsNaN(sd.MarginMin) || double.IsInfinity(sd.MarginMin)) return "min-invalid";
            if (double.IsNaN(sd.MarginMax) || double.IsInfinity(sd.MarginMax)) return "max-invalid";
            return null;
        }

        /// <summary>Phase U10: a station's stop range could not be read (or is not finite), so the WHOLE list of this scenario is rejected - never a list without that station (the StationIndex is the position in the host list,
        /// a missing station would shift every later index) and never that station with a stand-in range. Nothing of it stays published (no list text, id, count, ready flag), a pending jump is abandoned like any jump the list
        /// can not carry, the scenario is latched (stationRangeRejected: the inputs are the host's static map data, so every Tick would answer the same; nothing is retried per Tick) and ONE line is written.</summary>
        private void RejectStationList(int stationIndex, string stage, string exceptionType)
        {
            int built = stationList.Count;
            stationRangeRejected = true;
            stationList.Clear();
            lastStaListPacket = "";
            stidxListId = TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;
            stidxListCount = 0;
            stidxListReady = false;
            isInitialized = false;
            AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RListNotReady, "-");
            try { if (diagnostics != null) diagnostics.Write("event=current-station-list-rejected scn=" + scenarioId + " idx=" + stationIndex + " stage=" + stage + " ex=" + exceptionType + " built=" + built + " verdict=rejected retry=scenario-change action=hold"); } catch { }
        }

        private bool firstTickNoted;

        public override void Tick(TimeSpan elapsed)
        {
            lastTickTime = DateTime.Now;
            if (!firstTickNoted)
            {
                firstTickNoted = true;
                try { if (router != null) router.NoteTick(); } catch { }
            }
            if (!BveHacker.IsScenarioCreated)
            {
                lastUdpData = "";
                lastStaListPacket = "";
                isInitialized = false;
                stationRangeRejected = false;
                isTextsCached = false;
                stationList.Clear();
                lastTimeMs = 0;
                initialStaListSent = false;
                lastStaListSendTime = DateTime.MinValue;
                currentScenario = null;
                AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RScenarioChanged, "-");
                return;
            }



            if (udpClient != null)
            {
                if (!object.Equals(currentScenario, BveHacker.Scenario))
                {
                    currentScenario = BveHacker.Scenario;
                    scenarioId = (int)(DateTime.Now.Ticks % 100000000);
                    stidxArrivalIndex = -1;
                    stidxArrivalSeq = 0;
                    stidxListId = TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;
                    stidxListCount = 0;
                    stidxListReady = false;
                    lastUdpData = "";
                    lastStaListPacket = "";
                    isInitialized = false;
                    stationRangeRejected = false;
                    isTextsCached = false;
                    stationList.Clear();
                    lastTimeMs = 0;
                    initialStaListSent = false;
                    lastStaListSendTime = DateTime.MinValue;
                    AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RScenarioChanged, "-");
                }

                // シナリオ情報を取得して送信用変数へ格納する
                try
                {
                    var bindFlagsAllDump = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static;
                    object scenarioInfo = BveHacker.GetType().GetProperty("ScenarioInfo", bindFlagsAllDump)?.GetValue(BveHacker);

                    if (scenarioInfo != null)
                    {
                        var t = scenarioInfo.GetType();
                        metaTitle = t.GetProperty("Title", bindFlagsAllDump)?.GetValue(scenarioInfo)?.ToString() ?? "";
                        metaRoute = t.GetProperty("RouteTitle", bindFlagsAllDump)?.GetValue(scenarioInfo)?.ToString() ?? "";
                        metaVehicle = t.GetProperty("VehicleTitle", bindFlagsAllDump)?.GetValue(scenarioInfo)?.ToString() ?? "";
                        metaAuthor = t.GetProperty("Author", bindFlagsAllDump)?.GetValue(scenarioInfo)?.ToString() ?? "";
                        metaComment = t.GetProperty("Comment", bindFlagsAllDump)?.GetValue(scenarioInfo)?.ToString() ?? "";
                    }
                }
                catch { }
                // =================================================================

                var bindFlagsAll = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.FlattenHierarchy | System.Reflection.BindingFlags.Static;

                if (udpReceiver != null || jumpEndpoint != null)
                {
                    try
                    {
                        foreach (JumpInput jumpInput in CollectJumpCommands())
                        {
                            string msg = jumpInput.Text;
                            byte[] jumpRequestId = jumpInput.RequestId;

                            // Phase ST-3b: the command is judged BEFORE any host call (JumpWire v1 / v2 grammar, scenario, list id and count, StationIndex, location). Only a v2 command that
                            // passes is executed, and it is executed with the ADOPTED index / location; every other command is refused with one diagnostic line, no host call, no completion.
                            TSScoringPlugin.DataPlane.CurrentJumpDecision jumpDecision = TSScoringPlugin.DataPlane.CurrentJumpExecution.Judge(msg, BuildJumpView());
                            if (!jumpDecision.Accepted)
                            {
                                JumpRefused(jumpRequestId, jumpDecision, jumpDecision.Reason, jumpDecision.Detail);
                                continue;
                            }
                            int adoptedIndex = jumpDecision.StationIndex;
                            double adoptedLocation = jumpDecision.Location;
                            int adoptedTimeMs = jumpDecision.TimeMs;

                            // 駅番号によるジャンプを実行し、指定されたBVE時刻へ同期する
                            if (msg.StartsWith("JUMP_STA_TIME:"))
                            {
                                try
                                {
                                    var scenario = BveHacker.Scenario;
                                    var srcProp = scenario == null ? null : scenario.GetType().GetProperty("Src", bindFlagsAll);
                                    object rawScenario = srcProp == null ? null : srcProp.GetValue(scenario);
                                    if (rawScenario == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RScenarioMissing, "-");
                                        continue;
                                    }

                                    // 駅番号を引数に取るジャンプメソッドを取得する
                                    var jumpStaMethod = rawScenario
                                        .GetType()
                                        .GetMethods(bindFlagsAll)
                                        .FirstOrDefault(
                                            m =>
                                                m.GetParameters().Length == 1
                                                && m.GetParameters()[0].ParameterType == typeof(int)
                                                && m.ReturnType == typeof(void)
                                        );
                                    if (jumpStaMethod == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RApiMissing, "-");
                                        continue;
                                    }

                                    object rawTimeMgr;
                                    var timeField = FindJumpTimeField(scenario, bindFlagsAll, out rawTimeMgr);
                                    if (timeField == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RTimeFieldMissing, "-");
                                        continue;
                                    }

                                    jumpStaMethod.Invoke(
                                        rawScenario,
                                        new object[] { adoptedIndex }
                                    );

                                    // BVE時刻を指定された時刻へ同期する
                                    timeField.SetValue(rawTimeMgr, adoptedTimeMs);

                                    // ジャンプ後の対象駅状態を再初期化する（対象駅は採用したStationIndexで決まり、位置では選ばない）
                                    ReinitializeTargetStateAfterJump();
                                    // 駅状態の再初期化後にPythonへ完了通知を送る
                                    BeginPendingJump("STA", jumpRequestId, jumpDecision);
                                }
                                catch (Exception jumpEx)
                                {
                                    JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RJumpException, jumpEx.GetType().Name);
                                }
                            }

                            // 駅ジャンプを利用できない場合は、座標と時刻を直接指定して移動する
                            else if (msg.StartsWith("JUMP_LOC_TIME:"))
                            {
                                try
                                {
                                    var scenario = BveHacker.Scenario;
                                    var srcProp = scenario == null ? null : scenario.GetType().GetProperty("Src", bindFlagsAll);
                                    object rawScenario = srcProp == null ? null : srcProp.GetValue(scenario);
                                    if (rawScenario == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RScenarioMissing, "-");
                                        continue;
                                    }

                                    // 指定座標へのジャンプを実行する
                                    var jumpMethod = rawScenario.GetType().GetMethods(bindFlagsAll)
                                        .FirstOrDefault(m => m.GetParameters().Length == 2 &&
                                                             m.GetParameters()[0].ParameterType == typeof(double) &&
                                                             m.GetParameters()[1].ParameterType == typeof(int) &&
                                                             m.ReturnType == typeof(void));
                                    if (jumpMethod == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RApiMissing, "-");
                                        continue;
                                    }

                                    object rawTimeMgr;
                                    var timeField = FindJumpTimeField(scenario, bindFlagsAll, out rawTimeMgr);
                                    if (timeField == null)
                                    {
                                        JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RTimeFieldMissing, "-");
                                        continue;
                                    }

                                    jumpMethod.Invoke(rawScenario, new object[] { adoptedLocation, 0 });

                                    // BVE時刻を指定された時刻へ同期する
                                    timeField.SetValue(rawTimeMgr, adoptedTimeMs);

                                    // 座標ジャンプも対象駅状態を自分で再初期化し、採用したStationIndexを完了へ載せる
                                    ReinitializeTargetStateAfterJump();
                                    // 駅状態の反映後にPythonへ完了通知を送る
                                    BeginPendingJump("LOC", jumpRequestId, jumpDecision);
                                }
                                catch (Exception jumpEx)
                                {
                                    JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RJumpException, jumpEx.GetType().Name);
                                }
                            }
                        }
                    }
                    catch { }
                }

                double speed = 0.0;
                double location = 0.0;
                int timeMs = 0;
                double finalGradient = 0.0;
                int stidxTarget = -1;      // Phase ST-1A: the index of the station nextStationLoc belongs to (-1 = none)
                double nextStationLoc = -1;
                int nextStationTime = -1;
                int isPass = 0;
                int isTiming = 0;
                double marginBack = 5.0;
                double marginFront = 5.0;
                string revText = "切";
                string powText = "N";
                string brkText = "N";
                int revPos = 0;
                int powNotch = 0;
                int brkNotch = 0;
                int brkMax = 8;
                int handleType = 2;

                dynamic map = null;
                dynamic vehicle = null;
                bool areDoorsClosed = true;

                try { map = BveHacker.Scenario.Map; } catch { }
                try { vehicle = BveHacker.Scenario.Vehicle; } catch { }
                try { timeMs = (int)BveHacker.Scenario.TimeManager.Time.TotalMilliseconds; } catch { }
                try { location = BveHacker.Scenario.VehicleLocation.Location; } catch { }
                try { speed = BveHacker.Scenario.VehicleLocation.Speed * 3.6; } catch { }
                try { if (vehicle != null) areDoorsClosed = vehicle.Doors.AreAllClosed; } catch { }

                if (map == null) return;

                double jumpTimeErrorMs = timeMs - lastTimeMs - elapsed.TotalMilliseconds;

                if (lastTimeMs != 0 && Math.Abs(jumpTimeErrorMs) > 300)
                {
                    isInitialized = false;
                    isTextsCached = false;
                    terminalFrozenDiffSeconds = -999;
                    wasTerminalDoorOpened = false;
                    opStopDelayStartMs = -1;
                    jumpCounter++;
                }

                int cabBrakeNotches = 8;
                bool hasHoldingBrake = false;

                try
                {
                    try
                    {
                        finalGradient = Convert.ToDouble(vehicle.Dynamics.TrackAlignment.Gradient) * 1000.0;
                        if (finalGradient == 0.0) finalGradient = Convert.ToDouble(map.MyTrack.Gradients.GetValueAt(location));
                    }
                    catch { }

                    object cabObj = vehicle.Instruments.Cab;
                    handleType = cabObj.GetType().Name.Contains("OneLever") ? 1 : 2;
                    object handles = cabObj.GetType().GetProperty("Handles", bindFlagsAll)?.GetValue(cabObj);

                    if (handles != null)
                    {
                        object notchInfo = handles.GetType().GetProperty("NotchInfo", bindFlagsAll)?.GetValue(handles);
                        if (notchInfo != null)
                        {
                            var propBrkCnt = notchInfo.GetType().GetProperty("BrakeNotchCount", bindFlagsAll);
                            if (propBrkCnt != null) cabBrakeNotches = Convert.ToInt32(propBrkCnt.GetValue(notchInfo));

                            var propHold = notchInfo.GetType().GetProperty("HasHoldingSpeedBrake", bindFlagsAll);
                            if (propHold != null) hasHoldingBrake = Convert.ToBoolean(propHold.GetValue(notchInfo));
                        }

                        revPos = Convert.ToInt32(handles.GetType().GetProperty("ReverserPosition", bindFlagsAll).GetValue(handles));
                        powNotch = Convert.ToInt32(handles.GetType().GetProperty("PowerNotch", bindFlagsAll).GetValue(handles));
                        brkNotch = Convert.ToInt32(handles.GetType().GetProperty("BrakeNotch", bindFlagsAll).GetValue(handles));
                    }

                    if (!isTextsCached)
                    {
                        try
                        {
                            string[] rTexts = (string[])cabObj.GetType().GetProperty("ReverserTexts", bindFlagsAll).GetValue(cabObj);
                            string[] pTexts = (string[])cabObj.GetType().GetProperty("PowerTexts", bindFlagsAll).GetValue(cabObj);
                            string[] bTexts = (string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlagsAll).GetValue(cabObj);
                            string[] hTexts = null;
                            try { hTexts = (string[])cabObj.GetType().GetProperty("HoldingSpeedTexts", bindFlagsAll).GetValue(cabObj); } catch { }

                            allRevTexts = JoinTexts(rTexts);
                            allPowTexts = JoinTexts(pTexts);
                            allBrkTexts = JoinTexts(bTexts);
                            allHldTexts = JoinTexts(hTexts);
                            genericPowerNotchCount = pTexts != null && pTexts.Length > 0 ? pTexts.Length - 1 : 0;
                            genericHoldingNotchCount = hTexts != null ? hTexts.Length : 0;
                            isTextsCached = true;
                        }
                        catch { }
                    }

                    try { brkMax = ((string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlagsAll).GetValue(cabObj)).Length - 1; } catch { }
                    try { revText = ((string[])cabObj.GetType().GetProperty("ReverserTexts", bindFlagsAll).GetValue(cabObj))[revPos + 1]; } catch { revText = revPos.ToString(); }
                    try { brkText = ((string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlagsAll).GetValue(cabObj))[brkNotch]; } catch { brkText = "B" + brkNotch; }

                    if (powNotch < 0)
                    {
                        try
                        {
                            string[] hTexts = (string[])cabObj.GetType().GetProperty("HoldingSpeedTexts", bindFlagsAll).GetValue(cabObj);
                            try { powText = hTexts[Math.Abs(powNotch)]; } catch { powText = hTexts[Math.Abs(powNotch) - 1]; }
                        }
                        catch { powText = "抑速" + Math.Abs(powNotch); }
                    }
                    else
                    {
                        try { powText = ((string[])cabObj.GetType().GetProperty("PowerTexts", bindFlagsAll).GetValue(cabObj))[powNotch]; }
                        catch { powText = "P" + powNotch; }
                    }
                }
                catch { }

                // Phase U10: a scenario whose station list was rejected has no station part at all (nothing is built, published or targeted) until the scenario changes
                if (!stationRangeRejected)
                try
                {
                    var stations = map.Stations;
                    if (!isInitialized || stations.Count != stationList.Count)
                    {
                        stationList.Clear();
                        for (int i = 0; i < stations.Count; i++)
                        {
                            dynamic st = stations[i];
                            StationData sd = new StationData();
                            sd.Location = st.Location;
                            try { sd.Name = st.Name; } catch { sd.Name = "不明な駅"; }
                            try { sd.IsPass = st.Pass; } catch { sd.IsPass = false; }
                            try { sd.DoorDir = (int)st.DoorSideNumber; } catch { sd.DoorDir = 1; }

                            sd.RawArrTime = -1;
                            sd.RawDepTime = -1;
                            sd.DefaultTime = -1;

                            try { sd.RawArrTime = (int)((TimeSpan)st.ArrivalTime).TotalMilliseconds; }
                            catch { try { sd.RawArrTime = (int)(Convert.ToDouble(st.ArrivalTime) * 1000.0); } catch { } }

                            sd.IsTerminal = false;

                            try
                            {
                                TimeSpan departureTime =
                                    (TimeSpan)st.DepartureTime;

                                long departureTimeMs =
                                    departureTime.Ticks
                                    / TimeSpan.TicksPerMillisecond;

                                bool isTerminalTime =
                                    departureTimeMs == TerminalDepartureTimeBve5Ms
                                    || departureTimeMs == TerminalDepartureTimeBve6Ms;

                                if (isTerminalTime)
                                {
                                    // BVE5/6のdepartureTime="t"
                                    sd.IsTerminal = true;
                                    sd.RawDepTime = -1;
                                }
                                else if (
                                    departureTimeMs >= -1L
                                    && departureTimeMs < TerminalDepartureTimeBve6Ms
                                )
                                {
                                    // -1は未定義、0以上は通常時刻
                                    sd.RawDepTime = (int)departureTimeMs;
                                }
                                else
                                {
                                    // 既知の終着センチネル以外の範囲外値
                                    sd.RawDepTime = -1;
                                }
                            }

                            catch
                            {
                                try
                                {
                                    double departureTimeMs =
                                        Convert.ToDouble(st.DepartureTime)
                                        * 1000.0;

                                    bool isTerminalTime =
                                        departureTimeMs == TerminalDepartureTimeBve5Ms
                                        || departureTimeMs == TerminalDepartureTimeBve6Ms;

                                    if (isTerminalTime)
                                    {
                                        // BVE5/6のdepartureTime="t"
                                        sd.IsTerminal = true;
                                        sd.RawDepTime = -1;
                                    }
                                    else if (
                                        departureTimeMs >= -1.0
                                        && departureTimeMs < TerminalDepartureTimeBve6Ms
                                    )
                                    {
                                        sd.RawDepTime = (int)departureTimeMs;
                                    }
                                    else
                                    {
                                        sd.RawDepTime = -1;
                                    }
                                }
                                catch
                                {
                                }
                            }

                            try { sd.DefaultTime = (int)((TimeSpan)st.DefaultTime).TotalMilliseconds; }
                            catch { try { sd.DefaultTime = (int)(Convert.ToDouble(st.DefaultTime) * 1000.0); } catch { } }

                            if (sd.RawArrTime <= -2000000000) sd.RawArrTime = -1;
                            if (sd.RawDepTime <= -2000000000) sd.RawDepTime = -1;
                            if (sd.DefaultTime <= -2000000000) sd.DefaultTime = -1;

                            sd.ArrTime = sd.RawArrTime;
                            sd.DepTime = sd.RawDepTime;

                            try { sd.StoppageTime = st.StoppageTimeMilliseconds; }
                            catch { try { sd.StoppageTime = (int)((TimeSpan)st.StoppageTime).TotalMilliseconds; } catch { sd.StoppageTime = 15000; } }

                            sd.HasTimeDef = (sd.ArrTime > 0 || sd.DepTime > 0);
                            sd.IsScoring = sd.HasTimeDef;

                            // Phase U10: the stop range is read by ReadStationRange. A station whose range can not be read (or is not finite) rejects the WHOLE list (RejectStationList) and leaves this builder: the range is
                            // never replaced by a stand-in, no station is skipped (the StationIndex is the host position) and nothing of the partial list is kept or published (the catch of this try is the old one).
                            string rangeFailType;
                            string rangeFailStage = ReadStationRange((object)st, sd, out rangeFailType);
                            if (rangeFailStage != null)
                            {
                                RejectStationList(i, rangeFailStage, rangeFailType);
                                throw new InvalidOperationException("station range rejected");
                            }
                            stationList.Add(sd);
                        }

                        // departureTime="t"が複数存在する場合は、最初の駅だけを終着とする
                        bool explicitTerminalFound = false;

                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (stationList[i].IsTerminal)
                            {
                                if (!explicitTerminalFound)
                                {
                                    explicitTerminalFound = true;
                                }
                                else
                                {
                                    stationList[i].IsTerminal = false;
                                }
                            }
                        }

                        // departureTime="t"が存在しない場合は、駅リストの最終駅を終着とする
                        if (!explicitTerminalFound && stationList.Count > 0)
                        {
                            stationList[stationList.Count - 1].IsTerminal = true;
                        }

                        // 駅リスト先頭駅は、従来どおり初期採時対象から外す
                        if (stationList.Count > 0)
                        {
                            stationList[0].IsScoring = false;
                        }

                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (stationList[i].HasTimeDef)
                            {
                                if (
                                    !stationList[i].IsTerminal
                                    && stationList[i].ArrTime > 0
                                    && stationList[i].DepTime <= 0
                                )
                                {
                                    stationList[i].DepTime =
                                        stationList[i].ArrTime
                                        + stationList[i].StoppageTime;
                                }
                                // 到着時刻の補完は、駅の役割(終着駅か)ではなく発車時刻の有効性で決める。
                                // 発車時刻が通常時刻なら終着駅でも補完し、未定義(-1)やterminal sentinelは補完に使わない。
                                else if (
                                    stationList[i].DepTime > 0
                                    && stationList[i].DepTime < TerminalDepartureTimeBve6Ms
                                    && stationList[i].ArrTime <= 0
                                )
                                {
                                    stationList[i].ArrTime =
                                        stationList[i].DepTime
                                        - stationList[i].StoppageTime;

                                    if (stationList[i].ArrTime < 0)
                                    {
                                        stationList[i].ArrTime = 0;
                                    }
                                }
                            }
                        }

                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (!stationList[i].HasTimeDef && stationList[i].DefaultTime > 0)
                            {
                                bool hasPrevAnchor = false;
                                for (int j = i - 1; j >= 0; j--) { if (stationList[j].HasTimeDef) { hasPrevAnchor = true; break; } }
                                bool hasNextAnchor = false;
                                for (int j = i + 1; j < stationList.Count; j++) { if (stationList[j].HasTimeDef) { hasNextAnchor = true; break; } }

                                if (!hasPrevAnchor || !hasNextAnchor)
                                {
                                    stationList[i].ArrTime =
                                        stationList[i].DefaultTime;

                                    if (stationList[i].IsTerminal)
                                    {
                                        // 終着駅では発車時刻を生成しない
                                        stationList[i].DepTime = -1;
                                        stationList[i].InterpolatedTime =
                                            stationList[i].ArrTime;
                                    }
                                    else
                                    {
                                        stationList[i].DepTime =
                                            stationList[i].DefaultTime
                                            + stationList[i].StoppageTime;

                                        stationList[i].InterpolatedTime =
                                            stationList[i].DepTime;
                                    }

                                    stationList[i].HasTimeDef = true;
                                    stationList[i].IsScoring = true;
                                }
                            }
                        }

                        int lastTimingIdx = -1;
                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (stationList[i].HasTimeDef) lastTimingIdx = i;
                            else
                            {
                                int nextTimingIdx = -1;
                                for (int j = i + 1; j < stationList.Count; j++)
                                {
                                    if (stationList[j].HasTimeDef) { nextTimingIdx = j; break; }
                                }
                                if (lastTimingIdx >= 0 && nextTimingIdx >= 0)
                                {
                                    double loc0 = stationList[lastTimingIdx].Location;
                                    double loc1 = stationList[nextTimingIdx].Location;
                                    int time0 = stationList[lastTimingIdx].DepTime;
                                    int time1 = stationList[nextTimingIdx].ArrTime;

                                    int totalStopTime = 0;
                                    for (int k = lastTimingIdx + 1; k < nextTimingIdx; k++)
                                        if (!stationList[k].IsPass) totalStopTime += stationList[k].StoppageTime;

                                    int runTime = (time1 - time0) - totalStopTime;
                                    if (runTime < 0) runTime = time1 - time0;

                                    double locT = stationList[i].Location;
                                    double ratio = (loc1 > loc0) ? (locT - loc0) / (loc1 - loc0) : 0;

                                    int accStopTime = 0;
                                    for (int k = lastTimingIdx + 1; k < i; k++)
                                        if (!stationList[k].IsPass) accStopTime += stationList[k].StoppageTime;

                                    int estArrTime = time0 + (int)(runTime * ratio) + accStopTime;
                                    stationList[i].ArrTime = estArrTime;

                                    if (stationList[i].IsTerminal)
                                    {
                                        stationList[i].DepTime = -1;
                                        stationList[i].InterpolatedTime =
                                            stationList[i].ArrTime;
                                    }
                                    else if (stationList[i].IsPass)
                                    {
                                        stationList[i].DepTime = estArrTime;
                                        stationList[i].InterpolatedTime =
                                            stationList[i].DepTime;
                                    }
                                    else
                                    {
                                        stationList[i].DepTime =
                                            estArrTime
                                            + stationList[i].StoppageTime;

                                        stationList[i].InterpolatedTime =
                                            stationList[i].DepTime;
                                    }
                                }
                            }
                        }

                        // Phase ST-3b: the re-initialisation that follows an official jump targets the ADOPTED StationIndex (one-shot, consumed here whatever the verdict); a list that can no longer
                        // carry it abandons the completion and leaves the target alone - it never falls back to the position search. Every re-initialisation that carries NO index
                        // (first Tick, scenario change, manual time jump, a changed station count) keeps the position search.
                        int requestedStationIndex = -1;
                        bool requestedTargetRefused = false;
                        if (requestedTargetIndex >= 0)
                        {
                            string reinitReason;
                            requestedStationIndex = TSScoringPlugin.DataPlane.CurrentJumpExecution.ResolveRequestedTarget(requestedTargetIndex, requestedTargetLocation, StationLocations(), out reinitReason);
                            requestedTargetIndex = -1;
                            requestedTargetLocation = 0.0;
                            if (requestedStationIndex < 0)
                            {
                                requestedTargetRefused = true;
                                AbandonPendingJump(reinitReason, "-");
                            }
                        }
                        if (requestedStationIndex >= 0) SelectTargetByRequestedIndex(requestedStationIndex, location, areDoorsClosed);
                        else if (!requestedTargetRefused) SelectTargetByPosition(location, areDoorsClosed);
                        opStopMadeIndex = -1;
                        isInitialized = true;
                    }

                    if (!initialStaListSent || (DateTime.Now - lastStaListSendTime).TotalMilliseconds >= 1000)
                    {
                        List<string> staInfoList = new List<string>();
                        foreach (var st in stationList)
                        {
                            string sName = string.IsNullOrEmpty(st.Name) ? "不明な駅" : st.Name.Replace(",", "").Replace("=", "");
                            int sTiming = st.IsScoring ? 1 : 0;

                            staInfoList.Add(
                                $"{sName}={sTiming}={TSScoringPlugin.DataPlane.CurrentJumpExecution.StationLocationText(st.Location)}="
                                + $"{st.ArrTime}={st.DepTime}="
                                + $"{st.DefaultTime}={st.StoppageTime}="
                                + $"{(st.IsPass ? 1 : 0)}="
                                + $"{(st.IsTerminal ? 1 : 0)}"
                            );
                        }

                        if (staInfoList.Count > 0)
                        {
                            lastStaListPacket = "STALIST:" + string.Join(",", staInfoList);
                        }

                        // Phase ST-1A: the identity of the list this STALIST describes (the text that is sent, hashed once a second; an empty list is 00000000)
                        stidxListCount = stationList.Count;
                        stidxListId = staInfoList.Count > 0 ? TSScoringPlugin.Telemetry.StationListIdentity.Compute(string.Join(",", staInfoList)) : TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;
                        stidxListReady = true;

                        string Sanitize(string s) => string.IsNullOrEmpty(s) ? "" : s.Replace(":", "：").Replace(",", "、").Replace("\r", "").Replace("\n", " ");
                        lastMetaPacket = $"META:{Sanitize(metaTitle)}:{Sanitize(metaRoute)}:{Sanitize(metaVehicle)}:{Sanitize(metaAuthor)}:{Sanitize(metaComment)}";

                        lastStaListSendTime = DateTime.Now;
                        initialStaListSent = true;
                    }

                    if (targetStationIndex < stationList.Count)
                    {
                        int stationIndexBeforeAdvance = targetStationIndex;
                        bool stidxDoorOpenedBefore = hasDoorOpenedAtTarget;      // Phase ST-1A: a read-only snapshot for the STIDX part; the state machine below is unchanged
                        var targetSt = stationList[targetStationIndex];
                        nextStationLoc = targetSt.Location;
                        isPass = targetSt.IsPass ? 1 : 0;
                        isTiming = targetSt.IsScoring ? 1 : 0;
                        marginBack = targetSt.MarginMin;
                        marginFront = targetSt.MarginMax;
                        bool isTerminal = targetSt.IsTerminal;

                        if (targetSt.IsPass)
                        {
                            if (location > nextStationLoc && !isTerminal)
                            {
                                targetStationIndex++;
                                hasDoorOpenedAtTarget = false;
                                opStopDelayStartMs = -1;
                            }
                        }
                        else if (targetSt.DoorDir == 0)
                        {
                            double distToStop = nextStationLoc - location;
                            bool isInMargin = (distToStop >= -marginFront && distToStop <= marginBack);
                            // Time Fix B3: BVE supplies exactly 0.0 while the train stands, so there is no noise band: speed == 0.0 (+0.0 and -0.0) is STOPPED, any other speed (either sign) is MOVING.
                            bool isStopped = speed == 0.0;
                            int depTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.InterpolatedTime;

                            if (isStopped && isInMargin) hasDoorOpenedAtTarget = true;
                            if (isStopped && isInMargin) opStopMadeIndex = targetStationIndex;

                            // Time Fix B2/B3: once the stop was made inside the author-defined range, the vehicle MOVING (speed != 0.0, either sign) ends the operational stop at once on that Tick.
                            // The range is not tested again, and neither the departure time nor the 300 ms hold is waited for; a vehicle that never stopped inside the range keeps the target.
                            // "The stop was made" is its own record (opStopMadeIndex): hasDoorOpenedAtTarget can also be PRESET by a target selection (doors open within 50 m) and is no proof of a stop.
                            if (hasDoorOpenedAtTarget && opStopMadeIndex == targetStationIndex && !isTerminal && speed != 0.0)
                            {
                                targetStationIndex++;
                                hasDoorOpenedAtTarget = false;
                                opStopDelayStartMs = -1;
                            }
                            else if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal)
                            {
                                if (opStopDelayStartMs < 0) opStopDelayStartMs = timeMs;
                                else if (timeMs >= opStopDelayStartMs + 300)
                                {
                                    targetStationIndex++;
                                    hasDoorOpenedAtTarget = false;
                                    opStopDelayStartMs = -1;
                                }
                            }
                            else opStopDelayStartMs = -1;
                        }
                        else
                        {
                            if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;
                            if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal)
                            {
                                targetStationIndex++;
                                hasDoorOpenedAtTarget = false;
                                opStopDelayStartMs = -1;
                            }
                        }

                        // 駅遷移したTickでは、更新後の対象駅から駅関連値を導出し直す（旧駅の値をパケットへ残さない）
                        if (targetStationIndex != stationIndexBeforeAdvance && targetStationIndex < stationList.Count)
                        {
                            targetSt = stationList[targetStationIndex];
                            nextStationLoc = targetSt.Location;
                            isPass = targetSt.IsPass ? 1 : 0;
                            isTiming = targetSt.IsScoring ? 1 : 0;
                            marginBack = targetSt.MarginMin;
                            marginFront = targetSt.MarginMax;
                            isTerminal = targetSt.IsTerminal;
                        }

                        // Phase ST-1A: the station the values of this Tick belong to (the new target after a change, the old one when the list ran out), and an arrival
                        // candidate event = the flag went false -> true for THIS target on this Tick (a flag set by the (re)selection of the target is not an event)
                        stidxTarget = targetStationIndex < stationList.Count ? targetStationIndex : stationIndexBeforeAdvance;
                        if (!stidxDoorOpenedBefore && hasDoorOpenedAtTarget && targetStationIndex == stationIndexBeforeAdvance)
                        {
                            stidxArrivalIndex = stationIndexBeforeAdvance;
                            stidxArrivalSeq++;
                        }

                        if (isTerminal)
                        {
                            if (hasDoorOpenedAtTarget)
                            {
                                if (!wasTerminalDoorOpened)
                                {
                                    int arrTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                                    terminalFrozenDiffSeconds = (arrTime - timeMs) / 1000;
                                    wasTerminalDoorOpened = true;
                                }
                                nextStationTime = timeMs + (terminalFrozenDiffSeconds * 1000);
                            }
                            else nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                        }
                        else
                        {
                            if (targetSt.IsPass)
                            {
                                nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                            }
                            else
                            {
                                // 運転停車駅では、到着判定後に発車時刻を採点対象とする
                                bool isReadyToDepart = false;
                                if (targetSt.DoorDir == 0)
                                {
                                    // 運転停車駅：許容範囲に停車してフラグが立った瞬間から発車時刻へ
                                    isReadyToDepart = hasDoorOpenedAtTarget;
                                }
                                else
                                {
                                    // 通常の停車駅：ドアが開いている間は発車時刻へ
                                    isReadyToDepart = (hasDoorOpenedAtTarget && !areDoorsClosed);
                                }

                                if (isReadyToDepart) nextStationTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.InterpolatedTime;
                                else nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                            }
                        }
                    }
                }
                catch { }

                double signalLimit = 1000.0;
                double trainLength = 20.0;
                string mapLimitsStr = "";
                double fwdSigLimit = 1000.0;
                double nextSigLoc = -1.0;
                double manualMapHead = 1000.0;
                double manualMapTail = 1000.0;
                double distToClear = 0.0;
                double currentG = 0.0;
                string bType = "Ecb";
                double bcPressure = 0.0;
                double bpPressure = 0.0;
                double bpInitialPressure = 490.0;
                string pRatesStr = "";
                double maxPressure = 0.0;
                int doorCloseTimeMs = 0;

                object speedLimits = null;
                try { speedLimits = map.GetType().GetProperty("SpeedLimits", bindFlagsAll)?.GetValue(map); } catch { }

                if (speedLimits != null)
                {
                    try
                    {
                        object tlObj = speedLimits.GetType().GetProperty("VehicleLength", bindFlagsAll)?.GetValue(speedLimits);
                        if (tlObj != null) trainLength = Convert.ToDouble(tlObj);
                    }
                    catch { }

                    try
                    {
                        var enumerable = speedLimits as System.Collections.IEnumerable;
                        if (enumerable != null)
                        {
                            List<Tuple<double, double>> validLimits = new List<Tuple<double, double>>();
                            List<string> futureList = new List<string>();

                            foreach (object sl in enumerable)
                            {
                                object locObj = sl.GetType().GetProperty("Location", bindFlagsAll)?.GetValue(sl);
                                object valObj = sl.GetType().GetProperty("Value", bindFlagsAll)?.GetValue(sl);
                                if (locObj != null && valObj != null)
                                {
                                    double sloc = Convert.ToDouble(locObj);
                                    double rawVal = Convert.ToDouble(valObj);
                                    double sval = (double.IsInfinity(rawVal) || rawVal > 999.0 || rawVal <= 0) ? 1000.0 : rawVal * 3.6;
                                    validLimits.Add(new Tuple<double, double>(sloc, sval));
                                    if (sloc > location && sloc <= location + 3000.0) futureList.Add($"{sloc:F1}={sval:F1}");
                                }
                            }
                            mapLimitsStr = string.Join("_", futureList);

                            double tailLoc = location - trainLength;
                            double limitAtTail = 1000.0;
                            double limitAtHead = 1000.0;

                            foreach (var l in validLimits)
                            {
                                if (l.Item1 <= tailLoc) limitAtTail = l.Item2;
                                if (l.Item1 <= location) limitAtHead = l.Item2;
                            }

                            double minOccupied = limitAtTail;
                            foreach (var l in validLimits)
                            {
                                if (l.Item1 > tailLoc && l.Item1 <= location)
                                {
                                    if (l.Item2 < minOccupied) minOccupied = l.Item2;
                                }
                            }

                            if (minOccupied < limitAtHead)
                            {
                                double clearanceLoc = location;
                                for (int i = validLimits.Count - 1; i >= 0; i--)
                                {
                                    if (validLimits[i].Item1 <= location && validLimits[i].Item1 > tailLoc)
                                    {
                                        if (validLimits[i].Item2 == limitAtHead) clearanceLoc = validLimits[i].Item1;
                                        else break;
                                    }
                                }
                                distToClear = clearanceLoc - tailLoc;
                            }

                            manualMapHead = limitAtHead;
                            manualMapTail = minOccupied;
                        }
                    }
                    catch { }
                }

                try
                {
                    object secMgr = BveHacker.Scenario.GetType().GetProperty("SectionManager", bindFlagsAll)?.GetValue(BveHacker.Scenario);
                    if (secMgr != null)
                    {
                        object sigLimObj = secMgr.GetType().GetProperty("CurrentSectionSpeedLimit", bindFlagsAll)?.GetValue(secMgr);
                        if (sigLimObj != null)
                        {
                            double rawSigLimit = Convert.ToDouble(sigLimObj);
                            if (double.IsInfinity(rawSigLimit) || rawSigLimit > 999.0) signalLimit = 1000.0;
                            else signalLimit = rawSigLimit * 3.6;
                        }

                        object fwdLimObj = secMgr.GetType().GetProperty("ForwardSectionSpeedLimit", bindFlagsAll)?.GetValue(secMgr);
                        if (fwdLimObj != null)
                        {
                            double rawFwdLimit = Convert.ToDouble(fwdLimObj);
                            if (double.IsInfinity(rawFwdLimit) || rawFwdLimit > 999.0) fwdSigLimit = 1000.0;
                            else fwdSigLimit = rawFwdLimit * 3.6;
                        }

                        object sections = secMgr.GetType().GetProperty("Sections", bindFlagsAll)?.GetValue(secMgr);
                        if (sections != null)
                        {
                            var secEnum = sections as System.Collections.IEnumerable;
                            if (secEnum != null)
                            {
                                foreach (object sec in secEnum)
                                {
                                    if (sec != null)
                                    {
                                        object locObj = sec.GetType().GetProperty("Location", bindFlagsAll)?.GetValue(sec);
                                        if (locObj != null)
                                        {
                                            double sLoc = Convert.ToDouble(locObj);
                                            if (sLoc > location)
                                            {
                                                nextSigLoc = sLoc;
                                                break;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                catch { }

                try
                {
                    double currentSpeedMps = speed / 3.6;
                    if (lastTimeMs != 0 && timeMs > lastTimeMs && timeMs - lastTimeMs < 1000)
                    {
                        double dt = (timeMs - lastTimeMs) / 1000.0;
                        double accelMps2 = (currentSpeedMps - lastSpeedMps) / dt;
                        currentG = accelMps2 / 9.80665;
                    }
                    lastSpeedMps = currentSpeedMps;

                    if (vehicle != null && vehicle.Instruments != null)
                    {
                        object brkSys = vehicle.Instruments.GetType().GetProperty("BrakeSystem", bindFlagsAll)?.GetValue(vehicle.Instruments);
                        if (brkSys != null)
                        {
                            try
                            {
                                object firstCarBrake = brkSys.GetType().GetProperty("FirstCarBrake", bindFlagsAll)?.GetValue(brkSys);
                                if (firstCarBrake != null)
                                {
                                    object bcValve = firstCarBrake.GetType().GetProperty("BcValve", bindFlagsAll)?.GetValue(firstCarBrake);
                                    if (bcValve != null)
                                    {
                                        object pressureContainer = bcValve.GetType().GetProperty("Pressure", bindFlagsAll)?.GetValue(bcValve);
                                        if (pressureContainer != null)
                                        {
                                            object pVal = pressureContainer.GetType().GetProperty("Value", bindFlagsAll)?.GetValue(pressureContainer)
                                                           ?? pressureContainer.GetType().GetField("Value", bindFlagsAll)?.GetValue(pressureContainer);
                                            if (pVal != null) bcPressure = Convert.ToDouble(pVal) / 1000.0;
                                        }
                                    }
                                }
                            }
                            catch { }

                            try
                            {
                                var brkSysType = brkSys.GetType();
                                object currentController = brkSysType.GetProperty("BrakeController", bindFlagsAll)?.GetValue(brkSys);
                                object ecbInstance = brkSysType.GetProperty("Ecb", bindFlagsAll)?.GetValue(brkSys);
                                object smeeInstance = brkSysType.GetProperty("Smee", bindFlagsAll)?.GetValue(brkSys);
                                object clInstance = brkSysType.GetProperty("Cl", bindFlagsAll)?.GetValue(brkSys);

                                if (currentController != null)
                                {
                                    object ccSrc = currentController.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(currentController);
                                    object ecbSrc = ecbInstance?.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(ecbInstance);
                                    object smeeSrc = smeeInstance?.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(smeeInstance);
                                    object clSrc = clInstance?.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(clInstance);

                                    if (ccSrc != null)
                                    {
                                        if (ccSrc.Equals(ecbSrc)) bType = "Ecb";
                                        else if (ccSrc.Equals(smeeSrc)) bType = "Smee";
                                        else if (ccSrc.Equals(clSrc)) bType = "Cl";
                                    }
                                    else
                                    {
                                        string typeName = currentController.GetType().Name;
                                        if (typeName.Contains("AutomaticAir") || typeName == "Cl") bType = "Cl";
                                        else if (typeName.Contains("Electromagnetic") || typeName == "Smee") bType = "Smee";
                                        else bType = "Ecb";
                                    }

                                    double[] pRates = currentController.GetType().GetProperty("PressureRates", bindFlagsAll)?.GetValue(currentController) as double[];
                                    if (pRates != null) pRatesStr = string.Join("_", pRates);

                                    object maxPObj = currentController.GetType().GetProperty("MaximumPressure", bindFlagsAll)?.GetValue(currentController);
                                    if (maxPObj != null) maxPressure = Convert.ToDouble(maxPObj) / 1000.0;

                                    if (smeeInstance != null)
                                    {
                                        object bpInitObj = smeeInstance.GetType().GetProperty("BpInitialPressure", bindFlagsAll)?.GetValue(smeeInstance);
                                        if (bpInitObj != null) bpInitialPressure = Convert.ToDouble(bpInitObj) / 1000.0;

                                        object bpValve = smeeInstance.GetType().GetProperty("Bp", bindFlagsAll)?.GetValue(smeeInstance);
                                        if (bpValve != null)
                                        {
                                            object pContainer = bpValve.GetType().GetProperty("Pressure", bindFlagsAll)?.GetValue(bpValve);
                                            if (pContainer != null)
                                            {
                                                object pVal = pContainer.GetType().GetProperty("Value", bindFlagsAll)?.GetValue(pContainer)
                                                                ?? pContainer.GetType().GetField("Value", bindFlagsAll)?.GetValue(pContainer);
                                                if (pVal != null) bpPressure = Convert.ToDouble(pVal) / 1000.0;
                                            }
                                        }
                                    }
                                }
                            }
                            catch { }
                        }
                    }
                }
                catch { }

                // BVE内部オブジェクトからドアのCloseTimeを取得する
                try
                {
                    if (vehicle != null)
                    {
                        object rawVehicle = vehicle.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(vehicle);
                        if (rawVehicle != null)
                        {
                            object ccObj = rawVehicle.GetType().GetField("m", bindFlagsAll)?.GetValue(rawVehicle);
                            if (ccObj != null)
                            {
                                object cfArray = ccObj.GetType().GetField("c", bindFlagsAll)?.GetValue(ccObj);
                                if (cfArray is Array arr && arr.Length > 0)
                                {
                                    object firstDoor = arr.GetValue(0); // 1つ目のドア(cf)
                                    if (firstDoor != null)
                                    {
                                        // ドア要素の「b」フィールドからCloseTimeを取得する
                                        object bVal = firstDoor.GetType().GetField("b", bindFlagsAll)?.GetValue(firstDoor);
                                        if (bVal != null)
                                        {
                                            // 型に関わらず確実に整数(4630)に変換
                                            doorCloseTimeMs = Convert.ToInt32(bVal);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                catch { doorCloseTimeMs = 0; } // 失敗時は安全のため 0 を返す
                // =================================================================

                try
                {
                    string currentStationName = "不明な駅";
                    int currentDoorDir = 1;
                    if (stationList.Count > 0 && targetStationIndex < stationList.Count)
                    {
                        var st = stationList[targetStationIndex];
                        currentStationName = !string.IsNullOrEmpty(st.Name) ? st.Name : "不明な駅";
                        currentDoorDir = st.DoorDir;
                    }

                    int holds = hasHoldingBrake ? 1 : 0;

                    bool oneLever = handleType == 1;
                    bool clBrake = string.Equals(bType, "Cl", StringComparison.Ordinal);
                    string defaultRevText = TSScoringPlugin.Telemetry.GenericHandleTextContract.ReverserText(revPos);
                    string defaultPowText = TSScoringPlugin.Telemetry.GenericHandleTextContract.PowerText(powNotch, oneLever, clBrake);
                    string defaultBrkText = clBrake
                        ? TSScoringPlugin.Telemetry.GenericHandleTextContract.ClBrakeText(brkNotch, brkMax, hasHoldingBrake)
                        : hasHoldingBrake
                            ? TSScoringPlugin.Telemetry.GenericHandleTextContract.HoldBrakeBrakeText(brkNotch, brkMax, oneLever)
                            : brkNotch >= brkMax
                                ? TSScoringPlugin.Telemetry.GenericHandleTextContract.TextEmergency
                                : TSScoringPlugin.Telemetry.GenericHandleTextContract.BrakeText(brkNotch, oneLever);
                    string defaultAllRevTexts = TSScoringPlugin.Telemetry.GenericHandleTextContract.AllReverserTexts();
                    string defaultAllPowTexts = TSScoringPlugin.Telemetry.GenericHandleTextContract.AllPowerTexts(genericPowerNotchCount, oneLever, clBrake);
                    string defaultAllBrkTexts = clBrake
                        ? TSScoringPlugin.Telemetry.GenericHandleTextContract.AllClBrakeTexts(hasHoldingBrake)
                        : hasHoldingBrake
                            ? TSScoringPlugin.Telemetry.GenericHandleTextContract.AllHoldBrakeTexts(brkMax, oneLever)
                            : TSScoringPlugin.Telemetry.GenericHandleTextContract.AllBrakeTexts(brkMax, oneLever);
                    string defaultAllHldTexts = handleType == 2
                        ? TSScoringPlugin.Telemetry.GenericHandleTextContract.AllHoldingTexts(genericHoldingNotchCount)
                        : string.Empty;

                    int terminalFlag = 0;

                    if (
                        targetStationIndex >= 0
                        && targetStationIndex < stationList.Count
                        && stationList[targetStationIndex].IsTerminal
                    )
                    {
                        terminalFlag = 1;
                    }

                    string data = $"SCENARIO_ID:{scenarioId},SPEED:{speed},TIME:{timeMs},LOCATION:{location},GRADIENT:{finalGradient},NEXTLOC:{nextStationLoc},NEXTTIME:{nextStationTime},ISPASS:{isPass},ISTIMING:{isTiming},MARGINB:{marginBack},MARGINF:{marginFront},REV:{revText}:{revPos},POW:{powText}:{powNotch},BRK:{brkText}:{brkNotch}:{brkMax},HTYPE:{handleType},ALLTXT:{allRevTexts}:{allPowTexts}:{allBrkTexts}:{allHldTexts},DREV:{defaultRevText}:{revPos},DPOW:{defaultPowText}:{powNotch},DBRK:{defaultBrkText}:{brkNotch}:{brkMax},DALLTXT:{defaultAllRevTexts}:{defaultAllPowTexts}:{defaultAllBrkTexts}:{defaultAllHldTexts},SIGLIMIT:{signalLimit},TRAINLEN:{trainLength},MAPLIMITS:{mapLimitsStr},FWDSIGLIMIT:{fwdSigLimit},FWDSIGLOC:{nextSigLoc},DOOR:{(areDoorsClosed ? 0 : 1)},DOORDIR:{currentDoorDir},TERM:{terminalFlag},MAPHEAD:{manualMapHead},MAPTAIL:{manualMapTail},CLEARDIST:{distToClear},CALCG:{currentG:F5},BTYPE:{bType},JUMP:{jumpCounter},CAB:{cabBrakeNotches}:{holds},BCP:{bcPressure:F1},PRATES:{pRatesStr}:{maxPressure:F1},BPP:{bpPressure:F1}:{bpInitialPressure:F1},STATNAME:{currentStationName},DOORTIME:{doorCloseTimeMs}";
                    // Phase ST-1A: the STIDX part, appended as a part of its own (every part above is unchanged). The Legacy sender writes the same part through the same
                    // shared helper (StationIndexWire). It is written only while the list of this Tick has been described by a STALIST text of this scenario instance.
                    if (isInitialized && stidxListReady && stidxListCount == stationList.Count)
                    {
                        data += ",STIDX:1:" + TSScoringPlugin.Telemetry.StationIndexWire.Fields(stidxTarget, stidxArrivalIndex, stidxArrivalSeq, stidxListCount, stidxListId);
                    }
                    lastUdpData = data;
                }
                catch { }

                lastTimeMs = timeMs;

                try
                {
                    // PID-D3: one routing snapshot per Tick (managed: Envelope v1 to the Directory endpoint, fail closed; normal: the plain fixed-port text as always).
                    // A STALIST / META that could not be sent (hold-off, Directory not ready) stays pending and goes out with the next Tick that can send.
                    var batch = router.Begin();
                    if (!string.IsNullOrEmpty(lastStaListPacket))
                    {
                        byte[] staBytes = Encoding.UTF8.GetBytes(lastStaListPacket);
                        if (batch.Send(TSScoringPlugin.DataPlane.DataPlaneMessageTypes.StationList, staBytes)) lastStaListPacket = "";
                    }
                    if (!string.IsNullOrEmpty(lastMetaPacket))
                    {
                        byte[] metaBytes = Encoding.UTF8.GetBytes(lastMetaPacket);
                        if (batch.Send(TSScoringPlugin.DataPlane.DataPlaneMessageTypes.Metadata, metaBytes)) lastMetaPacket = "";
                    }
                    if (!string.IsNullOrEmpty(lastUdpData))
                    {
                        byte[] bytes = Encoding.UTF8.GetBytes(lastUdpData);
                        batch.Send(TSScoringPlugin.DataPlane.DataPlaneMessageTypes.Telemetry, bytes);
                    }
                    if (pendingJumpComplete && isInitialized)
                    {
                        // Phase ST-3b: the completion carries what the host REALLY reports (position, time) and the index the jump ADOPTED; a value that can not be read or written is
                        // never replaced by -1: the completion is abandoned (Python releases the jump by its own timeout) and nothing is sent.
                        double completedLocation = 0.0;
                        int completedTime = 0;
                        bool completedLocationRead = false;
                        bool completedTimeRead = false;

                        try
                        {
                            completedLocation =
                                BveHacker.Scenario.VehicleLocation.Location;
                            completedLocationRead = true;
                        }
                        catch
                        {
                        }

                        try
                        {
                            completedTime =
                                (int)BveHacker.Scenario
                                    .TimeManager
                                    .Time
                                    .TotalMilliseconds;
                            completedTimeRead = true;
                        }
                        catch
                        {
                        }

                        string completeReason = null;
                        string completeMessage = null;
                        if (!completedLocationRead || !completedTimeRead)
                        {
                            completeReason = TSScoringPlugin.DataPlane.CurrentJumpExecution.RCompletionUnreadable;
                        }
                        else if (!stidxListReady)
                        {
                            completeReason = TSScoringPlugin.DataPlane.CurrentJumpExecution.RListNotReady;
                        }
                        else
                        {
                            completeMessage = TSScoringPlugin.DataPlane.CurrentJumpExecution.FormatCompletion(
                                pendingJumpType, pendingJumpStationIndex, completedLocation, completedTime, jumpCounter, scenarioId, stidxListId, stationList.Count, out completeReason);
                        }

                        if (completeMessage == null)
                        {
                            AbandonPendingJump(
                                completeReason == TSScoringPlugin.DataPlane.CurrentJumpExecution.RCompletionUnreadable || completeReason == TSScoringPlugin.DataPlane.CurrentJumpExecution.RListNotReady
                                    ? completeReason : TSScoringPlugin.DataPlane.CurrentJumpExecution.RCompletionFormat,
                                completeReason);
                        }
                        else
                        {
                            byte[] completeBytes =
                                Encoding.UTF8.GetBytes(completeMessage);

                            // Normal mode (plain command, no RequestId): sent plain as always. Managed mode (PID-D6): a type 5 envelope that echoes the RequestId of
                            // the command. During the hold-off, or while the Telemetry endpoint cannot be resolved, the notice stays pending (and is sent once, when it can be).
                            if (batch.SendJumpComplete(completeBytes, pendingJumpRequestId))
                            {
                                JumpDiag(TSScoringPlugin.DataPlane.CurrentJumpExecution.CompletedLine(
                                    pendingJumpRequestId, pendingJumpType, pendingJumpRequestedIndex, pendingJumpStationIndex, pendingJumpRequestedLocation, completedLocation, completedTime, jumpCounter));
                                ClearPendingJump();
                            }
                        }
                    }
                }
                catch { }
            }
        }
    }
}
