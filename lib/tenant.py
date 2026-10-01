"""Shared tenant-identity check for the toolbelt's per-client tools.

Every money/data tool (site, db, newsletter, social, gbp, pay, connections)
reads which client it's acting for from `.client.json` in the current
directory. The relay also tells the run which project it is, in `RELAY_PROJECT`.
A client/demo run that rewrites `.client.json` to another client's slug would,
without this check, point those tools at the other client's data. So each tool
cross-checks the slug it read against `RELAY_PROJECT` and refuses on a mismatch.

The check only bites inside a relay client/demo run (where `RELAY_PROJECT` names
a specific project). A terminal run has no `RELAY_PROJECT`, and the owner's own
`global` run names `global`, so neither is constrained here — this guards the
exact case the sandbox review found, not ordinary use.
"""

import os
import sys

# RELAY_PROJECT values that are not a single client's workspace: the owner's own
# session, or the relay's internal jobs. These never bind a tool to a slug.
_EXEMPT = {"", "global", "triage"}


def enforce(slug, die=None):
    """Refuse if the run's RELAY_PROJECT names a different client than `slug`.

    `slug` is the identity read from `.client.json`. `die(msg)` is the tool's
    own error-and-exit if it has one; otherwise this prints and exits 2.
    """
    want = os.environ.get("RELAY_PROJECT", "")
    if want in _EXEMPT or not slug or want == slug:
        return
    msg = (f"this run is for {want!r}, but the workspace here is {slug!r}. "
           f"Refusing to touch another client's data. Run from that client's own "
           f"workspace (~/projects/clients/{want}) for its site, mail, payments or lists.")
    if die:
        die(msg)
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)
