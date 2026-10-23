"""Phase PID-D4JA StationIndex ST-3e0 - the deterministic source package manifest, its generator / validator and the N-12 package guard.

What this is
  The Jump / StationIndex package is four sets of source that must travel together: the Python runtime (the import closure of main.py), the Current (BveEX) project, the Legacy
  (AtsEX) project and the Shared C# sources both compile. The manifest (package/source-package-manifest.json, Git managed) names those sources by the SHA-256 of the Git BLOB and
  fixes a fingerprint over them. The guard (`evaluate`) accepts exactly ONE combination - every set carries the same TSJUMP2 bundle, every source is the one the manifest
  names, the compile lists are the manifest's - and refuses everything else (fail-closed: whatever it can not read or understand is a refusal, never an acceptance).

Identity rules
  * source identity = SHA-256 of the Git blob = the bytes the Git clean filter stores (CRLF -> LF; binary and lone-CR files untouched). The work tree bytes, their line endings and
    their sizes are facts of one checkout (core.autocrlf), not identity: they are never written to the manifest (`facts` prints them for the pre-build inventory).
  * the fingerprint hashes a header (contract tag, versions, capability bundle) and the entry lines `set TAB path TAB BLOB_SHA256`, ordered by (set, UTF-8 bytes of the path), LF
    joined, no trailing LF. It does NOT hash the manifest, the commit, the branch, a time or a path outside the entries: no self reference, no future commit.
  * the manifest is not an entry of itself and not a runtime file. package/ (this tool included) is guard tooling, not runtime; tests are evidence, not runtime.
  * source_base_commit is the commit the source identity was computed on top of. The commit of the change that adds the manifest is recorded after the commit, outside this file.

This module reads only (git is asked cat-file / rev-parse / hash-object / merge-base). Only `cmd_generate` writes, to the path it is given. Standard library only, no network.

Usage (explicit paths only):
  python -I -B package/source_package.py generate --repo-root R --base-commit C --branch B --out PATH
  python -I -B package/source_package.py check --repo-root R [--manifest PATH] [--mode worktree|commit] [--rev HEAD] [--verify-clean-filter]
  python -I -B package/source_package.py facts --repo-root R [--manifest PATH]
Exit status: 0 accepted / done, 1 refused, 2 usage.
"""
import argparse
import ast
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ElementTree

# ---- the lock: what the guard expects (the fifth definition of the bundle, deliberately: a package whose own files were all edited together is still refused) ----------------
EXPECTED_TAG = "TSJUMP2"
EXPECTED_REQUEST_WIRE = 2
EXPECTED_COMPLETION_WIRE = 2
EXPECTED_STATIONINDEX_WIRE = 1
EXPECTED_CAPABILITIES = (
    "jump-request-v2",
    "jump-completion-v2",
    "current-selected-idx",
    "legacy-selected-idx",
    "python-completion-settlement",
    "stationindex-transaction",
    "target-reinitialization",
    "retry-history-settlement",
    "legacy-r1b",
    "current-station-range-fail-closed",
    "whole-list-reject",
    "partial-list-not-published",
)
SCHEMA = "ts-source-package-manifest/1"
PACKAGE_CONTRACT = "ts-package-contract/1"
FINGERPRINT_HEADER = "ts-source-package-fingerprint/1"
EXPECTED_BUILD_STATUS = "not-built"
EXPECTED_DEPLOYMENT_STATUS = "not-deployed"
LAUNCHER_CONTRACT = collections.OrderedDict([("file_name", "launcher.json"), ("schema_version", 1), ("mode", "development")])

MANIFEST_PATH = "package/source-package-manifest.json"
PYTHON_ENTRY = "main.py"
PYTHON_CONTRACT_FILE = "package_contract.py"
REQUIRED_PYTHON = ("main.py", "scoring_logic.py", "managed_input.py", "station_identity.py", "jump_wire.py", "jump_transaction.py")
CURRENT_DIR = "TsScoringPlugin/TsScoringPlugin"
LEGACY_DIR = "TsScoringPlugin/Handshake/Telemetry/Legacy"
SHARED_DIR = "TsScoringPlugin/Handshake/Telemetry/Shared"
CURRENT_PROJECT = CURRENT_DIR + "/TsScoringPlugin.csproj"
LEGACY_PROJECT = LEGACY_DIR + "/TSScoringPlugin.AtsExLegacy.Telemetry.csproj"
CONTRACT_CS = SHARED_DIR + "/PackageContract.cs"
SETS = ("python", "current", "legacy", "shared")
SET_RANK = dict((name, i) for i, name in enumerate(SETS))
MANIFEST_KEYS = ["schema", "package_contract", "contract_tag", "source_base_commit", "source_branch", "request_wire_version", "completion_wire_version",
                 "stationindex_wire_version", "capabilities", "launcher_contract", "build_status", "deployment_status", "python_entry", "compile_inputs", "files", "fingerprint"]
