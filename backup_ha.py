# pyright: reportUnusedCoroutine=false

import datetime as dt
from pathlib import Path
from typing import Optional

import adplus

adplus.importlib.reload(adplus)

KWARGS_SCHEMA = {
    "test_mode": {"type": "boolean", "default": False, "required": False},
    "run_at_time": {"type": "string", "required": True},
    "number_to_keep": {"type": "integer", "required": True},
}


class BackupHa(adplus.Hass):
    """
    BackupHA on a schedule. Only keep <number_to_keep> backups.
    
    Requires:
        * backup integration: https://www.home-assistant.io/integrations/backup/
        * /ha_backups dir in docker container
            ```(yaml)
            volumes:
            - ../homeassistant/config/backups:/ha_backups            
            ```
    
    Stores in: 
        homeassistant/config/backups
    """

    def initialize(self):
        self.argsn = adplus.normalized_args(self, KWARGS_SCHEMA, self.args, debug=False)
        self.test_mode = self.argsn.get("test_mode")
        self.run_at_time = self.parse_time(self.argsn["run_at_time"])
        self.day_to_run = 0 # Hardcoded, Monday
        self.number_to_keep = self.argsn["number_to_keep"]
        self.backup_dir = Path("/ha_backups")
        self.MINDATE = dt.datetime(dt.MINYEAR, 1, 1)

        self.log(f"Initialize")

        self.run_in(self.maybe_backup_now, 0)
        self.run_daily(self.backup_weekly, self.run_at_time)  

    def find_latest_backup_dt(self):
        latest_dt = self.MINDATE
        for file in self.backup_dir.glob('*.tar'):
            create_ts = file.stat().st_mtime # birthtime is not available. Good enough
            if (new_dt := dt.datetime.fromtimestamp(create_ts)) > latest_dt:
                latest_dt = new_dt
                
        # Now make timezone aware
        latest_dt = latest_dt.replace(tzinfo=self.get_now().tzinfo)
        return latest_dt
    
    def run_backup(self):
        self.log('Running HA backup')
        self.call_service("backup/create")

    def maybe_backup_now(self, _):
        """If all backups are old, do one now"""
        latest_backup_dt = self.find_latest_backup_dt()
        if ((self.get_now() - latest_backup_dt) > dt.timedelta(days=7)
             or self.test_mode):
            if self.test_mode:
                self.log(f"DEBUG: running backup anyway. Actual age of oldest backup: {(self.get_now() - latest_backup_dt)} ")
            self.run_backup()
    
    def backup_weekly(self, _):
        """Once per week, backup"""
        if self.get_now().weekday() != self.day_to_run:
            self.log(f"DEBUG: backup_weekly - skipping. Wrong day.")
            return
        self.run_backup()
        