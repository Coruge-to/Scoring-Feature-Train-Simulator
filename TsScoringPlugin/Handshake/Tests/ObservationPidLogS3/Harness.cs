// Phase PID-S3 (offline): the observation log is ONE FILE PER BVE PROCESS. ObservationLog.cs and HandshakeProtocol.cs are compiled into this console harness
// (same assembly, so the internal members are reachable). Every file goes to a private temp folder (ObservationLog.TestFolder); no BVE, no network, no Downloads.
// LOG-R1 two PIDs write to separate files           LOG-R2 a later PID never truncates an earlier PID's log
// LOG-R3 inside one PID / run the log is only appended, a NEW run of the same PID starts the file again
// LOG-R5 nothing is appended to another PID's file  LOG-R6 a PID change (Current -> Legacy) gives a different file
using System;
using System.IO;
using TSScoringPlugin.Handshake;

internal static class Harness
{
    private static int failures;
    private static int passes;

    private static void Check(string name, bool ok)
    {
        Console.WriteLine((ok ? "PASS " : "FAIL ") + name);
        if (ok) { passes++; } else { failures++; }
    }

    private static string Slurp(string path)
    {
        using (FileStream fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (StreamReader sr = new StreamReader(fs))
        {
            return sr.ReadToEnd();
        }
    }

    private static int Main(string[] args)
    {
        string folder = args[0];
        // the PRODUCTION path (no test folder): pure, creates nothing
        string production = ObservationLog.DefaultPathFor(31337);
        Check("LOG-R1 the production path is <profile>\\Downloads\\TSScoring-Phase-C1-Observation-P<pid>.log", production != null && production.EndsWith("\\Downloads\\TSScoring-Phase-C1-Observation-P31337.log", StringComparison.Ordinal));
        Directory.CreateDirectory(folder);
        ObservationLog.TestFolder = folder;
        const int current = 41001;   // the Current-side PID of a Current -> Legacy switch
        const int legacy = 41002;    // the Legacy-side PID
        const int other = 52003;     // a second, unrelated BVE

        string nameCurrent = Path.GetFileName(ObservationLog.DefaultPathFor(current));
        Check("LOG-R1 the name carries the PID: " + nameCurrent, nameCurrent == "TSScoring-Phase-C1-Observation-P41001.log");

        ObservationLog.ResetForTests();
        ObservationLog.TestPid = current;
        ObservationLog.Write("A", "FIRST_PID_EVENT", "k=1");
        ObservationLog.Write("A", "FIRST_PID_EVENT_2", "k=2");
        string firstPath = ObservationLog.DefaultPathFor(current);
        string firstBefore = Slurp(firstPath);
        Check("LOG-R1 the first PID wrote its own file", File.Exists(firstPath) && firstBefore.Contains("FIRST_PID_EVENT_2") && firstBefore.Contains("P=" + current));
        Check("LOG-R3 inside one run the earlier line is kept (appended, not truncated)", firstBefore.Contains("FIRST_PID_EVENT k=1") && firstBefore.Contains("FIRST_PID_EVENT_2 k=2"));

        // a LATER PID in another log session (the first PID's marker object stays alive in this process through the second name: they are different names)
        ObservationLog.ResetForTests();
        ObservationLog.TestPid = other;
        ObservationLog.Write("A", "SECOND_PID_EVENT", "k=1");
        string otherPath = ObservationLog.DefaultPathFor(other);
        Check("LOG-R1 the later PID wrote a DIFFERENT file", File.Exists(otherPath) && otherPath != firstPath && Slurp(otherPath).Contains("SECOND_PID_EVENT"));
        string firstAfter = Slurp(firstPath);
        Check("LOG-R2 the later PID did not truncate or change the earlier PID's log", firstAfter == firstBefore);
        Check("LOG-R5 nothing of the later PID is in the earlier PID's file", !firstAfter.Contains("SECOND_PID_EVENT") && !Slurp(otherPath).Contains("FIRST_PID_EVENT"));

        // Current -> Legacy: the new PID has its own file; the Current-side file keeps its lines
        ObservationLog.ResetForTests();
        ObservationLog.TestPid = legacy;
        ObservationLog.Write("A", "LEGACY_SIDE_EVENT", "k=1");
        string legacyPath = ObservationLog.DefaultPathFor(legacy);
        Check("LOG-R6 Current and Legacy PIDs are different files and the Current-side file is intact",
            File.Exists(legacyPath) && legacyPath != firstPath && Slurp(firstPath) == firstBefore && !Slurp(legacyPath).Contains("FIRST_PID_EVENT"));

        // a NEW run of the same PID (its run marker is gone) starts its own file again: the expected truncate contract
        ObservationLog.ResetForTests();
        ObservationLog.TestPid = current;
        ObservationLog.Write("A", "NEW_RUN_EVENT", "k=1");
        string restarted = Slurp(firstPath);
        Check("LOG-R3 a new run of the same PID starts its file again (the old lines are gone, the new one is there)", restarted.Contains("NEW_RUN_EVENT") && !restarted.Contains("FIRST_PID_EVENT_2"));

        // the default (no TestPid) uses the real process id of this harness, never a fixed name
        ObservationLog.TestPid = 0;
        string own = ObservationLog.DefaultPath();
        Check("LOG-R1 the default name is the process's own PID", own == ObservationLog.DefaultPathFor(HandshakeProtocol.CurrentProcessId()) && own.EndsWith("-P" + HandshakeProtocol.CurrentProcessId() + ".log", StringComparison.Ordinal));

        ObservationLog.ResetForTests();
        Console.WriteLine("PASS=" + passes + " FAIL=" + failures);
        return failures == 0 ? 0 : 1;
    }
}