ENTRY_KEYS = ["set", "path", "blob_sha256", "blob_size", "blob_eol"]
EOL_VALUES = ("none", "lf", "crlf", "mixed")

_LONE_CR = re.compile(rb"\r(?!\n)")
_SHA_UPPER = re.compile(r"^[0-9A-F]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SEGMENT = re.compile(r"^[A-Za-z0-9_+-][A-Za-z0-9_.+-]*$")
_BOM = b"\xef\xbb\xbf"

Verdict = collections.namedtuple("Verdict", "accepted findings build_allowed deployment_allowed mode")


class GenerationError(Exception):
    """The tree can not be turned into a manifest; `findings` says why."""

    def __init__(self, findings):
        Exception.__init__(self, "; ".join(findings))
        self.findings = list(findings)


class LinkError(OSError):
    """A source path runs through a symbolic link or a reparse point (a junction): its bytes are not the bytes of the place it is listed at, so it is never read."""


# ---- trees: where the bytes come from -----------------------------------------------------------------------------------------------------------------------------------------

def _norm(path):
    return path.replace("\\", "/").strip("/")


class MemoryTree(object):
    """A tree held in a dict {relative path with '/': bytes}."""

    def __init__(self, files):
        self.files = dict((_norm(k), v) for k, v in files.items())

    def read(self, path):
        return self.files.get(_norm(path))

    def listdir(self, path):
        prefix = _norm(path)
        prefix = prefix + "/" if prefix else ""
        names = set()
        for key in self.files:
            if key.startswith(prefix) and "/" not in key[len(prefix):]:
                names.add(key[len(prefix):])
        return sorted(names)


class DiskTree(object):
    """The work tree under `root` (read only). A path that runs through a symbolic link or a reparse point raises LinkError (it is never followed)."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def _full(self, path):
        parts = [p for p in _norm(path).split("/") if p]
        return os.path.join(self.root, *parts) if parts else self.root

    def _refuse_links(self, full, shown):
        current = self.root
        for part in [p for p in os.path.relpath(full, self.root).split(os.sep) if p and p != "."]:
            current = os.path.join(current, part)
            if not os.path.lexists(current):
                return
            if os.path.islink(current) or (getattr(os.lstat(current), "st_file_attributes", 0) & 0x400):
                raise LinkError("symbolic link or reparse point: " + shown)

    def read(self, path):
        full = self._full(path)
        self._refuse_links(full, _norm(path))
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as handle:
            return handle.read()

    def listdir(self, path):
        full = self._full(path)
        self._refuse_links(full, _norm(path))
        if not os.path.isdir(full):
            return []
        return sorted(n for n in os.listdir(full) if os.path.isfile(os.path.join(full, n)))


def _git(root, args, data=None):
    """Run git read-only in `root`; the bytes of its standard output, or None when it failed."""
    done = subprocess.run(["git", "-C", root] + list(args), input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return done.stdout if done.returncode == 0 else None


class GitTree(object):
    """The blobs of a revision (`git cat-file`), read only."""

    def __init__(self, root, rev):
        self.root = os.path.abspath(root)
        self.rev = rev

    def read(self, path):
        return _git(self.root, ["cat-file", "blob", "%s:%s" % (self.rev, _norm(path))])

    def listdir(self, path):
        spec = "%s:%s" % (self.rev, _norm(path)) if _norm(path) else self.rev
        out = _git(self.root, ["ls-tree", "--name-only", spec])
        return [] if out is None else sorted(n for n in out.decode("utf-8").splitlines() if n)


# ---- bytes -----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def clean_blob(data):
    """What the Git clean filter stores for a work tree file: CRLF -> LF, unless the bytes are binary (a NUL) or hold a lone CR."""
    if b"\x00" in data or _LONE_CR.search(data):
        return data
    return data.replace(b"\r\n", b"\n")


def sha256_upper(data):
    return hashlib.sha256(data).hexdigest().upper()


def git_blob_id(data):
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def line_ending(blob):
    crlf = blob.count(b"\r\n")
    lf = blob.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    return "lf" if lf else "none"


def _blob(tree, path):
    data = tree.read(path)
    return None if data is None else clean_blob(data)


def path_set(path):
    """The set a path belongs to by its place, or None when it belongs to none of the four."""
    if "/" not in path and path.endswith(".py"):
        return "python"
    for name, folder in (("current", CURRENT_DIR), ("legacy", LEGACY_DIR), ("shared", SHARED_DIR)):
        if path.startswith(folder + "/"):
            return name
    return None


def path_problem(path):
    """Why a manifest path is not a plain relative path with '/', or None."""
    if not isinstance(path, str) or not path:
        return "empty or not text"
    if "\\" in path or ":" in path or path.startswith("/") or path.endswith("/"):
        return "absolute, drive or backslash"
    for seg in path.split("/"):
        if seg in ("", ".", "..") or not _SEGMENT.match(seg):
            return "segment %r" % seg
    return None


# ---- the python set --------------------------------------------------------------------------------------------------------------------------------------------------------------

def python_closure(tree):
    """The static import closure of main.py over the root modules of the tree. Returns (sorted module names, list of modules with a dynamic import, list of unparseable modules)."""
    universe = set(n[:-3] for n in tree.listdir("") if n.endswith(".py"))
    seen, dynamic, broken = set(), set(), set()
    stack = [PYTHON_ENTRY[:-3]]
    while stack:
        name = stack.pop()
        if name in seen or name not in universe:
            continue
        seen.add(name)
        try:
            module = ast.parse(tree.read(name + ".py"))
        except (SyntaxError, ValueError):
            broken.add(name)
            continue
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                stack.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                stack.append(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                f = node.func
                called = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                if called in ("__import__", "import_module"):
                    dynamic.add(name)
    return sorted(seen), sorted(dynamic), sorted(broken)


def python_contract(tree):
    """The constants of package_contract.py read as a syntax tree (never imported): a dict, with None for every value that is missing."""
    out = {"tag": None, "request": None, "completion": None, "stationindex": None, "capabilities": None}
    data = tree.read(PYTHON_CONTRACT_FILE)
    if data is None:
        return out
    try:
        module = ast.parse(data)
    except (SyntaxError, ValueError):
        return out
    names = {"CONTRACT_TAG": "tag", "REQUEST_WIRE_VERSION": "request", "COMPLETION_WIRE_VERSION": "completion", "STATIONINDEX_WIRE_VERSION": "stationindex", "CAPABILITIES": "capabilities"}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            out[names[node.targets[0].id]] = tuple(value) if isinstance(value, (list, tuple)) else value
    return out


# ---- the C# sets -----------------------------------------------------------------------------------------------------------------------------------------------------------------

def compile_items(tree, project):
    """The Compile items of a project: a list of (resolved repository relative path or None, raw Include, Link or None). Raises ValueError when the project can not be read as XML."""
    data = tree.read(project)
    if data is None:
        raise ValueError("project missing")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("project is not XML: %s" % error)
    base = os.path.dirname(project)
    items = []
    for element in root.iter():
        if not (isinstance(element.tag, str) and element.tag.split("}")[-1] == "Compile"):
            continue
        include = element.get("Include")
        link = None
        for child in element:
            if isinstance(child.tag, str) and child.tag.split("}")[-1] == "Link":
                link = (child.text or "").strip()
        resolved = None
        if include:
            resolved = os.path.normpath(os.path.join(base, include.replace("\\", "/"))).replace("\\", "/")
        items.append((resolved, include, link))
    return items


def compile_hazards(tree, project):
    """What in a project can change WHAT is compiled without changing the list of Compile Include items: a Condition on a Compile item or on a group around it, and a
    Remove / Update / Exclude on a Compile item. Returns a sorted list of "conditional" / "modified". Raises ValueError like compile_items."""
    data = tree.read(project)
    if data is None:
        raise ValueError("project missing")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError("project is not XML: %s" % error)
    parents = dict((child, parent) for parent in root.iter() for child in parent)
    found = set()
    for element in root.iter():
        if not (isinstance(element.tag, str) and element.tag.split("}")[-1] == "Compile"):
            continue
        if element.get("Condition") is not None:
            found.add("conditional")
        if any(element.get(a) is not None for a in ("Remove", "Update", "Exclude")):
            found.add("modified")
        ancestor = parents.get(element)
        while ancestor is not None:
            if ancestor.get("Condition") is not None:
                found.add("conditional")
            ancestor = parents.get(ancestor)
    return sorted(found)


def csharp_contract(tree, project):
    """The constants of PackageContract.cs as THIS project compiles them (None for everything when the project does not compile the file). `directives` is True when the file holds
    a preprocessor directive (#if ...): the constants could then differ from what the compiler sees, so the file is refused."""
    out = {"tag": None, "request": None, "completion": None, "stationindex": None, "capabilities": None, "directives": False}
    try:
        compiled = [r for r, _i, _l in compile_items(tree, project)]
    except ValueError:
        return out
    if CONTRACT_CS not in compiled:
        return out
    data = tree.read(CONTRACT_CS)
    if data is None:
        return out
    text = data.decode("utf-8", "replace")
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    out["directives"] = re.search(r"^\s*#", text, flags=re.M) is not None
    def string_const(name):
        m = re.search(r'internal const string %s = "([^"]*)";' % name, text)
        return None if m is None else m.group(1)
    def int_const(name):
        m = re.search(r"internal const int %s = (-?\d+);" % name, text)
        return None if m is None else int(m.group(1))
    out["tag"] = string_const("Tag")
    out["request"] = int_const("RequestWireVersion")
    out["completion"] = int_const("CompletionWireVersion")
    out["stationindex"] = int_const("StationIndexWireVersion")
    caps = string_const("Capabilities")
    out["capabilities"] = None if caps is None else tuple(caps.split(","))
    return out


def shared_files(tree):
    return sorted(SHARED_DIR + "/" + n for n in tree.listdir(SHARED_DIR) if n.endswith(".cs"))


# ---- the manifest ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def entry_sort_key(entry):
    return (SET_RANK[entry["set"]], entry["path"].encode("utf-8"))


def fingerprint(manifest):
    """SHA-256 (upper case hex) of the header and the sorted entry lines (see the module text). Raises on a manifest of the wrong shape."""
    lines = [FINGERPRINT_HEADER, "contract_tag\t" + manifest["contract_tag"], "request_wire_version\t%d" % manifest["request_wire_version"],
             "completion_wire_version\t%d" % manifest["completion_wire_version"], "stationindex_wire_version\t%d" % manifest["stationindex_wire_version"],
             "capabilities\t" + ",".join(manifest["capabilities"])]
    for entry in sorted(manifest["files"], key=entry_sort_key):
        lines.append("%s\t%s\t%s" % (entry["set"], entry["path"], entry["blob_sha256"]))
    return sha256_upper("\n".join(lines).encode("utf-8"))


def build_manifest(tree, base_commit, branch):
    """The manifest of the tree: the four sets, the identity of every source, the fingerprint. Raises GenerationError when the tree can not carry a package."""
    problems = []
    if not isinstance(base_commit, str) or not _COMMIT.match(base_commit):
        problems.append("base-commit-invalid")
    if not isinstance(branch, str) or not branch.strip() or not re.match(r"^[A-Za-z0-9._/-]+$", branch):
        problems.append("branch-invalid")
    if tree.read(PYTHON_ENTRY) is None:
        raise GenerationError(["python-entry-missing"] + problems)
    modules, _dynamic, broken = python_closure(tree)
    if broken:
        problems.extend("source-unparseable:%s.py" % m for m in broken)
    sets = {"python": [m + ".py" for m in modules], "current": [CURRENT_PROJECT], "legacy": [LEGACY_PROJECT], "shared": shared_files(tree)}
    compile_lists = {}
    for name, project, folder in (("current", CURRENT_PROJECT, CURRENT_DIR), ("legacy", LEGACY_PROJECT, LEGACY_DIR)):
        try:
            resolved = [r for r, _i, _l in compile_items(tree, project)]
        except ValueError as error:
            problems.append("project-unparseable:%s (%s)" % (name, error))
            continue
        if None in resolved:
            problems.append("compile-item-without-include:%s" % name)
            continue
        compile_lists[name] = sorted(resolved)
        sets[name].extend(r for r in resolved if r.startswith(folder + "/"))
    if problems:
        raise GenerationError(problems)
    files = []
    for name in SETS:
        for path in sorted(set(sets[name]), key=lambda p: p.encode("utf-8")):
            blob = _blob(tree, path)
            if blob is None:
                problems.append("source-missing:" + path)
                continue
            files.append(collections.OrderedDict([("set", name), ("path", path), ("blob_sha256", sha256_upper(blob)), ("blob_size", len(blob)), ("blob_eol", line_ending(blob))]))
    if problems:
        raise GenerationError(problems)
    manifest = collections.OrderedDict()
    manifest["schema"] = SCHEMA
    manifest["package_contract"] = PACKAGE_CONTRACT
    manifest["contract_tag"] = EXPECTED_TAG
    manifest["source_base_commit"] = base_commit
    manifest["source_branch"] = branch
    manifest["request_wire_version"] = EXPECTED_REQUEST_WIRE
    manifest["completion_wire_version"] = EXPECTED_COMPLETION_WIRE
    manifest["stationindex_wire_version"] = EXPECTED_STATIONINDEX_WIRE
    manifest["capabilities"] = list(EXPECTED_CAPABILITIES)
    manifest["launcher_contract"] = collections.OrderedDict(LAUNCHER_CONTRACT)
    manifest["build_status"] = EXPECTED_BUILD_STATUS
    manifest["deployment_status"] = EXPECTED_DEPLOYMENT_STATUS
    manifest["python_entry"] = PYTHON_ENTRY
    manifest["compile_inputs"] = collections.OrderedDict([("current", compile_lists["current"]), ("legacy", compile_lists["legacy"])])
    manifest["files"] = files
    manifest["fingerprint"] = fingerprint(manifest)
    return manifest


def _js(value):
    return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))


