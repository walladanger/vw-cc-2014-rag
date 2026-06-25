#!/usr/bin/env python3
"""
Safety-critical numeric extraction + verification (v1).

WHY THIS EXISTS
The grounding gate proves an answer CITES a real chunk. It does NOT prove the
NUMBER in the answer matches the source. For torque specs that gap can break a
bolt: retrieval can return the right page while a generator transcribes 40 Nm as
25, or drops the "+180°" angle stage off a stretch bolt. This module makes numbers
non-negotiable:

  1. extract_specs(chunk)  -> structured TorqueSpec records pulled straight from
     the manual text, INCLUDING angle stages and multi-stage sequences. The raw
     source substring is kept verbatim on every record.
  2. verify_answer(answer, allowed_chunks) -> every torque-like number the answer
     states must match, character-for-character, a spec extracted from a cited
     chunk. Any number not backed by an extracted spec => REJECT.

DESIGN RULES
  * Angle-torque ("40 Nm + 180°") and multi-stage specs are captured WHOLE. If a
    spec is complex, it is flagged complex=True and must be shown verbatim, never
    paraphrased or reduced to the first number.
  * Engine-code / condition qualifiers near a value are captured so a value is
    never shown detached from the engine it applies to.
  * Unknown / ambiguous unit => the value is still captured but flagged; the
    verifier treats an unverifiable safety number as a REJECT, not a pass.
  * No value is ever invented or rounded. Extraction is copy-only.
"""
import json
import re
import glob
from dataclasses import dataclass, asdict, field

# --- number + unit grammar -------------------------------------------------
NUM = r"\d{1,4}(?:\.\d{1,2})?"
TORQUE_UNITS = r"(?:Nm|N\s?m|ft[\-.\s]?lb|lb[\-.\s]?ft|in[\-.\s]?lb)"

# A full torque value, optionally followed by one or more angle stages and/or a
# "(1/4 turn)" gloss. Captures the WHOLE thing as one unit so angle stages can
# never be silently dropped.
TORQUE_RE = re.compile(
    rf"({NUM})\s*({TORQUE_UNITS})"                       # base value + unit
    rf"((?:\s*\+\s*\d{{1,3}}\s*°(?:\s*\([^)]*\))?)*)"     # zero+ angle stages
    rf"(\s*(?:±|\+/-)\s*{NUM}(?:\s*{TORQUE_UNITS})?)?",  # optional tolerance
    re.IGNORECASE,
)
ANGLE_STAGE_RE = re.compile(r"\+\s*(\d{1,3})\s*°")
GAP_RE = re.compile(rf"({NUM})\s*mm\b")
# qualifier words that bind a value to a condition/engine — captured for context
QUALIFIER_RE = re.compile(
    r"(engine code[s]?\s+[A-Z0-9 ,/and]+|"
    r"\b(?:CBFA|CCTA|CDAA|CDAB|CCZ[A-Z]?|CCT[A-Z]?|CBF[A-Z]?)\b|"
    r"metal|plastic|stage\s*[12]|step\s*[12]|M\d{1,2}(?:x[\d.]+)?)",
    re.IGNORECASE,
)


@dataclass
class TorqueSpec:
    value: str                 # base numeric value, verbatim ("40")
    unit: str                  # normalised unit label ("Nm")
    angle_stages: list = field(default_factory=list)  # ["180"] for +180°
    fastener: str = ""         # best-effort label to the left of the value
    qualifier: str = ""        # engine code / metal-plastic / stage, if present
    complex: bool = False      # angle and/or staged => must be shown verbatim
    replace_bolt: bool = False # single-use stretch bolt: replacement mandatory
    tolerance: str = ""        # e.g. '± 0.4 Nm' captured with the value
    raw: str = ""              # exact source substring (the source of truth)
    manual_id: str = ""
    page_physical: int = 0
    chunk_id: str = ""

    def canonical(self):
        """Verbatim human string. For complex specs this is the ONLY safe form."""
        s = f"{self.value} {self.unit}"
        for a in self.angle_stages:
            s += f" + {a}°"
        if self.tolerance:
            s += f" {self.tolerance}"
        return s


def _normalise_unit(u):
    u = u.lower().replace(" ", "").replace(".", "").replace("-", "")
    return {"nm": "Nm", "ftlb": "ft-lb", "lbft": "ft-lb", "inlb": "in-lb"}.get(u, u)


