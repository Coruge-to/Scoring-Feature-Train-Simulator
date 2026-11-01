"""TB-F Stage 1 - scenario file line-grammar GUARD (test equipment only; NOT product code and NOT part of the TScoring repository).

Why: the first live load of the TB-G scenario failed with 'invalid key' warnings because the Author value had been split into five one-character lines by a generator bug (PowerShell: the comma
bound tighter than +). The static route checks had no line grammar. This module is that missing check. It is deliberately strict and structural:

  SG-01 line count equals the reference scenario's                    SG-07 no stray line (every line after the blank is a single 'Key = value')
  SG-02 header: 'Bvets Scenario 2.00' then one blank line              SG-08 structure equals the reference (separator, fixed-value keys Image / Vehicle / VehicleTitle)
  SG-03 every other line is one 'Key = value' record                   SG-09 Route and Vehicle resolve to existing files
  SG-04 only the 8 allowed keys, each exactly once                     SG-10 UTF-8 with BOM, strict decoding, CRLF only, final CRLF, no NUL / U+FFFD
  SG-05 key order equals the reference's                               SG-11 the SHA-256 is the declared live canonical one
  SG-06 Author is exactly one line, equal to the reference's Author    SG-12 the SHA-256 is none of the forbidden (superseded) ones
"""
import hashlib
import os
import re

ALLOWED_KEYS = ("Title", "Author", "Image", "Route", "RouteTitle", "Vehicle", "VehicleTitle", "Comment")
KEY_LINE = re.compile(r"^([A-Za-z]+) = (.*)$")
HEADER = "Bvets Scenario 2.00"
FIXED_VALUE_KEYS = ("Image", "Vehicle", "VehicleTitle")
CJK = re.compile(r"[　-ヿ㐀-鿿＀-￯]")
SHA_LIVE_SCENARIO = "4FFA382733F9E63387F538D624999763894980A44F369745515E2E2C8E95A549"
SHA_SUPERSEDED_SCENARIO = "F021734C3148FF9DB6432D6535C836FD163C0401784D52C1220C08E946C4441F"


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest().upper()


def _decode(raw):
    """Returns (text or None, findings). Only the byte contract (SG-10) is judged here."""
    findings = []
    if raw[:3] != b"\xef\xbb\xbf":
        findings.append(("SG-10", "no UTF-8 BOM"))
        body = raw
    else:
        body = raw[3:]
    if b"\x00" in raw:
        findings.append(("SG-10", "NUL byte"))
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(("SG-10", "not strict UTF-8: %s" % exc))
        return None, findings
    if "�" in text:
        findings.append(("SG-10", "U+FFFD replacement character"))
    if re.search(r"(?<!\r)\n", text):
        findings.append(("SG-10", "bare LF"))
    if re.search(r"\r(?!\n)", text):
        findings.append(("SG-10", "bare CR"))
    if not text.endswith("\r\n"):
        findings.append(("SG-10", "no final CRLF"))
    elif text.endswith("\r\n\r\n"):
        findings.append(("SG-10", "extra blank line at the end"))
    return text, findings


def _lines(text):
    return text[:-2].split("\r\n") if text.endswith("\r\n") else text.split("\r\n")


def parse_keys(lines):
    return [(KEY_LINE.match(l).group(1), KEY_LINE.match(l).group(2)) for l in lines[2:] if KEY_LINE.match(l)]


