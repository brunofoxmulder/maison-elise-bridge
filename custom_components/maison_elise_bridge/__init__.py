from __future__ import annotations

import asyncio
import logging
from typing import Any
import uuid

from aiohttp import ClientError, ClientTimeout, web

from homeassistant.components import cloud, persistent_notification, webhook
from homeassistant.components.hassio import HassioNotReadyError, get_apps_list
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BACKGROUND_REQUEST_TIMEOUT_SECONDS,
    CONF_CLOUDHOOK_URL,
    CONF_INVESTIGATOR_SLUG,
    CONF_INVESTIGATOR_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
    ERROR_NOTIFICATION_ID,
    EXPECTED_SKILL_ID,
    INVESTIGATOR_ASK_PATH,
    INVESTIGATOR_PORT,
    LAST_CALLED_SENSOR,
    MAISON_ELISE_APP_CONVERSATION_PATH,
    MAISON_ELISE_APP_PORT,
    MAISON_ELISE_APP_SLUG_SUFFIX,
    MAX_QUESTION_LENGTH,
    NOTIFICATION_ID,
)

_LOGGER = logging.getLogger(__name__)

_NOTIFY_SUFFIXES = ("_announce", "_annoncer", "_speak", "_parler")
_ANNOUNCE_SUFFIXES = ("_announce", "_annoncer")


def _investigator_url(slug: str) -> str:
    """Build the internal Supervisor-network URL for Investigator."""
    hostname = slug.replace("_", "-")
    return f"http://{hostname}:{INVESTIGATOR_PORT}{INVESTIGATOR_ASK_PATH}"


def _maison_elise_app_url(slug: str) -> str:
    """Build the private Supervisor-network URL for Maison Élise App."""
    hostname = slug.replace("_", "-")
    return (
        f"http://{hostname}:{MAISON_ELISE_APP_PORT}"
        f"{MAISON_ELISE_APP_CONVERSATION_PATH}"
    )


def _find_maison_elise_app_slug(hass: HomeAssistant) -> str | None:
    """Discover Maison Élise App without hardcoding its repository hash."""
    try:
        apps = get_apps_list(hass)
    except HassioNotReadyError:
        return None

    for app in apps:
        slug = app.get("slug")
        if isinstance(slug, str) and (
            slug == MAISON_ELISE_APP_SLUG_SUFFIX
            or slug.endswith(f"_{MAISON_ELISE_APP_SLUG_SUFFIX}")
        ):
            return slug
    return None


def _usable_notify_entity(hass: HomeAssistant, entity_id: Any) -> str | None:
    """Return a loaded Alexa notify entity when usable."""
    if not isinstance(entity_id, str) or not entity_id.startswith("notify."):
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state == "unavailable":
        return None
    return entity_id


def _last_alexa_notify_entity(hass: HomeAssistant) -> str | None:
    """Find the announce/speak entity of the most recently used Alexa device."""
    last_called = hass.states.get(LAST_CALLED_SENSOR)
    if last_called is not None:
        for attribute in ("notify_announce", "notify_speak"):
            entity_id = _usable_notify_entity(
                hass, last_called.attributes.get(attribute)
            )
            if entity_id:
                return entity_id

    registry = er.async_get(hass)
    voice_events = [
        state
        for state in hass.states.async_all("event")
        if "voice_command" in state.attributes
        or state.entity_id.endswith("_voice_event")
    ]
    voice_events.sort(key=lambda state: state.last_updated, reverse=True)

    for event_state in voice_events:
        event_entry = registry.async_get(event_state.entity_id)
        if event_entry is None or event_entry.device_id is None:
            continue

        notify_entities = [
            item.entity_id
            for item in registry.entities.values()
            if item.device_id == event_entry.device_id
            and item.entity_id.startswith("notify.")
        ]
        for suffix in _NOTIFY_SUFFIXES:
            for entity_id in notify_entities:
                if entity_id.endswith(suffix):
                    usable = _usable_notify_entity(hass, entity_id)
                    if usable:
                        return usable

    announce_entities = [
        state.entity_id
        for state in hass.states.async_all("notify")
        if state.entity_id.endswith(_ANNOUNCE_SUFFIXES)
        and state.state != "unavailable"
    ]
    if len(announce_entities) == 1:
        return announce_entities[0]

    return None


