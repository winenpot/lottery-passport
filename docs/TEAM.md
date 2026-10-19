# Team: roles, expectations, working agreements

Three people build this: you (backend, data, operations, and in practice technical lead),
Arman (frontend, external), Mehdi (marketing manager, owner of the business side). The CEO
decides money and scope. This page says who owns what and how we work together.

## Contents

- [Who owns what](#who-owns-what)
- [What to expect from yourself](#what-to-expect-from-yourself)
- [Working with Arman](#working-with-arman)
- [Working with Mehdi](#working-with-mehdi)
- [A 90-minute field visit](#a-90-minute-field-visit)
- [Message templates](#message-templates)

## Who owns what

R = does it, A = decides/accountable, C = consulted, I = informed.

| Area | You | Arman | Mehdi | CEO |
|---|---|---|---|---|
| Architecture, data, security, hosting | A/R | C | I | I |
| API contract | A/R | C | I | |
| Player app (PWA) | C | A/R | C | I |
| Code format, generation, batches | A/R | I | C | I |
| Factory and printing | C | | A/R | I |
| Prizes, economy, challenge content | C | I | A/R | A (budget) |
| Legal, T&Cs, draw rules | C | | R | A |
| Lounge relations, staff training | C | | A/R | I |
| Launch go/no-go | R | C | R | A |
| Production incidents | A/R | C | I (player comms: R) | I |

## What to expect from yourself

You are the technical lead whatever your title says. In practice that means:

- **Guard the scope.** The most valuable sentence you will say is "after launch". Use the cut line in [ROADMAP.md](../ROADMAP.md#scope-must-should-later) and the swap rule; write every swap down.
- **Make decisions visible.** Short written decisions (an ADR, a line in the board, a chat message that says "decided: ...") protect you when someone asks later why something is the way it is.
- **Own correctness and security.** Codes, coins, sign-in and the admin panel are where mistakes cost money and trust; those parts get tests against PostgreSQL before they ship.
- **Unblock Arman first.** A blocked frontend developer costs a day per day. Answer contract questions the same day; keep staging up.
- **Ask early.** If an external dependency (SMS template, server, factory) is late, say so the same day with its consequence and a fallback, not on D14.
- **Keep a sustainable pace.** 11 working days is a sprint, not a marathon of all-nighters; tired people ship double-crediting bugs. Protect D13 as the buffer.
- **Learn in small doses.** One hour a day of the [learning path](GAMIFICATION.md#learning-path-about-8-hours) is enough; you already know the audience.

## Working with Arman

The goal: Arman never waits for you and never guesses.

1. **Contract first.** [API_CONTRACT.md](API_CONTRACT.md) is the source of truth. A change starts as a pull request to that file, which Arman reviews; code follows. Planned endpoints already have their final shapes, so he builds against mocks (Mock Service Worker) from day 1.
2. **Staging is the shared reality.** From D2 he points his dev server's `/api` proxy at staging. Every backend item counts as done only when it is on staging.
3. **Same day answers.** One chat thread for the project; questions answered the same working day. A 10-minute call beats a 20-message thread.
4. **Visible progress.** He pushes to a repository you can see, with a short note per day (done / next / blocked). Demos on staging at M1, M2, M3 instead of status meetings.
5. **Definition of done for a screen**: matches the contract, handles every error code with Persian copy, has loading/empty/offline states, works on a real Android and iPhone, passes the CSP.
6. **What he needs from you**: the contract, staging with test data (users, a test batch, challenges), 20 test QR URLs, the brand assets (via Mehdi), the code-check helper ([docs/frontend/](frontend/)).
7. **What you need from him**: a `dist/` build you can deploy, no external CDNs or fonts, no tokens in `localStorage`, and early warning if anything in the contract is awkward.

About the QR question in your message to him: a "QR with a variable" is just a URL that contains
the code (`https://torshx.com/b/TO-HA1-NQC-C32`). You generate those URLs; his job is the
`/b/:code` page. The SMS autofill question was the right one to ask him: it is frontend work
(`autocomplete="one-time-code"` + the WebOTP API), plus the SMS template you get approved.

## Working with Mehdi

The idea and the deal are his; the product and its risks are yours. The way through is to make
him successful on your terms, in writing.

- **Give him decisions, not problems.** Every question comes with a default and a deadline ([decision list](TODO.md#decisions-needed-by-d2)). Silence means the default.
- **Use his strengths.** Factory, legal, lounges, content, comms: these are his items (M01–M15) and they are on the critical path. Make that explicit to him and to the CEO.
- **Bring him to the users.** The field visit below lets him see the audience with his own eyes; it changes opinions faster than arguments.
- **Write things down.** After any meeting, a three-line message: decided, owner, deadline. If the CEO asks later, the record answers.
- **Disagree on evidence.** "Gamers will mock this, here is what I saw at the lounge / here is what three players said" works better than "this is wrong".
- **Never surprise him in front of the CEO.** Tell him first, then the CEO, then together.

## A 90-minute field visit

Week 1 (by D8), you and Mehdi, at the busiest lounge in the evening (M15).

- **Observe (30 min)**: where people buy drinks, what they do while waiting, which games are on which screens, where a poster or a TV leaderboard would actually be seen.
- **Talk to 8–10 players (45 min, 5 minutes each)**, with permission, no recording of faces:
  1. What do you play here, and how often do you come?
  2. Which of our drinks do you know? Which do you buy?
  3. (Show the passport mock-up) What would make you scan this every time?
  4. What prize would actually make you care? What would feel fake?
  5. Would you post about it? Where (Instagram story, Telegram, nowhere)?
  6. What would make you stop using it?
- **Debrief (15 min)**: three things that surprised you, one challenge to change, one thing to cut.

## Message templates

**Decision list to Mehdi (Persian, D1)**

> سلام مهدی جان، وقت بخیر.
> برای اینکه لانچ ۲۹ مهر عملی باشد، این تصمیم‌ها باید تا پنجشنبه ۱۶ مهر گرفته شوند. برای هر کدام یک پیش‌فرض گذاشته‌ام؛ اگر تا آن روز تصمیم دیگری نگیریم، پیش‌فرض اجرا می‌شود:
> ۱. محل چاپ کد روی محصول: زیر درب یا زبانه، طوری که قبل از باز کردن دیده نشود.
> ۲. چاپ QR اختصاصی برای هر واحد ممکن است یا فقط متن؟ پیش‌فرض: کد متنی روی هر واحد + یک QR ثابت روی برچسب.
> ۳. تعداد کد برای هر شهر و تاریخ چاپ. پیش‌فرض: یک بچ آزمایشی ۵٬۰۰۰ تایی توکیو.
> ۴. سکه برای هر کد: ۱۰ سکه. سقف روزانه هر نفر: ۲۰ کد.
> ۵. لیست جوایز و بودجه؛ پیش‌فرض: فروشگاه جوایز بعد از لانچ باز می‌شود.
> ۶. نظر حقوقی درباره قرعه‌کشی (مجوز، شرایط سنی، شرایط جوایز سفر) تا ۲۶ مهر.
> لیست کامل با جزئیات در فایل TODO هست. ممنون.

**Daily check-in (to the group, any language)**

> Done yesterday: ... / Today: ... / Blocked by: ... (owner, needed by)
