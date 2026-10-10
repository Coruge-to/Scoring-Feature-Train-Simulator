using System;
using System.Reflection;
using System.Runtime.InteropServices;

// Public metadata (Phase SI-A7 M1a build: SI-A6 + the Ready epoch of the Bridge read and copied to the managed application; Phase SI-A6: E4 + the load marker - ScenarioCreated / first Tick of the generation - copied from the Bridge to the managed application). Human-facing product name: TS Scoring. No personal information.
[assembly: AssemblyTitle("TS Scoring Input Device Caller")]
[assembly: AssemblyDescription("Phase E4 build (Phase SI-A7 M1a adds the Ready epoch and its TickSeenInEpoch flag, read from the Bridge, logged and copied to the managed application as plain information that nothing acts on; Phase SI-A6 adds the load marker of the generation: ScenarioCreated / first Tick, copied from the Bridge to the managed application): Session / Driving state published to the managed application, managed application process (start, AppReady, stop at Dispose; launcher.json permitting), AppController decisions, DrivingActive state, BveEX dependency notice at scenario use start, Ready handshake and ScenarioReady reader")]
[assembly: AssemblyProduct("TS Scoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

[assembly: AssemblyVersion("0.13.0.0")]
[assembly: AssemblyFileVersion("0.13.0.0")]
[assembly: AssemblyInformationalVersion("0.13.0.0")]
