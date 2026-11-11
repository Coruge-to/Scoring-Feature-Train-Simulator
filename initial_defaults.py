"""INITIAL-DEFAULTS: the saved_defaults model (Commit 1). Pure Python, no Qt, no Overlay: schema, builtin values, normalisation, load, atomic save, the preset data and the A boundary validation.

saved_defaults is the persistent value set edited by the 'initial defaults' window (opened from the Input Device Properties). It is NOT the F1 state: a later stage regenerates the F1 scenario settings from it at every scenario load
(and the scoring start freezes a copy). Nothing here knows the Overlay; nothing here writes outside the one file.

File: %LOCALAPPDATA%\\Coruge-to\\TS Scoring\\initial-defaults.json (UTF-8 JSON, schemaVersion 1, per user). A missing file is not an error (builtin values; the file is created by a save only).
"""
import json
import os
from typing import NamedTuple, Optional, Tuple

SCHEMA_VERSION = 1
FILE_NAME = "initial-defaults.json"
COMPANY_FOLDER = "Coruge-to"
APP_FOLDER = "TS Scoring"
MAX_FILE_BYTES = 1024 * 1024

A_RANK_MIN_PERCENT = 50
A_RANK_MAX_PERCENT = 90
A_RANK_BUILTIN_PERCENT = 60

# one to one with Overlay.disp_settings (main.py): the JSON key <-> the F1 key
ENV_JSON_KEYS = ("current_time", "remaining_time", "current_speed", "speed_limit", "speed_limit_advance", "remaining_distance", "handle_reverser", "gradient")
ENV_F1_KEYS = ("time", "time_left", "speed", "limit", "limit_advance", "dist", "handle", "grad")
INITIAL_RELEASE_VALUES = ("off", "on1")            # "on2" is selectable in F1 only and is never a stored value
PRESET_NAMES = ("beginner", "intermediate", "advanced")


class Environment(NamedTuple):
    current_time: bool
    remaining_time: bool
    current_speed: bool
    speed_limit: bool
    speed_limit_advance: bool
    remaining_distance: bool
    handle_reverser: bool
    gradient: bool


class Penalties(NamedTuple):
    rolling: bool
    safety_intervention: bool            # always False in the beta (kept as a field so that the future scoring can enable it without a schema change)
    speed_limit_exceeded: bool
    stop_shock: bool
    emergency_brake: bool
    initial_release_brake: str           # "off" | "on1"


class InitialDefaults(NamedTuple):
    environment: Environment
    all_changeable_non_timed_to_timed: bool
    penalties: Penalties
    a_rank_percent: int


class LoadResult(NamedTuple):
    defaults: InitialDefaults
    source: str                          # "file" | "builtin"
    problems: Tuple[str, ...]


