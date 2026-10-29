"""
Translate an amended client note, at the keyboard.

    .venv/bin/python engine/serve.py                          # the composer calls this
    .venv/bin/python engine/translate.py --dry-run FINDING_ID # show what would leave

The deterministic notes (clientnote.py) and the narration drafts (narrate.py)
are both written before the RM touches them. Once she amends one language, the
other no longer says the same thing, and until now the composer could only say
so. This closes that gap, under the same three rules narrate.py enforces.

1.  **No number reaches a client unless the engine produced it.** A translation
    is not allowed to add, drop or restate a figure — converting USD 7.7m into
    770萬美元 is arithmetic, and arithmetic is not the model's to do. The prompt
    says so, and afterwards `check()` compares the figures on both sides. A
    translation that fails is still returned, marked, and the composer refuses
    to treat it as sendable.

2.  **Direct identifiers never leave the perimeter.** The client's name, the
    exact age, the RM's name and the bank's name are swapped for tokens before
    the call and restored afterwards. Restoring is exact for the client, and in
    the target language's own form for the RM and the bank — Clara Teo signs as
    張慧玲 in Chinese, which no translation of the letters would produce.

3.  **A repeat costs nothing.** Every response is cached to disk under a hash of
    the exact payload, prompt and model.

Needs Python 3.10+ and the anthropic SDK, like narrate.py — the README sets
up a virtual environment for it. Everything the
check does is standard library, so the tests run anywhere.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import clientnote                            # noqa: E402
from narrate import MODEL, name_parts, read_key   # noqa: E402

ROOT = os.path.dirname(HERE)
BUNDLE = os.path.join(ROOT, "app", "findings.json")
CACHE_DIR = os.path.join(HERE, "cache", "translate")
RECORDED = os.path.join(HERE, "cache", "translations.json")
PROMPT_VERSION = "1"          # bump to invalidate every cached translation
MAX_CHARS = 8000              # a client note is a few paragraphs, not a document
VENV_HINT = ("set up the project's virtual environment (python3.13 -m venv .venv, then "
             ".venv/bin/pip install -r requirements.txt) and run with .venv/bin/python")

SYSTEM = """You translate private-client correspondence for a relationship \
manager at a private bank. The letter has already been written and approved in \
one language; you produce the same letter in another, for a reader who does not \
read the first.

Absolute rules:

1. Translate; do not rewrite. Keep every sentence's meaning, its order, the \
paragraph breaks and the line breaks. Do not add, drop, soften or strengthen \
anything, and do not add a greeting, a closing or a signature that is not there.
2. Copy every figure exactly as written: the same digits, the same decimal point, \
the same thousands separators, the same currency code, the same unit letters \
(such as m or k) and the same % sign. Use Western digits, never full-width or \
local numerals. Do not convert a currency, a unit or a date format, and do not \
re-express an amount in another counting unit such as 萬, 万 or 億 — that is \
arithmetic, and a separate system checks every figure you write against the \
original. Numbers the original writes as words may stay as words.
3. Tokens in double square brackets, such as [[FIRST_NAME]], [[RM_NAME]], \
[[BANK]] or [[NAME_2]], stand for names. Copy each one exactly, unchanged, \
wherever the name belongs in the translated sentence. Never invent a name, a \
title or a token.
4. Company, fund and instrument names are proper nouns: leave them as written.
5. Register: a senior banker writing to a client of long standing, in the \
conventions the target language uses for such a letter — formal address, no \
marketing language, no exclamation marks.

If something cannot be carried across faithfully, translate it as closely as you \
can and say what, in one plain English sentence, in translator_note. Otherwise \
leave translator_note empty."""

SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {"type": "string",
                        "description": "The whole letter in the target language."},
        "translator_note": {"type": "string",
                            "description": "One English sentence on anything that could "
                                           "not be carried across faithfully, or empty."},
    },
    "required": ["translation", "translator_note"],
    "additionalProperties": False,
}


class TranslateError(Exception):
    """Something the RM should be told, in words she can act on."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ── identifiers out, identifiers back ─────────────────────────────────────
