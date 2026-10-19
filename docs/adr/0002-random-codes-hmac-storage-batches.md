# ADR-0002: Random printed codes, HMAC storage, batches with a kill switch

**Status:** Accepted
**Date:** 2026-10-07
**Deciders:** Backend developer; Mehdi and the factory for the printed format

## Context

Codes printed on drinks are the security boundary of the campaign: each is a draw entry and
coins, and the prizes include foreign trips. The first version used 2 letters + 7 digits
(10 million combinations per city). With 500,000 codes per city, 1 in 20 random guesses is
valid; with 50,000 codes and 8 digits, 1 in 2,000. Either is easy to farm with a script and a
few dozen accounts. A "formula" (derivable codes) is worse: once someone finds the pattern,
every code is known.

## Decision

- Codes are **random**: city prefix + 10 Crockford Base32 characters (50 bits) + a Luhn mod 32 check character. Format and math in [CODES.md](../CODES.md).
- The database stores only `HMAC-SHA256(pepper, code)`; the pepper lives in the environment, never in the database or git.
- Codes belong to **batches** (one per print run) with states `generated` → `active` → `void`. Nothing is redeemable until activated; a leaked batch is voided in seconds.

## Options considered

### Option A: random 50-bit codes + HMAC + batches (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low (implemented and tested) |
| Cost | 13 characters to print |
| Security | 1 valid in ~2.25 billion guesses at 500k codes/city |
| Operations | Printer file must be handled carefully (it is the only plaintext) |

### Option B: digits only, longer (14 digits + check digit)

Same idea if the printer cannot print letters: 1 in 200 million at 500k codes. Acceptable fallback.

### Option C: signed codes (code = serial + truncated MAC)

Verifiable without a database lookup, but a short MAC is guessable and single-use still needs
a database row. No benefit here.

### Option D: sequential or formula-based codes

Rejected: one leaked or reverse-engineered pattern compromises every code.

## Trade-off analysis

Length is the price of security; the QR removes most typing, and the check character turns a
typo into a friendly "check this character" message instead of a support ticket.

## Consequences

- Easier: brute force is pointless; a leak is contained by voiding one batch.
- Harder: the printer CSV must be transferred and destroyed carefully; the pepper can never change once codes are printed (all hashes depend on it), so it needs a backup holder.
- Revisit: if the factory can only print digits, switch the generator to 14 digits + check digit before the first print (small change in `app/domain/codes.py`).

## Action items

1. [x] Implement format, generator, batch CLI, tests.
2. [ ] Confirm printable format and placement with the factory (P01, P02).
3. [ ] Store the production pepper with a backup holder (B06).
4. [x] Guard against a wrong/rotated pepper at startup and `/ready`, not just at redemption
   time (`code_batches.pepper_fingerprint`; see [CODES.md](../CODES.md#5-batches)).
