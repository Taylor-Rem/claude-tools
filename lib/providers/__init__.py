"""The Factory's providers (ROADMAP B144, plan 55 § 5.7): one adapter a vendor, one fake for tests.

`bin/infra` speaks to a provider only through the methods below, and only through its own keyed wrapper
(`Op.call` in bin/infra), so every mutation is in the ledger before it leaves the machine and a re-run
after a crash finds the key instead of repeating the call. An adapter never decides anything: it makes
the call it is asked to make and says what came back. Verification is not its job either; bin/infra
reads the world (DNS, a login, the seed inboxes) and never takes the vendor's "ok" as proof.

Reads (allowed while the factory is halted):
    domain(name)            -> {"owned": bool, "id", "prewarmed": bool} or None when we don't hold it
    available(name)         -> {"available": bool, "price_usd": float}
    mailboxes(domain)       -> [{"address", "id"}]   (never a password)
    warmup(address)         -> {"enrolled": bool, "days": int} or None when the vendor doesn't say
    placement(domain)       -> {"inbox_pct": float, "date"} or None when the vendor has no probe
    prices()                -> {"domain_usd_year", "mailbox_usd_month"}
Mutations (each takes `key`, the idempotency key bin/infra already wrote to the ledger):
    buy_domain(name, key, prewarmed=False)    -> {"id", "cost_usd", "human_steps": [HumanStep...]}
    set_auth_dns(name, key)                   -> {"records": [{"type", "name", "value"}], "dkim_selector"}
    add_txt(name, host, value, key)           -> {}
    remove_dns(name, key)                     -> {}
    create_mailbox(domain, local, password, key) -> {"id", "address", "user", "smtp", "imap", "cost_usd_month"}
    delete_mailbox(address, key)              -> {}
    start_warmup(address, key)                -> {}
    set_autorenew(name, on, key)              -> {}

A step only a person can take (a card, a verification email, a terms box) is a HumanStep: raised when
it blocks the call, returned in `human_steps` when it doesn't. bin/infra files it in TAYLOR-TODO.md
once, under its repeat key, and stops (or carries on) accordingly.

No business is named here or in an adapter (tests/test_portable.py): names come from the caller.
"""

import importlib


class ProviderError(Exception):
    """The vendor said no or couldn't be reached, in a sentence with no credential in it."""


class HumanStep(Exception):
    """Something only Taylor can do, with the exact click.

    key       the step's own key (one TODO entry per key, ever): "registrant-verify:example.com"
    repeat_key  the operation's family for `todo audit` (plan 55 § 5.5): "domain-registrant-verify"
    title     the entry's bold line, action first
    steps     the numbered clicks
    why       why a person: identity | contract | money | judgment | physical
    minutes   about how long
    blocking  True when the call can't go on without it"""

    def __init__(self, key, repeat_key, title, steps, why, minutes, then="", blocking=True):
        super().__init__(title)
        self.key, self.repeat_key, self.title, self.steps = key, repeat_key, title, list(steps)
        self.why, self.minutes, self.then, self.blocking = why, int(minutes), then, blocking

    def as_dict(self):
        return {"key": self.key, "repeat_key": self.repeat_key, "title": self.title, "steps": self.steps,
                "why": self.why, "minutes": self.minutes, "then": self.then, "blocking": self.blocking}

    @classmethod
    def from_dict(cls, d):
        return cls(d["key"], d["repeat_key"], d["title"], d.get("steps") or [], d.get("why") or "",
                   d.get("minutes") or 5, d.get("then") or "", d.get("blocking", True))


NAMES = ("fake", "infraforge")


def get(name, get_env, dry_run=False, say=print):
    """The adapter called `name`. get_env(NAME) reads one toolbelt env value (never printed)."""
    if name not in NAMES:
        raise ProviderError(f"no adapter called {name!r}; there is {', '.join(NAMES)} "
                            "(a second vendor waits until the registry asks for one, plan 55 § 5.7)")
    mod = importlib.import_module(f"providers.{name}")
    return mod.Adapter(get_env, dry_run=dry_run, say=say)