def _lines(values, indent):
    if not isinstance(values, list):
        return _js(values)
    if not values:
        return "[]"
    pad = " " * (indent + 2)
    return "[\n" + ",\n".join(pad + _js(v) for v in values) + "\n" + " " * indent + "]"


def serialize(manifest):
    """The canonical bytes: UTF-8 (ASCII), LF, two space indent, one trailing LF, fixed key order, every file entry on one line. Does not repair a manifest: it writes what it is given."""
    keys = [k for k in MANIFEST_KEYS if k in manifest] + sorted(k for k in manifest if k not in MANIFEST_KEYS)
    parts = []
    for key in keys:
        value = manifest[key]
        if key == "capabilities":
            text = _lines(value, 2)
        elif key == "compile_inputs" and isinstance(value, dict):
            inner = ",\n".join("    %s: %s" % (_js(k), _lines(v, 4)) for k, v in value.items())
            text = "{\n" + inner + "\n  }" if value else "{}"
        elif key == "files":
            text = _lines(value, 2)
        else:
            text = _js(value)
        parts.append("  %s: %s" % (_js(key), text))
    return ("{\n" + ",\n".join(parts) + "\n}\n").encode("ascii")


def parse_manifest(data):
    """(parsed, object, findings). `parsed` is False when there is no document (a missing manifest is `manifest-missing`, bytes that are not JSON are `manifest-unparseable`); a JSON null is a
    parsed document whose object is None (and is refused by the shape check). A duplicate key is reported and parsing goes on."""
    findings = []
    if data is None:
        return False, None, ["manifest-missing"]
    if not isinstance(data, (bytes, bytearray)):
        return False, None, ["manifest-unparseable"]
    body = bytes(data)
    if body.startswith(_BOM):
        body = body[len(_BOM):]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return False, None, ["manifest-unparseable"]
    duplicates = []

    def hook(pairs):
        seen = set()
        for k, _v in pairs:
            if k in seen:
                duplicates.append(k)
            seen.add(k)
        return collections.OrderedDict(pairs)

    try:
        obj = json.loads(text, object_pairs_hook=hook)
    except (ValueError, RecursionError):
        return False, None, ["manifest-unparseable"]
    if duplicates:
        findings.append("manifest-duplicate-key")
    return True, obj, findings


