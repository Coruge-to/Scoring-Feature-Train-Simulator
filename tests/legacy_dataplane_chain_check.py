"""PID-D4 Slice 1: feeds the Envelope v1 datagrams that the REAL Legacy telemetry sender produced (Test-LegacyDataPlaneD4.ps1 -> LegacyDataPlaneTestFixture.WriteGolden)
to the REAL application path of the managed mode - the real Overlay (offscreen Qt) with its strict gate and the real TelemetryDataPlaneReceiver - through a real UDP
socket on the Overlay's own dynamic port, and prints what the Overlay holds and draws afterwards, as JSON. Nothing of the application is changed or mocked.

    python -I tests\\legacy_dataplane_chain_check.py <golden folder>

The folder holds legacy_NNN.bin (one datagram each), legacy_manifest.txt ("NNN type") and legacy_identity.txt (BVE pid, AppInstance, generation, token hex).
Besides the good datagrams the script also sends, to the same socket, the plain texts of the SAME datagrams (what the Legacy sender used to send to 54321) and
datagrams of another generation / token / instance / BVE pid: all of them must be dropped by the receiver, and none may change the Overlay.
"""
import json
import os
import socket
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataplane_contract as contract  # noqa: E402


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.002)


def _read(folder):
    with open(os.path.join(folder, "legacy_identity.txt"), encoding="ascii") as stream:
        pid, instance, generation, token = stream.read().split()
    manifest = []
    with open(os.path.join(folder, "legacy_manifest.txt"), encoding="ascii") as stream:
        for line in stream.read().split("\n"):
            if line.strip():
                index, kind = line.split()
                with open(os.path.join(folder, "legacy_%s.bin" % index), "rb") as data:
                    manifest.append((int(kind), data.read()))
    return int(pid), instance, int(generation), bytes.fromhex(token), manifest


def main(folder):
    from PyQt6.QtWidgets import QApplication
    app = QApplication(["d4"])
    import hud_ui
    import main
    import telemetry_dataplane_receiver
    import telemetry_gate
    main.write_desktop_log = lambda *a, **k: None               # the Overlay logs a door time to the Desktop; a check must not
    pid, instance, generation, token, manifest = _read(folder)

    overlay = main.Overlay(0)                                   # a dynamic port, exactly like the managed application (never 54321)
    overlay.timer.stop()
    if not overlay.udp_bind_ok:
        sys.stdout.write(json.dumps({"error": "udp-bind-failed"}))
        return 3
    overlay.dataplane_strict = True
    receiver = telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(pid, instance, generation, token)
    overlay.dataplane_receiver = receiver
    overlay.telemetry_gate = telemetry_gate.TelemetryGate(strict=True)
    overlay.telemetry_gate.on_generation(1)

    drawn = []
    original = hud_ui.draw_text_with_stroke
    hud_ui.draw_text_with_stroke = lambda painter, text, *a, **k: drawn.append(text)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = ("127.0.0.1", overlay.udp_port)

    def send(data):
        sender.sendto(data, target)
        _pump(app, 0.05)

    # 1. what must NOT change anything: the plain texts of the very same datagrams (the pre-migration wire), and four foreign identities
    hostile = 0
    for kind, data in manifest:
        send(contract.decode_envelope(data)["payload"])         # the plain text of that datagram, unwrapped (the pre-migration wire)
        hostile += 1
    # the same real datagrams offered to receivers of another BVE pid / generation / token / AppInstance: all of them must reject every one
    foreign = [
        telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(pid + 1, instance, generation, token),
        telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(pid, instance, generation + 1, token),
        telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(pid, instance, generation, bytes(reversed(token))),
        telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(pid, "fedcba0987abcdeffedcba0987abcdef", generation, token),
    ]
    foreign_rejected = [all(r.accept(data) is None for _kind, data in manifest) for r in foreign]
    hud_before = {"speed": overlay.bve_speed, "time": overlay.bve_time_ms, "scenario": overlay.current_scenario_id}

    # 2. the real datagrams, in the order the sender produced them
    for kind, data in manifest:
        send(data)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    sender.close()
    overlay.grab()
    gate = overlay.telemetry_gate
    names = ("bve_speed", "bve_time_ms", "bve_location", "bve_gradient", "bve_next_loc", "bve_next_time", "bve_is_pass", "bve_is_timing",
             "bve_margin_b", "bve_margin_f", "bve_door", "bve_doordir", "bve_term", "bve_current_station_name", "bve_signal_limit",
             "bve_fwd_sig_limit", "bve_fwd_sig_loc", "map_head_limit", "map_tail_limit", "bve_calc_g", "bve_btype", "cab_brk_count",
             "has_holding_brake", "bve_pressure_rates", "bve_max_pressure", "meta_title", "meta_route", "meta_vehicle", "meta_author",
             "current_scenario_id", "bve_rev_text", "bve_pow_text", "bve_brk_text", "bcPressure", "bpPressure", "bve_train_length",
             "bve_actual_state", "is_bve_loaded")
    values = {n: getattr(overlay, n, None) for n in names}
    values["station_names"] = [s["name"] for s in overlay.station_list]
    values["station_terminal"] = [s["is_terminal"] for s in overlay.station_list]
    out = {
        "values": values,
        "hud_before_real_datagrams": hud_before,
        "plain_sent": hostile,
        "foreign_rejected": foreign_rejected,
        "receiver": {"accepted": receiver.accepted, "rejected": receiver.rejected, "reasons": receiver.reasons},
        "datagrams": len(manifest),
        "types": [kind for kind, _data in manifest],
        "ready": gate.ready,
        "wait_reason": gate.wait_reason,
        "tokens": sorted(gate.availability.tokens) if gate.availability.tokens is not None else None,
        "drawn": drawn,
        "states": {k: hud_ui.hud_item_state(overlay, k) for k in ("time", "time_left", "speed", "limit", "dist", "handle", "grad")},
        "stats": gate.summary_fields(),
        "udp_port_is_not_54321": overlay.udp_port != 54321,
    }
    hud_ui.draw_text_with_stroke = original
    overlay.udp_socket.close()
    overlay.close()
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
