# Chronology capture gap — Charles Emery `32GSYJK2BA` (2026-08-20)

## Why 3:09 PM weigh-entry was missing from DB

1. Last ingested chronology for this bag (upload batches 3713/3714) ended at **1:44 PM ET** (drying / start-cleaning).
2. Live Rinse later showed additional scans including **weight-entry 3:09 PM ET** (Florentina) after garments-reviewed / complete-cleaning.
3. Presence marked the bag **inactive / disappeared from at_vendor** after afternoon scrapes, so **list-page** scan-events crawls no longer visited the row.
4. No targeted `?q=BAGID` chronology refresh ran for day-membership bags that left the list.

**Not** primarily: page-budget alone (the bag simply was not on pages being crawled).

## Fix (narrow — do not change freshness supervisor)

- Use existing **`scrape-targeted-bags.mjs`** (now also stamps Pre-clean / workitem weights) to refresh chronology for day bags missing later scans.
- Production list scrape (`scrape-scan-events.mjs`) now extracts:
  - **Pre-clean weight** from `.preclean-info` (`dt`/`dd`)
  - **POST candidate** from `td.number_of_wash_and_fold_lbs` when a post-processing weigh-entry exists
  - Writes `Weight` / `Weight Source` / `Weight Role` onto the corresponding weigh-entry CSV rows

**Overlap with freshness:** wiring targeted refresh into the ACA supervisor / lane leases would touch shared scheduled-scrape runtime. **Not done in this workstream.** Run targeted refresh as a separate ops/job until freshness owners agree.

## Authoritative fields (proven live 2026-08-20)

| Role | Rinse location | Example (Emery) |
|------|----------------|-----------------|
| PRE | vendorinline `.preclean-info` → `Pre-clean weight:` | **12.20 lbs** |
| POST | After post weigh-entry: workitem `td.number_of_wash_and_fold_lbs` (same mutable field as list LBS) | **11.3 LBS** |
| List `wf_lbs` | Cleaner-ticket list Weight column | **11.3** ≠ PRE — mutable latest |

Events CSV still has no Weight column from Rinse itself; we **inject** Weight from the DOM fields above onto the correct weigh-entry rows at scrape time.
