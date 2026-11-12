using System;
using System.Reflection;
using System.Runtime.InteropServices;

// Public metadata. Human-facing product name: TScoring. No personal information.
// DLL suffix A = the legacy compatibility path.
// The five public DLLs (Input Device, Bridge B, Telemetry B, Bridge A, Telemetry A) share one release version.
[assembly: AssemblyTitle("TScoring Bridge A")]
[assembly: AssemblyDescription("TScoring bridge for the legacy compatibility path (DLL suffix A): publishes the scenario life-cycle (ScenarioReady) and the Ready handshake to the TScoring application.")]
[assembly: AssemblyProduct("TScoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

[assembly: AssemblyVersion("0.14.0.0")]
[assembly: AssemblyFileVersion("0.14.0.0")]
[assembly: AssemblyInformationalVersion("0.14.0.0")]
