"""
The diary: every dated obligation across the book, in order.

Emits the whole list, not the nearest few, because the workbench renders it
three ways — an agenda of the next handful, a month grid and a week. The
`spotlight` flag marks the agenda set, so the "which five matter" judgement
stays here in the engine rather than being reinvented in the UI.

Amounts are converted to USD for ordering but shown in the currency the client
actually owes. Every entry carries a stable `id`, which is what lets the RM
edit or hide one in the workbench and have that survive a rebuild.
"""
QUARTER_START = {"Q1": "-01-01", "Q2": "-04-01", "Q3": "-07-01", "Q4": "-10-01"}


def window_start(window):
    """'2026 Q4 to 2028 Q2' -> '2026-10-01'."""
    head = window.split(" to ")[0].strip()
    parts = head.split()
    if len(parts) == 2 and parts[1] in QUARTER_START:
        return parts[0] + QUARTER_START[parts[1]]
    return head


def next_occurrence(need, today):
    """When does this obligation next fall due?

    `due_from` is the FIRST occurrence, not the only one. For an annual need it
    is followed by `due_to`, which is when the series ends — living costs drawn
    every January to 2036 are ten more drawdowns, not one already in the past.
    Treating `due_from` as the only date dropped the next one from the diary
    entirely. The funding rule always counted it; only the diary lost it, which
    is the worst way for the two to disagree — the finding says the money is
    owed and the calendar shows nothing.

    One-off and irregular needs keep the old behaviour: a past date is past."""
    due, until = need["due_from"], need.get("due_to") or ""
    if due >= today:
        return due
    if not (need.get("recurrence") or "").lower().startswith("annual"):
        return None
    year, tail = int(due[:4]), due[4:]
    for _ in range(40):
        year += 1
        cand = "%04d%s" % (year, tail)
        if until and cand > until:
            return None
        if cand >= today:
            return cand
    return None


def build(book, spotlight=5):
    items = []

    for n in book.cash_needs:
        if n["certainty"] == "Aspirational":
            continue
        date = next_occurrence(n, book.today)
        if not date:
            continue
        items.append({
            "id": "CN-%s" % n["need_id"],
            "date": date,
            "first_due": n["due_from"],
            "recurrence": n["recurrence"],
            "recurring": date != n["due_from"],
            "client_id": n["client_id"],
            "client": book.C[n["client_id"]]["client_name"],
            "what": n["description"],
            "currency": n["currency"],
            "amount": float(n["amount"]),
            "usd": book.to_usd(float(n["amount"]), n["currency"]),
            "kind": "Cash need",
            "certainty": n["certainty"],
        })

    # same restatement guard as the funding rule: do not list the commitments
    # separately when a cash-needs row already stands for them
    restated = {n["client_id"] for n in book.cash_needs
                if "commitment" in n["description"].lower()}
    for c in book.commitments:
        date = window_start(c["expected_call_window"])
        if c["client_id"] in restated or date < book.today or not float(c["uncalled"]):
            continue
        items.append({
            "id": "PC-%s-%s" % (c["client_id"], c["fund_name"][:12].replace(" ", "")),
            "date": date,
            "client_id": c["client_id"],
            "client": book.C[c["client_id"]]["client_name"],
            "what": "Capital call window opens — " + c["fund_name"],
            "currency": c["currency"],
            "amount": float(c["uncalled"]),
            "usd": book.to_usd(float(c["uncalled"]), c["currency"]),
            "kind": "Commitment",
            "certainty": "Contractual",
        })

    for c in book.clients:
        due = c.get("kyc_review_due", "")
        if not due or due < book.today:
            continue
        items.append({
            "id": "KYC-%s" % c["client_id"],
            "date": due, "client_id": c["client_id"], "client": c["client_name"],
            "what": "KYC review falls due", "currency": "", "amount": 0.0, "usd": 0.0,
            "kind": "Review", "certainty": "Confirmed",
        })

    items.sort(key=lambda x: (x["date"], -x["usd"]))

    # The agenda shows the nearest few. KYC reviews are diary admin, not client
    # money, so only the nearest one is ever allowed into it — the rest still
    # exist and still appear in the month and week grids.
    chosen, kyc_used = 0, False
    for it in items:
        it["spotlight"] = False
        if chosen >= spotlight:
            continue
        if it["kind"] == "Review":
            if kyc_used:
                continue
            kyc_used = True
        it["spotlight"] = True
        chosen += 1
    return items
