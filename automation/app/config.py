import json
import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(BASE_DIR, "config", "settings.json")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

# Load environment variables from automation/.env
load_dotenv(os.path.join(BASE_DIR, ".env"))

with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
    SETTINGS = json.load(f)

ADMIN_ID = SETTINGS["admin_id"]
CHANNEL_ID = SETTINGS["channel_id"]
DEFAULT_LANGUAGE = SETTINGS.get("default_language", "한국어")

BOT_TOKEN = os.getenv("BOT_TOKEN")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
INTEGRATION_SECRET = os.getenv("INTEGRATION_SECRET", "")


def load_prompt(filename: str) -> str:
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
