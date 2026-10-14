// Browser-side mirror of app/domain/codes.py (parse only; generation stays
// on the server). Formats mirror docs/frontend/code-formats.json; keep both
// in sync with app/domain/codes.py (see docs/CODES.md#adding-a-code-format).

export const FORMATS = {
  "v2-b10": {
    formatId: "v2-b10",
    alphabet: "0123456789ABCDEFGHJKMNPQRSTVWXYZ",
    bodyLength: 10,
    grouping: [4, 4, 3],
    aliases: { O: "0", I: "1", L: "1" },
  },
  "city2-b9": {
    formatId: "city2-b9",
    alphabet: "0123456789ABCDEFGHJKMNPQRSTVWXYZ",
    bodyLength: 8,
    grouping: [3, 3, 3],
    aliases: { O: "0", I: "1", L: "1" },
  },
};

export const DEFAULT_FORMAT_ID = "city2-b9";

const CITY_CHECK_INDEX = { PR: 1, BE: 2, PA: 3, ME: 4, MA: 5, TO: 6, MO: 7 };
const EASTERN_DIGITS = /[۰-۹٠-٩]/g;
const SEPARATORS = /[\p{Zs}\p{Pd}\p{Cf}\t\r\n_.]/gu;
const PREFIX_LENGTH = 2;

function canonicalLength(format) {
  return PREFIX_LENGTH + format.bodyLength + 1;
}

function formatsByLength() {
  return Object.values(FORMATS).reduce((byLength, format) => {
    byLength.set(canonicalLength(format), format);
    return byLength;
  }, new Map());
}

function toAsciiDigit(character) {
  const code = character.charCodeAt(0);
  return String(code >= 0x06f0 ? code - 0x06f0 : code - 0x0660);
}

export function normalizeCode(raw) {
  return raw
    .normalize("NFKC")
    .replace(EASTERN_DIGITS, toAsciiDigit)
    .replace(SEPARATORS, "")
    .toUpperCase();
}

// Drop a scanned QR's URL, keeping only the code it carries. The printed QR
// puts the code in the path, "https://torshx.com/b/TO-ABC-DEF-GHJ" (the text
// after the last "/"); the fragment form "https://torshx.com/r#TO-ABC-DEF-GHJ"
// is still accepted (the text after "#"). A bare typed code (no "#" or "://")
// passes through unchanged.
function stripQrWrapper(raw) {
  const text = raw.trim();
  if (text.includes("#")) return text.slice(text.lastIndexOf("#") + 1);
  if (text.includes("://")) return text.slice(text.lastIndexOf("/") + 1);
  return text;
}

function luhnModNSum(values, startFactor, base) {
  let factor = startFactor;
  let total = 0;
  for (let i = values.length - 1; i >= 0; i -= 1) {
    const addend = factor * values[i];
    total += Math.floor(addend / base) + (addend % base);
    factor = factor === 2 ? 1 : 2;
  }
  return total;
}

function checkIsValid(prefix, body, check, format) {
  const base = format.alphabet.length;
  const values = [
    CITY_CHECK_INDEX[prefix],
    ...[...(body + check)].map((c) => format.alphabet.indexOf(c)),
  ];
  return luhnModNSum(values, 1, base) % base === 0;
}

// Returns {ok: true, city, canonical, formatId} or
// {ok: false, problem: "malformed" | "mistyped"}.
export function parseCode(raw) {
  const text = normalizeCode(stripQrWrapper(raw));
  if (!/^[\x00-\x7F]*$/.test(text)) return { ok: false, problem: "malformed" };

  const format = formatsByLength().get(text.length);
  if (!format) return { ok: false, problem: "malformed" };

  const prefix = text.slice(0, PREFIX_LENGTH).replaceAll("0", "O");
  if (!(prefix in CITY_CHECK_INDEX)) return { ok: false, problem: "malformed" };

  const tail = [...text.slice(PREFIX_LENGTH)].map((c) => format.aliases[c] ?? c).join("");
  if ([...tail].some((c) => !format.alphabet.includes(c))) {
    return { ok: false, problem: "malformed" };
  }

  const body = tail.slice(0, format.bodyLength);
  const check = tail.slice(format.bodyLength);
  if (!checkIsValid(prefix, body, check, format)) {
    return { ok: false, problem: "mistyped" };
  }
  return { ok: true, city: prefix, canonical: prefix + tail, formatId: format.formatId };
}

// "TO7KQ2M9XH4R6" -> "TO-7KQ2-M9XH-4R6" (also useful while the user types).
export function formatPrinted(canonical, formatId = DEFAULT_FORMAT_ID) {
  const format = FORMATS[formatId];
  const rest = canonical.slice(PREFIX_LENGTH);
  const parts = [canonical.slice(0, PREFIX_LENGTH)];
  let position = 0;
  for (const size of format.grouping) {
    parts.push(rest.slice(position, position + size));
    position += size;
  }
  return parts.filter(Boolean).join("-");
}
