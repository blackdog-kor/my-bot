import asyncio
import inspect
import sys
from pathlib import Path

# Tests run from bot/ (working-directory in CI).
# Add my-bot/ (project root) and my-bot/bot/ to sys.path so that
# both `app.*` and `bot.*` / bare `handlers.*` packages are importable.
BOT_DIR = Path(__file__).resolve().parents[1]   # my-bot/bot/
ROOT    = BOT_DIR.parent                         # my-bot/
for _p in (str(ROOT), str(BOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test to run in an asyncio event loop")


def pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(testfunction(**kwargs))
        return True
    return None
