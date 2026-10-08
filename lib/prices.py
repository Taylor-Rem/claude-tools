"""Patchlamp's prices as the toolbelt says them, and the hash Taylor's approval of a letter is kept against.

One place for the numbers `outreach` and `leads` both put in front of a lead, so a price change is one
edit here, and so `leads` reads a letter's approval exactly the way `outreach send` checks it.

The numbers are the ones on patchlamp.com/pricing (patchlamp/CLAIMS.md, `Prices::TIERS` in the app,
`relay/tiers.py` in the relay); change them only with a CLAIMS.md row in hand, and together with those.
Hosting is $20 a month since 2026-10-05 (B115; it was $10 from 2026-09-24).
"""
import hashlib

HOSTING_PRICE = "$20"
LIGHT_PRICE = "$50"            # the small plan a club or a price list starts on (`leads` ladder and objections)
STARTER_PRICE = "$99"          # the plan the close quotes ("someone on the hook")
PRICE_LINE = f"{HOSTING_PRICE} a month, no contract"
PRICES_LINE = (f"The full range is {HOSTING_PRICE}, $50, $99, $250, $400 and $1,000 a month as the amount of work "
               "goes up; all six are on the pricing page.")

# A letter that says `{price_line}` or `{prices_line}` is approved together with the sentence it puts there:
# Taylor read the price as part of the letter, so a new price un-approves it the same way an edit does.
_PRICED = (("price_line", PRICE_LINE), ("prices_line", PRICES_LINE))


def letter_sha(raw):
    """sha256 of a template's text, plus the price sentences it uses. A letter with neither hashes as its text alone."""
    used = [f"{key}={value}" for key, value in _PRICED if "{" + key + "}" in raw]
    return hashlib.sha256("\n".join([raw, *used]).encode()).hexdigest()
