// Legacy sway source lookup against the REAL Legacy BveTypes wrappers (C# 5 on purpose: Windows PowerShell's Add-Type compiles it). Compiled into an assembly NAMED TsScoringLegacyTelemetryTests, which the
// telemetry DLL lets see its internals. Used only by Test-SwaySourceLegacyRealL3.ps1, which loads the real BveTs.exe (assembly load only, BVE is never started) and builds FAKE STATE with
// GetUninitializedObject. Nothing here touches the network or the disk.
using System;
using System.Collections;
using BveTypes.ClassWrappers;
using TSScoringPlugin.Telemetry;

namespace TsScoringRealWrapperFakes
{
    public static class RealBridge
    {
        /// <summary>The PRODUCTION host access (AtsExSwayHostAccess) over real wrappers made from a fake original main form object.</summary>
        internal static ILegacySwayHostAccess Make(object originalMainForm, bool wrapperGetterThrows)
        {
            return new AtsExSwayHostAccess(
                delegate
                {
                    if (wrapperGetterThrows) { throw new InvalidOperationException("wrapper getter failed"); }
                    return MainForm.FromSource(originalMainForm);
                },
                delegate { return originalMainForm; });
        }

        public static object FindWrapper(object originalMainForm, bool wrapperGetterThrows, out string selectedPath, out string failureStage, out bool rawTried)
        {
            LegacySwaySourceFinder finder = new LegacySwaySourceFinder(Make(originalMainForm, wrapperGetterThrows));
            LegacySwaySourceResult r = finder.Find();
            selectedPath = r.SelectedPath;
            failureStage = r.FailureStage;
            rawTried = r.Raw.Tried;
            return r.Figure;
        }

        /// <summary>The loop of the SHD-L-01 build, character for character (gauge != null uses ClassWrapperBase.operator !=).</summary>
        public static string OriginalLoop(IEnumerable items)
        {
            object figure = null;
            try
            {
                foreach (AssistantBase item in items)
                {
                    SwayGauge gauge = item as SwayGauge;
                    if (gauge != null) { figure = gauge.Src; break; }
                }
            }
            catch (Exception ex)
            {
                return "CAUGHT " + ex.GetType().FullName;
            }

            return figure == null ? "no figure" : "figure found";
        }

        public static string NullOperatorProbe()
        {
            SwayGauge g = null;
            try { bool b = g != null; return "no exception " + b; }
            catch (Exception ex) { return "CAUGHT " + ex.GetType().FullName; }
        }

        public static IEnumerable ItemsOf(object originalMainForm)
        {
            return MainForm.FromSource(originalMainForm).AssistantDrawer.Items;
        }
    }
}
