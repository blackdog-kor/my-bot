"""
Browser stealth patches for Playwright context.

Injects JavaScript overrides to bypass common bot detection checks:
- navigator.webdriver removal
- Chrome runtime patching
- Realistic permissions, plugins, and language settings
"""
import logging

logger = logging.getLogger(__name__)

# JS to remove the webdriver property and patch Chrome runtime
_STEALTH_SCRIPT = """
() => {
    // Remove navigator.webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // Patch Chrome runtime to look like a real browser
    window.chrome = {
        runtime: {
            onConnect: undefined,
            onMessage: undefined,
        },
    };

    // Fake notification permission
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );

    // Realistic plugins list (real Chrome has these)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin',   filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client',       filename: 'internal-nacl-plugin' },
        ],
    });

    // Realistic language settings
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ko-KR', 'ko', 'en-US', 'en'],
    });

    // Hide automation-related properties
    delete navigator.__proto__.webdriver;
}
"""


async def apply_stealth(context) -> None:
    """
    Apply stealth patches to a Playwright browser context.

    Must be called after launch_persistent_context() and before navigating
    to any pages. Adds an init script that runs in every new page context.

    Args:
        context: Playwright BrowserContext instance
    """
    try:
        await context.add_init_script(_STEALTH_SCRIPT)
        logger.info("[browser_stealth] Stealth init script registered")
    except Exception as exc:
        logger.warning("[browser_stealth] Failed to add init script: %s", exc)
