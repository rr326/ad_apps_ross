import json  # noqa

import adplus

adplus.importlib.reload(adplus)


class DashboardSupport(adplus.Hass):
    """
    Usage (with card_mod):

    ```yaml
    style: |
    ha-card {
        background-color: {{ state_attr('climate_dashboard', entity_id+'_color') }}
    }
    ```
    """

    SCHEMA = {
        "test_mode": {"type": "boolean", "default": False, "required": False},
        "climate": {
            "type": "dict",
            "required": True,
            "schema": {
                "entities": {
                    "required": True,
                    "type": "list",
                    "schema": {
                        "type": "string",
                        "check_with": "validate_entity",
                    },
                },
            },
        },
    }

    def initialize(self):
        self.log("Initialize")
        self.argsn = adplus.normalized_args(self, self.SCHEMA, self.args, debug=False)
        self.test_mode = self.argsn.get("test_mode")
        self.log(f"config: {json.dumps(self.argsn,indent=4)}")
        self.run_in(self.run_climate, 0)

    def run_climate(self, *args, **kwargs):
        entities = self.argsn["climate"]["entities"]
        home_mode = "Home"  # GET HOME MODE

        configed_entities = entities  # DEFINE ENTITIES I KNOW ABOUT

        # Guard against programming / config errors
        if set(entities) != set(configed_entities):
            self.warn(
                f"climate_dashboard is not displaying all entities. autoclimate_entities: {entities} -- climate_dashboard_entities: {configed_entities}"
            )

        if home_mode not in ["Home", "Away"]:
            self.warn(f"Unexpected home_mode: {home_mode}")

        # Business logic
        state_dict = {}
        color = None
        for climate in configed_entities:
            if home_mode == "Home":
                if self.call_service("autoclimate/is_offline", climate=climate, namespace="autoclimate"):
                    color = "yellow"
                elif self.call_service("autoclimate/is_on", climate=climate, namespace="autoclimate"):
                    if climate in ["climate.gym", "climate.tv_room"]:
                        color = "red"
                    else:
                        color = "green"
                elif self.call_service("autoclimate/is_hardoff", climate=climate, namespace="autoclimate"):
                    if climate == "climate.cabin":
                        color = "red"
                    else:
                        color = "white"
                else:
                    self.warn(
                        f"Unexpected state for climate: {climate}. State: {self.call_service('autoclimate/entity_state', climate=climate, namespace='autoclimate')}"
                    )
                    color = "purple"
            elif home_mode == "Away":
                if self.is_offline(climate):
                    color = "yellow"
                elif self.is_on(climate):
                    color = "red"
                elif self.is_off(climate):
                    color = "white"
                else:
                    self.warn(
                        f"Unexpected state for climate: {climate}. State: {self.state(climate)}"
                    )
                    color = "purple"

            else:
                self.warn(f"Unexpected home_mode: {home_mode}")
                color = "purple"

            state_dict[climate] = color

        # Publish state_dict.
        self.log(f"run_climate: state_dict: {json.dumps(state_dict, indent=4)}")
