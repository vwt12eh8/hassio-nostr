from asyncio import wait_for
from typing import cast

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, NostrData, NostrEntity
from .nostr.contact import ContactRegistory
from .nostr.event import Event


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data: NostrData = hass.data[DOMAIN]
    pubhex = cast(str, entry.unique_id)
    pub = bytes.fromhex(pubhex)
    async_add_entities([
        FollowsSensorEntity(data.contacts, pub, pubhex),
        FollowersSensorEntity(data.contacts, pub, pubhex),
    ])


class FollowsSensorEntity(NostrEntity, SensorEntity):
    _attr_available = False
    _attr_icon = "mdi:counter"
    _attr_name = "Follows"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = True
    _name = "follows"

    def __init__(self, cr: ContactRegistory, pub: bytes, pubhex: str):
        super().__init__(pubhex)
        self._cr = cr
        self._pub = pub

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cr.subscribe(
            self._pub).subscribe(self._updated).dispose)
        try:
            await wait_for(self._inited, 5)
        except:
            pass

    def _updated(self, event: Event):
        self._attr_native_value = len(
            {x[1] for x in event.tags if x[0] == "p"})
        self._attr_available = True
        self.async_schedule_update_ha_state()
        if not self._inited.done():
            self._inited.set_result(None)


class FollowersSensorEntity(NostrEntity, SensorEntity):
    _attr_icon = "mdi:counter"
    _attr_name = "Followers"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = True
    _name = "followers"

    def __init__(self, cr: ContactRegistory, pub: bytes, pubhex: str):
        super().__init__(pubhex)
        self._cr = cr
        self._pub = pub

    @property
    def native_value(self):
        return len(self._cr.get_followers(self._pub))
