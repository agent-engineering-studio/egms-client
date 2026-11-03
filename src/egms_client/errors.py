class EgmsError(Exception):
    """The EGMS archive or the CLMS token endpoint answered, but not with what was asked.

    The archive reports most failures as HTTP 200 with ``{"status": false,
    "message": ...}``, so a status check alone never sees them.
    """
