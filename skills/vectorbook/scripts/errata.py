"""Guarantee that erratum markup never changes the author's content.

Usage: py errata.py snapshot pages/pNNN   before any erratum is added (saves body.pre-errata.tex)
       py errata.py check pages/pNNN      after: body with \\vberrnote{...} removed and \\vberr{X}
                                          unwrapped to X must equal the snapshot exactly
"""
import sys
from pathlib import Path


def braced(s: str, i: int) -> int:
    """Index after the balanced {...} group that starts at s[i] == '{'."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("unbalanced braces after position %d" % i)


def strip(s: str) -> str:
    for cmd, keep in (("\\vberrnote", False), ("\\vberr", True)):
        while True:
            i = s.find(cmd + "{")
            if i < 0:
                break
            j = braced(s, i + len(cmd))
            s = s[:i] + (s[i + len(cmd) + 1:j - 1] if keep else "") + s[j:]
    return s


def main() -> int:
    mode, d = sys.argv[1], Path(sys.argv[2])
    body, snap = d / "body.tex", d / "body.pre-errata.tex"
    if mode == "snapshot":
        snap.write_text(body.read_text(encoding="utf-8"), encoding="utf-8")
        print("snapshot", snap)
        return 0
    same = strip(body.read_text(encoding="utf-8")).strip() == snap.read_text(encoding="utf-8").strip()
    n = body.read_text(encoding="utf-8").count("\\vberrnote{")
    print(("OK" if same else "FAIL: errata markup changed the original text") + f" ({n} errata) {d.name}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
