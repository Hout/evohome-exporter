#!/usr/bin/python3 -u

import sys
import time
import datetime as dt
from typing import KeysView
from evohomeclient2 import EvohomeClient
import prometheus_client as prom
from os import environ

username_env_var = "EVOHOME_USERNAME"
password_env_var = "EVOHOME_PASSWORD"
poll_interval_env_var = "EVOHOME_POLL_INTERVAL"
scrape_port_env_var = "EVOHOME_SCRAPE_PORT"


class hashabledict(dict):
    def __hash__(self):
        return hash(tuple(sorted(self.items())))


def loginEvohome(myclient):
    try:
        myclient._login()
    except Exception as e:
        print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
        return False
    return True


def _get_set_point(zone_schedule, day_of_week, spot_time):
    daily_schedules = {
        s["DayOfWeek"]: s["Switchpoints"] for s in zone_schedule["DailySchedules"]
    }
    switch_points = {
        dt.time.fromisoformat(s["TimeOfDay"]): s["heatSetpoint"]
        for s in daily_schedules[day_of_week]
    }
    candidate_times = [k for k in switch_points.keys() if k <= spot_time]
    if len(candidate_times) == 0:
        # no time less than current time
        return None

    candidate_time = max(candidate_times)
    return switch_points[candidate_time]


def calculate_planned_temperature(zone_schedule):
    current_time = dt.datetime.now().time()
    day_of_week = dt.datetime.today().weekday()
    return _get_set_point(zone_schedule, day_of_week, current_time) or _get_set_point(
        zone_schedule, day_of_week - 1 if day_of_week > 0 else 6, dt.time.max
    )


schedules_updated = dt.datetime.min
schedules = {}


def get_schedules():
    global schedules_updated
    global schedules

    # this takes time, update once per hour
    if schedules_updated < dt.datetime.now() - dt.timedelta(hours=1):
        for zone in client._get_single_heating_system()._zones:
            schedules[zone.zoneId] = zone.schedule()

        # schedules = {
        #     zone.zone_id: zone.schedule()
        #     for zone in client._get_single_heating_system()._zones
        # }
        schedules_updated = dt.datetime.now()


