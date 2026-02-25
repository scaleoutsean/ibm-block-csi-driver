"""Base abstractions for auth strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import MutableMapping


class AuthStrategy(ABC):
    """Interface each authentication mechanism must implement."""

    @abstractmethod
    def apply(self, headers: MutableMapping[str, str]) -> None:
        """Mutate headers in-place with the necessary credentials."""

    def refresh(self, headers: MutableMapping[str, str]) -> None:
        """Optional hook for refreshing credentials prior to retry."""
        self.apply(headers)
