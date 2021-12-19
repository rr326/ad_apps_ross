import json
import re
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import adplus
from appdaemon.adapi import ADAPI
from appdaemon.plugins.mqtt import mqttapi as mqtt

adplus.importlib.reload(adplus)

# pylint: disable=unused-argument


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
        !str = must NOT equal string (eg: pattern_host="!pihaven" means host != "pihaven")
        str = must equal string
        TODO (maybe) - more powerful matching
    """

    def __init__(
        self,
        adapi: ADAPI,
        mqtt_base_topic: str,
        event: str,
        pattern: Optional[EventPattern],
    ):
        self.adapi = adapi
        self.mqtt_base_topic = mqtt_base_topic
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

        if parts[0] != self.mqtt_base_topic:
            self.adapi.log(
                f"split failed - does not start with {self.mqtt_base_topic}: {self.event}"
            )
            return False

        self.host = parts[1]
        self.event_type = parts[2]
        self.entity = parts[3] if len(parts) >= 4 else None
        return True

    def _match_pattern(self, value: Optional[str], pattern: Optional[str]) -> bool:
        """
        None --> True
        !pattern != value --> True
        pattern == value --> True
        Otherwise False
        """
        if pattern is None:
            return True
        if pattern[0] == "!":
            return pattern[1:] != value
        else:
            return pattern == value

    def _do_match(self):
        return (
            self._match_pattern(self.host, self._pattern_host)
            and self._match_pattern(self.event_type, self._pattern_event_type)
            and self._match_pattern(self.entity, self._pattern_entity)
        )


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

    def __init__(self, adapi: ADAPI, mqtt_base_topic: str):
        self.adapi = adapi
        self.mqtt_base_topic = mqtt_base_topic

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

    def default_callback(
        self, host, event_type, entity, payload, payload_as_obj
    ) -> list:
        return [
            self.adapi.log(
                f"default_callback: {host}/{event_type}/{entity} -- {payload}"
            )
        ]

    def safe_payload_as_obj(self, payload) -> Optional[object]:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
        except Exception:
            self.adapi.log(f"Unexpected error trying to json decode: {payload}")
            return None

    def dispatch(self, mq_event, payload) -> list:
        did_dispatch = False
        results = []
        for name, listener in self._listeners.items():
            ep = EventParts(
                self.adapi, self.mqtt_base_topic, mq_event, listener.pattern
            )
            if ep.matches:
                self.adapi.log(f"dispatcher: dispatching to: {name}")
                results.append(
                    listener.callback(
                        ep.host,
                        ep.event_type,
                        ep.entity,
                        payload,
                        self.safe_payload_as_obj(payload),
                    )
                )
                did_dispatch = True

        if not did_dispatch:
            self.adapi.log(f"dispatcher: could not find pattern to match: {mq_event}.")
        return results


class SyncEntitiesViaMqtt(mqtt.Mqtt):
    """
    This syncs the state of selected entities across multiple HA installations via MQTT.

    It requires both HA installations to share state via MQTT (probably via a bridge)
    with a shared topic (eg: mqtt_shared)


    TODO - Make this generic

    Devnotes
    * If you create a new entity with set_state(entity_id="something_new"),
    it will *create* the entity, but it will not function normally.
    For instance, you can't use the UI to turn the entity off. You can't
    even listen on a "call_service" event, since it won't trigger.
    (Despite what it says here: https://community.home-assistant.io/t/dynamically-create-ha-entity/66869)
    * Instead, create a read-only sensor.
    * Then to trigger a change, in the UI override "tap-action" to have it fire off an MQTT message
    to tell the source machine to turn it change state, which will then reflect back locally.
    """

    MQTT_DEFAULT_BASE_TOPIC = "mqtt_shared"

    SCHEMA = {
        "my_hostname": {
            "required": True,
            "type": "string",
            "regex": "^[^-]+$",  # No dashes permitted
        },
        "mqtt_base_topic": {
            "required": False,
            "type": "string",
            "default": MQTT_DEFAULT_BASE_TOPIC,
        },
        "state_for_entities": {
            "required": False,
            "type": "list",
            "schema": {"type": "string"},
        },
    }

    def initialize(self):
        self.log("Initialize")
        self.argsn = adplus.normalized_args(self, self.SCHEMA, self.args, debug=False)
        self.state_entities = self.argsn.get("state_for_entities")
        self._state_listeners = set()
        self._remote_entity_listeners = {}
        self.my_hostname = self.argsn.get("my_hostname", "HOSTNAME_NOT_SET")
        self.mqtt_base_topic = self.argsn.get(
            "mqtt_base_topic", self.MQTT_DEFAULT_BASE_TOPIC
        )

        self.dispatcher = EventListenerDispatcher(
            self.get_ad_api(), self.mqtt_base_topic
        )

        # Note - this will not work if you have previously registered wildcard="#"
        self.mqtt_unsubscribe(
            "#", namespace="mqtt"
        )  # Be safe, though this will hurt other apps. Figure out.
        self.mqtt_subscribe(f"{self.mqtt_base_topic}/#", namespace="mqtt")

        # Register event dispatch listeners - processing INCOMING messages
        self.dispatcher.add_listener("print all", EventPattern(), None)
        self.dispatcher.add_listener(
            "ping/pong",
            EventPattern(
                pattern_host=f"!{self.my_hostname}",  # Only listen to for events I didn't create
                pattern_event_type="ping",
            ),
            self.ping_callback,
        )
        self.dispatcher.add_listener(
            "inbound state",
            EventPattern(
                pattern_host=f"!{self.my_hostname}",  # Only listen to for events I didn't create
                pattern_event_type="state",
            ),
            self.inbound_state_callback,
        )

        # Register OUTGOING messages
        self.run_in(self.register_state_entities, 0)

        # Listen to all MQ events
        self.listen_event(
            self.mq_listener,
            "MQTT_MESSAGE",
            wildcard=f"{self.mqtt_base_topic}/#",
            namespace="mqtt",
        )

    def entity_add_hostname(self, entity: str, host: str) -> str:
        """
        light.named_light, host -> light.named_light_#host#

        opposite: entity_split_hostname()
        """
        return f"{entity}xxx{host}xxx"

    def entity_split_hostname(self, entity: str) -> Tuple[str, Optional[str]]:
        """
        light.named_light#pihaven# -> ("light.named_light", "pihaven")
        light.local_light -> ("light.local_light", None)

        opposite: entity_add_myhostname()
        """
        match = re.fullmatch(r"(.*)xxx([^#]+)xxx", entity)
        if match:
            return (match.group(1), match.group(2))
        else:
            return (entity, None)

    def mq_listener(self, event, data, kwargs):
        self.log(f"mq_listener: {event}, {data}")
        self.dispatcher.dispatch(data.get("topic"), data.get("payload"))

    def ping_callback(self, host, event, entity, payload, payload_asobj=None):
        self.log(
            f"PING/PONG - {self.mqtt_base_topic}/{host}/pong - {payload} [my_hostname: {self.my_hostname}]"
        )
        self.mqtt_publish(
            topic=f"{self.mqtt_base_topic}/{self.my_hostname}/pong",
            payload=payload,
            namespace="mqtt",
        )

    def inbound_state_callback(self, host, event, entity, payload, payload_asobj=None):
        (_, entity_host) = self.entity_split_hostname(entity)
        if entity_host is not None:
            # Should not be here - programming error
            self.log(
                f"inbound_state_callback(): Ignoring /{host}/{event}/{entity} -- {payload}",
                level="ERROR",
            )
            return

        self.log(
            f"inbound_state_callback(): set_state: /{host}/{event}/{entity} -- {payload}"
        )

        remote_entity = self.entity_add_hostname(entity, host)
        self.log(f"inbound_callback() set_state({remote_entity}, state={payload})")
        self.set_state(f"{remote_entity}", state=payload, namespace="default")

        # Need to listen for changes to this entity, but only once.
        # You need to do this every time the app reloads.
        if remote_entity not in self._remote_entity_listeners:
            # We created the entity. Watch for changes
            def remote_entity_callback(entity, attribute, old, new, kwargs):
                (remote_entity, remote_host) = self.entity_split_hostname(entity)
                self.log(
                    f"remote_entity_callback({entity}, {new}) --> {self.mqtt_base_topic}/{remote_entity}/state/{remote_host}"
                )
                self.mqtt_publish(
                    topic=f"{self.mqtt_base_topic}/{remote_entity}/state/{remote_host}",
                    payload=new,
                    namespace="mqtt",
                )

            cancel_handle = self.listen_state(
                remote_entity_callback, entity=remote_entity
            )
            self._remote_entity_listeners[remote_entity] = cancel_handle
            self.log(f"Added remote_entity state listener for {remote_entity}")

            # Unfortunately when you make a non-sensor entity with Appdaemon
            # it doesn't behave properly. So to enable on/off functionality, you
            # need to handle that yourself. Listen for events for the entity.
            def capture_changes_callback(event_name, data, kwargs):
                # This will get ALL call-service events. Be efficient!
                # event_entity = data.get("")
                self.log(
                    f"capture_changes_callback() data:\nevent:{event_name}\n{json.dumps(data,indent=4)}"
                )

            self.listen_event(
                capture_changes_callback, event="call_service", oneshot=True
            )

    def register_state_entities(self, kwargs):
        def state_callback(entity, attribute, old, new, kwargs):
            self.log(f"state_callback(): {entity} -- {attribute} -- {new}")
            self.mqtt_publish(
                topic=f"{self.mqtt_base_topic}/{self.my_hostname}/state/{entity}",
                payload=new,
                namespace="mqtt",
            )

        for entity in self.state_entities:
            cur_state = self.get_state(entity)
            self.log(f"** registered {entity} -- {cur_state}")
            self._state_listeners.add(self.listen_state(state_callback, entity))


class TestSyncEntitiesViaMqtt(adplus.Hass):
    """
    This runs some tests that would normally be run under pytest.
    But getting it all working with pytest is more trouble than it is worth.
    (Since Appdaeomon loads modules dynamically.)
    """

    def initialize(self):
        self.log("Initialize")

        self.run_in(self.test_event_parts, 0)
        self.run_in(self.test_dispatcher, 0)

    def test_event_parts(self, _):
        adapi = self.get_ad_api()
        mqtt_base_topic = SyncEntitiesViaMqtt.MQTT_DEFAULT_BASE_TOPIC

        topic = "BOGUS/pi-haven/ping"
        assert EventParts(adapi, mqtt_base_topic, topic, None).matches is False

        topic = f"{mqtt_base_topic}/pi-haven/ping"
        assert EventParts(adapi, mqtt_base_topic, topic, None).matches is True

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity/BOGUS"
        assert EventParts(adapi, mqtt_base_topic, topic, None).matches is False

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity"
        assert EventParts(adapi, mqtt_base_topic, topic, None).matches is True

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity"
        assert (
            EventParts(adapi, mqtt_base_topic, topic, EventPattern("pi-haven")).matches
            is True
        )

        topic = f"{mqtt_base_topic}/BOGUS/state/myentity"
        assert (
            EventParts(adapi, mqtt_base_topic, topic, EventPattern("pi-haven")).matches
            is False
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_event_type="state")
            ).matches
            is True
        )

        topic = f"{mqtt_base_topic}/pi-haven/BOGUS/myentity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_event_type="state")
            ).matches
            is False
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_entity="myentity")
            ).matches
            is True
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/BOGUS"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_entity="myentity")
            ).matches
            is False
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/entity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_host="pi-haven")
            ).matches
            is True
        )

        topic = f"{mqtt_base_topic}/pi-seattle/state/entity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_host="pi-haven")
            ).matches
            is False
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/entity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_host="!pi-haven")
            ).matches
            is False
        )

        topic = f"{mqtt_base_topic}/pi-seattle/state/entity"
        assert (
            EventParts(
                adapi, mqtt_base_topic, topic, EventPattern(pattern_host="!pi-haven")
            ).matches
            is True
        )

        topic = f"{mqtt_base_topic}/pi-haven/state/myentity"
        assert (
            EventParts(
                adapi,
                mqtt_base_topic,
                topic,
                EventPattern("pi-haven", "state", "myentity"),
            ).matches
            is True
        )

        self.log("**test_event_parts() - all pass!**")

    def test_dispatcher(self, _):
        adapi = self.get_ad_api()
        mqtt_base_topic = SyncEntitiesViaMqtt.MQTT_DEFAULT_BASE_TOPIC

        def callback(host, event_type, entity, payload, payload_as_obj):
            return payload

        dispatcher = EventListenerDispatcher(adapi, mqtt_base_topic)

        assert (
            dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == []
        )  # no registered callbacks

        event_pattern1 = EventPattern("pi-haven", "state", "myentity")
        dispatcher.add_listener("/pi-haven/state/myentity", event_pattern1, callback)
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == ["1"]
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/BOGUS", "1") == []

        event_pattern2 = EventPattern("pi-haven", "state", None)
        dispatcher.add_listener("/pi-haven/state/+", event_pattern2, callback)
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/myentity", "1") == [
            "1",
            "1",
        ]
        assert dispatcher.dispatch("mqtt_shared/pi-haven/state/DIFFERENT", "1") == ["1"]

        self.log("**test_dispatcher() - all pass!**")