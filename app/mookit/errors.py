class MooKitError(Exception):
    """Base class for all mooKIT API errors."""
    def __init__(self, message: str, code: int = 0, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class MooKitAuthError(MooKitError):
    """401 / 403 — invalid or expired credentials."""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code=401, retryable=False)


class MooKitForbiddenError(MooKitError):
    """403 — authenticated but not authorized for the resource."""
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, code=403, retryable=False)


class MooKitNotFoundError(MooKitError):
    """404 — resource does not exist."""
    def __init__(self, message: str = "Not found"):
        super().__init__(message, code=404, retryable=False)


class MooKitValidationError(MooKitError):
    """422 — request body failed mooKIT's own validation."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code=422, retryable=False)
        self.details = details or {}


class MooKitRateLimitError(MooKitError):
    """429 — too many requests; honor Retry-After."""
    def __init__(self, message: str = "Rate limited", retry_after: float | None = None):
        super().__init__(message, code=429, retryable=True)
        self.retry_after = retry_after


class MooKitServerError(MooKitError):
    """5xx — transient server error; safe to retry on idempotent calls."""
    def __init__(self, message: str = "Server error", code: int = 500):
        super().__init__(message, code=code, retryable=True)


class CircuitOpenError(MooKitError):
    """Circuit breaker is open — dependency is considered down."""
    def __init__(self, service: str = "mooKIT"):
        super().__init__(f"Circuit breaker OPEN for {service}", code=503, retryable=False)


def map_http_error(status_code: int, message: str, details: dict | None = None) -> MooKitError:
    """Map an HTTP status code to the appropriate typed exception."""
    if status_code in (401,):
        return MooKitAuthError(message)
    if status_code == 403:
        return MooKitForbiddenError(message)
    if status_code == 404:
        return MooKitNotFoundError(message)
    if status_code == 422:
        return MooKitValidationError(message, details)
    if status_code == 429:
        return MooKitRateLimitError(message)
    if status_code >= 500:
        return MooKitServerError(message, code=status_code)
    return MooKitError(message, code=status_code)
