class DomainError(Exception):
    """Safe, stable code. Never put PII or provider response bodies in errors."""
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


class IntegrationError(DomainError):
    def __init__(self, code: str, retryable: bool = False, uncertain: bool = False):
        super().__init__(code, 503)
        self.retryable = retryable
        self.uncertain = uncertain