def _is_int(value):
    return type(value) is int


def manifest_findings(obj, data):
    """Everything wrong with the manifest on its own (shape, values, paths, order, fingerprint, canonical bytes). Returns (findings, shape_ok)."""
    found = []
    if not isinstance(obj, dict):
        return ["manifest-schema-mismatch"], False
    shape = []
    if set(obj) != set(MANIFEST_KEYS):
        shape.append("manifest-schema-mismatch")
    else:
        text_keys = ("schema", "package_contract", "contract_tag", "source_base_commit", "source_branch", "build_status", "deployment_status", "python_entry", "fingerprint")
        if not all(isinstance(obj[k], str) for k in text_keys):
            shape.append("manifest-schema-mismatch")
        if not all(_is_int(obj[k]) for k in ("request_wire_version", "completion_wire_version", "stationindex_wire_version")):
            shape.append("manifest-schema-mismatch")
        if not (isinstance(obj["capabilities"], list) and all(isinstance(c, str) for c in obj["capabilities"])):
            shape.append("manifest-schema-mismatch")
        if not (isinstance(obj["launcher_contract"], dict) and isinstance(obj["compile_inputs"], dict) and isinstance(obj["files"], list)):
            shape.append("manifest-schema-mismatch")
        else:
            ci = obj["compile_inputs"]
            if set(ci) != {"current", "legacy"} or not all(isinstance(v, list) and all(isinstance(p, str) for p in v) for v in ci.values()):
                shape.append("manifest-schema-mismatch")
            for entry in obj["files"]:
                if not (isinstance(entry, dict) and set(entry) == set(ENTRY_KEYS) and isinstance(entry["set"], str) and isinstance(entry["path"], str)
                        and isinstance(entry["blob_sha256"], str) and _is_int(entry["blob_size"]) and isinstance(entry["blob_eol"], str)):
                    shape.append("manifest-schema-mismatch")
                    break
    if shape:
        return sorted(set(shape)), False
    if obj["schema"] != SCHEMA:
        found.append("manifest-schema-mismatch")
    if obj["package_contract"] != PACKAGE_CONTRACT:
        found.append("manifest-contract-mismatch")
    if obj["build_status"] != EXPECTED_BUILD_STATUS or obj["deployment_status"] != EXPECTED_DEPLOYMENT_STATUS:
        found.append("manifest-status-invalid")
    if not _COMMIT.match(obj["source_base_commit"]):
        found.append("manifest-base-commit-invalid")
    if not re.match(r"^[A-Za-z0-9._/-]+$", obj["source_branch"]):
        found.append("manifest-schema-mismatch")
    if obj["python_entry"] != PYTHON_ENTRY:
        found.append("manifest-schema-mismatch")
    if dict(obj["launcher_contract"]) != dict(LAUNCHER_CONTRACT) or list(obj["launcher_contract"]) != list(LAUNCHER_CONTRACT):
        found.append("launcher-contract-mismatch")
    # the values of the bundle in the manifest
    found.extend(_bundle_findings("manifest", obj["contract_tag"], obj["request_wire_version"], obj["completion_wire_version"], obj["stationindex_wire_version"], tuple(obj["capabilities"])))
    # entries
    seen, folded = set(), {}
    for entry in obj["files"]:
        path = entry["path"]
        if path_problem(path):
            found.append("manifest-path-invalid")
        if path in seen:
            found.append("manifest-duplicate-path")
        seen.add(path)
        other = folded.setdefault(path.lower(), path)
        if other != path:
            found.append("manifest-path-collision")
        if entry["set"] not in SET_RANK:
            found.append("manifest-schema-mismatch")
        elif path_set(path) != entry["set"]:
            found.append("manifest-set-mismatch")
        if not _SHA_UPPER.match(entry["blob_sha256"]) or entry["blob_size"] < 0 or entry["blob_eol"] not in EOL_VALUES:
            found.append("manifest-schema-mismatch")
    if not any(f in found for f in ("manifest-schema-mismatch", "manifest-path-invalid")):
        keys = [entry_sort_key(e) for e in obj["files"]]
        if keys != sorted(keys):
            found.append("manifest-not-canonical")
    for name in ("current", "legacy"):
        listed = obj["compile_inputs"][name]
        if listed != sorted(listed) or len(listed) != len(set(listed)):
            found.append("manifest-not-canonical")
    # canonical bytes: key order and the exact serialization
    if list(obj) != MANIFEST_KEYS or list(obj["compile_inputs"]) != ["current", "legacy"]:
        found.append("manifest-not-canonical")
    for entry in obj["files"]:
        if list(entry) != ENTRY_KEYS:
            found.append("manifest-not-canonical")
            break
    if not any(f.startswith("manifest-schema") or f == "manifest-path-invalid" for f in found):
        try:
            if fingerprint(obj) != obj["fingerprint"]:
                found.append("manifest-fingerprint-mismatch")
        except (KeyError, TypeError, ValueError):
            found.append("manifest-fingerprint-mismatch")
    if serialize(obj) != data:
        found.append("manifest-not-canonical")
    return sorted(set(found)), True


