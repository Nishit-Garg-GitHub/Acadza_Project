"""Load the production records and give every stage the same normalised view.

Production format: the body lives under q[q.questionType] (scq / mcq / integerQuestion),
options are *inside* the question HTML as "(A) ... (B) ...", answers are a letter, a list
of letters, or a numeric string. Nothing here calls an LLM.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .linearize import linearize

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

OPT_RE = re.compile(r"\(([A-D])\)")


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@dataclass
class Record:
    raw: dict
    id: str
    qtype: str
    subject: str
    chapter: str
    question_html: str
    solution_html: str
    answer: object
    question_text: str
    solution_text: str
    stem: str
    options: dict = field(default_factory=dict)  # letter -> text ('' when blank)
    images: list = field(default_factory=list)

    @property
    def body(self):
        return self.raw[self.qtype]

    def field_value(self, name):
        """Current stored value of an editable field, as a string (answers JSON-encoded unless plain)."""
        if name == "question":
            return self.question_html
        if name == "solution":
            return self.solution_html
        if name == "answer":
            return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        if name == "questionType":
            return self.qtype
        if name in ("chapter", "subject"):
            return self.raw.get(name) or ""
        raise KeyError(name)

    def prompt_view(self, with_key=True, with_solution=True):
        """Compact text block used inside prompts."""
        lines = [f"questionType: {self.qtype}", f"subject/chapter: {self.subject} / {self.chapter}",
                 "STEM:", self.stem or "(empty)"]
        if self.qtype != "integerQuestion":
            lines.append("OPTIONS:")
            for k in "ABCD":
                if k in self.options:
                    lines.append(f"  ({k}) {self.options[k] or '<<BLANK>>'}")
                else:
                    lines.append(f"  ({k}) <<NOT PRESENT IN RECORD>>")
        if self.images:
            lines.append(f"IMAGES: {self.images}")
        else:
            lines.append("IMAGES: none attached")
        if with_key:
            lines.append(f"STORED ANSWER KEY: {json.dumps(self.answer, ensure_ascii=False)}")
        if with_solution:
            lines.append("STORED SOLUTION:")
            lines.append(self.solution_text or "(empty)")
        return "\n".join(lines)


def split_options(text):
    """'stem (A) x (B) y ...' -> (stem, {A: x, B: y})"""
    marks = list(OPT_RE.finditer(text))
    # keep only the first run of A,B,C,D in order (assertion-reason text also contains "(A)")
    seq, expect = [], "A"
    for m in marks:
        if m.group(1) == expect:
            seq.append(m)
            expect = chr(ord(expect) + 1)
        elif m.group(1) == "A":  # restart: a later (A) is the real option list
            seq, expect = [m], "B"
    if not seq:
        return text.strip(), {}
    stem = text[: seq[0].start()].strip()
    opts = {}
    for i, m in enumerate(seq):
        end = seq[i + 1].start() if i + 1 < len(seq) else len(text)
        opts[m.group(1)] = text[m.end():end].strip()
    return stem, opts


def build_record(q):
    t = q["questionType"]
    b = q[t]
    qtext = linearize(b.get("question", ""))
    stem, opts = (qtext, {}) if t == "integerQuestion" else split_options(qtext)
    return Record(
        raw=q, id=q["_id"], qtype=t, subject=q.get("subject") or "", chapter=q.get("chapter") or "",
        question_html=b.get("question", ""), solution_html=b.get("solution", ""), answer=b.get("answer"),
        question_text=qtext, solution_text=linearize(b.get("solution", "")), stem=stem, options=opts,
        images=(b.get("quesImages") or []) + (b.get("solutionImages") or []),
    )


def load_all():
    questions = load_json("questions.json")
    reports = load_json("reports.json")
    taxonomy = load_json("taxonomy.json")
    records = {q["_id"]: build_record(q) for q in questions}
    return records, reports, taxonomy