class SaveError(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------------------------------------ the state functions shared with F1
# The speed limit / advance dependency: (limit OFF, advance ON) does not exist. Operates on a plain dict with the F1 keys 'limit' and 'limit_advance'.
def normalize_speed_limit_settings(settings):
    if not settings.get("limit", True):
        settings["limit_advance"] = False


def set_speed_limit(settings, enabled):
    settings["limit"] = bool(enabled)
    normalize_speed_limit_settings(settings)


def set_speed_limit_advance(settings, enabled):
    settings["limit_advance"] = bool(enabled)
    if settings["limit_advance"]:
        settings["limit"] = True
    normalize_speed_limit_settings(settings)


# ------------------------------------------------------------------------------------------------------------------------------------------ the A boundary
def a_rank_percent_valid(value):
    """True for an integer 50..90 (a bool, a float, a str, None are not valid: no silent conversion)."""
    return type(value) is int and A_RANK_MIN_PERCENT <= value <= A_RANK_MAX_PERCENT


def a_rank_percent_to_ratio(percent):
    """The F1 type: a float ratio 0.50..0.90 rounded to 2 digits (Overlay.rank_a_ratio)."""
    if not a_rank_percent_valid(percent):
        raise ValueError("the A boundary must be an integer %d..%d" % (A_RANK_MIN_PERCENT, A_RANK_MAX_PERCENT))
    return round(percent / 100.0, 2)


def a_rank_text_allowed(text):
    """The editable text of the A boundary (the 'initial defaults' window and F1): ASCII digits 0-9 only, 2 digits at most (00..99 while editing; the empty text is allowed). No sign, no space, no decimal point, no full-width digit."""
    return type(text) is str and len(text) <= 2 and all(c in "0123456789" for c in text)


def normalize_a_rank_percent(text):
    """The ONE confirm rule of the A boundary text, shared by the 'initial defaults' window (OK) and F1 (Enter). Returns (percent, corrected):
    50..90 is kept (corrected False); 00..49, 91..99, a single digit, an empty text or any other text is A_RANK_BUILTIN_PERCENT (60, corrected True). F1 applies the 60 silently; the window uses `corrected` to show the input error
    (and does not save in that same OK)."""
    if type(text) is str and 1 <= len(text) <= 2 and all(c in "0123456789" for c in text):
        value = int(text)
        if a_rank_percent_valid(value):
            return value, False
    return A_RANK_BUILTIN_PERCENT, True


def clamp_a_rank_ratio(ratio):
    """The one clamp of the F1 value (the ratio 0.50..0.90, 2 digits)."""
    return max(A_RANK_MIN_PERCENT / 100.0, min(A_RANK_MAX_PERCENT / 100.0, round(float(ratio), 2)))


# ------------------------------------------------------------------------------------------------------------------------------------------ presets (pure data)
def _penalties(speed_limit_exceeded, stop_shock, initial_release_brake):
    return Penalties(rolling=True, safety_intervention=False, speed_limit_exceeded=speed_limit_exceeded, stop_shock=stop_shock, emergency_brake=True, initial_release_brake=initial_release_brake)


PRESETS = {
    "beginner": (_penalties(False, False, "off"), 50),
    "intermediate": (_penalties(True, True, "off"), 60),
    "advanced": (_penalties(True, True, "on1"), 70),
}


def apply_preset(defaults, name):
    """A new InitialDefaults with the six penalties and the A boundary of the preset. The environment and the timing-station setting are never changed."""
    if name not in PRESETS:
        raise ValueError("unknown preset %r" % (name,))
    penalties, percent = PRESETS[name]
    return defaults._replace(penalties=penalties, a_rank_percent=percent)


def builtin_defaults():
    penalties, percent = PRESETS["intermediate"]
    return InitialDefaults(environment=Environment(*([True] * 8)), all_changeable_non_timed_to_timed=False, penalties=penalties, a_rank_percent=percent)


# ------------------------------------------------------------------------------------------------------------------------------------------ path
def defaults_path(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, COMPANY_FOLDER, APP_FOLDER, FILE_NAME)


# ------------------------------------------------------------------------------------------------------------------------------------------ normalisation
def _bool_item(section, key, fallback, problems, label):
    if key not in section:
        return fallback
    value = section[key]
    if type(value) is bool:
        return value
    problems.append("%s: not a boolean" % label)
    return fallback


def normalize(raw):
    """(InitialDefaults, problems) from a decoded JSON object. A bad item falls back to the builtin value for that item only; the safety intervention is always False; (limit OFF, advance ON) is normalised."""
    base = builtin_defaults()
    problems = []
    env_raw = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    if "environment" in raw and not isinstance(raw.get("environment"), dict):
        problems.append("environment: not an object")
    values = [_bool_item(env_raw, k, base.environment[i], problems, "environment.%s" % k) for i, k in enumerate(ENV_JSON_KEYS)]
    settings = dict(zip(ENV_F1_KEYS, values))
    normalize_speed_limit_settings(settings)
    environment = Environment(*[settings[k] for k in ENV_F1_KEYS])
    timing_raw = raw.get("timing_stations") if isinstance(raw.get("timing_stations"), dict) else {}
    if "timing_stations" in raw and not isinstance(raw.get("timing_stations"), dict):
        problems.append("timing_stations: not an object")
    timing = _bool_item(timing_raw, "all_changeable_non_timed_to_timed", base.all_changeable_non_timed_to_timed, problems, "timing_stations.all_changeable_non_timed_to_timed")
    pen_raw = raw.get("penalties") if isinstance(raw.get("penalties"), dict) else {}
    if "penalties" in raw and not isinstance(raw.get("penalties"), dict):
        problems.append("penalties: not an object")
    b = base.penalties
    release = pen_raw.get("initial_release_brake", b.initial_release_brake)
    if "initial_release_brake" in pen_raw and (type(release) is not str or release not in INITIAL_RELEASE_VALUES):
        problems.append("penalties.initial_release_brake: not one of %s" % (INITIAL_RELEASE_VALUES,))
        release = b.initial_release_brake
    penalties = Penalties(
        rolling=_bool_item(pen_raw, "rolling", b.rolling, problems, "penalties.rolling"),
        safety_intervention=False,
        speed_limit_exceeded=_bool_item(pen_raw, "speed_limit_exceeded", b.speed_limit_exceeded, problems, "penalties.speed_limit_exceeded"),
        stop_shock=_bool_item(pen_raw, "stop_shock", b.stop_shock, problems, "penalties.stop_shock"),
        emergency_brake=_bool_item(pen_raw, "emergency_brake", b.emergency_brake, problems, "penalties.emergency_brake"),
        initial_release_brake=release)
    percent = raw.get("a_rank_percent", base.a_rank_percent)
    if "a_rank_percent" in raw and not a_rank_percent_valid(percent):
        problems.append("a_rank_percent: not an integer %d..%d" % (A_RANK_MIN_PERCENT, A_RANK_MAX_PERCENT))
        percent = base.a_rank_percent
    return InitialDefaults(environment, timing, penalties, percent), tuple(problems)


# ------------------------------------------------------------------------------------------------------------------------------------------ load
def load(path=None):
    """LoadResult. Never raises, never writes. Missing file -> builtin (source 'builtin', no problem); a damaged file -> builtin + the reason."""
    path = path or defaults_path()
    builtin = LoadResult(builtin_defaults(), "builtin", ())
    try:
        if not os.path.exists(path):
            return builtin
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return LoadResult(builtin_defaults(), "builtin", ("file too large",))
        with open(path, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return LoadResult(builtin_defaults(), "builtin", ("unreadable: %s" % type(exc).__name__,))
    try:
        text = data.decode("utf-8-sig")
        raw = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return LoadResult(builtin_defaults(), "builtin", ("not a UTF-8 JSON document",))
    if not isinstance(raw, dict):
        return LoadResult(builtin_defaults(), "builtin", ("not a JSON object",))
    version = raw.get("schemaVersion")
    if type(version) is not int or version != SCHEMA_VERSION:
        return LoadResult(builtin_defaults(), "builtin", ("unknown schemaVersion",))
    defaults, problems = normalize(raw)
    return LoadResult(defaults, "file", problems)


# ------------------------------------------------------------------------------------------------------------------------------------------ save
def to_json_dict(defaults):
    env = defaults.environment
    p = defaults.penalties
    return {
        "schemaVersion": SCHEMA_VERSION,
        "environment": {k: env[i] for i, k in enumerate(ENV_JSON_KEYS)},
        "timing_stations": {"all_changeable_non_timed_to_timed": defaults.all_changeable_non_timed_to_timed},
        "penalties": {"rolling": p.rolling, "safety_intervention": False, "speed_limit_exceeded": p.speed_limit_exceeded, "stop_shock": p.stop_shock,
                      "emergency_brake": p.emergency_brake, "initial_release_brake": p.initial_release_brake},
        "a_rank_percent": defaults.a_rank_percent,
    }


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def validate_for_save(defaults):
    """Raises ValueError for a value that must not be stored (the A boundary out of range is refused, never clamped; on2 is not a stored value; the types are strict)."""
    if not a_rank_percent_valid(defaults.a_rank_percent):
        raise ValueError("the A boundary must be an integer %d..%d" % (A_RANK_MIN_PERCENT, A_RANK_MAX_PERCENT))
    if type(defaults.penalties.initial_release_brake) is not str or defaults.penalties.initial_release_brake not in INITIAL_RELEASE_VALUES:
        raise ValueError("the initial / release brake must be one of %s" % (INITIAL_RELEASE_VALUES,))
    for value in tuple(defaults.environment) + (defaults.all_changeable_non_timed_to_timed, defaults.penalties.rolling, defaults.penalties.speed_limit_exceeded, defaults.penalties.stop_shock, defaults.penalties.emergency_brake):
        if type(value) is not bool:
            raise ValueError("a boolean item holds %r" % (value,))
    settings = dict(zip(ENV_F1_KEYS, defaults.environment))
    if not settings["limit"] and settings["limit_advance"]:
        raise ValueError("the speed limit advance cannot be ON while the speed limit is OFF")


def save(defaults, path=None, replace=os.replace, fsync=os.fsync):
    """Atomic save: validate -> a temp file in the SAME directory -> flush / fsync -> re-read and verify -> replace. Any failure leaves the old file untouched, removes the temp file and raises
    (ValueError before anything is written; SaveError after). The safety intervention is always stored as False."""
    validate_for_save(defaults)
    path = os.path.abspath(path or defaults_path())
    directory = os.path.dirname(path)
    document = json_dumps(to_json_dict(defaults))
    tmp = os.path.join(directory, "%s.%d.tmp" % (FILE_NAME, os.getpid()))
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(document.encode("utf-8"))
            f.flush()
            fsync(f.fileno())
        with open(tmp, "rb") as f:
            written = f.read()
        verify = load(tmp)
        if written != document.encode("utf-8") or verify.source != "file" or verify.problems or verify.defaults != defaults._replace(penalties=defaults.penalties._replace(safety_intervention=False)):
            raise SaveError("the written file does not read back equal")
        replace(tmp, path)
    except SaveError:
        _remove(tmp)
        raise
    except OSError as exc:
        _remove(tmp)
        raise SaveError("could not save: %s" % type(exc).__name__)
    except Exception:
        _remove(tmp)
        raise
    return path


def _remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
