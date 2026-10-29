"""The one shape every module emits and every layer above consumes."""
from dataclasses import dataclass, field, asdict

from severity import Sev


DIMENSIONS = [
    "purpose_fit", "collateral", "funding", "mandate",
    "concentration", "life_event", "tax", "data_quality",
]

# Human labels, and the order the workbench shows them in.
LABELS = {
    "purpose_fit":   "Purpose fit",
    "collateral":    "Collateral",
    "funding":       "Funding",
    "mandate":       "Mandate",
    "concentration": "Concentration",
    "life_event":    "Life event",
    "tax":           "Tax",
    "data_quality":  "Data quality",
    "rebalance":     "Rebalancing",
    "scenario":      "Scenario",
}


@dataclass
class Finding:
    id: str
    client_id: str
    dimension: str
    severity: float                 # 0-100, comparable across dimensions
    headline: str                   # one line, no jargon
    detail: str                     # the paragraph an RM reads
    action: str                     # what to actually do
    rule_text: str                  # the rule that produced this, shown on click
    severity_basis: dict = field(default_factory=dict)   # how that number was built
    numbers: dict = field(default_factory=dict)
    source_rows: list = field(default_factory=list)   # traceable row references
    status: str = "open"            # open | waived | directed
    confidence: str = "high"        # high | medium | check
    check: str = ""                 # what we would verify, when not high
    evidence: list = field(default_factory=list)      # {note_id, date, quote}
    # Two rules can describe the same fact from different angles: a dated
    # obligation is a life event, and whether it can be paid is a funding
    # finding. Both are worth saying and both stay on screen, but one
    # obligation is one problem — the weaker of the pair carries the id of the
    # stronger and stops counting toward the tiebreak. See build.link_duplicates.
    same_fact_as: str = ""

    def __post_init__(self):
        # modules pass a Sev, which carries its own arithmetic; unpack it here
        # so nothing downstream has to know the difference
        if isinstance(self.severity, Sev):
            self.severity_basis = self.severity.basis()
            self.severity = self.severity.value

    def as_dict(self):
        d = asdict(self)
        d["severity"] = round(self.severity, 1)
        d["label"] = LABELS.get(self.dimension, self.dimension)
        return d
