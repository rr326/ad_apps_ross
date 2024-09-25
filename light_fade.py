from math import ceil
from typing import Tuple

import adplus

adplus.importlib.reload(adplus)

KWARGS_SCHEMA = {
    "entity_id": {"required": True, "type": "string", "check_with": "validate_entity"},
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
}


class LightFade(adplus.Hass):
    """
    See README.md
    """

    def initialize(self):
        self.log("Initialize")
        self.listen_event(self.cb_fade_begin, "light_fade.begin")

    @staticmethod
    def val_to_pct(val: int) -> float:
        "brigtness pct to brightness val"
        v = max(0, min(255, val if val is not None else 0 ))  # HA actually gave me a value > 255!
        return v / 255

    @staticmethod
    def pct_to_val(val: float) -> int:
        "brigtness pct to brightness val"
        v = max(0, min(1.0, val / 100))
        return round(v * 255)

    def cb_fade_begin(self, event_name, data, kwargs):
        MIN_BRIGHTNESS = 26  # My leviton has a minimum value of 26. (or 0)

        self.log(f'Begin LightFade: {data["entity_id"]}')

        args = adplus.normalized_args(self, KWARGS_SCHEMA, data, debug=False)

        entity_id = args["entity_id"]
        current_brightness_val = self.get_state(
            entity_id, attribute="brightness", default=0
        )
        current_brightness = self.val_to_pct(current_brightness_val)
        brightness_start = (
            args["brightness_start"] if args["brightness_start"] else current_brightness
        )
        brightness_start = brightness_start or 0
        brightness_end = args["brightness_end"]
        duration = args["duration"]
        increase = brightness_end >= brightness_start

        bright_start = self.pct_to_val(brightness_start)
        bright_end = self.pct_to_val(brightness_end)

        def calc_step(
            bright_start: int, bright_end: int, duration: int
        ) -> Tuple[int, int, int]:
            STEP_SHORTEST_DURATION = (
                5  # It takes some time for the entity to respond to a changed state.
            )
            STEP_SIZE_MIN = 3  # round(0.01 * 255)  # 1% min step size
            num_steps = ceil(duration / STEP_SHORTEST_DURATION)

            total = abs(bright_end - bright_start)
            step_duration = STEP_SHORTEST_DURATION

            step_size = max(ceil(total / (duration / step_duration)), STEP_SIZE_MIN)

            # Now recalculate step duration
            step_duration = max(
                STEP_SHORTEST_DURATION, ceil(duration / (total / step_size))
            )

            self.debug(
                f"LightFade: step_duration: {step_duration} -- step_size: {step_size} -- num_steps: {num_steps} -- total increase: {num_steps * step_size} -- bright_start: {bright_start} -- bright_end: {bright_end} -- duration: {duration}",
            )
            return step_duration, step_size, num_steps

        # For testing
        # calc_step(0,100,10)
        # calc_step(0,100,60)
        # calc_step(0,100,300)
        # calc_step(0,100,600)
        # calc_step(0,50,10)
        # calc_step(0,50,60)
        # calc_step(0,50,300)
        # calc_step(0,50,600)
        # return

        step_duration, step_size, num_steps = calc_step(
            bright_start, bright_end, duration
        )

        # Initialize
        bright_target = max(bright_start + 1, MIN_BRIGHTNESS)
        self.turn_on(
            entity_id, brightness=bright_target
        )  # It won't turn on with brightness = 0. And for my Leviton, the min brightness appears to be 26!
        current_brightness_val = self.get_state(
            entity_id, attribute="brightness", default=0
        )
        if num_steps > 0:
            self.run_in(
                self.cb_fader,
                step_duration,
                entity_id=entity_id,
                bright_start=bright_start,
                bright_end=bright_end,
                increase=increase,
                step_duration=step_duration,
                step_size=step_size,
                last_step=1,
                bright_target=bright_target,
                bright_previous=current_brightness_val,
            )

    def cb_fader(self, kwargs):
        entity_id = kwargs["entity_id"]
        bright_start = kwargs["bright_start"]
        bright_end = kwargs["bright_end"]
        increase = kwargs["increase"]
        step_duration = kwargs["step_duration"]
        step_size = kwargs["step_size"]
        last_step = kwargs["last_step"]
        bright_target = kwargs["bright_target"]
        bright_previous = kwargs["bright_previous"]

        current_brightness_val = self.get_state(
            entity_id, attribute="brightness", default=0
        )
        try:
            self.debug(
                f"cb_fader step_num: {last_step:3} -- current: {current_brightness_val:3} -- last target: {bright_target:3} -- start: {bright_start} -- end: {bright_end} -- step_duration: {step_duration} -- step_size: {step_size} "
            )
        except Exception as e:
            self.debug(f"Error in self.dubug for light_fade: {e}")
            self.debug(last_step)
            self.debug(current_brightness_val)
            self.debug(bright_target)
            self.debug(bright_start)
            self.debug(bright_end)
            self.debug(step_duration)
            self.debug(step_size)

        CLOSE_ENOUGH = 5
        if (
            abs(current_brightness_val - bright_target) > CLOSE_ENOUGH
            and abs(current_brightness_val - bright_previous) > CLOSE_ENOUGH
        ):
            self.log(
                f"Looks like someone has manually changed the value. Cancel light fader. currernt_brightness: {current_brightness_val}. bright_target: {bright_target}. bright_previous: {bright_previous}"
            )
            return

        if (increase and current_brightness_val >= bright_end) or (
            not increase and current_brightness_val <= bright_end
        ):
            self.log(
                f"Done. current_brightness_val: {current_brightness_val}. bright_end target: {bright_end}"
            )
            return

        if (last_step - 1) * step_size > abs(bright_end - bright_start):
            return

        new_brightness = current_brightness_val + step_size * (1 if increase else -1)
        if increase:
            new_brightness = min(new_brightness, bright_end, 255)
        else:
            new_brightness = max(new_brightness, bright_end, 0)

        if new_brightness <= 0:
            self.turn_off(entity_id, brightness=0)
        else:
            self.turn_on(entity_id, brightness=new_brightness)

        self.run_in(
            self.cb_fader,
            step_duration,
            entity_id=entity_id,
            bright_start=bright_start,
            bright_end=bright_end,
            increase=increase,
            step_duration=step_duration,
            step_size=step_size,
            last_step=last_step + 1,
            bright_target=new_brightness,
            bright_previous=current_brightness_val,
        )


class TestLightFade(adplus.Hass):
    """
    Testing
    """

    def initialize(self):
        self.log(f"Initialize")
        self.run_in(self.call_fire, 1)

    def call_fire(self, kwargs):
        self.log(f"Firing event light_fade.being with args: {self.args}")
        self.fire_event("light_fade.begin", **self.args)
