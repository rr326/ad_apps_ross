import json  # noqa
from typing import Dict, Optional, cast

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
        self.app_color_entity = f"app.{self.appname}"
        self.climates = self.argsn["climate"]["entities"]
        self.app_state_entity = self.argsn["app_state"]
        self.configured_climates = [
            "climate.cabin",
            "climate.master_bath",
            "climate.gym",
            "climate.tv_room",
        ]
        self.home_state_entity = self.argsn["home_state_entity"]
        self.water_shutoff_valve = "switch.haven_flo_shutoff_valve"
        self.water_system_mode = "sensor.haven_flo_current_system_mode"

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
        self.set_colors_for_water()
        self.listen_state(
            self.set_color_for_all, entity=self.app_state_entity, attribute="all"
        )
        self.listen_state(self.set_color_for_all, entity=self.home_state_entity)
        self.listen_state(self.set_colors_for_water, entity=self.home_state_entity)
        self.listen_state(
            self.set_colors_for_water, entity=self.water_shutoff_valve
        ) 
        self.listen_state(
            self.set_colors_for_water, entity=self.water_system_mode
        )  # Takes a long time to change, so watch it.

        self.log("Fully initialized")

    def set_color_for_all(self, *args):
        for climate in self.climates:
            self.set_color_for(climate)

    def valid_home_state(self):
        home_mode = self.get_state(self.home_state_entity)
        if self.get_state(self.home_state_entity) not in [
            "Home",
            "Away",
            "Arriving",
            "Leaving",
        ]:
            self.warn(f"Unexpected home_mode: {home_mode}")
            return False
        return True

    def set_app_state(self, new_dict: dict):
        """
        **Merges** state into existsing state
        """
        if self.entity_exists(self.app_color_entity):
            existing = self.get_state(self.app_color_entity, attribute="all")
        else:
            existing = {}

        if not isinstance(new_dict, dict):
            self.warn(f"Got unexpected value for {self.app_color_entity}: {new_dict}")
            return
        existing = cast(dict, existing)
        existing = existing.get("attributes", {})

        self.set_state(
            self.app_color_entity, state="colors", attributes={**existing, **new_dict}
        )

    def set_color_for(self, climate, *args):
        """
        Can be called as state callback or normal, non-callback call.

        The first arg will always be climate
        """

        if not self.valid_home_state():
            return

        # Business logic
        color = None
        def check(service):
            return self.call_service(
            f"autoclimate/{service}", climate=climate, return_result=True
        )

        home_mode = self.get_state(self.home_state_entity)
        if home_mode in ["Home", "Arriving"]:
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
        elif home_mode in ["Away", "Leaving"]:
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

        #
        # Now do overall state
        #
        overall = self.get_state("app.autoclimate_state")
        overall_color = None
        if overall == "offline":
            overall_color = "yellow"
        elif home_mode in ["Home", "Arriving"]:
            if overall == "on":
                overall_color = "green"
            elif overall == "off":
                overall_color = "white"
            else:
                overall_color = "purple"
        elif home_mode in ["Away", "Leaving"]:
            if overall == "on":
                overall_color = "red"
            elif overall == "off":
                overall_color = "white"
            else:
                overall_color = "purple"
        else:
            overall_color = "purple"

        # Flatten
        data = {climate: self.colors_dict[climate] for climate in self.climates}
        data["overall"] = overall_color

        self.set_app_state(data)

    def set_colors_for_water(self, *args):
        if not self.valid_home_state():
            return

        # Initialize
        water_shutoff_color = "purple"
        water_system_mode_color = "purple"

        home_mode = self.get_state(self.home_state_entity)
        water_shutoff_state = str(self.get_state(self.water_shutoff_valve)).lower()
        water_system_mode = str(self.get_state(self.water_system_mode)).lower()
        if home_mode in ["Arriving", "Away"]:
            if water_shutoff_state == "off":
                water_shutoff_color = "white"
            else:
                water_shutoff_color = "yellow"

            if water_system_mode == "away":
                water_system_mode_color = "white"
            else:
                water_system_mode_color = "yellow"
        elif home_mode in ["Leaving", "Home"]:
            if water_shutoff_state == "on":
                water_shutoff_color = "green"
            else:
                water_shutoff_color = "red"

            if water_system_mode == "home":
                water_system_mode_color = "green"
            else:
                water_system_mode_color = "red"

        self.set_app_state(
            {
                "switch.haven_flo_shutoff_valve": water_shutoff_color,
                "sensor.haven_flo_current_system_mode": water_system_mode_color,
            }
        )
