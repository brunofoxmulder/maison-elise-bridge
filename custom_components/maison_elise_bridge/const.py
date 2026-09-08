from __future__ import annotations

DOMAIN = "maison_elise_bridge"

CONF_CLOUDHOOK_URL = "cloudhook_url"
CONF_INVESTIGATOR_SLUG = "investigator_slug"
CONF_INVESTIGATOR_TOKEN = "investigator_token"
CONF_WEBHOOK_ID = "webhook_id"

EXPECTED_SKILL_ID = "amzn1.ask.skill.181d55b3-1ac2-4733-b0f1-9197819204cc"

MAISON_ELISE_APP_CONVERSATION_PATH = "/api/v1/bridge/conversation"
MAISON_ELISE_APP_PORT = 8099
MAISON_ELISE_APP_SLUG_SUFFIX = "maison_elise"

INVESTIGATOR_ASK_PATH = "/api/v1/ask"
INVESTIGATOR_ENTITIES_PATH = "/api/v1/entities"
INVESTIGATOR_PORT = 8099
INVESTIGATOR_SLUG_SUFFIX = "elise_investigator_02_test"

CONFIG_TEST_TIMEOUT_SECONDS = 4
BACKGROUND_REQUEST_TIMEOUT_SECONDS = 45
MAX_QUESTION_LENGTH = 500

LAST_CALLED_SENSOR = "sensor.alexa_devices_last_called"
NOTIFICATION_ID = "maison_elise_bridge_cloudhook"
ERROR_NOTIFICATION_ID = "maison_elise_bridge_error"
