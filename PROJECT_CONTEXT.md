# PROJECT_CONTEXT

## Project
casino-system

## Goal
Build a Telegram-based casino affiliate growth engine with:
- Telegram entry bot
- automation backend
- AI development pipeline
- future scraper-based intelligence

## Services

### bot
User-facing Telegram bot.

Responsibilities:
- webhook handling
- /start
- language selection
- menu navigation
- deep link tracking

Rule:
Keep this service lightweight.

### automation
Backend automation service.

Responsibilities:
- AI pipeline
- campaign automation
- database
- analytics
- content generation
- future scraping modules

Rule:
All heavy logic belongs here.

## Deployment
Railway with two services:
- bot service
- automation service

## AI development pipeline
/dev command
→ trigger_ai_pipeline.py
→ GitHub Actions
→ ai_direct_pr.py
→ AI-generated branch
→ PR creation

## Rules
1. Do not mix bot and automation logic.
2. Prefer minimal safe changes.
3. Do not break webhook architecture.
4. Avoid unnecessary microservices.
5. Keep deployment stable.
