# pyright: reportUnusedCoroutine=false

import time

import adplus

adplus.importlib.reload(adplus)


class Wallmote:
    EVENT_NAME = "zwave_js_value_notification"
    PROPERTY_NAME = "scene"
    COMMAND_CLASS_NAME = "Central Scene"

    def __init__(self):
        pass


class WallmoteApp(adplus.Hass):
    """
    Wallmote Controller

    There is actually a decent blueprint here: https://community.home-assistant.io/t/zwavejs-aeon-labs-aeotec-zw130-wallmote-quad-all-scenes-supported/290685

    But HA automation is SUCH a kludge, and that blueprint is so imperfect, that it's just much easier to do it here.
    """

    SCHEMA = {
        "debug_mode": {"required": False, "type": "boolean", "default": False},
        "zwave_node_id": {"required": True, "type": "number"},
    }

    def initialize(self):
        self.log("Initialize")
        self.argsn = adplus.normalized_args(self, self.SCHEMA, self.args, debug=False)
        self.zwave_node_id = self.argsn.get("zwave_node_id")
        self.debug_mode = self.argsn["debug_mode"]
        self.climate = "climate.seattle_hvac"

        self.listen_event(self.event_listener, Wallmote.EVENT_NAME)

    def event_listener(self, event_name, data, kwargs):
        if self.debug_mode:
            self.log(
                f"event_listener: event_name: {event_name}, data: {data}, kwargs: {kwargs}"
            )

        if data["node_id"] != self.zwave_node_id:
            # Other devices can signal this event. For instance, new Enbrighten switch
            return

        if data["command_class_name"] != Wallmote.COMMAND_CLASS_NAME:
            self.warning(
                f'Improper Wallmote command class. Got: {data["command_class"]}, Expected: {Wallmote.COMMAND_CLASS_NAME}'
            )
            return

        button = int(data["property_key"])
        press_type = data["value"]
        if self.debug_mode:
            self.log(f"button: {button} -- press_type: {press_type}")

        self.take_action(button, press_type)

    def take_action(self, button, press_type):
        """
        Hardcode actions here.

        button: 1-4, clockwise from upper left
        press_type: KeyPressed, KeyHeldDown, KeyReleased

        "KeyHeldDown" will usually repeat multiple times, followed by a single KeyReleased
        """
        if self.debug_mode:
            self.info(
                f"take_action: zone: {self.zwave_node_id} - button: {button} - key: {press_type}"
            )
        if button == 1 and press_type == "KeyPressed":
            old_state = self.get_state("switch.fan_in_loft")
            self.toggle("switch.fan_in_loft")
            time.sleep(3)  # Wait for results
            new_state = self.get_state("switch.fan_in_loft")
            self.ll_success(f"Fan in loft toggled: {old_state} --> {new_state}")
            if True or self.debug_mode:
                self.info(
                    f"Wallmote - triggered toggle fan_in_loft. Old_state: {old_state} --> {new_state}"
                )
                
        elif button==2 and press_type == "KeyPressed":
            self.lb_log(
                f'Button 2 pressed: Calling mitsubishi/set_to_home_state'
            )
            self.call_service("mitsubishi/set_to_home_state")            
        else:
            if self.debug_mode:
                self.warn(
                    f"Wallmote node_id {self.zwave_node_id} - Unexpected button ({button})/ press_type ({press_type}) combination."
                )


"""
sample_event_data = {
  domain: "zwave_js",
  node_id: 38,
  home_id: 3635510990,
  endpoint: 0,
  device_id: "f44ffa348b76dccbe00f035247e6bf9a",
  command_class: 91,
  command_class_name: "Central Scene",
  label: "Scene 001",
  property: "scene",
  property_name: "scene",
  property_key: "001",
  property_key_name: "001",
  value: "KeyPressed",
  value_raw: 0,
  metadata: {
    origin: "LOCAL",
    time_fired: "2022-07-17T00:15:50.730417+00:00",
    context: {
      id: "01G84R5TEAT73XT5H1X3RQCHD7",
      parent_id: None,
      user_id: None,
    },
  },
}
"""
