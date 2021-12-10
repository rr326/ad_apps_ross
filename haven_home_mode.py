import adplus
from appdaemon.adapi import ADAPI
from appdaemon.plugins.mqtt import mqttapi as mqtt
from dataclasses import dataclass
import re
from typing import Callable, Optional
import json

adplus.importlib.reload(adplus)

# Topic format: mqtt_shared/<source_hostname>/<event_type>/<entity> "payload as string"
# EG:
#   mqtt_shared/pi-haven/state/light.outside_porch 'on' # plain text
#   mqtt_shared/pi-haven/state/light.outside_porch '{state: "on", attribute1: "value"}' # JSON
MQTT_BASE_TOPIC = "mqtt_shared"


@dataclass
class EventPattern:
    pattern_host: Optional[str] = None
    pattern_event_type: Optional[str] = None
    pattern_entity: Optional[str] = None


class EventParts:
    """
    Splits a topic string into its components.
    If does not match, it will NOT fail. Just reports self.matches == False

    event:
        mqtt_shared/<source_hostname>/<event_type>/<entity>
        mqtt_shared/pi-haven/state/light.outside_porch
        mqtt_shared/pi-haven/ping

    match_host, match_event_type, match_entity:
        None = match any value (like regex ".*")
        str = must equal string
        TODO (maybe) - more powerful matching
    """

    def __init__(self, adapi: ADAPI, event: str, pattern: Optional[EventPattern]):
        self.adapi = adapi
        self.event = event
        self._pattern_host = pattern.pattern_host if pattern else None
        self._pattern_event_type = pattern.pattern_event_type if pattern else None
        self._pattern_entity = pattern.pattern_entity if pattern else None

        self.matches = False
        self.host = None
        self.event_type = None
        self.entity = None

        split_ok = self._do_split()
        if split_ok:
            self.matches = self._do_match()

    def _do_split(self):
        parts = self.event.split("/")
        if len(parts) < 3 or len(parts) > 4:
            self.adapi.log(f"match failed - improper format: {self.event}")
            return False

        if parts[0] != MQTT_BASE_TOPIC:
            self.adapi.log(
                f"split failed - does not start with {MQTT_BASE_TOPIC}: {self.event}"
            )
            return False

        self.host = parts[1]
        self.event_type = parts[2]
        self.entity = parts[3] if len(parts) >= 4 else None
        return True

    def _do_match(self):
        if self._pattern_host and self.host != self._pattern_host:
            return False

        if self._pattern_event_type and self.event_type != self._pattern_event_type:
            return False

        if self._pattern_entity and self.entity != self._pattern_entity:
            return False
        
        return True


@dataclass
class EventListener:
    name: str
    pattern: EventPattern
    callback: Callable


class EventListenerDispatcher:
    """
    This will dispatch *ALREADY CAUGHT* mqtt events and send them to the proper callback.
    
    Usage:
    
    dispatcher = EventListenerDispatcher(self.adapi)
    def my_callback(host_str, event_str, entity_str, payload, payload_asobj=None): pass
    
    dispatcher.add_listener("listen for all state changes", EventPattern(event_type="state"), my_callback)
    
    # new event from MQ caught: "mqtt_shared/pi-haven/state/light.outside_porch 'on'"
    dispatcher.dispatch(mq_event, payload)
    """
    def __init__(self, adapi: ADAPI):
        self.adapi = adapi

        self._listeners = {}

    def add_listener(self, name, pattern: EventPattern, callback):
        if name in self._listeners:
            self.adapi.log(
                f"add_listener - being asked to re-register following listener: {name}",
                LEVEL="WARNING",
            )
            del self._listeners["name"]

        self._listeners[name] = EventListener(
            name, pattern, callback if callback else self.default_callback
        )

    def remove_listener(self, name):
        if name not in self._listeners:
            self.adapi.log(
                f"remove_listener - being asked to remove listener that is not found: {name}",
                LEVEL="WARNING",
            )
            return
        del self._listeners["name"]

    def default_callback(self, host, event_type, entity, payload, payload_as_obj) -> list:
        return [self.adapi.log(f"default_callback: {host}/{event_type}/{entity} -- {payload}")]
        
    def safe_payload_as_obj(self, payload) -> Optional[object]:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
        except Exception:
            self.adapi.log(f'Unexpected error trying to json decode: {payload}')
            return None

    def dispatch(self, mq_event, payload) -> list:
        did_dispatch = False
        results = []
        for name, listener in self._listeners.items():
            ep = EventParts(self.adapi, mq_event, listener.pattern)
            if ep.matches:
                self.adapi.log(f"dispatcher: dispatching to: {name}")
                results.append(listener.callback(ep.host, ep.event_type, ep.entity, payload, self.safe_payload_as_obj(payload)))
                did_dispatch = True
           
        if not did_dispatch:
            self.adapi.log(f"dispatcher: could not find pattern to match: {mq_event}.")
        return results