def _bundle_findings(component, tag, request, completion, stationindex, capabilities):
    """tag-missing / tag-mismatch and the version / capability mismatches of one component against the lock."""
    found = []
    if tag is None:
        found.append("tag-missing:" + component)
        return found                                            # a component without the tag has no bundle to compare
    if tag != EXPECTED_TAG:
        found.append("tag-mismatch:" + component)
    if request != EXPECTED_REQUEST_WIRE:
        found.append("request-wire-mismatch:" + component)
    if completion != EXPECTED_COMPLETION_WIRE:
        found.append("completion-wire-mismatch:" + component)
    if stationindex != EXPECTED_STATIONINDEX_WIRE:
        found.append("stationindex-wire-mismatch:" + component)
    if capabilities is None or tuple(capabilities) != EXPECTED_CAPABILITIES:
        found.append("capabilities-mismatch:" + component)
    return found


# ---- the guard -------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _phase(findings, name, function):
    """Run one phase; anything it raises is a refusal (fail-closed), never an acceptance and never an uncaught exception."""
    try:
        function()
    except Exception as error:                                  # noqa: BLE001 - the guard must never let an unknown state through
        findings.add("internal-error:%s (%s)" % (name, type(error).__name__))


def evaluate(tree, manifest_bytes, mode="worktree", committed=None):
    """The N-12 verdict on a tree and the bytes of its manifest. `mode` is "worktree" (the tree is what is checked) or "commit" (the tree must also be what the `committed` view holds)."""
    findings = set()
    manifest = {"obj": None, "shape_ok": False}

    if mode not in ("worktree", "commit"):
        findings.add("mode-invalid")

    def manifest_phase():
        parsed, obj, found = parse_manifest(manifest_bytes)
        findings.update(found)
        if parsed:
            extra, shape_ok = manifest_findings(obj, manifest_bytes)
            findings.update(extra)
            manifest["obj"], manifest["shape_ok"] = obj, shape_ok

    _phase(findings, "manifest", manifest_phase)
    obj = manifest["obj"] if manifest["shape_ok"] else None
    entries = {}
    if obj is not None:
        entries = dict((e["path"], e) for e in obj["files"])

    def identity_phase():
        for path, entry in sorted(entries.items()):
            try:
                blob = _blob(tree, path)
            except LinkError:
                findings.add("source-link:" + path)
                continue
            if blob is None:
                findings.add("source-missing:" + path)
            elif sha256_upper(blob) != entry["blob_sha256"] or len(blob) != entry["blob_size"] or line_ending(blob) != entry["blob_eol"]:
                findings.add("source-identity-mismatch:" + path)

    _phase(findings, "identity", identity_phase)

    python_state = {"modules": None}

    def python_phase():
        if tree.read(PYTHON_ENTRY) is None:
            findings.add("python-entry-missing")
        modules, dynamic, broken = python_closure(tree)
        python_state["modules"] = modules
        if dynamic:
            findings.add("python-dynamic-import")
        for name in broken:
            findings.add("source-unparseable:%s.py" % name)
        for name in REQUIRED_PYTHON:
            if name[:-3] not in modules:
                findings.add("python-required-missing:" + name)
        if obj is not None:
            listed = sorted(p for p, e in entries.items() if e["set"] == "python")
            if listed != [m + ".py" for m in modules]:
                findings.add("python-set-mismatch")
            for m in modules:
                if m + ".py" not in entries:
                    findings.add("source-unlisted:%s.py" % m)
        contract = python_contract(tree)
        for f in _bundle_findings("python", contract["tag"], contract["request"], contract["completion"], contract["stationindex"], contract["capabilities"]):
            findings.add(f)

    _phase(findings, "python", python_phase)

    csharp_tags = {}
    resolved_lists = {}

    def csharp_phase(name, project, folder, allowed):
        try:
            items = compile_items(tree, project)
            hazards = compile_hazards(tree, project)
        except ValueError as error:
            findings.add("source-missing:" + project if "missing" in str(error) else "project-unparseable:" + name)
            csharp_tags[name] = None
            return
        for hazard in hazards:
            findings.add("compile-%s:%s" % (hazard, name))
        resolved = []
        links = []
        for path, include, link in items:
            if not include:
                findings.add("compile-item-without-include:" + name)
                continue
            if "*" in include or "?" in include:
                findings.add("compile-wildcard:" + name)
                continue
            if path is None or path.startswith("../") or path == ".." or os.path.isabs(path) or not any(path.startswith(a + "/") for a in allowed):
                findings.add("compile-input-out-of-set:" + name)
            resolved.append(path)
            if link is not None:
                links.append(link.lower())
        if len(resolved) != len(set(resolved)):
            findings.add("compile-duplicate:" + name)
        if len(links) != len(set(links)):
            findings.add("compile-link-collision:" + name)
        if obj is not None:
            if sorted(set(resolved)) != obj["compile_inputs"][name]:
                findings.add("compile-set-mismatch:" + name)
            for path in resolved:
                owner = path_set(path)
                if owner in ("current", "legacy", "shared") and path not in entries:
                    findings.add("source-unlisted:" + path)
        contract = csharp_contract(tree, project)
        csharp_tags[name] = contract["tag"]
        if contract["directives"]:
            findings.add("contract-source-conditional:" + name)
        for f in _bundle_findings(name, contract["tag"], contract["request"], contract["completion"], contract["stationindex"], contract["capabilities"]):
            findings.add(f)
        resolved_lists[name] = resolved

    _phase(findings, "current", lambda: csharp_phase("current", CURRENT_PROJECT, CURRENT_DIR, (CURRENT_DIR, SHARED_DIR)))
    _phase(findings, "legacy", lambda: csharp_phase("legacy", LEGACY_PROJECT, LEGACY_DIR, (LEGACY_DIR, SHARED_DIR, CURRENT_DIR)))

    def shared_phase():
        compiled = set(resolved_lists.get("current", [])) | set(resolved_lists.get("legacy", []))
        for path in shared_files(tree):
            if path not in compiled:
                findings.add("shared-unreferenced:" + path)
            if obj is not None and path not in entries:
                findings.add("source-unlisted:" + path)

    _phase(findings, "shared", shared_phase)

    def partial_phase():
        python_tag = python_contract(tree)["tag"]
        carried = [t is not None for t in (python_tag, csharp_tags.get("current"), csharp_tags.get("legacy"))]
        if any(carried) and not all(carried):
            findings.add("tag-partial")

    _phase(findings, "partial", partial_phase)

    def commit_phase():
        if committed is None:
            findings.add("committed-view-missing")
            return
        for path in sorted(entries):
            live = _blob(tree, path)
            held = _blob(committed, path)
            if held is None:
                findings.add("source-not-committed:" + path)
            elif live is not None and live != held:
                findings.add("working-tree-drift:" + path)

    if mode == "commit":
        _phase(findings, "commit", commit_phase)

    accepted = not findings
    return Verdict(accepted, tuple(sorted(findings)), accepted, False, mode)


