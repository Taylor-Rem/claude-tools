#!/usr/bin/env python3
"""A stand-in for client-leads/scripts/reach.py in prep's tests (LEADS_REACH_PY), so they don't depend on the
census branch being checked out. Two halves, the same two `leads` uses:

  imported   `place_evidence(text, *, name, city, phone, site, where)`: a small version of the real check. The
             business's name is taken out first; Utah / UT, the city as a word, or the listing phone's ten digits
             tie it ('high'); another state's code after a comma with no tie is 'rejected'; nothing is 'low'.
  run        `--verdict PLACE_ID FIELD VERDICT WHY --by TAG [--value V] --db DB`: appends its argv as one JSON
             line to REACH_STUB_LOG and prints the line the real one prints. A field named in REACH_STUB_REFUSE
             (comma-separated) is refused the way the real one refuses a missing candidate: exit 2, stderr.
"""
import json
import os
import re
import sys


def place_evidence(text, *, name, city, phone=None, site=None, where="the text"):
    t = text or ""
    if name:
        t = re.sub(re.escape(name), " ", t, flags=re.I)
    if re.search(r"\bUtah\b", t) or re.search(r"\bUT\b", t):
        return "high", f"names Utah ({where})"
    if city and re.search(r"\b" + re.escape(city) + r"\b", t, re.I):
        return "high", f"names {city} ({where})"
    digits = re.sub(r"\D", "", phone or "")[-10:]
    if len(digits) == 10 and digits in re.sub(r"\D", "", t):
        return "high", f"the listing phone ({where})"
    m = re.search(r",\s*([A-Z]{2})\b", t)
    if m:
        return "rejected", f"another state: \"{m.group(0).strip(', ')}\" ({where})"
    return "low", f"nothing ties it to the place ({where})"


def main(argv):
    log = os.environ.get("REACH_STUB_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps(argv) + "\n")
    if argv[:1] != ["--verdict"] or len(argv) < 5:
        print("reach stub: --verdict only", file=sys.stderr)
        return 2
    pid, field, verdict, why = argv[1:5]
    if field in (os.environ.get("REACH_STUB_REFUSE") or "").split(","):
        print(f"--verdict refused: {pid} has no {field} candidate stored", file=sys.stderr)
        return 2
    by = argv[argv.index("--by") + 1] if "--by" in argv else "?"
    conf = "rejected" if verdict == "not_theirs" else "unsure"
    print(f"{pid} {field}: {conf} — {why} (by {by}); out of its column")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