def check_scenario_bytes(raw, reference_raw, scenarios_root=None, expected_sha=None, forbidden_shas=()):
    """Returns the list of (check id, message). Empty list = the scenario passes every check."""
    findings = []
    text, f = _decode(raw)
    findings.extend(f)
    ref_text, ref_f = _decode(reference_raw)
    if ref_f or ref_text is None:
        findings.append(("SG-00", "the reference scenario itself is not clean: %r" % (ref_f,)))
        return findings
    ref_lines = _lines(ref_text)
    ref_keys = parse_keys(ref_lines)
    digest = sha256_bytes(raw)
    if expected_sha is not None and digest != expected_sha.upper():
        findings.append(("SG-11", "SHA-256 %s is not the declared canonical %s" % (digest, expected_sha.upper())))
    if digest in {s.upper() for s in forbidden_shas}:
        findings.append(("SG-12", "SHA-256 %s is a superseded (forbidden) scenario" % digest))
    if text is None:
        return findings
    lines = _lines(text)
    if len(lines) != len(ref_lines):
        findings.append(("SG-01", "line count %d, reference has %d" % (len(lines), len(ref_lines))))
    if len(lines) < 2 or lines[0] != HEADER or lines[1] != "":
        findings.append(("SG-02", "header is not %r + one blank line" % HEADER))
    stray = [(i + 1, l) for i, l in enumerate(lines[2:], start=2) if not KEY_LINE.match(l)]
    for number, content in stray:
        kind = "an invalid single CJK line" if CJK.search(content) and "=" not in content else "a stray line"
        findings.append(("SG-07", "line %d is %s: %r" % (number, kind, content)))
        findings.append(("SG-03", "line %d is not one 'Key = value' record" % number))
    keys = parse_keys(lines)
    names = [k for k, _ in keys]
    unknown = [k for k in names if k not in ALLOWED_KEYS]
    if unknown:
        findings.append(("SG-04", "unknown key(s): %s" % ", ".join(unknown)))
    for k in ALLOWED_KEYS:
        if names.count(k) != 1:
            findings.append(("SG-04", "key %s appears %d times (must be exactly once)" % (k, names.count(k))))
    if [k for k in names if k in ALLOWED_KEYS] and names != [k for k, _ in ref_keys]:
        findings.append(("SG-05", "key order %s differs from the reference %s" % (names, [k for k, _ in ref_keys])))
    author_values = [v for k, v in keys if k == "Author"]
    ref_author = [v for k, v in ref_keys if k == "Author"]
    if len(author_values) != 1:
        findings.append(("SG-06", "Author appears %d times" % len(author_values)))
    elif not author_values[0].strip():
        findings.append(("SG-06", "Author is empty"))
    elif ref_author and author_values[0] != ref_author[0]:
        findings.append(("SG-06", "Author value %r differs from the reference's %r (possible character-split)" % (author_values[0], ref_author[0])))
    values = dict(keys)
    ref_values = dict(ref_keys)
    for k in FIXED_VALUE_KEYS:
        if k in values and values[k] != ref_values.get(k):
            findings.append(("SG-08", "fixed-value key %s is %r, the reference has %r" % (k, values[k], ref_values.get(k))))
    for number, content in enumerate(lines[2:], start=3):
        m = KEY_LINE.match(content)
        if m is None and content.strip() and "=" in content:
            findings.append(("SG-08", "line %d uses a separator other than ' = ': %r" % (number, content)))
    if scenarios_root is not None:
        for k in ("Route", "Vehicle"):
            if k in values:
                resolved = os.path.join(scenarios_root, values[k].replace("\\", os.sep))
                if not os.path.isfile(resolved):
                    findings.append(("SG-09", "%s %r does not resolve to a file under %s" % (k, values[k], scenarios_root)))
    return findings


def check_scenario(path, reference_path, scenarios_root=None, expected_sha=None, forbidden_shas=()):
    with open(path, "rb") as fh:
        raw = fh.read()
    with open(reference_path, "rb") as fh:
        reference = fh.read()
    return check_scenario_bytes(raw, reference, scenarios_root, expected_sha, forbidden_shas)


SIZE_SUPERSEDED_SCENARIO = 449


def scan_for_forbidden_sha(root, forbidden_shas, sizes=(SIZE_SUPERSEDED_SCENARIO,)):
    """Every file below `root` whose SHA-256 is one of the forbidden (superseded) ones. Only files of the forbidden size(s) are hashed (a SHA match implies the size match; the live
    Scenarios folder holds third-party assets of many megabytes that cannot be the scenario). sizes=None hashes everything."""
    bad = {s.upper() for s in forbidden_shas}
    hits = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(folder, name)
            try:
                if sizes is not None and os.path.getsize(full) not in sizes:
                    continue
                with open(full, "rb") as fh:
                    if sha256_bytes(fh.read()) in bad:
                        hits.append(full)
            except OSError:
                continue
    return hits


if __name__ == "__main__":
    import sys
    scenarios = sys.argv[1]
    target = os.path.join(scenarios, "iida_sanmpe_tbg_pt4_v1.txt")
    reference = os.path.join(scenarios, "iida_sanmpe_b3zero_v1.txt")
    problems = check_scenario(target, reference, scenarios, SHA_LIVE_SCENARIO, (SHA_SUPERSEDED_SCENARIO,))
    for check_id, message in problems:
        print("%s\t%s" % (check_id, message))
    print("SCENARIO SYNTAX GUARD: %s (%d findings)" % ("PASS" if not problems else "FAIL", len(problems)))
    sys.exit(1 if problems else 0)
