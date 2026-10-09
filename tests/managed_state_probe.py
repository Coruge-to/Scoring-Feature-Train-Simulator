"""Phase E4 test helper (cross-language contract): reads the Caller's state block with the application's own reader and prints what it sees.

Usage: python tests\\managed_state_probe.py <bve-pid> <instance>
Protocol on stdin/stdout: every input line "read" is answered with one line
    S session=<0|1> driving=<0|1> closed=<0|1> gen=<n> changes=<n>       or       NONE <reason-word>
The line "quit" ends the probe. Used by the PowerShell test with a 64-bit and a 32-bit Caller writing the block.
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
        line = sys.stdin.readline()     # not "for line in sys.stdin": iteration may wait for more data on a pipe
        if not line:
            break
        line = line.strip().lstrip("\ufeff")
        if line == "quit":
            break
        if line != "read":
            continue
        s = reader.poll()
        if s is None:
            print("NONE", flush=True)
        else:
            print("S session=%d driving=%d closed=%d gen=%d changes=%d" % (s.session, s.driving, s.closed, s.generation, s.change_count), flush=True)
    reader.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
