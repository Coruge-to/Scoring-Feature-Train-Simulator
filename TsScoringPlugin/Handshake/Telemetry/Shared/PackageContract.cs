// ============================================================================
// PHASE PID-D4JA StationIndex ST-3e0 - the package contract of the Jump / StationIndex package (constants only), shared by BOTH senders
// (the BveEX Current plugin links this file, the AtsEX Legacy telemetry DLL links the same file). Host independent: no BVE, no AtsEX, no BveEX name.
//
// TSJUMP2 is ONE capability bundle, not a set of switches: Jump request wire v2 and completion wire v2, Current and Legacy selected_idx, the target reinitialization,
// the Python completion settlement and retry history settlement, the StationIndex transaction, the Legacy R1-B resend and the Current station-range fail-closed
// rejection (a rejected list is rejected as a whole and never published in part). The Python twin is package_contract.py. The tag has ONE definition per language;
// the two must stay equal to each other and to package/source-package-manifest.json (the N-12 package guard, package/source_package.py, refuses a package where they are not).
//
// The values are compiled constants and nothing in the DLL calls them: the file only lets a build be recognized by its bytes (the tag text is in the assembly)
// and by reflection. The versions are the versions of the existing wires (JumpWire V2, the STIDX wire 1); this file defines no wire and no behaviour.
// ============================================================================
namespace TSScoringPlugin.Package
{
    internal static class PackageContract
    {
        internal const string Tag = "TSJUMP2";
        internal const int RequestWireVersion = 2;
        internal const int CompletionWireVersion = 2;
        internal const int StationIndexWireVersion = 1;
        internal const string Capabilities = "jump-request-v2,jump-completion-v2,current-selected-idx,legacy-selected-idx,python-completion-settlement,stationindex-transaction,target-reinitialization,retry-history-settlement,legacy-r1b,current-station-range-fail-closed,whole-list-reject,partial-list-not-published";
    }
}
