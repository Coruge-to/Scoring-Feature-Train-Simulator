// Legacy sway SOURCE lookup test fixture (C# 5 on purpose: Windows PowerShell's Add-Type compiles it). Compiled TOGETHER with SwayFakeTypes.cs into an assembly NAMED TsScoringLegacyTelemetryTests,
// which the telemetry DLL lets see its internals (InternalsVisibleTo). Nothing here touches BVE, AtsEX, the network or the disk.
//   FakeSwayHost         : a fake ILegacySwayHostAccess (the wrapper side) with switchable failures
//   bz / ar / cu / aw ... : fake RAW structure with the names of the audited BVE: bz has a private field "l" of type "ar"; ar has a method "a()" returning the IList; the figure's type is "b4"
using System;
using System.Collections;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

namespace TsScoringSwayFakes
{
    public class SecretFailure : Exception
    {
        public SecretFailure() : base("SECRET-MESSAGE-MUST-NOT-APPEAR") { }
    }

    public class cu { }
    public class aw : cu { }
    public class ci : cu { }
    public class ae : cu { }

    public class ar
    {
        public List<object> Items = new List<object>();
        public string Mode = "ok";      // ok | null | throw
        public List<object> a()
        {
            if (Mode == "null") { return null; }
            if (Mode == "throw") { throw new SecretFailure(); }
            return Items;
        }
    }

    public class bz
    {
        private ar l;
        public bz(ar drawer) { l = drawer; }
    }

    public class bzNoDrawerField
    {
        private ar other = new ar();
        public object Touch() { return other; }
    }

    public class bzWrongFieldType
    {
        private string l = "x";
        public object Touch() { return l; }
    }

    public class arNoMethod
    {
        public object b() { return null; }
    }

    public class bzWithArNoMethod
    {
        private arNoMethod l = new arNoMethod();
        public object Touch() { return l; }
    }

    // ---- the host reader (IBveHacker.MainFormSource through the interface by name)
    public interface IBveHacker { object MainFormSource { get; } }
    public interface IOtherHacker { object MainFormSource { get; } }
    public interface IBveHackerNoProperty { }

    public class FakeHacker : IBveHacker
    {
        public object Form;
        public bool Throw;
        public object MainFormSource { get { if (Throw) { throw new SecretFailure(); } return Form; } }
    }

    public class FakeHackerOtherName : IOtherHacker
    {
        public object MainFormSource { get { return new object(); } }
    }

    public static class HostReaderProbe
    {
        public static object Read(object hacker) { return LegacySwayHostReader.ReadMainFormSource(hacker); }
    }

    public class WrapperMainFormFake { }
    public class WrapperDrawerFake { }
    public class WrapperItemFake { public bool IsSway; public object Src; }

    public class WrapperItemList : IEnumerable
    {
        public List<WrapperItemFake> Items = new List<WrapperItemFake>();
        public string FailMode = "none";       // none | invalid-operation | invalid-cast | null-ref | secret
        public int FailAt = 0;
        public IEnumerator GetEnumerator()
        {
            for (int i = 0; i < Items.Count; i++)
            {
                if (i == FailAt && FailMode != "none")
                {
                    if (FailMode == "invalid-operation") { throw new InvalidOperationException("boom"); }
                    if (FailMode == "invalid-cast") { throw new InvalidCastException("cast"); }
                    if (FailMode == "null-ref") { throw new NullReferenceException(); }
                    throw new SecretFailure();
                }

                yield return Items[i];
            }
        }
    }

    public class FakeSwayHost : ILegacySwayHostAccess
    {
        public string MainFormMode = "ok";        // ok | null | throw
        public string DrawerMode = "ok";          // ok | null | throw
        public string ItemsMode = "ok";           // ok | null | throw
        public WrapperItemList Items = new WrapperItemList();
        public object RawForm;                    // null = RawMainForm() returns null
        public string RawMode = "ok";             // ok | throw
        public int WrapperCalls;
        public int RawCalls;
        public int ItemCalls;

        public object WrapperMainForm()
        {
            WrapperCalls++;
            if (MainFormMode == "null") { return null; }
            if (MainFormMode == "throw") { throw new SecretFailure(); }
            return new WrapperMainFormFake();
        }

        public object WrapperAssistantDrawer(object wrapperMainForm)
        {
            if (DrawerMode == "null") { return null; }
            if (DrawerMode == "throw") { throw new SecretFailure(); }
            return new WrapperDrawerFake();
        }

        public IEnumerable WrapperItems(object wrapperAssistantDrawer)
        {
            if (ItemsMode == "null") { return null; }
            if (ItemsMode == "throw") { throw new SecretFailure(); }
            return Items;
        }

        public object FigureOfWrapperItem(object wrapperItem)
        {
            ItemCalls++;
            WrapperItemFake item = wrapperItem as WrapperItemFake;
            if (item != null && item.IsSway) { return item.Src; }
            return null;
        }

