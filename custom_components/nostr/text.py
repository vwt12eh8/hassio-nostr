from typing import cast

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    async_add_entities([NameTextEntity(entry)])


class NameTextEntity(TextEntity):
    _attr_available = False  # TODO
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_name = "Name"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry):
        super().__init__()
        self._attr_device_info = {
            'identifiers': {(DOMAIN, cast(str, entry.unique_id))},
        }
        self._attr_unique_id = f"{entry.unique_id}-name"
        self._attr_native_value = None
