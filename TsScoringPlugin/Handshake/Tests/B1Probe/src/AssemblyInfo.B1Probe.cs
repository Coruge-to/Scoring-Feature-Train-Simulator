using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;

// Phase SI-B1 B1-probe: an OBSERVATION-ONLY build of the AtsEX Legacy telemetry DLL. NOT a release, NOT Phase SI-B2 (that is 0.5.0.0).
// It sends exactly the telemetry of 0.4.0.0, and on top of that performs ONE explicitly requested Initialize / SetTime sequence per request file on the Extension Tick
// and logs it (Downloads\TSScoring-B1Probe.log). The product telemetry DLL (src\AssemblyInfo.cs, 0.4.0.0) is not changed. No personal information.
[assembly: AssemblyTitle("TS Scoring AtsEX Legacy Telemetry [B1-PROBE OBSERVATION BUILD - NOT A RELEASE]")]
[assembly: AssemblyDescription("Phase SI-B1 B1-probe 0.4.1.1: OBSERVATION-ONLY build (0.4.1.0 is the build that was run on the real machine; 0.4.1.1 only corrects the probe's own verdict on a discontinuity Tick and on the Tick right after the call, see the SI-B1 document). The telemetry is the 0.4.0.0 telemetry byte for byte; in addition, only when a request file is placed by the observation scripts, it performs one Scenario.Initialize / InitializeTimeAndLocation / TimeManager.SetTime sequence on the Extension Tick and writes a detailed log. It announces no jump, answers no COMPLETE and starts no scoring. Restore the accepted 0.4.0.0 DLL after the observation.")]
[assembly: AssemblyProduct("TS Scoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("B1-PROBE-OBSERVATION-ONLY")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

// The offline tests (and nothing else) reach the internal core through this.
[assembly: InternalsVisibleTo("TsScoringLegacyTelemetryTests")]

[assembly: AssemblyVersion("0.4.1.1")]
[assembly: AssemblyFileVersion("0.4.1.1")]
[assembly: AssemblyInformationalVersion("0.4.1.1-b1-probe-observation-only")]