if __name__ == "__main__":
    print("Evohome exporter for Prometheus")
    try:
        username = environ[username_env_var]
        password = environ[password_env_var]
    except KeyError:
        print("Missing environment variables for Evohome credentials:", file=sys.stderr)
        print(f"\t{username_env_var} - Evohome username", file=sys.stderr)
        print(f"\t{password_env_var} - Evohome password", file=sys.stderr)
        exit(1)
    else:
        print(f"Evohome credentials read from environment variables ({username})")

    poll_interval = int(environ.get(poll_interval_env_var, 300))
    scrape_port = int(environ.get(scrape_port_env_var, 8082))

    eht = prom.Gauge(
        "evohome_temperature_celcius",
        "Evohome temperatuur in celsius",
        ["name", "thermostat", "id", "type"],
    )
    zavail = prom.Gauge(
        "evohome_zone_available",
        "Evohome zone availability",
        ["name", "thermostat", "id"],
    )
    zfault = prom.Gauge(
        "evohome_zone_fault",
        "Evohome zone has active fault(s)",
        ["name", "thermostat", "id"],
    )
    zmode = prom.Enum(
        "evohome_zone_mode",
        "Evohome zone mode",
        ["name", "thermostat", "id"],
        states=["FollowSchedule", "TemporaryOverride", "PermanentOverride"],
    )
    tcsperm = prom.Gauge(
        "evohome_temperaturecontrolsystem_permanent",
        "Evohome temperatureControlSystem is in permanent state",
        ["id"],
    )
    tcsfault = prom.Gauge(
        "evohome_temperaturecontrolsystem_fault",
        "Evohome temperatureControlSystem has active fault(s)",
        ["id"],
    )
    tcsmode = prom.Enum(
        "evohome_temperaturecontrolsystem_mode",
        "Evohome temperatureControlSystem mode",
        ["id"],
        states=[
            "Auto",
            "AutoWithEco",
            "AutoWithReset",
            "Away",
            "DayOff",
            "HeatingOff",
            "Custom",
        ],
    )
    upd = prom.Gauge("evohome_updated", "Evohome client last updated")
    up = prom.Gauge("evohome_up", "Evohome client status")
    prom.start_http_server(scrape_port)

    try:
        client = EvohomeClient(username, password)
    except Exception as e:
        print(
            "ERROR: can't create EvohomeClient\n{}: {}".format(
                type(e).__name__, str(e)
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    print("Logged into Evohome API")

    loggedin = True
    lastupdated = 0
    tcsalerts = set()
    zonealerts = dict()

    oldids = set()
    labels = {}
    lastup = False
    while True:
        temps = []
        newids = set()
        try:
            temps = list(client.temperatures())
            get_schedules()
            loggedin = True
            updated = True
            lastupdated = time.time()
        except Exception as e:
            print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
            temps = []
            updated = False
            loggedin = loginEvohome(client)
            if loggedin:
                continue

        if loggedin and updated:
            up.set(1)
            upd.set(lastupdated)
            tcs = client._get_single_heating_system()
            sysmode = tcs.systemModeStatus
            tcsperm.labels(client.system_id).set(
                float(sysmode.get("isPermanent", True))
            )
            tcsmode.labels(client.system_id).state(sysmode.get("mode", "Auto"))
            if tcs.activeFaults:
                tcsfault.labels(client.system_id).set(1)
                for af in tcs.activeFaults:
                    afhd = hashabledict(af)
                    if afhd not in tcsalerts:
                        tcsalerts.add(afhd)
                        print(
                            "fault in temperatureControlSystem: {}".format(af),
                            file=sys.stderr,
                        )
            else:
                tcsfault.labels(client.system_id).set(0)
                tcsalerts = set()
            for d in temps:
                newids.add(d["id"])
                labels[d["id"]] = [d["name"], d["thermostat"], d["id"]]
                if d["temp"] is None:
                    zavail.labels(d["name"], d["thermostat"], d["id"]).set(0)
                    eht.remove(d["name"], d["thermostat"], d["id"], "measured")
                else:
                    zavail.labels(d["name"], d["thermostat"], d["id"]).set(1)
                    eht.labels(d["name"], d["thermostat"], d["id"], "measured").set(
                        d["temp"]
                    )
                eht.labels(d["name"], d["thermostat"], d["id"], "setpoint").set(
                    d["setpoint"]
                )
                eht.labels(d["name"], d["thermostat"], d["id"], "planned").set(
                    calculate_planned_temperature(schedules[d["id"]])
                )
                zmode.labels(d["name"], d["thermostat"], d["id"]).state(
                    d.get("setpointmode", "FollowSchedule")
                )
                if d["id"] not in zonealerts.keys():
                    zonealerts[d["id"]] = set()
                if d.get("activefaults"):
                    zonefault = 1
                    for af in d["activefaults"]:
                        afhd = hashabledict(af)
                        if afhd not in zonealerts[d["id"]]:
                            zonealerts[d["id"]].add(afhd)
                            print(
                                "fault in zone {}: {}".format(d["name"], af),
                                file=sys.stderr,
                            )
                else:
                    zonefault = 0
                    zonealerts[d["id"]] = set()
                zfault.labels(d["name"], d["thermostat"], d["id"]).set(zonefault)
            lastup = True
        else:
            up.set(0)
            if lastup:
                tcsperm.remove(client.system_id)
                tcsfault.remove(client.system_id)
                tcsmode.remove(client.system_id)
            lastup = False

        for i in oldids:
            if i not in newids:
                eht.remove(*labels[i] + ["measured"])
                eht.remove(*labels[i] + ["setpoint"])
                eht.remove(*labels[i] + ["planned"])
                zavail.remove(*labels[i])
                zmode.remove(*labels[i])
                zfault.remove(*labels[i])
        oldids = newids

        time.sleep(poll_interval)
