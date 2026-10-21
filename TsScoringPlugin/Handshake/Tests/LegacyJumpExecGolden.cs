using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP LJX-1 - the golden output of the flag OFF telemetry (TEST CODE ONLY).
//
// A fully scripted run of the REAL session (the 8 argument constructor of the 2A-alpha build: no availability, no execution) over the fake Legacy API of the earlier
// phases. Everything the session sends and logs is written down as one text; the runner stores the SHA-256 of that text BEFORE the LJX-1 product exists (Stage 0) and
// compares it after: the OFF build must not change a single byte. Only types that exist in the 2A-alpha build are bound at compile time.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    public static partial class LegacyJumpExecTestFixture
    {
        private static FakeStation Station(string name, double loc, bool pass, bool term, int arr, int dep)
        {
            FakeStation s = new FakeStation();
            s.Name = name;
            s.Location = loc;
            s.Pass = pass;
            s.IsTerminal = term;
            s.ArrivalMs = arr;
            s.DepartureMs = dep;
            return s;
        }

        private static void Script(Harness h, StringBuilder sb, string tag)
        {
            h.Api.Stations.Add(Station("A", 0.0, false, false, -1, 36060000));
            h.Api.Stations.Add(Station("B", 1000.0, false, false, 36100000, 36130000));
            h.Api.Stations.Add(Station("C", 2000.0, true, false, -1, -1));
            h.Api.Stations.Add(Station("D", 3000.0, false, true, 36400000, -1));
            h.Api.Created = true;
            h.NoteInit("events=yes heartbeat=yes");
            h.Opened(false);
            h.Created();
            h.Run(6, 16);
            sb.AppendLine("# " + tag + " after 6 ticks lines=" + h.LinesSent + " disc=" + h.Discontinuities);
            h.Api.SpeedMps = 12.5;
            h.Api.Location = 1010.0;
            h.Api.DoorsClosed = false;
            h.Run(4, 33);
            h.Api.DoorsClosed = true;
            h.Run(3, 20);
            h.Api.TimeMs += 120000;                 // a jump of the simulation time (the 300 ms rule)
            h.Run(2, 16);
            sb.AppendLine("# " + tag + " after the jump disc=" + h.Discontinuities);
            h.Api.Location = 2500.0;
            h.Api.SpeedMps = 0.0;
            h.Run(5, 16);
            h.Tick(16.0);
            h.Api.Fail.Add("TryGradientRatio");
            h.Run(2, 16);
            h.Api.Fail.Clear();
            h.Api.Created = false;
            h.Run(2, 16);
            h.Api.Created = true;
            h.Closed();
            h.Opened(true);
            h.Created();
            h.Run(5, 16);
            sb.AppendLine("# " + tag + " heartbeat=" + h.Heartbeat());
            h.Dispose();
            sb.AppendLine("# " + tag + " lines=" + h.LinesSent + " skipped=" + h.LinesSkipped + " epochs=" + h.Epochs + " disc=" + h.Discontinuities);
            foreach (string s in h.Sink.Sent) sb.AppendLine("S " + s);
            foreach (string e in h.Diag.Events) sb.AppendLine("D " + e);
        }

        /// <summary>The scripted output of the OFF session as one text (several wirings: L3 only, with input, with everything).</summary>
        public static string GoldenOffText()
        {
            StringBuilder sb = new StringBuilder();
            Script(new Harness(), sb, "plain");
            Script(new Harness(true, true), sb, "input");
            Script(new Harness(true, true, true, true), sb, "full");
            // the managed thread id of the recorder lines (th=) differs from run to run; nothing else does
            return System.Text.RegularExpressions.Regex.Replace(sb.ToString(), @" th=\d+", " th=T");
        }

        public static string GoldenOffSha256()
        {
            using (SHA256 h = SHA256.Create())
            {
                return BitConverter.ToString(h.ComputeHash(Encoding.UTF8.GetBytes(GoldenOffText()))).Replace("-", string.Empty);
            }
        }
    }
}
