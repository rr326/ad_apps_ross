# Ross Apps for AppDaemon
These are some apps I use that others might find useful.

1. **LightFade**  
   Fade a light from 0 to brightness over X seconds
2. **Sonos**
    1. describe_sonos_system() - dumps data about your system to logs/sonos_data.json upon startup
    2. play_favorite()
    3. stop()
3. **GentleWakeup**  
   This uses LightFade and Sonos to enable gentle alarms. At a certain time, fade the light on and fade the Sonos on. Then after some amount of time, turn both off. 

(These are[Appdaemon](https://appdaemon.readthedocs.io/en/latest/) applications that works with [Home Assistant](https://www.home-assistant.io/) home automation.)

## Requirements
1. [AdPlus](https://github.com/rr326/adplus)

## LightFade
Fade a light from 0 to brightess over X seconds.
Cancel if light is changed during the duration.

### Events
Listens for `light_fade.begin` with data attributes:

```python
data = {
    "entity_id": "light.xxx" 
    "brightness_start": 0 (optional)
    "brightness_end": 100 (required)
    "duration": 480 (required)
}
```

## Sonos
### describe_sonos_system()
Dumps data about your sonos system devices and favorites to `logs/sonos_data.json`. This 
is very handy in getting the data you need for GentleWakeup. (Or any other Sonos automation.)

### play_favorite()
Listens for `sonos_app.play_favorite` with the following data. It will play the favorite, ramping to volume.
```python
data = {
    "player_name": "SonosPlayerName",
    "favorite": {
        "uri": "x-sonosapi-radio:ST%3a36601058475458?sid=236&flags=8300&sn=6"
        "title": "Morning Music"
        }
    "volume": 25
}
```

### stop()
Listens for `sonos_app.stop` and stops the music.
```python
data = {
    "player_name": "SonosPlayerName"
}
```

## GentleWakeup
This uses LightFade and Sonos to enable gentle alarms. At a certain time, fade the light on and fade the Sonos on. Then after some amount of time, turn both off. 

See [gentlewakup.yaml.sample](./gentlewakeup.yaml.sample) for complete configuration.

This depends on SonosApp, LightFade, and AdPlus. (See above.)

