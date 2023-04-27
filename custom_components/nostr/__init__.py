from asyncio import Future, Task, create_task, gather
from datetime import datetime
from logging import getLogger
from typing import Any, Callable, Iterable, cast

from aioesphomeapi import TypeVar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import (DeviceEntryType,
                                                   DeviceRegistry)
from homeassistant.helpers.entity import Entity
from reactivex import operators as ops

from .nostr.contact import ContactRegistory
from .nostr.event import Event as NEvent
from .nostr.event import EventKind
from .nostr.filter import Filter
from .nostr.key import PrivateKey, PublicKey
from .nostr.metadata import MetadataRegistory
from .nostr.relay import RelayClient

ATTR_CONTENT = "content"
ATTR_CREATED_AT = "created_at"
ATTR_KIND = "kind"
ATTR_PUBKEY = "pubkey"
ATTR_TAGS = "tags"
CONF_PRIVATE_KEY = "private_key"
CONF_READ_RELAYS = "read_relays"
CONF_WRITE_RELAYS = "write_relays"
DOMAIN = "nostr"

_PLATFORMS = {
    Platform.SENSOR,
    Platform.TEXT,
}
_LOGGER = getLogger(__name__)

_T = TypeVar("_T")


class NostrData:
    def __init__(self, hass: HomeAssistant) -> None:
        self.relays = RelayClient(async_get_clientsession(hass))
        self.contacts = ContactRegistory()
        self.metadatas = MetadataRegistory()


class NostrEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _name: str

    def __init__(self, pubhex: str):
        super().__init__()
        self._attr_device_info = {
            'identifiers': {(DOMAIN, cast(str, pubhex))},
        }
        self._attr_unique_id = f"{pubhex}-{self._name}"
        self._inited = Future()


async def async_setup(hass: HomeAssistant, config):
    data = NostrData(hass)
    hass.data[DOMAIN] = data

    async def _service_post_event(call: ServiceCall):
        entries = hass.config_entries.async_entries(DOMAIN)
        dr = device_registry.async_get(hass)
        keys = list[ConfigEntry]()
        for pubkey in call.data[ATTR_PUBKEY]:
            if entry := _device_to_config_entry(dr, entries, pubkey):
                keys.append(entry)

        tasks = list[Task]()
        for entry in keys:
            key = PrivateKey.from_nsec(entry.data[CONF_PRIVATE_KEY])
            created_at: Any = _parse_or_none(call.data.get(
                ATTR_CREATED_AT, None), lambda x: int(datetime.fromisoformat(x).timestamp()))
            event = NEvent(
                call.data.get(ATTR_CONTENT, ""),
                key.public_key.hex(),
                created_at,
                int(call.data[ATTR_KIND]),
                call.data.get(ATTR_TAGS, []),
            )
            event.sign(key)
            tasks.append(create_task(data.relays.post_event(
                event, [x for x in entry.options[CONF_WRITE_RELAYS].split("\n") if x])))

        await gather(*tasks, return_exceptions=True)

    hass.services.async_register(DOMAIN, "post_event", _service_post_event)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    data: NostrData = hass.data[DOMAIN]
    pubhex = cast(str, entry.unique_id)

    async def connect_relays(url: str):
        relay = await data.relays.get(url)
        entry.async_on_unload(relay.subscribe(Filter(authors=[pubhex], kinds=[EventKind.SET_METADATA])).pipe(
            ops.filter(lambda x: x[0] == "EVENT"),
            ops.map(lambda x: cast(NEvent, x[2])),
        ).subscribe(data.metadatas.update_verified).dispose)
        entry.async_on_unload(relay.subscribe(Filter(authors=[pubhex], kinds=[EventKind.CONTACTS])).pipe(
            ops.filter(lambda x: x[0] == "EVENT"),
            ops.map(lambda x: cast(NEvent, x[2])),
        ).subscribe(data.contacts.update_verified).dispose)
        entry.async_on_unload(relay.subscribe(Filter(pubkey_refs=[pubhex], kinds=[EventKind.CONTACTS])).pipe(
            ops.filter(lambda x: x[0] == "EVENT"),
            ops.map(lambda x: cast(NEvent, x[2])),
        ).subscribe(data.contacts.update_verified).dispose)

    await gather(*[connect_relays(x) for x in decode_relays(entry.options.get(CONF_READ_RELAYS))], return_exceptions=True)

    dr = device_registry.async_get(hass)
    dr.async_get_or_create(
        config_entry_id=entry.entry_id,
        configuration_url=f"https://nostx.shino3.net/{PublicKey(bytes.fromhex(pubhex)).bech32()}",
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, pubhex)},
        name=entry.title,
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


def decode_relays(data: str | None) -> Any:
    if not data:
        return []
    values = set[str]()
    for url in data.split("\n"):
        url = url.strip()
        if not url:
            continue
        values.add(url)
    return list(values)


def encode_relays(urls: Iterable[str] | None):
    if not urls:
        return ""
    values = set[str]()
    for url in urls:
        url = url.rstrip("/")
        if not url:
            continue
        values.add(url)
    return "\n".join(values)


def _device_to_config_entry(dr: DeviceRegistry, entries: list[ConfigEntry], device_id: str):
    if device_id.startswith("npub"):
        npub = device_id
    else:
        if not (device := dr.async_get(device_id)):
            return
        if not (npub := next((x[1] for x in device.identifiers if x[0] == DOMAIN), None)):
            return
    return next((x for x in entries if x.unique_id == npub), None)


def _parse_or_none(value: str | None, parse: Callable[[str], _T]) -> _T | None:
    if value is None:
        return None
    return parse(value)
