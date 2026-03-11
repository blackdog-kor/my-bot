import importlib


def test_get_ptb_app_registers_all_handlers(monkeypatch):
    bot_module = importlib.import_module("bot")

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

    monkeypatch.setattr(bot_module, "Application", FakeApplication)
    monkeypatch.setattr(bot_module, "BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(bot_module, "_ptb_app", None)

    app = bot_module._get_ptb_app()

    assert app is not None
    handler_types = [type(handler).__name__ for handler in app.handlers]
    assert handler_types == [
        "CommandHandler",
        "CallbackQueryHandler",
        "MessageHandler",
    ]

    # Returns cached app on repeated calls.
    assert bot_module._get_ptb_app() is app
