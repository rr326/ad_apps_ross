import json
from pathlib import Path
from typing import cast

import adplus
import soco
import soco.discovery
import soco.music_library

adplus.importlib.reload(adplus)


class Sonos(adplus.Hass):
    """
    https://soco.readthedocs.io/en/latest/api/soco.core.html#soco.core.SoCo
    https://soco.readthedocs.io/en/latest/api/soco.alarms.html

    # Sonos services
    * describe_sonos_system (dumps to logs/sonos_data.json upon startup)
    * play_favorites
    * stop

    ## play_favorite
    ### Triggered by event:
        * sonos_app.play_favorite
            * Data: {
                "player_name": "Marley Bedroom"
                "favorite": {
                    "uri": "..."
                    "title": "..."
                    "meta": "..."
                    }
                "volume": 25
                }

    ## stop
    ### Triggered by event:
        * sonos_app.stop
            * data: {
                 "player_name": "Marley Bedroom"
            }


    # Playing a song

    * You need to create a sonos-favorite
    * Then look in sonos_data.json
    * Copy the uri, meta, and title
    """

    def initialize(self):
        self.log("Initialize")
        self.run_in(self.describe_sonos_system, 0)
        self.listen_event(self.cb_event_play_favorite, "sonos_app.play_favorite")
        self.listen_event(self.cb_event_stop, "sonos_app.stop")
        return

    def describe_sonos_system(self, kwargs):
        devices = list(cast(set, soco.discover()))
        # favorites = list(soco.music_library.MusicLibrary().get_sonos_favorites())
        favorites = list(devices[0].get_sonos_favorites().get("favorites", []))
        devices_simple = {}

        # Currently not used.
        # def clip(line):
        #     MAX_LENGTH = 75
        #     line = str(line)
        #     if len(line) < MAX_LENGTH:
        #         return line
        #     else:
        #         return line[: MAX_LENGTH - 3] + "..."

        # def clipdict(indict):
        #     return {k: clip(v) for k, v in indict.items()}

        for dev in devices:
            devices_simple[dev.player_name] = {
                "player_name": dev.player_name,
                "ip_address": dev.ip_address,
                "group": str(dev.group),
                "volume": dev.volume,
                "play_mode": dev.play_mode,
                "transport_info": dev.get_current_transport_info(),
                "current_media_info": (dev.get_current_media_info()),
                "current_track_info": (dev.get_current_track_info()),
                # "speaker_info": dev.get_speaker_info()
            }
        data = {
            "devices": devices_simple,
            "favorites": favorites,
        }

        logfile = Path(self.config_dir) / "../logs/sonos_data.json"
        with logfile.open("wt") as fp:
            json.dump(data, fp, indent=4)

    def get_device_by_name(self, player_name, raise_on_notfound=False):
        try:
            device = soco.discovery.by_name(player_name)
            if device:
                return device
        except TypeError as err:
            self.error(
                f"soco.discover returned None for player: {player_name} err: {err}"
            )
            return None

        # Not found
        if raise_on_notfound:
            raise adplus.ConfigException(
                f"Could not find Sonos Device named: {player_name}"
            )
        return None

    def cb_event_play_favorite(self, event_name, data, kwargs):
        self.log(f"PlayFavorite: {data['player_name']}")

        device = self.get_device_by_name(data["player_name"], raise_on_notfound=True)
        if device:
            device.ramp_to_volume(data["volume"], ramp_type=data["ramp_to_volume"])
            if data.get("uri", "").find("spotify") >= 0:
                if data.get("shuffle"):
                    device.play_mode = "SHUFFLE"
                else:
                    device.play_mode = "NORMAL"
            device.play_uri(uri=data["uri"], meta=data["meta"], start=True)
        else:
            self.warn(f'Could not play favorite. Could not find {data["player_name"]}')

    def cb_event_stop(self, event_name, data, kwargs):
        self.log(f"Stop: {data['player_name']}")

        device = self.get_device_by_name(data["player_name"], raise_on_notfound=True)
        if device:
            device.stop()
