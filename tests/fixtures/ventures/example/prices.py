"""The example venture's prices (tests only; made up): the same names lib/prices.py exports."""
import hashlib

HOSTING_PRICE = "$35"
LIGHT_PRICE = "$35"
STARTER_PRICE = "$75"
PRICE_LINE = f"{HOSTING_PRICE} a month"
PRICES_LINE = f"Two plans: {HOSTING_PRICE} and {STARTER_PRICE} a month."
_PRICED = (("price_line", PRICE_LINE), ("prices_line", PRICES_LINE))


def letter_sha(raw):
    used = [f"{key}={value}" for key, value in _PRICED if "{" + key + "}" in raw]
    return hashlib.sha256("\n".join([raw, *used]).encode()).hexdigest()
