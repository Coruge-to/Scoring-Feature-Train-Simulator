"""Phase SI-1 test helper: feeds telemetry lines to the REAL Overlay (offscreen, UDP stubbed, the production receive path read_udp_data ->
telemetry_gate -> apply_telemetry_text) and to the REAL managed_hud.hud_update_step -> scoring_logic.update_physics_and_scoring, and reports the speed limit flash state
after every line. Nothing in the production code is replaced except QUdpSocket (so UDP 54321 is never bound and a running TS Scoring is never touched) and the desktop log.

    python tests\\si1_flash_probe.py <input.json> <output.json>

input  = {"name": ["telemetry line", ...], ...}   (each name gets its own Overlay; a pseudo line "@strict" switches the gate to the strict, generation aware gate of the\n         managed mode, "@gen=N" is the Caller announcing ScenarioGeneration N - both are not telemetry and produce no output step)
output = {"name": [{"red": "None" | "<km/h>", "blue": ..., "blink": bool, "color": "red"|"blue"|"white"|"other", "disp": float, "eff": float,
                    "ahead": int, "head": float, "tail": float, "clear": float, "train": float, "wait": bool}, ...], ...}
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(sequences):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, ROOT)
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["si1"])
    import main
    import managed_hud
    import config
    import telemetry_gate

    class Signal(object):
        def connect(self, slot):
            self.slot = slot

    class StubUdp(object):
        """Stands in for QUdpSocket: a queue of datagrams; binds nothing."""
        def __init__(self, parent=None):
            self.readyRead = Signal()
            self.queue = []

        def bind(self, address, port):
            return True

        def hasPendingDatagrams(self):
            return bool(self.queue)

        def pendingDatagramSize(self):
            return len(self.queue[0])

        def readDatagram(self, size):
            return self.queue.pop(0), None, 0

        def writeDatagram(self, data, address, port):
            return 0

        def close(self):
            return None

    saved = (main.QUdpSocket, main.write_desktop_log)
    main.QUdpSocket = StubUdp
    main.write_desktop_log = lambda *a, **k: None
    out = {}
    try:
        for name, lines in sequences.items():
            o = main.Overlay()
            o.timer.stop()
            steps = []
            for line in lines:
                if line == "@strict":
                    o.telemetry_gate = telemetry_gate.TelemetryGate(strict=True)
                    continue
                if line.startswith("@gen="):
                    held = o.telemetry_gate.on_generation(int(line[5:]))
                    if held:
                        o.apply_telemetry_text(held)
                    continue
                o.udp_socket.queue.append(line.encode("utf-8"))
                o.read_udp_data()
                managed_hud.hud_update_step(o)
                if o.limit_color == config.COLOR_B_EMG:
                    color = "red"
                elif o.limit_color == config.COLOR_P:
                    color = "blue"
                elif o.limit_color == config.COLOR_WHITE:
                    color = "white"
                else:
                    color = "other"
                steps.append({
                    "red": o.dbg_red, "blue": o.dbg_blue, "blink": bool(o.blink_active), "color": color, "disp": float(o.disp_limit),
                    "eff": float(o.effective_limit), "ahead": len(o.bve_map_limits), "head": float(o.map_head_limit), "tail": float(o.map_tail_limit),
                    "clear": float(o.bve_clear_dist), "train": float(o.bve_train_length), "wait": bool(o.dbg_is_wait),
                    "limits": [[float(a), float(b)] for a, b in o.bve_map_limits],
                })
            out[name] = steps
            try:
                o.udp_socket.close()
                o.close()
                o.deleteLater()
            except Exception:
                pass
    finally:
        main.QUdpSocket, main.write_desktop_log = saved
    return out


def main_cli(argv):
    with open(argv[1], encoding="utf-8-sig") as f:
        sequences = json.load(f)
    result = run(sequences)
    with open(argv[2], "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv))
