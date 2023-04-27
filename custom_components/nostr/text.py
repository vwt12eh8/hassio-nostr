import json
from asyncio import wait_for
from logging import getLogger
from typing import Any, cast

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import utcnow

from . import (CONF_PRIVATE_KEY, CONF_WRITE_RELAYS, DOMAIN, NostrData,
               NostrEntity, decode_relays)
from .nostr.event import Event, EventKind
from .nostr.key import PrivateKey
from .nostr.metadata import MetadataRegistory

_LOGGER = getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data: NostrData = hass.data[DOMAIN]
    pubhex = cast(str, entry.unique_id)
    if CONF_PRIVATE_KEY in entry.data:
        key = PrivateKey(bytes.fromhex(entry.data[CONF_PRIVATE_KEY]))
        pub = key.public_key.raw_bytes
    else:
        key = None
        pub = bytes.fromhex(pubhex)

    async def post_event(event: Event):
        await data.relays.post_event(event, [x for x in decode_relays(entry.options.get(CONF_WRITE_RELAYS))])

    async_add_entities([
        AboutTextEntity(data.metadatas, post_event, key, pub, pubhex),
        DisplayNameTextEntity(data.metadatas, post_event, key, pub, pubhex),
        NameTextEntity(data.metadatas, post_event, key, pub, pubhex),
        PictureTextEntity(data.metadatas, post_event, key, pub, pubhex),
    ])


class NostrTextEntity(NostrEntity, TextEntity):
    _attr_available = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_value = None

    def __init__(self, mr: MetadataRegistory, post_event: Any, key: PrivateKey | None, pub: bytes, pubhex: str):
        super().__init__(pubhex)
        self._key = key
        self._pub = pub
        self._mr = mr
        self._post_event = post_event

    async def async_set_value(self, value: str) -> None:
        if self._key is None:
            raise Exception("Private key required")
        data = self._mr.get(self._pub)
        if data is None:
            raise Exception("Full metadata not exist")
        if value:
            data[self._name] = value
        else:
            del data[self._name]
        event = Event(
            json.dumps(data, ensure_ascii=False),
            self._key.public_key.hex(),
            int(utcnow().timestamp()),
            EventKind.SET_METADATA,
        )
        event.sign(self._key)
        _LOGGER.debug(event.to_message())
        await self._post_event(event)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._mr.subscribe(
            self._pub).subscribe(self._updated).dispose)
        try:
            await wait_for(self._inited, 5)
        except:
            pass

    def _updated(self, args: tuple[int, dict]):
        self._attr_native_value = args[1].get(self._name, "")
        self._attr_available = True
        self.async_schedule_update_ha_state()
        if not self._inited.done():
            self._inited.set_result(None)


class AboutTextEntity(NostrTextEntity):
    _attr_icon = "mdi:rename"
    _attr_name = "About"
    _name = "about"


class DisplayNameTextEntity(NostrTextEntity):
    _attr_icon = "mdi:rename"
    _attr_name = "Display name"
    _name = "display_name"


class NameTextEntity(NostrTextEntity):
    _attr_icon = "mdi:rename"
    _attr_name = "Name"
    _name = "name"


class PictureTextEntity(NostrTextEntity):
    _attr_icon = "mdi:image"
    _attr_name = "Picture"
    _name = "picture"

    @property
    def entity_picture(self) -> str | None:
        return self.native_value or None
