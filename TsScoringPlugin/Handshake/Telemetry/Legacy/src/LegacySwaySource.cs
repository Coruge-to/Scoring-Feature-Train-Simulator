// Shadow sway diagnostics, LEGACY ONLY: finds the ORIGINAL BVE passenger-sway figure object (b4) for the shared SwayStateReader, says WHY when it cannot, and has one bounded fallback.
// (Current never uses this file: the Current sender has its own, unchanged lookup in TsScoringPlugin\Class1.cs.)
//
// Why this file exists (SHD-L-01, Owner ruling LSR-D1): the Legacy lookup used to be
//     foreach (AssistantBase item in hacker.MainForm.AssistantDrawer.Items) { SwayGauge gauge = item as SwayGauge; if (gauge != null) {...} }  inside  try { } catch { figure = null; }
// BveTypes.ClassWrappers.ClassWrapperBase (Legacy BveTypes 1.0.50314.2) defines operator == / != as  left.Equals(right) : with a NULL left operand it throws NullReferenceException.
// `item as SwayGauge` is null for the first item (the time table), so `gauge != null` threw, the catch hid it, and the figure was never found (pending:no-source for ever).
// The test below therefore never uses a wrapper operator: it uses `is` and the original object only.
//
// Order (Owner LSR-D1), one attempt = one Find():
//   1. the WRAPPER path  : hacker.MainForm -> AssistantDrawer -> Items -> the item that is a SwayGauge -> its original object (Src)
//   2. the RAW-LIST path : ONLY when the wrapper path failed: IBveHacker.MainFormSource (the original main form, a public property) -> its private field "l" (type "ar", the drawer)
//                          -> the method "a()" of the drawer (the underlying IList) -> the element whose runtime type is "b4". These are the members the Legacy BveTypes mapping itself names
//                          (MainForm.AssistantDrawer = bz.l, AssistantDrawer.Items = ar.a(), SwayGauge = b4); the audited BVE versions only (the caller checks the version first), no enumeration of
//                          members, no search of the object graph, one fixed chain.
//   When the wrapper path succeeds the raw path is NOT run and no value of it is used. Both failed = nothing is found = unavailable (never a 0).
// It writes nothing, calls nothing of the host except the getters above, shows nothing, and records the TYPE NAME of an exception only (never its message or stack).
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;

namespace TSScoringPlugin.Telemetry
{
    /// <summary>What the Legacy adapter hands to the finder: only plain objects (the real adapter wraps IBveHacker; the offline tests fake it).</summary>
    internal interface ILegacySwayHostAccess
    {
        /// <summary>The wrapper main form (IBveHacker.MainForm) or null.</summary>
        object WrapperMainForm();

        /// <summary>The wrapper AssistantDrawer of that main form, or null.</summary>
        object WrapperAssistantDrawer(object wrapperMainForm);

        /// <summary>The wrapper items (AssistantDrawer.Items) or null. Enumerating it may throw (a wrapper that cannot be made).</summary>
        IEnumerable WrapperItems(object wrapperAssistantDrawer);

        /// <summary>The ORIGINAL object (Src) of a wrapper item that is a SwayGauge, otherwise null. Must not use a wrapper operator ==/!=.</summary>
        object FigureOfWrapperItem(object wrapperItem);

        /// <summary>The ORIGINAL main form object (IBveHacker.MainFormSource) or null.</summary>
        object RawMainForm();
    }

    internal static class SwayFailureStage
    {
        internal const string None = "none";
        internal const string MainFormNull = "mainform-null";
        internal const string AssistantDrawerNull = "assistantdrawer-null";
        internal const string ItemsNull = "items-null";
        internal const string ItemsEnumerationFailure = "items-enumeration-failure";
        internal const string TypeCastFailure = "type-cast-failure";
        internal const string NoSwayItem = "no-sway-item";
        internal const string VersionMismatch = "version-mismatch";
        internal const string FieldSignatureMismatch = "field-signature-mismatch";
        internal const string ReflectionException = "reflection-exception";
        internal const string UnexpectedException = "unexpected-exception";
        internal const string NotRun = "not-run";
    }