        public object RawMainForm()
        {
            RawCalls++;
            if (RawMode == "throw") { throw new SecretFailure(); }
            return RawForm;
        }

        // ---- builders
        public void FillWrapper(object figure, bool withSway, int count)
        {
            Items = new WrapperItemList();
            for (int i = 0; i < count; i++)
            {
                WrapperItemFake it = new WrapperItemFake();
                it.IsSway = withSway && i == count - 3;
                it.Src = it.IsSway ? figure : new object();
                Items.Items.Add(it);
            }
        }

        public static bz MakeRaw(object figure, bool withSway, int count)
        {
            ar drawer = new ar();
            for (int i = 0; i < count; i++)
            {
                if (withSway && i == count - 3) { drawer.Items.Add(figure); }
                else if (i % 3 == 0) { drawer.Items.Add(new aw()); }
                else if (i % 3 == 1) { drawer.Items.Add(new ci()); }
                else { drawer.Items.Add(new ae()); }
            }

            return new bz(drawer);
        }

        public static ar DrawerOf(bz form)
        {
            System.Reflection.FieldInfo f = typeof(bz).GetField("l", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            return (ar)f.GetValue(form);
        }
    }

    /// <summary>Drives a LegacySwayProvider from PowerShell (the provider API has out parameters and delegates).</summary>
    public class ProviderProbe
    {
        internal LegacySwayProvider Provider;
        public List<string> Lines = new List<string>();
        public List<string> Names = new List<string>();
        public string LastDiagnostic;
        public string LastRead = "none";

        public ProviderProbe(string version, FakeSwayHost host, bool withDiag)
        {
            Action<string, string> sink = null;
            if (withDiag) { sink = delegate(string name, string detail) { Names.Add(name); Lines.Add(detail); }; }
            Provider = new LegacySwayProvider(version, host, sink);
        }

        public bool Tick(object scenarioSource)
        {
            double a, b, c, d; string diag;
            bool ok = Provider.TryState(scenarioSource, out a, out b, out c, out d, out diag);
            LastDiagnostic = diag;
            LastRead = ok ? (a.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" + b.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" + c.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" + d.ToString("R", System.Globalization.CultureInfo.InvariantCulture)) : "none";
            return ok;
        }

        public void Ticks(object scenarioSource, int n)
        {
            for (int i = 0; i < n; i++) { Tick(scenarioSource); }
        }

        public string Status { get { return Provider.Status.ToString(); } }
        public int FindAttempts { get { return Provider.FindAttempts; } }
        public int Generation { get { return Provider.Generation; } }
        public bool Released { get { return Provider.Released; } }
        public void Release() { Provider.Release(); }
        public string AllLines() { return string.Join("\n", Lines.ToArray()); }
        public int MaxLineLength() { int m = 0; foreach (string l in Lines) { if (l.Length > m) { m = l.Length; } } return m; }
        public int CountLines(string role) { int n = 0; foreach (string l in Lines) { if (l.StartsWith("role=" + role + " ")) { n++; } } return n; }
        public string LineOf(string role, int occurrence) { int n = 0; foreach (string l in Lines) { if (l.StartsWith("role=" + role + " ")) { if (n == occurrence) { return l; } n++; } } return ""; }
    }

    /// <summary>The finder alone (no state).</summary>
    public class FinderProbe
    {
        internal LegacySwaySourceResult Result;
        public FinderProbe(FakeSwayHost host) { Result = new LegacySwaySourceFinder(host).Find(); }
        public string SelectedPath { get { return Result.SelectedPath; } }
        public string FailureStage { get { return Result.FailureStage; } }
        public string ExceptionType { get { return Result.ExceptionType; } }
        public object Figure { get { return Result.Figure; } }
        public string WrapperStage { get { return Result.Wrapper.Stage; } }
        public string RawStage { get { return Result.Raw.Stage; } }
        public bool RawTried { get { return Result.Raw.Tried; } }
        public int WrapperCount { get { return Result.Wrapper.ItemsCount; } }
        public int RawCount { get { return Result.Raw.ItemsCount; } }
        public string WrapperNames { get { return string.Join(",", Result.Wrapper.TypeNames); } }
        public string RawNames { get { return string.Join(",", Result.Raw.TypeNames); } }
        public bool WrapperMainFormNull { get { return Result.Wrapper.MainFormNull; } }
        public bool WrapperDrawerNull { get { return Result.Wrapper.AssistantDrawerNull; } }
        public bool WrapperItemsNull { get { return Result.Wrapper.ItemsNull; } }
        public bool WrapperSway { get { return Result.Wrapper.SwayFound; } }
        public bool RawSway { get { return Result.Raw.SwayFound; } }
        public string RawMainFormType { get { return Result.Raw.MainFormType; } }
        public string RawDrawerType { get { return Result.Raw.AssistantDrawerType; } }
        public string RawItemsType { get { return Result.Raw.ItemsType; } }
        public string WrapperException { get { return Result.Wrapper.ExceptionType; } }
        public string RawException { get { return Result.Raw.ExceptionType; } }
    }
}
