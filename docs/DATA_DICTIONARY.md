# Data dictionary

The book in `data/` is synthetic, written by [`data/generate.py`](../data/generate.py):

```bash
python3 data/generate.py      # rewrites every file below, deterministically
```

**Everything in it is invented** — the bank (Halden Rowe), its relationship
manager (Clara Teo), the twenty clients, every company, fund, bond and price,
and every market event. Nothing describes a real person, company or market, and
none of it is investment advice.

The generator works stories first. Each client is a few positions at a stated
weight and a stated gain or loss *today*; it derives the quantities, a price for
every instrument at every snapshot, cost bases, lending values, facility
loan-to-value, income, fees and cash movements, so that every file agrees with
every other.

---

## Files

| File | Rows | Grain |
|---|---|---|
| `clients.csv` | 20 | one row per client |
| `portfolios.csv` | 23 | one row per portfolio; some clients hold several |
| `holdings.csv` | 1,008 | one row per position **per snapshot** |
| `instruments.csv` | 62 | one row per instrument, with its price at every snapshot |
| `mandates.csv` | 42 | asset-allocation bands, one row per mandate × asset class |
| `transactions.csv` | 428 | income, fees, interest, trades, transfers, capital calls |
| `credit_facilities.csv` | 2 | Lombard facilities, with loan-to-value at every snapshot |
| `commitments.csv` | 3 | private-markets commitments and what is still uncalled |
| `planned_cash_needs.csv` | 14 | dated obligations the client has told the bank about |
| `market_context.csv` | 160 | 19 market series and 13 currency pairs × 5 snapshots |
| `event_log.csv` | 14 | the year's market events, with the channels they travelled through |
| `rm_notes.json` | 33 | the RM's free-text notes |

The five snapshots are quarter-ends: 2025-09-30, 2025-12-31, 2026-03-31,
2026-06-30 and **2026-09-30, which is "today"**.

### Joins

```
clients.client_id         → portfolios.client_id → holdings.portfolio_id
holdings.instrument_id    → instruments.instrument_id
portfolios.mandate_code   → mandates.mandate_code   (custody portfolios have none)
holdings.snapshot_date    → market_context.snapshot_date
credit_facilities.collateral_portfolio_id → portfolios.portfolio_id
rm_notes[].client_id      → clients.client_id
```

---

## Fields

### clients.csv

