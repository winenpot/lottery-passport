# Glossary

Words that mean something specific in this project. When two people (or the
code and the rewards sheet) use different words for the same thing, the row
says so.

| Term | Means | Not to be confused with |
|---|---|---|
| **City (passport city)** | A TorshX **flavor**, which is a product **SKU**: TorshX Tokyo, TorshX Pattaya, ... Seven of them: Paris, Berlin, Pattaya, Mexico, Madrid, Tokyo, Moscow (`CityCode` in `app/domain/codes.py`). Every code batch belongs to one, the code prefix encodes it (`TO-...`), and `passport_progress` counts per city. Persian: «طعم». | A real city where lounges are. |
| **Flavor / taste / طعم / SKU** | Same as passport city. "Discover three flavors" in the rewards sheet = valid codes from three different passport cities (three SKUs). | |
| **Team** | In the rewards sheet («انتخاب تیم طعم»): the flavor a player belongs to, so one of the passport cities. Membership is exclusive (one team at a time). 5 codes of a flavor (lifetime) unlock that team and its badge; the player chooses a team among the unlocked flavors; after joining, switching is locked for 30 days, then open to any other unlocked flavor (new 30-day lock each time), see [vault/Decisions.md](vault/Decisions.md) 2026-10-15. Team ranking in the league is per flavor. All seven flavors ship to the lounges, so there are seven teams. | A lounge or a squad. |
| **Lounge / venue / branch / شعبه** | An OxinGame gaming center (`venues` table): id, Persian name, Persian street address, location city, optional public IP. | |
| **Location city** | A real city with lounges: Tehran, Ahvaz, Mashhad, Isfahan (`SUPPORTED_CITIES` in `app/domain/venues.py`; `GET /config` fields `location_cities` and `venues[].location_city`; DB column `venues.city`). | Passport city (flavor). |
| **Coin** | Spendable reward currency, ledger-backed (`coin_ledger_entries`). | League points. |
| **Diamond** | Second currency in the rewards sheet: coins convert to diamonds in a monthly window. Not built. | |
| **League points** | Rewards-sheet ranking counter, separate from coins, not spendable, monthly reset. Not built. | Coins. |
| **Entry** | One chance in a passport city's draw; `passport_progress.points`. Parked for the MVP (ADR 0009). | |
