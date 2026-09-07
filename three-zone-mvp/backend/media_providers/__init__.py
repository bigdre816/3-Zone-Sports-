from .cloudflare import CloudflareProvider
from .demo import DemoProvider, live_input_create_body


def get_provider(config, override=None):
    if override is not None:
        return override
    if getattr(config, "media_provider", "demo") == "cloudflare":
        return CloudflareProvider(config)
    return DemoProvider()
