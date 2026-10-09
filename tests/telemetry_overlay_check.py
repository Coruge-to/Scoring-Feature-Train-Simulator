"""Phase L3: feeds the datagrams a C# sender produced (one per line of the file given as argument, UTF-8) to the REAL Overlay through the REAL UDP socket
(127.0.0.1:54321, offscreen Qt) and prints what the Overlay holds and draws afterwards, as JSON. Used by Test-TelemetryL3.ps1 to prove, byte for byte,
that real sender output updates the real HUD and that only what the sender announced is drawn.

    python -I tests\\telemetry_overlay_check.py <file> [strict]
"""
import json
import os
import socket
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(path, strict):
    from PyQt6.QtWidgets import QApplication
    app = QApplication(["l3"])
    import hud_ui
    import main
    import telemetry_gate
    main.write_desktop_log = lambda *a, **k: None               # the Overlay logs a door time to the Desktop; a check must not
    overlay = main.Overlay()
    overlay.timer.stop()
    if not overlay.udp_bind_ok:
        sys.stdout.write(json.dumps({"error": "udp-bind-failed"}))
        return 3
    if strict:
        overlay.telemetry_gate = telemetry_gate.TelemetryGate(strict=True)
        overlay.telemetry_gate.on_generation(1)
    drawn = []
    original = hud_ui.draw_text_with_stroke
    hud_ui.draw_text_with_stroke = lambda painter, text, *a, **k: drawn.append(text)
    with open(path, encoding="utf-8") as f:
        datagrams = [line for line in f.read().split("\n") if line]
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for text in datagrams:
        sender.sendto(text.encode("utf-8"), ("127.0.0.1", 54321))
        end = time.time() + 0.05
        while time.time() < end:
            app.processEvents()
            time.sleep(0.002)
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
             "current_scenario_id", "bve_rev_text", "bve_pow_text", "bve_brk_text", "bcPressure", "bpPressure", "bve_train_length")
    values = {n: getattr(overlay, n) for n in names}
    values["station_names"] = [s["name"] for s in overlay.station_list]
    values["station_timing"] = [s["is_timing"] for s in overlay.station_list]
    out = {"values": values, "ready": gate.ready, "tokens": sorted(gate.availability.tokens) if gate.availability.tokens is not None else None,
           "drawn": drawn, "states": {k: hud_ui.hud_item_state(overlay, k) for k in ("time", "time_left", "speed", "limit", "dist", "handle", "grad")},
           "stats": gate.summary_fields()}
    hud_ui.draw_text_with_stroke = original
    overlay.udp_socket.close()
    overlay.close()
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], len(sys.argv) > 2 and sys.argv[2] == "strict"))
