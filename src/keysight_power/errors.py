"""Project exception types."""


class KeysightPowerError(Exception):
    """Base exception for keysight_power failures."""


class VisaConnectionError(KeysightPowerError):
    """Raised when VISA discovery, connection, or I/O fails."""
