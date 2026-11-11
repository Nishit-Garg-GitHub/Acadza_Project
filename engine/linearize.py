"""HTML + MathML -> compact plain text, for prompts and for deterministic checks.

The LLM never sees raw production HTML: it is ~5x the tokens and models misread
nested <mrow>/<msub>. We linearise MathML to a calculator-style string
(a/b, x^2, sqrt(...), x_1) and strip styling spans.
"""
import html
import re
from html.parser import HTMLParser

ENT = re.compile(r"&#x([0-9a-fA-F]+);")


class _Node:
    __slots__ = ("tag", "attrs", "kids", "text")

    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.kids, self.text = tag, dict(attrs or []), [], ""


class _Tree(HTMLParser):
    VOID = {"br", "img", "hr", "input", "meta", "mspace", "none", "mprescripts"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = _Node(tag, attrs)
        self.stack[-1].kids.append(n)
        if tag not in self.VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        # tolerant close: pop to the nearest matching open tag (production HTML is unbalanced)
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        t = _Node("#text")
        t.text = data
        self.stack[-1].kids.append(t)


def _wrap(s):
    s = s.strip()
    if re.fullmatch(r"[\w.]+", s) or (s.startswith("(") and s.endswith(")") and s.count("(") == 1):
        return s
    return f"({s})"


def _m(n):
    """MathML node -> text"""
    if n.tag == "#text":
        return n.text.replace(" ", " ").replace("⁡", "").replace("⁢", "")
    k = [c for c in n.kids if not (c.tag == "#text" and not c.text.strip())]
    sub = [_m(c) for c in k]
    t = n.tag
    if t == "mfrac":
        return f"{_wrap(sub[0])}/{_wrap(sub[1])}" if len(sub) == 2 else "".join(sub)
    if t == "msup":
        return f"{sub[0]}^{_wrap(sub[1])}" if len(sub) == 2 else "".join(sub)
    if t == "msub":
        return f"{sub[0]}_{_wrap(sub[1])}" if len(sub) == 2 else "".join(sub)
    if t == "msubsup":
        return f"{sub[0]}_{_wrap(sub[1])}^{_wrap(sub[2])}" if len(sub) == 3 else "".join(sub)
    if t == "msqrt":
        return f"sqrt({''.join(sub)})"
    if t == "mroot":
        return f"root{_wrap(sub[1])}({sub[0]})" if len(sub) == 2 else "".join(sub)
    if t in ("munder", "mover", "munderover"):
        return " ".join(sub)
    if t == "mtable":
        return "[" + "; ".join(sub) + "]"
    if t == "mtr":
        return ", ".join(sub)
    if t == "mfenced":
        o, c = n.attrs.get("open", "("), n.attrs.get("close", ")")
        return o + ", ".join(sub) + c
    if t == "mo":
        s = "".join(sub).strip()
        return {"×": "×", "−": "-", "⋅": "·"}.get(s, s)
    return "".join(sub)


BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "tr", "br", "table"}


def _h(n, out):
    if n.tag == "#text":
        out.append(n.text)
        return
    if n.tag == "math":
        out.append(" " + re.sub(r"\s+", " ", _m(n)).strip() + " ")
        return
    if n.tag == "img":
        out.append(f" [IMAGE {n.attrs.get('src','')[:80]}] ")
        return
    if n.tag in BLOCK:
        out.append("\n")
    for c in n.kids:
        _h(c, out)
    if n.tag in BLOCK:
        out.append("\n")


def linearize(s: str) -> str:
    if not s:
        return ""
    p = _Tree()
    p.feed(s)
    out = []
    _h(p.root, out)
    txt = "".join(out).replace(" ", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r" *\n *", "\n", txt)
    txt = re.sub(r"\n{2,}", "\n", txt)
    return txt.strip()


def plain(s: str) -> str:
    """Visible text with all tags removed (no math linearisation) - for find/replace sanity checks."""
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))
