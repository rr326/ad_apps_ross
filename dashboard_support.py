import json  # noqa
from typing import Dict, Optional

import adplus

adplus.importlib.reload(adplus)


class DashboardSupport(adplus.Hass):
    """
    Usage (with card_mod):

    ```yaml
    style: |
        ha-card {
            background-color: {{ state_attr('app.dashboard_colors', 'climate.gym') }};
        }
    ```
    """

    SCHEMA = {
        "test_mode": {"type": "boolean", "default": False, "required": False},
        "appname": {"required": False, "type": "string", "default": "dashboard_colors"},
        "home_state_entity": {"required": True, "type": "string"},
        "app_state": {"required": True, "type": "string"},
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
        self.appname = self.argsn["appname"]
        self.climates = self.argsn["climate"]["entities"]
        self.app_state_entity = self.argsn["app_state"]
        self.configured_climates = [
            "climate.cabin",
            "climate.master_bath",
            "climate.gym",
            "climate.tv_room",
        ]
        self.home_state_entity = self.argsn["home_state_entity"]

        self.colors_dict: Dict[str, Optional[str]] = {
            climate: None for climate in self.climates
        }

        # Guard against programming / config errors
        if set(self.climates) != set(self.configured_climates):
            self.warn(
                f"climate_dashboard is not displaying all entities. autoclimate_entities: {self.climates} -- climate_dashboard_entities: {self.configured_climates}"
            )

        self.run_in(
            self.init_all, 5
        )  # Give AutoClimate a chance to fully initialize. Prioirity & Dependencies aren't working.

    def init_all(self, kwargs):
        self.set_color_for_all()
        self.listen_state(
            self.set_color_for_all, entity=self.app_state_entity, attribute="all"
        )
        self.log("Fully initialized")

    def set_color_for_all(self, *args):
        for climate in self.climates:
            self.set_color_for(climate)

    def set_color_for(self, climate, *args):
        """
        Can be called as state callback or normal, non-callback call.

        The first arg will always be climate
        """

        home_mode = self.get_state(self.home_state_entity)
        if home_mode not in ["Home", "Away"]:
            self.warn(f"Unexpected home_mode: {home_mode}")

        # Business logic
        color = None
        check = lambda service: self.call_service(
            f"autoclimate/{service}", climate=climate, namespace="autoclimate"
        )

        if home_mode == "Home":
            if check("is_offline"):
                color = "yellow"
            elif check("is_hardoff") and climate == "climate.cabin":
                color = "orange"
            elif check("is_on"):
                if climate in ["climate.gym", "climate.tv_room"]:
                    color = "red"
                else:
                    color = "green"
            elif check("is_off"):
                color = "white"
            else:
                self.warn(
                    f"Unexpected state for climate: {climate}. State: {check('entity_state')}"
                )
                color = "purple"
        elif home_mode == "Away":
            if check("is_offline"):
                color = "yellow"
            elif check("is_hardoff") and climate == "climate.cabin":
                color = "orange"
            elif check("is_on"):
                color = "red"
            elif check("is_off"):
                color = "white"
            else:
                self.warn(
                    f"Unexpected state for climate: {climate}. State: {check('entity_state')}"
                )
                color = "purple"

        self.colors_dict[climate] = color
        # self.log(f"{climate:35} -- color: {color}")
        # Publish as flat state
        data = {climate: self.colors_dict[climate] for climate in self.climates}

        #
        # Now do overall state
        #
        overall = self.get_state("app.autoclimate_state")
        overall_color = None
        if overall == 'offline':
            overall_color = 'yellow'
        elif home_mode == "Home":
            if overall == "on":
                overall_color = "green"
            elif overall == "off":
                overall_color = "white"
            else:
                overall_color = "purple"
        elif home_mode == "Away":
            if overall == "on":
                overall_color = "red"
            elif overall == "off":
                overall_color = "white"
            else:
                overall_color = "purple" 
        else:
            overall_color = "purple"

        data["overall"] = overall_color
        # self.log(f"{'overall':35} -- color: {overall_color}")

        self.set_state(f"app.{self.appname}", state="colors", attributes=data)
