class FactoryError(Exception):
    """Base exception for factory errors."""


class ContractValidationError(FactoryError):
    """Raised when a contract fails validation."""


class GateBlockedError(FactoryError):
    """Raised when a gate blocks progress."""


class TransitionError(FactoryError):
    """Raised when a state transition is invalid."""


class UnsafePathError(FactoryError):
    """Raised when a path is unsafe to use."""
