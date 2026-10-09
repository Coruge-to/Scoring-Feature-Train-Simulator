"""Phase L3 - the telemetry DATA CONTRACT between the senders (BVE6 Current, BVE5 AtsEX Legacy) and the application (no Qt, no scoring).

The wire format is the one that has always been used on UDP 127.0.0.1:54321: one datagram of comma separated `KEY:value` parts. Phase L3 adds exactly
ONE optional part and changes nothing else:

    AVAIL:<version>:<token>+<token>+...        e.g.  AVAIL:1:time+speed+loc+grad+station

AVAIL is the list of the data groups ("tokens") this line really carries. It is a positive list: a token that is not in it is NOT available from this
sender and the application must not show anything that depends on it (no placeholder, no default, no stale value). A sender that never sends AVAIL
(the Current sender of Phase C/D/E) keeps working exactly as before: no AVAIL means "everything is available".

Rules
  * the version is the first number after `AVAIL:`; this module understands version 1. A line with another version is not interpreted at all
    (`unsupported-version`); a line whose AVAIL part is malformed is not trusted (`avail-malformed`).
  * an unknown token is ignored (counted, never an error), so a newer sender can add tokens without breaking an older application.
  * a sender never sends the keys of a token it does not list. The core keys (REQUIRED_KEYS) are always present: a line without them is not telemetry.
  * AVAIL travels in every telemetry line, so an application that starts late, loses a datagram or follows a scenario reload learns the current
    availability from the very next line (a reload that changes the vehicle changes the list; nothing has to be announced separately).
  * the user's own HUD switches (Overlay.disp_settings) are a different thing from availability and are kept apart: see hud_ui.hud_item_state.
"""
import math
import re

PROTOCOL_VERSION = 1
AVAIL_PREFIX = "AVAIL:"
REQUIRED_KEYS = ("SCENARIO_ID", "TIME", "LOCATION", "SPEED")

MAX_TOKENS = 64
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# token -> the wire keys (or datagram kinds) that belong to it. The union with SCENARIO_ID is the whole vocabulary of the telemetry line.
TOKEN_KEYS = {
    "time": ("TIME",),
    "speed": ("SPEED",),
    "loc": ("LOCATION",),
    "grad": ("GRADIENT",),
    "station": ("NEXTLOC", "NEXTTIME", "ISPASS", "ISTIMING", "MARGINB", "MARGINF", "DOORDIR", "TERM", "STATNAME", "STALIST"),
    "door": ("DOOR",),
    "siglimit": ("SIGLIMIT",),
    "siglimit_ahead": ("FWDSIGLIMIT", "FWDSIGLOC"),
    "maplimit": ("MAPHEAD", "MAPTAIL"),
    "maplimit_ahead": ("MAPLIMITS", "CLEARDIST"),
    "handle": ("REV", "POW", "BRK", "HTYPE", "ALLTXT"),
    "brake_type": ("BTYPE",),
    "brake_cab": ("CAB",),
    "prates": ("PRATES",),
    "bcp": ("BCP",),
    "bpp": ("BPP",),
    "trainlen": ("TRAINLEN",),
    "doortime": ("DOORTIME",),
    "calcg": ("CALCG",),
    "meta": ("META",),
    "jump": ("JUMP", "JUMP_COMPLETE"),
}
KNOWN_TOKENS = frozenset(TOKEN_KEYS)

# HUD item (Overlay.disp_settings key) -> the tokens it needs. An item the application cannot draw without a token is hidden when the token is missing.
HUD_ITEM_REQUIRES = {
    "time": ("time",),
    "time_left": ("time", "station"),
    "speed": ("speed",),
    "limit": ("siglimit", "maplimit"),
    "dist": ("loc", "station"),
    "handle": ("handle",),
    "grad": ("grad",),
}

# state of the telemetry line that is part of the Overlay (attribute -> value at construction). An epoch change resets exactly these, so that a value
# of the previous scenario can never be read as a value of the new one (station_list / meta_* are replaced by their own datagrams and are not here).
def telemetry_state_defaults():
    return {
        "bve_speed": 0.0, "bve_location": 0.0, "bve_time_ms": 0, "bve_gradient": 0.0,
        "bve_next_loc": -1.0, "bve_next_time": -1, "bve_is_pass": 0, "bve_is_timing": 0,
        "bve_margin_b": 5.0, "bve_margin_f": 5.0, "bve_door": 0, "bve_doordir": 1, "bve_term": 0,
        "bve_rev_text": "切", "bve_rev_pos": 0, "bve_pow_text": "N", "bve_pow_notch": 0,
        "bve_brk_text": "N", "bve_brk_notch": 0, "bve_brk_max": 8, "is_single_handle": False,
        "all_brk_texts": [], "bve_current_station_name": "不明な駅",
        "max_rev_w": 40, "max_pow_w": 40, "max_brk_w": 40,
        "bve_signal_limit": 1000.0, "bve_train_length": 20.0, "bve_map_limits": [],
        "bve_fwd_sig_limit": 1000.0, "bve_fwd_sig_loc": -1.0,
        "map_head_limit": 1000.0, "map_tail_limit": 1000.0, "bve_clear_dist": 0.0, "bve_calc_g": 0.0,
        "bve_btype": "Ecb", "bcPressure": 0.0, "bpPressure": 0.0, "bve_bp_initial": 490.0,
        "bve_pressure_rates": [], "bve_max_pressure": 440.0,
        "cab_brk_count": 8, "has_holding_brake": False, "svc_brk_count": 8,
        "cushion_count": 2, "cushion_min": 1, "cushion_max": 2,
    }