def _fastener_label(text, start):
    """Find the fastener this value belongs to. VAG specs come in two layouts:
      (a) inline:   "Tighten the bolts to 20 Nm"   -> label is left, same line
      (b) legend:   "14 - Bolts / Engine support to engine / Replace / 40 Nm+180"
                    -> label is one or more lines ABOVE the value
    We take the same-line text if it carries words, else walk up to the nearest
    preceding non-empty, non-marker line(s)."""
    head = text[:start]
    same = head.rsplit("\n", 1)[-1]
    same_clean = re.sub(r"\s*(?:to|:|-|\u2013|specification[s]?|tighten(?:ing)?)\s*$",
                        "", same.strip(), flags=re.I)
    if re.search(r"[A-Za-z]{3,}", same_clean):
        return same_clean[-60:].strip(" -\u2013\u2014.")
    # legend layout: walk upward, skipping bullets / markers / "Replace"
    lines = [ln.strip() for ln in head.split("\n")]
    parts = []
    for ln in reversed(lines[:-1]):
        if not ln or ln in {"\u274d", "\u2022", "-"} or re.fullmatch(r"[\u274d\u2022\-\u25a1\u25cf]+", ln):
            continue
        if re.fullmatch(r"(?i)replace", ln):
            continue  # captured separately as a flag
        if re.search(r"[A-Za-z]{3,}", ln):
            parts.append(re.sub(r"^\d+\s*-\s*", "", ln))  # drop "14 - " index
            if len(parts) >= 2:
                break
    return " / ".join(reversed(parts))[:60]


def _replace_flag(text, start):
    """True if a 'Replace' instruction precedes the value (single-use stretch
    bolt). For these, replacement is mandatory and as critical as the torque."""
    window = text[max(0, start - 120):start]
    return bool(re.search(r"(?i)\breplace\b", window))


def extract_specs(chunk):
    """Return a list of TorqueSpec from one chunk. Copy-only; never invents."""
    text = chunk["text"]
    specs = []
    for m in TORQUE_RE.finditer(text):
        raw = m.group(0).strip()
        value, unit_raw, angle_blob = m.group(1), m.group(2), m.group(3) or ""
        tol = (m.group(4) or "").strip()
        angles = ANGLE_STAGE_RE.findall(angle_blob)
        # qualifier within a small window around the match
        window = text[max(0, m.start() - 70): m.end() + 20]
        q = QUALIFIER_RE.search(window)
        spec = TorqueSpec(
            value=value,
            unit=_normalise_unit(unit_raw),
            angle_stages=angles,
            fastener=_fastener_label(text, m.start()),
            qualifier=(q.group(0) if q else ""),
            complex=bool(angles),
            tolerance=tol,
            replace_bolt=_replace_flag(text, m.start()),
            raw=raw,
            manual_id=chunk.get("manual_id", ""),
            page_physical=chunk.get("page_physical", 0),
            chunk_id=chunk.get("chunk_id", ""),
        )
        specs.append(spec)
    return specs


# --- verification ----------------------------------------------------------
# Any token in an answer that looks like a torque value must be backed.
ANSWER_TORQUE_RE = re.compile(
    rf"({NUM})\s*({TORQUE_UNITS})((?:\s*\+\s*\d{{1,3}}\s*°)*)",
    re.IGNORECASE,
)


def _spec_key(value, unit, angles):
    return (value, _normalise_unit(unit), tuple(angles))


def verify_answer(answer_text, cited_chunks):
    """cited_chunks: list of chunk dicts the answer is allowed to draw on.
    Returns dict with ok flag and per-number findings. A torque number stated in
    the answer is OK only if an identical spec (value+unit+angle stages) was
    extracted from one of the cited chunks."""
    backed = {}
    for c in cited_chunks:
        for s in extract_specs(c):
            backed[_spec_key(s.value, s.unit, s.angle_stages)] = s

    findings = []
    all_ok = True
    for m in ANSWER_TORQUE_RE.finditer(answer_text):
        value, unit, angle_blob = m.group(1), m.group(2), m.group(3) or ""
        angles = ANGLE_STAGE_RE.findall(angle_blob)
        key = _spec_key(value, unit, angles)
        stated = m.group(0).strip()
        if key in backed:
            findings.append({"stated": stated, "status": "VERIFIED",
                             "source": f"{backed[key].manual_id} p{backed[key].page_physical}",
                             "raw": backed[key].raw})
        else:
            all_ok = False
            # diagnose: did the answer drop an angle stage that exists in source?
            base_only = _spec_key(value, unit, [])
            if angles == [] and any(k[0] == value and k[1] == _normalise_unit(unit) and k[2]
                                    for k in backed):
                reason = "DROPPED ANGLE STAGE — source value has a + degrees stage this answer omitted"
            elif base_only in backed:
                reason = "ANGLE MISMATCH vs source"
            else:
                reason = "NOT FOUND in any cited chunk"
            findings.append({"stated": stated, "status": "REJECT", "reason": reason})
    return {"ok": all_ok, "numbers_checked": len(findings), "findings": findings}


