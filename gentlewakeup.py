import datetime as dt

import adplus

adplus.importlib.reload(adplus)

KWARGS_SCHEMA = {
    "test_mode": {"type": "boolean", "default": False, "required": False},
    "alarms": {
        "required": True,
        "type": "dict",
        "valuesrules": {
            "type": "dict",
            "schema": {
                "schedule": {
                    "required": True,
                    "type": "dict",
                    "schema": {
                        "constrain_days": {
                            "required": True,
                            "type": "string",
                            "check_with": "validate_weekdays",
                        },
                        "time": {
                            "required": True,
                            "type": "string",
                            "check_with": "validate_time",
                        },
                        "duration": {
                            # Optional minutes - if none, will not turn off in 60 minuts
                            # 0 = do not turn off
                            "required": False,
                            "type": "integer",
                            "default": 60,
                        },
                    },
                },
                "lights": {
                    "required": True,
                    "type": "dict",
                    "schema": {
                        "entity_id": {
                            "required": True,
                            "type": "list",
                            "schema": {
                                "type": "string",
                                "check_with": "validate_entity",
                            },
                        },
                        "brightness_start": {
                            # Percent, as int
                            # Optional - Use current value if false
                            "required": False,
                            "type": "integer",
                            "min": 0,  # Percent, as int
                            "max": 100,
                        },
                        "brightness_end": {
                            # Percent, as int
                            "required": True,
                            "type": "integer",
                            "min": 0,
                            "max": 100,
                        },
                        "duration": {
                            # Seconds, int
                            "required": True,
                            "type": "integer",
                        },
                    },
                },
                "lights_on_nooff": {
                    "required": False,
                    "type": "dict",
                    "schema": {
                        "entity_id": {
                            "required": False,
                            "type": "list",
                            "schema": {
                                "type": "string",
                                "check_with": "validate_entity",
                            },
                        },
                    },
                },
                "sonos": {
                    "required": True,
                    "type": "dict",
                    "schema": {
                        "player_name": {
                            "required": True,
                            "type": "list",
                            "schema": {"type": "string"},
                        },
                        "favorite": {
                            "required": True,
                            "type": "dict",
                            "schema": {
                                "uri": {"required": True, "type": "string"},
                                "title": {"required": False, "type": "string"},
                            },
                        },
                        "volume": {
                            "required": True,
                            "type": "integer",
                            "min": 0,
                            "max": 100,
                        },
                    },
                },
            },
        },
    },
}