TOKEN = re.compile(r"\[\[[A-Z_0-9]+\]\]")
# Word boundaries for a Latin-script name, in ASCII on purpose: Python's \w
# also matches Chinese and Japanese characters, so "Wing您好" would not count as
# the end of the name "Wing" and the name would travel untouched.
LATIN_BEFORE = r"(?<![A-Za-z0-9_])"
LATIN_AFTER = r"(?![A-Za-z0-9_])"


def tokenise(text, profile):
    """Swap every direct identifier for a token.

    Returns (tokenised text, restore map). The client's name parts become
    [[FIRST_NAME]] when they are the salutation the workbench would use and
    [[NAME_n]] otherwise, so that restoring puts back exactly what the RM wrote
    rather than whatever form the salutation takes. The RM and the bank become
    [[RM_NAME]] and [[BANK]] in any of the forms clientnote.py signs with."""
    out = str(text)
    restore = {}

    # the RM and the bank, every form in every language, longest first
    for token, table in (("[[RM_NAME]]", clientnote.RM_NAME),
                         ("[[BANK]]", clientnote.BANK_NAME)):
        for form in sorted(set(table.values()), key=len, reverse=True):
            out = out.replace(form, token)

    # the client: the full name, then any part of it long enough to be a name
    name = (profile.get("client_name") or "").strip()
    salutation = salutation_for(profile)
    spans = [name] + sorted(set(name_parts(profile)), key=len, reverse=True)
    n = 0
    for span in [s for s in dict.fromkeys(spans) if s]:
        pattern = re.compile(LATIN_BEFORE + re.escape(span) + LATIN_AFTER)
        if not pattern.search(out):
            continue
        if span == salutation:
            token = "[[FIRST_NAME]]"
        else:
            n += 1
            token = "[[NAME_%d]]" % n
        restore[token] = span
        out = pattern.sub(token, out)

    # the exact age, where it stands alone as a number; it comes back exactly
    age = str(profile.get("age") or "").strip()
    if age:
        # "At 71, he..." is the age; 71,000 and 71.5 and 71% are figures
        pattern = re.compile(r"(?<![A-Za-z0-9_.,])" + re.escape(age)
                             + r"(?![A-Za-z0-9_%])(?![.,]\d)")
        if pattern.search(out):
            restore["[[AGE]]"] = age
            out = pattern.sub("[[AGE]]", out)
    return out, restore


def restore_names(text, restore, language):
    """Put the identifiers back, the RM and the bank in the target language's form."""
    out = text.replace("[[RM_NAME]]", clientnote.RM_NAME.get(language, clientnote.RM_NAME["English"]))
    out = out.replace("[[BANK]]", clientnote.BANK_NAME.get(language, clientnote.BANK_NAME["English"]))
    for token, value in restore.items():
        out = out.replace(token, value)
    return out


def salutation_for(profile):
    """The same rule the workbench uses: the whole name for a client reported to
    in Chinese, Japanese or Korean, where the family name comes first, and for an
    entity such as a family office, which has no first name and no age."""
    name = profile.get("client_name") or ""
    lang = profile.get("reporting_language") or ""
    if any(l in lang for l in ("Chinese", "Japanese", "Korean")) or not profile.get("age"):
        return name
    return name.split(" ")[0] if name else ""


# ── the figure check ──────────────────────────────────────────────────────
# The lookbehinds are deliberately narrow. Python's \w matches CJK characters,
# so the obvious (?<!\w) cannot see the 768 in 約768萬 — a figure glued to a
# Chinese character would pass any check built on it without being looked at.
# What is skipped is only what is not a figure: the digits of an identifier such
# as CF-0002 (letter, hyphen, digits) and the tail of a longer number.
FIGURE = re.compile(r"(?<![0-9_.,])(?<![A-Za-z]-)"
                    r"(?:\d{4}-\d{2}-\d{2}|\d[\d,]*(?:\.\d+)?)")
# counting words: "twelve months" may fairly become 12個月, and back
SMALL = {str(i) for i in range(0, 13)}