    /// <summary>
    /// The one read of the host that needs the type System.Windows.Forms.Form: IBveHacker.MainFormSource (the original main form, a PUBLIC property of the public interface). Naming the property at compile time
    /// would add an assembly reference to the product DLL (which is pinned to AtsEX, BveTypes and the framework core only), and the host adapter must not contain reflection, so the adapter hands the hacker
    /// over as a plain object and this host-independent class reads that one public interface property. It finds the interface by its name among the interfaces of the object, reads nothing else,
    /// and returns null when the object is null, has no such interface or no such property (never throws for those).
    /// </summary>
    internal static class LegacySwayHostReader
    {
        internal const string HackerInterfaceName = "IBveHacker";
        internal const string MainFormSourceName = "MainFormSource";

        internal static object ReadMainFormSource(object hacker)
        {
            if (hacker == null)
            {
                return null;
            }

            Type[] interfaces = hacker.GetType().GetInterfaces();
            for (int i = 0; i < interfaces.Length; i++)
            {
                if (interfaces[i].Name == HackerInterfaceName)
                {
                    PropertyInfo property = interfaces[i].GetProperty(MainFormSourceName);
                    if (property == null)
                    {
                        return null;
                    }

                    return property.GetValue(hacker, null);
                }
            }

            return null;
        }
    }

    internal sealed class SwayPathProbe
    {
        internal bool Tried;
        internal bool MainFormNull;
        internal bool AssistantDrawerNull;
        internal bool ItemsNull;
        internal int ItemsCount = -1;
        internal string[] TypeNames = new string[0];
        internal bool SwayFound;
        internal object Figure;
        internal string MainFormType = "none";
        internal string AssistantDrawerType = "none";
        internal string ItemsType = "none";
        internal string Stage = SwayFailureStage.NotRun;
        internal string ExceptionType = "none";
    }

    internal sealed class LegacySwaySourceResult
    {
        internal SwayPathProbe Wrapper = new SwayPathProbe();
        internal SwayPathProbe Raw = new SwayPathProbe();
        internal string SelectedPath = "none";           // wrapper | raw-list | none
        internal string FailureStage = SwayFailureStage.None;
        internal string ExceptionType = "none";
        internal object Figure;
    }

    internal sealed class LegacySwaySourceFinder
    {
        internal const string RawDrawerFieldName = "l";
        internal const string RawDrawerTypeName = "ar";
        internal const string RawItemsMethodName = "a";
        internal const string RawFigureTypeName = "b4";
        private const int MaxNames = 16;
        private const int MaxNameChars = 24;
        private const BindingFlags Declared = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        private readonly ILegacySwayHostAccess host;

        internal LegacySwaySourceFinder(ILegacySwayHostAccess host)
        {
            this.host = host;
        }

        /// <summary>One attempt. Never throws.</summary>
        internal LegacySwaySourceResult Find()
        {
            LegacySwaySourceResult result = new LegacySwaySourceResult();
            try
            {
                result.Wrapper = ProbeWrapper();
                if (result.Wrapper.SwayFound && result.Wrapper.Figure != null && result.Wrapper.Stage == SwayFailureStage.None)
                {
                    result.SelectedPath = "wrapper";
                    result.Figure = result.Wrapper.Figure;
                    return result;
                }

                // the wrapper path failed: the bounded fallback (never run, and never mixed in, when the wrapper path succeeded)
                result.Raw = ProbeRaw();
                if (result.Raw.SwayFound && result.Raw.Figure != null && result.Raw.Stage == SwayFailureStage.None)
                {
                    result.SelectedPath = "raw-list";
                    result.Figure = result.Raw.Figure;
                    return result;
                }

                result.SelectedPath = "none";
                result.FailureStage = result.Raw.Stage != SwayFailureStage.None && result.Raw.Stage != SwayFailureStage.NotRun ? result.Raw.Stage : result.Wrapper.Stage;
                result.ExceptionType = result.Raw.ExceptionType != "none" ? result.Raw.ExceptionType : result.Wrapper.ExceptionType;
            }
            catch (Exception ex)
            {
                result.SelectedPath = "none";
                result.Figure = null;
                result.FailureStage = SwayFailureStage.UnexpectedException;
                result.ExceptionType = ExceptionName(ex);
            }

            return result;
        }

