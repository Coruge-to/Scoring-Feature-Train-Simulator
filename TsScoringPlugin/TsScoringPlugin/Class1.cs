using BveEx.PluginHost;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;

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

        private string lastUdpData = "";
        private string lastStaListPacket = "";
        private object currentScenario = null;
        private int scenarioId = -1;

        private int targetStationIndex = 0;
        private bool hasDoorOpenedAtTarget = false;
        private bool isInitialized = false;
        private int lastTimeMs = 0;
        private double lastSpeedMps = 0.0;

        private int jumpCounter = 0;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened = false;

        private int opStopDelayStartMs = -1;
        private bool initialStaListSent = false;
        private DateTime lastStaListSendTime = DateTime.MinValue;

        private bool isTextsCached = false;
        private string allRevTexts = "切";
        private string allPowTexts = "N";
        private string allBrkTexts = "EB";
        private string allHldTexts = "";

        private List<StationData> stationList = new List<StationData>();

        private string JoinTexts(string[] arr)
        {
            if (arr == null || arr.Length == 0) return "";
            List<string> validTexts = new List<string>();
            foreach (var s in arr) if (!string.IsNullOrWhiteSpace(s)) validTexts.Add(s);
            return string.Join("_", validTexts);
        }

        public ScoringPlugin(PluginBuilder builder) : base(builder)
        {
            try
            {
                udpClient = new UdpClient();
                endPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 54321);
                udpReceiver = new UdpClient(54322);
                udpReceiver.Client.Blocking = false;
            }
            catch { }
        }

        public override void Dispose()
        {
            if (udpClient != null) { udpClient.Close(); udpClient = null; }
            if (udpReceiver != null) { udpReceiver.Close(); udpReceiver = null; }
        }

        public override void Tick(TimeSpan elapsed)
        {
            if (!BveHacker.IsScenarioCreated)
            {
                lastUdpData = "";
                lastStaListPacket = "";
                isInitialized = false;
                isTextsCached = false;
                stationList.Clear();
                lastTimeMs = 0;
                initialStaListSent = false;
                lastStaListSendTime = DateTime.MinValue;
                currentScenario = null;
                return;
            }

            if (udpClient != null)
            {
                if (!object.Equals(currentScenario, BveHacker.Scenario))
                {
                    currentScenario = BveHacker.Scenario;
                    scenarioId = (int)(DateTime.Now.Ticks % 100000000);
                    lastUdpData = "";
                    lastStaListPacket = "";
                    isInitialized = false;
                    isTextsCached = false;
                    stationList.Clear();
                    lastTimeMs = 0;
                    initialStaListSent = false;
                    lastStaListSendTime = DateTime.MinValue;
                }

                var bindFlagsAll = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.FlattenHierarchy | System.Reflection.BindingFlags.Static;

                if (udpReceiver != null)
                {
                    try
                    {
                        while (udpReceiver.Available > 0)
                        {
                            IPEndPoint ep = new IPEndPoint(IPAddress.Any, 0);
                            byte[] rData = udpReceiver.Receive(ref ep);
                            string msg = Encoding.UTF8.GetString(rData);

                            // =================================================================
                            // ★ 究極の解決策：「駅ジャンプ」＋「時間ハック」の融合コマンド
                            // 座標ジャンプ(早送り)をしないため、マップ音声が絶対に暴発しない！
                            // =================================================================
                            if (msg.StartsWith("JUMP_STA_TIME:"))
                            {
                                string[] parts = msg.Split(':');
                                if (parts.Length >= 3 && int.TryParse(parts[1], out int sIdx) && int.TryParse(parts[2], out int rTimeMs))
                                {
                                    System.IO.File.AppendAllText(System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "debug.log"),
                                        $"[{DateTime.Now:HH:mm:ss.fff}] [C#] コマンド受信: STA={sIdx}, TIME={rTimeMs}\n");
                                    try
                                    {
                                        var scenario = BveHacker.Scenario;
                                        if (scenario == null) continue;
                                        var srcProp = scenario.GetType().GetProperty("Src", bindFlagsAll);
                                        if (srcProp != null)
                                        {
                                            object rawScenario = srcProp.GetValue(scenario);
                                            if (rawScenario != null)
                                            {
                                                // 1. 公式のクリーンな駅ジャンプを実行（音も環境も綺麗にリセット）
                                                var jumpStaMethod = rawScenario.GetType().GetMethods(bindFlagsAll)
                                                    .FirstOrDefault(m => m.GetParameters().Length == 1 &&
                                                                         m.GetParameters()[0].ParameterType == typeof(int) &&
                                                                         m.ReturnType == typeof(void));
                                                if (jumpStaMethod != null)
                                                {
                                                    jumpStaMethod.Invoke(rawScenario, new object[] { sIdx });
                                                }

                                                // 2. 時計の針（TimeManager）だけを強引に過去(セーブデータ)に合わせる
                                                var timeMgr = scenario.GetType().GetProperty("TimeManager", bindFlagsAll)?.GetValue(scenario);
                                                if (timeMgr != null)
                                                {
                                                    var rawTimeMgr = timeMgr.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(timeMgr);
                                                    if (rawTimeMgr != null)
                                                    {
                                                        var timeField = rawTimeMgr.GetType().GetField("c", bindFlagsAll);
                                                        if (timeField != null && rTimeMs >= 0) timeField.SetValue(rawTimeMgr, rTimeMs);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    catch { }
                                }
                            }

                            // =================================================================
                            // ★ 追加：理不尽ドア待ち回避用ハイブリッド（従来の座標ワープ復活）
                            // =================================================================
                            else if (msg.StartsWith("JUMP_LOC_TIME:"))
                            {
                                string[] parts = msg.Split(':');
                                if (parts.Length >= 3 && double.TryParse(parts[1], out double rLoc) && int.TryParse(parts[2], out int rTimeMs))
                                {
                                    try
                                    {
                                        var scenario = BveHacker.Scenario;
                                        if (scenario == null) continue;
                                        var srcProp = scenario.GetType().GetProperty("Src", bindFlagsAll);
                                        if (srcProp != null)
                                        {
                                            object rawScenario = srcProp.GetValue(scenario);
                                            if (rawScenario != null)
                                            {
                                                // 1. 従来の「座標ジャンプ（早送り）」を実行
                                                var jumpMethod = rawScenario.GetType().GetMethods(bindFlagsAll)
                                                    .FirstOrDefault(m => m.GetParameters().Length == 2 &&
                                                                         m.GetParameters()[0].ParameterType == typeof(double) &&
                                                                         m.GetParameters()[1].ParameterType == typeof(int) &&
                                                                         m.ReturnType == typeof(void));
                                                if (jumpMethod != null)
                                                {
                                                    jumpMethod.Invoke(rawScenario, new object[] { rLoc, 0 });
                                                }

                                                // 2. 時計の針を合わせる
                                                var timeMgr = scenario.GetType().GetProperty("TimeManager", bindFlagsAll)?.GetValue(scenario);
                                                if (timeMgr != null)
                                                {
                                                    var rawTimeMgr = timeMgr.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(timeMgr);
                                                    if (rawTimeMgr != null)
                                                    {
                                                        var timeField = rawTimeMgr.GetType().GetField("c", bindFlagsAll);
                                                        if (timeField != null && rTimeMs >= 0) timeField.SetValue(rawTimeMgr, rTimeMs);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    catch { }
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

                try
                {
                    speed = BveHacker.Scenario.VehicleLocation.Speed * 3.6;
                    location = BveHacker.Scenario.VehicleLocation.Location;
                    timeMs = (int)BveHacker.Scenario.TimeManager.Time.TotalMilliseconds;
                    map = BveHacker.Scenario.Map;
                    vehicle = BveHacker.Scenario.Vehicle;
                    try { areDoorsClosed = vehicle.Doors.AreAllClosed; } catch { }
                }
                catch { }

                // =================================================================
                // ★ 方針②：ドア（cc）とパラメータ（d3）の数値をすべて暴く！
                // =================================================================
                if (!isInitialized && vehicle != null)
                {
                    try
                    {
                        string logPath = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "debug_doors_deep.log");
                        if (!System.IO.File.Exists(logPath))
                        {
                            StringBuilder sb = new StringBuilder();
                            sb.AppendLine($"\n[{DateTime.Now:HH:mm:ss.fff}] ===== DEEP DOOR DUMP =====");

                            object rawVehicle = vehicle.GetType().GetProperty("Src", bindFlagsAll)?.GetValue(vehicle);
                            if (rawVehicle != null)
                            {
                                // パラメータ群（d3 = h）をダンプ
                                object d3Obj = rawVehicle.GetType().GetField("h", bindFlagsAll)?.GetValue(rawVehicle);
                                if (d3Obj != null)
                                {
                                    sb.AppendLine("\n--- Parameters (h / d3) ---");
                                    foreach (var f in d3Obj.GetType().GetFields(bindFlagsAll))
                                    {
                                        object val = f.GetValue(d3Obj);
                                        if (val is double || val is float || val is int || val is long)
                                            sb.AppendLine($"{f.Name} = {val}");
                                    }
                                }

                                // ドア群（cc = m）をダンプ
                                object ccObj = rawVehicle.GetType().GetField("m", bindFlagsAll)?.GetValue(rawVehicle);
                                if (ccObj != null)
                                {
                                    sb.AppendLine("\n--- Doors (m / cc) ---");
                                    object cfArray = ccObj.GetType().GetField("c", bindFlagsAll)?.GetValue(ccObj); // cf[]
                                    if (cfArray is Array arr && arr.Length > 0)
                                    {
                                        object firstDoor = arr.GetValue(0); // 1つ目のドアオブジェクトを取得
                                        if (firstDoor != null)
                                        {
                                            sb.AppendLine($"First Door Type: {firstDoor.GetType().Name}");
                                            foreach (var f in firstDoor.GetType().GetFields(bindFlagsAll))
                                            {
                                                object val = f.GetValue(firstDoor);
                                                if (val is double || val is float || val is int || val is long)
                                                    sb.AppendLine($"DoorField {f.Name} = {val}");
                                            }
                                        }
                                    }
                                }
                            }
                            System.IO.File.WriteAllText(logPath, sb.ToString());
                        }
                    }
                    catch { }
                }
                // =================================================================

                if (map == null) return;

                if (lastTimeMs != 0 && Math.Abs(timeMs - lastTimeMs - elapsed.TotalMilliseconds) > 300)
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

                            try { sd.RawDepTime = (int)((TimeSpan)st.DepartureTime).TotalMilliseconds; }
                            catch { try { sd.RawDepTime = (int)(Convert.ToDouble(st.DepartureTime) * 1000.0); } catch { } }

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

                            try { sd.MarginMin = Math.Abs((double)st.MarginMin); } catch { sd.MarginMin = 5.0; }
                            try { sd.MarginMax = (double)st.MarginMax; } catch { sd.MarginMax = 5.0; }
                            stationList.Add(sd);
                        }

                        if (stationList.Count > 0) stationList[0].IsScoring = false;

                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (stationList[i].HasTimeDef)
                            {
                                if (stationList[i].ArrTime > 0 && stationList[i].DepTime <= 0) stationList[i].DepTime = stationList[i].ArrTime + stationList[i].StoppageTime;
                                else if (stationList[i].DepTime > 0 && stationList[i].ArrTime <= 0)
                                {
                                    stationList[i].ArrTime = stationList[i].DepTime - stationList[i].StoppageTime;
                                    if (stationList[i].ArrTime < 0) stationList[i].ArrTime = 0;
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
                                    stationList[i].ArrTime = stationList[i].DefaultTime;
                                    stationList[i].DepTime = stationList[i].DefaultTime + stationList[i].StoppageTime;
                                    stationList[i].HasTimeDef = true;
                                    stationList[i].IsScoring = true;
                                    stationList[i].InterpolatedTime = stationList[i].DepTime;
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
                                    if (stationList[i].IsPass) stationList[i].DepTime = estArrTime;
                                    else stationList[i].DepTime = estArrTime + stationList[i].StoppageTime;
                                    stationList[i].InterpolatedTime = stationList[i].DepTime;
                                }
                            }
                        }

                        for (int i = 0; i < stationList.Count; i++)
                        {
                            if (stationList[i].Location >= location - 50.0)
                            {
                                targetStationIndex = i;
                                hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[i].Location - location) < 50.0;
                                break;
                            }
                        }
                        isInitialized = true;
                    }

                    if (!initialStaListSent || (DateTime.Now - lastStaListSendTime).TotalMilliseconds >= 1000)
                    {
                        List<string> staInfoList = new List<string>();
                        foreach (var st in stationList)
                        {
                            string sName = string.IsNullOrEmpty(st.Name) ? "不明な駅" : st.Name.Replace(",", "").Replace("=", "");
                            int sTiming = st.IsScoring ? 1 : 0;
                            staInfoList.Add($"{sName}={sTiming}={st.Location}={st.RawArrTime}={st.RawDepTime}={st.DefaultTime}={st.StoppageTime}={(st.IsPass ? 1 : 0)}");
                        }
                        if (staInfoList.Count > 0)
                        {
                            lastStaListPacket = "STALIST:" + string.Join(",", staInfoList);
                        }
                        lastStaListSendTime = DateTime.Now;
                        initialStaListSent = true;
                    }

                    if (targetStationIndex < stationList.Count)
                    {
                        var targetSt = stationList[targetStationIndex];
                        nextStationLoc = targetSt.Location;
                        isPass = targetSt.IsPass ? 1 : 0;
                        isTiming = targetSt.IsScoring ? 1 : 0;
                        marginBack = targetSt.MarginMin;
                        marginFront = targetSt.MarginMax;
                        bool isTerminal = (targetStationIndex == stationList.Count - 1);

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
                            bool isStopped = Math.Abs(speed) < 0.1;
                            int depTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.InterpolatedTime;

                            if (isStopped && isInMargin) hasDoorOpenedAtTarget = true;

                            if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal)
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
                            if (targetSt.IsPass) nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                            else if (targetSt.DoorDir == 0) nextStationTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.InterpolatedTime;
                            else
                            {
                                if (hasDoorOpenedAtTarget && !areDoorsClosed) nextStationTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.InterpolatedTime;
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

                // =================================================================
                // ★ 追加：ドアの動作時間（CloseTime）を暗号化階層から取得する
                // =================================================================
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
                                        // ダンプで突き止めた「b」フィールドを取得
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
                    string data = $"SCENARIO_ID:{scenarioId},SPEED:{speed},TIME:{timeMs},LOCATION:{location},GRADIENT:{finalGradient},NEXTLOC:{nextStationLoc},NEXTTIME:{nextStationTime},ISPASS:{isPass},ISTIMING:{isTiming},MARGINB:{marginBack},MARGINF:{marginFront},REV:{revText}:{revPos},POW:{powText}:{powNotch},BRK:{brkText}:{brkNotch}:{brkMax},HTYPE:{handleType},ALLTXT:{allRevTexts}:{allPowTexts}:{allBrkTexts}:{allHldTexts},SIGLIMIT:{signalLimit},TRAINLEN:{trainLength},MAPLIMITS:{mapLimitsStr},FWDSIGLIMIT:{fwdSigLimit},FWDSIGLOC:{nextSigLoc},DOOR:{(areDoorsClosed ? 0 : 1)},DOORDIR:{currentDoorDir},TERM:{(targetStationIndex == stationList.Count - 1 ? 1 : 0)},MAPHEAD:{manualMapHead},MAPTAIL:{manualMapTail},CLEARDIST:{distToClear},CALCG:{currentG:F5},BTYPE:{bType},JUMP:{jumpCounter},CAB:{cabBrakeNotches}:{holds},BCP:{bcPressure:F1},PRATES:{pRatesStr}:{maxPressure:F1},BPP:{bpPressure:F1}:{bpInitialPressure:F1},STATNAME:{currentStationName},DOORTIME:{doorCloseTimeMs}"; 
                    lastUdpData = data;
                }
                catch { }

                lastTimeMs = timeMs;

                try
                {
                    if (!string.IsNullOrEmpty(lastStaListPacket))
                    {
                        byte[] staBytes = Encoding.UTF8.GetBytes(lastStaListPacket);
                        udpClient.Send(staBytes, staBytes.Length, endPoint);
                        lastStaListPacket = "";
                    }
                    if (!string.IsNullOrEmpty(lastUdpData))
                    {
                        byte[] bytes = Encoding.UTF8.GetBytes(lastUdpData);
                        udpClient.Send(bytes, bytes.Length, endPoint);
                    }
                }
                catch { }
            }
        }
    }
}