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

        // HandleSetの内部実体で保持されているブレーキ段
        private int prevPhysSrcBrake = int.MinValue;
        private int prevAtsSrcBrake = int.MinValue;

        // AtsPlugin.Src直下のc、lが保持するブレーキ段
        private int prevRawHandleCBrake = int.MinValue;
        private int prevRawHandleLBrake = int.MinValue;
        private int prevVehicleStateHandleBrake = int.MinValue;

        // 車両側で定義されているブレーキ段
        private int serviceMaxBrakeNotch = -1;
        private int emergencyBrakeNotch = -1;

        // ログファイルのセッション初期化状態
        private bool isLogSessionInitialized = false;

        // ATSプラグインの内部構造を出力済みか
        private bool isAtsStructureDumped = false;

        private double lastLocation = -1.0;
        private List<dynamic> beaconList = new List<dynamic>();
        private bool isBeaconsLoaded = false;

        // =========================================================
        // 共通ランタイムプロファイルの診断状態
        // =========================================================
        private bool hasScannedRuntimeProfiles = false;
        private bool hasLoggedRuntimeProfileError = false;
        private string runtimeProfilePath = null;

        // DLLの遅延ロードへ対応するため、一定間隔で再走査する。
        private DateTime nextRuntimeProfileScanTime =
            DateTime.MinValue;

        // 一度MATCHを出したDLLは重複記録しない。
        private HashSet<string> matchedRuntimeProfileHashes =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase
            );

        private Dictionary<string, RuntimeProfileIdentity>
            runtimeProfilesByHash =
                new Dictionary<string, RuntimeProfileIdentity>(
                    StringComparer.OrdinalIgnoreCase
                );

        private sealed class RuntimeProfileIdentity
        {
            public string Sha256;
            public string Pattern;
            public string VerificationStatus;

            // 一致したモジュールの実行時情報
            public string FileName;
            public IntPtr ModuleBaseAddress;

            // ObjectBackedBrakeOutputSelector用の静的配置
            public int ObjectPointerRva;
            public int PhysicalBrakeOffset;
            public int ServiceMaximumOffset;
            public int EmergencyOffset;
            public int OutputBrakeRva;

            // 前回ログ出力値
            public bool HasPreviousState;
            public int PreviousPhysicalBrake;
            public int PreviousServiceMaximum;
            public int PreviousEmergency;
            public int PreviousOutputBrake;
            public IntPtr PreviousObjectAddress;
        }

        public AtsLoggerPlugin(PluginBuilder builder) : base(builder) { }

        public override void Dispose() { }

        private void DumpObjectMembers(
    object target,
    string objectName,
    System.Reflection.BindingFlags bindFlags
)
        {
            if (target == null)
            {
                return;
            }

            StringBuilder dump = new StringBuilder();
            Type targetType = target.GetType();

            dump.AppendLine();
            dump.AppendLine(
                $"=== OBJECT DUMP: {objectName} ==="
            );
            dump.AppendLine(
                $"Type={targetType.FullName}"
            );

            dump.AppendLine("--- Properties ---");

            foreach (
                System.Reflection.PropertyInfo property
                in targetType.GetProperties(bindFlags)
            )
            {
                try
                {
                    // 引数が必要なインデクサーは読み取らない。
                    if (
                        property.GetIndexParameters().Length > 0
                    )
                    {
                        dump.AppendLine(
                            $"{property.Name} "
                            + $"[{property.PropertyType.FullName}] "
                            + "= <INDEXED>"
                        );

                        continue;
                    }

                    object value = property.GetValue(
                        target,
                        null
                    );

                    dump.AppendLine(
                        $"{property.Name} "
                        + $"[{property.PropertyType.FullName}] "
                        + $"= {FormatDumpValue(value)}"
                    );
                }
                catch (Exception ex)
                {
                    dump.AppendLine(
                        $"{property.Name} "
                        + $"[{property.PropertyType.FullName}] "
                        + $"= <ERROR:{ex.GetType().Name}>"
                    );
                }
            }

            dump.AppendLine("--- Fields ---");

            foreach (
                System.Reflection.FieldInfo field
                in targetType.GetFields(bindFlags)
            )
            {
                try
                {
                    object value = field.GetValue(target);

                    dump.AppendLine(
                        $"{field.Name} "
                        + $"[{field.FieldType.FullName}] "
                        + $"= {FormatDumpValue(value)}"
                    );
                }
                catch (Exception ex)
                {
                    dump.AppendLine(
                        $"{field.Name} "
                        + $"[{field.FieldType.FullName}] "
                        + $"= <ERROR:{ex.GetType().Name}>"
                    );
                }
            }

            dump.AppendLine(
                $"=== END OBJECT DUMP: {objectName} ==="
            );
            dump.AppendLine();

            System.IO.File.AppendAllText(
                realtimeLogPath,
                dump.ToString()
            );
        }

        private string FormatDumpValue(object value)
        {
            if (value == null)
            {
                return "<NULL>";
            }

            Type valueType = value.GetType();

            if (
                valueType.IsPrimitive
                || value is string
                || value is decimal
                || value is Enum
            )
            {
                return value.ToString();
            }

            if (value is Array array)
            {
                return $"<ARRAY Length={array.Length}>";
            }

            return $"<OBJECT Type={valueType.FullName}>";
        }

        private string GetObjectIdentity(object value)
        {
            if (value == null)
            {
                return "<NULL>";
            }

            return
                $"{value.GetType().FullName}"
                + $"@{System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value)}";
        }

        private string FormatMethodSignature(
    System.Reflection.MethodInfo method
)
        {
            if (method == null)
            {
                return "<NULL METHOD>";
            }

            StringBuilder result = new StringBuilder();

            result.Append(
                method.ReturnType != null
                    ? method.ReturnType.FullName
                    : "<NULL RETURN TYPE>"
            );

            result.Append(" ");
            result.Append(method.Name);
            result.Append("(");

            System.Reflection.ParameterInfo[] parameters =
                method.GetParameters();

            for (int i = 0; i < parameters.Length; i++)
            {
                if (i > 0)
                {
                    result.Append(", ");
                }

                System.Reflection.ParameterInfo parameter =
                    parameters[i];

                result.Append(
                    parameter.ParameterType != null
                        ? parameter.ParameterType.FullName
                        : "<NULL PARAMETER TYPE>"
                );

                result.Append(" ");
                result.Append(parameter.Name);
            }

            result.Append(")");

            return result.ToString();
        }
        private void DumpDelegateInfo(
    object delegateObject,
    string delegateName,
    System.Reflection.BindingFlags bindFlags
)
        {
            StringBuilder log = new StringBuilder();

            log.AppendLine();
            log.AppendLine(
                $"=== DELEGATE INFO: {delegateName} ==="
            );

            if (delegateObject == null)
            {
                log.AppendLine("Delegate=<NULL>");
                log.AppendLine(
                    $"=== END DELEGATE INFO: {delegateName} ==="
                );
                log.AppendLine();

                System.IO.File.AppendAllText(
                    realtimeLogPath,
                    log.ToString()
                );

                return;
            }

            try
            {
                Type delegateType = delegateObject.GetType();

                log.AppendLine(
                    $"DelegateType={delegateType.FullName}"
                );

                object target = delegateType
                    .GetProperty(
                        "Target",
                        bindFlags
                    )
                    ?.GetValue(delegateObject);

                System.Reflection.MethodInfo method =
                    delegateType
                        .GetProperty(
                            "Method",
                            bindFlags
                        )
                        ?.GetValue(delegateObject)
                    as System.Reflection.MethodInfo;

                log.AppendLine(
                    $"Target={GetObjectIdentity(target)}"
                );

                log.AppendLine(
                    $"Method={FormatMethodSignature(method)}"
                );

                if (method != null)
                {
                    log.AppendLine(
                        $"DeclaringType="
                        + (
                            method.DeclaringType != null
                                ? method.DeclaringType.FullName
                                : "<NULL>"
                        )
                    );

                    log.AppendLine(
                        $"IsStatic={method.IsStatic}"
                    );

                    log.AppendLine(
                        $"IsPublic={method.IsPublic}"
                    );

                    log.AppendLine(
                        $"ReturnType="
                        + (
                            method.ReturnType != null
                                ? method.ReturnType.FullName
                                : "<NULL>"
                        )
                    );

                    System.Reflection.ParameterInfo[] parameters =
                        method.GetParameters();

                    log.AppendLine(
                        $"ParameterCount={parameters.Length}"
                    );

                    for (int i = 0; i < parameters.Length; i++)
                    {
                        System.Reflection.ParameterInfo parameter =
                            parameters[i];

                        log.AppendLine(
                            $"Parameter[{i}]="
                            + $"Type:{parameter.ParameterType.FullName}, "
                            + $"Name:{parameter.Name}, "
                            + $"IsOut:{parameter.IsOut}, "
                            + $"IsByRef:{parameter.ParameterType.IsByRef}"
                        );
                    }
                }
            }
            catch (Exception ex)
            {
                log.AppendLine(
                    $"ERROR={ex}"
                );
            }

            log.AppendLine(
                $"=== END DELEGATE INFO: {delegateName} ==="
            );
            log.AppendLine();

            System.IO.File.AppendAllText(
                realtimeLogPath,
                log.ToString()
            );
        }

        private void DumpTypeDefinition(
    Type targetType,
    string typeName,
    System.Reflection.BindingFlags bindFlags
)
        {
            StringBuilder log = new StringBuilder();

            log.AppendLine();
            log.AppendLine(
                $"=== TYPE DEFINITION: {typeName} ==="
            );

            if (targetType == null)
            {
                log.AppendLine("Type=<NULL>");
                log.AppendLine(
                    $"=== END TYPE DEFINITION: {typeName} ==="
                );
                log.AppendLine();

                System.IO.File.AppendAllText(
                    realtimeLogPath,
                    log.ToString()
                );

                return;
            }

            try
            {
                log.AppendLine(
                    $"FullName={targetType.FullName}"
                );

                log.AppendLine(
                    $"BaseType="
                    + (
                        targetType.BaseType != null
                            ? targetType.BaseType.FullName
                            : "<NULL>"
                    )
                );

                log.AppendLine(
                    $"IsValueType={targetType.IsValueType}"
                );

                log.AppendLine(
                    $"IsClass={targetType.IsClass}"
                );

                log.AppendLine("--- Properties ---");

                System.Reflection.PropertyInfo[] properties =
                    targetType.GetProperties(bindFlags);

                foreach (
                    System.Reflection.PropertyInfo property
                    in properties
                )
                {
                    log.AppendLine(
                        $"{property.Name} "
                        + $"[{property.PropertyType.FullName}] "
                        + $"CanRead:{property.CanRead}, "
                        + $"CanWrite:{property.CanWrite}"
                    );
                }

                log.AppendLine("--- Fields ---");

                System.Reflection.FieldInfo[] fields =
                    targetType.GetFields(bindFlags);

                foreach (
                    System.Reflection.FieldInfo field
                    in fields
                )
                {
                    log.AppendLine(
                        $"{field.Name} "
                        + $"[{field.FieldType.FullName}] "
                        + $"IsStatic:{field.IsStatic}, "
                        + $"IsPublic:{field.IsPublic}"
                    );
                }

                log.AppendLine("--- Constructors ---");

                System.Reflection.ConstructorInfo[] constructors =
                    targetType.GetConstructors(bindFlags);

                foreach (
                    System.Reflection.ConstructorInfo constructor
                    in constructors
                )
                {
                    StringBuilder constructorText =
                        new StringBuilder();

                    constructorText.Append(
                        targetType.FullName
                    );
                    constructorText.Append("(");

                    System.Reflection.ParameterInfo[] parameters =
                        constructor.GetParameters();

                    for (int i = 0; i < parameters.Length; i++)
                    {
                        if (i > 0)
                        {
                            constructorText.Append(", ");
                        }

                        constructorText.Append(
                            parameters[i].ParameterType.FullName
                        );
                    }

                    constructorText.Append(")");

                    log.AppendLine(
                        constructorText.ToString()
                    );
                }
            }
            catch (Exception ex)
            {
                log.AppendLine(
                    $"ERROR={ex}"
                );
            }

            log.AppendLine(
                $"=== END TYPE DEFINITION: {typeName} ==="
            );
            log.AppendLine();

            System.IO.File.AppendAllText(
                realtimeLogPath,
                log.ToString()
            );
        }


        private bool TryGetIntField(
    object target,
    string fieldName,
    System.Reflection.BindingFlags bindFlags,
    out int value
)
        {
            value = 0;

            if (target == null)
            {
                return false;
            }

            try
            {
                System.Reflection.FieldInfo field = target.GetType()
                    .GetField(
                        fieldName,
                        bindFlags
                    );

                if (field == null)
                {
                    return false;
                }

                object rawValue = field.GetValue(target);

                if (rawValue == null)
                {
                    return false;
                }

                value = Convert.ToInt32(rawValue);
                return true;
            }
            catch
            {
                return false;
            }
        }

        // =========================================================
        // ファイルのSHA-256を大文字16進文字列として取得する
        // =========================================================
        private string ComputeFileSha256(string filePath)
        {
            using (
                System.Security.Cryptography.SHA256 sha256 =
                    System.Security.Cryptography.SHA256.Create()
            )
            using (
                System.IO.FileStream stream =
                    System.IO.File.OpenRead(filePath)
            )
            {
                byte[] hash = sha256.ComputeHash(stream);
                StringBuilder result =
                    new StringBuilder(hash.Length * 2);

                foreach (byte value in hash)
                {
                    result.Append(value.ToString("X2"));
                }

                return result.ToString();
            }
        }

        // =========================================================
        // 現在のプロセス内にある32ビット整数を安全に読み取る
        // =========================================================
        private bool TryReadRuntimeInt32(
            IntPtr address,
            out int value
        )
        {
            value = 0;

            if (address == IntPtr.Zero)
            {
                return false;
            }

            try
            {
                value =
                    System.Runtime.InteropServices.Marshal.ReadInt32(
                        address
                    );

                return true;
            }
            catch
            {
                return false;
            }
        }

        // =========================================================
        // 現在のプロセス内にある32ビットポインターを安全に読み取る
        // =========================================================
        private bool TryReadRuntimePointer32(
            IntPtr address,
            out IntPtr value
        )
        {
            value = IntPtr.Zero;

            int rawPointer;

            if (
                !TryReadRuntimeInt32(
                    address,
                    out rawPointer
                )
            )
            {
                return false;
            }

            if (rawPointer == 0)
            {
                return false;
            }

            value = new IntPtr(
                unchecked((long)(uint)rawPointer)
            );

            return true;
        }

        // =========================================================
        // 共通ランタイムプロファイルを読み込み、
        // ロード済みDLLとSHA-256で照合する
        //
        // 現段階では診断ログだけを出力し、減点には接続しない。
        // =========================================================
        private void DiagnoseRuntimeProfiles(
    StringBuilder rtLog,
    ref bool hasChanges
)
        {
            DateTime currentTime = DateTime.UtcNow;

            // BVEのTickごとに全DLLをハッシュ計算すると負荷が高いため、
            // DLL走査は1秒間隔に制限する。
            if (currentTime < nextRuntimeProfileScanTime)
            {
                return;
            }

            nextRuntimeProfileScanTime =
                currentTime.AddSeconds(1.0);

            try
            {
                // カタログファイルはシナリオごとに1回だけ読み込む。
                if (!hasScannedRuntimeProfiles)
                {
                    runtimeProfilePath = System.IO.Path.Combine(
                        Environment.GetFolderPath(
                            Environment.SpecialFolder.MyDocuments
                        ),
                        "BveDllInventory",
                        "reports",
                        "runtime-profile-candidates.json"
                    );

                    if (!System.IO.File.Exists(runtimeProfilePath))
                    {
                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + "[RUNTIME_PROFILE] FILE NOT FOUND "
                            + $"Path:{runtimeProfilePath}, "
                            + "ScoringEnabled:False"
                        );

                        hasChanges = true;
                        return;
                    }

                    string json =
                        System.IO.File.ReadAllText(runtimeProfilePath);

                    string profilePattern =
                        "\"sha256\"\\s*:\\s*"
                        + "\"(?<sha>[0-9A-Fa-f]{64})\""
                        + ".*?"
                        + "\"pattern\"\\s*:\\s*"
                        + "\"(?<pattern>[^\"]+)\""
                        + ".*?"
                        + "\"verificationStatus\"\\s*:\\s*"
                        + "\"(?<verification>[^\"]+)\"";

                    System.Text.RegularExpressions.MatchCollection
                        profileMatches =
                            System.Text.RegularExpressions.Regex.Matches(
                                json,
                                profilePattern,
                                System.Text.RegularExpressions
                                    .RegexOptions.Singleline
                            );

                    runtimeProfilesByHash.Clear();

                    foreach (
                        System.Text.RegularExpressions.Match profileMatch
                        in profileMatches
                    )
                    {
                        RuntimeProfileIdentity profile =
                            new RuntimeProfileIdentity();

                        profile.Sha256 =
                            profileMatch.Groups["sha"]
                                .Value
                                .ToUpperInvariant();

                        profile.Pattern =
                            profileMatch.Groups["pattern"].Value;

                        profile.VerificationStatus =
                            profileMatch.Groups["verification"].Value;

                        runtimeProfilesByHash[profile.Sha256] =
                            profile;
                    }

                    hasScannedRuntimeProfiles = true;

                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[RUNTIME_PROFILE] CATALOG LOADED "
                        + $"Count:{runtimeProfilesByHash.Count}, "
                        + $"Path:{runtimeProfilePath}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                }

                // カタログ読込み後も、DLL一覧は1秒ごとに再走査する。
                // これにより、シナリオ開始後に遅延ロードされた
                // 保安装置DLLも検出できる。
                System.Diagnostics.Process currentProcess =
                    System.Diagnostics.Process.GetCurrentProcess();

                foreach (
                    System.Diagnostics.ProcessModule module
                    in currentProcess.Modules
                )
                {
                    string modulePath = module.FileName;

                    if (
                        !string.Equals(
                            System.IO.Path.GetExtension(modulePath),
                            ".dll",
                            StringComparison.OrdinalIgnoreCase
                        )
                    )
                    {
                        continue;
                    }

                    string moduleHash;

                    try
                    {
                        moduleHash =
                            ComputeFileSha256(modulePath);
                    }
                    catch
                    {
                        // 読み取れないDLLは対象外として継続する。
                        continue;
                    }

                    RuntimeProfileIdentity matchedProfile;

                    if (
                        !runtimeProfilesByHash.TryGetValue(
                            moduleHash,
                            out matchedProfile
                        )
                    )
                    {
                        continue;
                    }

                    // 既に同じSHA-256のMATCHを記録済みなら、
                    // 1秒ごとの再走査では重複記録しない。
                    // モジュールの実行時情報は、再走査のたびに更新する。
                    matchedProfile.FileName =
                        System.IO.Path.GetFileName(modulePath);

                    matchedProfile.ModuleBaseAddress =
                        module.BaseAddress;

                    // ATSKeihan800.dllで確認した
                    // ObjectBackedBrakeOutputSelectorの静的配置。
                    if (
                        matchedProfile.Pattern
                            == "ObjectBackedBrakeOutputSelector"
                    )
                    {
                        matchedProfile.ObjectPointerRva = 0x17F44;
                        matchedProfile.PhysicalBrakeOffset = 0x3C;
                        matchedProfile.ServiceMaximumOffset = 0x2C;
                        matchedProfile.EmergencyOffset = 0x30;
                        matchedProfile.OutputBrakeRva = 0x17F4C;
                    }

                    // MATCHログは同じSHA-256につき1回だけ記録する。
                    if (
                        matchedRuntimeProfileHashes.Add(
                            moduleHash
                        )
                    )
                    {
                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + "[RUNTIME_PROFILE] MATCH "
                            + $"File:{matchedProfile.FileName}, "
                            + $"SHA256:{moduleHash}, "
                            + $"Pattern:{matchedProfile.Pattern}, "
                            + "Verification:"
                            + $"{matchedProfile.VerificationStatus}, "
                            + $"Base:0x{module.BaseAddress.ToInt64():X}, "
                            + "ScoringEnabled:False"
                        );

                        hasChanges = true;
                    }
                }
            }
            catch (Exception ex)
            {
                if (!hasLoggedRuntimeProfileError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[RUNTIME_PROFILE] ERROR "
                        + $"Type:{ex.GetType().Name}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedRuntimeProfileError = true;
                    hasChanges = true;
                }
            }
        }

        // =========================================================
        // MATCH済みのObjectBackedBrakeOutputSelectorについて、
        // 実メモリ値を読み取り、変化時だけ診断ログへ記録する。
        //
        // この処理は減点には接続しない。
        // =========================================================
        private void DiagnoseObjectBackedBrakeState(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            foreach (
                RuntimeProfileIdentity profile
                in runtimeProfilesByHash.Values
            )
            {
                if (
                    profile.Pattern
                        != "ObjectBackedBrakeOutputSelector"
                    || profile.ModuleBaseAddress == IntPtr.Zero
                )
                {
                    continue;
                }

                IntPtr objectPointerAddress =
                    IntPtr.Add(
                        profile.ModuleBaseAddress,
                        profile.ObjectPointerRva
                    );

                IntPtr objectAddress;

                if (
                    !TryReadRuntimePointer32(
                        objectPointerAddress,
                        out objectAddress
                    )
                )
                {
                    continue;
                }

                int physicalBrake;
                int serviceMaximum;
                int emergency;
                int outputBrake;

                bool physicalRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            objectAddress,
                            profile.PhysicalBrakeOffset
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            objectAddress,
                            profile.ServiceMaximumOffset
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            objectAddress,
                            profile.EmergencyOffset
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.OutputBrakeRva
                        ),
                        out outputBrake
                    );

                if (
                    !physicalRead
                    || !serviceRead
                    || !emergencyRead
                    || !outputRead
                )
                {
                    continue;
                }

                // 明らかに不自然な値はログへ流さない。
                if (
                    physicalBrake < -1
                    || serviceMaximum < 0
                    || emergency < 0
                    || outputBrake < -1
                    || serviceMaximum > 100
                    || emergency > 100
                    || physicalBrake > 100
                    || outputBrake > 100
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile.HasPreviousState
                    || physicalBrake
                        != profile.PreviousPhysicalBrake
                    || serviceMaximum
                        != profile.PreviousServiceMaximum
                    || emergency
                        != profile.PreviousEmergency
                    || outputBrake
                        != profile.PreviousOutputBrake
                    || objectAddress
                        != profile.PreviousObjectAddress;

                if (!stateChanged)
                {
                    continue;
                }

                bool overrideActive =
                    outputBrake > physicalBrake;

                string interventionKind = "None";

                if (overrideActive)
                {
                    if (outputBrake == emergency)
                    {
                        interventionKind = "Emergency";
                    }
                    else if (outputBrake == serviceMaximum)
                    {
                        interventionKind = "ServiceMaximum";
                    }
                    else
                    {
                        interventionKind = "Intermediate";
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[RUNTIME_PROFILE_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"Pattern:{profile.Pattern}, "
                    + $"Object:0x{objectAddress.ToInt64():X}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + $"Override:{overrideActive}, "
                    + $"Kind:{interventionKind}, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousState = true;
                profile.PreviousPhysicalBrake =
                    physicalBrake;
                profile.PreviousServiceMaximum =
                    serviceMaximum;
                profile.PreviousEmergency =
                    emergency;
                profile.PreviousOutputBrake =
                    outputBrake;
                profile.PreviousObjectAddress =
                    objectAddress;

                hasChanges = true;
            }
        }


        public override void Tick(TimeSpan elapsed)
        {
            if (!BveHacker.IsScenarioCreated)
            {
                isLogSessionInitialized = false;
                isAtsStructureDumped = false;
                isBeaconsLoaded = false;

                serviceMaxBrakeNotch = -1;
                emergencyBrakeNotch = -1;

                prevPhysBrake = -1;
                prevAtsBrake = -1;

                prevPhysSrcBrake = int.MinValue;
                prevAtsSrcBrake = int.MinValue;
                prevRawHandleCBrake = int.MinValue;
                prevRawHandleLBrake = int.MinValue;
                prevVehicleStateHandleBrake = int.MinValue;

                hasScannedRuntimeProfiles = false;
                hasLoggedRuntimeProfileError = false;
                runtimeProfilePath = null;
                nextRuntimeProfileScanTime = DateTime.MinValue;

                runtimeProfilesByHash.Clear();
                matchedRuntimeProfileHashes.Clear();

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

                double location =
                    BveHacker.Scenario.VehicleLocation.Location;

                double speed =
                    BveHacker.Scenario.VehicleLocation.Speed * 3.6;

                int bveTimeMs = 0;

                try
                {
                    bveTimeMs = Convert.ToInt32(
                        BveHacker.Scenario
                            .TimeManager
                            .Time
                            .TotalMilliseconds
                    );
                }
                catch
                {
                }

                StringBuilder rtLog = new StringBuilder();
                bool hasChanges = false;


                // =========================================================
                // ① ログセッションと車両ブレーキ段の初期化
                // =========================================================
                if (!isLogSessionInitialized)
                {
                    serviceMaxBrakeNotch = -1;
                    emergencyBrakeNotch = -1;

                    try
                    {
                        object cabObj = vehicle.Instruments?.Cab;

                        if (cabObj != null)
                        {
                            object cabHandles = cabObj.GetType()
                                .GetProperty(
                                    "Handles",
                                    bindFlagsAll
                                )
                                ?.GetValue(cabObj);

                            if (cabHandles != null)
                            {
                                object notchInfo = cabHandles.GetType()
                                    .GetProperty(
                                        "NotchInfo",
                                        bindFlagsAll
                                    )
                                    ?.GetValue(cabHandles);

                                if (notchInfo != null)
                                {
                                    object brakeNotchCount = notchInfo
                                        .GetType()
                                        .GetProperty(
                                            "BrakeNotchCount",
                                            bindFlagsAll
                                        )
                                        ?.GetValue(notchInfo);

                                    if (brakeNotchCount != null)
                                    {
                                        serviceMaxBrakeNotch =
                                            Convert.ToInt32(
                                                brakeNotchCount
                                            );
                                    }
                                }
                            }

                            string[] brakeTexts = cabObj.GetType()
                                .GetProperty(
                                    "BrakeTexts",
                                    bindFlagsAll
                                )
                                ?.GetValue(cabObj)
                                as string[];

                            if (
                                brakeTexts != null
                                && brakeTexts.Length > 0
                            )
                            {
                                emergencyBrakeNotch =
                                    brakeTexts.Length - 1;
                            }
                        }
                    }
                    catch
                    {
                        serviceMaxBrakeNotch = -1;
                        emergencyBrakeNotch = -1;
                    }

                    StringBuilder header = new StringBuilder();

                    header.AppendLine(
                        "=== REALTIME ATS LOG ==="
                    );
                    header.AppendLine(
                        $"常用最大={serviceMaxBrakeNotch}"
                    );
                    header.AppendLine(
                        $"非常={emergencyBrakeNotch}"
                    );
                    header.AppendLine();

                    System.IO.File.WriteAllText(
                        realtimeLogPath,
                        header.ToString()
                    );

                    isLogSessionInitialized = true;
                }

                // =========================================================
                // 2 地上子(Beacon)の取得と通過判定
                // =========================================================
                if (!isBeaconsLoaded)

                    // 共通ランタイムプロファイルを診断する。
                    // カタログは1回だけ読み込み、DLLは1秒間隔で再走査する。
                    DiagnoseRuntimeProfiles(
                        rtLog,
                        ref hasChanges
                    );
                // MATCH済みのオブジェクト保持型プロファイルについて、
                // 実メモリ値を変化時だけ記録する。
                DiagnoseObjectBackedBrakeState(
                    rtLog,
                    ref hasChanges
                );

                // 後続のATS内部監視で例外が発生しても診断結果が
                // 消失しないよう、この時点で診断ログを書き出す。
                if (hasChanges && rtLog.Length > 0)
                {
                    System.IO.File.AppendAllText(
                        realtimeLogPath,
                        rtLog.ToString()
                    );

                    rtLog.Clear();
                    hasChanges = false;
                }

                {
                    try
                    {
                        object beaconsObj = map.GetType().GetProperty("Beacons", bindFlagsAll)?.GetValue(map);
                        if (beaconsObj is System.Collections.IEnumerable enumBeacons)
                        {
                            foreach (object b in enumBeacons) beaconList.Add(b);
                        }
                        isBeaconsLoaded = true;

                        // 読み込んだ地上子数を通常ログへ記録
                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + $"BEACONS_LOADED "
                            + $"Count:{beaconList.Count}"
                        );

                        hasChanges = true;
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
                            rtLog.AppendLine(
                                $"[{DateTime.Now:HH:mm:ss.fff}] "
                                + $"[BveTime:{bveTimeMs}] "
                                + $"[Loc:{bLoc:F3}] "
                                + $"[Spd:{speed:F1}] "
                                + $"BEACON "
                                + $"Type:{type}, "
                                + $"Data:{data}"
                            );
                            hasChanges = true;
                        }
                    }
                }
                lastLocation = location;

                // =========================================================
                // ③ ATSプラグイン情報の取得
                // =========================================================
                object atsPlugin =
                    vehicle.Instruments?.AtsPlugin;

                if (
                    atsPlugin == null
                    && !isAtsStructureDumped
                )
                {
                    System.IO.File.AppendAllText(
                        realtimeLogPath,
                        "[ATS DUMP] AtsPlugin is NULL\r\n"
                    );
                    

                    isAtsStructureDumped = true;
                }


                // ATSプラグイン直下のプロパティとフィールドを
                // シナリオごとに1回だけログへ出力する。
                if (
                    atsPlugin != null
                    && !isAtsStructureDumped
                )
                {
                    try
                    {
                        System.IO.File.AppendAllText(
                            realtimeLogPath,
                            "[ATS DUMP] START\r\n"
                        );

                        DumpObjectMembers(
                            atsPlugin,
                            "AtsPlugin",
                            bindFlagsAll
                        );

                        // =========================================================
                        // AtsPluginの内部実体
                        // =========================================================
                        object atsPluginSrc = atsPlugin.GetType()
                            .GetProperty(
                                "Src",
                                bindFlagsAll
                            )
                            ?.GetValue(atsPlugin);

                        DumpObjectMembers(
                            atsPluginSrc,
                            "AtsPlugin.Src",
                            bindFlagsAll
                        );
                        // =========================================================
                        // AtsPlugin.Src内部の主要オブジェクト g から k
                        // それぞれ直接のプロパティとフィールドだけを調べる
                        // =========================================================
                        if (atsPluginSrc != null)
                        {
                            string[] candidateFieldNames =
                            {
                                "g",
                                "h",
                                "i",
                                "j",
                                "k",
                                "m",
                                "n",
                                "u",
                                "x"
                            };

                            foreach (string candidateFieldName in candidateFieldNames)
                            {
                                object candidateObject = atsPluginSrc.GetType()
                                    .GetField(
                                        candidateFieldName,
                                        bindFlagsAll
                                    )
                                    ?.GetValue(atsPluginSrc);

                                DumpObjectMembers(
                                    candidateObject,
                                    $"AtsPlugin.Src.{candidateFieldName}",
                                    bindFlagsAll
                                );
                            }
                        }
                        // =========================================================
                        // ATSプラグイン本体らしきデリゲートTargetを調べる
                        // =========================================================
                        object atsDelegate = null;
                        object atsPluginTarget = null;

                        if (atsPluginSrc != null)
                        {
                            atsDelegate = atsPluginSrc.GetType()
                                .GetField(
                                    "m",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPluginSrc);
                        }

                        if (atsDelegate != null)
                        {
                            atsPluginTarget = atsDelegate.GetType()
                                .GetProperty(
                                    "Target",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsDelegate);
                        }

                        DumpObjectMembers(
                            atsPluginTarget,
                            "AtsPlugin.DelegateTarget",
                            bindFlagsAll
                        );

                        StringBuilder delegateTargetLog = new StringBuilder();

                        delegateTargetLog.AppendLine();
                        delegateTargetLog.AppendLine(
                            "=== DELEGATE TARGET IDENTITY ==="
                        );

                        string[] delegateFieldNames =
                        {
    "m",
    "n",
    "u",
    "x"
};

                        foreach (string delegateFieldName in delegateFieldNames)
                        {
                            object delegateObject = null;
                            object delegateTarget = null;

                            if (atsPluginSrc != null)
                            {
                                delegateObject = atsPluginSrc.GetType()
                                    .GetField(
                                        delegateFieldName,
                                        bindFlagsAll
                                    )
                                    ?.GetValue(atsPluginSrc);
                            }

                            if (delegateObject != null)
                            {
                                delegateTarget = delegateObject.GetType()
                                    .GetProperty(
                                        "Target",
                                        bindFlagsAll
                                    )
                                    ?.GetValue(delegateObject);
                            }

                            delegateTargetLog.AppendLine(
                                $"Src.{delegateFieldName}.Target="
                                + GetObjectIdentity(delegateTarget)
                            );

                            delegateTargetLog.AppendLine(
                                $"Src.{delegateFieldName}.Target == Src.m.Target: "
                                + Object.ReferenceEquals(
                                    delegateTarget,
                                    atsPluginTarget
                                )
                            );
                        }

                        delegateTargetLog.AppendLine(
                            "=== END DELEGATE TARGET IDENTITY ==="
                        );
                        delegateTargetLog.AppendLine();

                        System.IO.File.AppendAllText(
    realtimeLogPath,
    delegateTargetLog.ToString()
);

                        // =========================================================
                        // 各ATSデリゲートのメソッドシグネチャを調べる
                        // =========================================================
                        if (atsPluginSrc != null)
                        {
                            string[] delegateInfoFieldNames =
                            {
        "m",
        "n",
        "o",
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x"
    };

                            foreach (
                                string delegateInfoFieldName
                                in delegateInfoFieldNames
                            )
                            {
                                object delegateInfoObject =
                                    atsPluginSrc.GetType()
                                        .GetField(
                                            delegateInfoFieldName,
                                            bindFlagsAll
                                        )
                                        ?.GetValue(atsPluginSrc);

                                DumpDelegateInfo(
                                    delegateInfoObject,
                                    $"AtsPlugin.Src.{delegateInfoFieldName}",
                                    bindFlagsAll
                                );
                            }
                        }

                        // =========================================================
                        // Src.nの入力型dxと戻り値型ddの構造を調べる
                        // =========================================================
                        object elapseDelegate = null;
                        System.Reflection.MethodInfo elapseMethod = null;

                        if (atsPluginSrc != null)
                        {
                            elapseDelegate = atsPluginSrc.GetType()
                                .GetField(
                                    "n",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPluginSrc);
                        }

                        if (elapseDelegate != null)
                        {
                            elapseMethod = elapseDelegate.GetType()
                                .GetProperty(
                                    "Method",
                                    bindFlagsAll
                                )
                                ?.GetValue(elapseDelegate)
                                as System.Reflection.MethodInfo;
                        }

                        if (elapseMethod != null)
                        {
                            DumpTypeDefinition(
                                elapseMethod.ReturnType,
                                "AtsPlugin.Src.n.ReturnType",
                                bindFlagsAll
                            );

                            System.Reflection.ParameterInfo[] elapseParameters =
                                elapseMethod.GetParameters();

                            if (elapseParameters.Length > 0)
                            {
                                DumpTypeDefinition(
                                    elapseParameters[0].ParameterType,
                                    "AtsPlugin.Src.n.Parameter0",
                                    bindFlagsAll
                                );
                            }

                            if (elapseParameters.Length > 1)
                            {
                                DumpTypeDefinition(
                                    elapseParameters[1].ParameterType,
                                    "AtsPlugin.Src.n.Parameter1",
                                    bindFlagsAll
                                );
                            }

                            if (elapseParameters.Length > 2)
                            {
                                DumpTypeDefinition(
                                    elapseParameters[2].ParameterType,
                                    "AtsPlugin.Src.n.Parameter2",
                                    bindFlagsAll
                                );
                            }
                        }

                        // =========================================================
                        // 公開されている物理ハンドル側
                        // =========================================================
                        object physicalHandlesForDump =
                            atsPlugin.GetType()
                                .GetProperty(
                                    "Handles",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPlugin);

                        DumpObjectMembers(
                            physicalHandlesForDump,
                            "AtsPlugin.Handles",
                            bindFlagsAll
                        );

                        object physicalHandlesSrcForDump = null;

                        if (physicalHandlesForDump != null)
                        {
                            physicalHandlesSrcForDump =
                                physicalHandlesForDump.GetType()
                                    .GetProperty(
                                        "Src",
                                        bindFlagsAll
                                    )
                                    ?.GetValue(physicalHandlesForDump);
                        }

                        DumpObjectMembers(
                            physicalHandlesSrcForDump,
                            "AtsPlugin.Handles.Src",
                            bindFlagsAll
                        );

                        // =========================================================
                        // 公開されているATSハンドル側
                        // =========================================================
                        object atsHandlesForDump =
                            atsPlugin.GetType()
                                .GetProperty(
                                    "AtsHandles",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPlugin);

                        DumpObjectMembers(
                            atsHandlesForDump,
                            "AtsPlugin.AtsHandles",
                            bindFlagsAll
                        );

                        object atsHandlesSrcForDump = null;

                        if (atsHandlesForDump != null)
                        {
                            atsHandlesSrcForDump =
                                atsHandlesForDump.GetType()
                                    .GetProperty(
                                        "Src",
                                        bindFlagsAll
                                    )
                                    ?.GetValue(atsHandlesForDump);
                        }

                        DumpObjectMembers(
                            atsHandlesSrcForDump,
                            "AtsPlugin.AtsHandles.Src",
                            bindFlagsAll
                        );

                        // =========================================================
                        // AtsPlugin.Src内にある2つのa2フィールド
                        // =========================================================
                        object rawHandleC = null;
                        object rawHandleL = null;

                        if (atsPluginSrc != null)
                        {
                            rawHandleC = atsPluginSrc.GetType()
                                .GetField(
                                    "c",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPluginSrc);

                            rawHandleL = atsPluginSrc.GetType()
                                .GetField(
                                    "l",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPluginSrc);
                        }

                        // =========================================================
                        // AtsPlugin.Src.i内部のa2型フィールドaを取得
                        // =========================================================
                        object vehicleStateObject = null;
                        object vehicleStateHandle = null;

                        if (atsPluginSrc != null)
                        {
                            vehicleStateObject = atsPluginSrc.GetType()
                                .GetField(
                                    "i",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsPluginSrc);
                        }

                        if (vehicleStateObject != null)
                        {
                            vehicleStateHandle = vehicleStateObject.GetType()
                                .GetField(
                                    "a",
                                    bindFlagsAll
                                )
                                ?.GetValue(vehicleStateObject);
                        }

                        DumpObjectMembers(
                            vehicleStateHandle,
                            "AtsPlugin.Src.i.a",
                            bindFlagsAll
                        );

                        DumpObjectMembers(
                            rawHandleC,
                            "AtsPlugin.Src.c",
                            bindFlagsAll
                        );

                        DumpObjectMembers(
                            rawHandleL,
                            "AtsPlugin.Src.l",
                            bindFlagsAll
                        );

                        // =========================================================
                        // オブジェクトの対応関係を記録
                        // =========================================================
                        StringBuilder identityLog =
                            new StringBuilder();

                        identityLog.AppendLine();
                        identityLog.AppendLine(
                            "=== HANDLE OBJECT IDENTITY ==="
                        );

                        identityLog.AppendLine(
                            $"Handles.Src={GetObjectIdentity(physicalHandlesSrcForDump)}"
                        );

                        identityLog.AppendLine(
                            $"AtsHandles.Src={GetObjectIdentity(atsHandlesSrcForDump)}"
                        );

                        identityLog.AppendLine(
                            $"Src.c={GetObjectIdentity(rawHandleC)}"
                        );

                        identityLog.AppendLine(
                            $"Src.l={GetObjectIdentity(rawHandleL)}"
                        );

                        identityLog.AppendLine(
                            $"Src.i.a={GetObjectIdentity(vehicleStateHandle)}"
                        );

                        identityLog.AppendLine(
                            $"Src.i.a == Src.c: "
                            + $"{Object.ReferenceEquals(vehicleStateHandle, rawHandleC)}"
                        );

                        identityLog.AppendLine(
                            $"Src.i.a == Src.l: "
                            + $"{Object.ReferenceEquals(vehicleStateHandle, rawHandleL)}"
                        );

                        identityLog.AppendLine(
                            $"Src.i.a == Handles.Src: "
                            + $"{Object.ReferenceEquals(vehicleStateHandle, physicalHandlesSrcForDump)}"
                        );

                        identityLog.AppendLine(
                            $"Src.i.a == AtsHandles.Src: "
                            + $"{Object.ReferenceEquals(vehicleStateHandle, atsHandlesSrcForDump)}"
                        );

                        identityLog.AppendLine(
                            $"Handles.Src == Src.c: "
                            + $"{Object.ReferenceEquals(physicalHandlesSrcForDump, rawHandleC)}"
                        );

                        identityLog.AppendLine(
                            $"Handles.Src == Src.l: "
                            + $"{Object.ReferenceEquals(physicalHandlesSrcForDump, rawHandleL)}"
                        );

                        identityLog.AppendLine(
                            $"AtsHandles.Src == Src.c: "
                            + $"{Object.ReferenceEquals(atsHandlesSrcForDump, rawHandleC)}"
                        );

                        identityLog.AppendLine(
                            $"AtsHandles.Src == Src.l: "
                            + $"{Object.ReferenceEquals(atsHandlesSrcForDump, rawHandleL)}"
                        );

                        identityLog.AppendLine(
                            $"Handles.Src == AtsHandles.Src: "
                            + $"{Object.ReferenceEquals(physicalHandlesSrcForDump, atsHandlesSrcForDump)}"
                        );

                        identityLog.AppendLine(
                            "=== END HANDLE OBJECT IDENTITY ==="
                        );

                        identityLog.AppendLine();

                        System.IO.File.AppendAllText(
                            realtimeLogPath,
                            identityLog.ToString()
                        );

                        // 毎フレーム同じダンプを書き続けない。
                        isAtsStructureDumped = true;
                    }
                    catch (Exception ex)
                    {
                        System.IO.File.AppendAllText(
                            realtimeLogPath,
                            "[ATS DUMP] ERROR\r\n"
                            + ex.ToString()
                            + "\r\n"
                        );

                        // 毎フレーム同じエラーを書き続けない。
                        isAtsStructureDumped = true;
                    }
                }

                if (atsPlugin != null)
                {
                    // パネルとサウンドをプロパティから取得する。
                    int[] currentSound = (
                        int[]
                    )atsPlugin.GetType()
                        .GetProperty(
                            "SoundArray",
                            bindFlagsAll
                        )
                        ?.GetValue(atsPlugin);

                    int[] currentPanel = (
                        int[]
                    )atsPlugin.GetType()
                        .GetProperty(
                            "PanelArray",
                            bindFlagsAll
                        )
                        ?.GetValue(atsPlugin);

                    if (currentSound != null)
                    {
                        int soundCount = Math.Min(
                            currentSound.Length,
                            prevSound.Length
                        );

                        for (int i = 0; i < soundCount; i++)
                        {
                            if (
                                currentSound[i]
                                != prevSound[i]
                            )
                            {
                                rtLog.AppendLine(
                                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                                    + $"[BveTime:{bveTimeMs}] "
                                    + $"[Loc:{location:F3}] "
                                    + $"[Spd:{speed:F1}] "
                                    + $"Sound[{i}] changed: "
                                    + $"{prevSound[i]} "
                                    + $"-> {currentSound[i]}"
                                );

                                prevSound[i] =
                                    currentSound[i];

                                hasChanges = true;
                            }
                        }
                    }

                    if (currentPanel != null)
                    {
                        int panelCount = Math.Min(
                            currentPanel.Length,
                            prevPanel.Length
                        );

                        for (int i = 0; i < panelCount; i++)
                        {
                            if (
                                currentPanel[i]
                                != prevPanel[i]
                            )
                            {
                                rtLog.AppendLine(
                                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                                    + $"[BveTime:{bveTimeMs}] "
                                    + $"[Loc:{location:F3}] "
                                    + $"[Spd:{speed:F1}] "
                                    + $"Panel[{i}] changed: "
                                    + $"{prevPanel[i]} "
                                    + $"-> {currentPanel[i]}"
                                );

                                prevPanel[i] =
                                    currentPanel[i];

                                hasChanges = true;
                            }
                        }
                    }

                    // =========================================================
                    // ④ 物理ハンドル段と保安装置側ブレーキ段の監視
                    // =========================================================
                    object physHandles = atsPlugin.GetType()
                        .GetProperty(
                            "Handles",
                            bindFlagsAll
                        )
                        ?.GetValue(atsPlugin);

                    object atsHandles = atsPlugin.GetType()
                        .GetProperty(
                            "AtsHandles",
                            bindFlagsAll
                        )
                        ?.GetValue(atsPlugin);

                    int physBrake = 0;
                    int atsBrake = 0;

                    if (physHandles != null)
                    {
                        object physBrakeValue =
                            physHandles.GetType()
                                .GetProperty(
                                    "BrakeNotch",
                                    bindFlagsAll
                                )
                                ?.GetValue(physHandles);

                        if (physBrakeValue != null)
                        {
                            physBrake = Convert.ToInt32(
                                physBrakeValue
                            );
                        }
                    }

                    if (atsHandles != null)
                    {
                        object atsBrakeValue =
                            atsHandles.GetType()
                                .GetProperty(
                                    "BrakeNotch",
                                    bindFlagsAll
                                )
                                ?.GetValue(atsHandles);

                        if (atsBrakeValue != null)
                        {
                            atsBrake = Convert.ToInt32(
                                atsBrakeValue
                            );
                        }
                    }

                    // =========================================================
                    // HandleSet内部のa2オブジェクトを取得
                    // =========================================================
                    object physHandlesSrc = null;
                    object atsHandlesSrc = null;

                    if (physHandles != null)
                    {
                        physHandlesSrc = physHandles.GetType()
                            .GetProperty(
                                "Src",
                                bindFlagsAll
                            )
                            ?.GetValue(physHandles);
                    }

                    if (atsHandles != null)
                    {
                        atsHandlesSrc = atsHandles.GetType()
                            .GetProperty(
                                "Src",
                                bindFlagsAll
                            )
                            ?.GetValue(atsHandles);
                    }

                    // =========================================================
                    // AtsPlugin.Src.cおよびAtsPlugin.Src.lを取得
                    // =========================================================
                    object atsPluginSrcDynamic = atsPlugin.GetType()
                        .GetProperty(
                            "Src",
                            bindFlagsAll
                        )
                        ?.GetValue(atsPlugin);
                    object vehicleStateObjectDynamic = null;
                    object vehicleStateHandleDynamic = null;

                    if (atsPluginSrcDynamic != null)
                    {
                        vehicleStateObjectDynamic = atsPluginSrcDynamic.GetType()
                            .GetField(
                                "i",
                                bindFlagsAll
                            )
                            ?.GetValue(atsPluginSrcDynamic);
                    }

                    if (vehicleStateObjectDynamic != null)
                    {
                        vehicleStateHandleDynamic = vehicleStateObjectDynamic.GetType()
                            .GetField(
                                "a",
                                bindFlagsAll
                            )
                            ?.GetValue(vehicleStateObjectDynamic);
                    }

                    object rawHandleCDynamic = null;
                    object rawHandleLDynamic = null;

                    if (atsPluginSrcDynamic != null)
                    {
                        rawHandleCDynamic = atsPluginSrcDynamic.GetType()
                            .GetField(
                                "c",
                                bindFlagsAll
                            )
                            ?.GetValue(atsPluginSrcDynamic);

                        rawHandleLDynamic = atsPluginSrcDynamic.GetType()
                            .GetField(
                                "l",
                                bindFlagsAll
                            )
                            ?.GetValue(atsPluginSrcDynamic);
                    }

                    // =========================================================
                    // 各a2オブジェクトのフィールドbを読み取る
                    // =========================================================
                    int physSrcBrake = 0;
                    int atsSrcBrake = 0;
                    int rawHandleCBrake = 0;
                    int rawHandleLBrake = 0;
                    int vehicleStateHandleBrake = 0;

                    bool hasPhysSrcBrake = TryGetIntField(
                        physHandlesSrc,
                        "b",
                        bindFlagsAll,
                        out physSrcBrake
                    );

                    bool hasAtsSrcBrake = TryGetIntField(
                        atsHandlesSrc,
                        "b",
                        bindFlagsAll,
                        out atsSrcBrake
                    );

                    bool hasRawHandleCBrake = TryGetIntField(
                        rawHandleCDynamic,
                        "b",
                        bindFlagsAll,
                        out rawHandleCBrake
                    );

                    bool hasRawHandleLBrake = TryGetIntField(
                        rawHandleLDynamic,
                        "b",
                        bindFlagsAll,
                        out rawHandleLBrake
                    );
                    bool hasVehicleStateHandleBrake = TryGetIntField(
                        vehicleStateHandleDynamic,
                        "b",
                        bindFlagsAll,
                        out vehicleStateHandleBrake
                    );

                    // =========================================================
                    // いずれかのブレーキ値が変化した場合だけ記録
                    // =========================================================
                    bool brakeStateChanged =
                    physBrake != prevPhysBrake
                    || atsBrake != prevAtsBrake
                    || (
                        hasPhysSrcBrake
                        && physSrcBrake != prevPhysSrcBrake
                    )
                    || (
                        hasAtsSrcBrake
                        && atsSrcBrake != prevAtsSrcBrake
                    )
                    || (
                        hasRawHandleCBrake
                        && rawHandleCBrake != prevRawHandleCBrake
                    )
                    || (
                        hasRawHandleLBrake
                        && rawHandleLBrake != prevRawHandleLBrake
                    )
                    || (
                        hasVehicleStateHandleBrake
                        && vehicleStateHandleBrake
                            != prevVehicleStateHandleBrake
                    );

                    if (brakeStateChanged)
                    {
                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + $"[BveTime:{bveTimeMs}] "
                            + $"[Loc:{location:F3}] "
                            + $"[Spd:{speed:F1}] "
                            + $"BRAKE_INTERNAL "
                            + $"Physical:{physBrake}, "
                            + $"PhysicalSrc.b:"
                            + $"{(hasPhysSrcBrake ? physSrcBrake.ToString() : "<ERR>")}, "
                            + $"Src.c.b:"
                            + $"{(hasRawHandleCBrake ? rawHandleCBrake.ToString() : "<ERR>")}, "
                            + $"ATS:{atsBrake}, "
                            + $"AtsSrc.b:"
                            + $"{(hasAtsSrcBrake ? atsSrcBrake.ToString() : "<ERR>")}, "
                            + $"Src.l.b:"
                            + $"{(hasRawHandleLBrake ? rawHandleLBrake.ToString() : "<ERR>")}, "
                            + $"Src.i.a.b:"
                            + $"{(hasVehicleStateHandleBrake ? vehicleStateHandleBrake.ToString() : "<ERR>")}"
                        );

                        prevPhysBrake = physBrake;
                        prevAtsBrake = atsBrake;

                        if (hasPhysSrcBrake)
                        {
                            prevPhysSrcBrake = physSrcBrake;
                        }

                        if (hasAtsSrcBrake)
                        {
                            prevAtsSrcBrake = atsSrcBrake;
                        }

                        if (hasRawHandleCBrake)
                        {
                            prevRawHandleCBrake = rawHandleCBrake;
                        }

                        if (hasRawHandleLBrake)
                        {
                            prevRawHandleLBrake = rawHandleLBrake;
                        }

                        if (hasVehicleStateHandleBrake)
                        {
                            prevVehicleStateHandleBrake =
                                vehicleStateHandleBrake;
                        }

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