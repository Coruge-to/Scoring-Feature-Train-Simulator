"""Phase PID-D4JA StationIndex ST-3e0 - the package contract of the Jump / StationIndex package (constants only).

TSJUMP2 is ONE capability bundle, not a set of switches: a package that carries it has
  * the Jump request wire v2 (7 fields) and the Jump completion wire v2 (9 fields),
  * the Current and the Legacy selected_idx, the target reinitialization of the sender,
  * the Python completion settlement, the retry history settlement, the StationIndex transaction,
  * the Legacy R1-B resend, and the Current station-range fail-closed rejection (a rejected list is rejected as a whole and never published in part).
The tag has one definition per language: this module (Python) and Handshake/Telemetry/Shared/PackageContract.cs (compiled by BOTH the Current and the Legacy project).
They must stay equal to each other and to package/source-package-manifest.json; package/source_package.py (the N-12 package guard) refuses a package where they are not.

No import, no function, no file, no network: this module is imported by main.py so that it is part of the runtime set of the package, and it does nothing else.
The wire versions below are the versions of the existing wires (JumpWire V2, the STIDX wire 1); this module does not define a wire.
"""
CONTRACT_TAG = "TSJUMP2"
REQUEST_WIRE_VERSION = 2
COMPLETION_WIRE_VERSION = 2
STATIONINDEX_WIRE_VERSION = 1
CAPABILITIES = (
    "jump-request-v2",
    "jump-completion-v2",
    "current-selected-idx",
    "legacy-selected-idx",
    "python-completion-settlement",
    "stationindex-transaction",
    "target-reinitialization",
    "retry-history-settlement",
    "legacy-r1b",
    "current-station-range-fail-closed",
    "whole-list-reject",
    "partial-list-not-published",
)
