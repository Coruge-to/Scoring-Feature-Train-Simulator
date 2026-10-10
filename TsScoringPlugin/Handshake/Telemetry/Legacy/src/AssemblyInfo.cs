using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;

// Public metadata (Phase L3 build). Human-facing product name: TS Scoring. No personal information.
[assembly: AssemblyTitle("TS Scoring AtsEX Legacy Telemetry")]
[assembly: AssemblyDescription("Phase L3: HUD telemetry sender for AtsEX legacy mode (data plane; independent of the Handshake bridge). 0.1.3.0 added a read-only input observation (diagnostic log only). 0.2.0.0 (Phase LI1) sends the handle group and the brake pressures (BCP, BPP) in the Current telemetry format. 0.3.0.0 (Phase LI2) adds the independent holding speed notches, the holding speed brake position and the one-lever Cl handle to the handle group. 0.3.1.0 (Phase SI-0) was an observation build (diagnostic log only). 0.4.0.0 (Phase SI-1) sends the Current ground limit contract: TRAINLEN (CarLength x (MotorCar + TrailerCar)), MAPLIMITS and CLEARDIST from the public speed limit list, and a MAPHEAD that is the limit at the head of the train (MAPTAIL stays the host value).")]
[assembly: AssemblyProduct("TS Scoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

// The offline tests (and nothing else) reach the internal core through this.
[assembly: InternalsVisibleTo("TsScoringLegacyTelemetryTests")]

[assembly: AssemblyVersion("0.4.0.0")]
[assembly: AssemblyFileVersion("0.4.0.0")]
[assembly: AssemblyInformationalVersion("0.4.0.0")]
