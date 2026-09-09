from .cloudflare import CloudflareProvider
from .demo import DemoProvider, live_input_create_body


def get_provider(config, override=None):
    if override is not None:
        return override
    name = config.live_provider_name() if hasattr(config, "live_provider_name") else getattr(config, "media_provider", "demo")
    if name == "cloudflare":
        return CloudflareProvider(config)
    return DemoProvider()
