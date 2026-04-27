using BveEx.PluginHost;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace TsScoringPlugin
{
    [Plugin(PluginType.Extension)]
    public class AtsLoggerPlugin : AssemblyPluginBase, IExtension
    {
        private string realtimeLogPath = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "ATS_Realtime.log");

        private int[] prevSound = new int[1024];
        private int[] prevPanel = new int[1024];

        private int prevPhysBrake = -1;
        private int prevAtsBrake = -1;

        private double lastLocation = -1.0;
        private List<dynamic> beaconList = new List<dynamic>();
        private bool isBeaconsLoaded = false;

        public AtsLoggerPlugin(PluginBuilder builder) : base(builder) { }

        public override void Dispose() { }

        public override void Tick(TimeSpan elapsed)
        {
            if (!BveHacker.IsScenarioCreated)
            {
                isBeaconsLoaded = false;
                beaconList.Clear();
                lastLocation = -1.0;
                return;
            }

            var bindFlagsAll = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.FlattenHierarchy;

            try
            {
                dynamic vehicle = BveHacker.Scenario.Vehicle;
                dynamic map = BveHacker.Scenario.Map;
                if (vehicle == null || map == null) return;

                double location = BveHacker.Scenario.VehicleLocation.Location;
                double speed = BveHacker.Scenario.VehicleLocation.Speed * 3.6;

                StringBuilder rtLog = new StringBuilder();
                bool hasChanges = false;

                // =========================================================
                // ① 地上子(Beacon)の取得と通過判定
                // =========================================================
                if (!isBeaconsLoaded)
                {
                    try
                    {
                        object beaconsObj = map.GetType().GetProperty("Beacons", bindFlagsAll)?.GetValue(map);
                        if (beaconsObj is System.Collections.IEnumerable enumBeacons)
                        {
                            foreach (object b in enumBeacons) beaconList.Add(b);
                        }
                        isBeaconsLoaded = true;

                        // ログファイルの初期化
                        System.IO.File.WriteAllText(realtimeLogPath, $"=== REALTIME ATS LOG (Loaded Beacons: {beaconList.Count}) ===\n");
                    }
                    catch { }
                }

                if (lastLocation >= 0.0 && location > lastLocation)
                {
                    foreach (var beacon in beaconList)
                    {
                        double bLoc = Convert.ToDouble(beacon.GetType().GetProperty("Location", bindFlagsAll)?.GetValue(beacon));
                        if (bLoc > lastLocation && bLoc <= location)
                        {
                            int type = Convert.ToInt32(beacon.GetType().GetProperty("Type", bindFlagsAll)?.GetValue(beacon));
                            int data = Convert.ToInt32(beacon.GetType().GetProperty("Data", bindFlagsAll)?.GetValue(beacon));
                            rtLog.AppendLine($"[{DateTime.Now:HH:mm:ss.fff}] [Spd:{speed:F1}] ★ BEACON通過! Type: {type}, Data: {data}, Loc: {bLoc:F1}");
                            hasChanges = true;
                        }
                    }
                }
                lastLocation = location;

                // =========================================================
                // ② ATSプラグイン情報の取得
                // =========================================================
                object atsPlugin = vehicle.Instruments?.AtsPlugin;
                if (atsPlugin != null)
                {
                    // パネルとサウンド（プロパティから取得）
                    int[] currentSound = (int[])atsPlugin.GetType().GetProperty("SoundArray", bindFlagsAll)?.GetValue(atsPlugin);
                    int[] currentPanel = (int[])atsPlugin.GetType().GetProperty("PanelArray", bindFlagsAll)?.GetValue(atsPlugin);

                    if (currentSound != null)
                    {
                        for (int i = 0; i < currentSound.Length; i++)
                        {
                            if (currentSound[i] != prevSound[i])
                            {
                                rtLog.AppendLine($"[{DateTime.Now:HH:mm:ss.fff}] [Spd:{speed:F1}] Sound[{i}] changed: {prevSound[i]} -> {currentSound[i]}");
                                prevSound[i] = currentSound[i];
                                hasChanges = true;
                            }
                        }
                    }

                    if (currentPanel != null)
                    {
                        for (int i = 0; i < currentPanel.Length; i++)
                        {
                            if (currentPanel[i] != prevPanel[i])
                            {
                                rtLog.AppendLine($"[{DateTime.Now:HH:mm:ss.fff}] [Spd:{speed:F1}] Panel[{i}] changed: {prevPanel[i]} -> {currentPanel[i]}");
                                prevPanel[i] = currentPanel[i];
                                hasChanges = true;
                            }
                        }
                    }

                    // =========================================================
                    // ③ 論理ノッチ vs 物理ノッチ の監視
                    // =========================================================
                    object physHandles = atsPlugin.GetType().GetProperty("Handles", bindFlagsAll)?.GetValue(atsPlugin);
                    object atsHandles = atsPlugin.GetType().GetProperty("AtsHandles", bindFlagsAll)?.GetValue(atsPlugin);

                    int physBrake = 0;
                    int atsBrake = 0;

                    if (physHandles != null) physBrake = Convert.ToInt32(physHandles.GetType().GetProperty("BrakeNotch", bindFlagsAll)?.GetValue(physHandles));
                    if (atsHandles != null) atsBrake = Convert.ToInt32(atsHandles.GetType().GetProperty("BrakeNotch", bindFlagsAll)?.GetValue(atsHandles));

                    // ブレーキ状態に変化があった時、または「ATSの介入状態」が変わった時にログ出力
                    if (physBrake != prevPhysBrake || atsBrake != prevAtsBrake)
                    {
                        if (atsBrake > physBrake)
                        {
                            rtLog.AppendLine($"[{DateTime.Now:HH:mm:ss.fff}] [Spd:{speed:F1}] ⚠️ ATS介入中! (物理:{physBrake}段 < 論理:{atsBrake}段)");
                        }
                        else if (prevAtsBrake > prevPhysBrake && atsBrake <= physBrake)
                        {
                            rtLog.AppendLine($"[{DateTime.Now:HH:mm:ss.fff}] [Spd:{speed:F1}] 🟢 ATS介入解除 (物理:{physBrake}段, 論理:{atsBrake}段)");
                        }

                        prevPhysBrake = physBrake;
                        prevAtsBrake = atsBrake;
                        hasChanges = true;
                    }
                }

                // 変化があった時だけログに書き出し
                if (hasChanges)
                {
                    System.IO.File.AppendAllText(realtimeLogPath, rtLog.ToString());
                }
            }
            catch { }
        }
    }
}