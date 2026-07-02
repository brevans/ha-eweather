"""EWeather forecast feed sensor.

Exposes the official eweather posts pulled from Firestore. The state is the number
of posts; the individual posts (title, body, image, timestamp, author, category) are
provided as the ``posts`` attribute for use in cards, automations, and templates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.hacs_eweather.const import (
    CONF_OFFICIAL_ONLY,
    CONF_POST_COUNT,
    DEFAULT_OFFICIAL_ONLY,
    DEFAULT_POST_COUNT,
)
from custom_components.hacs_eweather.entity import EWeatherHomeAssistantEntity
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

if TYPE_CHECKING:
    from custom_components.hacs_eweather.coordinator import EWeatherHomeAssistantDataUpdateCoordinator

# Internal keys added by the client (see api/client.py).
_DOC_ID_KEY = "__doc_id__"
_OFFICIAL_KEY = "_official"
_AUTHOR_KEY = "_author"

ENTITY_DESCRIPTION = SensorEntityDescription(
    key="feed",
    translation_key="feed",
    icon="mdi:weather-partly-cloudy",
    native_unit_of_measurement="posts",
)


class EWeatherHomeAssistantFeedSensor(SensorEntity, EWeatherHomeAssistantEntity):
    """Sensor exposing the eweather post feed."""

    def __init__(
        self,
        coordinator: EWeatherHomeAssistantDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialize the feed sensor."""
        super().__init__(coordinator, entity_description)

    def _selected_posts(self) -> list[dict[str, Any]]:
        """Return the posts to expose, honoring the official-only option."""
        data = self.coordinator.data or {}
        official_only = self.coordinator.config_entry.options.get(
            CONF_OFFICIAL_ONLY,
            DEFAULT_OFFICIAL_ONLY,
        )
        key = "official" if official_only else "posts"
        posts = data.get(key, [])
        return posts if isinstance(posts, list) else []

    @property
    def native_value(self) -> int | None:
        """Return the number of posts currently in the feed."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        return len(self._selected_posts())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the posts and feed metadata as attributes."""
        data = self.coordinator.data or {}
        counts = data.get("counts", {})
        post_count = int(
            self.coordinator.config_entry.options.get(CONF_POST_COUNT, DEFAULT_POST_COUNT),
        )
        posts = [self._clean_post(post) for post in self._selected_posts()[:post_count]]
        return {
            "posts": posts,
            "official_count": counts.get("official"),
            "total_count": counts.get("total"),
        }

    @staticmethod
    def _clean_post(post: dict[str, Any]) -> dict[str, Any]:
        """Project a decoded post into a tidy attribute dict for cards/automations."""
        images = post.get("images")
        image_urls = (
            [img.get("original") for img in images if isinstance(img, dict) and img.get("original")]
            if isinstance(images, list)
            else []
        )
        return {
            "id": post.get(_DOC_ID_KEY),
            "title": post.get("title"),
            "text": post.get("text"),
            "category": post.get("category"),
            "created": post.get("created"),
            "author": post.get(_AUTHOR_KEY),
            "official": post.get(_OFFICIAL_KEY),
            "likes": post.get("likes"),
            "comments": post.get("comments"),
            "views": post.get("views"),
            "image": image_urls[0] if image_urls else None,
            "images": image_urls,
        }
