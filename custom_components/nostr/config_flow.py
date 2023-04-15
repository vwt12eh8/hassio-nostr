from typing import Any, Iterable

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from nostr.key import PrivateKey
from voluptuous import Optional, Required, Schema

from . import CONF_PRIVATE_KEY, CONF_WRITE_RELAYS, DOMAIN


class MyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input:
            key = PrivateKey.from_nsec(user_input[CONF_PRIVATE_KEY])
            npub = key.public_key.bech32()
            await self.async_set_unique_id(npub)
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or npub,
                data={
                    CONF_PRIVATE_KEY: key.bech32(),
                },
                options={
                    CONF_WRITE_RELAYS: _encode_relays(user_input[CONF_WRITE_RELAYS]),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=Schema({
                Required(CONF_PRIVATE_KEY): str,
                Required(CONF_WRITE_RELAYS): SelectSelector(SelectSelectorConfig(options=[], multiple=True, custom_value=True)),
                Optional(CONF_NAME): str,
            }),
            last_step=True,
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry):
        return MyOptionsFlow(entry)


class MyOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry):
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input:
            return self.async_create_entry(
                data={
                    CONF_WRITE_RELAYS: _encode_relays(user_input[CONF_WRITE_RELAYS]),
                },
            )
        else:
            options = self.entry.options
            urls = _decode_relays(options[CONF_WRITE_RELAYS])
            return self.async_show_form(
                step_id="init",
                data_schema=Schema({
                    Required(CONF_WRITE_RELAYS, default=urls): SelectSelector(SelectSelectorConfig(options=urls, multiple=True, custom_value=True)),
                }),
                last_step=True,
            )


def _decode_relays(data: str) -> Any:
    values = set[str]()
    for url in data.split("\n"):
        url = url.strip()
        if not url:
            continue
        values.add(url)
    return list(values)


def _encode_relays(urls: Iterable[str]):
    values = set[str]()
    for url in urls:
        url = url.rstrip("/")
        if not url:
            continue
        values.add(url)
    return "\n".join(values)
