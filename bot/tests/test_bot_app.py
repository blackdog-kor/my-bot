"""
bot/main.py의 build_application() 동작을 검증한다.
"""
import bot.main as bot_main


def test_build_application_registers_all_handlers(monkeypatch):
    """build_application()이 3개의 핸들러(Command/Callback/Message)를 등록하는지 확인."""

    class FakeApp:
        def __init__(self):
            self.handlers = []
            self.bot = object()

        def add_handler(self, handler):
            self.handlers.append(handler)

        async def initialize(self):
            return None

    class FakeBuilder:
        def token(self, _token):
            return self

        def build(self):
            return FakeApp()

    class FakeApplication:
        @staticmethod
        def builder():
            return FakeBuilder()

    monkeypatch.setattr(bot_main, "Application",   FakeApplication)
    monkeypatch.setattr(bot_main, "BOT_TOKEN",     "dummy-token")
    monkeypatch.setattr(bot_main, "_application",  None)

    app = bot_main.build_application()

    assert app is not None
    handler_types = [type(handler).__name__ for handler in app.handlers]
    assert handler_types == [
        "CommandHandler",
        "CallbackQueryHandler",
        "MessageHandler",
    ]

    # 두 번째 호출은 캐시된 인스턴스를 반환해야 한다.
    assert bot_main.build_application() is app
