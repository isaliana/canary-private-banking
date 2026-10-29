"""
Structured claims from the RM's free-text notes.

Half the positions in this book exist for a reason that appears nowhere except
here. A breach the client waived in writing is not the same finding as a breach
the client merely shrugged at, and a position the client refuses to sell for
sentimental reasons must never appear in a rebalancing suggestion.

This is the deterministic floor: explicit patterns, always with the sentence
that triggered them so an RM can check. A model could extract the same claims
with more recall, over the same schema and with the same quoting rule; that is
not built yet, and nothing here depends on it.
"""
import re

# (claim type, pattern, what it means downstream)
PATTERNS = [
    ("waiver",        r"waiver on file|suitability waiver",
     "a signed waiver exists; the breach is governed, not outstanding"),
    ("directed",      r"acknowledged .{0,60}(?:but )?proceeded|confirmed the instruction in writing"
                      r"|client instructed|he subscribed|instructed an additional",
     "client-directed; the breach stands but the bank did not choose it"),
    ("refusal",       r"does not want to sell|would rather wait|will not sell|unwilling to sell"
                      r"|did not want to discuss|does not want to",
     "the client has refused this action before"),
    ("protected",     r"sentimental|legacy shareholding|family holding",
     "do not propose selling this position"),
    ("awareness_gap", r"was not aware|not aware of|was surprised|surprised how",
     "the client does not know this; lead the conversation with it"),
    ("health",        r"declining health|medical costs?|medical care",
     "time-sensitive for reasons outside the portfolio"),
    ("open_item",     r"have not yet replied|we have not modelled|asked for a full liquidity map"
                      r"|asked for a view on",
     "the RM owes this client something"),
    ("gated",         r"gated (?:\w+) consecutive|has now gated|restrict withdrawals|gated position",
     "cannot be exited on schedule regardless of its stated liquidity tier"),
    ("escalate",      r"needs monitoring|needs a proper conversation|recommend involving",
     "already flagged by the RM as needing follow-up"),
]

_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentence(text, match_start):
    """The sentence containing a match, so evidence is quotable."""
    pos = 0
    for s in _SPLIT.split(text):
        if pos <= match_start < pos + len(s) + 1:
            return s.strip()
        pos += len(s) + 1
    return text[:180].strip()


def extract(notes):
    """[note] -> {client_id: [claim]}, newest last."""
    out = {}
    for n in notes:
        text = n["note"]
        for kind, pattern, meaning in PATTERNS:
            m = re.search(pattern, text, re.I)
            if not m:
                continue
            out.setdefault(n["client_id"], []).append({
                "type": kind,
                "meaning": meaning,
                "note_id": n["note_id"],
                "date": n["note_date"],
                "channel": n["channel"],
                "quote": _sentence(text, m.start()),
                "source": "pattern",     # the narration layer writes "model"
            })
    for claims in out.values():
        claims.sort(key=lambda c: c["date"])
    return out


def has(claims, client_id, *kinds):
    return [c for c in claims.get(client_id, []) if c["type"] in kinds]


if __name__ == "__main__":
    from loader import Book
    b = Book()
    claims = extract(b.notes)
    for cid in sorted(claims):
        print("%s  %s" % (cid, b.C[cid]["client_name"]))
        for c in claims[cid]:
            print("   %-14s %s  %s" % (c["type"], c["note_id"], c["quote"][:96]))
    print()
    missing = [c for c in sorted(b.C) if c not in claims]
    print("clients with no extracted claim:", missing)
