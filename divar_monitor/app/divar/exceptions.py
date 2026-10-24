class DivarError(Exception): ...
class DivarTransientError(DivarError): ...   # timeouts, 5xx, network
class DivarBlockedError(DivarError): ...     # 403 / 429 -> back off, rotate proxy
class DivarNotFoundError(DivarError): ...    # deleted/expired post
class DivarAPIError(DivarError): ...         # unexpected status / schema