class GentleWakeup(adplus.Hass):
    """
    This fades on light dimmers and turns on sonos based on a schedule.
    It then turns everything off some time later.
    Note - the light come on 30 seconds before the Sonos.

    # gentlewakeup.yaml
        GentleWakeup:
            module: gentlewakeup
            class: GentleWakeup
            test_mode: false
            dependencies:
                - SonosApp
                - LightFade
            constrain_input_boolean: input_boolean.gentle_wakeup # Important!
            constrain_input_select: input_select.home_state,Home
            schedule:
                constrain_days: mon,tue,wed,thu,fri
                time: "08:00:00"
                duration: 60 # Optional - turn off in X mintues
            lights:
                entity_id:
                - "light.leviton_dz6hd_1bz_decora_600w_smart_dimmer_level_6" # Marley Bedroom
                - "light.leviton_dz6hd_1bz_decora_600w_smart_dimmer_level_5" # Kestrel Bedroom
                brightness_start: 0
                brightness_end: 100
                duration: 480
            lights_on_nooff:
                entity_id:
                    - light.leviton_dz6hd_1bz_decora_600w_smart_dimmer_level_2
            sonos:
                player_name:
                - "Marley Bedroom"
                - "Kestrel Bedroom"
            favorite:
            uri: "x-sonosapi-radio:ST%3a36601058461575458?sid=236&flags=8300&sn=6"
            title: "Chick Music"
            volume: 25

    # Required entities
        * input_select.home_state
            - constrain_input_boolean: input_boolean.gentle_wakeup
        * input_boolean.gentle_wakeup
            - constrain_input_select: input_select.home_state,Home

    # Exposed State
        app.gentlewakeup.running:
            state: "on" (running) / "off" (idle)

    # MQ Events
        listens:
            None
        fires:
            None
    """

    def initialize(self):
        self.log("Initialize")

        self.app_entity = "app.gentlewakeup"
        self.set_state(
            self.app_entity,
            state="off",
            attributes={"friendly_name": "Running: Gentle Wakeup"},
        )

        self.argsn = adplus.normalized_args(self, KWARGS_SCHEMA, self.args, debug=False)
        self.test_mode = self.argsn.get("test_mode")

        for config_name, config in self.argsn["alarms"].items():
            self.debug(f"Setting config for {config_name}: {config}")
            config["schedule"]["constrain_days_set"] = adplus.weekdays_as_set(
                config["schedule"]["constrain_days"]
            )
            self.run_daily(
                self.cb_gw_on,
                self.parse_time(config["schedule"]["time"]),
                config=config,
            )

            if self.test_mode:
                self.run_in(self.cb_gw_on, 0, description="For Testing", config=config)

    def is_scheduled_day(self, config: dict, date: dt.date):
        daymap = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}

        day = date.weekday()

        return daymap[day] in config["schedule"]["constrain_days_set"]

    def cb_gw_on(self, kwargs):
        self.lb_log("Starting")
        self.set_state(self.app_entity, state="on")

        config = kwargs["config"]

        if not self.is_scheduled_day(config, self.date()) and not self.test_mode:
            self.log(
                f'Abort: not scheduled today: {config["schedule"]["constrain_days"]}. Today: {self.date().weekday()}'
            )
            return

        # Lights
        for entity_id in config["lights"]["entity_id"]:
            # Fader takes a single entity id
            data = config["lights"].copy()
            data["entity_id"] = entity_id
            if not self.test_mode:
                self.fire_event("light_fade.begin", **data)
            else:
                self.log(f"Test mode: Would fire_event: light_fade.begin, {data}")

        # Lights on, no off
        if "lights_on_nooff" in config:
            for entity_id in config["lights_on_nooff"]["entity_id"]:
                if not self.test_mode:
                    self.turn_on(entity_id)
                else:
                    self.log(f"Test mode: would turn on entity, {entity_id}")

        # Sonos
        for player_name in config["sonos"]["player_name"]:
            data = config["sonos"].copy()
            data["player_name"] = player_name
            data["ramp_to_volume"] = "ALARM_RAMP_TYPE"
            data["uri"] = data["favorite"]["uri"]
            if not self.test_mode:
                self.fire_event("sonos_app.play_favorite", **data)
            else:
                self.log(
                    f"Test mode: Would fire_event: sonos_app.play_favorite, {data}"
                )

        # Now set up to turn off in 1 hour
        if config["schedule"].get("duration", 0) > 0:
            self.run_in(
                self.cb_gw_off, 60 * config["schedule"]["duration"], config=config
            )

        if self.test_mode:
            self.run_in(self.cb_gw_off, 5, config=config)

    def cb_gw_off(self, kwargs):
        self.lb_log(f"Turning off")
        self.set_state(self.app_entity, state="off")

        config = kwargs["config"]

        # Lights
        for entity_id in config["lights"]["entity_id"]:
            if not config.get("test_mode"):
                self.turn_off(entity_id)
            else:
                self.log(f"Test mode: Would turn_off({entity_id})")

        # Sonos
        for player_name in config["sonos"]["player_name"]:
            if not config.get("test_mode"):
                self.fire_event("sonos_app.stop", player_name=player_name)
            else:
                self.log(
                    f'Test mode: Would fire event: "sonos_app.stop", {player_name}'
                )
