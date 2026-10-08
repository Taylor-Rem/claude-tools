"""Patchlamp's propositions: why we would write to a business, and the true things the letter says (ROADMAP B135).

Plan ~/projects/plans/55-autonomous-acquisition.md § 1.1 (the six and their counts), § 5.2 (rules 3 and 6), § 5.6
(E1), § 5.12 (this file is the venture's, the engine calls it through lib/venture.py `propositions()`);
VISION § Decided "Autonomous acquisition" #4 and #13 (Taylor, 2026-10-07: "the current qualification rule is one
campaign hypothesis, not the addressable pool").

The engine (`leads batch`) hands `classify` one prospect: the stored facts of one business, each from the census
with its source, and nothing a model wrote. What comes back decides which letter set it may get, and `letter`
picks the sentences that letter says. Nothing here reads the network, a file or the clock.

    P1  visibly faulted: the rule as it was (two true specifics, one a fault). Its letters carry the faults packet
        the engine computes (batch-first / -second / -third), so its rule stays in one place.
    P3  agency-hosted: the site is on an agency's platform (Hibu, Thryv, Duda, a named local agency).
    P4  self-built on a builder (Wix, Squarespace, GoDaddy, Weebly, Webflow, Showit, Shopify and the like).
    P5  an own site with no fault found: the hardest letter to write well, because it isn't about a problem.
    P6  AI-curious, stopped by the setup: not detectable from stored facts, so it is a frame dealt against P5 on
        P5's own pool, half and half by a hash of the place id (experiment E1). Prior AI use is never a
        requirement (Taylor, 2026-10-07), and P6 is never defined by a fingerprint (#13): the tooling signals the
        census stores (a field-service generator, a booking or chat widget, online payments) reach this file in
        `prospect["signals"]` and are read by nothing below, until outcomes show one predicts.
    P2  no independent site of their own (none, a Facebook page, a dead link, a directory): the card's (B54).
    P0  none: excluded (a chain, held, a client, suppressed, closed), or nothing true to say beside a fault.

Order, when more than one is true: P0, then P2 (no independent site is the card's, whatever the listing's faults:
plan 55 § 1.1; Flint, 2026-10-08, B140), then P1 (a fault the owner can check is the strongest specific there is,
its letters are already approved, and it is the rule `leads batch` ran before B135), then P3, P4, P5. P1 overlaps
P3-P5 in the plan's counts, never P2; here a business gets one.

Why the letter facts are these: each is a stored fact with a source a stranger could check (their Google standing,
how Google lists them, the phone on their site matching the listing, the site loading securely and fitting a phone,
the copyright line being current), and each says something true and in their favour. None is a judgement, none is
invented, and a business with too few of them for its letter isn't written to.
"""

import hashlib
import re

# A vendor's name that carries a domain ("Network Solutions (Web.com)") would put a link in a first letter, and the
# first letter carries none (plan 37 § 3): that business isn't written to under P3/P4.
DOMAIN_RE = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|co|io|ai|dev|app|us|design|me)\b", re.I)

PROPOSITIONS = {
    "P1": {"label": "visibly faulted", "lane": "email", "packet": "faults",
           "letters": ("batch-first", "batch-second", "batch-third"), "slots": (), "ai_test": True},
    "P3": {"label": "agency-hosted", "lane": "email", "packet": "slots",
           "letters": ("p3-first", "p3-second", "p3-third"), "slots": ("host_vendor", "fact"), "ai_test": True},
    "P4": {"label": "self-built on a builder", "lane": "email", "packet": "slots",
           "letters": ("p4-first", "p4-second", "p4-third"), "slots": ("builder", "fact"), "ai_test": True},
    "P5": {"label": "own site, no fault found", "lane": "email", "packet": "slots",
           "letters": ("p5-first", "p5-second", "p5-third"), "slots": ("fact_one", "fact_two"), "ai_test": False},
    "P6": {"label": "AI-curious, stopped by the setup (dealt from P5's pool)", "lane": "email", "packet": "slots",
           "letters": ("p6-first", "p6-second", "p6-third"), "slots": ("fact_one", "fact_two"), "ai_test": False},
    "P2": {"label": "no independent site (the card's, B54)", "lane": "card", "packet": None, "letters": None,
           "slots": (), "ai_test": False},
    "P0": {"label": "none", "lane": None, "packet": None, "letters": None, "slots": (), "ai_test": False},
}