def figures(text):
    """Every figure in the text, normalised so 1,280,000 and 1280000 are one."""
    out = set()
    for raw in FIGURE.findall(TOKEN.sub(" ", str(text or ""))):
        f = raw.rstrip(",").replace(",", "")
        if "." in f and "-" not in f:
            whole, frac = f.split(".", 1)
            frac = frac.rstrip("0")
            f = whole + "." + frac if frac else whole
        if f not in SMALL:
            out.add(f)
    return out


def check(source, translation):
    """What the translation added, dropped or lost, against the source.

    Figures on one side and not the other, and tokens in the source that the
    translation lost (a name it dropped) or tokens it invented. Empty lists
    mean the two say the same thing, figure for figure."""
    s, t = figures(source), figures(translation)
    st, tt = set(TOKEN.findall(source)), set(TOKEN.findall(translation))
    return {"added": sorted(t - s), "dropped": sorted(s - t),
            "names_lost": sorted(st - tt), "names_invented": sorted(tt - st)}


def clean(result):
    return not any(result.values())


# ── the call ──────────────────────────────────────────────────────────────
def payload_for(text, source, target):
    """Everything the model sees besides the system prompt."""
    return {"from": source, "to": target, "letter": text}


def cache_key(payload):
    blob = json.dumps({"m": MODEL, "v": PROMPT_VERSION, "s": SYSTEM, "p": payload},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _cached(key):
    path = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _store(key, record):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)


