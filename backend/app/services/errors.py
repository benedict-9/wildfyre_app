"""Sanitized failures at external-provider boundaries."""


class ProviderError(Exception):
    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")
