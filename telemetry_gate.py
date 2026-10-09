"""Phase L3 - which telemetry the application may use, and what it carries (pure: no Qt, no windows, no clock).

Two roles, one object:

  * AVAILABILITY (always, normal and managed mode): the AVAIL part of the accepted telemetry decides which HUD items can be drawn from real data
    (telemetry_contract). A sender that sends no AVAIL leaves everything available, exactly as before Phase L3.

  * SCENARIO GENERATION (strict, managed mode only): the HUD may only show telemetry that belongs to the CURRENT ScenarioGeneration of the Caller.
    The telemetry names its own scenario (SCENARIO_ID: one value per scenario instance, a new one for every scenario / reload), the Caller names the
    generation (state block). They are joined here, without any clock or timeout:

        stale    a SCENARIO_ID that is older than the newest one seen, or that belongs to an earlier generation (retired)   -> dropped
        bound    the SCENARIO_ID that is the data of the current generation (the first current one after a generation change)  -> accepted
        ahead    a newer SCENARIO_ID than the bound one while the generation has not changed yet: the sender has moved on to the next scenario
                 before the Caller said so. The old data is no longer current, so the HUD waits; the newest packet is HELD and bound as soon as
                 the generation change arrives (a paused simulation then still gets its HUD)
        invalid  a line without the core keys / with a malformed AVAIL / of an unknown AVAIL version                              -> dropped

    ready = a generation is bound, at least one valid line of it was accepted, and the sender has not moved ahead. Until then the HUD stays hidden.
    There is no "telemetry too old" threshold: while the simulation is paused no line arrives and the last data of the generation stays valid.

Diagnostics go to `log(event, **fields)` and only on a CHANGE of state (first telemetry, availability change, the start of a drop episode); repeated
packets are only counted.
"""
from collections import OrderedDict

import telemetry_contract as contract

MAX_REMEMBERED_EPOCHS = 64