class HavenHomeModeSync(mqtt.Mqtt):
    """
    This uses MQ to sync the state of Haven's home mode.
    """

    HAVEN_MODE_ENTITY = "input_select.home_state"  # Arriving, Home, Leaving, Away
    SEATTLE_MODE_ENTITY = "input_select.pihaven_home_state"  # Mirror
    MQ_MIRRORED_TOPICS = "mqtt_shared/#"

    def initialize(self):
        self.log("Initialize")
        
        self.dispatcher = EventListenerDispatcher(self.get_ad_api())

        # Note - this will not work if you have previously registered wildcard="#"
        self.mqtt_unsubscribe(
            "#", namespace="mqtt"
        )  # Be safe, though this will hurt other apps. Figure out.
        self.mqtt_subscribe(self.MQ_MIRRORED_TOPICS, namespace="mqtt")

        
        # Register event dispatch listeners
        self.dispatcher.add_listener("print all", EventPattern(), None)
        self.dispatcher.add_listener("ping/pong", EventPattern(pattern_event_type="ping"), self.ping_callback)
        
        # Listen to all MQ events
        self.listen_event(
            self.mq_listener,
            "MQTT_MESSAGE",
            wildcard=self.MQ_MIRRORED_TOPICS,
            namespace="mqtt",
        )

    def mq_listener(self, event, data, kwargs):
        self.log(f"mq_listener: {event}, {data}")
        self.dispatcher.dispatch(data.get('topic'), data.get('payload'))
        
    def ping_callback(self, host_str, event_str, entity_str, payload, payload_asobj=None):
        self.log(f'PING/PONG - {MQTT_BASE_TOPIC}/{host_str}/pong - {payload}')
        self.mqtt_publish(topic=f"{MQTT_BASE_TOPIC}/{host_str}/pong", payload=payload, namespace="mqtt")


class HavenHomeMode(adplus.Hass):
    def initialize(self):
        self.log("Initialize")


class TestHavenHomeMode(adplus.Hass):
    """
    This runs some tests that would normally be run under pytest.
    But getting it all working with pytest is more trouble than it is worth. 
    (Since Appdaeomon loads modules dynamically.)
    """
    def initialize(self):
        self.log("Initialize")
        
        self.run_in(self.test_event_parts,0)
        self.run_in(self.test_dispatcher,0)
        
        
    def test_event_parts(self, _):
        adapi = self.get_ad_api()
        
        topic = "BOGUS/pi-haven/ping"
        assert EventParts(adapi, topic, None).matches is False
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/ping"
        assert EventParts(adapi, topic, None).matches is True
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity/BOGUS"
        assert EventParts(adapi, topic, None).matches is False
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity"
        assert EventParts(adapi, topic, None).matches is True        
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity"
        assert EventParts(adapi, topic, EventPattern("pi-haven")).matches is True            
        
        topic = f"{MQTT_BASE_TOPIC}/BOGUS/state/myentity"
        assert EventParts(adapi, topic, EventPattern("pi-haven")).matches is False   
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity"
        assert EventParts(adapi, topic, EventPattern(pattern_event_type="state")).matches is True      
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/BOGUS/myentity"
        assert EventParts(adapi, topic, EventPattern(pattern_event_type="state")).matches is False      
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity"
        assert EventParts(adapi, topic, EventPattern(pattern_entity="myentity")).matches is True      
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/BOGUS"
        assert EventParts(adapi, topic, EventPattern(pattern_entity="myentity")).matches is False      
        
        topic = f"{MQTT_BASE_TOPIC}/pi-haven/state/myentity"
        assert EventParts(adapi, topic, EventPattern("pi-haven", "state", "myentity")).matches is True           
        
        self.log('**test_event_parts() - all pass!**')
    
    def test_dispatcher(self, _):
        adapi = self.get_ad_api()
        

        def callback(host, event_type, entity, payload, payload_as_obj):
            return payload
        
        dispatcher = EventListenerDispatcher(adapi)
        
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == [] # no registered callbacks
        
        event_pattern1 = EventPattern("pi-haven", "state", "myentity")
        dispatcher.add_listener("/pi-haven/state/myentity", event_pattern1, callback)
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == ["1"]
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/BOGUS", "1") == [] 
        
        event_pattern2 = EventPattern("pi-haven", "state", None)
        dispatcher.add_listener("/pi-haven/state/+", event_pattern2, callback)
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == ["1", "1"] 
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/DIFFERENT", "1") == ["1"] 

        self.log('**test_dispatcher() - all pass!**')
