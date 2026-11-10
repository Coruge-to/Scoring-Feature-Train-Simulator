"""INITIAL-DEFAULTS Commit 1 (Owner contract 2026-11-10): the saved_defaults model. RED = fails on the baseline 73e00b5 (the module does not exist); every message starts with 'ID-RED'.

Contract
  * file: %LOCALAPPDATA%\\Coruge-to\\TS Scoring\\initial-defaults.json (UTF-8 JSON, schemaVersion 1, per user, shared by BVE5 / BVE6 and Current / Legacy). No registry, no INI, never launcher.json.
  * builtin defaults (no file): environment 8 x ON, all_changeable_non_timed_to_timed OFF, penalties = the INTERMEDIATE preset (rolling ON, safety_intervention OFF fixed, speed_limit_exceeded ON, stop_shock ON, emergency_brake ON,
    initial_release_brake "off"), a_rank_percent 60. The file is never created by a load.
  * safety_intervention is always false (a stored true is read as false); initial_release_brake is "off" or "on1" only ("on2" is not a stored value); a_rank_percent is an integer 50..90 (save: out of range is REFUSED, never clamped; load: the
    item falls back to 60); (speed limit OFF, advance ON) cannot exist (one state function shared with F1).
  * presets (pure data): beginner / intermediate / advanced change the six penalties and the A boundary ONLY (never the environment or the timing-station setting).
  * save is atomic: validate -> temp file in the same directory -> flush / fsync -> re-read and verify -> os.replace -> no temp file left; any failure leaves the old file untouched and raises.
  * a damaged file (not JSON, wrong type, unknown schemaVersion, too large, not UTF-8) -> builtin defaults + a reason; a bad item falls back for that item only. A load never writes."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "USERPROFILE", "HOME")}
    for k in _TMP["saved"]:
        os.environ[k] = _TMP["dir"].name


def tearDownModule():
    try:
        pass
    finally:
        for k, v in _TMP["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP["dir"].cleanup()


def model():
    try:
        import initial_defaults
    except ImportError as exc:
        raise AssertionError("ID-RED: the module initial_defaults does not exist (%s)" % exc)
    return initial_defaults


ENV_JSON = ("current_time", "remaining_time", "current_speed", "speed_limit", "speed_limit_advance", "remaining_distance", "handle_reverser", "gradient")
ENV_F1 = ("time", "time_left", "speed", "limit", "limit_advance", "dist", "handle", "grad")
PEN_JSON = ("rolling", "safety_intervention", "speed_limit_exceeded", "stop_shock", "emergency_brake", "initial_release_brake")


class Base(unittest.TestCase):
    def setUp(self):
        self.m = model()
        self.dir = tempfile.mkdtemp(prefix="idm-", dir=_TMP["dir"].name)
        self.path = os.path.join(self.dir, "TS Scoring", "initial-defaults.json")
        os.makedirs(os.path.dirname(self.path))

    def write_raw(self, data):
        with open(self.path, "wb") as f:
            f.write(data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def good(self):
        return {"schemaVersion": 1,
                "environment": dict(zip(ENV_JSON, [True] * 8)),
                "timing_stations": {"all_changeable_non_timed_to_timed": False},
                "penalties": {"rolling": True, "safety_intervention": False, "speed_limit_exceeded": True, "stop_shock": True, "emergency_brake": True, "initial_release_brake": "off"},
                "a_rank_percent": 60}


class Paths(Base):
    def test_the_file_lives_in_the_user_settings_directory_next_to_launcher_json(self):
        os.environ["LOCALAPPDATA"] = r"C:\Users\someone\AppData\Local"
        try:
            p = self.m.defaults_path()
        finally:
            os.environ["LOCALAPPDATA"] = _TMP["dir"].name
        self.assertEqual(p, os.path.join(r"C:\Users\someone\AppData\Local", "Coruge-to", "TS Scoring", "initial-defaults.json"), "ID-RED: the path is not %LOCALAPPDATA%\\Coruge-to\\TS Scoring\\initial-defaults.json")

    def test_no_dll_name_registry_or_ini_is_used(self):
        src = open(os.path.join(ROOT, "initial_defaults.py"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "initial_defaults.py")) else None
        self.assertIsNotNone(src, "ID-RED: the module does not exist")
        import re
        for bad in (r"winreg", r"configparser", r"\.ini\b", r"TsScoringPlugin", r"\.dll\b", r"launcher\.json"):
            self.assertIsNone(re.search(bad, src, re.I), "ID-RED: the model must not mention %r (no registry / INI / DLL name / launcher.json)" % bad)


class Builtin(Base):
    def test_builtin_defaults_are_the_owner_values(self):
        d = self.m.builtin_defaults()
        self.assertEqual(tuple(d.environment), (True,) * 8, "ID-RED: the environment is not 8 x ON")
        self.assertIs(d.all_changeable_non_timed_to_timed, False)
        p = d.penalties
        self.assertEqual((p.rolling, p.safety_intervention, p.speed_limit_exceeded, p.stop_shock, p.emergency_brake, p.initial_release_brake), (True, False, True, True, True, "off"))
        self.assertEqual(d.a_rank_percent, 60)

    def test_builtin_penalties_and_a_boundary_equal_the_intermediate_preset(self):
        d = self.m.builtin_defaults()
        i = self.m.apply_preset(d, "intermediate")
        self.assertEqual((i.penalties, i.a_rank_percent), (d.penalties, d.a_rank_percent), "ID-RED: the builtin penalties / A boundary differ from the intermediate preset")
        self.assertEqual(i, d)

    def test_a_missing_file_gives_builtin_and_creates_nothing(self):
        r = self.m.load(self.path)
        self.assertEqual(r.defaults, self.m.builtin_defaults())
        self.assertFalse(os.path.exists(self.path), "ID-RED: a load created the file")
        self.assertEqual(os.listdir(os.path.dirname(self.path)), [])


class Presets(Base):
    EXPECT = {
        "beginner": dict(rolling=True, speed_limit_exceeded=False, stop_shock=False, emergency_brake=True, initial_release_brake="off", a=50),
        "intermediate": dict(rolling=True, speed_limit_exceeded=True, stop_shock=True, emergency_brake=True, initial_release_brake="off", a=60),
        "advanced": dict(rolling=True, speed_limit_exceeded=True, stop_shock=True, emergency_brake=True, initial_release_brake="on1", a=70),
    }

    def test_each_preset_has_the_owner_content(self):
        base = self.m.builtin_defaults()
        for name, e in self.EXPECT.items():
            d = self.m.apply_preset(base, name)
            p = d.penalties
            self.assertEqual((p.rolling, p.safety_intervention, p.speed_limit_exceeded, p.stop_shock, p.emergency_brake, p.initial_release_brake, d.a_rank_percent),
                             (e["rolling"], False, e["speed_limit_exceeded"], e["stop_shock"], e["emergency_brake"], e["initial_release_brake"], e["a"]), "ID-RED: preset %s" % name)

    def test_a_preset_never_changes_the_environment_or_the_timing_setting(self):
        env = self.m.builtin_defaults().environment
        odd = self.m.builtin_defaults()._replace(environment=type(env)(*([False, True] * 4)), all_changeable_non_timed_to_timed=True)
        for name in self.EXPECT:
            d = self.m.apply_preset(odd, name)
            self.assertEqual(d.environment, odd.environment, "ID-RED: preset %s changed the environment" % name)
            self.assertIs(d.all_changeable_non_timed_to_timed, True, "ID-RED: preset %s changed the timing-station setting" % name)

    def test_presets_never_turn_the_safety_intervention_on(self):
        for name in self.EXPECT:
            self.assertIs(self.m.apply_preset(self.m.builtin_defaults(), name).penalties.safety_intervention, False)

    def test_an_unknown_preset_is_refused(self):
        with self.assertRaises(ValueError):
            self.m.apply_preset(self.m.builtin_defaults(), "expert")


class Normalise(Base):
    def test_a_good_file_round_trips(self):
        raw = self.good()
        raw["environment"]["handle_reverser"] = False
        raw["timing_stations"]["all_changeable_non_timed_to_timed"] = True
        raw["penalties"]["initial_release_brake"] = "on1"
        raw["a_rank_percent"] = 80
        self.write_raw(raw)
        r = self.m.load(self.path)
        self.assertEqual(r.source, "file")
        d = r.defaults
        self.assertEqual((d.environment[6], d.all_changeable_non_timed_to_timed, d.penalties.initial_release_brake, d.a_rank_percent), (False, True, "on1", 80))
        self.assertEqual(r.problems, ())

    def test_a_stored_safety_intervention_true_is_read_as_false(self):
        raw = self.good()
        raw["penalties"]["safety_intervention"] = True
        self.write_raw(raw)
        self.assertIs(self.m.load(self.path).defaults.penalties.safety_intervention, False, "ID-RED: a stored true was kept")

    def test_on2_is_not_a_stored_value(self):
        for bad in ("on2", "ON2", "ON②", "on1 ", 1, None, True):
            raw = self.good()
            raw["penalties"]["initial_release_brake"] = bad
            self.write_raw(raw)
            self.assertEqual(self.m.load(self.path).defaults.penalties.initial_release_brake, "off", "ID-RED: %r was accepted" % (bad,))

    def test_the_a_boundary_is_an_integer_50_to_90_else_the_builtin_60(self):
        for ok in (50, 60, 90):
            raw = self.good()
            raw["a_rank_percent"] = ok
            self.write_raw(raw)
            self.assertEqual(self.m.load(self.path).defaults.a_rank_percent, ok)
        for bad in (49, 91, 0, 100, -1, 60.5, "70", None, True, False, 1e9):
            raw = self.good()
            raw["a_rank_percent"] = bad
            self.write_raw(raw)
            r = self.m.load(self.path)
            self.assertEqual(r.defaults.a_rank_percent, 60, "ID-RED: %r was accepted" % (bad,))
            self.assertTrue(r.problems, "ID-RED: no reason for %r" % (bad,))

    def test_the_forbidden_speed_limit_state_cannot_exist(self):
        raw = self.good()
        raw["environment"]["speed_limit"] = False
        raw["environment"]["speed_limit_advance"] = True
        self.write_raw(raw)
        d = self.m.load(self.path).defaults
        self.assertEqual((d.environment[3], d.environment[4]), (False, False), "ID-RED: (limit OFF, advance ON) was kept")

    def test_a_bad_item_falls_back_for_that_item_only(self):
        raw = self.good()
        raw["environment"]["current_speed"] = "yes"
        raw["environment"]["gradient"] = False
        raw["penalties"]["stop_shock"] = 0
        raw["penalties"]["rolling"] = False
        raw["timing_stations"]["all_changeable_non_timed_to_timed"] = "true"
        self.write_raw(raw)
        r = self.m.load(self.path)
        d = r.defaults
        self.assertEqual((d.environment[2], d.environment[7], d.penalties.stop_shock, d.penalties.rolling, d.all_changeable_non_timed_to_timed), (True, False, True, False, False))
        self.assertEqual(len(r.problems), 3)

    def test_unknown_keys_are_ignored_and_a_missing_section_uses_the_builtin(self):
        raw = {"schemaVersion": 1, "future": {"x": 1}}
        self.write_raw(raw)
        r = self.m.load(self.path)
        self.assertEqual(r.defaults, self.m.builtin_defaults())

    def test_the_japanese_old_label_is_never_a_key(self):
        text = json.dumps(self.m.to_json_dict(self.m.builtin_defaults()), ensure_ascii=False)
        self.assertNotIn("ATS信号無視", text)
        self.assertIn("safety_intervention", text)

    def test_the_environment_mapping_to_the_f1_keys(self):
        self.assertEqual(tuple(self.m.ENV_JSON_KEYS), ENV_JSON)
        self.assertEqual(tuple(self.m.ENV_F1_KEYS), ENV_F1, "ID-RED: the F1 disp_settings keys do not map one to one")

    def test_the_speed_limit_state_function_is_the_f1_one(self):
        main = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        self.assertIn("def normalize_speed_limit_settings(self):", main)
        for limit in (True, False):
            for adv in (True, False):
                s = {"limit": limit, "limit_advance": adv}
                self.m.normalize_speed_limit_settings(s)
                self.assertEqual(s, {"limit": limit, "limit_advance": adv and limit})
        for start in itertools.product((True, False), repeat=2):
            for enabled in (True, False):
                a = dict(zip(("limit", "limit_advance"), start))
                b = dict(a)
                self.m.set_speed_limit(a, enabled)
                if True:
                    b["limit"] = enabled
                    if not b["limit"]:
                        b["limit_advance"] = False
                self.assertEqual(a, b)
                c = dict(zip(("limit", "limit_advance"), start))
                self.m.set_speed_limit_advance(c, enabled)
                d = dict(zip(("limit", "limit_advance"), start))
                d["limit_advance"] = enabled
                if d["limit_advance"]:
                    d["limit"] = True
                self.assertEqual(c, d)


import itertools  # noqa: E402


class Damaged(Base):
    def test_damaged_files_give_the_builtin_with_a_reason_and_are_not_rewritten(self):
        cases = {
            "empty": b"",
            "not json": b"{not json",
            "array": b"[1, 2]",
            "string": b'"x"',
            "bad utf8": b"\xff\xfe\x00\x00{",
            "no version": b'{"environment": {}}',
            "unknown version": b'{"schemaVersion": 2}',
            "version text": b'{"schemaVersion": "1"}',
            "version bool": b'{"schemaVersion": true}',
            "huge": b'{"schemaVersion": 1, "pad": "' + b"x" * (2 * 1024 * 1024) + b'"}',
        }
        for name, data in cases.items():
            self.write_raw(data)
            r = self.m.load(self.path)
            self.assertEqual(r.defaults, self.m.builtin_defaults(), "ID-RED: %s" % name)
            self.assertTrue(r.problems, "ID-RED: no reason for %s" % name)
            if name == "huge":
                self.assertEqual(r.problems, ("file too large",), "ID-RED: the size limit is not applied before the parse")
            with open(self.path, "rb") as f:
                self.assertEqual(f.read(), data, "ID-RED: the load rewrote the damaged file (%s)" % name)

    def test_a_bom_is_tolerated(self):
        self.write_raw(b"\xef\xbb\xbf" + json.dumps(self.good()).encode("utf-8"))
        self.assertEqual(self.m.load(self.path).source, "file")

    def test_an_unreadable_path_gives_the_builtin(self):
        r = self.m.load(os.path.join(self.dir, "TS Scoring"))        # a directory, not a file
        self.assertEqual(r.defaults, self.m.builtin_defaults())
        self.assertTrue(r.problems)


class Save(Base):
    def make(self, **kw):
        d = self.m.builtin_defaults()
        if "a" in kw:
            d = d._replace(a_rank_percent=kw["a"])
        return d

    def test_save_writes_the_schema_and_loads_back_equal(self):
        d = self.m.apply_preset(self.make(), "advanced")
        d = d._replace(all_changeable_non_timed_to_timed=True)
        self.m.save(d, self.path)
        raw = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual(raw["schemaVersion"], 1)
        self.assertEqual(raw["a_rank_percent"], 70)
        self.assertEqual(raw["penalties"]["initial_release_brake"], "on1")
        self.assertEqual(raw["penalties"]["safety_intervention"], False)
        self.assertTrue(raw["timing_stations"]["all_changeable_non_timed_to_timed"])
        self.assertEqual(self.m.load(self.path).defaults, d)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"], "ID-RED: a temp file was left")

    def test_save_creates_the_directory_and_writes_utf8_lf(self):
        path = os.path.join(self.dir, "new", "dir", "initial-defaults.json")
        self.m.save(self.make(), path)
        data = open(path, "rb").read()
        self.assertNotIn(b"\r\n", data)
        data.decode("utf-8")

    def test_save_refuses_an_a_boundary_out_of_range_and_never_clamps(self):
        self.m.save(self.make(a=65), self.path)
        before = open(self.path, "rb").read()
        for bad in (49, 91, 0, 100, 60.5, "70", None, True):
            with self.assertRaises(ValueError):
                self.m.save(self.make()._replace(a_rank_percent=bad), self.path)
            self.assertEqual(open(self.path, "rb").read(), before, "ID-RED: a refused save changed the file (%r)" % (bad,))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"])

    def test_save_refuses_on2_and_never_stores_the_safety_intervention_on(self):
        d = self.make()
        with self.assertRaises(ValueError):
            self.m.save(d._replace(penalties=d.penalties._replace(initial_release_brake="on2")), self.path)
        self.m.save(d._replace(penalties=d.penalties._replace(safety_intervention=True)), self.path)
        self.assertIs(json.load(open(self.path, encoding="utf-8"))["penalties"]["safety_intervention"], False, "ID-RED: the safety intervention was stored ON")

    def test_a_failed_replace_keeps_the_old_file_and_leaves_no_temp_file(self):
        self.m.save(self.make(a=55), self.path)
        before = open(self.path, "rb").read()

        def boom(src, dst):
            raise OSError("replace failed")
        with self.assertRaises(self.m.SaveError):
            self.m.save(self.make(a=77), self.path, replace=boom)
        self.assertEqual(open(self.path, "rb").read(), before, "ID-RED: the old file changed")
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"], "ID-RED: a temp file was left")

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(self):
        self.m.save(self.make(a=55), self.path)
        before = open(self.path, "rb").read()

        def boom(fd):
            raise OSError("disk full")
        with self.assertRaises(self.m.SaveError):
            self.m.save(self.make(a=77), self.path, fsync=boom)
        self.assertEqual(open(self.path, "rb").read(), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"])

    def test_a_save_that_reads_back_wrong_is_not_installed(self):
        self.m.save(self.make(a=55), self.path)
        before = open(self.path, "rb").read()
        real = self.m.json_dumps

        def corrupt(obj):
            return real(obj)[:-3]                                       # a truncated document
        self.m.json_dumps, saved = corrupt, self.m.json_dumps
        try:
            with self.assertRaises(self.m.SaveError):
                self.m.save(self.make(a=77), self.path)
        finally:
            self.m.json_dumps = saved
        self.assertEqual(open(self.path, "rb").read(), before, "ID-RED: an unverified file was installed")
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"])

    def test_replace_is_the_only_way_the_formal_file_changes(self):
        calls = []
        real = os.replace

        def spy(src, dst):
            calls.append((os.path.dirname(os.path.abspath(src)), os.path.abspath(dst)))
            return real(src, dst)
        self.m.save(self.make(), self.path, replace=spy)
        self.assertEqual(len(calls), 1, "ID-RED: the save did not use one atomic replace")
        self.assertEqual(calls[0][0], os.path.dirname(os.path.abspath(self.path)), "ID-RED: the temp file is not in the same directory")
        self.assertEqual(calls[0][1], os.path.abspath(self.path))

    def test_save_refuses_a_non_boolean_item(self):
        d = self.make()
        env = list(d.environment)
        env[2] = "yes"
        with self.assertRaises(ValueError):
            self.m.save(d._replace(environment=type(d.environment)(*env)), self.path)
        with self.assertRaises(ValueError):
            self.m.save(d._replace(penalties=d.penalties._replace(stop_shock=1)), self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_the_a_boundary_conversion_is_strict_and_the_f1_clamp_is_one_function(self):
        self.assertEqual((self.m.a_rank_percent_to_ratio(50), self.m.a_rank_percent_to_ratio(60), self.m.a_rank_percent_to_ratio(90)), (0.5, 0.6, 0.9))
        for bad in (49, 91, 60.0, "60", None, True):
            with self.assertRaises(ValueError):
                self.m.a_rank_percent_to_ratio(bad)
        self.assertEqual((self.m.clamp_a_rank_ratio(0.49), self.m.clamp_a_rank_ratio(0.91), self.m.clamp_a_rank_ratio(0.655), self.m.clamp_a_rank_ratio(0.7)), (0.5, 0.9, 0.66, 0.7))

    def test_the_model_values_are_immutable(self):
        d = self.m.builtin_defaults()
        with self.assertRaises(AttributeError):
            d.a_rank_percent = 70
        with self.assertRaises(AttributeError):
            d.penalties.rolling = False
        self.assertIsInstance(d.environment, tuple)


if __name__ == "__main__":
    unittest.main()
