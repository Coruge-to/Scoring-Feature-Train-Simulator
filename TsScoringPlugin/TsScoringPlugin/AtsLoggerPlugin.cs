using BveEx.PluginHost;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
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

        // BveEx VehiclePluginsの構造診断
        private bool hasDumpedVehiclePlugins = false;
        private bool hasLoggedVehiclePluginsError = false;

        // AppDomain内のAtsPT5アセンブリ診断
        private bool hasDumpedAtsPtAppDomain = false;
        private bool hasLoggedAtsPtAppDomainError = false;

        // BveExホスト参照の診断
        private bool hasDumpedBveExHostReferences = false;
        private bool hasLoggedBveExHostReferenceError = false;

        // ExtensionSet内部構造の診断
        private bool hasDumpedExtensionSet = false;
        private bool hasLoggedExtensionSetError = false;

        // BveEx側の静的プラグイン管理参照の診断
        private bool hasDumpedBveExStaticPluginHosts = false;
        private bool hasLoggedBveExStaticPluginHostError = false;

        // BveEx.PluginHost.App.Instance内部の診断
        private bool hasDumpedPluginHostApp = false;
        private bool hasLoggedPluginHostAppError = false;

        // BveHackerイベント購読先の診断
        private bool hasDumpedBveHackerEventTargets = false;
        private bool hasLoggedBveHackerEventTargetError = false;
        // =========================================================
        // .NET管理オブジェクト型プロファイルの診断状態
        // =========================================================
        private readonly List<ManagedRuntimeProfile>
            managedRuntimeProfiles =
                new List<ManagedRuntimeProfile>();

        private readonly Dictionary<string, ManagedRuntimeResolution>
            managedRuntimeResolutions =
                new Dictionary<string, ManagedRuntimeResolution>(
                    StringComparer.OrdinalIgnoreCase
                );

        private bool hasInitializedManagedRuntimeProfiles = false;
        private DateTime nextManagedRuntimeResolveTime = DateTime.MinValue;
        private bool hasLoggedManagedRuntimeResolverError = false;
        // 中央西線系AtsPT5はMANAGED_RUNTIMEを単独の正式経路とする。
        private bool hasPreviousManagedPrimaryState = false;
        private string previousManagedPrimaryRequestKind = "Unknown";
        private int previousManagedPrimaryRequestBrake = int.MinValue;
        private int previousManagedPrimaryPhysicalBrake = int.MinValue;
        private int previousManagedPrimaryAtsBrake = int.MinValue;
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
        // SHA-256の計算が完了したDLLパス。
        // 同じDLLファイルを1秒ごとに再ハッシュしない。
        private HashSet<string> inspectedRuntimeModulePaths =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase
            );

        private Dictionary<string, RuntimeProfileIdentity>
            runtimeProfilesByHash =
                new Dictionary<string, RuntimeProfileIdentity>(
                    StringComparer.OrdinalIgnoreCase
                );
        [DataContract]
        private sealed class RuntimeProfileCatalog
        {
            [DataMember(Name = "schemaVersion")]
            public int SchemaVersion { get; set; }


            [DataMember(Name = "profileCount")]
            public int ProfileCount { get; set; }

            [DataMember(Name = "profiles")]
            public List<RuntimeProfileCatalogEntry> Profiles { get; set; }
        }

        [DataContract]
        private sealed class RuntimeProfileCatalogEntry
        {
            [DataMember(Name = "sha256")]
            public string Sha256 { get; set; }

            [DataMember(Name = "pattern")]
            public string Pattern { get; set; }

            [DataMember(Name = "verificationStatus")]
            public string VerificationStatus { get; set; }

            [DataMember(Name = "addresses")]
            public RuntimeProfileCatalogAddresses Addresses { get; set; }

            [DataMember(Name = "detection")]
            public RuntimeProfileCatalogDetection Detection { get; set; }
        }

        [DataContract]
        private sealed class RuntimeProfileCatalogAddresses
        {
            [DataMember(Name = "physicalBrake")]
            public RuntimeProfileCatalogAddress PhysicalBrake { get; set; }

            [DataMember(Name = "serviceMaximum")]
            public RuntimeProfileCatalogAddress ServiceMaximum { get; set; }

            [DataMember(Name = "emergency")]
            public RuntimeProfileCatalogAddress Emergency { get; set; }

            [DataMember(Name = "outputBrake")]
            public RuntimeProfileCatalogAddress OutputBrake { get; set; }

            [DataMember(Name = "serviceMaximumRequestFlags")]
            public List<RuntimeProfileCatalogAddress>
                ServiceMaximumRequestFlags
            { get; set; }

            [DataMember(Name = "emergencyRequestFlags")]
            public List<RuntimeProfileCatalogAddress>
                EmergencyRequestFlags
            { get; set; }

            [DataMember(Name = "metroEmergencySelectionFlag")]
            public RuntimeProfileCatalogAddress
                MetroEmergencySelectionFlag
            { get; set; }

            [DataMember(Name = "metroLevel7SelectionFlag")]
            public RuntimeProfileCatalogAddress
                MetroLevel7SelectionFlag
            { get; set; }

            [DataMember(Name = "metroLevel4SelectionFlag")]
            public RuntimeProfileCatalogAddress
                MetroLevel4SelectionFlag
            { get; set; }

            [DataMember(Name = "metroControlMode")]
            public RuntimeProfileCatalogAddress
                MetroControlMode
            { get; set; }

            [DataMember(Name = "metroInternalState")]
            public RuntimeProfileCatalogAddress
                MetroInternalState
            { get; set; }
            [DataMember(Name = "metroSafetyEmergencySource")]
            public RuntimeProfileCatalogAddress
    MetroSafetyEmergencySource
            { get; set; }
            [DataMember(Name = "kintetsuAbsoluteStopEmergencyLatch")]
            public RuntimeProfileCatalogAddress
    KintetsuAbsoluteStopEmergencyLatch
            { get; set; }

            [DataMember(Name = "kintetsuSecondaryEmergencySource")]
            public RuntimeProfileCatalogAddress
                KintetsuSecondaryEmergencySource
            { get; set; }
            [DataMember(Name = "kintetsuEmergencySourceA")]
            public RuntimeProfileCatalogAddress
    KintetsuEmergencySourceA
            { get; set; }

            [DataMember(Name = "kintetsuEmergencySourceB")]
            public RuntimeProfileCatalogAddress
                KintetsuEmergencySourceB
            { get; set; }

            [DataMember(Name = "kintetsuServiceMaximumSourceA")]
            public RuntimeProfileCatalogAddress
                KintetsuServiceMaximumSourceA
            { get; set; }

            [DataMember(Name = "kintetsuServiceMaximumSourceB")]
            public RuntimeProfileCatalogAddress
                KintetsuServiceMaximumSourceB
            { get; set; }

        }

        [DataContract]
        private sealed class RuntimeProfileCatalogAddress
        {
            [DataMember(Name = "kind")]
            public string Kind { get; set; }

            [DataMember(Name = "rva")]
            public string Rva { get; set; }

            [DataMember(Name = "valueType")]
            public string ValueType { get; set; }
        }

        [DataContract]
        private sealed class RuntimeProfileCatalogDetection
        {
            [DataMember(Name = "strategy")]
            public string Strategy { get; set; }

            [DataMember(Name = "activeCondition")]
            public string ActiveCondition { get; set; }

            [DataMember(Name = "priority")]
            public string Priority { get; set; }

            [DataMember(Name = "completionStatus")]
            public string CompletionStatus { get; set; }

            [DataMember(Name = "safetyEmergencySourceVerificationStatus")]
            public string SafetyEmergencySourceVerificationStatus
            { get; set; }
        }
        private sealed class ManagedRuntimeProfile
        {
            public string Id;
            public List<string> Sha256Values = new List<string>();

            public string ResolverStrategy;
            public string EventFieldName;
            public string TargetTypeName;

            public List<ManagedRuntimePathStep> ObjectPath =
                new List<ManagedRuntimePathStep>();

            public Dictionary<string, ManagedRuntimeMemberDefinition>
                Members =
                    new Dictionary<string, ManagedRuntimeMemberDefinition>(
                        StringComparer.Ordinal
                    );
        }

        private sealed class ManagedRuntimePathStep
        {
            public string FieldName;
            public string ExpectedTypeName;
        }

        private sealed class ManagedRuntimeMemberDefinition
        {
            public string OwnerName;
            public string FieldName;
            public string ValueTypeName;
            public string SemanticRole;
        }

        private sealed class ManagedRuntimeResolution
        {
            public ManagedRuntimeProfile Profile;
            public string MatchedSha256;

            public object TargetObject;

            public Dictionary<string, object> NamedObjects =
                new Dictionary<string, object>(
                    StringComparer.Ordinal
                );

            public Dictionary<string, System.Reflection.FieldInfo>
                ResolvedFields =
                    new Dictionary<string, System.Reflection.FieldInfo>(
                        StringComparer.Ordinal
                    );

            public Dictionary<string, object> PreviousValues =
                new Dictionary<string, object>(
                    StringComparer.Ordinal
                );

            public bool HasLoggedResolved;
            public bool HasLoggedStructureError;
            public bool HasValidatedMembers;
            public bool HasLoggedInitialState;

            public bool HasCurrentRequestBrake;
            public int CurrentRequestBrake;

            public bool HasCurrentEmergencyState;
            public bool CurrentEmergencyState;

            public bool HasCurrentSecurityEmergencyState;
            public bool CurrentSecurityEmergencyState;


            public string CurrentRequestKind = "Unknown";
            public int CurrentRequestBrakeCandidate = 0;
        }
        private sealed class RuntimeProfileIdentity
        {
            public string Sha256;
            public string Pattern;
            public string VerificationStatus;

            public string DetectionStrategy;
            public string DetectionPriority;
            public string DetectionCompletionStatus;
            public string SafetyEmergencySourceVerificationStatus;

            public List<int> ServiceMaximumRequestFlagRvas =
                new List<int>();

            public List<int> EmergencyRequestFlagRvas =
                new List<int>();

            // 一致したモジュールの実行時情報
            public string FileName;
            public IntPtr ModuleBaseAddress;

            // ObjectBackedBrakeOutputSelector用の静的配置
            public int ObjectPointerRva;
            public int PhysicalBrakeOffset;
            public int ServiceMaximumOffset;
            public int EmergencyOffset;
            public int OutputBrakeRva;

            // ThreeStateBrakeIntervention用の静的配置
            public int InterventionModeRva;
            public int NoneModeValue;
            public int ServiceMaximumModeValue;
            public int EmergencyModeValue;
            // PhysicalServiceEmergencyOutputComparison用の静的配置
            public int DirectPhysicalBrakeRva;
            public int DirectServiceMaximumRva;
            public int DirectEmergencyRva;
            public int DirectOutputBrakeRva;

            // 阪急ATSの非常要求統合出口を診断する静的配置
            public int HankyuInputBrakeRva;
            public int HankyuOutputBrakeRva;
            public int HankyuRequestActiveRva;
            public int HankyuRequestedBrakeRva;
            public bool HasPreviousHankyuRequestState;
            public int PreviousHankyuInputBrake;
            public int PreviousHankyuOutputBrake;
            public int PreviousHankyuRequestActive;
            public int PreviousHankyuRequestedBrake;
            // 南海ATS-Nの非常要求を診断する静的配置
            public int NankaiNEmergencyFlagRva;
            public bool HasPreviousNankaiNEmergencyState;
            public byte PreviousNankaiNEmergencyRequested;
            // 南海ATS-PNの集約済み要求状態を診断する静的配置
            public int NankaiPnRequestStatePointerRva;
            public int NankaiPnServiceMaximumOffset;
            public int NankaiPnEmergencyOffset;
            public bool HasPreviousNankaiPnRequestState;
            public byte PreviousNankaiPnServiceMaximumRequested;
            public byte PreviousNankaiPnEmergencyRequested;
            // NNN式C-ATSのcats2.dll内部要求状態
            public int NnnCatsDriverBrakeRva;
            public int NnnCatsEmergencyNotchRva;
            public int NnnCatsReturnedBrakeRva;
            public int NnnCatsSafetyFlagRva;
            public int NnnCatsMainStateRva;
            public int NnnCatsRequestStatePointerRva;
            public int NnnCatsMode0RequestStateRva;
            public int NnnCatsMode1RequestStateRva;
            public bool HasPreviousNnnCatsRequestState;
            public int PreviousNnnCatsDriverBrake;
            public int PreviousNnnCatsEmergencyNotch;
            public int PreviousNnnCatsReturnedBrake;
            public byte PreviousNnnCatsSafetyFlag;
            public int PreviousNnnCatsMainState;
            public long PreviousNnnCatsRequestStateAddress;
            public int PreviousNnnCatsSelectedRequestState;
            public int PreviousNnnCatsMode0RequestState;
            public int PreviousNnnCatsMode1RequestState;
            // 南海旧系統ATS-PNの直接配置された内部要求状態
            public int NankaiLegacyPnServiceSourceARva;
            public int NankaiLegacyPnServiceSourceBRva;
            public int NankaiLegacyPnServiceSourceCRva;
            public int NankaiLegacyPnEmergencyFlagRva;
            public bool HasPreviousNankaiLegacyPnRequestState;
            public int PreviousNankaiLegacyPnServiceSourceA;
            public int PreviousNankaiLegacyPnServiceSourceB;
            public int PreviousNankaiLegacyPnServiceSourceC;
            public byte PreviousNankaiLegacyPnEmergencyRequested;
            // ExplicitMetroBrakeRequestState用の静的配置
            public int MetroEmergencySelectionFlagRva;
            public int MetroLevel7SelectionFlagRva;
            public int MetroLevel4SelectionFlagRva;
            public int MetroControlModeRva;
            public int MetroInternalStateRva;
            public int MetroSafetyEmergencySourceRva;
            // 近鉄系ATSの非常要求候補
            public int KintetsuAbsoluteStopEmergencyLatchRva;
            public int KintetsuSecondaryEmergencySourceRva;
            // 近鉄大阪線向け旧版の非常・常用最大要求候補
            public int KintetsuEmergencySourceARva;
            public int KintetsuEmergencySourceBRva;
            public int KintetsuServiceMaximumSourceARva;
            public int KintetsuServiceMaximumSourceBRva;

            // 上記4候補の前回診断状態
            public bool
                HasPreviousKintetsuServiceAndEmergencyCandidateState;

            public byte PreviousKintetsuEmergencySourceA;
            public byte PreviousKintetsuEmergencySourceB;
            public byte PreviousKintetsuServiceMaximumSourceA;
            public byte PreviousKintetsuServiceMaximumSourceB;

            public int
                PreviousKintetsuServiceAndEmergencyPhysicalBrake;

            public int
                PreviousKintetsuServiceAndEmergencyServiceMaximum;

            public int
                PreviousKintetsuServiceAndEmergencyEmergency;

            public int
                PreviousKintetsuServiceAndEmergencyOutputBrake;

            // 近鉄系ATSの前回診断状態
            public bool HasPreviousKintetsuEmergencyCandidateState;
            public byte PreviousKintetsuAbsoluteStopEmergencyLatch;
            public byte PreviousKintetsuSecondaryEmergencySource;
            public int PreviousKintetsuPhysicalBrake;
            public int PreviousKintetsuServiceMaximum;
            public int PreviousKintetsuEmergency;
            public int PreviousKintetsuOutputBrake;

            // ExplicitBrakeRequestFlags方式の前回診断状態
            public bool HasPreviousRequestFlagState;

            public List<byte> PreviousServiceMaximumRequestFlags =
                new List<byte>();

            public List<byte> PreviousEmergencyRequestFlags =
                new List<byte>();

            public int PreviousRequestPhysicalBrake;
            public int PreviousRequestServiceMaximum;
            public int PreviousRequestEmergency;
            public int PreviousRequestOutputBrake;
            // 前回のモード値
            public bool HasPreviousModeValue;
            public int PreviousModeValue;

            // 前回ログ出力値
            public bool HasPreviousState;
            public int PreviousPhysicalBrake;
            public int PreviousServiceMaximum;
            public int PreviousEmergency;
            public int PreviousOutputBrake;
            public IntPtr PreviousObjectAddress;
            // 前回の介入状態。
            // 現在はログ生成専用で、減点処理には接続しない。
            public bool HasPreviousInterventionState;
            // メトロ総合プラグインの内部指示段候補
            public bool HasPreviousMetroRequestCandidateState;

            public byte PreviousMetroEmergencyFlag;
            public byte PreviousMetroLevel7Flag;
            public byte PreviousMetroServiceMaximumMinus3Flag;

            public int PreviousMetroControlMode;
            public int PreviousMetroInternalState;
            public int PreviousMetroSafetyEmergencySource;

            // EmergencyFlagへ集約される非常要因候補の前回値

            public string PreviousInterventionKind = "None";

            // SWP2装置別要求の診断設定。物理ブレーキは要求値へ混ぜない。
            public string Swp2Group;
            public int Swp2RootPointerRva;
            public int Swp2AtsPBrakeOffset;
            public int Swp2AtsPApplyOffset;
            public int Swp2AtsSActiveOffset;
            public bool HasPreviousSwp2State;
            public int PreviousSwp2AtsPRequest;
            public int PreviousSwp2AtsSRequest;
            public int PreviousSwp2AtsOnlyRequest;
            public string PreviousSwp2FailureStage = "Uninitialized";
        }

        private const string ScenarioResetFixV2 = "ScenarioResetFixV2";
        private int scenarioGeneration;
        private int handledScenarioGeneration = -1;
        private bool scenarioResetPending = true;
        private string pendingScenarioIdentity = "Startup";

        public AtsLoggerPlugin(PluginBuilder builder) : base(builder)
        {
            BveHacker.ScenarioOpened += OnAtsLoggerScenarioOpened;
            BveHacker.ScenarioCreated += OnAtsLoggerScenarioCreated;
            BveHacker.ScenarioClosed += OnAtsLoggerScenarioClosed;
        }

        private void OnAtsLoggerScenarioOpened(ScenarioOpenedEventArgs e)
        {
            pendingScenarioIdentity =
                e == null || e.ScenarioInfo == null
                    ? "ScenarioOpened:null"
                    : "ScenarioOpened@" + e.ScenarioInfo.ToString();
        }

        private void OnAtsLoggerScenarioCreated(ScenarioCreatedEventArgs e)
        {
            scenarioGeneration++;
            scenarioResetPending = true;
            if (e != null && e.Scenario != null)
            {
                pendingScenarioIdentity =
                    "ScenarioCreated@"
                    + e.Scenario.GetType().FullName
                    + "#"
                    + System.Runtime.CompilerServices.RuntimeHelpers
                        .GetHashCode(e.Scenario)
                        .ToString("X8");
            }
        }

        private void OnAtsLoggerScenarioClosed(EventArgs e)
        {
            scenarioResetPending = true;
            isLogSessionInitialized = false;
        }

        private void ResetAtsLoggerScenarioState()
        {
            isLogSessionInitialized = false;
            isAtsStructureDumped = false;
            hasDumpedVehiclePlugins = false;
            hasLoggedVehiclePluginsError = false;
            hasDumpedAtsPtAppDomain = false;
            hasLoggedAtsPtAppDomainError = false;
            hasDumpedBveExHostReferences = false;
            hasLoggedBveExHostReferenceError = false;
            hasDumpedExtensionSet = false;
            hasLoggedExtensionSetError = false;
            hasDumpedBveExStaticPluginHosts = false;
            hasLoggedBveExStaticPluginHostError = false;
            hasDumpedPluginHostApp = false;
            hasLoggedPluginHostAppError = false;
            hasDumpedBveHackerEventTargets = false;
            hasLoggedBveHackerEventTargetError = false;
            managedRuntimeResolutions.Clear();
            nextManagedRuntimeResolveTime = DateTime.MinValue;
            hasLoggedManagedRuntimeResolverError = false;
            hasPreviousManagedPrimaryState = false;
            previousManagedPrimaryRequestKind = "Unknown";
            previousManagedPrimaryRequestBrake = int.MinValue;
            previousManagedPrimaryPhysicalBrake = int.MinValue;
            previousManagedPrimaryAtsBrake = int.MinValue;
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
            inspectedRuntimeModulePaths.Clear();
            beaconList.Clear();
            lastLocation = -1.0;
        }
        private void InitializeManagedRuntimeProfiles()
        {
            if (hasInitializedManagedRuntimeProfiles)
            {
                return;
            }

            ManagedRuntimeProfile atsPt5Profile =
                new ManagedRuntimeProfile();

            atsPt5Profile.Id = "ChuoWestAtsPt5";
            atsPt5Profile.ResolverStrategy =
                "BveHackerEventDelegateTarget";
            atsPt5Profile.EventFieldName =
                "ScenarioCreated";
            atsPt5Profile.TargetTypeName =
                "AtsPlugin.AtsMain";

            atsPt5Profile.Sha256Values.Add(
                "9A75F078C8CF8198C5E4970052DE7504C010CA28B68D93CFD66FEC6110949FE4"
            );

            atsPt5Profile.Sha256Values.Add(
                "AF9DDE58B4D987F32E77A9C3DA0929A2EB5D244527FD83DBF5AB5A3E434A35B7"
            );

            atsPt5Profile.ObjectPath.Add(
                new ManagedRuntimePathStep
                {
                    FieldName = "AtsPT",
                    ExpectedTypeName =
                        "AtsPlugin.Core.Engine.PT"
                }
            );

            atsPt5Profile.Members["requestBrake"] =
                new ManagedRuntimeMemberDefinition
                {
                    OwnerName = "AtsPT",
                    FieldName = "pOutputBrakeHandle",
                    ValueTypeName = "System.Int32",
                    SemanticRole = "RequestedBrakeNotch"
                };

            atsPt5Profile.Members["emergencyState"] =
                new ManagedRuntimeMemberDefinition
                {
                    OwnerName = "AtsPT",
                    FieldName = "pIsEmgBrake",
                    ValueTypeName = "System.Boolean",
                    SemanticRole = "EmergencyRequestState"
                };

            atsPt5Profile.Members["securityEmergencyState"] =
                new ManagedRuntimeMemberDefinition
                {
                    OwnerName = "Target",
                    FieldName = "pSecurityEmgBrake",
                    ValueTypeName = "System.Boolean",
                    SemanticRole = "SafetyEmergencyRequestState"
                };

            managedRuntimeProfiles.Add(atsPt5Profile);

            hasInitializedManagedRuntimeProfiles = true;
        }
        private bool TryReadManagedField(
            object target,
            string fieldName,
            string expectedTypeName,
            out object value,
            out string resolvedMember
        )
        {
            value = null;
            resolvedMember = "<NOT_FOUND>";

            if (
                target == null
                || string.IsNullOrWhiteSpace(fieldName)
            )
            {
                return false;
            }

            System.Reflection.BindingFlags declaredFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Static
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;

            Type currentType = target.GetType();

            while (currentType != null)
            {
                System.Reflection.FieldInfo field =
                    currentType.GetField(
                        fieldName,
                        declaredFlags
                    );

                if (field != null)
                {
                    if (
                        !string.IsNullOrWhiteSpace(expectedTypeName)
                        && !string.Equals(
                            field.FieldType.FullName,
                            expectedTypeName,
                            StringComparison.Ordinal
                        )
                    )
                    {
                        return false;
                    }

                    try
                    {
                        value = field.GetValue(
                            field.IsStatic ? null : target
                        );

                        resolvedMember =
                            "Field:"
                            + currentType.FullName
                            + "."
                            + field.Name;

                        return true;
                    }
                    catch
                    {
                        value = null;
                        resolvedMember = "<FIELD_READ_ERROR>";
                        return false;
                    }
                }

                currentType = currentType.BaseType;
            }

            return false;
        }

        private bool TryResolveManagedFieldInfo(
            object owner,
            string fieldName,
            string expectedTypeName,
            out System.Reflection.FieldInfo field,
            out string failureReason
        )
        {
            field = null;
            failureReason = "";

            if (owner == null)
            {
                failureReason = "OwnerIsNull";
                return false;
            }

            if (string.IsNullOrWhiteSpace(fieldName))
            {
                failureReason = "FieldNameIsEmpty";
                return false;
            }

            System.Reflection.BindingFlags declaredFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Static
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;

            Type currentType = owner.GetType();

            while (currentType != null)
            {
                System.Reflection.FieldInfo candidate =
                    currentType.GetField(
                        fieldName,
                        declaredFlags
                    );

                if (candidate != null)
                {
                    if (
                        !string.IsNullOrWhiteSpace(expectedTypeName)
                        && !string.Equals(
                            candidate.FieldType.FullName,
                            expectedTypeName,
                            StringComparison.Ordinal
                        )
                    )
                    {
                        failureReason =
                            "DeclaredTypeMismatch:"
                            + candidate.FieldType.FullName;

                        return false;
                    }

                    field = candidate;
                    return true;
                }

                currentType = currentType.BaseType;
            }

            failureReason = "FieldNotFound";
            return false;
        }

        private bool TryReadResolvedManagedField(
            object owner,
            System.Reflection.FieldInfo field,
            out object value,
            out string failureReason
        )
        {
            value = null;
            failureReason = "";

            if (field == null)
            {
                failureReason = "FieldInfoIsNull";
                return false;
            }

            try
            {
                object readTarget = field.IsStatic ? null : owner;

                if (!field.IsStatic && readTarget == null)
                {
                    failureReason = "InstanceOwnerIsNull";
                    return false;
                }

                value = field.GetValue(readTarget);
                return true;
            }
            catch (Exception ex)
            {
                failureReason =
                    ex.GetType().FullName
                    + ":"
                    + ex.Message;

                return false;
            }
        }

        private bool ValidateManagedRuntimeMembers(
            ManagedRuntimeResolution resolution,
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (
                resolution == null
                || resolution.Profile == null
            )
            {
                return false;
            }

            if (resolution.HasValidatedMembers)
            {
                return true;
            }

            bool allResolved = true;

            foreach (
                KeyValuePair<string, ManagedRuntimeMemberDefinition> pair
                in resolution.Profile.Members
            )
            {
                string memberKey = pair.Key;
                ManagedRuntimeMemberDefinition definition = pair.Value;
                object owner;

                if (
                    definition == null
                    || string.IsNullOrWhiteSpace(definition.OwnerName)
                    || !resolution.NamedObjects.TryGetValue(
                        definition.OwnerName,
                        out owner
                    )
                    || owner == null
                )
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[MANAGED_RUNTIME] MEMBER_ERROR "
                        + $"Profile:{resolution.Profile.Id}, "
                        + $"Member:{memberKey}, "
                        + $"Owner:{definition?.OwnerName ?? "<NULL>"}, "
                        + "Reason:OwnerNotResolved, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    allResolved = false;
                    continue;
                }

                System.Reflection.FieldInfo field;
                string failureReason;

                if (
                    !TryResolveManagedFieldInfo(
                        owner,
                        definition.FieldName,
                        definition.ValueTypeName,
                        out field,
                        out failureReason
                    )
                )
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[MANAGED_RUNTIME] MEMBER_ERROR "
                        + $"Profile:{resolution.Profile.Id}, "
                        + $"Member:{memberKey}, "
                        + $"Owner:{definition.OwnerName}, "
                        + $"Field:{definition.FieldName}, "
                        + $"ExpectedType:{definition.ValueTypeName}, "
                        + $"OwnerType:{owner.GetType().FullName}, "
                        + $"Reason:{failureReason}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    allResolved = false;
                    continue;
                }

                resolution.ResolvedFields[memberKey] = field;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[MANAGED_RUNTIME] MEMBER_RESOLVED "
                    + $"Profile:{resolution.Profile.Id}, "
                    + $"Member:{memberKey}, "
                    + $"Owner:{definition.OwnerName}, "
                    + $"Field:{field.DeclaringType.FullName}.{field.Name}, "
                    + $"DeclaredType:{field.FieldType.FullName}, "
                    + $"IsStatic:{field.IsStatic}, "
                    + $"SemanticRole:{definition.SemanticRole}, "
                    + "ScoringEnabled:False"
                );

                hasChanges = true;
            }

            if (!allResolved)
            {
                resolution.HasLoggedStructureError = true;
                return false;
            }

            resolution.HasValidatedMembers = true;

            rtLog.AppendLine(
                $"[{DateTime.Now:HH:mm:ss.fff}] "
                + "[MANAGED_RUNTIME] MEMBERS_VALIDATED "
                + $"Profile:{resolution.Profile.Id}, "
                + $"ResolvedCount:{resolution.ResolvedFields.Count}, "
                + $"DeclaredCount:{resolution.Profile.Members.Count}, "
                + "ScoringEnabled:False"
            );

            hasChanges = true;
            return true;
        }

        private bool AreManagedRuntimeValuesEqual(
            object left,
            object right
        )
        {
            if (object.ReferenceEquals(left, right))
            {
                return true;
            }

            if (left == null || right == null)
            {
                return false;
            }

            return left.Equals(right);
        }

        private void MonitorManagedRuntimeResolution(
            ManagedRuntimeResolution resolution,
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (
                resolution == null
                || resolution.Profile == null
                || !ValidateManagedRuntimeMembers(
                    resolution,
                    rtLog,
                    ref hasChanges
                )
            )
            {
                return;
            }

            bool anyValueChanged = false;

            foreach (
                KeyValuePair<string, ManagedRuntimeMemberDefinition> pair
                in resolution.Profile.Members
            )
            {
                string memberKey = pair.Key;
                ManagedRuntimeMemberDefinition definition = pair.Value;
                object owner;
                System.Reflection.FieldInfo field;

                if (
                    !resolution.NamedObjects.TryGetValue(
                        definition.OwnerName,
                        out owner
                    )
                    || !resolution.ResolvedFields.TryGetValue(
                        memberKey,
                        out field
                    )
                )
                {
                    continue;
                }

                object currentValue;
                string failureReason;

                if (
                    !TryReadResolvedManagedField(
                        owner,
                        field,
                        out currentValue,
                        out failureReason
                    )
                )
                {
                    if (!resolution.HasLoggedStructureError)
                    {
                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + "[MANAGED_RUNTIME] MEMBER_READ_ERROR "
                            + $"Profile:{resolution.Profile.Id}, "
                            + $"Member:{memberKey}, "
                            + $"Field:{field.DeclaringType.FullName}.{field.Name}, "
                            + $"Reason:{failureReason}, "
                            + "ScoringEnabled:False"
                        );

                        hasChanges = true;
                    }

                    resolution.HasLoggedStructureError = true;
                    continue;
                }

                object previousValue;
                bool hadPreviousValue =
                    resolution.PreviousValues.TryGetValue(
                        memberKey,
                        out previousValue
                    );

                if (
                    !hadPreviousValue
                    || !AreManagedRuntimeValuesEqual(
                        previousValue,
                        currentValue
                    )
                )
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[MANAGED_RUNTIME] MEMBER_VALUE "
                        + $"Profile:{resolution.Profile.Id}, "
                        + $"Member:{memberKey}, "
                        + $"SemanticRole:{definition.SemanticRole}, "
                        + $"Value:{currentValue ?? "<NULL>"}, "
                        + $"Previous:{(hadPreviousValue ? previousValue ?? "<NULL>" : "<UNINITIALIZED>")}, "
                        + $"DeclaredType:{field.FieldType.FullName}, "
                        + $"IsStatic:{field.IsStatic}, "
                        + "ScoringEnabled:False"
                    );

                    resolution.PreviousValues[memberKey] = currentValue;
                    anyValueChanged = true;
                    hasChanges = true;
                }

                if (
                    string.Equals(
                        memberKey,
                        "requestBrake",
                        StringComparison.Ordinal
                    )
                    && currentValue is int
                )
                {
                    resolution.HasCurrentRequestBrake = true;
                    resolution.CurrentRequestBrake = (int)currentValue;
                }
                else if (
                    string.Equals(
                        memberKey,
                        "emergencyState",
                        StringComparison.Ordinal
                    )
                    && currentValue is bool
                )
                {
                    resolution.HasCurrentEmergencyState = true;
                    resolution.CurrentEmergencyState = (bool)currentValue;
                }
                else if (
                    string.Equals(
                        memberKey,
                        "securityEmergencyState",
                        StringComparison.Ordinal
                    )
                    && currentValue is bool
                )
                {
                    resolution.HasCurrentSecurityEmergencyState = true;
                    resolution.CurrentSecurityEmergencyState = (bool)currentValue;
                }
            }

            bool hasAllValues =
                resolution.HasCurrentRequestBrake
                && resolution.HasCurrentEmergencyState
                && resolution.HasCurrentSecurityEmergencyState;

            if (!hasAllValues)
            {
                return;
            }

            bool emergencyCandidate =
                resolution.CurrentEmergencyState
                || resolution.CurrentSecurityEmergencyState;

            bool serviceMaximumCandidate =
                !emergencyCandidate
                && serviceMaxBrakeNotch > 0
                && resolution.CurrentRequestBrake == serviceMaxBrakeNotch;

            string requestKindCandidate;
            int requestBrakeCandidate;

            if (emergencyCandidate)
            {
                requestKindCandidate = "Emergency";
                requestBrakeCandidate = emergencyBrakeNotch;
            }
            else if (serviceMaximumCandidate)
            {
                requestKindCandidate = "ServiceMaximum";
                requestBrakeCandidate = serviceMaxBrakeNotch;
            }
            else if (resolution.CurrentRequestBrake > 0)
            {
                requestKindCandidate = "Service";
                requestBrakeCandidate = resolution.CurrentRequestBrake;
            }
            else
            {
                requestKindCandidate = "None";
                requestBrakeCandidate = 0;
            }

            bool derivedStateChanged =
                !resolution.HasLoggedInitialState
                || !string.Equals(
                    resolution.CurrentRequestKind,
                    requestKindCandidate,
                    StringComparison.Ordinal
                )
                || resolution.CurrentRequestBrakeCandidate
                    != requestBrakeCandidate;

            resolution.CurrentRequestKind = requestKindCandidate;
            resolution.CurrentRequestBrakeCandidate = requestBrakeCandidate;

            if (anyValueChanged || derivedStateChanged)
            {
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[MANAGED_RUNTIME] STATE "
                    + $"Profile:{resolution.Profile.Id}, "
                    + $"OutputBrakeHandle:{resolution.CurrentRequestBrake}, "
                    + $"IsEmgBrake:{resolution.CurrentEmergencyState}, "
                    + $"SecurityEmgBrake:{resolution.CurrentSecurityEmergencyState}, "
                    + $"EmergencyCandidate:{emergencyCandidate}, "
                    + $"ServiceMaximumCandidate:{serviceMaximumCandidate}, "
                    + $"RequestKindCandidate:{requestKindCandidate}, "
                    + $"RequestBrakeCandidate:{requestBrakeCandidate}, "
                    + $"TargetIdentity:{GetObjectIdentity(resolution.TargetObject)}, "
                    + "ScoringEnabled:False"
                );

                resolution.HasLoggedInitialState = true;
                hasChanges = true;
            }
        }

        private bool TryResolveManagedRuntimeProfile(
    ManagedRuntimeProfile profile,
    StringBuilder rtLog,
    ref bool hasChanges
)
        {
            if (
                profile == null
                || BveHacker == null
                || !string.Equals(
                    profile.ResolverStrategy,
                    "BveHackerEventDelegateTarget",
                    StringComparison.Ordinal
                )
                || string.IsNullOrWhiteSpace(
                    profile.EventFieldName
                )
            )
            {
                return false;
            }

            object bveHackerObject = BveHacker;

            System.Reflection.BindingFlags declaredFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;

            Type currentType = bveHackerObject.GetType();

            while (currentType != null)
            {
                System.Reflection.FieldInfo eventField =
                    currentType.GetField(
                        profile.EventFieldName,
                        declaredFlags
                    );

                if (eventField == null)
                {
                    currentType = currentType.BaseType;
                    continue;
                }

                if (
                    !typeof(Delegate).IsAssignableFrom(
                        eventField.FieldType
                    )
                )
                {
                    return false;
                }

                Delegate eventDelegate;

                try
                {
                    eventDelegate =
                        eventField.GetValue(
                            bveHackerObject
                        ) as Delegate;
                }
                catch
                {
                    return false;
                }

                if (eventDelegate == null)
                {
                    return false;
                }

                foreach (
                    Delegate invocation
                    in eventDelegate.GetInvocationList()
                )
                {
                    object target = invocation.Target;

                    if (target == null)
                    {
                        continue;
                    }

                    Type targetType = target.GetType();

                    if (
                        !string.Equals(
                            targetType.FullName,
                            profile.TargetTypeName,
                            StringComparison.Ordinal
                        )
                    )
                    {
                        continue;
                    }

                    string assemblyLocation;
                    string targetSha256;

                    GetAssemblyIdentity(
                        targetType.Assembly,
                        out assemblyLocation,
                        out targetSha256
                    );

                    if (
                        string.IsNullOrWhiteSpace(targetSha256)
                        || !profile.Sha256Values.Any(
                            hash => string.Equals(
                                hash,
                                targetSha256,
                                StringComparison.OrdinalIgnoreCase
                            )
                        )
                    )
                    {
                        continue;
                    }

                    ManagedRuntimeResolution resolution =
                        new ManagedRuntimeResolution();

                    resolution.Profile = profile;
                    resolution.MatchedSha256 =
                        targetSha256;
                    resolution.TargetObject =
                        target;

                    resolution.NamedObjects["Target"] =
                        target;

                    object currentObject = target;
                    bool pathResolved = true;

                    foreach (
                        ManagedRuntimePathStep step
                        in profile.ObjectPath
                    )
                    {
                        object nextObject;
                        string resolvedMember;

                        if (
                            !TryReadManagedField(
                                currentObject,
                                step.FieldName,
                                "",
                                out nextObject,
                                out resolvedMember
                            )
                            || nextObject == null
                        )
                        {
                            pathResolved = false;

                            rtLog.AppendLine(
                                $"[{DateTime.Now:HH:mm:ss.fff}] "
                                + "[MANAGED_RUNTIME] PATH_ERROR "
                                + $"Profile:{profile.Id}, "
                                + $"SHA256:{targetSha256}, "
                                + $"Field:{step.FieldName}, "
                                + $"FromType:{currentObject.GetType().FullName}, "
                                + "Reason:FieldNotFoundOrNull, "
                                + "ScoringEnabled:False"
                            );

                            hasChanges = true;
                            break;
                        }

                        if (
                            !string.IsNullOrWhiteSpace(
                                step.ExpectedTypeName
                            )
                            && !string.Equals(
                                nextObject.GetType().FullName,
                                step.ExpectedTypeName,
                                StringComparison.Ordinal
                            )
                        )
                        {
                            pathResolved = false;

                            rtLog.AppendLine(
                                $"[{DateTime.Now:HH:mm:ss.fff}] "
                                + "[MANAGED_RUNTIME] PATH_ERROR "
                                + $"Profile:{profile.Id}, "
                                + $"SHA256:{targetSha256}, "
                                + $"Field:{step.FieldName}, "
                                + $"ExpectedType:{step.ExpectedTypeName}, "
                                + $"ActualType:{nextObject.GetType().FullName}, "
                                + "Reason:TypeMismatch, "
                                + "ScoringEnabled:False"
                            );

                            hasChanges = true;
                            break;
                        }

                        currentObject = nextObject;

                        resolution.NamedObjects[
                            step.FieldName
                        ] = nextObject;
                    }

                    if (!pathResolved)
                    {
                        continue;
                    }

                    managedRuntimeResolutions[
                        profile.Id
                    ] = resolution;

                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[MANAGED_RUNTIME] RESOLVED "
                        + $"Profile:{profile.Id}, "
                        + $"Strategy:{profile.ResolverStrategy}, "
                        + $"Event:{profile.EventFieldName}, "
                        + $"Method:{invocation.Method.Name}, "
                        + $"SHA256:{targetSha256}, "
                        + $"TargetType:{targetType.FullName}, "
                        + $"TargetIdentity:{GetObjectIdentity(target)}, "
                        + $"ResolvedObjectCount:{resolution.NamedObjects.Count}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    return true;
                }

                return false;
            }

            return false;
        }
        private void ResolveManagedRuntimeProfiles(
        StringBuilder rtLog,
        ref bool hasChanges
        )
        {
            InitializeManagedRuntimeProfiles();

            try
            {
                DateTime currentTime = DateTime.UtcNow;

                if (currentTime >= nextManagedRuntimeResolveTime)
                {
                    nextManagedRuntimeResolveTime =
                        currentTime.AddSeconds(1.0);

                    foreach (
                        ManagedRuntimeProfile profile
                        in managedRuntimeProfiles
                    )
                    {
                        if (
                            profile == null
                            || string.IsNullOrWhiteSpace(
                                profile.Id
                            )
                            || managedRuntimeResolutions.ContainsKey(
                                profile.Id
                            )
                        )
                        {
                            continue;
                        }

                        TryResolveManagedRuntimeProfile(
                            profile,
                            rtLog,
                            ref hasChanges
                        );
                    }
                }

                foreach (
                    ManagedRuntimeResolution resolution
                    in managedRuntimeResolutions.Values.ToArray()
                )
                {
                    MonitorManagedRuntimeResolution(
                        resolution,
                        rtLog,
                        ref hasChanges
                    );
                }
            }
            catch (Exception ex)
            {
                if (!hasLoggedManagedRuntimeResolverError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[MANAGED_RUNTIME] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedManagedRuntimeResolverError =
                        true;

                    hasChanges = true;
                }
            }
        }

        public override void Dispose()
        {
            BveHacker.ScenarioOpened -= OnAtsLoggerScenarioOpened;
            BveHacker.ScenarioCreated -= OnAtsLoggerScenarioCreated;
            BveHacker.ScenarioClosed -= OnAtsLoggerScenarioClosed;
        }

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
        // カタログ内の16進RVA文字列を整数へ変換する。
        // 不正値、負値、Int32範囲外は失敗として扱う。
        // =========================================================
        private bool TryParseRuntimeRva(
            string text,
            out int rva
        )
        {
            rva = 0;

            if (string.IsNullOrWhiteSpace(text))
            {
                return false;
            }

            string normalized = text.Trim();

            if (
                normalized.StartsWith(
                    "0x",
                    StringComparison.OrdinalIgnoreCase
                )
            )
            {
                normalized = normalized.Substring(2);
            }

            uint unsignedRva;

            if (
                !uint.TryParse(
                    normalized,
                    System.Globalization.NumberStyles.HexNumber,
                    System.Globalization.CultureInfo.InvariantCulture,
                    out unsignedRva
                )
                || unsignedRva == 0
                || unsignedRva > int.MaxValue
            )
            {
                return false;
            }

            rva = (int)unsignedRva;
            return true;
        }

        // =========================================================
        // ModuleRva形式のアドレスだけを読み取る。
        // ポインター参照型など、異なる方式はここでは受け付けない。
        // =========================================================
        private bool TryGetDirectRuntimeRva(
            RuntimeProfileCatalogAddress address,
            string expectedValueType,
            out int rva
        )
        {
            rva = 0;

            if (
                address == null
                || !string.Equals(
                    address.Kind,
                    "ModuleRva",
                    StringComparison.OrdinalIgnoreCase
                )
                || !string.Equals(
                    address.ValueType,
                    expectedValueType,
                    StringComparison.OrdinalIgnoreCase
                )
            )
            {
                return false;
            }

            return TryParseRuntimeRva(
                address.Rva,
                out rva
            );
        }

        // =========================================================
        // runtime-profile-candidates.jsonを型付きで読み込む。
        // =========================================================
        private RuntimeProfileCatalog LoadRuntimeProfileCatalog(
    string path
)
        {
            string json =
                System.IO.File.ReadAllText(
                    path,
                    Encoding.UTF8
                );

            if (
                json.Length > 0
                && json[0] == '\uFEFF'
            )
            {
                json = json.Substring(1);
            }

            byte[] jsonBytes =
                Encoding.UTF8.GetBytes(json);

            DataContractJsonSerializer serializer =
                new DataContractJsonSerializer(
                    typeof(RuntimeProfileCatalog)
                );

            using (
                System.IO.MemoryStream stream =
                    new System.IO.MemoryStream(jsonBytes)
            )
            {
                return serializer.ReadObject(stream)
                    as RuntimeProfileCatalog;
            }
        }

        // =========================================================
        // カタログのModuleRva配列から、指定型のRVAを取得する。
        // 不正または未対応の要素はスキップする。
        // =========================================================
        private List<int> GetDirectRuntimeRvas(
            List<RuntimeProfileCatalogAddress> addresses,
            string expectedValueType
        )
        {
            List<int> result = new List<int>();

            if (addresses == null)
            {
                return result;
            }

            foreach (
                RuntimeProfileCatalogAddress address
                in addresses
            )
            {
                int rva;

                if (
                    TryGetDirectRuntimeRva(
                        address,
                        expectedValueType,
                        out rva
                    )
                    && !result.Contains(rva)
                )
                {
                    result.Add(rva);
                }
            }

            return result;
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
        // 現在のプロセス内にある64ビット浮動小数点値を安全に読み取る。
        // BAB4の名前付き値マップはdouble値を保持する。
        // =========================================================
        private bool TryReadRuntimeDouble(
            IntPtr address,
            out double value
        )
        {
            value = 0.0;

            if (address == IntPtr.Zero)
            {
                return false;
            }

            try
            {
                byte[] bytes = new byte[sizeof(double)];
                System.Runtime.InteropServices.Marshal.Copy(
                    address,
                    bytes,
                    0,
                    bytes.Length
                );
                value = BitConverter.ToDouble(bytes, 0);
                return !double.IsNaN(value) && !double.IsInfinity(value);
            }
            catch
            {
                value = 0.0;
                return false;
            }
        }

        // =========================================================
        // 現在のプロセス内にある1バイト値を安全に読み取る
        // =========================================================
        private bool TryReadRuntimeByte(
            IntPtr address,
            out byte value
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
                    System.Runtime.InteropServices.Marshal.ReadByte(
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
        // ModuleRvaの配列に対応するByte値をすべて読み取る。
        // 1個でも読取りに失敗した場合はfalseを返す。
        // =========================================================
        private bool TryReadRuntimeBytes(
            IntPtr moduleBaseAddress,
            List<int> rvas,
            out List<byte> values
        )
        {
            values = new List<byte>();

            if (
                moduleBaseAddress == IntPtr.Zero
                || rvas == null
                || rvas.Count == 0
            )
            {
                return false;
            }

            foreach (int rva in rvas)
            {
                byte value;

                if (
                    rva == 0
                    || !TryReadRuntimeByte(
                        IntPtr.Add(
                            moduleBaseAddress,
                            rva
                        ),
                        out value
                    )
                )
                {
                    values.Clear();
                    return false;
                }

                values.Add(value);
            }

            return true;
        }

        // =========================================================
        // ModuleRvaの配列に対応するInt32値をすべて読み取る。
        // 1個でも読取りに失敗した場合はfalseを返す。
        // =========================================================


        // =========================================================
        // 2つのByte配列が同じ内容か確認する。
        // =========================================================
        private bool RuntimeByteListsEqual(
            List<byte> left,
            List<byte> right
        )
        {
            if (
                left == null
                || right == null
                || left.Count != right.Count
            )
            {
                return false;
            }

            for (
                int index = 0;
                index < left.Count;
                index++
            )
            {
                if (left[index] != right[index])
                {
                    return false;
                }
            }

            return true;
        }

        // =========================================================
        // 非ゼロになっている要求フラグのRVAをログ用に整形する。
        // =========================================================
        private string FormatActiveRequestFlagRvas(
            List<int> rvas,
            List<byte> values
        )
        {
            List<string> activeRvas =
                new List<string>();

            if (
                rvas == null
                || values == null
            )
            {
                return "None";
            }

            int count = Math.Min(
                rvas.Count,
                values.Count
            );

            for (
                int index = 0;
                index < count;
                index++
            )
            {
                if (values[index] != 0)
                {
                    activeRvas.Add(
                        string.Format(
                            "0x{0:X}",
                            rvas[index]
                        )
                    );
                }
            }

            return activeRvas.Count > 0
                ? string.Join("|", activeRvas)
                : "None";
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
        // 現在のプロセスのポインター幅に合わせてポインターを読み取る。
        // x86では4バイト、x64では8バイトとして扱う。
        // =========================================================
        private bool TryReadRuntimePointer(
            IntPtr address,
            out IntPtr value
        )
        {
            value = IntPtr.Zero;
            if (address == IntPtr.Zero)
            {
                return false;
            }
            try
            {
                value =
                    System.Runtime.InteropServices.Marshal.ReadIntPtr(
                        address
                    );
                return value != IntPtr.Zero;
            }
            catch
            {
                value = IntPtr.Zero;
                return false;
            }
        }

        // =========================================================
        // BveExのVehiclePluginsを一度だけ列挙し、
        // ATSプラグイン本体への参照経路を調査する。
        //
        // 現段階では診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseVehiclePlugins(
            System.Reflection.BindingFlags bindFlags,
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedVehiclePlugins)
            {
                return;
            }

            try
            {
                if (Plugins == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[VEHICLE_PLUGINS_DIAGNOSTIC] WAIT "
                        + "Reason:PluginsIsNull, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    return;
                }

                object vehiclePluginsObject =
                    Plugins.VehiclePlugins;

                if (vehiclePluginsObject == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[VEHICLE_PLUGINS_DIAGNOSTIC] WAIT "
                        + "Reason:VehiclePluginsIsNull, "
                        + $"PluginsType:{Plugins.GetType().FullName}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    return;
                }

                System.Collections.IEnumerable vehiclePlugins =
                    vehiclePluginsObject
                        as System.Collections.IEnumerable;

                if (vehiclePlugins == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[VEHICLE_PLUGINS_DIAGNOSTIC] WAIT "
                        + "Reason:VehiclePluginsIsNotEnumerable, "
                        + "VehiclePluginsType:"
                        + $"{vehiclePluginsObject.GetType().FullName}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    return;
                }

                int entryCount = 0;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[VEHICLE_PLUGINS_DIAGNOSTIC] START "
                    + "CollectionType:"
                    + $"{vehiclePluginsObject.GetType().FullName}, "
                    + "ScoringEnabled:False"
                );

                foreach (object entryObject in vehiclePlugins)
                {
                    if (entryObject == null)
                    {
                        continue;
                    }

                    Type entryType = entryObject.GetType();

                    System.Reflection.PropertyInfo keyProperty =
                        entryType.GetProperty(
                            "Key",
                            bindFlags
                        );

                    System.Reflection.PropertyInfo valueProperty =
                        entryType.GetProperty(
                            "Value",
                            bindFlags
                        );

                    object keyObject =
                        keyProperty != null
                            ? keyProperty.GetValue(
                                entryObject,
                                null
                            )
                            : null;

                    object valueObject =
                        valueProperty != null
                            ? valueProperty.GetValue(
                                entryObject,
                                null
                            )
                            : null;

                    string keyText =
                        keyObject != null
                            ? keyObject.ToString()
                            : "<NULL>";

                    if (valueObject == null)
                    {
                        rtLog.AppendLine(
                            "[VEHICLE_PLUGINS_DIAGNOSTIC] ENTRY "
                            + $"Index:{entryCount}, "
                            + $"Key:{keyText}, "
                            + $"EntryType:{entryType.FullName}, "
                            + "Value:<NULL>"
                        );

                        entryCount++;
                        continue;
                    }

                    Type valueType =
                        valueObject.GetType();

                    System.Reflection.Assembly valueAssembly =
                        valueType.Assembly;

                    string assemblyName = "<UNKNOWN>";
                    string assemblyVersion = "<UNKNOWN>";
                    string assemblyLocation = "<EMPTY>";
                    string assemblySha256 = "<UNAVAILABLE>";

                    if (valueAssembly != null)
                    {
                        System.Reflection.AssemblyName assemblyIdentity =
                            valueAssembly.GetName();

                        if (assemblyIdentity != null)
                        {
                            if (
                                !string.IsNullOrWhiteSpace(
                                    assemblyIdentity.Name
                                )
                            )
                            {
                                assemblyName =
                                    assemblyIdentity.Name;
                            }

                            if (assemblyIdentity.Version != null)
                            {
                                assemblyVersion =
                                    assemblyIdentity.Version
                                        .ToString();
                            }
                        }

                        try
                        {
                            assemblyLocation =
                                valueAssembly.Location;

                            if (
                                !string.IsNullOrWhiteSpace(
                                    assemblyLocation
                                )
                                && System.IO.File.Exists(
                                    assemblyLocation
                                )
                            )
                            {
                                assemblySha256 =
                                    ComputeFileSha256(
                                        assemblyLocation
                                    );
                            }
                        }
                        catch
                        {
                            assemblyLocation =
                                "<UNAVAILABLE>";

                            assemblySha256 =
                                "<UNAVAILABLE>";
                        }
                    }

                    rtLog.AppendLine(
                        "[VEHICLE_PLUGINS_DIAGNOSTIC] ENTRY "
                        + $"Index:{entryCount}, "
                        + $"Key:{keyText}, "
                        + $"EntryType:{entryType.FullName}, "
                        + $"ValueType:{valueType.FullName}, "
                        + $"AssemblyName:{assemblyName}, "
                        + $"AssemblyVersion:{assemblyVersion}, "
                        + $"AssemblyLocation:{assemblyLocation}, "
                        + $"SHA256:{assemblySha256}, "
                        + $"Identity:{GetObjectIdentity(valueObject)}, "
                        + "ScoringEnabled:False"
                    );

                    System.Reflection.PropertyInfo[] properties =
                        valueType.GetProperties(
                            bindFlags
                        );

                    foreach (
                        System.Reflection.PropertyInfo property
                        in properties
                    )
                    {
                        rtLog.AppendLine(
                            "[VEHICLE_PLUGINS_DIAGNOSTIC] PROPERTY "
                            + $"Index:{entryCount}, "
                            + $"Name:{property.Name}, "
                            + "DeclaredType:"
                            + $"{property.PropertyType.FullName}, "
                            + $"CanRead:{property.CanRead}"
                        );
                    }

                    System.Reflection.FieldInfo[] fields =
                        valueType.GetFields(
                            bindFlags
                        );

                    foreach (
                        System.Reflection.FieldInfo field
                        in fields
                    )
                    {
                        string runtimeType = "<NOT_READ>";
                        string identity = "<NOT_READ>";

                        try
                        {
                            object fieldValue =
                                field.GetValue(
                                    valueObject
                                );

                            runtimeType =
                                fieldValue != null
                                    ? fieldValue.GetType().FullName
                                    : "<NULL>";

                            identity =
                                GetObjectIdentity(
                                    fieldValue
                                );
                        }
                        catch (Exception ex)
                        {
                            runtimeType =
                                "<ERROR:"
                                + ex.GetType().Name
                                + ">";

                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[VEHICLE_PLUGINS_DIAGNOSTIC] FIELD "
                            + $"Index:{entryCount}, "
                            + $"Name:{field.Name}, "
                            + $"DeclaredType:{field.FieldType.FullName}, "
                            + $"IsStatic:{field.IsStatic}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}"
                        );
                    }

                    entryCount++;
                }

                // シナリオ生成直後で一覧が空なら、
                // 次のTickで改めて診断する。
                if (entryCount == 0)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[VEHICLE_PLUGINS_DIAGNOSTIC] WAIT "
                        + "Reason:VehiclePluginsIsEmpty, "
                        + "CollectionType:"
                        + $"{vehiclePluginsObject.GetType().FullName}, "
                        + "ScoringEnabled:False"
                    );

                    hasChanges = true;
                    return;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[VEHICLE_PLUGINS_DIAGNOSTIC] END "
                    + $"EntryCount:{entryCount}, "
                    + "ScoringEnabled:False"
                );

                hasDumpedVehiclePlugins = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedVehiclePluginsError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[VEHICLE_PLUGINS_DIAGNOSTIC] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedVehiclePluginsError = true;
                    hasChanges = true;
                }
            }
        }
        // =========================================================
        // 現在のAppDomainへロードされているアセンブリから、
        // AtsPT5.dllおよびAtsPlugin.AtsMain型を探索する。
        //
        // AtsMainまたは関連型の静的フィールドに実行中の
        // インスタンスが保持されていないかも確認する。
        //
        // 現段階では診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseAtsPtAppDomain(
            System.Reflection.BindingFlags bindFlags,
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedAtsPtAppDomain)
            {
                return;
            }

            try
            {
                System.Reflection.Assembly[] assemblies =
                    AppDomain.CurrentDomain.GetAssemblies();

                int candidateAssemblyCount = 0;
                int atsMainTypeCount = 0;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[ATSPT_APPDOMAIN] START "
                    + $"AssemblyCount:{assemblies.Length}, "
                    + $"AppDomain:{AppDomain.CurrentDomain.FriendlyName}, "
                    + "ScoringEnabled:False"
                );

                foreach (
                    System.Reflection.Assembly assembly
                    in assemblies
                )
                {
                    if (assembly == null)
                    {
                        continue;
                    }

                    System.Reflection.AssemblyName assemblyName =
                        assembly.GetName();

                    string simpleName =
                        assemblyName != null
                            ? assemblyName.Name
                            : "<UNKNOWN>";

                    string versionText =
                        assemblyName != null
                        && assemblyName.Version != null
                            ? assemblyName.Version.ToString()
                            : "<UNKNOWN>";

                    string location = "<EMPTY>";
                    string sha256 = "<UNAVAILABLE>";

                    try
                    {
                        location = assembly.Location;

                        if (
                            !string.IsNullOrWhiteSpace(location)
                            && System.IO.File.Exists(location)
                        )
                        {
                            sha256 =
                                ComputeFileSha256(location);
                        }
                    }
                    catch
                    {
                        location = "<UNAVAILABLE>";
                        sha256 = "<UNAVAILABLE>";
                    }

                    Type[] assemblyTypes;

                    try
                    {
                        assemblyTypes = assembly.GetTypes();
                    }
                    catch (
                        System.Reflection.ReflectionTypeLoadException ex
                    )
                    {
                        assemblyTypes =
                            ex.Types
                                .Where(type => type != null)
                                .ToArray();
                    }
                    catch
                    {
                        assemblyTypes = new Type[0];
                    }

                    Type atsMainType =
                        assemblyTypes.FirstOrDefault(
                            type =>
                                type != null
                                && string.Equals(
                                    type.FullName,
                                    "AtsPlugin.AtsMain",
                                    StringComparison.Ordinal
                                )
                        );

                    bool nameLooksLikeAtsPt =
                        !string.IsNullOrWhiteSpace(simpleName)
                        && simpleName.IndexOf(
                            "AtsPT5",
                            StringComparison.OrdinalIgnoreCase
                        ) >= 0;

                    bool locationLooksLikeAtsPt =
                        !string.IsNullOrWhiteSpace(location)
                        && location.IndexOf(
                            "AtsPT5",
                            StringComparison.OrdinalIgnoreCase
                        ) >= 0;

                    bool hashMatchesKnownAtsPt =
                        string.Equals(
                            sha256,
                            "9A75F078C8CF8198C5E4970052DE7504C010CA28B68D93CFD66FEC6110949FE4",
                            StringComparison.OrdinalIgnoreCase
                        )
                        || string.Equals(
                            sha256,
                            "AF9DDE58B4D987F32E77A9C3DA0929A2EB5D244527FD83DBF5AB5A3E434A35B7",
                            StringComparison.OrdinalIgnoreCase
                        );

                    bool isCandidate =
                        nameLooksLikeAtsPt
                        || locationLooksLikeAtsPt
                        || hashMatchesKnownAtsPt
                        || atsMainType != null;

                    if (!isCandidate)
                    {
                        continue;
                    }

                    candidateAssemblyCount++;

                    rtLog.AppendLine(
                        "[ATSPT_APPDOMAIN] ASSEMBLY "
                        + $"Name:{simpleName}, "
                        + $"Version:{versionText}, "
                        + $"Location:{location}, "
                        + $"SHA256:{sha256}, "
                        + $"TypeCount:{assemblyTypes.Length}, "
                        + $"HasAtsMain:{atsMainType != null}, "
                        + $"KnownHash:{hashMatchesKnownAtsPt}"
                    );

                    if (atsMainType == null)
                    {
                        foreach (
                            Type candidateType
                            in assemblyTypes
                        )
                        {
                            if (
                                candidateType == null
                                || string.IsNullOrWhiteSpace(
                                    candidateType.FullName
                                )
                                || !candidateType.FullName.StartsWith(
                                    "AtsPlugin.",
                                    StringComparison.Ordinal
                                )
                            )
                            {
                                continue;
                            }

                            rtLog.AppendLine(
                                "[ATSPT_APPDOMAIN] TYPE "
                                + $"Assembly:{simpleName}, "
                                + $"Type:{candidateType.FullName}, "
                                + $"IsClass:{candidateType.IsClass}"
                            );
                        }

                        continue;
                    }

                    atsMainTypeCount++;

                    rtLog.AppendLine(
                        "[ATSPT_APPDOMAIN] ATSMAIN "
                        + $"Assembly:{simpleName}, "
                        + $"Type:{atsMainType.FullName}, "
                        + $"BaseType:"
                        + $"{(atsMainType.BaseType != null ? atsMainType.BaseType.FullName : "<NULL>")}"
                    );

                    System.Reflection.FieldInfo[] fields =
                        atsMainType.GetFields(
                            bindFlags
                            | System.Reflection.BindingFlags.Static
                        );

                    foreach (
                        System.Reflection.FieldInfo field
                        in fields
                    )
                    {
                        object fieldValue = null;
                        string runtimeType = "<NOT_READ>";
                        string identity = "<NOT_READ>";

                        try
                        {
                            if (field.IsStatic)
                            {
                                fieldValue =
                                    field.GetValue(null);

                                runtimeType =
                                    fieldValue != null
                                        ? fieldValue.GetType().FullName
                                        : "<NULL>";

                                identity =
                                    GetObjectIdentity(fieldValue);
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType =
                                "<ERROR:"
                                + ex.GetType().Name
                                + ">";

                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[ATSPT_APPDOMAIN] STATIC_FIELD "
                            + $"DeclaringType:{atsMainType.FullName}, "
                            + $"Name:{field.Name}, "
                            + $"DeclaredType:{field.FieldType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}"
                        );
                    }

                    System.Reflection.PropertyInfo[] properties =
                        atsMainType.GetProperties(
                            bindFlags
                            | System.Reflection.BindingFlags.Static
                        );

                    foreach (
                        System.Reflection.PropertyInfo property
                        in properties
                    )
                    {
                        if (
                            !property.CanRead
                            || property.GetIndexParameters().Length != 0
                        )
                        {
                            continue;
                        }

                        System.Reflection.MethodInfo getter =
                            property.GetGetMethod(true);

                        if (
                            getter == null
                            || !getter.IsStatic
                        )
                        {
                            continue;
                        }

                        string runtimeType = "<NOT_READ>";
                        string identity = "<NOT_READ>";

                        try
                        {
                            object propertyValue =
                                property.GetValue(
                                    null,
                                    null
                                );

                            runtimeType =
                                propertyValue != null
                                    ? propertyValue.GetType().FullName
                                    : "<NULL>";

                            identity =
                                GetObjectIdentity(propertyValue);
                        }
                        catch (Exception ex)
                        {
                            runtimeType =
                                "<ERROR:"
                                + ex.GetType().Name
                                + ">";

                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[ATSPT_APPDOMAIN] STATIC_PROPERTY "
                            + $"DeclaringType:{atsMainType.FullName}, "
                            + $"Name:{property.Name}, "
                            + $"DeclaredType:{property.PropertyType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}"
                        );
                    }

                    Type[] atsPluginTypes =
                        assemblyTypes
                            .Where(
                                type =>
                                    type != null
                                    && !string.IsNullOrWhiteSpace(
                                        type.FullName
                                    )
                                    && type.FullName.StartsWith(
                                        "AtsPlugin.",
                                        StringComparison.Ordinal
                                    )
                            )
                            .ToArray();

                    foreach (
                        Type candidateType
                        in atsPluginTypes
                    )
                    {
                        rtLog.AppendLine(
                            "[ATSPT_APPDOMAIN] TYPE "
                            + $"Assembly:{simpleName}, "
                            + $"Type:{candidateType.FullName}, "
                            + $"IsClass:{candidateType.IsClass}"
                        );

                        System.Reflection.FieldInfo[] staticFields =
                            candidateType.GetFields(
                                bindFlags
                                | System.Reflection.BindingFlags.Static
                            );

                        foreach (
                            System.Reflection.FieldInfo staticField
                            in staticFields
                        )
                        {
                            if (!staticField.IsStatic)
                            {
                                continue;
                            }

                            bool couldReferenceAtsMain =
                                staticField.FieldType == atsMainType
                                || atsMainType.IsAssignableFrom(
                                    staticField.FieldType
                                )
                                || staticField.FieldType == typeof(object);

                            if (!couldReferenceAtsMain)
                            {
                                continue;
                            }

                            string runtimeType = "<NOT_READ>";
                            string identity = "<NOT_READ>";
                            bool valueIsAtsMain = false;

                            try
                            {
                                object staticValue =
                                    staticField.GetValue(null);

                                runtimeType =
                                    staticValue != null
                                        ? staticValue.GetType().FullName
                                        : "<NULL>";

                                identity =
                                    GetObjectIdentity(staticValue);

                                valueIsAtsMain =
                                    staticValue != null
                                    && atsMainType.IsInstanceOfType(
                                        staticValue
                                    );
                            }
                            catch (Exception ex)
                            {
                                runtimeType =
                                    "<ERROR:"
                                    + ex.GetType().Name
                                    + ">";

                                identity = "<ERROR>";
                            }

                            rtLog.AppendLine(
                                "[ATSPT_APPDOMAIN] INSTANCE_CANDIDATE "
                                + $"DeclaringType:{candidateType.FullName}, "
                                + $"Field:{staticField.Name}, "
                                + $"DeclaredType:{staticField.FieldType.FullName}, "
                                + $"RuntimeType:{runtimeType}, "
                                + $"IsAtsMain:{valueIsAtsMain}, "
                                + $"Identity:{identity}"
                            );
                        }
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[ATSPT_APPDOMAIN] END "
                    + $"CandidateAssemblyCount:{candidateAssemblyCount}, "
                    + $"AtsMainTypeCount:{atsMainTypeCount}, "
                    + "ScoringEnabled:False"
                );

                hasDumpedAtsPtAppDomain = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedAtsPtAppDomainError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[ATSPT_APPDOMAIN] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedAtsPtAppDomainError = true;
                    hasChanges = true;
                }
            }
        }

        // =========================================================
        // 現在の拡張プラグインとBveHackerが保持する参照を調べる。
        //
        // AtsPT5のAtsMainインスタンスまたはプラグイン管理オブジェクトへ
        // 到達できる参照を探すための診断専用処理。
        //
        // 現段階では診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseBveExHostReferences(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedBveExHostReferences)
            {
                return;
            }

            try
            {
                System.Reflection.BindingFlags declaredInstanceFlags =
                    System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEEX_HOST_REFERENCE] START "
                    + $"ThisType:{GetType().FullName}, "
                    + "ScoringEnabled:False"
                );

                Type currentType = GetType();
                int hierarchyLevel = 0;

                while (currentType != null)
                {
                    rtLog.AppendLine(
                        "[BVEEX_HOST_REFERENCE] TYPE "
                        + $"Source:ThisHierarchy, "
                        + $"Level:{hierarchyLevel}, "
                        + $"Type:{currentType.FullName}, "
                        + "Assembly:"
                        + $"{currentType.Assembly.GetName().Name}"
                    );

                    System.Reflection.FieldInfo[] instanceFields =
                        currentType.GetFields(
                            declaredInstanceFlags
                        );

                    foreach (
                        System.Reflection.FieldInfo field
                        in instanceFields
                    )
                    {
                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";
                        string valueText = "<OBJECT>";
                        bool isAtsMain = false;

                        try
                        {
                            object fieldValue =
                                field.GetValue(this);

                            if (fieldValue != null)
                            {
                                runtimeType =
                                    fieldValue.GetType().FullName;

                                identity =
                                    GetObjectIdentity(fieldValue);

                                Type fieldRuntimeType =
                                    fieldValue.GetType();

                                isAtsMain =
                                    string.Equals(
                                        fieldRuntimeType.FullName,
                                        "AtsPlugin.AtsMain",
                                        StringComparison.Ordinal
                                    );

                                if (
                                    fieldRuntimeType.IsPrimitive
                                    || fieldValue is string
                                    || fieldValue is decimal
                                    || fieldValue is Enum
                                )
                                {
                                    valueText =
                                        fieldValue.ToString();
                                }
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType =
                                "<ERROR:"
                                + ex.GetType().Name
                                + ">";

                            identity = "<ERROR>";
                            valueText = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[BVEEX_HOST_REFERENCE] INSTANCE_FIELD "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{field.Name}, "
                            + $"DeclaredType:{field.FieldType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"IsAtsMain:{isAtsMain}, "
                            + $"Identity:{identity}, "
                            + $"Value:{valueText}"
                        );
                    }

                    System.Reflection.PropertyInfo[] instanceProperties =
                        currentType.GetProperties(
                            declaredInstanceFlags
                        );

                    foreach (
                        System.Reflection.PropertyInfo property
                        in instanceProperties
                    )
                    {
                        if (
                            !property.CanRead
                            || property.GetIndexParameters().Length != 0
                        )
                        {
                            continue;
                        }

                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";
                        bool isAtsMain = false;

                        try
                        {
                            object propertyValue =
                                property.GetValue(
                                    this,
                                    null
                                );

                            if (propertyValue != null)
                            {
                                runtimeType =
                                    propertyValue
                                        .GetType()
                                        .FullName;

                                identity =
                                    GetObjectIdentity(
                                        propertyValue
                                    );

                                isAtsMain =
                                    string.Equals(
                                        propertyValue
                                            .GetType()
                                            .FullName,
                                        "AtsPlugin.AtsMain",
                                        StringComparison.Ordinal
                                    );
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType =
                                "<ERROR:"
                                + ex.GetType().Name
                                + ">";

                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[BVEEX_HOST_REFERENCE] INSTANCE_PROPERTY "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{property.Name}, "
                            + $"DeclaredType:{property.PropertyType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"IsAtsMain:{isAtsMain}, "
                            + $"Identity:{identity}"
                        );
                    }

                    currentType = currentType.BaseType;
                    hierarchyLevel++;
                }

                object bveHackerObject = BveHacker;

                if (bveHackerObject == null)
                {
                    rtLog.AppendLine(
                        "[BVEEX_HOST_REFERENCE] BVEHACKER "
                        + "RuntimeType:<NULL>"
                    );
                }
                else
                {
                    Type bveHackerType = bveHackerObject.GetType();

                    rtLog.AppendLine(
                        "[BVEEX_HOST_REFERENCE] TYPE "
                        + "Source:BveHackerRuntime, "
                        + $"Type:{bveHackerType.FullName}, "
                        + $"Assembly:{bveHackerType.Assembly.GetName().Name}"
                    );

                    Type currentBveHackerType = bveHackerType;
                    int bveHackerLevel = 0;

                    while (currentBveHackerType != null)
                    {
                        rtLog.AppendLine(
                            "[BVEEX_HOST_REFERENCE] TYPE "
                            + "Source:BveHackerHierarchy, "
                            + $"Level:{bveHackerLevel}, "
                            + $"Type:{currentBveHackerType.FullName}, "
                            + $"Assembly:{currentBveHackerType.Assembly.GetName().Name}"
                        );

                        System.Reflection.FieldInfo[] bveHackerFields =
                            currentBveHackerType.GetFields(
                                declaredInstanceFlags
                            );

                        foreach (
                            System.Reflection.FieldInfo field
                            in bveHackerFields
                        )
                        {
                            string runtimeType = "<NULL>";
                            string identity = "<NULL>";
                            bool isAtsMain = false;

                            try
                            {
                                object fieldValue =
                                    field.GetValue(bveHackerObject);

                                if (fieldValue != null)
                                {
                                    runtimeType =
                                        fieldValue.GetType().FullName;
                                    identity =
                                        GetObjectIdentity(fieldValue);
                                    isAtsMain =
                                        string.Equals(
                                            fieldValue.GetType().FullName,
                                            "AtsPlugin.AtsMain",
                                            StringComparison.Ordinal
                                        );
                                }
                            }
                            catch (Exception ex)
                            {
                                runtimeType =
                                    "<ERROR:"
                                    + ex.GetType().Name
                                    + ">";
                                identity = "<ERROR>";
                            }

                            rtLog.AppendLine(
                                "[BVEEX_HOST_REFERENCE] BVEHACKER_FIELD "
                                + $"Level:{bveHackerLevel}, "
                                + $"DeclaringType:{currentBveHackerType.FullName}, "
                                + $"Name:{field.Name}, "
                                + $"DeclaredType:{field.FieldType.FullName}, "
                                + $"RuntimeType:{runtimeType}, "
                                + $"IsAtsMain:{isAtsMain}, "
                                + $"Identity:{identity}"
                            );
                        }

                        System.Reflection.PropertyInfo[] bveHackerProperties =
                            currentBveHackerType.GetProperties(
                                declaredInstanceFlags
                            );

                        foreach (
                            System.Reflection.PropertyInfo property
                            in bveHackerProperties
                        )
                        {
                            if (
                                !property.CanRead
                                || property.GetIndexParameters().Length != 0
                            )
                            {
                                continue;
                            }

                            string runtimeType = "<NULL>";
                            string identity = "<NULL>";
                            bool isAtsMain = false;

                            try
                            {
                                object propertyValue =
                                    property.GetValue(
                                        bveHackerObject,
                                        null
                                    );

                                if (propertyValue != null)
                                {
                                    runtimeType =
                                        propertyValue.GetType().FullName;
                                    identity =
                                        GetObjectIdentity(propertyValue);
                                    isAtsMain =
                                        string.Equals(
                                            propertyValue.GetType().FullName,
                                            "AtsPlugin.AtsMain",
                                            StringComparison.Ordinal
                                        );
                                }
                            }
                            catch (Exception ex)
                            {
                                runtimeType =
                                    "<ERROR:"
                                    + ex.GetType().Name
                                    + ">";
                                identity = "<ERROR>";
                            }

                            rtLog.AppendLine(
                                "[BVEEX_HOST_REFERENCE] BVEHACKER_PROPERTY "
                                + $"Level:{bveHackerLevel}, "
                                + $"DeclaringType:{currentBveHackerType.FullName}, "
                                + $"Name:{property.Name}, "
                                + $"DeclaredType:{property.PropertyType.FullName}, "
                                + $"RuntimeType:{runtimeType}, "
                                + $"IsAtsMain:{isAtsMain}, "
                                + $"Identity:{identity}"
                            );
                        }

                        currentBveHackerType =
                            currentBveHackerType.BaseType;
                        bveHackerLevel++;
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEEX_HOST_REFERENCE] END "
                    + "ScoringEnabled:False"
                );

                hasDumpedBveExHostReferences = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedBveExHostReferenceError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[BVEEX_HOST_REFERENCE] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedBveExHostReferenceError = true;
                    hasChanges = true;
                }
            }
        }

        // =========================================================
        // PluginBase.Extensionsが参照するExtensionSetを1階層だけ調べる。
        // 内部コレクションがあれば、格納要素の型とアセンブリを列挙する。
        // 現段階では診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseExtensionSet(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedExtensionSet)
            {
                return;
            }

            try
            {
                object extensionSetObject = Extensions;

                if (extensionSetObject == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[EXTENSION_SET_DIAGNOSTIC] WAIT "
                        + "Reason:ExtensionsIsNull, "
                        + "ScoringEnabled:False"
                    );
                    hasChanges = true;
                    return;
                }

                System.Reflection.BindingFlags declaredFlags =
                    System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                Type extensionSetType = extensionSetObject.GetType();

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[EXTENSION_SET_DIAGNOSTIC] START "
                    + $"Type:{extensionSetType.FullName}, "
                    + $"Assembly:{extensionSetType.Assembly.GetName().Name}, "
                    + $"Identity:{GetObjectIdentity(extensionSetObject)}, "
                    + "ScoringEnabled:False"
                );

                Type currentType = extensionSetType;
                int hierarchyLevel = 0;

                while (currentType != null)
                {
                    rtLog.AppendLine(
                        "[EXTENSION_SET_DIAGNOSTIC] TYPE "
                        + $"Level:{hierarchyLevel}, "
                        + $"Type:{currentType.FullName}, "
                        + $"Assembly:{currentType.Assembly.GetName().Name}"
                    );

                    System.Reflection.FieldInfo[] fields =
                        currentType.GetFields(declaredFlags);

                    foreach (System.Reflection.FieldInfo field in fields)
                    {
                        object value = null;
                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";
                        string collectionKind = "None";
                        int itemCount = 0;

                        try
                        {
                            value = field.GetValue(extensionSetObject);

                            if (value != null)
                            {
                                runtimeType = value.GetType().FullName;
                                identity = GetObjectIdentity(value);
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[EXTENSION_SET_DIAGNOSTIC] FIELD "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{field.Name}, "
                            + $"DeclaredType:{field.FieldType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}"
                        );

                        System.Collections.IEnumerable enumerable =
                            value as System.Collections.IEnumerable;

                        if (enumerable != null && !(value is string))
                        {
                            collectionKind = "Enumerable";

                            foreach (object item in enumerable)
                            {
                                LogExtensionSetItem(
                                    rtLog,
                                    "Field:" + field.Name,
                                    itemCount,
                                    item
                                );
                                itemCount++;

                                if (itemCount >= 200)
                                {
                                    rtLog.AppendLine(
                                        "[EXTENSION_SET_DIAGNOSTIC] COLLECTION_LIMIT "
                                        + $"Source:Field:{field.Name}, "
                                        + "Limit:200"
                                    );
                                    break;
                                }
                            }
                        }

                        if (collectionKind != "None")
                        {
                            rtLog.AppendLine(
                                "[EXTENSION_SET_DIAGNOSTIC] COLLECTION "
                                + $"Source:Field:{field.Name}, "
                                + $"Kind:{collectionKind}, "
                                + $"ItemCount:{itemCount}"
                            );
                        }
                    }

                    System.Reflection.PropertyInfo[] properties =
                        currentType.GetProperties(declaredFlags);

                    foreach (
                        System.Reflection.PropertyInfo property
                        in properties
                    )
                    {
                        if (
                            !property.CanRead
                            || property.GetIndexParameters().Length != 0
                        )
                        {
                            continue;
                        }

                        object value = null;
                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";

                        try
                        {
                            value = property.GetValue(
                                extensionSetObject,
                                null
                            );

                            if (value != null)
                            {
                                runtimeType = value.GetType().FullName;
                                identity = GetObjectIdentity(value);
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[EXTENSION_SET_DIAGNOSTIC] PROPERTY "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{property.Name}, "
                            + $"DeclaredType:{property.PropertyType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}"
                        );
                    }

                    currentType = currentType.BaseType;
                    hierarchyLevel++;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[EXTENSION_SET_DIAGNOSTIC] END "
                    + "ScoringEnabled:False"
                );

                hasDumpedExtensionSet = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedExtensionSetError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[EXTENSION_SET_DIAGNOSTIC] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedExtensionSetError = true;
                    hasChanges = true;
                }
            }
        }

        private void LogExtensionSetItem(
            StringBuilder rtLog,
            string source,
            int index,
            object item
        )
        {
            if (item == null)
            {
                rtLog.AppendLine(
                    "[EXTENSION_SET_DIAGNOSTIC] ITEM "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + "Value:<NULL>"
                );
                return;
            }

            Type itemType = item.GetType();

            rtLog.AppendLine(
                "[EXTENSION_SET_DIAGNOSTIC] ITEM "
                + $"Source:{source}, "
                + $"Index:{index}, "
                + $"RuntimeType:{itemType.FullName}, "
                + $"Identity:{GetObjectIdentity(item)}"
            );

            System.Reflection.BindingFlags memberFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;

            System.Reflection.PropertyInfo keyProperty =
                itemType.GetProperty("Key", memberFlags);
            System.Reflection.PropertyInfo valueProperty =
                itemType.GetProperty("Value", memberFlags);

            if (keyProperty == null || valueProperty == null)
            {
                LogExtensionSetObject(
                    rtLog,
                    source + ":Item",
                    index,
                    item,
                    false
                );
                return;
            }

            object keyObject = null;
            object valueObject = null;

            try
            {
                keyObject = keyProperty.GetValue(item, null);
            }
            catch (Exception ex)
            {
                rtLog.AppendLine(
                    "[EXTENSION_SET_DIAGNOSTIC] KEY_ERROR "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + $"Type:{ex.GetType().FullName}, "
                    + $"Message:{ex.Message}"
                );
            }

            try
            {
                valueObject = valueProperty.GetValue(item, null);
            }
            catch (Exception ex)
            {
                rtLog.AppendLine(
                    "[EXTENSION_SET_DIAGNOSTIC] VALUE_ERROR "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + $"Type:{ex.GetType().FullName}, "
                    + $"Message:{ex.Message}"
                );
            }

            string keyTypeName = "<NULL>";
            string keyAssemblyName = "<NULL>";
            string keyLocation = "<NULL>";
            string keySha256 = "<NULL>";

            Type keyTypeValue = keyObject as Type;

            if (keyTypeValue != null)
            {
                keyTypeName = keyTypeValue.FullName;
                keyAssemblyName = keyTypeValue.Assembly.GetName().Name;
                GetAssemblyIdentity(
                    keyTypeValue.Assembly,
                    out keyLocation,
                    out keySha256
                );
            }
            else if (keyObject != null)
            {
                keyTypeName = keyObject.ToString();
                keyAssemblyName = keyObject.GetType().Assembly.GetName().Name;
                GetAssemblyIdentity(
                    keyObject.GetType().Assembly,
                    out keyLocation,
                    out keySha256
                );
            }

            rtLog.AppendLine(
                "[EXTENSION_SET_DIAGNOSTIC] ENTRY "
                + $"Source:{source}, "
                + $"Index:{index}, "
                + $"Key:{keyTypeName}, "
                + $"KeyAssembly:{keyAssemblyName}, "
                + $"KeyLocation:{keyLocation}, "
                + $"KeySHA256:{keySha256}, "
                + $"ValueType:{(valueObject != null ? valueObject.GetType().FullName : "<NULL>")}, "
                + $"ValueIdentity:{GetObjectIdentity(valueObject)}"
            );

            LogExtensionSetObject(
                rtLog,
                source + ":Value",
                index,
                valueObject,
                true
            );
        }

        private void LogExtensionSetObject(
            StringBuilder rtLog,
            string source,
            int index,
            object target,
            bool expandMembers
        )
        {
            if (target == null)
            {
                rtLog.AppendLine(
                    "[EXTENSION_SET_DIAGNOSTIC] OBJECT "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + "Value:<NULL>"
                );
                return;
            }

            Type targetType = target.GetType();
            string location;
            string sha256;

            GetAssemblyIdentity(
                targetType.Assembly,
                out location,
                out sha256
            );

            rtLog.AppendLine(
                "[EXTENSION_SET_DIAGNOSTIC] OBJECT "
                + $"Source:{source}, "
                + $"Index:{index}, "
                + $"RuntimeType:{targetType.FullName}, "
                + $"Assembly:{targetType.Assembly.GetName().Name}, "
                + $"Location:{location}, "
                + $"SHA256:{sha256}, "
                + $"Identity:{GetObjectIdentity(target)}, "
                + $"IsAtsMain:{IsKnownAtsMainObject(target)}"
            );

            if (!expandMembers)
            {
                return;
            }

            System.Reflection.BindingFlags memberFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.DeclaredOnly;

            Type currentType = targetType;
            int hierarchyLevel = 0;

            while (currentType != null)
            {
                System.Reflection.FieldInfo[] fields =
                    currentType.GetFields(memberFlags);

                foreach (System.Reflection.FieldInfo field in fields)
                {
                    object memberValue = null;
                    string runtimeType = "<NULL>";
                    string identity = "<NULL>";
                    bool isAtsMain = false;

                    try
                    {
                        memberValue = field.GetValue(target);

                        if (memberValue != null)
                        {
                            runtimeType = memberValue.GetType().FullName;
                            identity = GetObjectIdentity(memberValue);
                            isAtsMain = IsKnownAtsMainObject(memberValue);
                        }
                    }
                    catch (Exception ex)
                    {
                        runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                        identity = "<ERROR>";
                    }

                    rtLog.AppendLine(
                        "[EXTENSION_SET_DIAGNOSTIC] MEMBER_FIELD "
                        + $"Source:{source}, "
                        + $"Index:{index}, "
                        + $"Level:{hierarchyLevel}, "
                        + $"DeclaringType:{currentType.FullName}, "
                        + $"Name:{field.Name}, "
                        + $"DeclaredType:{field.FieldType.FullName}, "
                        + $"RuntimeType:{runtimeType}, "
                        + $"Identity:{identity}, "
                        + $"IsAtsMain:{isAtsMain}"
                    );

                    if (isAtsMain)
                    {
                        LogAtsPtMainCandidate(
                            rtLog,
                            source + ":Field:" + field.Name,
                            index,
                            memberValue
                        );
                    }
                }

                System.Reflection.PropertyInfo[] properties =
                    currentType.GetProperties(memberFlags);

                foreach (
                    System.Reflection.PropertyInfo property
                    in properties
                )
                {
                    if (
                        !property.CanRead
                        || property.GetIndexParameters().Length != 0
                    )
                    {
                        continue;
                    }

                    object memberValue = null;
                    string runtimeType = "<NULL>";
                    string identity = "<NULL>";
                    bool isAtsMain = false;

                    try
                    {
                        memberValue = property.GetValue(target, null);

                        if (memberValue != null)
                        {
                            runtimeType = memberValue.GetType().FullName;
                            identity = GetObjectIdentity(memberValue);
                            isAtsMain = IsKnownAtsMainObject(memberValue);
                        }
                    }
                    catch (Exception ex)
                    {
                        runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                        identity = "<ERROR>";
                    }

                    rtLog.AppendLine(
                        "[EXTENSION_SET_DIAGNOSTIC] MEMBER_PROPERTY "
                        + $"Source:{source}, "
                        + $"Index:{index}, "
                        + $"Level:{hierarchyLevel}, "
                        + $"DeclaringType:{currentType.FullName}, "
                        + $"Name:{property.Name}, "
                        + $"DeclaredType:{property.PropertyType.FullName}, "
                        + $"RuntimeType:{runtimeType}, "
                        + $"Identity:{identity}, "
                        + $"IsAtsMain:{isAtsMain}"
                    );

                    if (isAtsMain)
                    {
                        LogAtsPtMainCandidate(
                            rtLog,
                            source + ":Property:" + property.Name,
                            index,
                            memberValue
                        );
                    }
                }

                currentType = currentType.BaseType;
                hierarchyLevel++;
            }
        }

        private bool IsKnownAtsMainObject(object value)
        {
            if (value == null)
            {
                return false;
            }

            Type valueType = value.GetType();

            if (
                !string.Equals(
                    valueType.FullName,
                    "AtsPlugin.AtsMain",
                    StringComparison.Ordinal
                )
            )
            {
                return false;
            }

            string location;
            string sha256;

            GetAssemblyIdentity(
                valueType.Assembly,
                out location,
                out sha256
            );

            return
                string.Equals(
                    sha256,
                    "9A75F078C8CF8198C5E4970052DE7504C010CA28B68D93CFD66FEC6110949FE4",
                    StringComparison.OrdinalIgnoreCase
                )
                || string.Equals(
                    sha256,
                    "AF9DDE58B4D987F32E77A9C3DA0929A2EB5D244527FD83DBF5AB5A3E434A35B7",
                    StringComparison.OrdinalIgnoreCase
                );
        }

        private void GetAssemblyIdentity(
            System.Reflection.Assembly assembly,
            out string location,
            out string sha256
        )
        {
            location = "<UNAVAILABLE>";
            sha256 = "<UNAVAILABLE>";

            if (assembly == null)
            {
                return;
            }

            try
            {
                location = assembly.Location;

                if (
                    !string.IsNullOrWhiteSpace(location)
                    && System.IO.File.Exists(location)
                )
                {
                    sha256 = ComputeFileSha256(location);
                }
            }
            catch
            {
                location = "<UNAVAILABLE>";
                sha256 = "<UNAVAILABLE>";
            }
        }

        private void LogAtsPtMainCandidate(
            StringBuilder rtLog,
            string source,
            int index,
            object atsMainObject
        )
        {
            if (atsMainObject == null)
            {
                return;
            }

            Type atsMainType = atsMainObject.GetType();
            System.Reflection.BindingFlags memberFlags =
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic
                | System.Reflection.BindingFlags.FlattenHierarchy;

            System.Reflection.FieldInfo atsPtField =
                atsMainType.GetField("AtsPT", memberFlags);
            object atsPtObject = null;

            if (atsPtField != null)
            {
                try
                {
                    atsPtObject = atsPtField.GetValue(atsMainObject);
                }
                catch
                {
                    atsPtObject = null;
                }
            }

            rtLog.AppendLine(
                "[EXTENSION_SET_DIAGNOSTIC] ATSMAIN_CANDIDATE "
                + $"Source:{source}, "
                + $"Index:{index}, "
                + $"MainIdentity:{GetObjectIdentity(atsMainObject)}, "
                + $"AtsPtFieldFound:{atsPtField != null}, "
                + $"AtsPtRuntimeType:{(atsPtObject != null ? atsPtObject.GetType().FullName : "<NULL>")}, "
                + $"AtsPtIdentity:{GetObjectIdentity(atsPtObject)}"
            );
        }

        // =========================================================
        // BveEx関連アセンブリの型から、静的に保持されている
        // プラグイン管理オブジェクトとコレクションを探索する。
        // 対象はBveEx、BveEx.PluginHost、BveEx.CoreExtensionsに限定する。
        // =========================================================
        private void DiagnoseBveExStaticPluginHosts(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedBveExStaticPluginHosts)
            {
                return;
            }

            try
            {
                string[] targetAssemblyNames =
                {
                    "BveEx",
                    "BveEx.PluginHost",
                    "BveEx.CoreExtensions"
                };

                string[] interestingNames =
                {
                    "plugin",
                    "vehicle",
                    "host",
                    "builder",
                    "loaded",
                    "item"
                };

                System.Reflection.BindingFlags staticFlags =
                    System.Reflection.BindingFlags.Static
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                System.Reflection.BindingFlags instanceFlags =
                    System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                int assemblyCount = 0;
                int candidateMemberCount = 0;
                int collectionItemCount = 0;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEEX_STATIC_PLUGIN_HOST] START "
                    + "ScoringEnabled:False"
                );

                foreach (
                    System.Reflection.Assembly assembly
                    in AppDomain.CurrentDomain.GetAssemblies()
                )
                {
                    if (assembly == null)
                    {
                        continue;
                    }

                    string assemblyName = assembly.GetName().Name;

                    if (!targetAssemblyNames.Contains(assemblyName))
                    {
                        continue;
                    }

                    assemblyCount++;
                    Type[] types;

                    try
                    {
                        types = assembly.GetTypes();
                    }
                    catch (
                        System.Reflection.ReflectionTypeLoadException ex
                    )
                    {
                        types = ex.Types.Where(type => type != null).ToArray();
                    }
                    catch
                    {
                        types = new Type[0];
                    }

                    rtLog.AppendLine(
                        "[BVEEX_STATIC_PLUGIN_HOST] ASSEMBLY "
                        + $"Name:{assemblyName}, "
                        + $"TypeCount:{types.Length}"
                    );

                    foreach (Type type in types)
                    {
                        if (type == null)
                        {
                            continue;
                        }

                        System.Reflection.FieldInfo[] fields =
                            type.GetFields(staticFlags);

                        foreach (System.Reflection.FieldInfo field in fields)
                        {
                            if (!IsInterestingPluginHostMember(
                                field.Name,
                                field.FieldType,
                                interestingNames
                            ))
                            {
                                continue;
                            }

                            candidateMemberCount++;
                            object value = null;
                            string runtimeType = "<NULL>";
                            string identity = "<NULL>";

                            try
                            {
                                value = field.GetValue(null);

                                if (value != null)
                                {
                                    runtimeType = value.GetType().FullName;
                                    identity = GetObjectIdentity(value);
                                }
                            }
                            catch (Exception ex)
                            {
                                runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                                identity = "<ERROR>";
                            }

                            rtLog.AppendLine(
                                "[BVEEX_STATIC_PLUGIN_HOST] FIELD "
                                + $"Assembly:{assemblyName}, "
                                + $"DeclaringType:{type.FullName}, "
                                + $"Name:{field.Name}, "
                                + $"DeclaredType:{field.FieldType.FullName}, "
                                + $"RuntimeType:{runtimeType}, "
                                + $"Identity:{identity}, "
                                + $"IsAtsMain:{IsKnownAtsMainObject(value)}"
                            );

                            collectionItemCount +=
                                LogStaticPluginHostValue(
                                    rtLog,
                                    "Field:" + type.FullName + "." + field.Name,
                                    value,
                                    instanceFlags
                                );
                        }

                        System.Reflection.PropertyInfo[] properties =
                            type.GetProperties(staticFlags);

                        foreach (
                            System.Reflection.PropertyInfo property
                            in properties
                        )
                        {
                            if (
                                !property.CanRead
                                || property.GetIndexParameters().Length != 0
                                || !IsInterestingPluginHostMember(
                                    property.Name,
                                    property.PropertyType,
                                    interestingNames
                                )
                            )
                            {
                                continue;
                            }

                            System.Reflection.MethodInfo getter =
                                property.GetGetMethod(true);

                            if (getter == null || !getter.IsStatic)
                            {
                                continue;
                            }

                            candidateMemberCount++;
                            object value = null;
                            string runtimeType = "<NULL>";
                            string identity = "<NULL>";

                            try
                            {
                                value = property.GetValue(null, null);

                                if (value != null)
                                {
                                    runtimeType = value.GetType().FullName;
                                    identity = GetObjectIdentity(value);
                                }
                            }
                            catch (Exception ex)
                            {
                                runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                                identity = "<ERROR>";
                            }

                            rtLog.AppendLine(
                                "[BVEEX_STATIC_PLUGIN_HOST] PROPERTY "
                                + $"Assembly:{assemblyName}, "
                                + $"DeclaringType:{type.FullName}, "
                                + $"Name:{property.Name}, "
                                + $"DeclaredType:{property.PropertyType.FullName}, "
                                + $"RuntimeType:{runtimeType}, "
                                + $"Identity:{identity}, "
                                + $"IsAtsMain:{IsKnownAtsMainObject(value)}"
                            );

                            collectionItemCount +=
                                LogStaticPluginHostValue(
                                    rtLog,
                                    "Property:" + type.FullName + "." + property.Name,
                                    value,
                                    instanceFlags
                                );
                        }
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEEX_STATIC_PLUGIN_HOST] END "
                    + $"AssemblyCount:{assemblyCount}, "
                    + $"CandidateMemberCount:{candidateMemberCount}, "
                    + $"CollectionItemCount:{collectionItemCount}, "
                    + "ScoringEnabled:False"
                );

                hasDumpedBveExStaticPluginHosts = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedBveExStaticPluginHostError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[BVEEX_STATIC_PLUGIN_HOST] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedBveExStaticPluginHostError = true;
                    hasChanges = true;
                }
            }
        }

        private bool IsInterestingPluginHostMember(
            string memberName,
            Type memberType,
            string[] interestingNames
        )
        {
            string normalizedName = memberName ?? "";
            string normalizedType =
                memberType != null ? memberType.FullName ?? "" : "";

            foreach (string interestingName in interestingNames)
            {
                if (
                    normalizedName.IndexOf(
                        interestingName,
                        StringComparison.OrdinalIgnoreCase
                    ) >= 0
                    || normalizedType.IndexOf(
                        interestingName,
                        StringComparison.OrdinalIgnoreCase
                    ) >= 0
                )
                {
                    return true;
                }
            }

            if (memberType == null)
            {
                return false;
            }

            return
                typeof(System.Collections.IEnumerable)
                    .IsAssignableFrom(memberType)
                && memberType != typeof(string);
        }

        private int LogStaticPluginHostValue(
            StringBuilder rtLog,
            string source,
            object value,
            System.Reflection.BindingFlags instanceFlags
        )
        {
            if (value == null)
            {
                return 0;
            }

            if (IsKnownAtsMainObject(value))
            {
                LogAtsPtMainCandidate(rtLog, source, 0, value);
                return 1;
            }

            System.Collections.IEnumerable enumerable =
                value as System.Collections.IEnumerable;

            if (enumerable == null || value is string)
            {
                return 0;
            }

            int index = 0;

            foreach (object item in enumerable)
            {
                object keyObject = null;
                object valueObject = item;

                if (item != null)
                {
                    Type itemType = item.GetType();
                    System.Reflection.PropertyInfo keyProperty =
                        itemType.GetProperty("Key", instanceFlags);
                    System.Reflection.PropertyInfo valueProperty =
                        itemType.GetProperty("Value", instanceFlags);

                    if (keyProperty != null && valueProperty != null)
                    {
                        try
                        {
                            keyObject = keyProperty.GetValue(item, null);
                            valueObject = valueProperty.GetValue(item, null);
                        }
                        catch
                        {
                            keyObject = null;
                            valueObject = item;
                        }
                    }
                }

                string keyText =
                    keyObject != null ? keyObject.ToString() : "<NONE>";
                string itemRuntimeType =
                    item != null ? item.GetType().FullName : "<NULL>";
                string valueRuntimeType =
                    valueObject != null
                        ? valueObject.GetType().FullName
                        : "<NULL>";
                bool valueIsAtsMain = IsKnownAtsMainObject(valueObject);

                rtLog.AppendLine(
                    "[BVEEX_STATIC_PLUGIN_HOST] ITEM "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + $"Key:{keyText}, "
                    + $"ItemRuntimeType:{itemRuntimeType}, "
                    + $"ValueRuntimeType:{valueRuntimeType}, "
                    + $"ValueIdentity:{GetObjectIdentity(valueObject)}, "
                    + $"IsAtsMain:{valueIsAtsMain}"
                );

                if (valueIsAtsMain)
                {
                    LogAtsPtMainCandidate(
                        rtLog,
                        source + ":Item",
                        index,
                        valueObject
                    );
                }

                index++;

                if (index >= 500)
                {
                    rtLog.AppendLine(
                        "[BVEEX_STATIC_PLUGIN_HOST] COLLECTION_LIMIT "
                        + $"Source:{source}, "
                        + "Limit:500"
                    );
                    break;
                }
            }

            return index;
        }

        // =========================================================
        // BveEx.PluginHost.App.Instanceを取得し、型階層ごとの
        // インスタンスフィールドとプロパティを1階層だけ調べる。
        // コレクションがあれば要素も展開する。
        // =========================================================
        private void DiagnosePluginHostApp(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedPluginHostApp)
            {
                return;
            }

            try
            {
                System.Reflection.Assembly pluginHostAssembly =
                    AppDomain.CurrentDomain.GetAssemblies()
                        .FirstOrDefault(
                            assembly =>
                                assembly != null
                                && string.Equals(
                                    assembly.GetName().Name,
                                    "BveEx.PluginHost",
                                    StringComparison.Ordinal
                                )
                        );

                if (pluginHostAssembly == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[PLUGIN_HOST_APP] WAIT "
                        + "Reason:PluginHostAssemblyNotFound, "
                        + "ScoringEnabled:False"
                    );
                    hasChanges = true;
                    return;
                }

                Type appType =
                    pluginHostAssembly.GetType(
                        "BveEx.PluginHost.App",
                        false
                    );

                if (appType == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[PLUGIN_HOST_APP] WAIT "
                        + "Reason:AppTypeNotFound, "
                        + "ScoringEnabled:False"
                    );
                    hasChanges = true;
                    return;
                }

                System.Reflection.BindingFlags staticFlags =
                    System.Reflection.BindingFlags.Static
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                System.Reflection.PropertyInfo instanceProperty =
                    appType.GetProperty("Instance", staticFlags);
                object appObject = null;

                if (instanceProperty != null && instanceProperty.CanRead)
                {
                    appObject = instanceProperty.GetValue(null, null);
                }

                if (appObject == null)
                {
                    System.Reflection.FieldInfo instanceField =
                        appType.GetField(
                            "<Instance>k__BackingField",
                            staticFlags
                        );

                    if (instanceField != null)
                    {
                        appObject = instanceField.GetValue(null);
                    }
                }

                if (appObject == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[PLUGIN_HOST_APP] WAIT "
                        + "Reason:AppInstanceIsNull, "
                        + "ScoringEnabled:False"
                    );
                    hasChanges = true;
                    return;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[PLUGIN_HOST_APP] START "
                    + $"Type:{appObject.GetType().FullName}, "
                    + $"Identity:{GetObjectIdentity(appObject)}, "
                    + "ScoringEnabled:False"
                );

                System.Reflection.BindingFlags instanceFlags =
                    System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                Type currentType = appObject.GetType();
                int hierarchyLevel = 0;
                int collectionItemCount = 0;

                while (currentType != null)
                {
                    rtLog.AppendLine(
                        "[PLUGIN_HOST_APP] TYPE "
                        + $"Level:{hierarchyLevel}, "
                        + $"Type:{currentType.FullName}, "
                        + $"Assembly:{currentType.Assembly.GetName().Name}"
                    );

                    System.Reflection.FieldInfo[] fields =
                        currentType.GetFields(instanceFlags);

                    foreach (System.Reflection.FieldInfo field in fields)
                    {
                        object value = null;
                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";

                        try
                        {
                            value = field.GetValue(appObject);

                            if (value != null)
                            {
                                runtimeType = value.GetType().FullName;
                                identity = GetObjectIdentity(value);
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[PLUGIN_HOST_APP] FIELD "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{field.Name}, "
                            + $"DeclaredType:{field.FieldType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}, "
                            + $"IsAtsMain:{IsKnownAtsMainObject(value)}"
                        );

                        collectionItemCount +=
                            LogPluginHostAppCollection(
                                rtLog,
                                "Field:" + currentType.FullName + "." + field.Name,
                                value,
                                instanceFlags
                            );
                    }

                    System.Reflection.PropertyInfo[] properties =
                        currentType.GetProperties(instanceFlags);

                    foreach (
                        System.Reflection.PropertyInfo property
                        in properties
                    )
                    {
                        if (
                            !property.CanRead
                            || property.GetIndexParameters().Length != 0
                        )
                        {
                            continue;
                        }

                        object value = null;
                        string runtimeType = "<NULL>";
                        string identity = "<NULL>";

                        try
                        {
                            value = property.GetValue(appObject, null);

                            if (value != null)
                            {
                                runtimeType = value.GetType().FullName;
                                identity = GetObjectIdentity(value);
                            }
                        }
                        catch (Exception ex)
                        {
                            runtimeType = "<ERROR:" + ex.GetType().Name + ">";
                            identity = "<ERROR>";
                        }

                        rtLog.AppendLine(
                            "[PLUGIN_HOST_APP] PROPERTY "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Name:{property.Name}, "
                            + $"DeclaredType:{property.PropertyType.FullName}, "
                            + $"RuntimeType:{runtimeType}, "
                            + $"Identity:{identity}, "
                            + $"IsAtsMain:{IsKnownAtsMainObject(value)}"
                        );

                        collectionItemCount +=
                            LogPluginHostAppCollection(
                                rtLog,
                                "Property:" + currentType.FullName + "." + property.Name,
                                value,
                                instanceFlags
                            );
                    }

                    currentType = currentType.BaseType;
                    hierarchyLevel++;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[PLUGIN_HOST_APP] END "
                    + $"CollectionItemCount:{collectionItemCount}, "
                    + "ScoringEnabled:False"
                );

                hasDumpedPluginHostApp = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedPluginHostAppError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[PLUGIN_HOST_APP] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedPluginHostAppError = true;
                    hasChanges = true;
                }
            }
        }

        private int LogPluginHostAppCollection(
            StringBuilder rtLog,
            string source,
            object value,
            System.Reflection.BindingFlags instanceFlags
        )
        {
            if (value == null)
            {
                return 0;
            }

            if (IsKnownAtsMainObject(value))
            {
                LogAtsPtMainCandidate(rtLog, source, 0, value);
                return 1;
            }

            System.Collections.IEnumerable enumerable =
                value as System.Collections.IEnumerable;

            if (enumerable == null || value is string)
            {
                return 0;
            }

            int index = 0;

            foreach (object item in enumerable)
            {
                object keyObject = null;
                object valueObject = item;

                if (item != null)
                {
                    Type itemType = item.GetType();
                    System.Reflection.PropertyInfo keyProperty =
                        itemType.GetProperty("Key", instanceFlags);
                    System.Reflection.PropertyInfo valueProperty =
                        itemType.GetProperty("Value", instanceFlags);

                    if (keyProperty != null && valueProperty != null)
                    {
                        try
                        {
                            keyObject = keyProperty.GetValue(item, null);
                            valueObject = valueProperty.GetValue(item, null);
                        }
                        catch
                        {
                            keyObject = null;
                            valueObject = item;
                        }
                    }
                }

                bool valueIsAtsMain = IsKnownAtsMainObject(valueObject);

                rtLog.AppendLine(
                    "[PLUGIN_HOST_APP] ITEM "
                    + $"Source:{source}, "
                    + $"Index:{index}, "
                    + $"Key:{(keyObject != null ? keyObject.ToString() : "<NONE>")}, "
                    + $"ItemRuntimeType:{(item != null ? item.GetType().FullName : "<NULL>")}, "
                    + $"ValueRuntimeType:{(valueObject != null ? valueObject.GetType().FullName : "<NULL>")}, "
                    + $"ValueIdentity:{GetObjectIdentity(valueObject)}, "
                    + $"IsAtsMain:{valueIsAtsMain}"
                );

                if (valueIsAtsMain)
                {
                    LogAtsPtMainCandidate(
                        rtLog,
                        source + ":Item",
                        index,
                        valueObject
                    );
                }

                index++;

                if (index >= 500)
                {
                    rtLog.AppendLine(
                        "[PLUGIN_HOST_APP] COLLECTION_LIMIT "
                        + $"Source:{source}, "
                        + "Limit:500"
                    );
                    break;
                }
            }

            return index;
        }

        // =========================================================
        // BveHackerが保持するイベントデリゲートのInvocationListを展開し、
        // コールバックのTargetから実行中プラグインを逆引きする。
        // 既知AtsPT5のAtsMainを発見した場合はAtsPTまで確認する。
        // =========================================================
        private void DiagnoseBveHackerEventTargets(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            if (hasDumpedBveHackerEventTargets)
            {
                return;
            }

            try
            {
                object bveHackerObject = BveHacker;

                if (bveHackerObject == null)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[BVEHACKER_EVENT_TARGET] WAIT "
                        + "Reason:BveHackerIsNull, "
                        + "ScoringEnabled:False"
                    );
                    hasChanges = true;
                    return;
                }

                System.Reflection.BindingFlags declaredInstanceFlags =
                    System.Reflection.BindingFlags.Instance
                    | System.Reflection.BindingFlags.Public
                    | System.Reflection.BindingFlags.NonPublic
                    | System.Reflection.BindingFlags.DeclaredOnly;

                int eventFieldCount = 0;
                int invocationCount = 0;
                int atsMainCount = 0;
                Type currentType = bveHackerObject.GetType();
                int hierarchyLevel = 0;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEHACKER_EVENT_TARGET] START "
                    + $"BveHackerType:{currentType.FullName}, "
                    + $"Identity:{GetObjectIdentity(bveHackerObject)}, "
                    + "ScoringEnabled:False"
                );

                while (currentType != null)
                {
                    System.Reflection.FieldInfo[] fields =
                        currentType.GetFields(declaredInstanceFlags);

                    foreach (System.Reflection.FieldInfo field in fields)
                    {
                        if (!typeof(Delegate).IsAssignableFrom(field.FieldType))
                        {
                            continue;
                        }

                        eventFieldCount++;
                        Delegate eventDelegate = null;

                        try
                        {
                            eventDelegate = field.GetValue(bveHackerObject) as Delegate;
                        }
                        catch (Exception ex)
                        {
                            rtLog.AppendLine(
                                "[BVEHACKER_EVENT_TARGET] FIELD_ERROR "
                                + $"Level:{hierarchyLevel}, "
                                + $"DeclaringType:{currentType.FullName}, "
                                + $"Field:{field.Name}, "
                                + $"Type:{ex.GetType().FullName}, "
                                + $"Message:{ex.Message}"
                            );
                            continue;
                        }

                        if (eventDelegate == null)
                        {
                            rtLog.AppendLine(
                                "[BVEHACKER_EVENT_TARGET] EVENT "
                                + $"Level:{hierarchyLevel}, "
                                + $"DeclaringType:{currentType.FullName}, "
                                + $"Field:{field.Name}, "
                                + $"DelegateType:{field.FieldType.FullName}, "
                                + "InvocationCount:0"
                            );
                            continue;
                        }

                        Delegate[] invocationList =
                            eventDelegate.GetInvocationList();

                        rtLog.AppendLine(
                            "[BVEHACKER_EVENT_TARGET] EVENT "
                            + $"Level:{hierarchyLevel}, "
                            + $"DeclaringType:{currentType.FullName}, "
                            + $"Field:{field.Name}, "
                            + $"DelegateType:{field.FieldType.FullName}, "
                            + $"InvocationCount:{invocationList.Length}"
                        );

                        for (int index = 0; index < invocationList.Length; index++)
                        {
                            Delegate invocation = invocationList[index];
                            object target = invocation.Target;
                            System.Reflection.MethodInfo methodInfo = invocation.Method;
                            Type targetType = target != null ? target.GetType() : null;
                            string targetAssembly =
                                targetType != null
                                    ? targetType.Assembly.GetName().Name
                                    : "<NULL>";
                            string targetLocation = "<NULL>";
                            string targetSha256 = "<NULL>";

                            if (targetType != null)
                            {
                                GetAssemblyIdentity(
                                    targetType.Assembly,
                                    out targetLocation,
                                    out targetSha256
                                );
                            }

                            bool isAtsMain = IsKnownAtsMainObject(target);

                            if (isAtsMain)
                            {
                                atsMainCount++;
                            }

                            invocationCount++;

                            rtLog.AppendLine(
                                "[BVEHACKER_EVENT_TARGET] INVOCATION "
                                + $"EventField:{field.Name}, "
                                + $"Index:{index}, "
                                + $"Method:{(methodInfo != null ? methodInfo.Name : "<NULL>")}, "
                                + $"MethodDeclaringType:{(methodInfo != null && methodInfo.DeclaringType != null ? methodInfo.DeclaringType.FullName : "<NULL>")}, "
                                + $"MethodIsStatic:{(methodInfo != null && methodInfo.IsStatic)}, "
                                + $"TargetRuntimeType:{(targetType != null ? targetType.FullName : "<NULL>")}, "
                                + $"TargetAssembly:{targetAssembly}, "
                                + $"TargetLocation:{targetLocation}, "
                                + $"TargetSHA256:{targetSha256}, "
                                + $"TargetIdentity:{GetObjectIdentity(target)}, "
                                + $"IsAtsMain:{isAtsMain}"
                            );

                            if (isAtsMain)
                            {
                                LogAtsPtMainCandidate(
                                    rtLog,
                                    "BveHackerEvent:" + field.Name,
                                    index,
                                    target
                                );
                            }
                        }
                    }

                    currentType = currentType.BaseType;
                    hierarchyLevel++;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[BVEHACKER_EVENT_TARGET] END "
                    + $"EventFieldCount:{eventFieldCount}, "
                    + $"InvocationCount:{invocationCount}, "
                    + $"AtsMainCount:{atsMainCount}, "
                    + "ScoringEnabled:False"
                );

                hasDumpedBveHackerEventTargets = true;
                hasChanges = true;
            }
            catch (Exception ex)
            {
                if (!hasLoggedBveHackerEventTargetError)
                {
                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[BVEHACKER_EVENT_TARGET] ERROR "
                        + $"Type:{ex.GetType().FullName}, "
                        + $"Message:{ex.Message}, "
                        + "ScoringEnabled:False"
                    );

                    hasLoggedBveHackerEventTargetError = true;
                    hasChanges = true;
                }
            }
        }

        // =========================================================
        // 中央西線系AtsPT5の内部要求を汎用管理オブジェクト経路から取得する。
        // このメソッドが移行後の主経路であり、旧専用経路は値の比較だけに使う。
        // =========================================================
        private void DiagnoseManagedPrimaryRuntimeState(
            int physicalBrake,
            int atsBrake,
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            ManagedRuntimeResolution resolution;
            if (
                !managedRuntimeResolutions.TryGetValue(
                    "ChuoWestAtsPt5",
                    out resolution
                )
                || resolution == null
                || !resolution.HasValidatedMembers
                || !resolution.HasCurrentRequestBrake
                || !resolution.HasCurrentEmergencyState
                || !resolution.HasCurrentSecurityEmergencyState
            )
            {
                return;
            }

            string requestKind = resolution.CurrentRequestKind;
            int requestBrake = resolution.CurrentRequestBrakeCandidate;
            bool stateChanged =
                !hasPreviousManagedPrimaryState
                || !string.Equals(
                    requestKind,
                    previousManagedPrimaryRequestKind,
                    StringComparison.Ordinal
                )
                || requestBrake != previousManagedPrimaryRequestBrake
                || physicalBrake != previousManagedPrimaryPhysicalBrake
                || atsBrake != previousManagedPrimaryAtsBrake;

            if (!stateChanged)
            {
                return;
            }

            bool hiddenByPhysical =
                requestBrake > 0
                && physicalBrake >= requestBrake;
            bool atsOutputMatchesRequest =
                requestBrake > 0
                && atsBrake == requestBrake;

            rtLog.AppendLine(
                $"[{DateTime.Now:HH:mm:ss.fff}] "
                + "[MANAGED_RUNTIME] PRIMARY_STATE "
                + $"Profile:{resolution.Profile.Id}, "
                + "Source:ManagedRuntimeProfile, "
                + $"RequestKind:{requestKind}, "
                + $"RequestBrake:{requestBrake}, "
                + $"Physical:{physicalBrake}, "
                + $"AtsOutput:{atsBrake}, "
                + $"AtsOutputMatchesRequest:{atsOutputMatchesRequest}, "
                + $"HiddenByPhysical:{hiddenByPhysical}, "
                + $"TargetIdentity:{GetObjectIdentity(resolution.TargetObject)}, "
                + "LegacyRole:ComparisonOnly, "
                + "ScoringEnabled:False"
            );

            hasPreviousManagedPrimaryState = true;
            previousManagedPrimaryRequestKind = requestKind;
            previousManagedPrimaryRequestBrake = requestBrake;
            previousManagedPrimaryPhysicalBrake = physicalBrake;
            previousManagedPrimaryAtsBrake = atsBrake;
            hasChanges = true;
        }

        // =========================================================
        // 阪急ATSの世代別診断プロファイルを登録する。
        // 両者はDLL全体を同一視せず、ブレーキ統合出口だけを
        // 独立した診断対象として扱う。
        // =========================================================
        private void RegisterHankyuDiagnosticRuntimeProfiles()
        {
            RuntimeProfileIdentity newGeneration =
                new RuntimeProfileIdentity();
            newGeneration.Sha256 =
                "5434FE58D3978A4CFF5521B1C7111C8C266D428382D82EA326E59F3568572EBC";
            newGeneration.Pattern =
                "HankyuAtsHkNewGeneration";
            newGeneration.VerificationStatus =
                "DynamicReverificationPending";
            newGeneration.DetectionStrategy =
                "HankyuEmergencyRequestState";
            newGeneration.DetectionPriority =
                "EmergencyOnly";
            newGeneration.DetectionCompletionStatus =
                "DiagnosticOnly";
            newGeneration.HankyuInputBrakeRva = 0x14464;
            newGeneration.HankyuOutputBrakeRva = 0x142A0;
            newGeneration.HankyuRequestActiveRva = 0x143E0;
            newGeneration.HankyuRequestedBrakeRva = 0x1435C;
            runtimeProfilesByHash[newGeneration.Sha256] =
                newGeneration;

            RuntimeProfileIdentity atsHk110 =
                new RuntimeProfileIdentity();
            atsHk110.Sha256 =
                "98DBBBE2A98676EBF23EF9739C0053A0B4DF58175C59481DA13529A3D08B1929";
            atsHk110.Pattern =
                "HankyuAtsHk110";
            atsHk110.VerificationStatus =
                "DynamicVerificationPassed";
            atsHk110.DetectionStrategy =
                "HankyuEmergencyRequestState";
            atsHk110.DetectionPriority =
                "EmergencyOnly";
            atsHk110.DetectionCompletionStatus =
                "DiagnosticOnly";
            atsHk110.HankyuInputBrakeRva = 0x14464;
            atsHk110.HankyuOutputBrakeRva = 0x142A0;
            atsHk110.HankyuRequestActiveRva = 0x143E0;
            atsHk110.HankyuRequestedBrakeRva = 0x1435C;
            runtimeProfilesByHash[atsHk110.Sha256] =
                atsHk110;

            RuntimeProfileIdentity legacy =
                new RuntimeProfileIdentity();
            legacy.Sha256 =
                "E6FBDD73D1FE25FB1D5913E414170981795F653ACCC7EFF3E6BA42913B665D6F";
            legacy.Pattern =
                "HankyuAtsHkLegacy";
            legacy.VerificationStatus =
                "DynamicVerificationPending";
            legacy.DetectionStrategy =
                "HankyuEmergencyRequestState";
            legacy.DetectionPriority =
                "RawSafetyRequest";
            legacy.DetectionCompletionStatus =
                "DiagnosticOnly";
            legacy.HankyuInputBrakeRva = 0x7048;
            legacy.HankyuOutputBrakeRva = 0x7064;
            legacy.HankyuRequestActiveRva = 0x70FC;
            legacy.HankyuRequestedBrakeRva = 0x7040;
            runtimeProfilesByHash[legacy.Sha256] =
                legacy;
            // 阪急5300系配布物の別ハッシュ。
            // 静的解析でAlternate配置と同じブレーキ統合出口を確認した。
            // 動的再検証中のため、採点には接続しない。
            RuntimeProfileIdentity hankyu5300AlternateCandidate =
                new RuntimeProfileIdentity();
            hankyu5300AlternateCandidate.Sha256 =
                "B55A083C58620E2F07404E1980F77EF2959D3D2B1DB92B5674AA869FBF7DBF7C";
            hankyu5300AlternateCandidate.Pattern =
                "HankyuAtsHk5300Alternate";
            hankyu5300AlternateCandidate.VerificationStatus =
                "DynamicVerificationPassed";
            hankyu5300AlternateCandidate.DetectionStrategy =
                "HankyuEmergencyRequestState";
            hankyu5300AlternateCandidate.DetectionPriority =
                "RawSafetyRequest";
            hankyu5300AlternateCandidate.DetectionCompletionStatus =
                "DiagnosticOnly";
            hankyu5300AlternateCandidate.HankyuInputBrakeRva = 0x7028;
            hankyu5300AlternateCandidate.HankyuOutputBrakeRva = 0x7044;
            hankyu5300AlternateCandidate.HankyuRequestActiveRva = 0x70DC;
            hankyu5300AlternateCandidate.HankyuRequestedBrakeRva = 0x7020;
            runtimeProfilesByHash[hankyu5300AlternateCandidate.Sha256] =
                hankyu5300AlternateCandidate;

            RuntimeProfileIdentity alternate =
                new RuntimeProfileIdentity();
            alternate.Sha256 =
                "0D69F0D0E305609F80C0AFC363F23864109A27AF6D18918667D3F22CB644C1E7";
            alternate.Pattern =
                "HankyuAtsHkAlternate";
            alternate.VerificationStatus =
                "DynamicVerificationPending";
            alternate.DetectionStrategy =
                "HankyuEmergencyRequestState";
            alternate.DetectionPriority =
                "RawSafetyRequest";
            alternate.DetectionCompletionStatus =
                "DiagnosticOnly";
            alternate.HankyuInputBrakeRva = 0x7028;
            alternate.HankyuOutputBrakeRva = 0x7044;
            alternate.HankyuRequestActiveRva = 0x70DC;
            alternate.HankyuRequestedBrakeRva = 0x7020;
            runtimeProfilesByHash[alternate.Sha256] =
                alternate;

            RuntimeProfileIdentity b8Legacy =
                new RuntimeProfileIdentity();
            b8Legacy.Sha256 =
                "77FB95B3868180D00A5E882695A839CB1BF950E064249734F3CECF54CFE1BD82";
            b8Legacy.Pattern =
                "HankyuAtsHkB8Legacy";
            b8Legacy.VerificationStatus =
                "DynamicVerificationPending";
            b8Legacy.DetectionStrategy =
                "HankyuEmergencyRequestState";
            b8Legacy.DetectionPriority =
                "RawSafetyRequest";
            b8Legacy.DetectionCompletionStatus =
                "DiagnosticOnly";
            b8Legacy.HankyuInputBrakeRva = 0x7048;
            b8Legacy.HankyuOutputBrakeRva = 0x7064;
            b8Legacy.HankyuRequestActiveRva = 0x70FC;
            b8Legacy.HankyuRequestedBrakeRva = 0x7044;
            runtimeProfilesByHash[b8Legacy.Sha256] =
                b8Legacy;
        }

        // =========================================================
        // 南海ATS-PNの診断プロファイルを登録する。
        // requestState先頭2バイトはATS-PN内部で4系統を集約した結果で、
        // +0が非常要求、+1が常用最大要求を表す。
        // =========================================================
        private void RegisterNankaiDiagnosticRuntimeProfiles()
        {
            RuntimeProfileIdentity atsN32 =
                new RuntimeProfileIdentity();
            atsN32.Sha256 =
                "D714B4C073F21E900324F79194E0EBD6EA3678208FDA269FB4AC081588310E00";
            atsN32.Pattern =
                "NankaiAtsNEmergencyRequestState32";
            atsN32.VerificationStatus =
                "DynamicallyVerified";
            atsN32.DetectionStrategy =
                "NankaiAtsNEmergencyRequestState";
            atsN32.DetectionPriority =
                "EmergencyOnly";
            atsN32.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            atsN32.NankaiNEmergencyFlagRva = 0x16368;
            runtimeProfilesByHash[atsN32.Sha256] = atsN32;

            RuntimeProfileIdentity atsN64 =
                new RuntimeProfileIdentity();
            atsN64.Sha256 =
                "2EF29897B76489CB08FBD2131A5B0DC3421632F6B35D9243E14EEF3C61421B89";
            atsN64.Pattern =
                "NankaiAtsNEmergencyRequestState64";
            atsN64.VerificationStatus =
                "DynamicallyVerified";
            atsN64.DetectionStrategy =
                "NankaiAtsNEmergencyRequestState";
            atsN64.DetectionPriority =
                "EmergencyOnly";
            atsN64.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            atsN64.NankaiNEmergencyFlagRva = 0x1BC78;
            runtimeProfilesByHash[atsN64.Sha256] = atsN64;

            RuntimeProfileIdentity atsPn32 =
                new RuntimeProfileIdentity();
            atsPn32.Sha256 =
                "7A87B40BABAE6FFF81E6BE368DBF5BC8944B66ECF1FFAF7AC28284415F750F29";
            atsPn32.Pattern =
                "NankaiAtsPnAggregatedRequestState32";
            atsPn32.VerificationStatus =
                "DynamicallyVerified";
            atsPn32.DetectionStrategy =
                "NankaiAtsPnAggregatedRequestState";
            atsPn32.DetectionPriority =
                "EmergencyThenServiceMaximum";
            atsPn32.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            atsPn32.NankaiPnRequestStatePointerRva = 0x6DBD4;
            atsPn32.NankaiPnEmergencyOffset = 0x00;
            atsPn32.NankaiPnServiceMaximumOffset = 0x01;
            runtimeProfilesByHash[atsPn32.Sha256] = atsPn32;

            RuntimeProfileIdentity atsPn64 =
                new RuntimeProfileIdentity();
            atsPn64.Sha256 =
                "F86E2133F8EFC3AB51369B5A2811E7E265906872F6E2D5DC83F36AFFA13CDCED";
            atsPn64.Pattern =
                "NankaiAtsPnAggregatedRequestState64";
            atsPn64.VerificationStatus =
                "DynamicallyVerified";
            atsPn64.DetectionStrategy =
                "NankaiAtsPnAggregatedRequestState";
            atsPn64.DetectionPriority =
                "EmergencyThenServiceMaximum";
            atsPn64.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            atsPn64.NankaiPnRequestStatePointerRva = 0x86E20;
            atsPn64.NankaiPnEmergencyOffset = 0x00;
            atsPn64.NankaiPnServiceMaximumOffset = 0x01;
            runtimeProfilesByHash[atsPn64.Sha256] = atsPn64;
            RuntimeProfileIdentity legacyAtsN =
                new RuntimeProfileIdentity();
            legacyAtsN.Sha256 =
                "BB5E34D69ED07E77E35001AAA9A8733E7B6768A690F861792301308A20237513";
            legacyAtsN.Pattern =
                "NankaiLegacyAtsNEmergencyRequestState32";
            legacyAtsN.VerificationStatus =
                "DynamicallyVerified";
            legacyAtsN.DetectionStrategy =
                "NankaiAtsNEmergencyRequestState";
            legacyAtsN.DetectionPriority =
                "EmergencyOnly";
            legacyAtsN.DetectionCompletionStatus =
                "DiagnosticOnly";
            legacyAtsN.NankaiNEmergencyFlagRva = 0x33A5;
            runtimeProfilesByHash[legacyAtsN.Sha256] = legacyAtsN;
            RuntimeProfileIdentity legacyAtsPn =
                new RuntimeProfileIdentity();
            legacyAtsPn.Sha256 =
                "D244535325458BEEDE93EE3CE05C6C4A298E095706D2A77B83844DBB18F8175B";
            legacyAtsPn.Pattern =
                "NankaiLegacyAtsPnDirectRequestState32";
            legacyAtsPn.VerificationStatus =
                "DynamicVerificationPending";
            legacyAtsPn.DetectionStrategy =
                "NankaiLegacyAtsPnDirectRequestState";
            legacyAtsPn.DetectionPriority =
                "EmergencyThenServiceMaximum";
            legacyAtsPn.DetectionCompletionStatus =
                "DiagnosticOnly";
            legacyAtsPn.NankaiLegacyPnServiceSourceARva = 0x1587C;
            legacyAtsPn.NankaiLegacyPnServiceSourceBRva = 0x15880;
            legacyAtsPn.NankaiLegacyPnServiceSourceCRva = 0x15884;
            legacyAtsPn.NankaiLegacyPnEmergencyFlagRva = 0x15895;
            runtimeProfilesByHash[legacyAtsPn.Sha256] = legacyAtsPn;
        }
        // =========================================================
        // NNN式C-ATSの共通x86版cats2.dllを診断対象へ登録する。
        // 現段階では動的検証専用であり、採点には接続しない。
        // =========================================================
        private void RegisterNnnCatsDiagnosticRuntimeProfiles()
        {
            RuntimeProfileIdentity cats2CommonX86 =
                new RuntimeProfileIdentity();
            cats2CommonX86.Sha256 =
                "EDBB3B53396ACB20D1AFBC155C37D7ACD9BD3E89FC74886528DF41FC59E96DAF";
            cats2CommonX86.Pattern =
                "NnnCats2CommonX86RequestState";
            cats2CommonX86.VerificationStatus =
                "DynamicallyVerified";
            cats2CommonX86.DetectionStrategy =
                "NnnCatsRequestState";
            cats2CommonX86.DetectionPriority =
                "EmergencyThenServiceMaximum";
            cats2CommonX86.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            cats2CommonX86.NnnCatsDriverBrakeRva = 0x3840C;
            cats2CommonX86.NnnCatsEmergencyNotchRva = 0x38410;
            cats2CommonX86.NnnCatsReturnedBrakeRva = 0x383D0;
            cats2CommonX86.NnnCatsSafetyFlagRva = 0x38424;
            cats2CommonX86.NnnCatsMainStateRva = 0x38780;
            cats2CommonX86.NnnCatsRequestStatePointerRva = 0x3878C;
            cats2CommonX86.NnnCatsMode0RequestStateRva = 0x3863C;
            cats2CommonX86.NnnCatsMode1RequestStateRva = 0x386C0;
            runtimeProfilesByHash[cats2CommonX86.Sha256] =
                cats2CommonX86;

            // 都営5300系向けNNN式C-ATSのx86版cats2.dll。
            // 共通x86版と要求状態構造は同じだが、安全フラグRVAが異なる。
            RuntimeProfileIdentity cats2Toei5300X86 =
                new RuntimeProfileIdentity();
            cats2Toei5300X86.Sha256 =
                "E1C2FCE0C717BC5F203E43BFB96891658EDF46B5AF97B9AC8647A74FFD1783BC";
            cats2Toei5300X86.Pattern =
                "NnnCats2Toei5300X86RequestState";
            cats2Toei5300X86.VerificationStatus =
                "DynamicallyVerified";
            cats2Toei5300X86.DetectionStrategy =
                "NnnCatsRequestState";
            cats2Toei5300X86.DetectionPriority =
                "EmergencyThenServiceMaximum";
            cats2Toei5300X86.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            cats2Toei5300X86.NnnCatsDriverBrakeRva = 0x3840C;
            cats2Toei5300X86.NnnCatsEmergencyNotchRva = 0x38410;
            cats2Toei5300X86.NnnCatsReturnedBrakeRva = 0x383D0;
            cats2Toei5300X86.NnnCatsSafetyFlagRva = 0x3842C;
            cats2Toei5300X86.NnnCatsMainStateRva = 0x38780;
            cats2Toei5300X86.NnnCatsRequestStatePointerRva = 0x3878C;
            cats2Toei5300X86.NnnCatsMode0RequestStateRva = 0;
            cats2Toei5300X86.NnnCatsMode1RequestStateRva = 0;
            runtimeProfilesByHash[cats2Toei5300X86.Sha256] =
                cats2Toei5300X86;

            RuntimeProfileIdentity cats2CommonX64 =
                new RuntimeProfileIdentity();
            cats2CommonX64.Sha256 =
                "B8EB45820967243F01D50E8EA194669A2F0AABCC81745C73FF76E338081A062E";
            cats2CommonX64.Pattern =
                "NnnCats2CommonX64RequestState";
            cats2CommonX64.VerificationStatus =
                "DynamicallyVerified";
            cats2CommonX64.DetectionStrategy =
                "NnnCatsRequestState";
            cats2CommonX64.DetectionPriority =
                "EmergencyThenServiceMaximum";
            cats2CommonX64.DetectionCompletionStatus =
                "ClosedDiagnosticReadout";
            cats2CommonX64.NnnCatsDriverBrakeRva = 0x1477C;
            cats2CommonX64.NnnCatsEmergencyNotchRva = 0x14780;
            cats2CommonX64.NnnCatsReturnedBrakeRva = 0x14740;
            cats2CommonX64.NnnCatsSafetyFlagRva = 0x14798;
            cats2CommonX64.NnnCatsMainStateRva = 0x14B30;
            cats2CommonX64.NnnCatsRequestStatePointerRva = 0x14B48;
            // x64版のモード別状態RVAは未確定。
            // 選択中状態ポインターの逆参照を主経路とする。
            cats2CommonX64.NnnCatsMode0RequestStateRva = 0;
            cats2CommonX64.NnnCatsMode1RequestStateRva = 0;
            runtimeProfilesByHash[cats2CommonX64.Sha256] =
                cats2CommonX64;
        }

        // =========================================================
        // 共通ランタイムプロファイルを読み込み,
        // ロード済みDLLとSHA-256で照合する
        //
        // 現段階では診断ログだけを出力し、減点には接続しない。
        // =========================================================
        // =========================================================
        // SWP2 Group A/B/Cをハッシュ別に登録する。
        // 装置別のATS-S要求とATS-P要求を復元し、最大値だけを診断する。
        // Panelと物理ブレーキは要求値の取得元に使わない。
        // =========================================================
        private void RegisterSwp2DeviceAggregatedRuntimeProfiles()
        {
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "1C74CE23AF4DBF1BBCFA9CC459C7899128EC4FFEFF2D597BFB6B802C540899DD",
                "Swp2GroupADeviceAggregatedRequest",
                "A",
                0x5CAA0,
                0x348,
                0x354,
                0x3B4
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "2E075FB26088D4D4508CB3F19FA25D25E3DF90E2CB0EEC25CBB69E705E325790",
                "Swp2GroupBDeviceAggregatedRequest",
                "B",
                0x52600,
                0,
                0,
                0
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "7EE150FED44B4E3E853D50AAF75E338CCB77C5AD0313EE1107CC44C0F288816B",
                "Swp2GroupA7Ee1DeviceAggregatedRequest",
                "A7EE1",
                0x5CAA0,
                0x308,
                0,
                0x364
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "BAB4C566762D3F8C07AF81541F953251A8201E263897F82B6BE0E64B6B25368F",
                "Swp2GroupBBab4DeviceAggregatedRequest",
                "BAB4",
                0x505E8,
                0,
                0,
                0
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "17D207995B096852BF28EAD51B20C6E8C144831D907F7C3F86CCBC75F4A437BB",
                "Swp2X64NamedValueAggregatedRequest",
                "X64",
                0x70EC8,
                0,
                0,
                0
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "DDB456B080588ED6DC0A270B3B36602DAF3F118DF262EAAD329F582A5F8401B4",
                "Swp2GroupCDdb4DeviceAggregatedRequest",
                "C",
                0x67A28,
                0x328,
                0x334,
                0x39C
            );
            RegisterSwp2DeviceAggregatedRuntimeProfile(
                "6E25B31C799BF09662DFFFACEE3C281D5E84A29DC28F3D3A796C13B152ACD92C",
                "Swp2GroupC6E25DeviceAggregatedRequest",
                "C",
                0x69A38,
                0x328,
                0x334,
                0x39C
            );
        }

        private void RegisterSwp2DeviceAggregatedRuntimeProfile(
            string sha256,
            string pattern,
            string group,
            int rootPointerRva,
            int atsPBrakeOffset,
            int atsPApplyOffset,
            int atsSActiveOffset
        )
        {
            RuntimeProfileIdentity profile = new RuntimeProfileIdentity();
            profile.Sha256 = sha256;
            profile.Pattern = pattern;
            profile.VerificationStatus = "StaticConfirmedDynamicVerificationPending";
            profile.DetectionStrategy = "Swp2DeviceAggregatedRequest";
            profile.DetectionPriority = "MaxAtsSAndAtsP";
            profile.DetectionCompletionStatus = "DiagnosticOnly";
            profile.Swp2Group = group;
            profile.Swp2RootPointerRva = rootPointerRva;
            profile.Swp2AtsPBrakeOffset = atsPBrakeOffset;
            profile.Swp2AtsPApplyOffset = atsPApplyOffset;
            profile.Swp2AtsSActiveOffset = atsSActiveOffset;
            runtimeProfilesByHash[profile.Sha256] = profile;
        }

        // =========================================================
        // BAB4の名前付き値マップを外部から読取り専用で探索する。
        // DLL内部関数の呼出し、フック、メモリ書込みは行わない。
        //
        // map + 0x04 = head/sentinel
        // head + 0x04 = root node
        // node + 0x00 = left
        // node + 0x08 = right
        // node + 0x10 = key address
        // node + 0x18 = double value
        // node + 0x29 = nil flag
        // =========================================================
        private bool TryReadSwp2Bab4NamedDouble(
            RuntimeProfileIdentity profile,
            IntPtr root,
            int keyRva,
            out double value,
            out string failureStage
        )
        {
            value = 0.0;
            failureStage = "None";

            if (
                profile == null
                || profile.ModuleBaseAddress == IntPtr.Zero
                || root == IntPtr.Zero
                || keyRva == 0
            )
            {
                failureStage = "Bab4NamedValueArguments";
                return false;
            }

            IntPtr mapAddress = IntPtr.Add(root, 0x68);
            IntPtr head;
            if (!TryReadRuntimePointer32(IntPtr.Add(mapAddress, 0x04), out head))
            {
                failureStage = "Bab4MapHead";
                return false;
            }

            IntPtr node;
            if (!TryReadRuntimePointer32(IntPtr.Add(head, 0x04), out node))
            {
                failureStage = "Bab4MapRoot";
                return false;
            }

            uint targetKey = unchecked(
                (uint)IntPtr.Add(profile.ModuleBaseAddress, keyRva).ToInt64()
            );
            System.Collections.Generic.HashSet<long> visited =
                new System.Collections.Generic.HashSet<long>();

            for (int depth = 0; depth < 256; depth++)
            {
                if (
                    node == IntPtr.Zero
                    || node == head
                    || !visited.Add(node.ToInt64())
                )
                {
                    failureStage = "Bab4MapNotFound";
                    return false;
                }

                byte nilFlag;
                if (!TryReadRuntimeByte(IntPtr.Add(node, 0x29), out nilFlag))
                {
                    failureStage = "Bab4MapNilFlag";
                    return false;
                }
                if (nilFlag != 0)
                {
                    failureStage = "Bab4MapNotFound";
                    return false;
                }

                IntPtr nodeKeyAddress;
                if (!TryReadRuntimePointer32(IntPtr.Add(node, 0x10), out nodeKeyAddress))
                {
                    failureStage = "Bab4MapKey";
                    return false;
                }

                uint nodeKey = unchecked((uint)nodeKeyAddress.ToInt64());
                if (nodeKey == targetKey)
                {
                    if (!TryReadRuntimeDouble(IntPtr.Add(node, 0x18), out value))
                    {
                        failureStage = "Bab4MapValue";
                        return false;
                    }
                    return true;
                }

                int childOffset = targetKey < nodeKey ? 0x00 : 0x08;
                IntPtr nextNode;
                if (!TryReadRuntimePointer32(IntPtr.Add(node, childOffset), out nextNode))
                {
                    failureStage = "Bab4MapChild";
                    return false;
                }
                node = nextNode;
            }

            failureStage = "Bab4MapDepthLimit";
            return false;
        }

        // =========================================================
        // BAB4のATS-P・ATS-S要求を名前付き値マップから復元する。
        // ats_p_work_brakeは作動ゲート、brake_notch_indicatorは要求段、
        // ats_s_workはATS-S作動状態として扱う。eb_workは診断表示のみで、
        // ATS-P/ATS-S要求へ混ぜない。
        // =========================================================
        private bool TryReadSwp2Bab4Request(
            RuntimeProfileIdentity profile,
            IntPtr root,
            out int atsPRequest,
            out int atsSRequest,
            out string detail,
            out string failureStage
        )
        {
            atsPRequest = 0;
            atsSRequest = 0;
            detail = "";
            failureStage = "None";

            double atsPWorkBrake;
            if (!TryReadSwp2Bab4NamedDouble(
                profile,
                root,
                0x45F24,
                out atsPWorkBrake,
                out failureStage
            ))
            {
                return false;
            }

            double brakeNotchIndicator;
            if (!TryReadSwp2Bab4NamedDouble(
                profile,
                root,
                0x45F70,
                out brakeNotchIndicator,
                out failureStage
            ))
            {
                return false;
            }

            double atsSWork;
            if (!TryReadSwp2Bab4NamedDouble(
                profile,
                root,
                0x45F00,
                out atsSWork,
                out failureStage
            ))
            {
                return false;
            }

            double ebWork;
            if (!TryReadSwp2Bab4NamedDouble(
                profile,
                root,
                0x45FE8,
                out ebWork,
                out failureStage
            ))
            {
                return false;
            }

            int indicatorRounded = (int)Math.Round(
                brakeNotchIndicator,
                MidpointRounding.AwayFromZero
            );
            bool indicatorIsIntegral =
                Math.Abs(brakeNotchIndicator - indicatorRounded) < 0.001;
            bool indicatorSpecial10 = indicatorRounded == 10;
            bool indicatorInRange =
                indicatorIsIntegral
                && indicatorRounded >= 0
                && emergencyBrakeNotch > 0
                && indicatorRounded <= emergencyBrakeNotch;
            bool atsPActive = Math.Abs(atsPWorkBrake) > 0.001;
            bool atsSActive = Math.Abs(atsSWork) > 0.001;
            bool ebActive = Math.Abs(ebWork) > 0.001;

            atsPRequest =
                atsPActive && indicatorInRange && !indicatorSpecial10
                    ? indicatorRounded
                    : 0;
            atsSRequest =
                atsSActive && emergencyBrakeNotch > 0
                    ? emergencyBrakeNotch
                    : 0;

            detail =
                "Source:NamedValueMap"
                + ",AtsPWorkBrake:" + atsPWorkBrake.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                + ",BrakeNotchIndicator:" + brakeNotchIndicator.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                + ",IndicatorRounded:" + indicatorRounded
                + ",IndicatorSpecial10:" + indicatorSpecial10
                + ",IndicatorInRange:" + indicatorInRange
                + ",AtsSWork:" + atsSWork.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                + ",EbWork:" + ebWork.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                + ",EbActiveDiagnosticOnly:" + ebActive
                + ",MapOffset:0x68"
                + ",NativeFunctionCalled:False"
                + ",MemoryWritePerformed:False";
            return true;
        }

        private bool TryReadSwp2GroupBRequest(
            RuntimeProfileIdentity profile,
            IntPtr root,
            out int atsPRequest,
            out int atsSRequest,
            out string detail,
            out string failureStage
        )
        {
            atsPRequest = 0;
            atsSRequest = 0;
            detail = "";
            failureStage = "None";

            IntPtr atsSObject;
            IntPtr atsSManager;
            IntPtr atsSTimer;
            IntPtr clockAddress;
            IntPtr notchInfo;
            int now;
            int deadline;
            int internalEmergencyNotch;
            byte timerFinished;
            byte timerAuxiliary;

            if (!TryReadRuntimePointer32(IntPtr.Add(root, 0x10), out atsSObject))
            {
                failureStage = "AtsSObject";
                return false;
            }
            if (!TryReadRuntimePointer32(IntPtr.Add(atsSObject, 0x04), out atsSManager))
            {
                failureStage = "AtsSManager";
                return false;
            }
            if (!TryReadRuntimePointer32(IntPtr.Add(atsSObject, 0x14), out atsSTimer))
            {
                failureStage = "AtsSTimer";
                return false;
            }
            if (!TryReadRuntimePointer32(IntPtr.Add(atsSManager, 0x10), out clockAddress))
            {
                failureStage = "AtsSClock";
                return false;
            }
            if (!TryReadRuntimePointer32(IntPtr.Add(atsSManager, 0x04), out notchInfo))
            {
                failureStage = "NotchInfo";
                return false;
            }
            if (
                !TryReadRuntimeInt32(clockAddress, out now)
                || !TryReadRuntimeInt32(atsSTimer, out deadline)
                || !TryReadRuntimeInt32(IntPtr.Add(notchInfo, 0x10), out internalEmergencyNotch)
                || !TryReadRuntimeByte(IntPtr.Add(atsSTimer, 0x04), out timerFinished)
                || !TryReadRuntimeByte(IntPtr.Add(atsSTimer, 0x05), out timerAuxiliary)
            )
            {
                failureStage = "AtsSState";
                return false;
            }
            bool atsSEmergency =
                timerFinished == 0
                && now >= deadline
                && timerAuxiliary == 0;
            if (atsSEmergency)
            {
                atsSRequest = internalEmergencyNotch;
            }

            IntPtr atsPManager;
            IntPtr atsPState;
            if (!TryReadRuntimePointer32(IntPtr.Add(root, 0x18), out atsPManager))
            {
                failureStage = "AtsPManager";
                return false;
            }
            if (!TryReadRuntimePointer32(IntPtr.Add(atsPManager, 0x10), out atsPState))
            {
                failureStage = "AtsPState";
                return false;
            }
            byte state2C;
            byte state2D;
            byte state30;
            if (
                !TryReadRuntimeByte(IntPtr.Add(atsPState, 0x2C), out state2C)
                || !TryReadRuntimeByte(IntPtr.Add(atsPState, 0x2D), out state2D)
                || !TryReadRuntimeByte(IntPtr.Add(atsPState, 0x30), out state30)
            )
            {
                failureStage = "AtsPFlags";
                return false;
            }
            List<byte> latches = new List<byte>();
            bool anyLatch = false;
            bool useRepresentativeGroupBLatches = string.Equals(
                profile.Swp2Group,
                "B",
                StringComparison.Ordinal
            );
            if (useRepresentativeGroupBLatches)
            {
                for (int rva = 0x52618; rva <= 0x5261E; rva++)
                {
                    byte latch;
                    if (!TryReadRuntimeByte(IntPtr.Add(profile.ModuleBaseAddress, rva), out latch))
                    {
                        failureStage = "AtsPLatches";
                        return false;
                    }
                    latches.Add(latch);
                    if (latch != 0)
                    {
                        anyLatch = true;
                    }
                }
            }
            if (state2D != 0 || state30 != 0)
            {
                atsPRequest = internalEmergencyNotch;
            }
            else if (state2C != 0 || anyLatch)
            {
                atsPRequest = Math.Max(0, internalEmergencyNotch - 1);
            }
            detail =
                "AtsSObject:0x" + atsSObject.ToInt64().ToString("X")
                + ",AtsPState:0x" + atsPState.ToInt64().ToString("X")
                + ",State2C:" + state2C
                + ",State2D:" + state2D
                + ",State30:" + state30
                + ",Latches:" + string.Join("|", latches)
                + ",Layout:" + profile.Swp2Group
                + ",AtsPSource:State2C2D30"
                + ",Now:" + now
                + ",Deadline:" + deadline
                + ",TimerFinished:" + timerFinished
                + ",TimerAuxiliary:" + timerAuxiliary
                + ",InternalEmergencyNotch:" + internalEmergencyNotch;
            return true;
        }

        private bool TryReadSwp2X64String(
            IntPtr stringAddress,
            out string value
        )
        {
            value = "";
            long length;
            long capacity;
            try
            {
                length = System.Runtime.InteropServices.Marshal.ReadInt64(
                    IntPtr.Add(stringAddress, 0x10)
                );
                capacity = System.Runtime.InteropServices.Marshal.ReadInt64(
                    IntPtr.Add(stringAddress, 0x18)
                );
            }
            catch
            {
                return false;
            }
            if (length < 0 || length > 256 || capacity < length)
            {
                return false;
            }
            IntPtr characters = stringAddress;
            if (capacity > 15)
            {
                if (!TryReadRuntimePointer(stringAddress, out characters))
                {
                    return false;
                }
            }
            byte[] bytes = new byte[(int)length];
            try
            {
                for (int index = 0; index < bytes.Length; index++)
                {
                    bytes[index] = System.Runtime.InteropServices.Marshal.ReadByte(
                        characters,
                        index
                    );
                }
                value = System.Text.Encoding.ASCII.GetString(bytes);
                return true;
            }
            catch
            {
                value = "";
                return false;
            }
        }

        private bool TryReadSwp2X64NamedInt32(
            IntPtr mapAddress,
            string key,
            out int value
        )
        {
            value = 0;
            IntPtr head;
            if (!TryReadRuntimePointer(IntPtr.Add(mapAddress, 0x08), out head))
            {
                return false;
            }
            IntPtr root;
            if (!TryReadRuntimePointer(IntPtr.Add(head, 0x08), out root))
            {
                return false;
            }
            System.Collections.Generic.Stack<IntPtr> pending =
                new System.Collections.Generic.Stack<IntPtr>();
            System.Collections.Generic.HashSet<long> visited =
                new System.Collections.Generic.HashSet<long>();
            pending.Push(root);
            int traversed = 0;
            while (pending.Count > 0 && traversed < 4096)
            {
                IntPtr node = pending.Pop();
                if (node == IntPtr.Zero || node == head || !visited.Add(node.ToInt64()))
                {
                    continue;
                }
                traversed++;
                byte nilFlag;
                if (!TryReadRuntimeByte(IntPtr.Add(node, 0x19), out nilFlag))
                {
                    return false;
                }
                if (nilFlag != 0)
                {
                    continue;
                }
                string nodeKey;
                if (!TryReadSwp2X64String(IntPtr.Add(node, 0x20), out nodeKey))
                {
                    return false;
                }
                if (string.Equals(nodeKey, key, StringComparison.Ordinal))
                {
                    return TryReadRuntimeInt32(IntPtr.Add(node, 0x40), out value);
                }
                IntPtr left;
                if (TryReadRuntimePointer(IntPtr.Add(node, 0x00), out left))
                {
                    pending.Push(left);
                }
                IntPtr right;
                if (TryReadRuntimePointer(IntPtr.Add(node, 0x10), out right))
                {
                    pending.Push(right);
                }
            }
            return false;
        }

        private bool TryReadSwp2X64Request(
            RuntimeProfileIdentity profile,
            IntPtr vehicle,
            out int atsPRequest,
            out int atsSRequest,
            out int finalBrake,
            out string detail,
            out string failureStage
        )
        {
            atsPRequest = 0;
            atsSRequest = 0;
            finalBrake = 0;
            detail = "";
            failureStage = "None";
            IntPtr environment;
            if (!TryReadRuntimePointer(
                IntPtr.Add(profile.ModuleBaseAddress, 0x70EC0),
                out environment
            ))
            {
                failureStage = "EnvironmentPointer";
                return false;
            }
            int emergencyNotch;
            if (!TryReadRuntimeInt32(IntPtr.Add(environment, 0x1C), out emergencyNotch))
            {
                failureStage = "EmergencyNotch";
                return false;
            }
            if (!TryReadSwp2X64NamedInt32(IntPtr.Add(vehicle, 0x10), "ats_brake", out atsPRequest))
            {
                failureStage = "AtsPNamedValue";
                return false;
            }
            byte atsSEmergency;
            if (!TryReadRuntimeByte(IntPtr.Add(vehicle, 0x424), out atsSEmergency))
            {
                failureStage = "AtsSEmergencyFlag";
                return false;
            }
            atsSRequest = atsSEmergency != 0 ? emergencyNotch : 0;
            if (!TryReadSwp2X64NamedInt32(IntPtr.Add(vehicle, 0x50), "brake", out finalBrake))
            {
                failureStage = "FinalBrakeNamedValue";
                return false;
            }
            detail =
                "AtsPNamedRequest:" + atsPRequest
                + ",AtsSEmergencyFlag:" + atsSEmergency
                + ",FinalBrake:" + finalBrake;
            return true;
        }
        private void DiagnoseSwp2DeviceAggregatedRequest(
            StringBuilder rtLog,
            ref bool hasChanges
        )
        {
            foreach (RuntimeProfileIdentity profile in runtimeProfilesByHash.Values)
            {
                if (
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "Swp2DeviceAggregatedRequest",
                        StringComparison.Ordinal
                    )
                    || profile.Swp2RootPointerRva == 0
                )
                {
                    continue;
                }

                IntPtr root;
                string failureStage = "None";
                int atsPRequest = 0;
                int atsSRequest = 0;
                string detail = "";
                bool readSucceeded;
                if (string.Equals(profile.Swp2Group, "X64", StringComparison.Ordinal))
                {
                    readSucceeded = TryReadRuntimePointer(
                        IntPtr.Add(profile.ModuleBaseAddress, profile.Swp2RootPointerRva),
                        out root
                    );
                }
                else
                {
                    readSucceeded = TryReadRuntimePointer32(
                        IntPtr.Add(profile.ModuleBaseAddress, profile.Swp2RootPointerRva),
                        out root
                    );
                }
                if (!readSucceeded)
                {
                    failureStage = "RootPointer";
                }
                else if (string.Equals(profile.Swp2Group, "X64", StringComparison.Ordinal))
                {
                    int finalBrake;
                    readSucceeded = TryReadSwp2X64Request(
                        profile,
                        root,
                        out atsPRequest,
                        out atsSRequest,
                        out finalBrake,
                        out detail,
                        out failureStage
                    );
                }
                else if (string.Equals(profile.Swp2Group, "A7EE1", StringComparison.Ordinal))
                {
                    int atsPBrakeCandidate;
                    byte atsSActive;
                    if (
                        !TryReadRuntimeInt32(
                            IntPtr.Add(root, profile.Swp2AtsPBrakeOffset),
                            out atsPBrakeCandidate
                        )
                    )
                    {
                        readSucceeded = false;
                        failureStage = "A7EE1AtsPBrakeRequest";
                    }
                    else if (
                        !TryReadRuntimeByte(
                            IntPtr.Add(root, profile.Swp2AtsSActiveOffset),
                            out atsSActive
                        )
                    )
                    {
                        readSucceeded = false;
                        failureStage = "A7EE1AtsSActive";
                    }
                    else
                    {
                        atsPRequest = Math.Max(
                            0,
                            Math.Min(atsPBrakeCandidate, emergencyBrakeNotch)
                        );
                        atsSRequest = atsSActive != 0 ? emergencyBrakeNotch : 0;
                        detail =
                            "AtsPBrakeRequest:" + atsPBrakeCandidate
                            + ",AtsSActive:" + atsSActive
                            + ",DirectLayout:7EE1"
                            + ",AtsPRequestOffset:0x"
                            + profile.Swp2AtsPBrakeOffset.ToString("X")
                            + ",AtsSActiveOffset:0x"
                            + profile.Swp2AtsSActiveOffset.ToString("X");
                    }
                }
                else if (string.Equals(profile.Swp2Group, "BAB4", StringComparison.Ordinal))
                {
                    readSucceeded = TryReadSwp2Bab4Request(
                        profile,
                        root,
                        out atsPRequest,
                        out atsSRequest,
                        out detail,
                        out failureStage
                    );
                }
                else if (string.Equals(profile.Swp2Group, "B", StringComparison.Ordinal))
                {
                    readSucceeded = TryReadSwp2GroupBRequest(
                        profile,
                        root,
                        out atsPRequest,
                        out atsSRequest,
                        out detail,
                        out failureStage
                    );
                }
                else
                {
                    int atsPBrakeCandidate;
                    int applyBrake;
                    byte atsSActive;
                    if (
                        !TryReadRuntimeInt32(
                            IntPtr.Add(root, profile.Swp2AtsPBrakeOffset),
                            out atsPBrakeCandidate
                        )
                    )
                    {
                        readSucceeded = false;
                        failureStage = "AtsPBrakeCandidate";
                    }
                    else if (
                        !TryReadRuntimeInt32(
                            IntPtr.Add(root, profile.Swp2AtsPApplyOffset),
                            out applyBrake
                        )
                    )
                    {
                        readSucceeded = false;
                        failureStage = "AtsPApplyBrake";
                    }
                    else if (
                        !TryReadRuntimeByte(
                            IntPtr.Add(root, profile.Swp2AtsSActiveOffset),
                            out atsSActive
                        )
                    )
                    {
                        readSucceeded = false;
                        failureStage = "AtsSActive";
                    }
                    else
                    {
                        atsPRequest = applyBrake != 0 ? atsPBrakeCandidate : 0;
                        atsSRequest = atsSActive != 0 ? emergencyBrakeNotch : 0;
                        detail =
                            "AtsPBrakeCandidate:" + atsPBrakeCandidate
                            + ",ApplyBrake:" + applyBrake
                            + ",AtsSActive:" + atsSActive;
                    }
                }

                int atsOnlyRequest = Math.Max(atsPRequest, atsSRequest);
                if (
                    atsPRequest < 0
                    || atsPRequest > 100
                    || atsSRequest < 0
                    || atsSRequest > 100
                    || atsOnlyRequest < 0
                    || atsOnlyRequest > 100
                )
                {
                    readSucceeded = false;
                    failureStage = "Plausibility";
                }
                bool stateChanged =
                    !profile.HasPreviousSwp2State
                    || atsPRequest != profile.PreviousSwp2AtsPRequest
                    || atsSRequest != profile.PreviousSwp2AtsSRequest
                    || atsOnlyRequest != profile.PreviousSwp2AtsOnlyRequest
                    || !string.Equals(
                        failureStage,
                        profile.PreviousSwp2FailureStage,
                        StringComparison.Ordinal
                    );
                if (!stateChanged)
                {
                    continue;
                }
                string requestKind = "None";
                if (atsOnlyRequest > 0)
                {
                    if (emergencyBrakeNotch > 0 && atsOnlyRequest == emergencyBrakeNotch)
                    {
                        requestKind = "Emergency";
                    }
                    else if (serviceMaxBrakeNotch > 0 && atsOnlyRequest == serviceMaxBrakeNotch)
                    {
                        requestKind = "ServiceMaximum";
                    }
                    else
                    {
                        requestKind = "Service";
                    }
                }
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[SWP2_DEVICE_AGGREGATED_REQUEST] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"Group:{profile.Swp2Group}, "
                    + $"ModuleBase:0x{profile.ModuleBaseAddress.ToInt64():X}, "
                    + $"Root:0x{root.ToInt64():X}, "
                    + $"ReadSucceeded:{readSucceeded}, "
                    + $"FailureStage:{failureStage}, "
                    + $"AtsPRequest:{atsPRequest}, "
                    + $"AtsSRequest:{atsSRequest}, "
                    + $"AtsOnlyRequest:{atsOnlyRequest}, "
                    + $"RequestKind:{requestKind}, "
                    + $"ServiceMax:{serviceMaxBrakeNotch}, "
                    + $"Emergency:{emergencyBrakeNotch}, "
                    + $"Detail:{detail}, "
                    + "Aggregation:Max(AtsP,AtsS), "
                    + "PanelUsed:False, "
                    + "PhysicalBrakeUsedAsRequest:False, "
                    + "ScoringEnabled:False"
                );
                profile.HasPreviousSwp2State = true;
                profile.PreviousSwp2AtsPRequest = atsPRequest;
                profile.PreviousSwp2AtsSRequest = atsSRequest;
                profile.PreviousSwp2AtsOnlyRequest = atsOnlyRequest;
                profile.PreviousSwp2FailureStage = failureStage;
                hasChanges = true;
            }
        }
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

                    RuntimeProfileCatalog catalog =
        LoadRuntimeProfileCatalog(
        runtimeProfilePath
        );

                    if (
                        catalog == null
                        || catalog.Profiles == null
                    )
                    {
                        throw new InvalidOperationException(
                            "Runtime profile catalog is empty or invalid."
                        );
                    }

                    runtimeProfilesByHash.Clear();

                    foreach (
                        RuntimeProfileCatalogEntry catalogEntry
                        in catalog.Profiles
                    )
                    {
                        if (
                            catalogEntry == null
                            || string.IsNullOrWhiteSpace(
                                catalogEntry.Sha256
                            )
                        )
                        {
                            continue;
                        }

                        string normalizedHash =
                            catalogEntry.Sha256
                                .Trim()
                                .ToUpperInvariant();

                        if (
                            normalizedHash.Length != 64
                            || normalizedHash.Any(
                                character =>
                                    !Uri.IsHexDigit(character)
                            )
                        )
                        {
                            continue;
                        }

                        RuntimeProfileIdentity profile =
                            new RuntimeProfileIdentity();

                        profile.Sha256 = normalizedHash;
                        profile.Pattern =
                            catalogEntry.Pattern ?? "";
                        profile.VerificationStatus =
                            catalogEntry.VerificationStatus ?? "";

                        if (catalogEntry.Detection != null)
                        {
                            profile.DetectionStrategy =
                                catalogEntry.Detection.Strategy ?? "";

                            profile.DetectionPriority =
                                catalogEntry.Detection.Priority ?? "";
                            profile.DetectionCompletionStatus =
                                 catalogEntry.Detection.CompletionStatus ?? "";

                            profile.SafetyEmergencySourceVerificationStatus =
                                 catalogEntry.Detection
                                    .SafetyEmergencySourceVerificationStatus
                                    ?? "";
                        }

                        RuntimeProfileCatalogAddresses addresses =
                            catalogEntry.Addresses;

                        if (addresses != null)
                        {
                            int rva;

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.PhysicalBrake,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.DirectPhysicalBrakeRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.ServiceMaximum,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.DirectServiceMaximumRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.Emergency,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.DirectEmergencyRva = rva;
                            }
                            if (
            TryGetDirectRuntimeRva(
                addresses.OutputBrake,
                "Int32",
                out rva
            )
        )
                            {
                                profile.DirectOutputBrakeRva = rva;
                            }

                            if (
            TryGetDirectRuntimeRva(
                addresses.MetroEmergencySelectionFlag,
                "Byte",
                out rva
            )
        )
                            {
                                profile.MetroEmergencySelectionFlagRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.MetroLevel7SelectionFlag,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.MetroLevel7SelectionFlagRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.MetroLevel4SelectionFlag,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.MetroLevel4SelectionFlagRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.MetroControlMode,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.MetroControlModeRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.MetroInternalState,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.MetroInternalStateRva = rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.MetroSafetyEmergencySource,
                                    "Int32",
                                    out rva
                                )
                            )
                            {
                                profile.MetroSafetyEmergencySourceRva = rva;
                            }
                            if (
    TryGetDirectRuntimeRva(
        addresses.KintetsuAbsoluteStopEmergencyLatch,
        "Byte",
        out rva
    )
)
                            {
                                profile.KintetsuAbsoluteStopEmergencyLatchRva =
                                    rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.KintetsuSecondaryEmergencySource,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.KintetsuSecondaryEmergencySourceRva =
                                    rva;
                            }
                            if (
    TryGetDirectRuntimeRva(
        addresses.KintetsuEmergencySourceA,
        "Byte",
        out rva
    )
)
                            {
                                profile.KintetsuEmergencySourceARva =
                                    rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.KintetsuEmergencySourceB,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.KintetsuEmergencySourceBRva =
                                    rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.KintetsuServiceMaximumSourceA,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.KintetsuServiceMaximumSourceARva =
                                    rva;
                            }

                            if (
                                TryGetDirectRuntimeRva(
                                    addresses.KintetsuServiceMaximumSourceB,
                                    "Byte",
                                    out rva
                                )
                            )
                            {
                                profile.KintetsuServiceMaximumSourceBRva =
                                    rva;
                            }

                            profile.ServiceMaximumRequestFlagRvas =
                        GetDirectRuntimeRvas(
                            addresses.ServiceMaximumRequestFlags,
                            "Byte"
                        );

                            profile.EmergencyRequestFlagRvas =
                                GetDirectRuntimeRvas(
                                    addresses.EmergencyRequestFlags,
                                    "Byte"
                                );

                        }

                        runtimeProfilesByHash[profile.Sha256] =
                            profile;
                    }

                    RegisterHankyuDiagnosticRuntimeProfiles();
                    RegisterNankaiDiagnosticRuntimeProfiles();
                    RegisterNnnCatsDiagnosticRuntimeProfiles();
                    RegisterSwp2DeviceAggregatedRuntimeProfiles();
                    hasScannedRuntimeProfiles = true;

                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[RUNTIME_PROFILE] CATALOG LOADED "
                        + $"SchemaVersion:{catalog.SchemaVersion}, "
                        + $"DeclaredCount:{catalog.ProfileCount}, "
                        + $"LoadedCount:{runtimeProfilesByHash.Count}, "
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

                    // 既にSHA-256を確認したパスは再計算しない。
                    if (
                        inspectedRuntimeModulePaths.Contains(
                            modulePath
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

                        // ハッシュ計算に成功したパスだけ記録する。
                        inspectedRuntimeModulePaths.Add(
                            modulePath
                        );
                    }
                    catch
                    {
                        // ロード直後などで一時的に読み取れない可能性があるため、
                        // 失敗したパスは記録せず、次回走査で再試行する。
                        continue;
                    }

                    string moduleFileName =
                        System.IO.Path.GetFileName(modulePath);

                    if (
                        string.Equals(
                            moduleFileName,
                            "ATS-N.dll",
                            StringComparison.OrdinalIgnoreCase
                        )
                        || string.Equals(
                            moduleFileName,
                            "ATS-Nx64.dll",
                            StringComparison.OrdinalIgnoreCase
                        )
                        || string.Equals(
                            moduleFileName,
                            "ATS-PN.dll",
                            StringComparison.OrdinalIgnoreCase
                        )
                        || string.Equals(
                            moduleFileName,
                            "ATS-PNx64.dll",
                            StringComparison.OrdinalIgnoreCase
                        )
                    )
                    {
                        bool profileRegistered =
                            runtimeProfilesByHash.ContainsKey(moduleHash);

                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + "[NANKAI_MODULE_DISCOVERY] "
                            + $"File:{moduleFileName}, "
                            + $"SHA256:{moduleHash}, "
                            + $"Base:0x{module.BaseAddress.ToInt64():X}, "
                            + $"ProfileRegistered:{profileRegistered}, "
                            + $"Path:{modulePath}, "
                            + "ScoringEnabled:False"
                        );

                        hasChanges = true;
                    }

                    bool isNnnCatsModule =
                        moduleFileName.IndexOf(
                            "cats2",
                            StringComparison.OrdinalIgnoreCase
                        ) >= 0
                        || moduleFileName.IndexOf(
                            "keisei",
                            StringComparison.OrdinalIgnoreCase
                        ) >= 0;

                    if (isNnnCatsModule)
                    {
                        bool profileRegistered =
                            runtimeProfilesByHash.ContainsKey(moduleHash);

                        rtLog.AppendLine(
                            $"[{DateTime.Now:HH:mm:ss.fff}] "
                            + "[NNN_CATS_MODULE_DISCOVERY] "
                            + $"File:{moduleFileName}, "
                            + $"SHA256:{moduleHash}, "
                            + $"Base:0x{module.BaseAddress.ToInt64():X}, "
                            + $"ModuleMemorySize:{module.ModuleMemorySize}, "
                            + $"ProcessPointerSize:{IntPtr.Size}, "
                            + $"ProfileRegistered:{profileRegistered}, "
                            + $"Path:{modulePath}, "
                            + "ScoringEnabled:False"
                        );

                        hasChanges = true;
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

                    // C_ATS.dllで確認する
                    // ThreeStateBrakeInterventionの静的配置。
                    if (
                        matchedProfile.Pattern
                            == "ThreeStateBrakeIntervention"
                    )
                    {
                        matchedProfile.InterventionModeRva = 0x9140;
                        matchedProfile.NoneModeValue = 0;
                        matchedProfile.ServiceMaximumModeValue = 1;
                        matchedProfile.EmergencyModeValue = 2;
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
                            + $"Strategy:{matchedProfile.DetectionStrategy}, "
                            + $"Priority:{matchedProfile.DetectionPriority}, "
                            + "ServiceRequestFlagCount:"
                            + $"{matchedProfile.ServiceMaximumRequestFlagRvas.Count}, "
                            + "EmergencyRequestFlagCount:"
                            + $"{matchedProfile.EmergencyRequestFlagRvas.Count}, "
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
        // NNN式C-ATSのcats2.dll内部状態を読み取る。
        // 状態コードの意味は動的確認中のため、候補として記録する。
        // この処理は採点には接続しない。
        // =========================================================
        private void DiagnoseNnnCatsRequestState(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "NnnCatsRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.NnnCatsDriverBrakeRva == 0
                    || profile.NnnCatsEmergencyNotchRva == 0
                    || profile.NnnCatsReturnedBrakeRva == 0
                    || profile.NnnCatsSafetyFlagRva == 0
                    || profile.NnnCatsMainStateRva == 0
                    || profile.NnnCatsRequestStatePointerRva == 0
                )
                {
                    continue;
                }
                int driverBrake;
                int emergencyNotch;
                int returnedBrake;
                byte safetyFlag;
                int mainState;
                int mode0RequestState = int.MinValue;
                int mode1RequestState = int.MinValue;
                bool driverRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsDriverBrakeRva),
                    out driverBrake
                );
                bool emergencyNotchRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsEmergencyNotchRva),
                    out emergencyNotch
                );
                bool returnedBrakeRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsReturnedBrakeRva),
                    out returnedBrake
                );
                bool safetyFlagRead = TryReadRuntimeByte(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsSafetyFlagRva),
                    out safetyFlag
                );
                bool mainStateRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsMainStateRva),
                    out mainState
                );
                bool mode0StateRead =
                    profile.NnnCatsMode0RequestStateRva == 0
                    || TryReadRuntimeInt32(
                        IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsMode0RequestStateRva),
                        out mode0RequestState
                    );
                bool mode1StateRead =
                    profile.NnnCatsMode1RequestStateRva == 0
                    || TryReadRuntimeInt32(
                        IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsMode1RequestStateRva),
                        out mode1RequestState
                    );
                IntPtr selectedRequestStateAddress;
                bool pointerRead = TryReadRuntimePointer(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NnnCatsRequestStatePointerRva),
                    out selectedRequestStateAddress
                );
                int selectedRequestState = int.MinValue;
                bool selectedStateRead =
                    pointerRead
                    && TryReadRuntimeInt32(
                        selectedRequestStateAddress,
                        out selectedRequestState
                    );
                if (
                    !driverRead
                    || !emergencyNotchRead
                    || !returnedBrakeRead
                    || !safetyFlagRead
                    || !mainStateRead
                    || !mode0StateRead
                    || !mode1StateRead
                )
                {
                    continue;
                }
                if (
                    driverBrake < -1
                    || driverBrake > 100
                    || emergencyNotch < 1
                    || emergencyNotch > 100
                    || returnedBrake < -1
                    || returnedBrake > 100
                    || safetyFlag > 1
                    || mainState < -1000
                    || mainState > 1000
                    || (profile.NnnCatsMode0RequestStateRva != 0 && (mode0RequestState < -1000 || mode0RequestState > 1000))
                    || (profile.NnnCatsMode1RequestStateRva != 0 && (mode1RequestState < -1000 || mode1RequestState > 1000))
                    || (selectedStateRead && (selectedRequestState < -1000 || selectedRequestState > 1000))
                )
                {
                    continue;
                }
                long selectedRequestStateAddressValue =
                    selectedRequestStateAddress.ToInt64();
                bool stateChanged =
                    !profile.HasPreviousNnnCatsRequestState
                    || driverBrake != profile.PreviousNnnCatsDriverBrake
                    || emergencyNotch != profile.PreviousNnnCatsEmergencyNotch
                    || returnedBrake != profile.PreviousNnnCatsReturnedBrake
                    || safetyFlag != profile.PreviousNnnCatsSafetyFlag
                    || mainState != profile.PreviousNnnCatsMainState
                    || selectedRequestStateAddressValue != profile.PreviousNnnCatsRequestStateAddress
                    || selectedRequestState != profile.PreviousNnnCatsSelectedRequestState
                    || mode0RequestState != profile.PreviousNnnCatsMode0RequestState
                    || mode1RequestState != profile.PreviousNnnCatsMode1RequestState;
                if (!stateChanged)
                {
                    continue;
                }
                bool selectedOddEmergencyCandidate =
                    selectedStateRead
                    && mainState > 2
                    && (
                        selectedRequestState == 1
                        || selectedRequestState == 3
                        || selectedRequestState == 5
                    );
                bool selectedEvenServiceCandidate =
                    selectedStateRead
                    && mainState > 2
                    && (
                        selectedRequestState == 2
                        || selectedRequestState == 4
                        || selectedRequestState == 6
                    );
                bool lowMainStateEmergencyOutputCondition =
                    mainState >= -1
                    && mainState < 3;
                bool safetyEmergencyCandidate =
                    safetyFlag != 0
                    || selectedOddEmergencyCandidate;
                bool serviceMaximumCandidate =
                    !safetyEmergencyCandidate
                    && selectedEvenServiceCandidate;
                string requestKindCandidate = "None";
                int requestBrakeCandidate = 0;
                if (safetyEmergencyCandidate)
                {
                    requestKindCandidate = "EmergencyCandidate";
                    requestBrakeCandidate = emergencyNotch;
                }
                else if (serviceMaximumCandidate)
                {
                    requestKindCandidate = "ServiceMaximumCandidate";
                    requestBrakeCandidate = emergencyNotch - 1;
                }
                bool hiddenByPhysical =
                    requestBrakeCandidate > 0
                    && driverBrake >= requestBrakeCandidate;
                bool outputMatchesCandidate =
                    requestBrakeCandidate > 0
                    && returnedBrake == requestBrakeCandidate;
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[NNN_CATS_REQUEST_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"DriverBrake:{driverBrake}, "
                    + $"EmergencyNotch:{emergencyNotch}, "
                    + $"ServiceMaximum:{emergencyNotch - 1}, "
                    + $"ReturnedBrake:{returnedBrake}, "
                    + $"SafetyFlag:{safetyFlag}, "
                    + $"MainState:{mainState}, "
                    + $"RequestStatePointerRead:{pointerRead}, "
                    + $"RequestStateAddress:0x{selectedRequestStateAddressValue:X}, "
                    + $"SelectedRequestStateRead:{selectedStateRead}, "
                    + $"SelectedRequestState:{(selectedStateRead ? selectedRequestState.ToString() : "<UNREADABLE>")}, "
                    + $"Mode0RequestState:{(profile.NnnCatsMode0RequestStateRva != 0 ? mode0RequestState.ToString() : "<NOT_CONFIGURED>")}, "
                    + $"Mode1RequestState:{(profile.NnnCatsMode1RequestStateRva != 0 ? mode1RequestState.ToString() : "<NOT_CONFIGURED>")}, "
                    + $"OddEmergencyCandidate:{selectedOddEmergencyCandidate}, "
                    + $"EvenServiceMaximumCandidate:{selectedEvenServiceCandidate}, "
                    + $"LowMainStateEmergencyOutputCondition:{lowMainStateEmergencyOutputCondition}, "
                    + $"RequestKindCandidate:{requestKindCandidate}, "
                    + $"RequestBrakeCandidate:{requestBrakeCandidate}, "
                    + $"OutputMatchesCandidate:{outputMatchesCandidate}, "
                    + $"HiddenByPhysical:{hiddenByPhysical}, "
                    + "ScoringEnabled:False"
                );
                profile.HasPreviousNnnCatsRequestState = true;
                profile.PreviousNnnCatsDriverBrake = driverBrake;
                profile.PreviousNnnCatsEmergencyNotch = emergencyNotch;
                profile.PreviousNnnCatsReturnedBrake = returnedBrake;
                profile.PreviousNnnCatsSafetyFlag = safetyFlag;
                profile.PreviousNnnCatsMainState = mainState;
                profile.PreviousNnnCatsRequestStateAddress = selectedRequestStateAddressValue;
                profile.PreviousNnnCatsSelectedRequestState = selectedRequestState;
                profile.PreviousNnnCatsMode0RequestState = mode0RequestState;
                profile.PreviousNnnCatsMode1RequestState = mode1RequestState;
                hasChanges = true;
            }
        }

        // =========================================================
        // 南海ATS-Nの内部非常要求フラグを読み取る。
        // この処理は動的検証専用であり、採点には接続しない。
        // =========================================================
        private void DiagnoseNankaiAtsNEmergencyRequestState(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "NankaiAtsNEmergencyRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.NankaiNEmergencyFlagRva == 0
                )
                {
                    continue;
                }
                byte emergencyRequested;
                if (
                    !TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.NankaiNEmergencyFlagRva
                        ),
                        out emergencyRequested
                    )
                    || emergencyRequested > 1
                )
                {
                    continue;
                }
                bool stateChanged =
                    !profile.HasPreviousNankaiNEmergencyState
                    || emergencyRequested
                        != profile.PreviousNankaiNEmergencyRequested;
                if (!stateChanged)
                {
                    continue;
                }
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[NANKAI_ATS_N_REQUEST_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"EmergencyFlagRva:0x{profile.NankaiNEmergencyFlagRva:X}, "
                    + $"EmergencyRequestedRaw:{emergencyRequested}, "
                    + $"EmergencyRequested:{emergencyRequested != 0}, "
                    + $"RequestBrake:{(emergencyRequested != 0 ? emergencyBrakeNotch : 0)}, "
                    + $"Emergency:{emergencyBrakeNotch}, "
                    + "ScoringEnabled:False"
                );
                profile.HasPreviousNankaiNEmergencyState = true;
                profile.PreviousNankaiNEmergencyRequested =
                    emergencyRequested;
                hasChanges = true;
            }
        }

        // =========================================================
        // 南海ATS-PNの集約済み常用最大・非常要求を読み取る。
        // ATS-PN内部4系統の個別フラグではなく、論理和後の2バイトを使う。
        // この処理は動的検証専用であり、採点には接続しない。
        // =========================================================
        private void DiagnoseNankaiAtsPnRequestState(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "NankaiAtsPnAggregatedRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.NankaiPnRequestStatePointerRva == 0
                )
                {
                    continue;
                }

                IntPtr pointerAddress = IntPtr.Add(
                    profile.ModuleBaseAddress,
                    profile.NankaiPnRequestStatePointerRva
                );
                IntPtr requestStateAddress;
                try
                {
                    requestStateAddress =
                        System.Runtime.InteropServices.Marshal.ReadIntPtr(
                            pointerAddress
                        );
                }
                catch
                {
                    continue;
                }
                if (requestStateAddress == IntPtr.Zero)
                {
                    continue;
                }

                byte emergencyRequested;
                byte serviceMaximumRequested;
                bool emergencyRead = TryReadRuntimeByte(
                    IntPtr.Add(
                        requestStateAddress,
                        profile.NankaiPnEmergencyOffset
                    ),
                    out emergencyRequested
                );
                bool serviceMaximumRead = TryReadRuntimeByte(
                    IntPtr.Add(
                        requestStateAddress,
                        profile.NankaiPnServiceMaximumOffset
                    ),
                    out serviceMaximumRequested
                );
                if (!emergencyRead || !serviceMaximumRead)
                {
                    continue;
                }
                if (
                    emergencyRequested > 1
                    || serviceMaximumRequested > 1
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile.HasPreviousNankaiPnRequestState
                    || emergencyRequested
                        != profile.PreviousNankaiPnEmergencyRequested
                    || serviceMaximumRequested
                        != profile.PreviousNankaiPnServiceMaximumRequested;
                if (!stateChanged)
                {
                    continue;
                }

                string requestKind;
                int requestBrake;
                if (emergencyRequested != 0)
                {
                    requestKind = "Emergency";
                    requestBrake = emergencyBrakeNotch;
                }
                else if (serviceMaximumRequested != 0)
                {
                    requestKind = "ServiceMaximum";
                    requestBrake = serviceMaxBrakeNotch;
                }
                else
                {
                    requestKind = "None";
                    requestBrake = 0;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[NANKAI_ATS_PN_REQUEST_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"PointerRva:0x{profile.NankaiPnRequestStatePointerRva:X}, "
                    + $"RequestStateAddress:0x{requestStateAddress.ToInt64():X}, "
                    + $"ServiceMaximumRequestedRaw:{serviceMaximumRequested}, "
                    + $"EmergencyRequestedRaw:{emergencyRequested}, "
                    + $"RequestKind:{requestKind}, "
                    + $"RequestBrake:{requestBrake}, "
                    + $"ServiceMax:{serviceMaxBrakeNotch}, "
                    + $"Emergency:{emergencyBrakeNotch}, "
                    + "Source:AggregatedFourSystems, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousNankaiPnRequestState = true;
                profile.PreviousNankaiPnEmergencyRequested =
                    emergencyRequested;
                profile.PreviousNankaiPnServiceMaximumRequested =
                    serviceMaximumRequested;
                hasChanges = true;
            }
        }

        // =========================================================
        // 南海旧系統ATS-PNの直接配置された内部要求候補を読み取る。
        // 常用最大は3つのInt32状態の論理和、非常はByte状態を使う。
        // この処理は動的検証専用であり、採点には接続しない。
        // =========================================================
        private void DiagnoseNankaiLegacyAtsPnRequestState(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "NankaiLegacyAtsPnDirectRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.NankaiLegacyPnServiceSourceARva == 0
                    || profile.NankaiLegacyPnServiceSourceBRva == 0
                    || profile.NankaiLegacyPnServiceSourceCRva == 0
                    || profile.NankaiLegacyPnEmergencyFlagRva == 0
                )
                {
                    continue;
                }
                int serviceSourceA;
                int serviceSourceB;
                int serviceSourceC;
                byte emergencyRequested;
                bool serviceSourceARead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NankaiLegacyPnServiceSourceARva),
                    out serviceSourceA
                );
                bool serviceSourceBRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NankaiLegacyPnServiceSourceBRva),
                    out serviceSourceB
                );
                bool serviceSourceCRead = TryReadRuntimeInt32(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NankaiLegacyPnServiceSourceCRva),
                    out serviceSourceC
                );
                bool emergencyRead = TryReadRuntimeByte(
                    IntPtr.Add(profile.ModuleBaseAddress, profile.NankaiLegacyPnEmergencyFlagRva),
                    out emergencyRequested
                );
                if (
                    !serviceSourceARead
                    || !serviceSourceBRead
                    || !serviceSourceCRead
                    || !emergencyRead
                    || emergencyRequested > 1
                    || serviceSourceA < -1000000
                    || serviceSourceA > 1000000
                    || serviceSourceB < -1000000
                    || serviceSourceB > 1000000
                    || serviceSourceC < -1000000
                    || serviceSourceC > 1000000
                )
                {
                    continue;
                }
                bool stateChanged =
                    !profile.HasPreviousNankaiLegacyPnRequestState
                    || serviceSourceA != profile.PreviousNankaiLegacyPnServiceSourceA
                    || serviceSourceB != profile.PreviousNankaiLegacyPnServiceSourceB
                    || serviceSourceC != profile.PreviousNankaiLegacyPnServiceSourceC
                    || emergencyRequested != profile.PreviousNankaiLegacyPnEmergencyRequested;
                if (!stateChanged)
                {
                    continue;
                }
                bool serviceMaximumRequested =
                    serviceSourceA != 0
                    || serviceSourceB != 0
                    || serviceSourceC != 0;
                string requestKind;
                int requestBrake;
                if (emergencyRequested != 0)
                {
                    requestKind = "Emergency";
                    requestBrake = emergencyBrakeNotch;
                }
                else if (serviceMaximumRequested)
                {
                    requestKind = "ServiceMaximum";
                    requestBrake = serviceMaxBrakeNotch;
                }
                else
                {
                    requestKind = "None";
                    requestBrake = 0;
                }
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[NANKAI_LEGACY_ATS_PN_REQUEST_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"ServiceSourceARva:0x{profile.NankaiLegacyPnServiceSourceARva:X}, "
                    + $"ServiceSourceA:{serviceSourceA}, "
                    + $"ServiceSourceBRva:0x{profile.NankaiLegacyPnServiceSourceBRva:X}, "
                    + $"ServiceSourceB:{serviceSourceB}, "
                    + $"ServiceSourceCRva:0x{profile.NankaiLegacyPnServiceSourceCRva:X}, "
                    + $"ServiceSourceC:{serviceSourceC}, "
                    + $"EmergencyFlagRva:0x{profile.NankaiLegacyPnEmergencyFlagRva:X}, "
                    + $"EmergencyRequestedRaw:{emergencyRequested}, "
                    + $"ServiceMaximumRequested:{serviceMaximumRequested}, "
                    + $"EmergencyRequested:{emergencyRequested != 0}, "
                    + $"RequestKind:{requestKind}, "
                    + $"RequestBrake:{requestBrake}, "
                    + $"ServiceMax:{serviceMaxBrakeNotch}, "
                    + $"Emergency:{emergencyBrakeNotch}, "
                    + "ScoringEnabled:False"
                );
                profile.HasPreviousNankaiLegacyPnRequestState = true;
                profile.PreviousNankaiLegacyPnServiceSourceA = serviceSourceA;
                profile.PreviousNankaiLegacyPnServiceSourceB = serviceSourceB;
                profile.PreviousNankaiLegacyPnServiceSourceC = serviceSourceC;
                profile.PreviousNankaiLegacyPnEmergencyRequested = emergencyRequested;
                hasChanges = true;
            }
        }
        // =========================================================
        // 阪急ATSの内部要求有効状態と要求ブレーキ段を読み取る。
        // 採点には接続せず、変化時だけ診断ログへ記録する。
        // =========================================================
        private void DiagnoseHankyuEmergencyRequestState(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "HankyuEmergencyRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.HankyuInputBrakeRva == 0
                    || profile.HankyuOutputBrakeRva == 0
                    || profile.HankyuRequestActiveRva == 0
                    || profile.HankyuRequestedBrakeRva == 0
                )
                {
                    continue;
                }
                int inputBrake;
                int outputBrake;
                int requestActive;
                int requestedBrake;
                bool inputRead = TryReadRuntimeInt32(
                    IntPtr.Add(
                        profile.ModuleBaseAddress,
                        profile.HankyuInputBrakeRva
                    ),
                    out inputBrake
                );
                bool outputRead = TryReadRuntimeInt32(
                    IntPtr.Add(
                        profile.ModuleBaseAddress,
                        profile.HankyuOutputBrakeRva
                    ),
                    out outputBrake
                );
                bool requestActiveRead = TryReadRuntimeInt32(
                    IntPtr.Add(
                        profile.ModuleBaseAddress,
                        profile.HankyuRequestActiveRva
                    ),
                    out requestActive
                );
                bool requestedBrakeRead = TryReadRuntimeInt32(
                    IntPtr.Add(
                        profile.ModuleBaseAddress,
                        profile.HankyuRequestedBrakeRva
                    ),
                    out requestedBrake
                );
                if (
                    !inputRead
                    || !outputRead
                    || !requestActiveRead
                    || !requestedBrakeRead
                )
                {
                    continue;
                }
                if (
                    inputBrake < -1
                    || inputBrake > 100
                    || outputBrake < -1
                    || outputBrake > 100
                    || requestedBrake < -1
                    || requestedBrake > 100
                    || requestActive < -1000000
                    || requestActive > 1000000
                )
                {
                    continue;
                }
                bool stateChanged =
                    !profile.HasPreviousHankyuRequestState
                    || inputBrake != profile.PreviousHankyuInputBrake
                    || outputBrake != profile.PreviousHankyuOutputBrake
                    || requestActive != profile.PreviousHankyuRequestActive
                    || requestedBrake != profile.PreviousHankyuRequestedBrake;
                if (!stateChanged)
                {
                    continue;
                }
                bool requestIsActive = requestActive != 0;
                bool emergencyNotchKnown = emergencyBrakeNotch > 0;
                bool emergencyCandidate =
                    requestIsActive
                    && emergencyNotchKnown
                    && requestedBrake == emergencyBrakeNotch;
                bool hiddenByPhysical =
                    requestIsActive
                    && requestedBrake > 0
                    && inputBrake >= requestedBrake;
                bool outputMatchesRequest =
                    requestIsActive
                    && outputBrake == requestedBrake;
                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[HANKYU_REQUEST_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Profile:{profile.Pattern}, "
                    + $"InputRva:0x{profile.HankyuInputBrakeRva:X}, "
                    + $"OutputRva:0x{profile.HankyuOutputBrakeRva:X}, "
                    + $"RequestActiveRva:0x{profile.HankyuRequestActiveRva:X}, "
                    + $"RequestedBrakeRva:0x{profile.HankyuRequestedBrakeRva:X}, "
                    + $"Input:{inputBrake}, "
                    + $"Output:{outputBrake}, "
                    + $"RequestActiveRaw:{requestActive}, "
                    + $"RequestIsActive:{requestIsActive}, "
                    + $"RequestedBrake:{requestedBrake}, "
                    + $"EmergencyNotch:{emergencyBrakeNotch}, "
                    + $"EmergencyCandidate:{emergencyCandidate}, "
                    + $"OutputMatchesRequest:{outputMatchesRequest}, "
                    + $"HiddenByPhysical:{hiddenByPhysical}, "
                    + "ScoringEnabled:False"
                );
                profile.HasPreviousHankyuRequestState = true;
                profile.PreviousHankyuInputBrake = inputBrake;
                profile.PreviousHankyuOutputBrake = outputBrake;
                profile.PreviousHankyuRequestActive = requestActive;
                profile.PreviousHankyuRequestedBrake = requestedBrake;
                hasChanges = true;
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

                // この方式では、物理入力と最終出力の差だけでは
                // 保安装置側の要求段を確定できない。
                //
                // ここでは出力差を診断情報として記録するだけとし、
                // RUNTIME_INTERVENTIONは要求フラグ側から生成する。
                bool outputDiffersFromPhysical =
                    outputBrake != physicalBrake;

                string outputStateKind = "Physical";

                if (outputDiffersFromPhysical)
                {
                    if (outputBrake == emergency)
                    {
                        outputStateKind = "EmergencyOutput";
                    }
                    else if (outputBrake == serviceMaximum)
                    {
                        outputStateKind = "ServiceMaximumOutput";
                    }
                    else
                    {
                        outputStateKind = "IntermediateOutput";
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[RUNTIME_PROFILE_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"Pattern:{profile.Pattern}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + "OutputDiffersFromPhysical:"
                    + $"{outputDiffersFromPhysical}, "
                    + $"OutputState:{outputStateKind}, "
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
        // =========================================================
        // MATCH済みのThreeStateBrakeInterventionについて、
        // 3状態の介入モードを読み取り、変化時だけ記録する。
        //
        // この処理は減点には接続しない。
        // =========================================================
        private void DiagnoseThreeStateBrakeIntervention(
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
                        != "ThreeStateBrakeIntervention"
                    || profile.ModuleBaseAddress == IntPtr.Zero
                    || profile.InterventionModeRva == 0
                )
                {
                    continue;
                }

                int modeValue;

                bool modeRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.InterventionModeRva
                        ),
                        out modeValue
                    );

                if (!modeRead)
                {
                    continue;
                }

                string interventionKind;

                if (modeValue == profile.NoneModeValue)
                {
                    interventionKind = "None";
                }
                else if (
                    modeValue
                        == profile.ServiceMaximumModeValue
                )
                {
                    interventionKind = "ServiceMaximum";
                }
                else if (
                    modeValue
                        == profile.EmergencyModeValue
                )
                {
                    interventionKind = "Emergency";
                }
                else
                {
                    interventionKind = "Unknown";
                }

                bool modeChanged =
                    !profile.HasPreviousModeValue
                    || modeValue != profile.PreviousModeValue;

                if (!modeChanged)
                {
                    continue;
                }

                // 初回読取りは現在状態を基準値として保存する。
                // シナリオ開始時点の状態を新規介入と誤認しない。
                if (!profile.HasPreviousInterventionState)
                {
                    profile.HasPreviousInterventionState = true;
                    profile.PreviousInterventionKind =
                        interventionKind;
                }
                else if (
                    profile.PreviousInterventionKind
                        != interventionKind
                )
                {
                    string transitionType;

                    if (
                        profile.PreviousInterventionKind == "None"
                        && interventionKind != "None"
                    )
                    {
                        transitionType = "START";
                    }
                    else if (
                        profile.PreviousInterventionKind != "None"
                        && interventionKind == "None"
                    )
                    {
                        transitionType = "END";
                    }
                    else
                    {
                        transitionType = "CHANGE";
                    }

                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[RUNTIME_INTERVENTION] "
                        + $"Event:{transitionType}, "
                        + $"File:{profile.FileName}, "
                        + $"Pattern:{profile.Pattern}, "
                        + "PreviousKind:"
                        + $"{profile.PreviousInterventionKind}, "
                        + $"CurrentKind:{interventionKind}, "
                        + $"Mode:{modeValue}, "
                        + "ScoringEnabled:False"
                    );

                    profile.PreviousInterventionKind =
                        interventionKind;

                    hasChanges = true;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[RUNTIME_PROFILE_MODE] "
                    + $"File:{profile.FileName}, "
                    + $"Pattern:{profile.Pattern}, "
                    + $"ModeRva:0x{profile.InterventionModeRva:X}, "
                    + $"Mode:{modeValue}, "
                    + $"Kind:{interventionKind}, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousModeValue = true;
                profile.PreviousModeValue = modeValue;

                hasChanges = true;
            }
        }

        // =========================================================
        // MATCH済みのPhysicalServiceEmergencyOutputComparisonについて、
        // 固定RVAのブレーキ状態を読み取り、変化時だけ記録する。
        //
        // 現段階ではOdakyuAts.dllのみを対象とし、減点には接続しない。
        // =========================================================
        private void DiagnoseDirectBrakeOutputComparison(
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
                        != "PhysicalServiceEmergencyOutputComparison"
                    || profile.ModuleBaseAddress == IntPtr.Zero
                    || profile.DirectPhysicalBrakeRva == 0
                    || profile.DirectServiceMaximumRva == 0
                    || profile.DirectEmergencyRva == 0
                    || profile.DirectOutputBrakeRva == 0
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
                            profile.ModuleBaseAddress,
                            profile.DirectPhysicalBrakeRva
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectServiceMaximumRva
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectEmergencyRva
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectOutputBrakeRva
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

                // ブレーキ段として明らかに不自然な値は記録しない。
                if (
                    physicalBrake < -1
                    || serviceMaximum < 0
                    || emergency < 0
                    || outputBrake < -1
                    || physicalBrake > 100
                    || serviceMaximum > 100
                    || emergency > 100
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
                        != profile.PreviousOutputBrake;

                if (!stateChanged)
                {
                    continue;
                }

                // 物理入力と最終出力の差は診断情報としてのみ記録する。
                // 保安装置介入の状態遷移は、このメソッドでは生成しない。
                //
                // 小田急の介入状態は、動的確認済みの要求フラグを使用する
                // DiagnoseExplicitBrakeRequestFlagsだけが生成する。
                bool outputDiffersFromPhysical =
                    outputBrake != physicalBrake;

                string outputStateKind = "MatchesPhysical";

                if (outputDiffersFromPhysical)
                {
                    if (outputBrake == emergency)
                    {
                        outputStateKind = "EmergencyOutput";
                    }
                    else if (outputBrake == serviceMaximum)
                    {
                        outputStateKind = "ServiceMaximumOutput";
                    }
                    else
                    {
                        outputStateKind = "IntermediateOutput";
                    }
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[RUNTIME_PROFILE_STATE] "
                    + $"File:{profile.FileName}, "
                    + $"Pattern:{profile.Pattern}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + "OutputDiffersFromPhysical:"
                    + $"{outputDiffersFromPhysical}, "
                    + $"OutputState:{outputStateKind}, "
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

                hasChanges = true;
            }
        }
        // =========================================================
        // 近鉄系ATSについて、2つの非常要求候補を個別に読み取る。
        //
        // この処理は動的検証専用であり、採点には接続しない。
        // 候補の論理和は診断情報としてのみ表示する。
        // =========================================================
        private void DiagnoseKintetsuEmergencyCandidates(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "KintetsuEmergencyCandidates",
                        StringComparison.Ordinal
                    )
                    || profile.DirectPhysicalBrakeRva == 0
                    || profile.DirectServiceMaximumRva == 0
                    || profile.DirectEmergencyRva == 0
                    || profile.DirectOutputBrakeRva == 0
                    || profile.KintetsuAbsoluteStopEmergencyLatchRva == 0
                    || profile.KintetsuSecondaryEmergencySourceRva == 0
                )
                {
                    continue;
                }

                byte absoluteStopEmergencyLatch;
                byte secondaryEmergencySource;
                int physicalBrake;
                int serviceMaximum;
                int emergency;
                int outputBrake;

                bool absoluteStopRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuAbsoluteStopEmergencyLatchRva
                        ),
                        out absoluteStopEmergencyLatch
                    );

                bool secondarySourceRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuSecondaryEmergencySourceRva
                        ),
                        out secondaryEmergencySource
                    );

                bool physicalRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectPhysicalBrakeRva
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectServiceMaximumRva
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectEmergencyRva
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectOutputBrakeRva
                        ),
                        out outputBrake
                    );

                if (
                    !absoluteStopRead
                    || !secondarySourceRead
                    || !physicalRead
                    || !serviceRead
                    || !emergencyRead
                    || !outputRead
                )
                {
                    continue;
                }

                if (
                    physicalBrake < -1
                    || physicalBrake > 100
                    || serviceMaximum < 0
                    || serviceMaximum > 100
                    || emergency < 0
                    || emergency > 100
                    || outputBrake < -1
                    || outputBrake > 100
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile.HasPreviousKintetsuEmergencyCandidateState
                    || absoluteStopEmergencyLatch
                        != profile.PreviousKintetsuAbsoluteStopEmergencyLatch
                    || secondaryEmergencySource
                        != profile.PreviousKintetsuSecondaryEmergencySource
                    || physicalBrake
                        != profile.PreviousKintetsuPhysicalBrake
                    || serviceMaximum
                        != profile.PreviousKintetsuServiceMaximum
                    || emergency
                        != profile.PreviousKintetsuEmergency
                    || outputBrake
                        != profile.PreviousKintetsuOutputBrake;

                if (!stateChanged)
                {
                    continue;
                }

                bool anySafetyEmergencyCandidate =
                    absoluteStopEmergencyLatch != 0
                    || secondaryEmergencySource != 0;

                bool outputIsEmergency =
                    outputBrake == emergency;

                bool emergencyHiddenByPhysical =
                    anySafetyEmergencyCandidate
                    && physicalBrake >= emergency;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[KINTETSU_EMERGENCY_CANDIDATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Strategy:{profile.DetectionStrategy}, "
                    + "AbsoluteStopEmergencyLatch:"
                    + $"{absoluteStopEmergencyLatch}, "
                    + "SecondaryEmergencySource:"
                    + $"{secondaryEmergencySource}, "
                    + "AnySafetyEmergencyCandidate:"
                    + $"{anySafetyEmergencyCandidate}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + $"OutputIsEmergency:{outputIsEmergency}, "
                    + "HiddenByPhysical:"
                    + $"{emergencyHiddenByPhysical}, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousKintetsuEmergencyCandidateState =
                    true;

                profile.PreviousKintetsuAbsoluteStopEmergencyLatch =
                    absoluteStopEmergencyLatch;

                profile.PreviousKintetsuSecondaryEmergencySource =
                    secondaryEmergencySource;

                profile.PreviousKintetsuPhysicalBrake =
                    physicalBrake;

                profile.PreviousKintetsuServiceMaximum =
                    serviceMaximum;

                profile.PreviousKintetsuEmergency =
                    emergency;

                profile.PreviousKintetsuOutputBrake =
                    outputBrake;

                hasChanges = true;
            }
        }

        // =========================================================
        // 近鉄大阪線向け旧版について、非常2源と常用最大2源を
        // 個別に読み取る。
        //
        // この処理は動的検証専用であり、採点には接続しない。
        // =========================================================
        private void DiagnoseKintetsuServiceAndEmergencyCandidates(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "KintetsuServiceAndEmergencyCandidates",
                        StringComparison.Ordinal
                    )
                    || profile.DirectPhysicalBrakeRva == 0
                    || profile.DirectServiceMaximumRva == 0
                    || profile.DirectEmergencyRva == 0
                    || profile.DirectOutputBrakeRva == 0
                    || profile.KintetsuEmergencySourceARva == 0
                    || profile.KintetsuEmergencySourceBRva == 0
                    || profile.KintetsuServiceMaximumSourceARva == 0
                    || profile.KintetsuServiceMaximumSourceBRva == 0
                )
                {
                    continue;
                }

                byte emergencySourceA;
                byte emergencySourceB;
                byte serviceMaximumSourceA;
                byte serviceMaximumSourceB;

                int physicalBrake;
                int serviceMaximum;
                int emergency;
                int outputBrake;

                bool emergencySourceARead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuEmergencySourceARva
                        ),
                        out emergencySourceA
                    );

                bool emergencySourceBRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuEmergencySourceBRva
                        ),
                        out emergencySourceB
                    );

                bool serviceMaximumSourceARead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuServiceMaximumSourceARva
                        ),
                        out serviceMaximumSourceA
                    );

                bool serviceMaximumSourceBRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.KintetsuServiceMaximumSourceBRva
                        ),
                        out serviceMaximumSourceB
                    );

                bool physicalRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectPhysicalBrakeRva
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectServiceMaximumRva
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectEmergencyRva
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectOutputBrakeRva
                        ),
                        out outputBrake
                    );

                if (
                    !emergencySourceARead
                    || !emergencySourceBRead
                    || !serviceMaximumSourceARead
                    || !serviceMaximumSourceBRead
                    || !physicalRead
                    || !serviceRead
                    || !emergencyRead
                    || !outputRead
                )
                {
                    continue;
                }

                if (
                    physicalBrake < -1
                    || physicalBrake > 100
                    || serviceMaximum < 0
                    || serviceMaximum > 100
                    || emergency < 0
                    || emergency > 100
                    || outputBrake < -1
                    || outputBrake > 100
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile
                        .HasPreviousKintetsuServiceAndEmergencyCandidateState
                    || emergencySourceA
                        != profile.PreviousKintetsuEmergencySourceA
                    || emergencySourceB
                        != profile.PreviousKintetsuEmergencySourceB
                    || serviceMaximumSourceA
                        != profile.PreviousKintetsuServiceMaximumSourceA
                    || serviceMaximumSourceB
                        != profile.PreviousKintetsuServiceMaximumSourceB
                    || physicalBrake
                        != profile
                            .PreviousKintetsuServiceAndEmergencyPhysicalBrake
                    || serviceMaximum
                        != profile
                            .PreviousKintetsuServiceAndEmergencyServiceMaximum
                    || emergency
                        != profile
                            .PreviousKintetsuServiceAndEmergencyEmergency
                    || outputBrake
                        != profile
                            .PreviousKintetsuServiceAndEmergencyOutputBrake;

                if (!stateChanged)
                {
                    continue;
                }

                bool safetyEmergencyRequested =
                    emergencySourceA != 0
                    || emergencySourceB != 0;

                bool safetyServiceMaximumRequested =
                    serviceMaximumSourceA != 0
                    || serviceMaximumSourceB != 0;

                int requestBrake;
                string requestKind;

                if (safetyEmergencyRequested)
                {
                    requestBrake = emergency;
                    requestKind = "SafetyEmergency";
                }
                else if (safetyServiceMaximumRequested)
                {
                    requestBrake = serviceMaximum;
                    requestKind = "ServiceMaximum";
                }
                else
                {
                    requestBrake = 0;
                    requestKind = "None";
                }

                bool hiddenByPhysical =
                    requestBrake > 0
                    && physicalBrake >= requestBrake;

                bool outputMatchesRequest =
                    requestBrake > 0
                    && outputBrake == requestBrake;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[KINTETSU_SERVICE_EMERGENCY_CANDIDATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Strategy:{profile.DetectionStrategy}, "
                    + $"EmergencySourceA:{emergencySourceA}, "
                    + $"EmergencySourceB:{emergencySourceB}, "
                    + "ServiceMaximumSourceA:"
                    + $"{serviceMaximumSourceA}, "
                    + "ServiceMaximumSourceB:"
                    + $"{serviceMaximumSourceB}, "
                    + "SafetyEmergencyRequested:"
                    + $"{safetyEmergencyRequested}, "
                    + "SafetyServiceMaximumRequested:"
                    + $"{safetyServiceMaximumRequested}, "
                    + $"Request:{requestBrake}, "
                    + $"RequestKind:{requestKind}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + $"OutputMatchesRequest:{outputMatchesRequest}, "
                    + $"HiddenByPhysical:{hiddenByPhysical}, "
                    + "ScoringEnabled:False"
                );

                profile
                    .HasPreviousKintetsuServiceAndEmergencyCandidateState =
                    true;

                profile.PreviousKintetsuEmergencySourceA =
                    emergencySourceA;

                profile.PreviousKintetsuEmergencySourceB =
                    emergencySourceB;

                profile.PreviousKintetsuServiceMaximumSourceA =
                    serviceMaximumSourceA;

                profile.PreviousKintetsuServiceMaximumSourceB =
                    serviceMaximumSourceB;

                profile
                    .PreviousKintetsuServiceAndEmergencyPhysicalBrake =
                    physicalBrake;

                profile
                    .PreviousKintetsuServiceAndEmergencyServiceMaximum =
                    serviceMaximum;

                profile
                    .PreviousKintetsuServiceAndEmergencyEmergency =
                    emergency;

                profile
                    .PreviousKintetsuServiceAndEmergencyOutputBrake =
                    outputBrake;

                hasChanges = true;
            }
        }
        // =========================================================
        // ExplicitMetroBrakeRequestState方式の全プロファイルについて、
        // カタログ記載の内部要求状態を読み取る。
        //
        // 特定のSHA-256および固定RVAには依存しない。
        // この処理は診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseMetroRequestCandidates(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "ExplicitMetroBrakeRequestState",
                        StringComparison.Ordinal
                    )
                    || profile.DirectPhysicalBrakeRva == 0
                    || profile.DirectServiceMaximumRva == 0
                    || profile.DirectEmergencyRva == 0
                    || profile.DirectOutputBrakeRva == 0
                    || profile.MetroEmergencySelectionFlagRva == 0
                    || profile.MetroLevel7SelectionFlagRva == 0
                    || profile.MetroLevel4SelectionFlagRva == 0
                    || profile.MetroControlModeRva == 0
                    || profile.MetroInternalStateRva == 0
                )
                {
                    continue;
                }

                byte emergencySelectionFlag;
                byte level7SelectionFlag;
                byte serviceMaximumMinus3SelectionFlag;

                int controlMode;
                int internalState;
                int safetyEmergencySource = 0;

                int physicalBrake;
                int serviceMaximum;
                int emergency;
                int outputBrake;

                bool emergencySelectionRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.MetroEmergencySelectionFlagRva
                        ),
                        out emergencySelectionFlag
                    );

                bool level7SelectionRead =
                    TryReadRuntimeByte(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.MetroLevel7SelectionFlagRva
                        ),
                        out level7SelectionFlag
                    );

                bool serviceMaximumMinus3SelectionRead =
    TryReadRuntimeByte(
        IntPtr.Add(
            profile.ModuleBaseAddress,
            profile.MetroLevel4SelectionFlagRva
        ),
        out serviceMaximumMinus3SelectionFlag
    );

                bool controlModeRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.MetroControlModeRva
                        ),
                        out controlMode
                    );

                bool internalStateRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.MetroInternalStateRva
                        ),
                        out internalState
                    );

                bool safetyEmergencySourceAvailable =
                    profile.MetroSafetyEmergencySourceRva != 0;

                bool safetyEmergencySourceRead =
                    !safetyEmergencySourceAvailable
                    || TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.MetroSafetyEmergencySourceRva
                        ),
                        out safetyEmergencySource
                    );

                bool physicalRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectPhysicalBrakeRva
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectServiceMaximumRva
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectEmergencyRva
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectOutputBrakeRva
                        ),
                        out outputBrake
                    );

                if (
                    !emergencySelectionRead
                    || !level7SelectionRead
                    || !serviceMaximumMinus3SelectionRead
                    || !controlModeRead
                    || !internalStateRead
                    || !safetyEmergencySourceRead
                    || !physicalRead
                    || !serviceRead
                    || !emergencyRead
                    || !outputRead
                )
                {
                    continue;
                }

                if (
                    physicalBrake < -1
                    || physicalBrake > 100
                    || serviceMaximum < 0
                    || serviceMaximum > 100
                    || emergency < 0
                    || emergency > 100
                    || outputBrake < -1
                    || outputBrake > 100
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile.HasPreviousMetroRequestCandidateState
                    || emergencySelectionFlag
                        != profile.PreviousMetroEmergencyFlag
                    || level7SelectionFlag
                        != profile.PreviousMetroLevel7Flag
                    || serviceMaximumMinus3SelectionFlag
    != profile.PreviousMetroServiceMaximumMinus3Flag
                    || controlMode
                        != profile.PreviousMetroControlMode
                    || internalState
                        != profile.PreviousMetroInternalState
                    || safetyEmergencySource
                        != profile.PreviousMetroSafetyEmergencySource
                    || physicalBrake
                        != profile.PreviousRequestPhysicalBrake
                    || serviceMaximum
                        != profile.PreviousRequestServiceMaximum
                    || emergency
                        != profile.PreviousRequestEmergency
                    || outputBrake
                        != profile.PreviousRequestOutputBrake;

                if (!stateChanged)
                {
                    continue;
                }

                bool safetyEmergencySourceVerified =
    string.Equals(
        profile.SafetyEmergencySourceVerificationStatus,
        "DynamicVerificationPassed",
        StringComparison.Ordinal
    );

                bool safetyEmergencyRequested =
                    safetyEmergencySourceAvailable
                    && safetyEmergencySourceVerified
                    && safetyEmergencySource != 0;

                int requestBrake = 0;
                string requestKind = "None";

                if (safetyEmergencyRequested)
                {
                    requestBrake = emergency;
                    requestKind = "SafetyEmergency";
                }
                else if (level7SelectionFlag != 0)
                {
                    // 回生失効関連の出力調整によって、最終出力が
                    // serviceMaximum - 1になる場合でも、内部要求は常用最大。
                    requestBrake = serviceMaximum;
                    requestKind = "ServiceMaximum";
                }
                else if (serviceMaximumMinus3SelectionFlag != 0)
                {
                    requestBrake =
                        Math.Max(
                            0,
                            serviceMaximum - 3
                        );

                    requestKind = "ServiceMaximumMinus3";
                }


                string safetyEmergencySourceText =
                    safetyEmergencySourceAvailable
                        ? safetyEmergencySource.ToString()
                        : "<N/A>";

                bool outputReducedFromServiceMaximum =
    level7SelectionFlag != 0
    && controlMode == 1
    && outputBrake == serviceMaximum - 1;

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[METRO_REQUEST_CANDIDATE] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Strategy:{profile.DetectionStrategy}, "
                    + "EmergencySelectionFlag:"
                    + $"{emergencySelectionFlag}, "
                    + $"Level7Flag:{level7SelectionFlag}, "
                    + "ServiceMaximumMinus3Flag:"
                    + $"{serviceMaximumMinus3SelectionFlag}, "
                    + "RegenerativeBrakeAdjustmentState:"
                    + $"{controlMode}, "
                    + "OutputReducedFromServiceMaximum:"
                    + $"{outputReducedFromServiceMaximum}, "
                    + $"InternalState:{internalState}, "
                    + "SafetyEmergencySource:"
                    + $"{safetyEmergencySourceText}, "
                    + "SafetyEmergencySourceVerification:"
                    + $"{profile.SafetyEmergencySourceVerificationStatus}, "
                    + "SafetyEmergencySourceVerified:"
                    + $"{safetyEmergencySourceVerified}, "
                    + "SafetyEmergencyRequested:"
                    + $"{safetyEmergencyRequested}, "
                    + $"Request:{requestBrake}, "
                    + $"RequestKind:{requestKind}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + "HiddenByPhysical:"
                    + $"{(requestBrake > 0 && physicalBrake >= requestBrake)}, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousMetroRequestCandidateState =
                    true;

                profile.PreviousMetroEmergencyFlag =
                    emergencySelectionFlag;

                profile.PreviousMetroLevel7Flag =
                    level7SelectionFlag;

                profile.PreviousMetroServiceMaximumMinus3Flag =
    serviceMaximumMinus3SelectionFlag;

                profile.PreviousMetroControlMode =
                    controlMode;

                profile.PreviousMetroInternalState =
                    internalState;

                profile.PreviousMetroSafetyEmergencySource =
                    safetyEmergencySource;

                profile.PreviousRequestPhysicalBrake =
                    physicalBrake;

                profile.PreviousRequestServiceMaximum =
                    serviceMaximum;

                profile.PreviousRequestEmergency =
                    emergency;

                profile.PreviousRequestOutputBrake =
                    outputBrake;

                hasChanges = true;
            }
        }
        // =========================================================
        // ExplicitBrakeRequestFlags方式の全プロファイルについて、
        // カタログ記載の要求フラグを読み取る。
        //
        // 特定のDLL名、SHA-256、フラグ個数、配列位置には依存しない。
        // この処理は診断ログだけを生成し、採点には接続しない。
        // =========================================================
        private void DiagnoseExplicitBrakeRequestFlags(
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
                    profile.ModuleBaseAddress == IntPtr.Zero
                    || !string.Equals(
                        profile.DetectionStrategy,
                        "ExplicitBrakeRequestFlags",
                        StringComparison.Ordinal
                    )
                    || !string.Equals(
                        profile.DetectionPriority,
                        "EmergencyThenServiceMaximum",
                        StringComparison.Ordinal
                    )
                    || profile.DirectPhysicalBrakeRva == 0
                    || profile.DirectServiceMaximumRva == 0
                    || profile.DirectEmergencyRva == 0
                    || profile.DirectOutputBrakeRva == 0
                    || profile.ServiceMaximumRequestFlagRvas == null
                    || profile.ServiceMaximumRequestFlagRvas.Count == 0
                    || profile.EmergencyRequestFlagRvas == null
                    || profile.EmergencyRequestFlagRvas.Count == 0
                )
                {
                    continue;
                }

                List<byte> serviceMaximumRequestFlags;
                List<byte> emergencyRequestFlags;

                bool serviceFlagsRead =
                    TryReadRuntimeBytes(
                        profile.ModuleBaseAddress,
                        profile.ServiceMaximumRequestFlagRvas,
                        out serviceMaximumRequestFlags
                    );

                bool emergencyFlagsRead =
                    TryReadRuntimeBytes(
                        profile.ModuleBaseAddress,
                        profile.EmergencyRequestFlagRvas,
                        out emergencyRequestFlags
                    );

                int physicalBrake;
                int serviceMaximum;
                int emergency;
                int outputBrake;

                bool physicalRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectPhysicalBrakeRva
                        ),
                        out physicalBrake
                    );

                bool serviceRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectServiceMaximumRva
                        ),
                        out serviceMaximum
                    );

                bool emergencyRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectEmergencyRva
                        ),
                        out emergency
                    );

                bool outputRead =
                    TryReadRuntimeInt32(
                        IntPtr.Add(
                            profile.ModuleBaseAddress,
                            profile.DirectOutputBrakeRva
                        ),
                        out outputBrake
                    );

                if (
                    !serviceFlagsRead
                    || !emergencyFlagsRead
                    || !physicalRead
                    || !serviceRead
                    || !emergencyRead
                    || !outputRead
                )
                {
                    continue;
                }

                if (
                    physicalBrake < -1
                    || serviceMaximum < 0
                    || emergency < 0
                    || outputBrake < -1
                    || physicalBrake > 100
                    || serviceMaximum > 100
                    || emergency > 100
                    || outputBrake > 100
                )
                {
                    continue;
                }

                bool stateChanged =
                    !profile.HasPreviousRequestFlagState
                    || !RuntimeByteListsEqual(
                        serviceMaximumRequestFlags,
                        profile.PreviousServiceMaximumRequestFlags
                    )
                    || !RuntimeByteListsEqual(
                        emergencyRequestFlags,
                        profile.PreviousEmergencyRequestFlags
                    )
                    || physicalBrake
                        != profile.PreviousRequestPhysicalBrake
                    || serviceMaximum
                        != profile.PreviousRequestServiceMaximum
                    || emergency
                        != profile.PreviousRequestEmergency
                    || outputBrake
                        != profile.PreviousRequestOutputBrake;

                if (!stateChanged)
                {
                    continue;
                }

                bool serviceMaximumRequested =
                    serviceMaximumRequestFlags.Any(
                        value => value != 0
                    );

                bool emergencyRequested =
                    emergencyRequestFlags.Any(
                        value => value != 0
                    );

                int safetyRequestBrake = 0;
                string safetyRequestKind = "None";

                if (emergencyRequested)
                {
                    safetyRequestBrake = emergency;
                    safetyRequestKind = "Emergency";
                }
                else if (serviceMaximumRequested)
                {
                    safetyRequestBrake = serviceMaximum;
                    safetyRequestKind = "ServiceMaximum";
                }

                string activeServiceRvas =
                    FormatActiveRequestFlagRvas(
                        profile.ServiceMaximumRequestFlagRvas,
                        serviceMaximumRequestFlags
                    );

                string activeEmergencyRvas =
                    FormatActiveRequestFlagRvas(
                        profile.EmergencyRequestFlagRvas,
                        emergencyRequestFlags
                    );

                string requestSource;

                if (emergencyRequested)
                {
                    requestSource =
                        $"EmergencyFlags:{activeEmergencyRvas}";
                }
                else if (serviceMaximumRequested)
                {
                    requestSource =
                        $"ServiceFlags:{activeServiceRvas}";
                }
                else
                {
                    requestSource = "None";
                }

                if (!profile.HasPreviousInterventionState)
                {
                    profile.HasPreviousInterventionState = true;
                    profile.PreviousInterventionKind =
                        safetyRequestKind;
                }
                else if (
                    profile.PreviousInterventionKind
                        != safetyRequestKind
                )
                {
                    string transitionType;

                    if (
                        profile.PreviousInterventionKind == "None"
                        && safetyRequestKind != "None"
                    )
                    {
                        transitionType = "START";
                    }
                    else if (
                        profile.PreviousInterventionKind != "None"
                        && safetyRequestKind == "None"
                    )
                    {
                        transitionType = "END";
                    }
                    else
                    {
                        transitionType = "CHANGE";
                    }

                    rtLog.AppendLine(
                        $"[{DateTime.Now:HH:mm:ss.fff}] "
                        + "[RUNTIME_INTERVENTION] "
                        + $"Event:{transitionType}, "
                        + $"File:{profile.FileName}, "
                        + $"SHA256:{profile.Sha256}, "
                        + $"Pattern:{profile.Pattern}, "
                        + $"Strategy:{profile.DetectionStrategy}, "
                        + "PreviousKind:"
                        + $"{profile.PreviousInterventionKind}, "
                        + $"CurrentKind:{safetyRequestKind}, "
                        + $"SafetyRequest:{safetyRequestBrake}, "
                        + $"RequestSource:{requestSource}, "
                        + $"ActiveServiceRvas:{activeServiceRvas}, "
                        + $"ActiveEmergencyRvas:{activeEmergencyRvas}, "
                        + $"Physical:{physicalBrake}, "
                        + $"ServiceMax:{serviceMaximum}, "
                        + $"Emergency:{emergency}, "
                        + $"Output:{outputBrake}, "
                        + "ScoringEnabled:False"
                    );

                    profile.PreviousInterventionKind =
                        safetyRequestKind;

                    hasChanges = true;
                }

                rtLog.AppendLine(
                    $"[{DateTime.Now:HH:mm:ss.fff}] "
                    + "[RUNTIME_REQUEST_FLAGS] "
                    + $"File:{profile.FileName}, "
                    + $"SHA256:{profile.Sha256}, "
                    + $"Pattern:{profile.Pattern}, "
                    + $"Strategy:{profile.DetectionStrategy}, "
                    + "ServiceFlagValues:"
                    + $"{string.Join("|", serviceMaximumRequestFlags)}, "
                    + "EmergencyFlagValues:"
                    + $"{string.Join("|", emergencyRequestFlags)}, "
                    + $"ActiveServiceRvas:{activeServiceRvas}, "
                    + $"ActiveEmergencyRvas:{activeEmergencyRvas}, "
                    + $"SafetyRequest:{safetyRequestBrake}, "
                    + $"RequestKind:{safetyRequestKind}, "
                    + $"RequestSource:{requestSource}, "
                    + $"Physical:{physicalBrake}, "
                    + $"ServiceMax:{serviceMaximum}, "
                    + $"Emergency:{emergency}, "
                    + $"Output:{outputBrake}, "
                    + "ScoringEnabled:False"
                );

                profile.HasPreviousRequestFlagState = true;

                profile.PreviousServiceMaximumRequestFlags =
                    new List<byte>(
                        serviceMaximumRequestFlags
                    );

                profile.PreviousEmergencyRequestFlags =
                    new List<byte>(
                        emergencyRequestFlags
                    );

                profile.PreviousRequestPhysicalBrake =
                    physicalBrake;

                profile.PreviousRequestServiceMaximum =
                    serviceMaximum;

                profile.PreviousRequestEmergency =
                    emergency;

                profile.PreviousRequestOutputBrake =
                    outputBrake;

                hasChanges = true;
            }
        }

        public override void Tick(TimeSpan elapsed)
        {
            if (
                BveHacker.IsScenarioCreated
                && scenarioResetPending
            )
            {
                ResetAtsLoggerScenarioState();
                handledScenarioGeneration = scenarioGeneration;
                scenarioResetPending = false;
            }

            if (!BveHacker.IsScenarioCreated)
            {
                ResetAtsLoggerScenarioState();
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
                    header.AppendLine(
                        $"ScenarioGeneration={handledScenarioGeneration}"
                    );
                    header.AppendLine(
                        $"ScenarioIdentity={pendingScenarioIdentity}"
                    );
                    header.AppendLine(
                        $"LogSessionStarted={DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}"
                    );
                    header.AppendLine();

                    System.IO.File.WriteAllText(
                        realtimeLogPath,
                        header.ToString()
                    );

                    isLogSessionInitialized = true;
                }
                // AppDomain内のAtsPT5アセンブリとAtsMain型を診断する。
                DiagnoseAtsPtAppDomain(
                    bindFlagsAll,
                    rtLog,
                    ref hasChanges
                );

                // BveExホスト参照の全体診断は完了済み。
                // DiagnoseBveExHostReferences(
                //     rtLog,
                //     ref hasChanges
                // );

                // ExtensionSetの全項目展開は完了済み。
                // DiagnoseExtensionSet(
                //     rtLog,
                //     ref hasChanges
                // );

                // BveEx側の静的プラグイン管理参照の全体診断は完了済み。
                // DiagnoseBveExStaticPluginHosts(
                //     rtLog,
                //     ref hasChanges
                // );

                // BveEx.PluginHost.App.Instanceの診断は完了済み。
                // DiagnosePluginHostApp(
                //     rtLog,
                //     ref hasChanges
                // );

                // BveHackerイベント購読先の全体診断は完了済み。
                // DiagnoseBveHackerEventTargets(
                //     rtLog,
                //     ref hasChanges
                // );

                // 共通ランタイムプロファイルの診断
                DiagnoseRuntimeProfiles(
                    rtLog,
                    ref hasChanges
                );

                // .NET管理オブジェクト型プロファイルについて、
                // 対象ハッシュに一致するイベントTargetと
                // オブジェクト経路を解決する。
                ResolveManagedRuntimeProfiles(
                    rtLog,
                    ref hasChanges
                );

                // Pluginsは実走中もnullであることを確認済み。
                // 別経路の調査へ移行するため無効化する。
                // DiagnoseVehiclePlugins(
                //     bindFlagsAll,
                //     rtLog,
                //     ref hasChanges
                // );
                // NNN式C-ATSのcats2.dll内部要求候補を記録する。
                DiagnoseNnnCatsRequestState(
                    rtLog,
                    ref hasChanges
                );
                // 南海ATS-Nの内部非常要求状態を記録する。
                DiagnoseNankaiAtsNEmergencyRequestState(
                    rtLog,
                    ref hasChanges
                );
                // 南海ATS-PN内部で4系統を論理和した要求状態を記録する。
                DiagnoseNankaiAtsPnRequestState(
                    rtLog,
                    ref hasChanges
                );
                // 南海旧系統ATS-PNの内部要求候補を記録する。
                DiagnoseNankaiLegacyAtsPnRequestState(
                    rtLog,
                    ref hasChanges
                );
                // 阪急ATSの内部要求有効状態と要求段を記録する。
                DiagnoseHankyuEmergencyRequestState(
                    rtLog,
                    ref hasChanges
                );
                // MATCH済みのオブジェクト保持型プロファイルについて、
                // 実メモリ値を変化時だけ記録する。
                DiagnoseObjectBackedBrakeState(
                    rtLog,
                    ref hasChanges
                );

                // MATCH済みの3状態介入型プロファイルについて、
                // モード値を変化時だけ記録する。
                DiagnoseThreeStateBrakeIntervention(
                    rtLog,
                    ref hasChanges
                );

                // MATCH済みの固定RVA出力比較型プロファイルについて、
                // 物理入力と最終出力を変化時だけ記録する。
                DiagnoseDirectBrakeOutputComparison(
                    rtLog,
                    ref hasChanges
                );

                // 近鉄系ATSの2つの非常要求候補を個別に記録する。
                DiagnoseKintetsuEmergencyCandidates(
                    rtLog,
                    ref hasChanges
                );

                // 近鉄大阪線向け旧版の非常・常用最大要求候補を記録する。
                DiagnoseKintetsuServiceAndEmergencyCandidates(
                    rtLog,
                    ref hasChanges
                );

                // メトロ総合プラグインの内部指示段候補を記録する。
                DiagnoseMetroRequestCandidates(
                    rtLog,
                    ref hasChanges
                );

                // カタログでExplicitBrakeRequestFlags方式と判定された
                // 全プロファイルの要求フラグを診断する。
                DiagnoseExplicitBrakeRequestFlags(
                    rtLog,
                    ref hasChanges
                );

                // SWP2のATS-S要求とATS-P要求を装置別に復元し、最大値を記録する。
                DiagnoseSwp2DeviceAggregatedRequest(
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

                // =========================================================
                // 2 地上子(Beacon)の取得と通過判定
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
                    // 中央西線系AtsPT5の内部要求は、汎用MANAGED_RUNTIME経路を
                    // 主経路として取得する。
                    // =========================================================
                    DiagnoseManagedPrimaryRuntimeState(
                        physBrake,
                        atsBrake,
                        rtLog,
                        ref hasChanges
                    );

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
