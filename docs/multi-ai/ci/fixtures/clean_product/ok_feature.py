"""Clean product code — no direct AI SDK imports."""

def caption_via_gateway(text: str) -> str:
    # Product would call threezone_ai.gateway.run — not providers.
    return text.upper()