AVAIL_ABSENT = "absent"
AVAIL_OK = "ok"
AVAIL_UNSUPPORTED = "unsupported-version"
AVAIL_MALFORMED = "avail-malformed"


DIAGNOSTIC_LIST_BUDGET = 60


def compact_groups(availability, budget=DIAGNOSTIC_LIST_BUDGET):
    """Fields that describe an availability in ONE diagnostic line (fixed words and numbers). The Caller keeps only 160 characters of an application
    line, so a list is written only when it fits: the groups that are missing, else the groups that are there, else only their number."""
    if availability.tokens is None:
        return {"groups": "all"}
    fields = {"groups": len(availability.tokens)}
    missing = "+".join(sorted(KNOWN_TOKENS - availability.tokens)) or "none"
    if len(missing) <= budget:
        fields["missing"] = missing
    else:
        have = "+".join(sorted(availability.tokens)) or "none"
        if len(have) <= budget:
            fields["have"] = have
    return fields


class Availability(object):
    """Which data groups the current telemetry carries. tokens=None means "no AVAIL was sent": everything is available (the Current behaviour)."""
    __slots__ = ("tokens",)

    def __init__(self, tokens=None):
        self.tokens = None if tokens is None else frozenset(tokens)

    @property
    def explicit(self):
        return self.tokens is not None

    def has(self, token):
        return self.tokens is None or token in self.tokens

    def item(self, name):
        """True when the HUD item can be drawn from real data. An item the contract does not govern is always True."""
        required = HUD_ITEM_REQUIRES.get(name)
        if required is None:
            return True
        return all(self.has(t) for t in required)

    def __eq__(self, other):
        return isinstance(other, Availability) and self.tokens == other.tokens

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.tokens)

    def __repr__(self):
        return "Availability(all)" if self.tokens is None else "Availability(%s)" % "+".join(sorted(self.tokens))


ALL_AVAILABLE = Availability(None)


class TelemetryLine(object):
    """The result of reading one telemetry datagram: valid or not (with a fixed-word reason), the scenario id, and the AVAIL part."""
    __slots__ = ("valid", "reason", "scenario_id", "avail_status", "tokens", "unknown_tokens", "bad_tokens")

    def __init__(self):
        self.valid = False
        self.reason = None
        self.scenario_id = None
        self.avail_status = AVAIL_ABSENT
        self.tokens = None            # frozenset of the KNOWN tokens of an ok AVAIL part
        self.unknown_tokens = 0
        self.bad_tokens = 0

    @property
    def availability(self):
        return Availability(self.tokens) if self.avail_status == AVAIL_OK else ALL_AVAILABLE


def format_avail(tokens):
    """The AVAIL part a sender writes (tokens sorted, so the line is deterministic)."""
    for t in tokens:
        if not _TOKEN_RE.match(t):
            raise ValueError("bad token")
    return "%s%d:%s" % (AVAIL_PREFIX, PROTOCOL_VERSION, "+".join(sorted(tokens)))


def _parse_avail(body, line):
    version_text, sep, token_text = body.partition(":")
    try:
        version = int(version_text)
    except ValueError:
        line.avail_status = AVAIL_MALFORMED
        return
    if not sep:
        line.avail_status = AVAIL_MALFORMED
        return
    if version != PROTOCOL_VERSION:
        line.avail_status = AVAIL_UNSUPPORTED
        return
    tokens = set()
    parts = token_text.split("+") if token_text else []
    if len(parts) > MAX_TOKENS:
        line.avail_status = AVAIL_MALFORMED
        return
    for t in parts:
        if not _TOKEN_RE.match(t):
            line.bad_tokens += 1
        elif t in KNOWN_TOKENS:
            tokens.add(t)
        else:
            line.unknown_tokens += 1
    line.tokens = frozenset(tokens)
    line.avail_status = AVAIL_OK


def parse_telemetry(text):
    """Reads the contract-relevant parts of one telemetry datagram. Never raises. valid=True needs every REQUIRED_KEYS part to be present and well
    formed (finite numbers) and an AVAIL part, if there is one, to be well formed and of a version this module understands."""
    line = TelemetryLine()
    found = {}
    try:
        for part in text.split(","):
            if part.startswith(AVAIL_PREFIX):
                if line.avail_status == AVAIL_ABSENT:
                    _parse_avail(part[len(AVAIL_PREFIX):], line)
                continue
            for key in REQUIRED_KEYS:
                if part.startswith(key + ":") and key not in found:
                    found[key] = part[len(key) + 1:]
                    break
        for key in REQUIRED_KEYS:
            if key not in found:
                line.reason = "missing-" + key.lower().replace("_", "-")
                return line
        line.scenario_id = int(found["SCENARIO_ID"])
        int(found["TIME"])
        for key in ("LOCATION", "SPEED"):
            if not math.isfinite(float(found[key])):
                raise ValueError(key)
    except (ValueError, TypeError, AttributeError):
        line.reason = "malformed-required"
        line.scenario_id = None
        return line
    if line.avail_status in (AVAIL_UNSUPPORTED, AVAIL_MALFORMED):
        line.reason = line.avail_status
        return line
    line.valid = True
    return line
