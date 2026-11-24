class EgmsError(Exception):
    """The EGMS archive or the CLMS token endpoint answered, but not with what was asked.

    The archive reports most failures as HTTP 200 with ``{"status": false,
    "message": ...}``, so a status check alone never sees them.

    ``status_code`` is the HTTP status of a refused download or token, when
    there was one: a caller that brings its own retry (``retries=0``) reads it
    to tell a busy archive (429, 5xx) from a refusal.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
