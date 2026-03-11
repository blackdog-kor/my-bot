from app.config import LLM_PROVIDER, LLM_MODEL, GEMINI_API_KEY, load_prompt
from app.providers.gemini_provider import GeminiProvider


class AIService:
    def __init__(self):
        # Lazy-init so the web server can boot without AI credentials.
        # (AI features will raise a clear error when invoked.)
        self._provider = None

    def _build_provider(self):
        if LLM_PROVIDER == "gemini":
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not set.")
            return GeminiProvider(api_key=GEMINI_API_KEY, model=LLM_MODEL)

        raise ValueError(f"Unsupported provider: {LLM_PROVIDER}")

    def _get_provider(self):
        if self._provider is None:
            self._provider = self._build_provider()
        return self._provider

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        template = load_prompt(template_name)
        return template.format(**kwargs)

    def generate_post(self, keyword: str, language: str) -> str:
        prompt = self._render_prompt(
            "post_generate.txt",
            keyword=keyword,
            language=language,
        )
        return self._get_provider().generate(prompt)

    def rewrite(self, style: str, text: str) -> str:
        prompt = self._render_prompt(
            "rewrite.txt",
            style=style,
            text=text,
        )
        return self._get_provider().generate(prompt)

    def translate(self, target_language: str, text: str) -> str:
        prompt = self._render_prompt(
            "translate.txt",
            target_language=target_language,
            text=text,
        )
        return self._get_provider().generate(prompt)

    def generate_hashtags(self, keyword: str) -> str:
        prompt = self._render_prompt(
            "hashtags.txt",
            keyword=keyword,
        )
        return self._get_provider().generate(prompt)

    def generate_ideas(self, keyword: str) -> str:
        prompt = self._render_prompt(
            "ideas.txt",
            keyword=keyword,
        )
        return self._get_provider().generate(prompt)
