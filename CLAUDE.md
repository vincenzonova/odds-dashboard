# CLAUDE.md — Agent Session Bootstrap

> This file is read by AI agents (Claude Code, Copilot, etc.) at the start of every session.
> It ensures agents understand the project before making changes.

---

## MANDATORY DEVELOPMENT WORKFLOW

Every code change MUST follow this 7-step sequence:

1. **READ DOCS** → Read relevant `docs/` files before touching any code
2. **CREATE DOCS** → Write/update documentation for the feature you're about to implement
3. **IMPLEMENT & TEST** → Make the code change AND write tests for new features
4. **UPDATE DOCS** → Update all affected documentation to reflect the changes made
5. **RUN ALL TESTS** → Run `pytest test_main.py -v` and confirm all tests pass
6. **DEPLOY** → Commit and push to main (Railway auto-deploys)
7. **RECHECK** → Verify the deployment works correctly on the live dashboard

**Do NOT skip steps. Do NOT commit if tests fail.**

### Key Rules

- **Tests are MANDATORY for new features** — every new feature must have corresponding test coverage
- **Documentation must ALWAYS be updated** — after any change, all affected docs must be brought up to date
- **Run tests after EVERY change** — no exceptions

---

## Step 1 — Read Docs First

Before making ANY code change, read the relevant documentation:

| If you're changing...                     | Read this first                                          |
|-------------------------------------------|----------------------------------------------------------|
| Merge logic, fuzzy matching, TEAM_ALIASES | `docs/CODE_DOCS.md` (Key Functions section)              |
| Scraper behavior                          | `docs/CODE_DOCS.md` (Scraper Architecture section)       |
| Dashboard JS/CSS                          | `docs/CODE_DOCS.md` (Dashboard section)                  |
| API endpoints or auth                     | `docs/CODE_DOCS.md` (API Endpoints section)              |
| Deployment or config                      | `docs/ARCHITECTURE.md`                                   |
| Business priorities or scope              | `docs/PRODUCT.md`                                        |
| Anything in main.py                       | `docs/CODE_DOCS.md` + `docs/ARCHITECTURE.md`             |

---

## Step 2 — Critical Gotchas (read before coding)

### Dashboard JS lives inside a Python f-string
All literal JS braces `{}` MUST be doubled `{{ }}` in `dashboard.py`.
Forgetting this causes Python crashes at runtime — not at test time.

### Fuzzy matching threshold is 0.70
The threshold in `fuzzy_match_event()` was raised from 0.55 to 0.70 to prevent false positives.
DO NOT lower it without explicit approval.

### merge_odds() has duplicate bookmaker protection
If a bookmaker already has odds for a merged event, incoming duplicates are skipped.
Do not remove this guard.

### SIGN_SWAP_MAP must stay in sync
When team order is reversed between bookmakers, signs are swapped via `SIGN_SWAP_MAP`.
If you add new market types, update this map.

### Scrapers: don't change what works
If a scraper is currently working and returning correct odds, do NOT refactor it without
confirming with the project owner first. **Stability > cleanliness.**

### Live-comparison uses print(), NOT logging

The `/api/live-comparison` endpoint and all of main.py uses `print()` for logging. Do NOT use `logger` or `logging` module — it will cause NameError crashes at runtime since no logger is configured.

### Betslip service is a separate Railway instance

The betslip service (`betslip_service.py`) runs on its own Railway deployment. The main service calls it via HTTP. If the betslip service is down, the main service falls back to formula-based comparison. Environment vars `BETSLIP_SERVICE_URL` and `BETSLIP_API_SECRET` must be set on the main service.

### Railway has NO persistent storage
SQLite DB is ephemeral — it resets on every deploy. Do not build features that depend on
historical data persisting.

### Playwright scrapers run SEQUENTIALLY
SportyBet, MSport, and Betgr8 share a single Playwright browser and run one after another.
Only Bet9ja (API-based) runs in parallel with them.



### Bet9ja GROUP IDs are season-specific
The Bet9ja API uses GROUP IDs to identify leagues. These IDs change between seasons. If European competitions (Champions League, Europa League, Conference League) suddenly return 0 events, the GROUP IDs in `bet9ja_scraper.py` are likely stale and need updating. Use the `GetSports?DISP=0` API endpoint to find current IDs. Current IDs (2025/26 season): CL=1185641, EL=1185689, ECL=1946188.

---

## Step 3 — Run Tests

After every code change:

```bash
pytest test_main.py -v
```

All tests must pass before committing. If a test fails:
1. Fix the issue
2. Re-run tests
3. Only commit when green

---

## Project Quick Reference

| Key            | Value                                                |
|----------------|------------------------------------------------------|
| **Repo**       | `vincenzonova/odds-dashboard`                        |
| **Stack**      | Python 3.11, FastAPI, Playwright, aiohttp            |
| **Deploy**     | Railway (EU West Amsterdam), auto-deploys from main  |
| **Active bookmakers** | bet9ja, sportybet, msport, betgr8              |
| **Paused bookmakers** | betking, betano                                |
| **Priority leagues**  | Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League |
| **Core objective**    | Odds comparison — all bookmakers must load and be comparable |

---

## File Map

| File                    | What it does                                |
|-------------------------|---------------------------------------------|
| `main.py`               | FastAPI app, merge logic, TEAM_ALIASES, auth, routes |
| `dashboard.py`          | Dashboard HTML/JS/CSS template              |
| `bet9ja_scraper.py`     | Bet9ja API scraper (no browser)             |
| `sportybet_scraper.py`  | SportyBet Playwright scraper                |
| `msport_scraper.py`     | MSport Playwright scraper                   |
| `betgr8_scraper.py`     | Betgr8 Playwright scraper                   |
| `betslip_checker.py`    | Accumulator/betslip logic                   |
| `betslip_scraper.py`   | Playwright-based betslip scraping for live checks |
| `betslip_service.py`   | FastAPI microservice for betslip (separate Railway instance) |
| `test_main.py`          | Test suite (pytest)                         |
| `docs/ARCHITECTURE.md`  | System architecture                         |
| `docs/PRODUCT.md`       | Product overview and priorities              |
| `docs/CODE_DOCS.md`     | Code-level documentation                    |

---

## CI / GitHub Actions

The repo has a CI workflow at `.github/workflows/test.yml` that runs pytest on every push.
Check that CI is green after pushing.

<!-- trigger redeploy -->