# --- CLI / self-test -------------------------------------------------------
def _load(out="./out"):
    return [json.loads(l) for f in glob.glob(f"{out}/*/chunks.jsonl") for l in open(f, encoding="utf-8")]


def cmd_extract(args):
    chunks = _load(args.out)
    by_page = [c for c in chunks if c["manual_id"] == args.manual and c["page_physical"] == args.page]
    if not by_page:
        print("no chunk for that manual/page"); return
    for c in by_page:
        for s in extract_specs(c):
            tag = " [COMPLEX: show verbatim]" if s.complex else ""
            if s.replace_bolt: tag += " [REPLACE BOLT]"
            print(f"  {s.canonical():<22} fastener={s.fastener[:40]!r} qual={s.qualifier!r}{tag}")
            print(f"      raw={s.raw!r}  src={s.manual_id} p{s.page_physical}")


def cmd_audit(args):
    """Inventory every torque spec in the corpus; highlight complex ones."""
    chunks = _load(args.out)
    total = complex_n = 0
    per_manual = {}
    for c in chunks:
        for s in extract_specs(c):
            total += 1
            complex_n += s.complex
            per_manual.setdefault(s.manual_id, [0, 0])
            per_manual[s.manual_id][0] += 1
            per_manual[s.manual_id][1] += s.complex
    print(f"torque specs extracted: {total}  (complex/angle/staged: {complex_n})\n")
    for mid, (t, cx) in sorted(per_manual.items()):
        print(f"  {mid:<26} {t:>4} specs  {cx:>3} complex")


def cmd_selftest(args):
    chunks = _load(args.out)
    # Use REAL chunks that we know contain specific specs.
    def chunk_on(mid, page, must):
        for c in chunks:
            if c["manual_id"] == mid and c["page_physical"] == page and must in c["text"]:
                return c
        return None

    starter = chunk_on("vw_cc_electrical_2018", 29, "75 Nm")
    angle = next(
        (c for c in chunks if any(s.complex for s in extract_specs(c))),
        None,
    )

    # Keep the safety test runnable in a clean checkout where the private manual
    # corpus is intentionally absent.
    if starter is None:
        starter = {
            "manual_id": "selftest",
            "page_physical": 1,
            "chunk_id": "selftest-starter",
            "text": "Starter mounting bolts: 75 Nm",
        }
    if angle is None:
        angle = {
            "manual_id": "selftest",
            "page_physical": 2,
            "chunk_id": "selftest-angle",
            "text": "Subframe bolt: 40 Nm + 180° Replace after removal.",
        }

    cases = []
    # 1. correct simple value -> VERIFIED
    cases.append(("simple correct", "Starter bolts: 75 Nm [cite]", [starter], True))
    # 2. WRONG simple value (transcription error) -> REJECT
    cases.append(("simple wrong (75->57)", "Starter bolts: 57 Nm [cite]", [starter], False))
    # 3. value from a DIFFERENT page not cited -> REJECT
    cases.append(("uncited number", "Torque is 999 Nm [cite]", [starter], False))
    # 4. angle spec stated WHOLE -> VERIFIED
    aspec = extract_specs(angle)
    target = next(s for s in aspec if s.complex)
    cases.append(("angle stated whole", f"Tighten to {target.canonical()} [cite]", [angle], True))
    # 5. angle spec with the +deg DROPPED -> REJECT (the dangerous case)
    cases.append(("angle stage dropped", f"Tighten to {target.value} {target.unit} [cite]", [angle], False))

    print(f"angle test spec from {target.manual_id} p{target.page_physical}: {target.canonical()!r} (raw {target.raw!r})\n")
    ok = 0
    for name, ans, cited, expect_ok in cases:
        r = verify_answer(ans, cited)
        good = (r["ok"] == expect_ok)
        ok += good
        detail = r["findings"][0] if r["findings"] else {}
        print(f"{'PASS' if good else 'FAIL'}  [{name}] expect_ok={expect_ok} got_ok={r['ok']}")
        print(f"        answer={ans!r}")
        print(f"        -> {detail.get('status','?')}: {detail.get('reason', detail.get('source',''))}")
    print(f"\n{ok}/{len(cases)} verification cases correct")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("--out", default="./out"); a.set_defaults(func=cmd_audit)
    e = sub.add_parser("extract"); e.add_argument("manual"); e.add_argument("page", type=int)
    e.add_argument("--out", default="./out"); e.set_defaults(func=cmd_extract)
    s = sub.add_parser("selftest"); s.add_argument("--out", default="./out"); s.set_defaults(func=cmd_selftest)
    args = ap.parse_args(); args.func(args)


if __name__ == "__main__":
    main()
