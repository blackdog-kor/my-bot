# PROJECT_MAP

## Repository Layout

casino-system/
- bot/
  - src/
  - tests/
  - requirements.txt

- automation/
  - app/
  - scripts/
  - tests/
  - requirements.txt
  - Procfile

- .github/
  - workflows/

## Ownership

### bot/
Telegram interaction only.

Expected contents:
- webhook entry
- handlers
- keyboards
- callback logic
- user-facing flow

### automation/
System brain.

Expected contents:
- FastAPI backend
- AI automation scripts
- campaign logic
- analytics
- scraper modules (future)
- dev pipeline

### .github/workflows/
Shared repository automation.

Expected:
- ai-control workflow
- future CI workflows

## Future expansion
automation/app/services/scraper/
- competitor_scraper.py
- casino_scraper.py
- trend_scraper.py
