"""Config flow for Bird Buddy integration."""

from __future__ import annotations

from birdbuddy.client import BirdBuddy
from birdbuddy.exceptions import AuthenticationFailedError
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_EMAIL
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    MAX_POLLING_INTERVAL,
)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bird Buddy."""

    VERSION = 1

    def __init__(self):
        self._client = None
        super().__init__()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}
        if user_input is not None:
            result = await self._async_auth_or_validate(user_input, errors)
            if result is not None:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=result["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _async_auth_or_validate(self, input, errors):
        self._client = BirdBuddy(input[CONF_EMAIL], input[CONF_PASSWORD])
        try:
            result = await self._client.refresh()
        except AuthenticationFailedError:
            self._client = None
            errors["base"] = "invalid_auth"
            return None
        except Exception:
            self._client = None
            errors["base"] = "cannot_connect"
            return None
        if not result:
            self._client = None
            errors["base"] = "cannot_connect"
            return None
        return {
            "title": self._client.user.name,
        }

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return BirdBuddyOptionsFlowHandler(config_entry)


class BirdBuddyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a options flow for Bird Buddy."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current polling interval from options or use default
        current_interval = self._config_entry.options.get(
            CONF_POLLING_INTERVAL,
            DEFAULT_POLLING_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_POLLING_INTERVAL,
                    default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL)
                )
            }),
            description_placeholders={
                "min": MIN_POLLING_INTERVAL,
                "max": MAX_POLLING_INTERVAL,
                "current": current_interval,
                "default": DEFAULT_POLLING_INTERVAL
            },
            description="Adjust how frequently Bird Buddy checks for new feed items. "
            "Lower values provide faster updates but increase API usage."
        )
