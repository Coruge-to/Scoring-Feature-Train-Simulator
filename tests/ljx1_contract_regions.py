"""Legacy Jump (PID-D4 LJX-1) contract regions of the managed Python application: an AST based, interpreter independent region digest (test support, not a test).

Phase ST-2a Commit Prep (owner decision O-1): the whole-file SHA-256 pins of main.py / managed_input.py / scoring_logic.py in tests/test_legacy_jump_exec_ljx1.py could not
describe "the jump contract is unchanged" any more - every later phase that touched those files for another reason (StationIndex, identity, checkpoint) broke them. This
module pins the CONTRACT instead of the bytes.

A region is one of
  WHOLE   a function whose whole body is the contract: its canonical AST without the docstring;
  SLICE   a function (or the module level) in which only some statements name the contract: the statements, dictionary entries and container elements that contain a jump word,
          each with the path of the compound statements around it (the condition of an enclosing if / loop counts only when it names the contract itself);
  ORDER   the order of dotted call names inside one function (e.g. the shutdown order).
Comments, blank lines, docstrings, line numbers and every statement that does not name the contract are invisible, so an unrelated change leaves the digests unchanged, while
a changed jump statement, a changed condition around it, a changed order, a renamed / re-signatured / removed function or a NEW function that names the contract changes the result.
"""
import ast
import hashlib
import re
import subprocess

# the words that name the jump contract inside a SLICE (identifiers, attributes, string constants, keyword names, import names)
JUMP_WORDS = re.compile(r"jump|official|execute_retry|expected_target|ignore_next_pass", re.IGNORECASE)
MODULE = "<module>"
_SKIPPED_FIELDS = ("type_comment", "kind", "type_params", "ctx")


def parse(source):
    """An ast.Module from bytes / text; an ast.Module is returned unchanged."""
    if isinstance(source, ast.AST):
        return source
    if isinstance(source, bytes):
        source = source.decode("utf-8-sig")
    return ast.parse(source.lstrip("﻿"))


def canon(node, drop_docstrings=False):
    """A canonical text of an AST node that does not depend on the interpreter's ast.dump format (None / empty fields, ctx and type comments are left out)."""
    if isinstance(node, ast.AST):
        parts = []
        for name, value in ast.iter_fields(node):
            if name in _SKIPPED_FIELDS or value is None or value == []:
                continue
            if drop_docstrings and name == "body" and isinstance(value, list):
                value = [s for i, s in enumerate(value) if not (i == 0 and _is_docstring(s))]
                if not value:
                    continue
            parts.append("%s=%s" % (name, canon(value, drop_docstrings)))
        return "%s(%s)" % (type(node).__name__, ",".join(parts))
    if isinstance(node, list):
        return "[" + ",".join(canon(item, drop_docstrings) for item in node) + "]"
    return repr(node)


def _is_docstring(stmt):
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _names_contract(node):
    return JUMP_WORDS.search(canon(node)) is not None


def _atoms(value, prefix):
    """The atoms of the value of a simple statement: the dictionary entries / container elements that name the contract, else the whole value."""
    out = []
    if isinstance(value, ast.Dict):
        for key, val in zip(value.keys, value.values):
            key_text = canon(key) if key is not None else "None"
            if JUMP_WORDS.search(key_text) or _names_contract(val):
                out.append(prefix + ("item", key_text, canon(val)))
    elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        for element in value.elts:
            if _names_contract(element):
                out.append(prefix + ("elt", canon(element)))
    elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("frozenset", "set", "tuple", "list") and len(value.args) == 1:
        out.extend(_atoms(value.args[0], prefix + (value.func.id,)))
    elif value is not None and _names_contract(value):
        out.append(prefix + ("value", canon(value)))
    return out


def _simple_atoms(stmt, path):
    if _is_docstring(stmt):
        return []
    if isinstance(stmt, ast.Assign):
        prefix = path + ("assign", canon(stmt.targets))
        found = _atoms(stmt.value, prefix)
        if not found and any(JUMP_WORDS.search(canon(t)) for t in stmt.targets):
            found = [prefix + ("value", canon(stmt.value))]
        return found
    if isinstance(stmt, ast.AnnAssign):
        prefix = path + ("annassign", canon(stmt.target))
        found = _atoms(stmt.value, prefix) if stmt.value is not None else []
        if not found and JUMP_WORDS.search(canon(stmt.target)):
            found = [prefix + ("value", canon(stmt.value))]
        return found
    if isinstance(stmt, ast.Expr):
        return _atoms(stmt.value, path + ("expr",))
    if isinstance(stmt, ast.Return):
        return _atoms(stmt.value, path + ("return",)) if stmt.value is not None else []
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        module = getattr(stmt, "module", None) or ""
        where = "%s%s" % ("." * (getattr(stmt, "level", 0) or 0), module)
        return [path + ("import", where, alias.name, alias.asname or "") for alias in stmt.names if JUMP_WORDS.search(alias.name) or JUMP_WORDS.search(alias.asname or "")]
    return [path + (type(stmt).__name__, canon(stmt))] if _names_contract(stmt) else []