def availability():
    """(ready, reason). Checked before the RM is offered the button."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, ("the anthropic package is not installed for this Python "
                       "(%d.%d) — %s" % (sys.version_info[:2] + (VENV_HINT,)))
    key, _ = read_key()
    if not key:
        return False, ("no API key — export ANTHROPIC_API_KEY, or write it to "
                       "~/.anthropic_key, then restart the server")
    return True, ""


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        key, _ = read_key()
        _client = anthropic.Anthropic(api_key=key)
    return _client


def call(client, payload):
    """One letter, one call. Structured output so the translation arrives as a
    field rather than as prose to be picked apart."""
    try:
        from anthropic import BadRequestError
    except ImportError:                      # a stand-in client, as in the tests
        BadRequestError = ()
    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content":
                   json.dumps(payload, ensure_ascii=False, indent=1)}],
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # server-side fallback: if a safety classifier declines, the same request
        # is re-run on the recommended model inside the same call
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except (BadRequestError, TypeError) as e:
        # TypeError: an SDK older than the `fallbacks` parameter
        if "fallback" not in str(e).lower():
            raise
        resp = client.messages.create(**kwargs)

    if resp.stop_reason == "refusal":
        raise TranslateError("the model declined to translate this note (%s)"
                             % getattr(resp.stop_details, "category", None), 422)
    if resp.stop_reason == "max_tokens":
        raise TranslateError("the translation was cut off — the note is too long", 422)
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.model


def translate(text, source, target, profile, client=None):
    """Translate `text` from `source` to `target` for the client in `profile`.

    Returns {text, note, check, clean, model, at, cached}. Raises TranslateError
    with a message fit to show the RM."""
    if not text or not text.strip():
        raise TranslateError("there is nothing to translate")
    if len(text) > MAX_CHARS:
        raise TranslateError("the note is longer than %d characters" % MAX_CHARS)
    allowed = {"English", profile.get("reporting_language") or "English"}
    if source not in allowed or target not in allowed or source == target:
        raise TranslateError("this client's notes go between %s only"
                             % " and ".join(sorted(allowed)))

    tokenised, restore = tokenise(text, profile)
    payload = payload_for(tokenised, source, target)
    key = cache_key(payload)
    rec = _cached(key)
    was_cached = rec is not None
    if rec is None:
        draft, model = call(client or _get_client(), payload)
        rec = {"translation": draft["translation"],
               "translator_note": draft.get("translator_note", ""),
               "model": model, "via": "API", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _store(key, rec)

    result = check(tokenised, rec["translation"])
    return {
        "text": restore_names(rec["translation"], restore, target),
        "note": rec.get("translator_note", ""),
        "check": result,
        "clean": clean(result),
        "model": rec.get("model", MODEL),
        "via": rec.get("via", "API"),
        "at": rec.get("at", ""),
        "cached": was_cached,
    }


# ── the bundle, for the server and the dry run ────────────────────────────
def load_bundle():
    if not os.path.exists(BUNDLE):
        raise TranslateError("run `python3 engine/build.py` first", 503)
    with open(BUNDLE, encoding="utf-8") as fh:
        return json.load(fh)


def profile_for(bundle, finding_id):
    f = next((x for x in bundle["findings"] if x["id"] == finding_id), None)
    if f is None:
        raise TranslateError("no finding %s in the bundle" % finding_id, 404)
    return bundle["clients"][f["client_id"]]["profile"], f


# ── recorded translations, for a copy with no server ──────────────────────
# A static copy of the workbench (GitHub Pages) has no key and no server, so it
# cannot translate. It can replay a translation recorded in advance, for one
# prepared amendment per demo note. A recording goes through the same door as
# a live translation: stored under the hash a live call would use,
# then passed through translate() exactly as serve.py would, so the figure
# check the composer shows is the real one, run on the real text.
def import_recorded(path, via):
    with open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    bundle = load_bundle()
    out = []
    for it in items:
        profile, _ = profile_for(bundle, it["finding_id"])
        tokenised, _ = tokenise(it["source"], profile)
        key = cache_key(payload_for(tokenised, it["from"], it["to"]))
        _store(key, {"translation": it["translation"],
                     "translator_note": it.get("translator_note", ""),
                     "model": MODEL, "via": via, "at": time.strftime("%Y-%m-%d")})
        res = translate(it["source"], it["from"], it["to"], profile)
        res.pop("cached")
        out.append(dict(res, finding_id=it["finding_id"], source=it["source"],
                        amendment=it.get("amendment", ""),
                        **{"from": it["from"], "to": it["to"]}))
        print("  %-14s %s -> %s  %s" % (it["finding_id"], it["from"], it["to"],
                                        "clean" if res["clean"] else json.dumps(res["check"])))
    with open(RECORDED, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("  %d recorded -> %s\n  now re-run:  python3 engine/build.py" % (len(out), RECORDED))


def main():
    ap = argparse.ArgumentParser(description="Translate an amended client note.")
    ap.add_argument("finding", nargs="?", help="a finding id, e.g. FIT-CL-0012")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the payload that would leave the perimeter; call nothing")
    ap.add_argument("--import-recorded", metavar="PATH",
                    help="record translations written outside the API, for the static "
                         "demo, through the same cache and figure check; call nothing")
    ap.add_argument("--via", default="Claude Code",
                    help="with --import-recorded: where the translations were written")
    args = ap.parse_args()
    if args.import_recorded:
        return import_recorded(args.import_recorded, args.via)
    if not args.finding:
        ap.error("a finding id is required")

    bundle = load_bundle()
    profile, f = profile_for(bundle, args.finding)
    lang = profile.get("reporting_language") or "English"
    # what the composer opens on: the model's draft when there is one
    text = ((f.get("draft") or {}).get("english")
            or (f.get("note", {}).get("English") or {}).get("text", ""))
    text = text.replace("[[FIRST_NAME]]", salutation_for(profile))
    target = lang if lang != "English" else None
    if target is None:
        sys.exit("%s is reported to in English; there is nothing to translate into"
                 % f["client_id"])

    tokenised, restore = tokenise(text, profile)
    print("  ── payload that would leave the perimeter, %s -> %s ──" % ("English", target))
    print(json.dumps(payload_for(tokenised, "English", target), ensure_ascii=False, indent=1))
    print("\n  restored locally, never sent: %s" % (", ".join(sorted(restore)) or "nothing"))
    print("  figures the translation must carry: %s"
          % (", ".join(sorted(figures(tokenised))) or "none"))
    if args.dry_run:
        return
    ready, why = availability()
    if not ready:
        sys.exit("  cannot call: " + why)
    out = translate(text, "English", target, profile)
    print("\n" + out["text"])
    print("\n  check: %s%s" % ("clean" if out["clean"] else json.dumps(out["check"]),
                               "  (cached)" if out["cached"] else ""))


if __name__ == "__main__":
    main()
