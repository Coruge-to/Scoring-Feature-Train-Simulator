"""Phase L3 (scenario identity fix): feeds the datagrams a C# sender produced (one per line of the file given as argument, UTF-8) to the REAL
TelemetryGate of the application in strict (managed) mode - no Qt, no socket - and prints, as JSON, what the gate did. A line `@GEN:<n>` in the file is
the Caller's ScenarioGeneration changing to n (the gate starts at generation 1). Used by Test-TelemetryL3.ps1 to prove that a sender that keeps one
SCENARIO_ID per scenario instance is never "ahead" of the Caller and that the HUD gate stays ready after the first accepted line.

    python -I tests\\telemetry_gate_check.py <file>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telemetry_gate  # noqa: E402


def main(path):
    events = []
    gate = telemetry_gate.TelemetryGate(strict=True, log=lambda event, **fields: events.append(event))
    gate.on_generation(1)
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().split("\n") if line]
    ready_after_first = None
    not_ready_after_first = 0
    accepted_flags = []
    for text in lines:
        if text.startswith("@GEN:"):
            gate.on_generation(int(text.split(":", 1)[1]))
            ready_after_first = None
            continue
        if not text.startswith("SCENARIO_ID:"):
            continue
        accepted = gate.accept(text)
        accepted_flags.append(accepted)
        if accepted and ready_after_first is None:
            ready_after_first = gate.ready
        if ready_after_first is not None and not gate.ready:
            not_ready_after_first += 1
    out = {"stats": gate.summary_fields(), "ready": gate.ready, "wait_reason": gate.wait_reason, "events": events,
           "accepted_all": all(accepted_flags) if accepted_flags else None, "not_ready_after_first": not_ready_after_first,
           "lines": len(accepted_flags)}
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
