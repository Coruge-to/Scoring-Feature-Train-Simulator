using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;

// Public metadata (Phase L3 build). Human-facing product name: TS Scoring. No personal information.
[assembly: AssemblyTitle("TS Scoring AtsEX Legacy Telemetry")]
[assembly: AssemblyDescription("Phase L3: HUD telemetry sender for AtsEX legacy mode (data plane; independent of the Handshake bridge). 0.1.3.0 added a read-only input observation (diagnostic log only). 0.2.0.0 (Phase LI1) sends the handle group and the brake pressures (BCP, BPP) in the Current telemetry format. 0.3.0.0 (Phase LI2) adds the independent holding speed notches, the holding speed brake position and the one-lever Cl handle to the handle group. 0.3.1.0 (Phase SI-0) was an observation build (diagnostic log only). 0.4.0.0 (Phase SI-1) sends the Current ground limit contract: TRAINLEN (CarLength x (MotorCar + TrailerCar)), MAPLIMITS and CLEARDIST from the public speed limit list, and a MAPHEAD that is the limit at the head of the train (MAPTAIL stays the host value). 0.4.2.0 (Phase PID-D4 Slice 1) moves the transport to the per-PID DataPlane: in managed mode every text goes as an Envelope v1 to the Directory-published endpoint of this BVE process (fail closed, no fixed-port fallback); in normal mode the plain text to the fixed port is unchanged; the diagnostic log is one file per BVE process. 0.5.0.0 (Phase PID-D4 Legacy Jump 2A-alpha) adds the Legacy Jump control plane: once the managed mode is confirmed a dedicated worker publishes the Legacy Jump Directory of this BVE process (a dynamic loopback port, a new generation and token per publication, REQUEST_ID capability only), judges the datagrams it receives and keeps or discards the accepted command; it executes nothing, calls no host API and announces no jump. 0.6.0.0 (Phase PID-D4 Legacy Jump LJX-1, the minimal execution slice) adds the Legacy Jump execution BEHIND A BUILD FLAG (the default build is unchanged: the Directory still carries REQUEST_ID only and nothing is executed): in the acceptance build the host Tick claims one accepted command, runs the station or location jump through the host seam, writes the row with the JUMP counter and then sends the completion notice with the echoed request id; the Directory carries STA, LOC and REQUEST_ID and the telemetry announces the jump group only while that contract is open.")]
[assembly: AssemblyProduct("TS Scoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

// The offline tests (and nothing else) reach the internal core through this.
[assembly: InternalsVisibleTo("TsScoringLegacyTelemetryTests")]

[assembly: AssemblyVersion("0.6.0.0")]
[assembly: AssemblyFileVersion("0.6.0.0")]
[assembly: AssemblyInformationalVersion("0.6.0.0")]
