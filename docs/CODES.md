# Printed codes

The specification for the codes printed on our drinks: format, why it looks like this, how the
app reads it, and how a print file travels from our server to the factory without leaking.
Section 1 is written to be handed to the factory as-is.

## Contents

- [1. Specification for the factory](#1-specification-for-the-factory)
- [2. Why this format](#2-why-this-format)
- [3. What the server accepts](#3-what-the-server-accepts)
- [4. The check character](#4-the-check-character)
- [Validating codes in the browser](#validating-codes-in-the-browser)
- [5. Batches](#5-batches)
- [Print runs: weighted, from the 1,000,000-code pool](#print-runs-weighted-from-the-1000000-code-pool)
- [Handing codes to the printer](#handing-codes-to-the-printer)
- [6. Quality control](#6-quality-control)
- [7. Adding a code format](#7-adding-a-code-format)
- [8. Plan B situations](#8-plan-b-situations)

## 1. Specification for the factory

| Item | Value |
|---|---|
| Characters per code | 11: two city letters, then 9 characters from `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (no I, L, O, U) |
| Printed form | Grouped with dashes: `TO-HA1-NQC-C32` (14 characters with dashes) |
| City prefixes | Paris `PR`, Berlin `BE`, Pattaya `PA`, Mexico `ME`, Madrid `MA`, Tokyo `TO`, Moscow `MO` |
| Uniqueness | Every unit has a different code; we supply them in a CSV, one row per unit |
| **Placement** | **Not visible until the drink is opened**: inside the cap / under the tab / under a peel layer. A code readable on a closed can can be harvested from shelves and vending-machine windows |
| Font | A clear sans-serif or monospace face, at least 2 mm character height; the dashes help reading |
| QR (if the printer can do variable QR) | Encodes the URL in the CSV column `qr_url`, e.g. `https://torshx.com/b/TO-HA1-NQC-C32` (path form, decision 2026-10-14; scheme, host and `/b/` lower-case because paths are case-sensitive). The code is in the path, so the proxy must not log `/b/*` paths and the app sends `Referrer-Policy: no-referrer` ([SECURITY.md](SECURITY.md)). Error correction level M. At about 0.5 mm per module the QR is roughly 2 cm square including its quiet zone; test before the run |
| If no per-unit QR is possible | Print the 11-character code per unit, plus one **static** QR on the label that opens `https://torshx.com/`; the player types the code |
| File we send | `batch_id, city, printed_code, code, qr_url` (UTF-8 CSV), plus a `.sha256` checksum file |
| Test print | 20 units with **test codes** before the real run; we scan and type them |

Current default format id: `city2-b9` (registered 2026-10-11, decision in
`docs/vault/Decisions.md`). The original `v2-b10` format (13 characters,
`https://.../r/CODE` path form) stays registered — nothing has been printed
in either format yet, but formats are never un-registered once real codes
could exist under them. `scripts.generate_codes --format <id>` picks a
non-default format when needed.

## 2. Why this format

The first version used two letters + 7 digits: 10 million combinations per city. Guessing is
the attack, and the number that matters is "how many guesses per valid code":

| Format | Codes printed per city | 1 valid code per... | Codes stolen per day by 1,000 throwaway accounts x 30 guesses |
|---|---|---|---|
| 7 digits (v1) | 500,000 | 20 guesses | 1,500 |
| 7 characters, digits + `@#$%&` | 500,000 | 342 guesses | ~88 |
| 8 digits | 50,000 | 2,000 guesses | ~15 |
| **10 characters Base32 (v2)** | 500,000 | **2.25 billion guesses** | ~0 (one every ~200 years) |
| 14 digits (fallback if only digits print) | 500,000 | 200 million guesses | ~0 (one every ~18 years) |

Symbols do not help much and hurt a lot: `#` starts the fragment in a URL (the rest never
reaches the server), `%` and `&` have special meanings in URLs, and players have to switch
keyboard layers to type them. **Length is what buys security.**

A code is random, not computed: there is no formula to discover. The server stores only
`HMAC-SHA256(pepper, code)`; even with a copy of the database, nobody can list valid codes
without the pepper ([ADR-0002](adr/0002-random-codes-hmac-storage-batches.md)).

## 3. What the server accepts

People mistype, use Persian keyboards and paste from chats. Before checking anything, the
server (`app/domain/codes.py`) normalizes the input:

1. If the input is a scanned QR URL, keep only the code: the text after the last `/`
   (printed path form `/b/<code>`), or after the last `#` if there is one (fragment form, still accepted).
2. Unicode NFKC (full-width characters become normal ones).
3. Persian `۰–۹` and Arabic-Indic `٠–٩` digits become `0–9`.
4. Spaces, every kind of dash, underscores, dots and invisible characters (ZWNJ, direction marks) are removed.
5. Upper case.
6. In the prefix, `0` is read as `O` (`T0` → `TO`). After the prefix, `O` → `0` and `I`, `L` → `1`.

Then: wrong length, unknown prefix or a character outside the alphabet → `CODE_MALFORMED`;
check character wrong → `CODE_MISTYPED`; otherwise the hash is looked up.

## 4. The check character

The last character is a **Luhn mod 32** check over the city's fixed index (`PR`=1 ... `MO`=7)
followed by the 10 random characters. Measured on 2,000 random codes:

| Error | Detected |
|---|---|
| Any single character changed | 100% (682,000 of 682,000) |
| Wrong city prefix | 100% (12,000 of 12,000) |
| Two neighbouring characters swapped | 99.8% (only `0`↔`Z` swaps slip through) |

This lets the app say "check this character" before calling the server, and it costs no
security: anyone can compute check characters, so they reveal nothing. The city indexes,
the alphabet and the algorithm are **frozen** once the first batch is printed.

## Validating codes in the browser

[`docs/frontend/codes.js`](frontend/codes.js) is a dependency-free JavaScript copy of the
parser for Arman. It loads its format definitions from
[`docs/frontend/code-formats.json`](frontend/code-formats.json), which is generated by
`uv run python -m scripts.code_batches formats` and must stay in sync with the Python
registry. It was checked against the Python parser on 9,007 generated inputs (valid
codes, single-character typos, Persian digits, dashes, look-alikes) with zero differences.
[`docs/frontend/code-test-vectors.json`](frontend/code-test-vectors.json) holds 40 of those
cases (one for each registered format) for his unit tests. Three guards keep them in sync:

- `tests/unit/test_code_vectors.py` — fails if the Python parser drifts from the vectors,
  if code-formats.json diverges from the server's spec, or if any registered format has no
  valid vector.
- `docs/frontend/codes.test.mjs` — Node script, same vectors and registry check on the JS
  side; run with `node docs/frontend/codes.test.mjs`.
- `tests/unit/test_code_vectors.py::test_browser_validator_passes_the_vectors` — calls the
  Node script from pytest (skipped when `node` is not installed).

```js
import { parseCode, formatPrinted } from "./codes.js";

const result = parseCode(input.value);       // {ok, city, canonical, formatId} or {ok: false, problem}
if (!result.ok && result.problem === "mistyped") showHint("یکی از کاراکترها اشتباه است");
input.value = result.ok ? formatPrinted(result.canonical) : input.value;
```

The browser only checks the shape. Whether a code exists and is unused is decided by the server.

## 5. Batches

One **batch** = one print run of one city. States: `generated` (exists, cannot be redeemed),
`active` (redeemable), `void` (dead; already-redeemed codes stay redeemed).

```bash
# generate (on the production server; details in OPERATIONS.md)
python -m scripts.generate_codes --city tokyo --quantity 50000 --coins-per-code 10 \
    --label "Tokyo can run 1" --base-url https://play.<domain> --output /out/tokyo-run1.csv
python -m scripts.code_batches list
python -m scripts.code_batches activate <batch-id>    # when the product reaches the lounges
python -m scripts.code_batches void <batch-id>        # leak, misprint, recall
```

`coins_per_code` is set per batch (0 = entries only). Keep `generated` until the product is
actually on sale: codes found early (factory staff, warehouse) are worthless until then.

**Pepper guard**: every batch generated from here on records the fingerprint of the pepper it
was generated with (`code_batches.pepper_fingerprint`, HMAC of a fixed label keyed by the pepper
— never the pepper itself). At startup, and on every `GET /ready` poll, the app refuses to serve
if an ACTIVE batch's fingerprint does not match the pepper it is running with now. Without this,
a misconfigured `REDEMPTION_CODE_PEPPER` (wrong value, stale secret, another environment's
pepper copied by mistake) would silently turn every redemption into `CODE_INVALID` — indistinguishable
from a bad scan — until support tickets added up. A `NULL` fingerprint (batches generated before
this guard existed) is never flagged. See [ADR-0002](adr/0002-random-codes-hmac-storage-batches.md).

## Print runs: weighted, from the 1,000,000-code pool

Production codes are issued as **print runs** (decision 2026-10-21). The campaign pool is
1,000,000 codes split evenly over the seven flavors: 142,857 each (7 x 142,857 = 999,999;
the remainder is dropped). A run asks for `k` codes and one weight per flavor, the weights
adding up to exactly 1. Flavor `i` gets `n_i` codes, `w_i * k` rounded so the counts add up
to exactly `k` (largest remainder, so each `n_i` is within 1 of `w_i * k`). The run is
refused **as a whole** if any flavor would go past its quota (`n_i > remaining_i`). Taking
a flavor's last code is allowed. Runs repeat until a flavor is used up.

- The pool is a **quota, not stored codes**. Picking `n_i` codes at random from a pile of
  random codes is the same as generating `n_i` fresh random codes. So each run draws fresh
  from the CSPRNG and no plaintext pool is ever kept to sample from. The database still
  knows every code that exists (as an HMAC), and each code can be claimed by exactly one
  player.
- Every code ever generated counts against its flavor's quota, including codes in voided
  batches and in batches made with `generate_codes` directly. The quota is read from
  `code_batches.quantity`.
- Each flavor in the run becomes one ordinary batch (`generated`, labelled
  `PR-<UTC time> <flavor> n/k`) with its own CSV in random order, a `.sha256`, and an
  `exported` event recording that checksum (so the format is frozen). A `manifest.json`
  records the weights, the split and the batch ids. It never contains codes.
- All or nothing: if generation fails half-way, every batch of the run is voided and its
  files are deleted. A Postgres advisory lock stops two runs from overlapping. The quota is
  re-read after the lock is taken.
- Weights are exact: decimals (`0.3`) or fractions (`1/7`). `--equal` means 1/7 each, and
  flavors left out weigh 0. Code: `app/domain/print_runs.py`, `scripts/print_run.py`.

```bash
python -m scripts.print_run --k 7000 --equal --dry-run      # split + quota table only
python -m scripts.print_run --k 7000 --weights "TO=0.3,PR=0.2,BE=0.1,PA=0.1,ME=0.1,MA=0.1,MO=0.1" \
    --coins-per-code 100 --base-url https://torshx.com --output-dir /out/run1
```

`--base-url` must be `https://torshx.com`: the in-app scanner accepts only that host, and
the apex redirects `/b/*` to the app. On a server, see
[OPERATIONS.md](OPERATIONS.md#code-batches-in-production). Activating, voiding and handing
over work per batch, exactly as above and below.

## Printing QR sheets for a test run

Needs the `codes-print` dependency group (`uv sync` includes it; the production image
does not, so run it on an operator machine). `scripts/qr_sheets.py` turns a batch CSV into a cut-ready PDF: one QR per code (encoding
the exact `qr_url` column), the printed code underneath as a manual-entry fallback, crop
marks at every cell, and the batch id plus `sheet n/N` in the page header. It is for test
prints and planning (a factory print run still works from the CSV directly, per section 1);
treat the PDF like the CSV — it is a plaintext copy of the codes.

```bash
uv run python -m scripts.qr_sheets --csv var/redemption-codes/tokyo-run1.csv \
    --paper A4 --per-page 50 --qr-mm 20 --output var/redemption-codes/tokyo-run1.pdf
```

The layout picks a columns x rows grid for `--per-page` codes on `--paper` (A4 or A3) and
refuses to run if a cell cannot hold `--qr-mm` plus the printed-code line and a cutting
margin — it never silently shrinks the QR below what you asked for. Defaults match the
factory spec: `A4 --per-page 50` lays out 5x10 at ~38x28mm cells; `A3 --per-page 120` lays
out 10x12 at ~28x34mm cells, both comfortably holding a 20mm QR.

Print at 100% scale ("actual size", never "fit to page"), then verify before trusting a
real run: measure a QR with a ruler, and scan it with an Android phone and an iPhone to
confirm it lands on the right URL (see "Test print" in section 1 and section 6).

## Handing codes to the printer

The CSV is the **only plaintext copy** of the codes. Treat it like cash.

1. Generate on the production server into `/root/batches` (mode 700); the file is created with mode 600 and a `.sha256` next to it.
2. Encrypt before it leaves the server: a password-protected 7-Zip archive with AES-256 and encrypted file names (`7z a -p -mhe=on tokyo-run1.7z tokyo-run1.csv`), or `age` if the printer's IT can use it. Use a long random passphrase.
3. Send the archive by one channel (company file share or in person on a USB stick), **the passphrase by another** (phone call). Never email both, never send the CSV in a chat app.
4. The printer verifies the checksum (`certutil -hashfile tokyo-run1.csv SHA256` on Windows, `sha256sum` elsewhere) and confirms it to you in writing.
5. After the run and quality control, the printer deletes the file and confirms in writing; you delete yours. Keep the encrypted archive in cold storage only until QC passes, then delete it too.
6. Write each step in a chain-of-custody note: batch ID, file name, checksum, who received it, when it was deleted.

If the file is lost before printing: void the batch and generate a new one. If it may have
leaked: void it, and follow the [code leak runbook](OPERATIONS.md#runbook-suspected-code-leak).

## 6. Quality control

- **Before the run**: the test print (20 units) is scanned with an Android phone and an iPhone and typed by hand on staging.
- **Each run**: the printer sends photos of 10 random units; you check them with `uv run python -m scripts.check_code "<code or scanned URL>"` (B28; a CLI today, not yet an admin UI panel), which says whether a code exists, its batch and status, and flags a corrupted pepper-fingerprint column on that batch — **without redeeming it**.
- **At launch**: one real unit is redeemed by a team member in production; note which.

## 7. Adding a code format

The server keeps a **format registry** (`app/domain/codes.py`). Every format is a
`CodeFormat` dataclass with its own `format_id`, alphabet, body length, grouping and
check scheme. Two formats are registered today (`city2-b9`, the default, and the
earlier `v2-b10`), and the system is built so adding another one is a mechanical
step — no surgery on the parser.

**When you need a new format** (the factory can only print digits, a future shorter
code for a small promo, etc.), do this in one PR:

1. Define and register a `CodeFormat` in `app/domain/codes.py`:

```python
MY_FORMAT = CodeFormat(
    format_id="my-format",
    body_length=14,  # plus 1 check character
    grouping=(5, 5, 5),  # must add up to body_length + 1
    alphabet="0123456789",
    aliases={},
    check_scheme="luhn-mod-n",
)
register_format(MY_FORMAT)
```

2. Add vectors for the new format to `docs/frontend/code-test-vectors.json`. Each
   valid vector needs a `"format_id"` field. The test
   `test_every_registered_format_has_valid_vectors` will fail if you forget.

3. Update `docs/frontend/code-formats.json` (run
   `uv run python -m scripts.code_batches formats` which regenerates it) and check
   `docs/frontend/codes.js` handles the new alphabet and grouping.

4. Run `node docs/frontend/codes.test.mjs` — it checks that codes.js, code-formats.json
   and the vectors are all consistent.

5. Update section 1 of this file (factory spec) for the new format if it will be
   printed, and note the format in `ARCHITECTURE.md`.

**Invariant once a batch is frozen**: `scripts.code_batches freeze <batch-id>`
records the format's SHA-256 fingerprint on the batch. On startup the application
checks every frozen batch's fingerprint against the live registry
(`app/domain/codes.py:verify_frozen_formats`). If the spec was changed after
freezing, startup fails loudly. Never change a registered format's spec once any
batch has been frozen with it — add a new format instead.

## 8. Plan B situations

**The factory can only print digits.** Register a new format before the first print run — see
[section 7](#7-adding-a-code-format). The new format uses `alphabet="0123456789"`,
`body_length=14`, `grouping=(5, 5, 5)` (Luhn mod 10 over 14 digits). The rest of the
system is format-agnostic; `scripts.generate_codes --format <new-format-id>` uses it.
Decide before generating anything for print.

**Codes in the old 2-letters + 7-digits format were already printed.** They cannot be made
safe, only less attractive: accept them with a much lower value (no coins, or entries only),
a strict per-account cap (for example 3 per day), every redemption visible in the daily
check, identity verification before any prize, and a switch to v2 for every later print run.
Tell the CEO in writing why.

**Products will not be printed in time for launch.** Print **code cards** with a local print
shop (variable-data printing, a few days): one batch per lounge, so a leak points at one lounge.
Cards stay in sealed, counted packs with the lounge manager, and staff hand one card per drink
sold. Activate a lounge's batch only when its packs arrive.
