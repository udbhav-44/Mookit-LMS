from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict | None = None
