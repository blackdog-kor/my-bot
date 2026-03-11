def _callback_url() -> str:
    base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if not base:
        return "(PUBLIC_BASE_URL 미설정)/api/video/callback"
    return f"{base.rstrip('/')}/api/video/callback"