        /// <summary>The result of an attempt that was not made because the BVE version is not an audited one: nothing of the host is touched.</summary>
        internal static LegacySwaySourceResult VersionMismatchResult()
        {
            LegacySwaySourceResult result = new LegacySwaySourceResult();
            result.FailureStage = SwayFailureStage.VersionMismatch;
            return result;
        }

        // ---------------------------------------------------------------- wrapper path
        private SwayPathProbe ProbeWrapper()
        {
            SwayPathProbe p = new SwayPathProbe();
            p.Tried = true;
            string phase = "mainform";
            List<string> names = new List<string>();
            int count = 0;
            try
            {
                object mainForm = host.WrapperMainForm();
                if (mainForm == null)
                {
                    p.MainFormNull = true;
                    p.Stage = SwayFailureStage.MainFormNull;
                    return p;
                }

                p.MainFormType = TypeNameOf(mainForm);
                phase = "drawer";
                object drawer = host.WrapperAssistantDrawer(mainForm);
                if (drawer == null)
                {
                    p.AssistantDrawerNull = true;
                    p.Stage = SwayFailureStage.AssistantDrawerNull;
                    return p;
                }

                p.AssistantDrawerType = TypeNameOf(drawer);
                phase = "items";
                IEnumerable items = host.WrapperItems(drawer);
                if (items == null)
                {
                    p.ItemsNull = true;
                    p.Stage = SwayFailureStage.ItemsNull;
                    return p;
                }

                p.ItemsType = TypeNameOf(items);
                phase = "enumeration";
                object figure = null;
                foreach (object item in items)
                {
                    count++;
                    if (names.Count < MaxNames)
                    {
                        names.Add(TypeNameOf(item));
                    }

                    if (figure == null)
                    {
                        object candidate = host.FigureOfWrapperItem(item);
                        if (candidate != null)
                        {
                            figure = candidate;
                        }
                    }
                }

                p.ItemsCount = count;
                p.TypeNames = names.ToArray();
                if (figure == null)
                {
                    p.Stage = SwayFailureStage.NoSwayItem;
                    return p;
                }

                p.Figure = figure;
                p.SwayFound = true;
                p.Stage = SwayFailureStage.None;
            }
            catch (Exception ex)
            {
                p.Figure = null;
                p.SwayFound = false;
                p.ItemsCount = phase == "enumeration" ? count : p.ItemsCount;
                p.TypeNames = names.ToArray();
                p.Stage = Classify(ex, phase == "enumeration");
                p.ExceptionType = ExceptionName(ex);
            }

            return p;
        }