def verify_clean_filter(root, tree, paths):
    """Ask git itself (hash-object with the path rules, no write) whether the blob this module computes is the blob git would store. Returns the paths where they differ."""
    bad = []
    for path in paths:
        data = tree.read(path)
        if data is None:
            bad.append(path)
            continue
        asked = _git(os.path.abspath(root), ["hash-object", "--path=" + path, "--stdin"], data)
        if asked is None or asked.decode("ascii").strip() != git_blob_id(clean_blob(data)):
            bad.append(path)
    return bad


# ---- command line ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def _print_verdict(verdict):
    print("RESULT: %s  mode=%s  build_allowed=%s  deployment_allowed=%s  findings=%d" % ("ACCEPT" if verdict.accepted else "REJECT", verdict.mode, verdict.build_allowed,
                                                                                         verdict.deployment_allowed, len(verdict.findings)))
    for f in verdict.findings:
        print("  finding: " + f)


def cmd_generate(args):
    tree = DiskTree(args.repo_root)
    try:
        manifest = build_manifest(tree, args.base_commit, args.branch)
    except GenerationError as error:
        print("RESULT: GENERATION-REFUSED")
        for f in error.findings:
            print("  finding: " + f)
        return 1
    data = serialize(manifest)
    verdict = evaluate(tree, data)
    if not verdict.accepted:
        _print_verdict(verdict)
        return 1
    with open(args.out, "wb") as handle:
        handle.write(data)
    print("RESULT: GENERATED  entries=%d  fingerprint=%s  bytes=%d  sha256=%s" % (len(manifest["files"]), manifest["fingerprint"], len(data), sha256_upper(data)))
    return 0