def _compound(stmt):
    """(kind, header text, [(branch name, statements), ...]) of a compound statement; None for a simple statement."""
    if isinstance(stmt, ast.If):
        return "if", canon(stmt.test), [("body", stmt.body), ("else", stmt.orelse)]
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return "for", canon(stmt.target) + "<-" + canon(stmt.iter), [("body", stmt.body), ("else", stmt.orelse)]
    if isinstance(stmt, ast.While):
        return "while", canon(stmt.test), [("body", stmt.body), ("else", stmt.orelse)]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return "with", canon(stmt.items), [("body", stmt.body)]
    if isinstance(stmt, ast.Try):
        branches = [("body", stmt.body)]
        for handler in stmt.handlers:
            branches.append(("except:" + canon(handler.type), handler.body))
        branches += [("else", stmt.orelse), ("finally", stmt.finalbody)]
        return "try", "", branches
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def", stmt.name + canon(stmt.args), [("body", stmt.body)]
    if isinstance(stmt, ast.ClassDef):
        return "class", stmt.name, [("body", stmt.body)]
    return None


_GUARDS = ("if", "while", "for", "with")


def _walk(stmts, path, records, module_level=False):
    for stmt in stmts:
        head = _compound(stmt)
        if head is None:
            records.extend(_simple_atoms(stmt, path))
            continue
        kind, text, branches = head
        if module_level and kind == "def":
            continue                                   # the module slice does not look into functions (they are units of their own)
        names_it = bool(JUMP_WORDS.search(text))
        for branch, body in branches:
            if not body:
                continue
            shown = text if (kind not in _GUARDS or names_it) else "~"     # a guard that does not name the contract is not part of it
            if kind in _GUARDS and names_it and branch == "body":
                records.append(path + ("%s-header" % kind, text))
            _walk(body, path + ("%s[%s]%s" % (kind, shown, branch),), records, module_level=module_level and kind == "class")


def slice_records(node):
    """The jump records of a module (its top level and class bodies, not its functions) or of one function (its body, nested functions included)."""
    records = []
    _walk(node.body, (), records, module_level=isinstance(node, ast.Module))
    return [" / ".join(record) for record in records]


def find_units(tree):
    """{qualified name: def node} for the module-level functions and the methods of the module-level classes."""
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out["%s.%s" % (node.name, child.name)] = child
    return out


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def whole_digest(node):
    return _digest(canon(node, drop_docstrings=True))


def slice_digest(records):
    return _digest("\n".join(records))


def region_digests(source, whole, sliced):
    """({unit: (kind, digest, record count) or None when the unit is missing}, [undeclared units that name the contract])."""
    tree = parse(source)
    units = find_units(tree)
    result = {}
    for name in whole:
        node = units.get(name)
        result[name] = None if node is None else ("whole", whole_digest(node), 1)
    for name in sliced:
        node = tree if name == MODULE else units.get(name)
        result[name] = None if node is None else ("slice", slice_digest(slice_records(node)), len(slice_records(node)))
    declared = set(whole) | set(sliced)
    undeclared = sorted(name for name, node in units.items() if name not in declared and slice_records(node))
    return result, undeclared


def call_names(node):
    """The dotted names of the calls inside a def (a nested def is part of it), in source order. A call on anything but a plain dotted name is left out."""
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            parts = []
            func = child.func
            while isinstance(func, ast.Attribute):
                parts.append(func.attr)
                func = func.value
            if isinstance(func, ast.Name):
                parts.append(func.id)
                found.append((child.lineno, child.col_offset, ".".join(reversed(parts))))
    return [name for _, _, name in sorted(found)]


def sequence_holds(source, unit, wanted):
    """True when the dotted call names in `wanted` occur in the def `unit` in that order (other calls may sit between); None when the unit is missing."""
    node = find_units(parse(source)).get(unit)
    if node is None:
        return None
    position = 0
    for name in call_names(node):
        if position < len(wanted) and name == wanted[position]:
            position += 1
    return position == len(wanted)


# -- git: the historical evidence is read from the formal LJX-1 commit, never from a copy -------------------------------------------------------------------------

def _git(repo, *args):
    try:
        done = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done


def git_blob(repo, commit, path):
    """The bytes of path at commit, or None when git / the commit / the path is not available."""
    done = _git(repo, "cat-file", "blob", "%s:%s" % (commit, path))
    return done.stdout if done is not None and done.returncode == 0 else None


def historical_blob_problems(repo, commit, path, blob_id, lf_sha256, crlf_sha256):
    """None = git or the commit is not available (INCONCLUSIVE); [] = the history holds; else the list of what does not match.
    blob_id: the git object id of path at commit; lf_sha256: SHA-256 of that blob; crlf_sha256: SHA-256 of the blob with CRLF line ends (the form of a Windows working file
    - the value the old whole-file pin held)."""
    content = git_blob(repo, commit, path)
    if content is None:
        return None
    problems = []
    done = _git(repo, "rev-parse", "%s:%s" % (commit, path))
    actual_id = done.stdout.decode("ascii", "replace").strip() if done is not None and done.returncode == 0 else ""
    if actual_id != blob_id:
        problems.append("blob id %s != %s" % (actual_id, blob_id))
    if _digest_bytes(content) != lf_sha256.upper():
        problems.append("LF SHA-256 %s != %s" % (_digest_bytes(content), lf_sha256.upper()))
    crlf = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if _digest_bytes(crlf) != crlf_sha256.upper():
        problems.append("CRLF SHA-256 %s != %s" % (_digest_bytes(crlf), crlf_sha256.upper()))
    done = _git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    if done is not None and done.returncode == 1:
        problems.append("%s is not an ancestor of HEAD" % commit)
    return problems


def _digest_bytes(data):
    return hashlib.sha256(data).hexdigest().upper()