# E1, registered in B142's shape (plan 55 § 5.6) from the first day; B142 moves it into experiments.json. The AI-line
# test (E2) runs on the chore lanes only, so P5 and P6 letters carry the AI sentence beside the introduction
# (`ai_test: False` above), and nothing else varies between the two arms.
EXPERIMENTS = {
    "E1": {"id": "E1", "name": "the frame", "population": "P5", "varied": "the proposition's frame",
           "arms": ("P5", "P6"), "deal": "sha256('E1:' + place_id), first 8 hex digits, mod 2: 0 is P5, 1 is P6",
           "held_at_default": "the AI sentence beside the introduction; the close arm as E3 assigns",
           "primary_endpoint": "positive reply", "floor_delivered": 100,
           "kill_rule": "an arm with 200 delivered and a positive-reply rate under half the other's is paused",
           "decision_owner": "Taylor", "registered": "2026-10-08"},
}

NO_SITE = ("none", "page", "dead", "directory")        # businesses.presence_class: nothing of their own to look at
# The host check said the site isn't answering: a letter about "your site" would be about a site that's down.
HOST_DOWN = ("404", "410", "nodns", "parked", "expired", "timeout", "refused", "tls", "error", "500", "502", "503",
             "521", "522", "525")
AGENCY_BUILDERS = ("duda",)        # sold white-label through agencies: the owner didn't build it on Duda themselves
# Builders an owner signs up for and builds on alone, so "you built it yourself on X" is likely true. Not here:
# CivicPlus, Sport Ngin, FaithConnector (an organisation's platform), Jobber (Jobber makes the site), the photo
# hosts' galleries, Netlify (a developer's host); those businesses go to P5 when their site is fine.
SELF_BUILT = ("wix", "squarespace", "godaddy", "weebly", "webflow", "showit", "shopify", "square-online", "hostinger",
              "framer", "jimdo", "strikingly", "carrd", "durable", "b12")
# The facts a letter may say, best first (each the engine's key; the sentence and its source come with it).
FACT_ORDER = ("google_standing", "listed_as", "phone_matches", "secure_mobile", "site_current")


def classify(p):
    """One prospect -> a proposition id. `p` is the engine's dict (bin/leads `prospect_of`)."""
    if p.get("excluded"):
        return "P0"
    if p.get("presence") in NO_SITE:      # no site of their own: the card's, whatever the listing's faults (§ 1.1)
        return "P2"
    if p.get("packet"):
        return "P1"
    host = p.get("host") or {}
    if str(host.get("status") or "") in HOST_DOWN:
        return "P0"
    vendor, kind, says = host.get("vendor") or "", host.get("kind") or "", host.get("says") or ""
    if says and (kind == "agency" or vendor in AGENCY_BUILDERS):
        return "P3"
    if says and vendor in SELF_BUILT:
        return "P4"
    if p.get("own_home") and not p.get("faults"):
        return "P5"
    return "P0"


def arm_of(place_id):
    """E1's arm for one business: stable, so a business is in the same arm in every batch and every count."""
    h = hashlib.sha256(f"E1:{place_id}".encode()).hexdigest()
    return EXPERIMENTS["E1"]["arms"][int(h[:8], 16) % 2]


def deal(place_id, prop):
    """(the proposition its letters are from, experiment id, arm). Only P5's pool is dealt."""
    if prop == "P5":
        arm = arm_of(place_id)
        return arm, "E1", arm
    return prop, None, None


def _facts(p):
    by = {f["key"]: f for f in p.get("facts") or [] if f.get("sentence") and f.get("evidence")}
    return [by[k] for k in FACT_ORDER if k in by]


def letter(prop, p):
    """[{slot, key, sentence, evidence}] for that proposition's letter, or [] when the stored facts can't fill it."""
    facts = _facts(p)
    host = p.get("host") or {}
    if prop in ("P3", "P4"):
        if not facts or not host.get("says") or DOMAIN_RE.search(host["says"]):
            return []
        what = "host_vendor" if prop == "P3" else "builder"
        return [{"slot": what, "key": "host", "sentence": host["says"],
                 "evidence": f"{host.get('url') or ''} ({host.get('why') or 'hosts.vendor ' + str(host.get('vendor'))}, "
                             f"checked {str(host.get('checked') or '')[:10]})".strip()},
                {"slot": "fact", **{k: facts[0][k] for k in ("key", "sentence", "evidence")}}]
    if prop in ("P5", "P6"):
        if len(facts) < 2:
            return []
        return [{"slot": s, **{k: f[k] for k in ("key", "sentence", "evidence")}}
                for s, f in zip(("fact_one", "fact_two"), facts[:2])]
    return []
