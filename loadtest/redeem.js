// Load test for staging: redemptions plus the reads a lounge evening produces.
//
// Open-model load (constant-arrival-rate): requests are sent on a fixed
// schedule whether or not the server keeps up, so slow responses show up in
// the percentiles instead of silently lowering the load (coordinated
// omission). See docs/TESTING.md#load-test.
//
//   uv run python -m scripts.loadtest_sessions --count 2000 --output loadtest/sessions.csv
//   (generate and activate a TEST batch on staging, copy its CSV to loadtest/codes.csv)
//   k6 run -e BASE_URL=https://staging.play.example.ir -e REDEEM_RPS=20 -e READ_RPS=300 loadtest/redeem.js
//
// The load generator's IP must be in lounge_ips.conf on staging, or nginx's
// per-IP limit (10 r/s) is what you end up measuring.

import http from "k6/http";
import { check } from "k6";
import { SharedArray } from "k6/data";
import exec from "k6/execution";

const BASE_URL = __ENV.BASE_URL || "https://staging.play.example.ir";
const DURATION = __ENV.DURATION || "5m";

const sessions = new SharedArray("sessions", () =>
  open(__ENV.SESSIONS_CSV || "./sessions.csv").trim().split(/\r?\n/).slice(1),
);
// codes.csv is the generator output: batch_id,city,printed_code,code,qr_url
// (Python's csv module writes CRLF line endings, hence the \r?\n splits.)
const codes = new SharedArray("codes", () =>
  open(__ENV.CODES_CSV || "./codes.csv")
    .trim()
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split(",")[3]),
);

export const options = {
  scenarios: {
    redeem: {
      executor: "constant-arrival-rate",
      exec: "redeem",
      rate: Number(__ENV.REDEEM_RPS || 20),
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 100,
      maxVUs: 1000,
    },
    read: {
      executor: "constant-arrival-rate",
      exec: "read",
      rate: Number(__ENV.READ_RPS || 300),
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 200,
      maxVUs: 2000,
    },
  },
  thresholds: {
    "http_req_failed{scenario:redeem}": ["rate<0.01"],
    "http_req_duration{scenario:redeem}": ["p(99)<500"],
    "http_req_failed{scenario:read}": ["rate<0.01"],
    "http_req_duration{scenario:read}": ["p(99)<300"],
    dropped_iterations: ["count<1"],
  },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "p(99.9)", "max"],
};

function asUser(index) {
  return {
    headers: {
      Cookie: `lottery_passport_session=${sessions[index % sessions.length]}`,
      "Content-Type": "application/json",
      "X-Requested-With": "loadtest",
    },
  };
}

export function redeem() {
  const index = exec.scenario.iterationInTest;
  // Each code is used once while there are enough codes; a reuse by another
  // user is a legitimate 409, not a failure.
  const code = codes[index % codes.length];
  const response = http.post(
    `${BASE_URL}/api/v1/redemptions`,
    JSON.stringify({ code }),
    { ...asUser(index), responseCallback: http.expectedStatuses(200, 409) },
  );
  check(response, { "redeemed, replayed or already used": (r) => r.status === 200 || r.status === 409 });
}

export function read() {
  const index = exec.scenario.iterationInTest;
  const path = index % 2 === 0 ? "/api/v1/me/wallet" : "/api/v1/me/passports";
  const response = http.get(`${BASE_URL}${path}`, asUser(index));
  check(response, { "200": (r) => r.status === 200 });
}