def cmd_check(args):
    tree = DiskTree(args.repo_root)
    path = args.manifest if args.manifest else os.path.join(os.path.abspath(args.repo_root), *MANIFEST_PATH.split("/"))
    data = None
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            data = handle.read()
    committed = GitTree(args.repo_root, args.rev) if args.mode == "commit" else None
    verdict = evaluate(tree, data, mode=args.mode, committed=committed)
    findings = set(verdict.findings)
    if args.verify_clean_filter:
        _parsed, obj, _f = parse_manifest(data)
        paths = [e["path"] for e in obj["files"] if isinstance(e, dict) and isinstance(e.get("path"), str)] if isinstance(obj, dict) and isinstance(obj.get("files"), list) else []
        for bad in verify_clean_filter(args.repo_root, tree, paths):
            findings.add("clean-filter-mismatch:" + bad)
    accepted = not findings
    _print_verdict(Verdict(accepted, tuple(sorted(findings)), accepted, False, args.mode))
    return 0 if accepted else 1


def cmd_facts(args):
    """Tab separated facts of the CHECKOUT (work tree) for every manifest entry - for the pre-build inventory, never part of the manifest."""
    tree = DiskTree(args.repo_root)
    path = args.manifest if args.manifest else os.path.join(os.path.abspath(args.repo_root), *MANIFEST_PATH.split("/"))
    with open(path, "rb") as handle:
        _parsed, obj, _f = parse_manifest(handle.read())
    print("set\tpath\tblob_sha256\tblob_size\tblob_eol\tworktree_sha256\tworktree_size\tworktree_eol")
    for e in obj["files"]:
        raw = tree.read(e["path"])
        if raw is None:
            print("\t".join([e["set"], e["path"], e["blob_sha256"], str(e["blob_size"]), e["blob_eol"], "MISSING", "", ""]))
        else:
            print("\t".join([e["set"], e["path"], e["blob_sha256"], str(e["blob_size"]), e["blob_eol"], sha256_upper(raw), str(len(raw)), line_ending(raw)]))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="source_package.py", description="deterministic source package manifest and N-12 package guard (read only)")
    sub = parser.add_subparsers(dest="command")
    gen = sub.add_parser("generate")
    gen.add_argument("--repo-root", required=True)
    gen.add_argument("--base-commit", required=True)
    gen.add_argument("--branch", required=True)
    gen.add_argument("--out", required=True)
    chk = sub.add_parser("check")
    chk.add_argument("--repo-root", required=True)
    chk.add_argument("--manifest", default=None)
    chk.add_argument("--mode", default="worktree", choices=["worktree", "commit"])
    chk.add_argument("--rev", default="HEAD")
    chk.add_argument("--verify-clean-filter", action="store_true")
    fct = sub.add_parser("facts")
    fct.add_argument("--repo-root", required=True)
    fct.add_argument("--manifest", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return 2 if error.code else 0
    handlers = {"generate": cmd_generate, "check": cmd_check, "facts": cmd_facts}
    if args.command not in handlers:
        parser.print_usage()
        return 2
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