        // ---------------------------------------------------------------- raw-list path
        private SwayPathProbe ProbeRaw()
        {
            SwayPathProbe p = new SwayPathProbe();
            p.Tried = true;
            bool enumerating = false;
            List<string> names = new List<string>();
            int count = 0;
            try
            {
                object mainForm = host.RawMainForm();
                if (mainForm == null)
                {
                    p.MainFormNull = true;
                    p.Stage = SwayFailureStage.MainFormNull;
                    return p;
                }

                p.MainFormType = TypeNameOf(mainForm);
                FieldInfo drawerField = FindDeclaredField(mainForm.GetType(), RawDrawerFieldName);
                if (drawerField == null || drawerField.FieldType.Name != RawDrawerTypeName)
                {
                    p.Stage = SwayFailureStage.FieldSignatureMismatch;
                    return p;
                }

                object drawer = drawerField.GetValue(mainForm);
                if (drawer == null)
                {
                    p.AssistantDrawerNull = true;
                    p.Stage = SwayFailureStage.AssistantDrawerNull;
                    return p;
                }

                p.AssistantDrawerType = TypeNameOf(drawer);
                MethodInfo itemsMethod = FindDeclaredItemsMethod(drawer.GetType());
                if (itemsMethod == null)
                {
                    p.Stage = SwayFailureStage.FieldSignatureMismatch;
                    return p;
                }

                object itemsObject = itemsMethod.Invoke(drawer, null);
                if (itemsObject == null)
                {
                    p.ItemsNull = true;
                    p.Stage = SwayFailureStage.ItemsNull;
                    return p;
                }

                p.ItemsType = TypeNameOf(itemsObject);
                IList list = itemsObject as IList;
                if (list == null)
                {
                    p.Stage = SwayFailureStage.FieldSignatureMismatch;
                    return p;
                }

                enumerating = true;
                object figure = null;
                for (int i = 0; i < list.Count; i++)
                {
                    object item = list[i];
                    count++;
                    if (names.Count < MaxNames)
                    {
                        names.Add(TypeNameOf(item));
                    }

                    if (figure == null && item != null && item.GetType().Name == RawFigureTypeName)
                    {
                        figure = item;
                    }
                }

                p.ItemsCount = count;
                p.TypeNames = names.ToArray();
                if (figure == null)
                {
                    p.Stage = SwayFailureStage.NoSwayItem;
                    return p;
                }

                p.Figure = figure;
                p.SwayFound = true;
                p.Stage = SwayFailureStage.None;
            }
            catch (Exception ex)
            {
                p.Figure = null;
                p.SwayFound = false;
                p.ItemsCount = enumerating ? count : p.ItemsCount;
                p.TypeNames = names.ToArray();
                p.Stage = Classify(ex, enumerating);
                p.ExceptionType = ExceptionName(ex);
            }

            return p;
        }

        private static FieldInfo FindDeclaredField(Type type, string name)
        {
            for (Type t = type; t != null && t != typeof(object); t = t.BaseType)
            {
                FieldInfo f = t.GetField(name, Declared);
                if (f != null)
                {
                    return f;
                }
            }

            return null;
        }

        private static MethodInfo FindDeclaredItemsMethod(Type type)
        {
            for (Type t = type; t != null && t != typeof(object); t = t.BaseType)
            {
                MethodInfo m = t.GetMethod(RawItemsMethodName, Declared, null, Type.EmptyTypes, null);
                if (m != null && typeof(IList).IsAssignableFrom(m.ReturnType))
                {
                    return m;
                }
            }

            return null;
        }

        // ---------------------------------------------------------------- classification and names (a type NAME only; never a message or a stack)
        internal static string Classify(Exception ex, bool enumerating)
        {
            Exception e = Unwrap(ex);
            if (e is InvalidCastException)
            {
                return SwayFailureStage.TypeCastFailure;
            }

            if (e is MemberAccessException || e is TargetException || e is TypeLoadException || e is AmbiguousMatchException || ex is TargetInvocationException)
            {
                return SwayFailureStage.ReflectionException;
            }

            return enumerating ? SwayFailureStage.ItemsEnumerationFailure : SwayFailureStage.UnexpectedException;
        }


        private static Exception Unwrap(Exception ex)
        {
            TargetInvocationException tie = ex as TargetInvocationException;
            if (tie != null && tie.InnerException != null)
            {
                return tie.InnerException;
            }

            return ex;
        }

        internal static string ExceptionName(Exception ex)
        {
            Exception e = Unwrap(ex);
            return CleanToken(e.GetType().FullName);
        }

        internal static string TypeNameOf(object value)
        {
            if (value == null)
            {
                return "null";
            }

            string name = value.GetType().Name;
            return CleanToken(name.Length > MaxNameChars ? name.Substring(0, MaxNameChars) : name);
        }

        internal static string CleanToken(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "none";
            }

            char[] chars = text.ToCharArray();
            for (int i = 0; i < chars.Length; i++)
            {
                char ch = chars[i];
                bool keep = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '_';
                if (!keep)
                {
                    chars[i] = '-';
                }
            }

