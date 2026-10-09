"""Phase L3: reads the datagrams a C# sender produced (one per line of the file given as argument, UTF-8) with the REFERENCE reader of the contract
(telemetry_contract) and prints one JSON object per line. Standard library only; used by Test-TelemetryL3.ps1 to prove that the two languages agree.

    python -I tests\\telemetry_xcheck.py <file>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telemetry_contract as tc  # noqa: E402


def main(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out = []
    for text in lines:
        if not text:
            continue
        if not text.startswith("SCENARIO_ID:"):
            out.append({"kind": text.split(":", 1)[0]})
            continue
        line = tc.parse_telemetry(text)
        keys = [p.split(":", 1)[0] for p in text.split(",")]
        out.append({"kind": "telemetry", "valid": line.valid, "reason": line.reason, "sid": line.scenario_id, "avail": line.avail_status,
                    "tokens": sorted(line.tokens) if line.tokens is not None else None, "unknown": line.unknown_tokens, "bad": line.bad_tokens,
                    "keys": keys})
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
