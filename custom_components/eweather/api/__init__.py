"""
API package for eweather.

Architecture:
    Three-layer data flow: Entities → Coordinator → API Client.
    Only the coordinator should call the API client. Entities must never
    import or call the API client directly.

Exception hierarchy:
    EWeatherHomeAssistantApiClientError (base)
    ├── EWeatherHomeAssistantApiClientCommunicationError (network/timeout)
    └── EWeatherHomeAssistantApiClientAuthenticationError (401/403)

Coordinator exception mapping:
    ApiClientAuthenticationError → ConfigEntryAuthFailed (triggers reauth)
    ApiClientCommunicationError → UpdateFailed (auto-retry)
    ApiClientError             → UpdateFailed (auto-retry)
"""

from .client import (
    EWeatherHomeAssistantApiClient,
    EWeatherHomeAssistantApiClientAuthenticationError,
    EWeatherHomeAssistantApiClientCommunicationError,
    EWeatherHomeAssistantApiClientError,
)

__all__ = [
    "EWeatherHomeAssistantApiClient",
    "EWeatherHomeAssistantApiClientAuthenticationError",
    "EWeatherHomeAssistantApiClientCommunicationError",
    "EWeatherHomeAssistantApiClientError",
]