            return new string(chars);
        }
    }

    /// <summary>
    /// The state around the finder for ONE adapter: the reader, the 30-Tick retry, the scenario boundary, the cache and the once-per-scenario diagnostic. Host independent (the offline tests drive it with a fake host).
    /// </summary>
    internal sealed class LegacySwayProvider
    {
        internal const int RetryEveryTicks = 30;                 // the existing contract: an unresolved source is looked for again on every 30th Tick only
        internal const int MaxDetailChars = 150;                 // a diagnostic line (the file log adds a short prefix); far below the Caller's 192
        internal const int MaxDiagnosticsPerScenario = 4;        // the first outcome plus at most 3 CHANGES of it

        private readonly SwayStateReader reader;
        private readonly LegacySwaySourceFinder finder;
        private readonly Action<string, string> diag;
        private readonly string version;
        private object lastScenarioSource;
        private bool haveScenarioSource;
        private int pendingTicks;
        private int generation;
        private int diagnosticsInScenario;
        private string lastSignature;
        private bool released;
        private int findAttempts;

        internal LegacySwayProvider(string bveFileVersion, ILegacySwayHostAccess host, Action<string, string> diag)
        {
            version = string.IsNullOrEmpty(bveFileVersion) ? "unknown" : bveFileVersion.Trim();
            reader = new SwayStateReader(version, "legacy");
            finder = new LegacySwaySourceFinder(host);
            this.diag = diag;
        }

        internal SwayStatus Status { get { return reader.Status; } }

        internal int FindAttempts { get { return findAttempts; } }

        internal int Generation { get { return generation; } }

        internal bool Released { get { return released; } }

        /// <summary>The adapter's TrySwayState. Tick thread only; never throws.</summary>
        internal bool TryState(object scenarioSource, out double longitudinalX, out double longitudinalV, out double lateralX, out double lateralV, out string diagnostic)
        {
            longitudinalX = 0; longitudinalV = 0; lateralX = 0; lateralV = 0; diagnostic = null;
            try
            {
                if (released)
                {
                    return false;
                }

                if (!haveScenarioSource || !object.ReferenceEquals(scenarioSource, lastScenarioSource))
                {
                    // a scenario boundary (a new scenario instance, F5, a reload): the binding, the cache and the once-per-scenario diagnostic start again
                    haveScenarioSource = true;
                    lastScenarioSource = scenarioSource;
                    reader.Reset();
                    pendingTicks = 0;
                    generation++;
                    diagnosticsInScenario = 0;
                    lastSignature = null;
                }

                if (reader.Status == SwayStatus.Pending)
                {
                    if (pendingTicks % RetryEveryTicks == 0)
                    {
                        Attempt();
                    }

                    pendingTicks++;
                }

                diagnostic = reader.ResolutionText();
                return reader.TryRead(out longitudinalX, out longitudinalV, out lateralX, out lateralV);
            }
            catch
            {
                diagnostic = null;
                return false;
            }
        }

        /// <summary>Dispose / session end: nothing is kept (the source object, the reader binding, the host).</summary>
        internal void Release()
        {
            released = true;
            lastScenarioSource = null;
            haveScenarioSource = false;
            try { reader.Reset(); } catch { }
            lastSignature = null;
        }

        private void Attempt()
        {
            LegacySwaySourceResult result;
            if (reader.Resolve(null) == SwayStatus.VersionUnsupported)
            {
                // not an audited BVE version: no member of the host is touched, nothing is guessed
                result = LegacySwaySourceFinder.VersionMismatchResult();
            }
            else
            {
                findAttempts++;
                result = finder.Find();
            }

            reader.Resolve(result.Figure);      // null keeps it Pending (no-source) or VersionUnsupported; a figure is validated by the reader's structure signature (fail-closed)
            Emit(result);
        }

        private void Emit(LegacySwaySourceResult result)
        {
            if (diag == null)
            {
                return;
            }

            string failureStage = result.FailureStage;
            string exceptionType = result.ExceptionType;
            string readerWord = reader.ResultWord();
            if (result.Figure != null && reader.Status == SwayStatus.StructureMismatch)
            {
                failureStage = SwayFailureStage.FieldSignatureMismatch;
            }
            else if (result.Figure != null && reader.Status == SwayStatus.Unavailable)
            {
                failureStage = SwayFailureStage.ReflectionException;
            }

            string signature = result.SelectedPath + "|" + failureStage + "|" + exceptionType + "|" + readerWord + "|" + reader.Detail + "|" + result.Wrapper.ItemsCount + "|" + result.Raw.ItemsCount;
            if (signature == lastSignature || diagnosticsInScenario >= MaxDiagnosticsPerScenario)
            {
                return;      // the same outcome is never logged twice in one scenario
            }

            lastSignature = signature;
            diagnosticsInScenario++;
            string head = "bve_version=" + LegacySwaySourceFinder.CleanToken(version) + " entry=legacy gen=" + generation.ToString(CultureInfo.InvariantCulture);
            Line("role=summary " + head + " selected_path=" + result.SelectedPath + " failure_stage=" + failureStage);
            Line("role=exception " + head + " exception_type=" + exceptionType);
            Line(ProbeLine("role=wrapper gen=" + generation.ToString(CultureInfo.InvariantCulture) + " ", result.Wrapper, false));
            Line(ProbeLine("role=raw gen=" + generation.ToString(CultureInfo.InvariantCulture) + " ", result.Raw, true));
            Line("role=reader gen=" + generation.ToString(CultureInfo.InvariantCulture) + " reader_result=" + readerWord + " reader_detail=" + LegacySwaySourceFinder.CleanToken(string.IsNullOrEmpty(reader.Detail) ? "none" : reader.Detail));
        }

        private static string ProbeLine(string lead, SwayPathProbe p, bool raw)
        {
            if (!p.Tried)
            {
                return lead + "stage=" + SwayFailureStage.NotRun;
            }

            StringBuilder sb = new StringBuilder(lead);
            sb.Append("stage=").Append(p.Stage);
            if (raw)
            {
                sb.Append(" mainform_type=").Append(p.MainFormType);
                sb.Append(" assistantdrawer_type=").Append(p.AssistantDrawerType);
                sb.Append(" items_type=").Append(p.ItemsType);
            }
            else
            {
                sb.Append(" mainform_null=").Append(p.MainFormNull ? 1 : 0);
                sb.Append(" assistantdrawer_null=").Append(p.AssistantDrawerNull ? 1 : 0);
                sb.Append(" items_null=").Append(p.ItemsNull ? 1 : 0);
            }

            sb.Append(" items_count=").Append(p.ItemsCount.ToString(CultureInfo.InvariantCulture));
            sb.Append(" sway_found=").Append(p.SwayFound ? 1 : 0);
            return sb.ToString() + NamesPart(p.TypeNames, sb.Length);
        }

        /// <summary>The type names, as many as fit under the line cap; what does not fit is COUNTED (names_cut=N), never cut silently.</summary>
        private static string NamesPart(string[] names, int usedChars)
        {
            string prefix = " names=";
            int room = MaxDetailChars - usedChars - prefix.Length - 13;      // 13 = a " names_cut=NN" tail
            StringBuilder sb = new StringBuilder();
            int shown = 0;
            for (int i = 0; i < names.Length; i++)
            {
                int add = names[i].Length + (shown > 0 ? 1 : 0);
                if (sb.Length + add > room)
                {
                    break;
                }

                if (shown > 0) { sb.Append(','); }
                sb.Append(names[i]);
                shown++;
            }

            string text = prefix + (shown == 0 ? "none" : sb.ToString());
            if (shown < names.Length)
            {
                text += " names_cut=" + (names.Length - shown).ToString(CultureInfo.InvariantCulture);
            }

            return text;
        }

        private void Line(string text)
        {
            try
            {
                string line = text.Length > MaxDetailChars ? text.Substring(0, MaxDetailChars) : text;      // a safety net only: every line is built to fit
                diag("TEL_SWAY_SRC", line);
            }
            catch
            {
                // a diagnostic never takes BVE down
            }
        }
    }
}
