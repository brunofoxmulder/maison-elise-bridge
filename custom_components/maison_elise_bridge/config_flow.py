from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientTimeout
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.components.hassio import HassioNotReadyError, get_apps_list
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONFIG_TEST_TIMEOUT_SECONDS,
    CONF_CLOUDHOOK_URL,
    CONF_INVESTIGATOR_SLUG,
    CONF_INVESTIGATOR_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
    INVESTIGATOR_ENTITIES_PATH,
    INVESTIGATOR_PORT,
    INVESTIGATOR_SLUG_SUFFIX,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INVESTIGATOR_TOKEN): str,
    }
)


def _find_investigator_slug(apps: list[dict[str, Any]]) -> str | None:
    """Return the installed Élise Investigator app slug."""
    for app in apps:
        slug = app.get("slug")
        if isinstance(slug, str) and (
            slug == INVESTIGATOR_SLUG_SUFFIX
            or slug.endswith(f"_{INVESTIGATOR_SLUG_SUFFIX}")
        ):
            return slug
    return None


def _investigator_url(slug: str, path: str) -> str:
    """Build the internal Supervisor-network URL for Investigator."""
    hostname = slug.replace("_", "-")
    return f"http://{hostname}:{INVESTIGATOR_PORT}{path}"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Maison Élise Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Set up the bridge from the UI."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = str(user_input[CONF_INVESTIGATOR_TOKEN]).strip()
            if not token:
                errors["base"] = "invalid_auth"
            else:
                try:
                    apps = get_apps_list(self.hass)
                except HassioNotReadyError:
                    errors["base"] = "supervisor_not_ready"
                else:
                    slug = _find_investigator_slug(apps)
                    if slug is None:
                        errors["base"] = "investigator_not_found"
                    else:
                        session = async_get_clientsession(self.hass)
                        try:
                            async with session.get(
                                _investigator_url(slug, INVESTIGATOR_ENTITIES_PATH),
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=ClientTimeout(
                                    total=CONFIG_TEST_TIMEOUT_SECONDS
                                ),
                            ) as response:
                                if response.status in (401, 403):
                                    errors["base"] = "invalid_auth"
                                elif response.status != 200:
                                    errors["base"] = "cannot_connect"
                        except (ClientError, asyncio.TimeoutError):
                            errors["base"] = "cannot_connect"

                        if not errors:
                            await self.async_set_unique_id(DOMAIN)
                            self._abort_if_unique_id_configured()
                            return self.async_create_entry(
                                title="Maison Élise Bridge",
                                data={
                                    CONF_INVESTIGATOR_TOKEN: token,
                                    CONF_INVESTIGATOR_SLUG: slug,
                                    CONF_WEBHOOK_ID: webhook.async_generate_id(),
                                },
                            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Expose the active Cloudhook URL for safe copy from the Home Assistant UI."""
        entry = self._get_reconfigure_entry()
        cloudhook_url = str(entry.data.get(CONF_CLOUDHOOK_URL) or "").strip()

        if user_input is not None:
            # The displayed value is intentionally never written back from the form.
            # The Bridge remains the sole source of truth for the active Cloudhook URL.
            return self.async_abort(reason="cloudhook_unchanged")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLOUDHOOK_URL,
                        default=cloudhook_url,
                    ): str,
                }
            ),
        )
