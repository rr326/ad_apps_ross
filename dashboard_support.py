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

        configed_entities = ["climate.cabin"]  # DEFINE ENTITIES I KNOW ABOUT

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
        for entity in configed_entities:
            if home_mode == "Home":
                if self.is_offline(entity):
                    color = "yellow"
                elif self.is_on(entity):
                    if entity in ["climate.gym", "climate.tv_room"]:
                        color = "red"
                    else:
                        color = "green"
                elif self.is_hardoff(entity):
                    if entity == "climate.cabin":
                        color = "red"
                    else:
                        color = "white"
                else:
                    self.warn(
                        f"Unexpected state for entity: {entity}. State: {self.state(entity)}"
                    )
                    color = "purple"
            elif home_mode == "Away":
                if self.is_offline(entity):
                    color = "yellow"
                elif self.is_on(entity):
                    color = "red"
                elif self.is_off(entity):
                    color = "white"
                else:
                    self.warn(
                        f"Unexpected state for entity: {entity}. State: {self.state(entity)}"
                    )
                    color = "purple"

            else:
                self.warn(f"Unexpected home_mode: {home_mode}")
                color = "purple"

            state_dict[entity] = color

        # Publish state_dict.
        self.log(f"run_climate: state_dict: {json.dumps(state_dict, indent=4)}")
