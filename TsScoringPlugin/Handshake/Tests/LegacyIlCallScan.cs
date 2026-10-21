using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA / STAGE S1 - static IL call scanner (A10). TEST CODE ONLY: never part of the product DLL.
//
// Reads the method bodies of the types of a loaded assembly (no Cecil: MethodBody.GetILAsByteArray + Module.Resolve*) and reports every call target, every type that
// a type or a method body refers to, and the assemblies those types live in. Shared by the D4 invariant F10 (S4) and the 2A-alpha scan K09 / ITR-13. It does no file,
// process or network work: the caller hands over an already loaded Assembly.
//
// Guard against the classic failure of a scanner (an empty set that "passes"): Result carries TypesScanned / MethodsScanned / CallsSeen, and every user of the result
// first asserts that those counts are not zero. The scanner itself is proven by positive and negative control probes in Test-LegacyJumpPlane2A.ps1.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    public static class LegacyIlCallScan
    {
        public sealed class Result
        {
            public int TypesScanned;
            public int MethodsScanned;
            public int CallsSeen;
            public int Unresolved;
            public readonly List<string> Calls = new List<string>();                 // "Namespace.Type::Method" (every call / callvirt / newobj / ldftn / ldvirtftn target)
            public readonly List<string> ReferencedTypes = new List<string>();       // full names of every type used by a signature, a local, a token, a catch clause
            public readonly List<string> MemberNames = new List<string>();           // names of the scanned types and of their members
            public readonly List<string> ExternalAssemblies = new List<string>();    // simple names of the assemblies of the referenced types (the scanned one excluded)
            public readonly List<string> TypeNames = new List<string>();
        }

        private static readonly Dictionary<short, OpCode> ops = BuildOps();

        private static Dictionary<short, OpCode> BuildOps()
        {
            Dictionary<short, OpCode> d = new Dictionary<short, OpCode>();
            foreach (FieldInfo f in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
            {
                if (f.FieldType != typeof(OpCode)) continue;
                OpCode oc = (OpCode)f.GetValue(null);
                d[oc.Value] = oc;
            }
            return d;
        }

        public static Type[] LoadableTypes(Assembly asm)
        {
            try { return asm.GetTypes(); }
            catch (ReflectionTypeLoadException ex)
            {
                List<Type> l = new List<Type>();
                foreach (Type t in ex.Types) if (t != null) l.Add(t);
                return l.ToArray();
            }
        }

        /// <summary>Scans every type whose full name starts with the prefix (nested and compiler generated types included).</summary>
        public static Result ScanPrefix(Assembly asm, string prefix)
        {
            List<Type> sel = new List<Type>();
            foreach (Type t in LoadableTypes(asm)) if (t.FullName != null && t.FullName.StartsWith(prefix, StringComparison.Ordinal)) sel.Add(t);
            return ScanTypes(asm, sel);
        }

        /// <summary>Scans every type except those whose full name starts with one of the excluded prefixes.</summary>
        public static Result ScanAllExcept(Assembly asm, string[] excludedPrefixes)
        {
            List<Type> sel = new List<Type>();
            foreach (Type t in LoadableTypes(asm))
            {
                bool skip = false;
                foreach (string p in excludedPrefixes) if (t.FullName != null && t.FullName.StartsWith(p, StringComparison.Ordinal)) skip = true;
                if (!skip) sel.Add(t);
            }
            return ScanTypes(asm, sel);
        }

        public static bool ReferencesType(Assembly asm, string prefix, string typeFullName)
        {
            Result r = ScanPrefix(asm, prefix);
            foreach (string t in r.ReferencedTypes) if (t == typeFullName) return true;
            foreach (string c in r.Calls) if (c.StartsWith(typeFullName + "::", StringComparison.Ordinal)) return true;
            return false;
        }

        public static string MethodNameOf(string call)
        {
            int i = call.LastIndexOf("::", StringComparison.Ordinal);
            return i < 0 ? call : call.Substring(i + 2);
        }

        public static bool CallsAnyOf(Result r, string callPrefix)
        {
            foreach (string c in r.Calls) if (c.StartsWith(callPrefix, StringComparison.Ordinal)) return true;
            return false;
        }

        /// <summary>Phase LJX-1: the call targets of ONE method or constructor body (the call graph of the Legacy Jump execution is built from these).</summary>
        public static Result ScanMethod(Assembly asm, MethodBase method)
        {
            Result r = new Result();
            string own = asm.GetName().Name;
            ScanBody(method, own, r, new HashSet<string>(), new HashSet<string>());
            return r;
        }

        public static Result ScanTypes(Assembly asm, IEnumerable<Type> types)
        {
            Result r = new Result();
            string own = asm.GetName().Name;
            HashSet<string> seenTypes = new HashSet<string>();
            HashSet<string> seenAsm = new HashSet<string>();
            foreach (Type t in types)
            {
                r.TypesScanned++;
                r.TypeNames.Add(t.FullName);
                r.MemberNames.Add(t.Name);
                Note(t.BaseType, own, r, seenTypes, seenAsm);
                foreach (Type i in t.GetInterfaces()) Note(i, own, r, seenTypes, seenAsm);
                BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
                foreach (FieldInfo f in t.GetFields(all)) { r.MemberNames.Add(f.Name); Note(f.FieldType, own, r, seenTypes, seenAsm); }
                foreach (PropertyInfo p in t.GetProperties(all)) { r.MemberNames.Add(p.Name); Note(p.PropertyType, own, r, seenTypes, seenAsm); }
                foreach (EventInfo e in t.GetEvents(all)) r.MemberNames.Add(e.Name);
                List<MethodBase> bodies = new List<MethodBase>();
                foreach (MethodInfo m in t.GetMethods(all)) bodies.Add(m);
                foreach (ConstructorInfo c in t.GetConstructors(all)) bodies.Add(c);
                foreach (MethodBase mb in bodies)
                {
                    r.MemberNames.Add(mb.Name);
                    MethodInfo mi = mb as MethodInfo;
                    if (mi != null) Note(mi.ReturnType, own, r, seenTypes, seenAsm);
                    foreach (ParameterInfo pi in mb.GetParameters()) Note(pi.ParameterType, own, r, seenTypes, seenAsm);
                    ScanBody(mb, own, r, seenTypes, seenAsm);
                }
            }
            r.ReferencedTypes.AddRange(seenTypes);
            r.ExternalAssemblies.AddRange(seenAsm);
            return r;
        }

        private static string DefinitionName(Type t)
        {
            if (t.IsGenericType && !t.IsGenericTypeDefinition) t = t.GetGenericTypeDefinition();
            return t.FullName ?? t.Name;
        }

        private static void Note(Type t, string own, Result r, HashSet<string> seenTypes, HashSet<string> seenAsm)
        {
            if (t == null) return;
            while (t.HasElementType) t = t.GetElementType();
            if (t.IsGenericParameter) return;
            if (t.IsGenericType && !t.IsGenericTypeDefinition)
            {
                foreach (Type a in t.GetGenericArguments()) Note(a, own, r, seenTypes, seenAsm);
                t = t.GetGenericTypeDefinition();
            }
            string name = t.FullName ?? t.Name;
            seenTypes.Add(name);
            string an = t.Assembly.GetName().Name;
            if (an != own) seenAsm.Add(an);
        }

        private static void ScanBody(MethodBase m, string own, Result r, HashSet<string> seenTypes, HashSet<string> seenAsm)
        {
            MethodBody body;
            try { body = m.GetMethodBody(); } catch { r.Unresolved++; return; }
            if (body == null) return;
            r.MethodsScanned++;
            foreach (LocalVariableInfo lv in body.LocalVariables) Note(lv.LocalType, own, r, seenTypes, seenAsm);
            foreach (ExceptionHandlingClause ec in body.ExceptionHandlingClauses)
            {
                if (ec.Flags == ExceptionHandlingClauseOptions.Clause) { try { Note(ec.CatchType, own, r, seenTypes, seenAsm); } catch { r.Unresolved++; } }
            }
            byte[] il = body.GetILAsByteArray();
            if (il == null) return;
            Module module = m.Module;
            Type[] typeArgs = null;
            Type[] methodArgs = null;
            try { if (m.DeclaringType != null && m.DeclaringType.IsGenericType) typeArgs = m.DeclaringType.GetGenericArguments(); } catch { }
            try { if (m.IsGenericMethod) methodArgs = m.GetGenericArguments(); } catch { }
            int pos = 0;
            while (pos < il.Length)
            {
                short code = il[pos++];
                if (code == 0xFE && pos < il.Length) code = (short)(0xFE00 | il[pos++]);
                OpCode oc;
                if (!ops.TryGetValue(code, out oc)) { r.Unresolved++; return; }
                switch (oc.OperandType)
                {
                    case OperandType.InlineNone: break;
                    case OperandType.ShortInlineBrTarget:
                    case OperandType.ShortInlineI:
                    case OperandType.ShortInlineVar: pos += 1; break;
                    case OperandType.InlineVar: pos += 2; break;
                    case OperandType.InlineI8:
                    case OperandType.InlineR: pos += 8; break;
                    case OperandType.InlineSwitch:
                        {
                            int n = BitConverter.ToInt32(il, pos);
                            pos += 4 + 4 * n;
                            break;
                        }
                    case OperandType.InlineMethod:
                        {
                            int tok = BitConverter.ToInt32(il, pos);
                            pos += 4;
                            r.CallsSeen++;
                            try
                            {
                                MethodBase target = module.ResolveMethod(tok, typeArgs, methodArgs);
                                Type dt = target.DeclaringType;
                                string dn = dt == null ? "?" : DefinitionName(dt);
                                r.Calls.Add(dn + "::" + target.Name);
                                if (dt != null) Note(dt, own, r, seenTypes, seenAsm);
                            }
                            catch { r.Unresolved++; r.Calls.Add("unresolved::" + tok.ToString("x8")); }
                            break;
                        }
                    case OperandType.InlineType:
                        {
                            int tok = BitConverter.ToInt32(il, pos);
                            pos += 4;
                            try { Note(module.ResolveType(tok, typeArgs, methodArgs), own, r, seenTypes, seenAsm); } catch { r.Unresolved++; }
                            break;
                        }
                    case OperandType.InlineField:
                        {
                            int tok = BitConverter.ToInt32(il, pos);
                            pos += 4;
                            try
                            {
                                FieldInfo f = module.ResolveField(tok, typeArgs, methodArgs);
                                Note(f.DeclaringType, own, r, seenTypes, seenAsm);
                                Note(f.FieldType, own, r, seenTypes, seenAsm);
                            }
                            catch { r.Unresolved++; }
                            break;
                        }
                    case OperandType.InlineTok:
                        {
                            int tok = BitConverter.ToInt32(il, pos);
                            pos += 4;
                            try
                            {
                                MemberInfo mm = module.ResolveMember(tok, typeArgs, methodArgs);
                                Type tt = mm as Type;
                                if (tt != null) Note(tt, own, r, seenTypes, seenAsm);
                                else if (mm.DeclaringType != null) Note(mm.DeclaringType, own, r, seenTypes, seenAsm);
                            }
                            catch { r.Unresolved++; }
                            break;
                        }
                    default: pos += 4; break;      // InlineI, InlineBrTarget, InlineString, InlineSig, ShortInlineR
                }
            }
        }
    }
}