def _bridge_error(hass: HomeAssistant, message: str) -> None:
    """Expose the latest bridge error without leaking secrets."""
    _LOGGER.warning("Maison Élise Bridge: %s", message)
    persistent_notification.async_create(
        hass,
        message,
        title="Maison Élise Bridge — erreur",
        notification_id=ERROR_NOTIFICATION_ID,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Maison Élise Bridge."""
    webhook_id = str(entry.data[CONF_WEBHOOK_ID])

    if not cloud.async_active_subscription(hass):
        raise ConfigEntryNotReady(
            "Maison Élise Bridge requires an active Home Assistant Cloud subscription"
        )

    try:
        cloudhook_url = await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    except (cloud.CloudNotAvailable, cloud.CloudNotConnected) as err:
        raise ConfigEntryNotReady("Home Assistant Cloud is not ready") from err

    if entry.data.get(CONF_CLOUDHOOK_URL) != cloudhook_url:
        data = dict(entry.data)
        data[CONF_CLOUDHOOK_URL] = cloudhook_url
        hass.config_entries.async_update_entry(entry, data=data)

    async def announce_answer(answer_text: str, preferred_target: str | None) -> None:
        """Announce the Maison Élise answer on the Alexa device used for the request."""
        target = _usable_notify_entity(hass, preferred_target)
        if target is None:
            target = _last_alexa_notify_entity(hass)

        if target is None:
            _bridge_error(
                hass,
                "Réponse reçue de Maison Élise, mais aucun Echo cible n'a pu être identifié. "
                f"Réponse : {answer_text}",
            )
            return

        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"message": f"Élise. {answer_text}"},
                target={"entity_id": target},
                blocking=True,
            )
        except Exception as err:  # Home Assistant service boundary
            _LOGGER.exception("Maison Élise Bridge announcement failed")
            _bridge_error(
                hass,
                f"La réponse a été trouvée mais l'annonce Alexa a échoué sur {target}: {err}",
            )
            return

        _LOGGER.info("Maison Élise Bridge announced answer on %s", target)

    async def try_maison_elise_app(
        question: str, preferred_target: str | None
    ) -> bool:
        """Try the new App first; return False so Investigator remains rollback."""
        app_slug = _find_maison_elise_app_slug(hass)
        if app_slug is None:
            _LOGGER.warning("Maison Élise App not found; using Investigator rollback")
            return False

        session = async_get_clientsession(hass)
        request_id = f"alexa-{uuid.uuid4().hex}"
        try:
            async with session.post(
                _maison_elise_app_url(app_slug),
                json={
                    "request_id": request_id,
                    "text": question,
                    "source": "alexa-bridge",
                },
                timeout=ClientTimeout(total=BACKGROUND_REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "Maison Élise App returned HTTP %s; using Investigator rollback",
                        response.status,
                    )
                    return False
                try:
                    result: Any = await response.json(content_type=None)
                except Exception:
                    _LOGGER.warning(
                        "Maison Élise App returned invalid JSON; using Investigator rollback"
                    )
                    return False
        except asyncio.TimeoutError:
            _LOGGER.warning("Maison Élise App timed out; using Investigator rollback")
            return False
        except ClientError as err:
            _LOGGER.warning(
                "Maison Élise App unavailable (%s); using Investigator rollback", err
            )
            return False
        except Exception:
            _LOGGER.exception("Unexpected Maison Élise App request failure")
            return False

        if not isinstance(result, dict) or result.get("ok") is not True:
            _LOGGER.warning("Maison Élise App rejected request; using Investigator rollback")
            return False

        answer_text = str(result.get("speech") or "").strip()
        if not answer_text:
            _LOGGER.warning(
                "Maison Élise App returned no speech; using Investigator rollback"
            )
            return False

        _LOGGER.info(
            "Maison Élise Bridge received App answer; response_type=%s",
            result.get("response_type"),
        )
        await announce_answer(answer_text, preferred_target)
        return True

    async def process_question(question: str, preferred_target: str | None) -> None:
        """Use Maison Élise App first, with the proven Investigator path as rollback."""
        if await try_maison_elise_app(question, preferred_target):
            return

        _LOGGER.info("Maison Élise Bridge using direct Investigator rollback")
        session = async_get_clientsession(hass)
        try:
            async with session.post(
                _investigator_url(str(entry.data[CONF_INVESTIGATOR_SLUG])),
                headers={
                    "Authorization": f"Bearer {entry.data[CONF_INVESTIGATOR_TOKEN]}"
                },
                json={"question": question},
                timeout=ClientTimeout(total=BACKGROUND_REQUEST_TIMEOUT_SECONDS),
            ) as response:
                if response.status in (401, 403):
                    _bridge_error(hass, "Élise Investigator a refusé le jeton API du Bridge.")
                    return
                if response.status != 200:
                    detail = ""
                    candidate_text = ""
                    try:
                        error_payload: Any = await response.json(content_type=None)
                        if isinstance(error_payload, dict):
                            detail = str(
                                error_payload.get("error")
                                or error_payload.get("message")
                                or ""
                            ).strip()
                            candidates = error_payload.get("candidates")
                            if response.status == 409 and isinstance(candidates, list):
                                formatted_candidates: list[str] = []
                                for candidate in candidates[:8]:
                                    if not isinstance(candidate, dict):
                                        continue
                                    entity_id = str(candidate.get("entity_id") or "").strip()
                                    name = str(candidate.get("name") or "").strip()
                                    if name and entity_id:
                                        formatted_candidates.append(f"{name} ({entity_id})")
                                    elif entity_id:
                                        formatted_candidates.append(entity_id)
                                    elif name:
                                        formatted_candidates.append(name)
                                candidate_text = "; ".join(formatted_candidates)
                    except Exception:
                        try:
                            detail = (await response.text()).strip()
                        except Exception:
                            detail = ""

                    detail = " ".join(detail.split())[:500]
                    candidate_text = " ".join(candidate_text.split())[:1000]
                    message = (
                        f"Élise Investigator a répondu avec le statut HTTP {response.status}."
                    )
                    if detail:
                        message += f" Détail : {detail}"
                    if candidate_text:
                        message += f" Candidats : {candidate_text}"
                    _bridge_error(hass, message)
                    return
                try:
                    result: Any = await response.json(content_type=None)
                except Exception:
                    _bridge_error(
                        hass, "La réponse d'Élise Investigator n'est pas un JSON valide."
                    )
                    return
        except asyncio.TimeoutError:
            _bridge_error(
                hass,
                f"Élise Investigator n'a pas répondu en {BACKGROUND_REQUEST_TIMEOUT_SECONDS} secondes.",
            )
            return
        except ClientError as err:
            _bridge_error(hass, f"Impossible de joindre Élise Investigator : {err}")
            return
        except Exception:
            _LOGGER.exception("Maison Élise Bridge background request failed")
            _bridge_error(hass, "Erreur inattendue pendant l'investigation.")
            return

        if not isinstance(result, dict):
            _bridge_error(hass, "La réponse d'Élise Investigator est invalide.")
            return

        answer_text = str(result.get("answer_text") or "").strip()
        if not answer_text:
            _bridge_error(hass, "Élise Investigator a répondu sans texte exploitable.")
            return

        _LOGGER.info(
            "Maison Élise Bridge received Investigator rollback answer; status=%s",
            result.get("status"),
        )
        await announce_answer(answer_text, preferred_target)

    async def handle_webhook(
        hass: HomeAssistant, received_webhook_id: str, request: web.Request
    ) -> web.Response:
        """Accept the unchanged Alexa payload and process it asynchronously."""
        if received_webhook_id != webhook_id:
            return web.json_response(
                {"ok": False, "error": "invalid_webhook"}, status=403
            )

        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": "invalid_json"}, status=400
            )

        if not isinstance(payload, dict):
            return web.json_response(
                {"ok": False, "error": "invalid_json"}, status=400
            )

        if payload.get("skill_id") != EXPECTED_SKILL_ID:
            _LOGGER.warning("Maison Élise Bridge rejected an invalid skill_id")
            return web.json_response(
                {"ok": False, "error": "invalid_skill"}, status=403
            )

        question = str(payload.get("question") or "").strip()
        if not question:
            return web.json_response(
                {"ok": False, "error": "question_required"}, status=400
            )
        if len(question) > MAX_QUESTION_LENGTH:
            return web.json_response(
                {"ok": False, "error": "question_too_long"}, status=400
            )

        preferred_target = _last_alexa_notify_entity(hass)
        _LOGGER.info(
            "Maison Élise Bridge accepted Alexa question; chars=%d target=%s",
            len(question),
            preferred_target or "auto",
        )
        hass.async_create_task(
            process_question(question, preferred_target),
            "Maison Élise App request",
        )

        return web.json_response(
            {"ok": True, "accepted": True, "read_only": True}, status=202
        )

    try:
        webhook.async_register(
            hass,
            DOMAIN,
            "Maison Élise",
            webhook_id,
            handle_webhook,
            allowed_methods=("POST",),
        )
    except ValueError as err:
        raise ConfigEntryNotReady(
            "Maison Élise webhook is already registered"
        ) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        CONF_WEBHOOK_ID: webhook_id,
        CONF_CLOUDHOOK_URL: cloudhook_url,
    }

    persistent_notification.async_create(
        hass,
        (
            "La passerelle vocale Maison Élise est prête.\n\n"
            "Le Cloudhook actuel est conservé pour la skill Maison Élise existante.\n\n"
            "Ne modifie pas la skill ni cette URL pendant la migration App."
        ),
        title="Maison Élise Bridge",
        notification_id=NOTIFICATION_ID,
    )

    _LOGGER.info("Maison Élise Bridge is ready in App-first mode with rollback")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Maison Élise Bridge without changing its cloudhook URL."""
    webhook_id = str(entry.data[CONF_WEBHOOK_ID])
    webhook.async_unregister(hass, webhook_id)

    entries = hass.data.get(DOMAIN)
    if isinstance(entries, dict):
        entries.pop(entry.entry_id, None)
        if not entries:
            hass.data.pop(DOMAIN, None)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the cloudhook only when the integration is removed permanently."""
    webhook_id = str(entry.data[CONF_WEBHOOK_ID])
    try:
        await cloud.async_delete_cloudhook(hass, webhook_id)
    except (cloud.CloudNotAvailable, cloud.CloudNotConnected):
        _LOGGER.debug(
            "Cloudhook deletion deferred because Home Assistant Cloud is unavailable"
        )
