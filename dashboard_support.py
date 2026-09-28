import datetime
import json  # noqa
from copy import deepcopy
from typing import Dict, Optional, cast

import adplus

adplus.importlib.reload(adplus)

# Colour vocabulary: meaning -> colour. Code picks a meaning, never a colour.
# What each meaning means, plus the dashboard-only rows (Transition, Status,
# Action): README_shared.md "Dashboard colours" in rr326/haconfig.
COLOR = {
    "good": "green",  # on / active, and it should be
    "idle": "white",  # off, and it should be
    "notice": "orange",  # not the default, but not wrong
    "wrong": "red",  # not what the home state calls for; act
    "no_data": "yellow",  # can't trust the reading right now; expected back
    "dead": "#b0b0b0",  # out of service; won't recover on its own
    "bug": "purple",  # state the code didn't anticipate
}


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
        self.home_state_entity = self.argsn["home_state_entity"]
        self.water_shutoff_valve = "switch.haven_flo_shutoff_valve"
        self.water_system_mode = "sensor.haven_flo_current_system_mode"
        self.rinnai = "water_heater.haven_rinnai_water_heater"

        self.colors_dict: Dict[str, Optional[str]] = {
            climate: None for climate in self.climates
        }

        # Guard against config drift: this app's climate list must match the
        # zones AutoClimate manages (AutoClimate is a declared dependency).
        autoclimate = self.get_app("AutoClimate")
        autoclimate_climates = (
            list(autoclimate.args.get("entity_rules", {})) if autoclimate else []
        )
        if set(self.climates) != set(autoclimate_climates):
            self.warn(
                f"climate list differs from AutoClimate's entity_rules. dashboard_support: {self.climates} -- autoclimate: {autoclimate_climates}"
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
        self.listen_state(self.set_color_for_all, entity_id=self.home_state_entity)
        self.listen_state(self.set_colors_for_water, entity_id=self.home_state_entity)
        self.listen_state(self.set_colors_for_water, entity=self.water_shutoff_valve)
        self.listen_state(
            self.set_colors_for_water, entity=self.water_system_mode
        )  # Takes a long time to change, so watch it.
        self.listen_state(self.set_colors_for_rinnai, entity_id=self.home_state_entity)
        self.listen_state(self.set_colors_for_rinnai, entity=self.rinnai)

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

    def set_app_state(self, new_attrs: dict):
        """
        **Merges** state into existsing state
        """
        existing_state = {}
        if self.entity_exists(self.app_color_entity):
            existing_state = self.get_state(self.app_color_entity, attribute="all")
        existing_attrs = existing_state.get("attributes", {})
        orig_attrs = deepcopy(existing_attrs)

        if not isinstance(new_attrs, dict):
            self.warn(f"Got unexpected value for {self.app_color_entity}: {new_attrs}")
            return

        merged_attrs = {**existing_attrs, **new_attrs}
        if orig_attrs != merged_attrs:
            self.set_state(
                self.app_color_entity,
                state="colors",
                attributes={**existing_attrs, **new_attrs},
                _silent=True,
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
            try:
                return self.call_service(
                    f"autoclimate/{service}",
                    climate=climate,
                    namespace="default",
                )
            except Exception as err:
                self.error(f"call_service returned error: {err}")
                return None

        home_mode = self.get_state(self.home_state_entity)
        state = check("entity_state")
        if state is None:
            # AutoClimate not yet initialized; skip silently
            return

        if home_mode in ["Home", "Arriving"]:
            if check("is_offline"):
                color = COLOR["no_data"]
            elif check("is_hardoff") and climate == "climate.cabin":
                color = COLOR["notice"]
            elif check("is_on"):
                if climate in ["climate.gym", "climate.tv_room"]:
                    color = COLOR["notice"]  # expensive room heating
                else:
                    color = COLOR["good"]
            elif check("is_off"):
                color = COLOR["idle"]
            else:
                self.warn(
                    f"Unexpected autoclimate state for climate: {climate}. State: {state}"
                )
                color = COLOR["bug"]
        elif home_mode in ["Away", "Leaving"]:
            if check("is_offline"):
                color = COLOR["no_data"]
            elif check("is_hardoff") and climate == "climate.cabin":
                color = COLOR["notice"]
            elif check("is_on"):
                color = COLOR["wrong"]
            elif check("is_off"):
                color = COLOR["idle"]
            else:
                self.warn(
                    f"Unexpected state for climate: {climate}. State: {state}"
                )
                color = COLOR["bug"]

        self.colors_dict[climate] = color

        #
        # Now do overall state
        #
        overall = self.get_state("app.autoclimate_state")
        overall_color = None
        if overall == "offline":
            overall_color = COLOR["no_data"]
        elif home_mode in ["Home", "Arriving"]:
            if overall == "on":
                overall_color = COLOR["good"]
            elif overall == "off":
                overall_color = COLOR["idle"]
            else:
                overall_color = COLOR["bug"]
        elif home_mode in ["Away", "Leaving"]:
            if overall == "on":
                overall_color = COLOR["wrong"]
            elif overall == "off":
                overall_color = COLOR["idle"]
            else:
                overall_color = COLOR["bug"]
        else:
            overall_color = COLOR["bug"]

        # Flatten
        data = {climate: self.colors_dict[climate] for climate in self.climates}
        data["overall"] = overall_color

        self.set_app_state(data)

    def set_colors_for_water(self, *args):
        if not self.valid_home_state():
            return

        # Initialize
        water_shutoff_color = COLOR["bug"]
        water_system_mode_color = COLOR["bug"]

        home_mode = self.get_state(self.home_state_entity)
        water_shutoff_state = str(self.get_state(self.water_shutoff_valve)).lower()
        water_system_mode = str(self.get_state(self.water_system_mode)).lower()
        if home_mode in ["Arriving", "Away"]:
            if water_shutoff_state == "off":
                water_shutoff_color = COLOR["idle"]
            else:
                water_shutoff_color = COLOR["wrong"]

            if water_system_mode == "away":
                water_system_mode_color = COLOR["idle"]
            else:
                water_system_mode_color = (
                    COLOR["idle"]  # Not doing vacation mode anymore. Does not work reliably.
                )
        elif home_mode in ["Leaving", "Home"]:
            if water_shutoff_state == "on":
                water_shutoff_color = COLOR["good"]
            else:
                water_shutoff_color = COLOR["wrong"]

            if water_system_mode == "home":
                water_system_mode_color = COLOR["good"]
            else:
                water_system_mode_color = COLOR["wrong"]

        self.set_app_state(
            {
                "switch.haven_flo_shutoff_valve": water_shutoff_color,
                "sensor.haven_flo_current_system_mode": water_system_mode_color,
            }
        )

    def set_colors_for_rinnai(self, *args):
        if not self.valid_home_state():
            return

        # Initialize
        rinnai_away_color = COLOR["bug"]
        rinnai_temp_color = COLOR["bug"]

        home_mode = self.get_state(self.home_state_entity)
        rinnai_away_state = self.get_state(self.rinnai, attribute="away_mode")
        raw_temp = self.get_state(self.rinnai, attribute="temperature")

        # During the Rinnai integration's hourly OAuth-token refresh, attributes
        # briefly come back as None. Treat that the same as stale data (no_data)
        # and bail; the next state change after reload will recolor correctly.
        if rinnai_away_state is None or raw_temp is None:
            self.set_app_state(
                {
                    "haven_rinnai_away_mode": COLOR["no_data"],
                    "haven_rinnai_set_temperature": COLOR["no_data"],
                }
            )
            return

        rinnai_temp = int(raw_temp)

        is_old_data = True
        try:
            last_updated = datetime.datetime.fromisoformat(
                datestr := self.get_state(self.rinnai, attribute="last_updated")
            )
            now = cast(datetime.datetime, self.get_now())
            if now - last_updated <= datetime.timedelta(minutes=30):
                is_old_data = False
        except Exception as err:
            self.error(
                f"Error getting last_updated time for {self.rinnai} -- {datestr}: {err}"
            )

        if is_old_data:
            rinnai_away_color = COLOR["no_data"]
            rinnai_temp_color = COLOR["no_data"]
        elif home_mode in ["Arriving", "Leaving", "Away"]:
            if rinnai_away_state == "on":
                rinnai_away_color = COLOR["idle"]
            else:
                rinnai_away_color = COLOR["wrong"]

            if rinnai_temp == 125:
                rinnai_temp_color = COLOR["idle"]
            else:
                rinnai_temp_color = COLOR["notice"]
        elif home_mode in ["Home"]:
            if rinnai_away_state == "off":
                rinnai_away_color = COLOR["good"]
            else:
                rinnai_away_color = COLOR["wrong"]

            if rinnai_temp == 125:
                rinnai_temp_color = COLOR["good"]
            else:
                rinnai_temp_color = COLOR["wrong"]

        self.set_app_state(
            {
                "haven_rinnai_away_mode": rinnai_away_color,
                "haven_rinnai_set_temperature": rinnai_temp_color,
            }
        )