`client_id`, `client_name`, `age`, `gender`, `nationality`,
`country_of_residence`, `tax_domicile`, `booking_centre`, the RM's `rm_id`,
`rm_name` and `rm_desk`, `base_currency`, `wealth_band` (HNW below USD 30m, UHNW
above), `total_aum_usd`, `life_stage`, `source_of_wealth`, `risk_profile`,
`risk_tolerance_score` (1-10), `investment_horizon_years`, `liquidity_needs`,
`objectives` (in the client's own framing), `client_since`, `kyc_review_due`,
`pep_status`, `reporting_language`.

Residence and tax domicile differ for eight clients; tax questions turn on the
second. One client is a family office and has no age or gender.

### portfolios.csv

`portfolio_id`, `client_id`, `portfolio_name`, `mandate_code`, `mandate_name`,
`service_model` (Discretionary, Advisory or Custody), `base_currency`,
`inception_date`, `benchmark`, `aum_<date>` in base currency at each snapshot,
and `aum_usd_current`. **Custody accounts are the client's wealth but are run
against no mandate.**

### holdings.csv

| Column | Notes |
|---|---|
| `quantity`, `price_local`, `market_value_local` | Bonds are quoted per 100 nominal and `quantity` is in units of 100, so `quantity × price_local = market_value_local` for every asset class |
| `market_value_base`, `market_value_usd`, `weight_pct` | Base is the portfolio's reporting currency; weight is within the portfolio |
| `avg_cost_local`, `cost_basis_base`, `unrealised_pnl_base`, `unrealised_pnl_pct` | The cost basis is struck at the exchange rate of the day the position was bought, so a gain in local currency can be a loss in base |
| `lending_value_base`, `advance_rate_pct` | What the bank will lend against the position. Illiquid funds and structured products carry 0% |
| `liquidity_tier` | Daily, Weekly, Monthly, Quarterly Gate or Illiquid |
| `valuation_date` | Equals `snapshot_date` — except where a mark has not been updated |
| `acquired_date` | When the position was first bought |

A position that starts during the year appears only from the snapshot after it
was bought.

### instruments.csv

`asset_class`, `sub_asset_class`, `sector`, `region`, `currency`,
`liquidity_tier`, `price_<date>` at every snapshot, and three fields worth
reading closely:

- **`underlying_reference`** — for a structured product, what it is actually
  exposed to. A worst-of basket is exposed to every name in it.
- **`sustainability_excluded`** — `Y` if a sustainable mandate's exclusion list
  covers it. It only matters in a mandate that has such a list.
- **`concentration_limit_applies`** — `Y` for single-name exposures, which is
  what a mandate's single-position limit is for.

A bond's maturity is in its name ("US Treasury 3.875% due 2049"), or the name
says "Perpetual".

### mandates.csv

`min_pct`, `target_pct` and `max_pct` per asset class, `max_single_position_pct`,
and `mandate_notes`. The Sustainable Balanced mandate's notes carry its binding
exclusions.

### credit_facilities.csv

`facility_ccy`, `credit_limit`, `interest_rate_pct`, `margin_call_ltv_pct`, and at
each snapshot `drawn_`, `collateral_market_value_`, `lending_value_`, `ltv_pct_`
and `headroom_`. Loan-to-value is `drawn ÷ lending_value` — lending value, not
market value.

### commitments.csv, planned_cash_needs.csv

Commitments: `committed`, `called_to_date`, `uncalled` and an
`expected_call_window` such as "2026 Q4 to 2027 Q3". Cash needs: `currency`,
`amount`, `due_from`, `due_to`, `recurrence` (One-off or Annual) and
`certainty` (Confirmed, Likely or Aspirational). **Amounts are in the currency
owed**, not USD. For an annual need `due_from` is the first occurrence and
`due_to` the last.

### market_context.csv, event_log.csv

Market context is long format: `snapshot_date`, `series_id`, `series_name`,
`category`, `unit`, `value`. Currency pairs are quoted in market convention —
`USDSGD` is SGD per USD, `EURUSD` is USD per EUR — so check before dividing.

The event log has `event_date`, `event_type`, `region`, `description`,
`primary_transmission` (the channels the event travelled through, in words the
instrument names use) and `severity` (Medium, High or Severe).

### rm_notes.json

`note_id`, `client_id`, `note_date`, `rm_id`, `rm_name`, `channel`, `note`.
Written the way an RM writes: partial, subjective, and sometimes the only place
a fact exists — a waiver, a refusal, a position kept for sentimental reasons, a
fund that has stopped paying out.

---

## The stories

| Client | What is planted |
|---|---|
| CL-0001 Takeshi Morimoto | Retired; 41% of his wealth matures after his horizon and is underwater. His stated income and his recorded cash need disagree. Reads Japanese. |
| CL-0002 Raymond Wong Ka Lok | A Lombard loan at 68.8% against a 70% trigger, breached twice this year. Selling the collateral to pay a land deposit trips the margin call. His family's developer is 38% of his wealth across three holdings. Reads Traditional Chinese. |
| CL-0003 Elisabeth Brandt | Her late husband's shares, transferred into a conservative mandate and never rebalanced. She wants to keep some for sentimental reasons. Reads German. |
| CL-0004 Arjun Mehta | 46% of his wealth is his own company at a fifteen-month-old mark, which also secures his loan. |
| CL-0005 Nurul Aisyah binti Hamzah | A sustainable mandate the bank runs, holding three things it excludes. One is a family holding she has asked not to sell. |
| CL-0006 Chen Jia Hui | Her own industry, three ways — shares, a linked note and a worst-of basket. She instructed the purchase. Reads Simplified Chinese. |
| CL-0007 Edward Ashworth | Gold over his ceiling, with a waiver on file. A foundation to endow, and a health note. |
| CL-0008 Lim Heng Family Office | Capital calls and family distributions against a book with a gated private credit fund. |
| CL-0009 Fatima Al-Suwaidi | Large losses, in a domicile with no capital gains tax. |
| CL-0010 Giulia Ferraro | A house in Tuscany, and gold she asked for in writing. Reads Italian. |
| CL-0011 Park Hyun-woo | A third of his wealth in one chip maker, after selling his chip-equipment company. Reads Korean, for which there are no letter templates. |
| CL-0012 Vivian Ho Wai Man | The same problem as CL-0001, in Hong Kong, where there is no tax reason to wait. Reads Traditional Chinese. |
| CL-0013 Pornthip Srisuk | The same problem again, in Thailand, where the losses are worth something. |
| CL-0014 Tran Minh Chau | Three obligations, each covered on its own and tight together. |
| CL-0015 Liu Zhen | An apartment for his parents, owed in renminbi. Reads Simplified Chinese. |
| CL-0016 Klaus Reinhardt | Content, retired, and one point over a single band. Reads German. |
| CL-0017 Siddharth Rao | Bonds below the floor after a good year for equities. |
| CL-0018, CL-0019 | Nothing outstanding — and the book says so rather than leaving them blank. |
| CL-0020 Benjamin Cho | His concentration sits in a custody account, where no mandate band can see it. |

Planted alongside them are the traps a careful engine has to get right: cash
needs in local currency, lending value that is not market value, custody accounts
that are wealth but not mandate, a fifteen-month-old mark securing a loan, and a
written waiver versus a mere acknowledgement.
