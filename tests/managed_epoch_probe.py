"""Phase SI-A7 (M1a) test helper (cross-language contract): reads the Caller's state block with the application's own reader and prints the Ready epoch it sees.

Usage: python tests\\managed_epoch_probe.py <bve-pid> <instance>
Protocol on stdin/stdout: every input line "read" is answered with one line
    E supported=<0|1> tick_seen=<0|1> epoch=<n> session=<0|1> gen=<n> changes=<n> info=<n>       or       NONE
The line "quit" ends the probe. Used by the PowerShell test (Test-ExtensionControlPlaneSIA7.ps1) with the Caller's own publisher writing the block.
Nothing here writes anything or sends any key.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import managed_mode  # noqa: E402
import managed_state  # noqa: E402


def main():
    pid, inst = int(sys.argv[1]), sys.argv[2]
    args = managed_mode.ManagedArgs(pid, inst, "probe")
    reader = managed_state.StateReader(args, managed_state.Win32StateSource(), lambda text: None)
    opened = reader.open()
    print("OPEN %s" % ("yes" if opened else "no"), flush=True)
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip().lstrip("﻿")
        if line == "quit":
            break
        if line != "read":
            continue
        s = reader.poll()
        if s is None:
            print("NONE", flush=True)
        else:
            print("E supported=%d tick_seen=%d epoch=%d session=%d gen=%d changes=%d info=%d" % (
                s.epoch_supported, s.epoch_tick_seen, s.ready_epoch, s.session, s.generation, s.change_count, s.epoch_info), flush=True)
    reader.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
