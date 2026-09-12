"""Forbidden: product code importing an AI SDK directly."""
import groq  # noqa: F401 — intentional scanner bait

def oops():
    return groq