class TelemetryGate(object):
    def __init__(self, strict=False, log=None):
        self.strict = bool(strict)
        self.log = log
        self.availability = contract.ALL_AVAILABLE
        self.generation = 0
        # strict-mode state
        self._seen = OrderedDict()      # SCENARIO_IDs seen, oldest first (bounded)
        self._retired = OrderedDict()   # SCENARIO_IDs that belonged to an earlier generation (bounded)
        self._newest = None
        self._bound = None
        self._accepted = 0              # valid lines accepted for the bound epoch
        self._ahead = None              # the newer SCENARIO_ID the sender has moved on to (None = not ahead)
        self._held = None               # (scenario_id, text, availability) of the newest ahead line
        self._applied_epoch = None      # the SCENARIO_ID the application state was last built from
        self._epoch_reset = False
        self._dropped_logged = set()    # the drop reasons already logged for the current generation
        # counters
        self.accepted = 0
        self.stale = 0
        self.invalid = 0
        self.ahead_lines = 0
        self.unknown_tokens = 0         # in the latest line followed (a newer sender may add tokens: they are ignored, never an error)
        self.avail_changes = 0
        self.epochs_bound = 0

    # -- diagnostics --------------------------------------------------------------------------------------------------------------------
    def _emit(self, event, **fields):
        if self.log is None:
            return
        try:
            self.log(event, **fields)
        except Exception:
            pass

    def _drop_episode(self, reason, **fields):
        """A drop reason is logged once per generation (the counters keep counting): a burst - or an alternation - of stale datagrams is one line."""
        if reason not in self._dropped_logged:
            self._dropped_logged.add(reason)
            self._emit("telemetry-drop", reason=reason, gen=self.generation, **fields)

    # -- state --------------------------------------------------------------------------------------------------------------------------
    @property
    def ready(self):
        """May the HUD show the telemetry? Always True in normal mode (nothing to wait for)."""
        if not self.strict:
            return True
        return self._bound is not None and self._accepted > 0 and self._ahead is None

    @property
    def wait_reason(self):
        """Why the HUD waits (a fixed word), or None when ready."""
        if self.ready:
            return None
        if self._ahead is not None:
            return "sender-ahead"
        if self._bound is None:
            return "no-telemetry-for-generation"
        return "no-telemetry"

    @property
    def bound_epoch(self):
        return self._bound

    @property
    def has_held(self):
        return self._held is not None

    def consume_epoch_reset(self):
        """True once after the application state must be reset to its defaults before the next telemetry is applied (a new scenario instance)."""
        flag = self._epoch_reset
        self._epoch_reset = False
        return flag

    # -- the generation (from the Caller's state block) ------------------------------------------------------------------------------------
    def on_generation(self, generation):
        """The Caller's ScenarioGeneration changed. The data of the previous generation is retired. Returns the HELD telemetry text of the newer
        scenario when the sender had already moved on (the caller applies it; it is bound to the new generation), else None."""
        if generation == self.generation:
            return None
        previous = self.generation
        self.generation = generation
        if not self.strict:
            return None
        if self._bound is not None:
            self._remember(self._retired, self._bound)
        self._bound = None
        self._accepted = 0
        self._ahead = None
        self.availability = contract.ALL_AVAILABLE
        self._dropped_logged = set()
        held, self._held = self._held, None
        self._emit("telemetry-generation", gen=generation, prev=previous, held="yes" if held is not None else "no")
        if held is not None and held[0] not in self._retired:
            self._bind(held[0], held[2])
            self._accepted = 1
            self.accepted += 1
            return held[1]
        return None

    # -- one datagram --------------------------------------------------------------------------------------------------------------------
    def accept(self, text):
        """Is this telemetry datagram to be applied to the application? Never raises. In normal mode it only follows AVAIL and always says yes."""
        line = contract.parse_telemetry(text)
        if not self.strict:
            self._follow_avail(line.availability if line.valid else None, line)
            return True
        if not line.valid:
            self.invalid += 1
            self._drop_episode(line.reason)
            return False
        sid = line.scenario_id
        if sid in self._retired or (sid in self._seen and sid != self._newest):
            self.stale += 1
            self._drop_episode("stale-epoch")
            return False
        if sid not in self._seen:
            self._remember(self._seen, sid)
            self._newest = sid
        # sid is now the newest scenario instance the sender has produced
        if self._bound is None:
            self._bind(sid, line.availability)
        elif sid != self._bound:
            self._ahead = sid
            self._held = (sid, text, line.availability)
            self.ahead_lines += 1
            self._drop_episode("sender-ahead")
            return False
        self._accepted += 1
        self.accepted += 1
        self._follow_avail(line.availability, line)
        return True

    # -- internals -----------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _remember(table, key):
        table[key] = True
        table.move_to_end(key)
        while len(table) > MAX_REMEMBERED_EPOCHS:
            table.popitem(last=False)

    def _bind(self, sid, availability):
        first = self._bound is None
        self._bound = sid
        self._ahead = None
        self._held = None
        self._accepted = 0
        self.epochs_bound += 1
        if sid != self._applied_epoch:
            self._applied_epoch = sid
            self._epoch_reset = True
        self.availability = availability
        self._emit("telemetry-first", gen=self.generation, avail="explicit" if availability.explicit else "none", **contract.compact_groups(availability))
        return first

    def _follow_avail(self, availability, line):
        """Tracks the availability of the accepted telemetry; logs only a change."""
        if availability is None:
            return
        self.unknown_tokens = line.unknown_tokens
        if availability != self.availability:
            self.availability = availability
            self.avail_changes += 1
            extra = {"unknown": line.unknown_tokens} if line.unknown_tokens else {}
            self._emit("telemetry-avail", gen=self.generation, avail="explicit" if availability.explicit else "none", changes=self.avail_changes,
                       **dict(contract.compact_groups(availability), **extra))

    def summary_fields(self):
        return dict(tel_accepted=self.accepted, tel_stale=self.stale, tel_invalid=self.invalid, tel_ahead=self.ahead_lines,
                    tel_epochs=self.epochs_bound, tel_avail_changes=self.avail_changes)
