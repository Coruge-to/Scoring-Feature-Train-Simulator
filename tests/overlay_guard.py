"""Static guard shared by the managed-mode test suites: what Phase L3 is allowed to change in the Overlay class of main.py, proved on the AST.

Phase L3 touched the Overlay in exactly three ways, all of them code motion or additions:
  1. __init__ gets ONE more statement: `self.telemetry_gate = telemetry_gate.TelemetryGate(strict=False)`.
  2. read_udp_data: the datagram intake keeps its structure, only the final `latest_telemetry = text` became
     `if self.telemetry_gate.accept(text): latest_telemetry = text`; the application of the telemetry (the `if latest_telemetry:` block) moved
     UNCHANGED into apply_telemetry_text (which first applies the new-scenario reset), and the jump-completion block moved UNCHANGED into
     _settle_jump_complete.
  3. one new method: reset_telemetry_state.
Every other member of the class (update_logic, paintEvent, all menu handlers ...) is AST-identical to the older commit.
"""
import ast
import copy

L3_NEW_METHODS = {"reset_telemetry_state", "apply_telemetry_text", "_settle_jump_complete"}
L3_INIT_STATEMENT = "self.telemetry_gate = telemetry_gate.TelemetryGate(strict=False)"


def overlay_class(src):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Overlay")


def members(src):
    return {n.name: n for n in overlay_class(src).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _find_if(func, test_name=None, attr=None):
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            t = node.test
            if test_name is not None and isinstance(t, ast.Name) and t.id == test_name:
                return node
            if attr is not None and isinstance(t, ast.Compare) and isinstance(t.left, ast.Attribute) and t.left.attr == attr:
                return node
    return None


def _intake_loop(func):
    return next(n for n in func.body if isinstance(n, ast.While))


class _AcceptRewriter(ast.NodeTransformer):
    """Turns the L3 intake line back into the old one: `if self.telemetry_gate.accept(text): latest_telemetry = text` -> `latest_telemetry = text`."""

    def visit_If(self, node):
        self.generic_visit(node)
        if ast.unparse(node.test) == "self.telemetry_gate.accept(text)" and len(node.body) == 1 and not node.orelse:
            return node.body[0]
        return node


def problems(old_src, new_src, allow_other_init_changes=0):
    """List of strings describing every difference that is not covered by the L3 allowance (empty = only the allowed L3 changes)."""
    out = []
    old, new = members(old_src), members(new_src)
    added = set(new) - set(old)
    if not added <= L3_NEW_METHODS:
        out.append("unexpected new members: %s" % sorted(added - L3_NEW_METHODS))
    if set(old) - set(new):
        out.append("members removed: %s" % sorted(set(old) - set(new)))
    for name in sorted(set(old) & set(new)):
        if ast.dump(old[name]) == ast.dump(new[name]):
            continue
        if name == "__init__":
            extra = [s for s in new[name].body if ast.dump(s) not in {ast.dump(x) for x in old[name].body}]
            gone = [s for s in old[name].body if ast.dump(s) not in {ast.dump(x) for x in new[name].body}]
            texts = [ast.unparse(s) for s in extra]
            if L3_INIT_STATEMENT not in texts:
                out.append("__init__ lacks the L3 statement")
            others = [t for t in texts if t != L3_INIT_STATEMENT]
            if len(others) != allow_other_init_changes or len(gone) != allow_other_init_changes:
                out.append("__init__ differs beyond the L3 statement: added=%s removed=%s" % (others, [ast.unparse(s) for s in gone]))
        elif name == "read_udp_data":
            ow, nw = _intake_loop(old[name]), _intake_loop(new[name])
            rewritten = _AcceptRewriter().visit(copy.deepcopy(nw))
            if ast.dump(ow) != ast.dump(rewritten):
                out.append("read_udp_data: the datagram intake differs beyond the accept() line")
            old_apply = _find_if(old[name], test_name="latest_telemetry")
            new_apply = _find_if(new["apply_telemetry_text"], test_name="latest_telemetry") if "apply_telemetry_text" in new else None
            if old_apply is None or new_apply is None or ast.dump(old_apply) != ast.dump(new_apply):
                out.append("the telemetry application block did not move unchanged into apply_telemetry_text")
            old_jump = _find_if(old[name], attr="pending_jump_complete")
            new_jump = _find_if(new["_settle_jump_complete"], attr="pending_jump_complete") if "_settle_jump_complete" in new else None
            if old_jump is None or new_jump is None or ast.dump(old_jump) != ast.dump(new_jump):
                out.append("the jump completion block did not move unchanged into _settle_jump_complete")
        else:
            out.append("member changed: %s" % name)
    return out
