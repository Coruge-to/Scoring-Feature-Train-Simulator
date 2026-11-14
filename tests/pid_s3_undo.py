"""Phase PID-S3 (on purpose, Owner 2026-11-14): the observation log is one file per BVE PROCESS.

Older byte-identity guards (LC-2 season-2 files, LC-5 shutdown set) compare ObservationLog.cs / HandshakeSession.cs with a base commit and allow only a named
display-string difference. This helper undoes EXACTLY the PID-S3 edits (and nothing else), so everything else in those files is still held byte for byte.
"""

_OBS = (
    # (new text, old text)
    ('        // Phase PID-S3: one file PER BVE PROCESS (the name carries the PID), so a later BVE can never truncate the evidence of an earlier one. The Caller and both\n'
     '        // Bridges of one process share that process\'s file. (No instance id: the DLLs do not know the application\'s instance GUID, and the PID is the process.)\n'
     '        internal const string FileNamePrefix = "TSScoring-Phase-C1-Observation-P";\n'
     '        internal const string FileNameSuffix = ".log";\n',
     '        internal const string FileName = "TSScoring-Phase-C1-Observation.log";\n'),
    ('        internal static string TestFolder { get; set; }   // PID-S3: replaces <user profile>\\Downloads (the per-PID NAME is still computed by DefaultPathFor)\n', ''),
    ('        internal static string DefaultPath()\n'
     '        {\n'
     '            return DefaultPathFor(TestPid != 0 ? TestPid : HandshakeProtocol.CurrentProcessId());\n'
     '        }\n'
     '\n'
     '        /// <summary>The per-PID file of process <paramref name="processId"/>. Pure: creates nothing.</summary>\n'
     '        internal static string DefaultPathFor(int processId)\n'
     '        {\n'
     '            try\n'
     '            {\n'
     '                if (!string.IsNullOrEmpty(TestFolder))\n'
     '                {\n'
     '                    return Path.Combine(TestFolder, FileNamePrefix + processId + FileNameSuffix);\n'
     '                }\n'
     '\n',
     '        internal static string DefaultPath()\n'
     '        {\n'
     '            try\n'
     '            {\n'),
    ('FileNamePrefix + processId + FileNameSuffix);\n            }\n            catch', 'FileName);\n            }\n            catch'),
    ('                pid = TestPid != 0 ? TestPid : HandshakeProtocol.CurrentProcessId();\n'
     '                path = TestPath ?? DefaultPathFor(pid);\n',
     '                path = TestPath ?? DefaultPath();\n'
     '                pid = TestPid != 0 ? TestPid : HandshakeProtocol.CurrentProcessId();\n'),
)

_CALLER = (
    ('ObservationLog.FileNamePrefix + HandshakeProtocol.CurrentProcessId() + ObservationLog.FileNameSuffix);', 'ObservationLog.FileName);'),
)


def _undo(text, pairs):
    for new, old in pairs:
        text = text.replace(new, old)
    return text


def undo_observation_log(text):
    return _undo(text, _OBS)


def undo_caller_notice(text):
    return _undo(text, _CALLER)
