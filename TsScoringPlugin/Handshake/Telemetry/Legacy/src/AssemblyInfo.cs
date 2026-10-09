using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;

// Public metadata (Phase L3 build). Human-facing product name: TS Scoring. No personal information.
[assembly: AssemblyTitle("TS Scoring AtsEX Legacy Telemetry")]
[assembly: AssemblyDescription("Phase L3: HUD telemetry sender for AtsEX legacy mode (data plane; independent of the Handshake bridge).")]
[assembly: AssemblyProduct("TS Scoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

// The offline tests (and nothing else) reach the internal core through this.
[assembly: InternalsVisibleTo("TsScoringLegacyTelemetryTests")]

[assembly: AssemblyVersion("0.1.2.0")]
[assembly: AssemblyFileVersion("0.1.2.0")]
[assembly: AssemblyInformationalVersion("0.1.2.0")]
