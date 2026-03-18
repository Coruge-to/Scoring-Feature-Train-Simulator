using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace TsScoringPlugin
{
    public class StationData
    {
        public double Location;
        public int ArrTime;
        public int DepTime;
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

        private int targetStationIndex = 0;
        private bool hasDoorOpenedAtTarget = false;
        private bool isInitialized = false;
        private int lastTimeMs = 0;
        private double lastSpeedMps = 0.0;

        private int jumpCounter = 0;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened = false;

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
            foreach (var s in arr)
            {
                if (!string.IsNullOrWhiteSpace(s)) validTexts.Add(s);
            }
            return string.Join("_", validTexts);
        }

        public ScoringPlugin(PluginBuilder builder) : base(builder)
        {
            try
            {
                udpClient = new UdpClient();
                endPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 54321);
            }
            catch { }
        }

        public override void Tick(TimeSpan elapsed)
        {
            if (BveHacker.IsScenarioCreated && udpClient != null)
            {
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

                if (map == null) return;

                if (lastTimeMs != 0 && Math.Abs(timeMs - lastTimeMs - elapsed.TotalMilliseconds) > 1000)
                {
                    isInitialized = false;
                    isTextsCached = false;
                    terminalFrozenDiffSeconds = -999;
                    wasTerminalDoorOpened = false;
                    jumpCounter++;
                }

                int cabBrakeNotches = 8;
                bool hasHoldingBrake = false;
                var bindFlags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.FlattenHierarchy;

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
                    object handles = cabObj.GetType().GetProperty("Handles", bindFlags)?.GetValue(cabObj);

                    if (handles != null)
                    {
                        object notchInfo = handles.GetType().GetProperty("NotchInfo", bindFlags)?.GetValue(handles);
                        if (notchInfo != null)
                        {
                            var propBrkCnt = notchInfo.GetType().GetProperty("BrakeNotchCount", bindFlags);
                            if (propBrkCnt != null) cabBrakeNotches = Convert.ToInt32(propBrkCnt.GetValue(notchInfo));

                            var propHold = notchInfo.GetType().GetProperty("HasHoldingSpeedBrake", bindFlags);
                            if (propHold != null) hasHoldingBrake = Convert.ToBoolean(propHold.GetValue(notchInfo));
                        }

                        revPos = Convert.ToInt32(handles.GetType().GetProperty("ReverserPosition", bindFlags).GetValue(handles));
                        powNotch = Convert.ToInt32(handles.GetType().GetProperty("PowerNotch", bindFlags).GetValue(handles));
                        brkNotch = Convert.ToInt32(handles.GetType().GetProperty("BrakeNotch", bindFlags).GetValue(handles));
                    }

                    if (!isTextsCached)
                    {
                        try
                        {
                            string[] rTexts = (string[])cabObj.GetType().GetProperty("ReverserTexts", bindFlags).GetValue(cabObj);
                            string[] pTexts = (string[])cabObj.GetType().GetProperty("PowerTexts", bindFlags).GetValue(cabObj);
                            string[] bTexts = (string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlags).GetValue(cabObj);
                            string[] hTexts = null;
                            try { hTexts = (string[])cabObj.GetType().GetProperty("HoldingSpeedTexts", bindFlags).GetValue(cabObj); } catch { }

                            allRevTexts = JoinTexts(rTexts);
                            allPowTexts = JoinTexts(pTexts);
                            allBrkTexts = JoinTexts(bTexts);
                            allHldTexts = JoinTexts(hTexts);
                            isTextsCached = true;
                        }
                        catch { }
                    }

                    try { brkMax = ((string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlags).GetValue(cabObj)).Length - 1; } catch { }
                    try { revText = ((string[])cabObj.GetType().GetProperty("ReverserTexts", bindFlags).GetValue(cabObj))[revPos + 1]; } catch { revText = revPos.ToString(); }
                    try { brkText = ((string[])cabObj.GetType().GetProperty("BrakeTexts", bindFlags).GetValue(cabObj))[brkNotch]; } catch { brkText = "B" + brkNotch; }

                    if (powNotch < 0)
                    {
                        try
                        {
                            string[] hTexts = (string[])cabObj.GetType().GetProperty("HoldingSpeedTexts", bindFlags).GetValue(cabObj);
                            try { powText = hTexts[Math.Abs(powNotch)]; } catch { powText = hTexts[Math.Abs(powNotch) - 1]; }
                        }
                        catch { powText = "抑速" + Math.Abs(powNotch); }
                    }
                    else
                    {
                        try { powText = ((string[])cabObj.GetType().GetProperty("PowerTexts", bindFlags).GetValue(cabObj))[powNotch]; }
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
                            try { sd.IsPass = st.Pass; } catch { sd.IsPass = false; }

                            sd.ArrTime = -1; sd.DepTime = -1;
                            try { sd.ArrTime = (int)((TimeSpan)st.ArrivalTime).TotalMilliseconds; } catch { try { sd.ArrTime = (int)st.ArrivalTime; } catch { } }
                            try { sd.DepTime = (int)((TimeSpan)st.DepartureTime).TotalMilliseconds; } catch { try { sd.DepTime = (int)st.DepartureTime; } catch { } }

                            sd.HasTimeDef = (sd.ArrTime > 0 || sd.DepTime > 0);
                            sd.IsScoring = sd.HasTimeDef;
                            sd.InterpolatedTime = sd.DepTime > 0 ? sd.DepTime : sd.ArrTime;
                            try { sd.StoppageTime = st.StoppageTimeMilliseconds; }
                            catch { try { sd.StoppageTime = (int)((TimeSpan)st.StoppageTime).TotalMilliseconds; } catch { sd.StoppageTime = 15000; } }
                            try { sd.MarginMin = Math.Abs((double)st.MarginMin); } catch { sd.MarginMin = 5.0; }
                            try { sd.MarginMax = (double)st.MarginMax; } catch { sd.MarginMax = 5.0; }
                            stationList.Add(sd);
                        }

                        if (stationList.Count > 0) stationList[0].IsScoring = false;

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
                                    int time0 = stationList[lastTimingIdx].DepTime > 0 ? stationList[lastTimingIdx].DepTime : stationList[lastTimingIdx].ArrTime;
                                    int time1 = stationList[nextTimingIdx].ArrTime > 0 ? stationList[nextTimingIdx].ArrTime : stationList[nextTimingIdx].DepTime;

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

                                    if (stationList[i].IsPass) stationList[i].InterpolatedTime = estArrTime;
                                    else
                                    {
                                        stationList[i].ArrTime = estArrTime;
                                        stationList[i].DepTime = estArrTime + stationList[i].StoppageTime;
                                        stationList[i].InterpolatedTime = stationList[i].DepTime;
                                    }
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

                    if (targetStationIndex < stationList.Count)
                    {
                        var targetSt = stationList[targetStationIndex];
                        nextStationLoc = targetSt.Location;
                        isPass = targetSt.IsPass ? 1 : 0;
                        isTiming = targetSt.IsScoring ? 1 : 0;
                        marginBack = targetSt.MarginMin;
                        marginFront = targetSt.MarginMax;
                        bool isTerminal = (targetStationIndex == stationList.Count - 1);

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
                            if (hasDoorOpenedAtTarget && !areDoorsClosed) nextStationTime = targetSt.DepTime > 0 ? targetSt.DepTime : targetSt.ArrTime;
                            else
                            {
                                if (targetSt.IsPass) nextStationTime = targetSt.InterpolatedTime;
                                else nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;
                            }
                        }

                        if (targetSt.IsPass)
                        {
                            if (location > nextStationLoc && !isTerminal)
                            {
                                targetStationIndex++;
                                hasDoorOpenedAtTarget = false;
                            }
                        }
                        else
                        {
                            if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;
                            if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal)
                            {
                                targetStationIndex++;
                                hasDoorOpenedAtTarget = false;
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
                double bpInitialPressure = 490.0; // ★ BpInitialPressureの初期値(kPa)

                string pRatesStr = "";
                double maxPressure = 0.0;

                object speedLimits = null;
                try { speedLimits = map.GetType().GetProperty("SpeedLimits", bindFlags)?.GetValue(map); } catch { }

                if (speedLimits != null)
                {
                    try
                    {
                        object tlObj = speedLimits.GetType().GetProperty("VehicleLength", bindFlags)?.GetValue(speedLimits);
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
                                object locObj = sl.GetType().GetProperty("Location", bindFlags)?.GetValue(sl);
                                object valObj = sl.GetType().GetProperty("Value", bindFlags)?.GetValue(sl);
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
                                        if (validLimits[i].Item2 == limitAtHead)
                                        {
                                            clearanceLoc = validLimits[i].Item1;
                                        }
                                        else
                                        {
                                            break;
                                        }
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
                    object secMgr = BveHacker.Scenario.GetType().GetProperty("SectionManager", bindFlags)?.GetValue(BveHacker.Scenario);
                    if (secMgr != null)
                    {
                        object sigLimObj = secMgr.GetType().GetProperty("CurrentSectionSpeedLimit", bindFlags)?.GetValue(secMgr);
                        if (sigLimObj != null)
                        {
                            double rawSigLimit = Convert.ToDouble(sigLimObj);
                            if (double.IsInfinity(rawSigLimit) || rawSigLimit > 999.0) signalLimit = 1000.0;
                            else signalLimit = rawSigLimit * 3.6;
                        }

                        object fwdLimObj = secMgr.GetType().GetProperty("ForwardSectionSpeedLimit", bindFlags)?.GetValue(secMgr);
                        if (fwdLimObj != null)
                        {
                            double rawFwdLimit = Convert.ToDouble(fwdLimObj);
                            if (double.IsInfinity(rawFwdLimit) || rawFwdLimit > 999.0) fwdSigLimit = 1000.0;
                            else fwdSigLimit = rawFwdLimit * 3.6;
                        }

                        object sections = secMgr.GetType().GetProperty("Sections", bindFlags)?.GetValue(secMgr);
                        if (sections != null)
                        {
                            var secEnum = sections as System.Collections.IEnumerable;
                            if (secEnum != null)
                            {
                                foreach (object sec in secEnum)
                                {
                                    if (sec != null)
                                    {
                                        object locObj = sec.GetType().GetProperty("Location", bindFlags)?.GetValue(sec);
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
                        object brkSys = vehicle.Instruments.GetType().GetProperty("BrakeSystem", bindFlags)?.GetValue(vehicle.Instruments);
                        if (brkSys != null)
                        {
                            try
                            {
                                object firstCarBrake = brkSys.GetType().GetProperty("FirstCarBrake", bindFlags)?.GetValue(brkSys);
                                if (firstCarBrake != null)
                                {
                                    object bcValve = firstCarBrake.GetType().GetProperty("BcValve", bindFlags)?.GetValue(firstCarBrake);
                                    if (bcValve != null)
                                    {
                                        object pressureContainer = bcValve.GetType().GetProperty("Pressure", bindFlags)?.GetValue(bcValve);
                                        if (pressureContainer != null)
                                        {
                                            object pVal = pressureContainer.GetType().GetProperty("Value", bindFlags)?.GetValue(pressureContainer)
                                                       ?? pressureContainer.GetType().GetField("Value", bindFlags)?.GetValue(pressureContainer);
                                            if (pVal != null) bcPressure = Convert.ToDouble(pVal) / 1000.0;
                                        }
                                    }
                                }
                            }
                            catch { }

                            try
                            {
                                var brkSysType = brkSys.GetType();
                                object currentController = brkSysType.GetProperty("BrakeController", bindFlags)?.GetValue(brkSys);
                                object ecbInstance = brkSysType.GetProperty("Ecb", bindFlags)?.GetValue(brkSys);
                                object smeeInstance = brkSysType.GetProperty("Smee", bindFlags)?.GetValue(brkSys);
                                object clInstance = brkSysType.GetProperty("Cl", bindFlags)?.GetValue(brkSys);

                                if (currentController != null)
                                {
                                    object ccSrc = currentController.GetType().GetProperty("Src", bindFlags)?.GetValue(currentController);
                                    object ecbSrc = ecbInstance?.GetType().GetProperty("Src", bindFlags)?.GetValue(ecbInstance);
                                    object smeeSrc = smeeInstance?.GetType().GetProperty("Src", bindFlags)?.GetValue(smeeInstance);
                                    object clSrc = clInstance?.GetType().GetProperty("Src", bindFlags)?.GetValue(clInstance);

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

                                    double[] pRates = currentController.GetType().GetProperty("PressureRates", bindFlags)?.GetValue(currentController) as double[];
                                    if (pRates != null) pRatesStr = string.Join("_", pRates);

                                    object maxPObj = currentController.GetType().GetProperty("MaximumPressure", bindFlags)?.GetValue(currentController);
                                    if (maxPObj != null) maxPressure = Convert.ToDouble(maxPObj) / 1000.0;

                                    if (smeeInstance != null)
                                    {
                                        // ★ BpInitialPressure の取得
                                        object bpInitObj = smeeInstance.GetType().GetProperty("BpInitialPressure", bindFlags)?.GetValue(smeeInstance);
                                        if (bpInitObj != null) bpInitialPressure = Convert.ToDouble(bpInitObj) / 1000.0;

                                        object bpValve = smeeInstance.GetType().GetProperty("Bp", bindFlags)?.GetValue(smeeInstance);
                                        if (bpValve != null)
                                        {
                                            object pContainer = bpValve.GetType().GetProperty("Pressure", bindFlags)?.GetValue(bpValve);
                                            if (pContainer != null)
                                            {
                                                object pVal = pContainer.GetType().GetProperty("Value", bindFlags)?.GetValue(pContainer)
                                                           ?? pContainer.GetType().GetField("Value", bindFlags)?.GetValue(pContainer);
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
                lastTimeMs = timeMs;

                try
                {
                    int holds = hasHoldingBrake ? 1 : 0;
                    // ★ BPP送信データに bpInitialPressure を追加
                    string data = $"SPEED:{speed},TIME:{timeMs},LOCATION:{location},GRADIENT:{finalGradient},NEXTLOC:{nextStationLoc},NEXTTIME:{nextStationTime},ISPASS:{isPass},ISTIMING:{isTiming},MARGINB:{marginBack},MARGINF:{marginFront},REV:{revText}:{revPos},POW:{powText}:{powNotch},BRK:{brkText}:{brkNotch}:{brkMax},HTYPE:{handleType},ALLTXT:{allRevTexts}:{allPowTexts}:{allBrkTexts}:{allHldTexts},SIGLIMIT:{signalLimit},TRAINLEN:{trainLength},MAPLIMITS:{mapLimitsStr},FWDSIGLIMIT:{fwdSigLimit},FWDSIGLOC:{nextSigLoc},DOOR:{(areDoorsClosed ? 0 : 1)},TERM:{(targetStationIndex == stationList.Count - 1 ? 1 : 0)},MAPHEAD:{manualMapHead},MAPTAIL:{manualMapTail},CLEARDIST:{distToClear},CALCG:{currentG:F5},BTYPE:{bType},JUMP:{jumpCounter},CAB:{cabBrakeNotches}:{holds},BCP:{bcPressure:F1},PRATES:{pRatesStr}:{maxPressure:F1},BPP:{bpPressure:F1}:{bpInitialPressure:F1}";
                    byte[] bytes = Encoding.UTF8.GetBytes(data);
                    udpClient.Send(bytes, bytes.Length, endPoint);
                }
                catch { }
            }
        }

        public override void Dispose()
        {
            if (udpClient != null)
            {
                udpClient.Close();
                udpClient = null;
            }
        }
    }
}