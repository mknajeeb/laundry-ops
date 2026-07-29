# WF PRE/POST Weight Stabilization — prepared repair plan (NOT EXECUTED)

Date prepared: 2026-07-29
Org: 3
Selected day: 2026-07-29
Branch: fix/wf-pre-post-weight-stabilization
Base: 467e8a49

Dry-run by default. Cannot write without explicit `--apply`.

## Guards (mandatory before any apply)

1. Exact before-state check per bag (`pre_weight_lbs`, `post_weight_lbs`, `effective_status`, `manager_edit_version`).
2. Abort bag if before-state drifted since validation snapshot.
3. Skip when `corrected_pre_weight_lbs` / `corrected_post_weight_lbs` / manager weight source present.
4. Do **not** change membership, Rush/Non-Rush, Review/Completed/Pending, or Release A completion event.
5. If `completion_event_would_change` is true → manager-review only.
6. Write audit row per bag (before/after, observation run, resolution status, actor).
7. Update Shift Monitor day bag PRE/POST (+ snapshot weight fields) only; then recompute productivity through canonical path.
8. No push/deploy in this phase.

## Safe automatic requirements

All of the following must hold:

- before-state matches validation snapshot
- current-cycle event chain complete (entry + garments-reviewed + POST event)
- selected POST event deterministic
- portal observation confirmed (`CONFIRMED` or `EQUAL_VALUES_CONFIRMED`)
- no manual correction
- no conflicting observation remains

## Buckets (Jul 29 read-only, conservative)

| Bucket | Count |
|--|--|
| Safe automatic correction | 36 |
| Already correct | 59 |
| Manual protected | 1 |
| Insufficient evidence | 3 |
| Needs manager review | 1 |

### Safe automatic correction (36)

```
05FU9VW8C8
18RRTGC65A
1HU281FWI7
1YOJWNUNEG
23Z607KK9R
3CGQ2592P4
3N5IJONMQB
456UYUOG6V
46HHJ7O2LE
4HDNWRB6NO
52QTT5IR0J
58P558D7ZD
6Q50OQ1VX8
6S462TZNON
6UMBZB1RXE
759GKCL3S7
79YHF491I7
7HZ2CGL6K6
7LGDZEQPHG
7MQYB3XE42
7O5PULVDVN
82ENM03UVN
8WXN79QPW4
951N3THGGR
9J8WRKNZAS
9L32AGFJPX
9QTPNSBYFG
9UK8ERRMHT
BLFJEDJLSI
BWGWN0O8ZE
D18ZSHL6XA
D8GCUPTXO7
D96VKIP5PN
DGEAVNHVLD
EK7PVD9UJX
EVC2UIC87Z
```

### Already correct (59)

```
07YRORDKCU
0B3APPV71R
0CHDIA263C
0GATNBN12R
0JZGIBVPPO
0XL5ZDYDD8
1M4WVBKGFW
1TFNU1P9XK
23MQL2K3F7
2LI902AJM1
2LZC7IU7LS
3CDH3I7B4V
40OE0W1AQS
48S25FQ2HH
4B5WDCL94P
4EYFY6PWLM
4H1ONIMJVV
4I1PQDBP5R
4IOZE7O3TQ
4IYB21DZ70
547FOOKRE4
5BVV3F1VIO
5D8P5M9TNC
5QA3QQYCOY
5TTHT9ANTX
61GLOLDAA7
65PCQQRAWC
68H5X5SESG
77B9OMHXNQ
7GI299IAR1
7LZNV7H30O
7TZ36VMOMI
7VLYV5MCHV
81Q24SXAE5
8S9QP5W4TE
8Y3IWYIFCF
97ZU9X8GLT
98T5WWOHEU
9R8RFFIG6L
9RD63TNIRY
A7J3EBC2QW
AAR7RM0DSL
AGFERC4YS1
B7OJ9I7E3M
BG4GZXCWPX
BIAOPS4RWC
BXA1UK9B2P
CJ2VMR9FTJ
CR7GKATK6M
DBEZ6FXIWV
DFCO1FK1EY
DU2E2YGTW5
DZ130LCJZ1
E5MON459OO
E6TD4ROHQD
EZ29RTTOVT
EZMSTPNIIG
F18VCD6ZIL
F5DV8FL5RU
```

### Manual protected (1)

```
51A40WOC3G
```

### Insufficient evidence (3)

```
9BPYQ4WPNA
DF4YSUSLM5
ELJZJRVNJ5
```

### Needs manager review (1)

```
F33G8I34B4
```

## Productivity impact (read-only; NOT applied)

- Affected bags: 38
- Affected employees: 8
- Total POST pound delta: 78.0
- Credited PRE pound delta: 0 (EP credit uses PRE; ranking unchanged)
- Ranking changes: False
- Day open: True

Full machine-readable report: `/tmp/wf_weight_stabilization_final_validation.json`

## Apply order (when approved)

1. Deploy code (current-cycle resolver + POST reconcile attach).
2. Dry-run repair script with before-state guards.
3. Apply safe automatic only.
4. Leave insufficient-evidence / manager-review / manual-protected for operators.
5. Re-validate surfaces: Shift Monitor = At Vendor = Employee Productivity PRE/POST/status.

## Not executed

Production data changed: No
Push status: NOT PUSHED
Deployment status: NOT DEPLOYED
Release B included: No
