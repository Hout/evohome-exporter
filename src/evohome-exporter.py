import datetime as dt
import json
import logging
from random import gauss
import sys
import time
from os import environ

import prometheus_client as prom
from evohomeclient2 import EvohomeClient
from kazoo.client import KazooClient

logging.root.setLevel(logging.DEBUG)
logging.root.handlers[0].setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
)

USERNAME_ENV_VAR = "EVOHOME_USERNAME"
PASSWORD_ENV_VAR = "EVOHOME_PASSWORD"
POLL_INTERVAL_ENV_VAR = "EVOHOME_POLL_INTERVAL"
SCRAPE_PORT_ENV_VAR = "EVOHOME_SCRAPE_PORT"
ZK_SERVICE_ENV_VAR = "EVOHOME_ZK_SERVICE"

ZK_BASE_PATH = "/evohome"
ZK_ELECTION_NODE = "election"
ZK_TOKEN_NODE = "token"
ZK_LOCK_NODE = "lock"
ZK_SCHEDULES_PATH = f"{ZK_BASE_PATH}/schedules"

TIME_MAX = 9999999999.0

def get_set_point(zone_schedule, day_of_week, spot_time):
    daily_schedules = {
        s["DayOfWeek"]: s["Switchpoints"]
        for s in zone_schedule["DailySchedules"]
    }
    switch_points = {
        dt.time.fromisoformat(s["TimeOfDay"]): s["heatSetpoint"]
        for s in daily_schedules[day_of_week]
    }
    candidate_times = [k for k in switch_points.keys() if k <= spot_time]
    if len(candidate_times) == 0:
        # no time on or earlier than current time
        return None

    candidate_time = max(candidate_times)
    return switch_points[candidate_time]


def calculate_planned_temperature(zone_schedule):
    current_time = dt.datetime.now().time()
    day_of_week = dt.datetime.today().weekday()
    setpoint = get_set_point(zone_schedule, day_of_week, current_time)
    if setpoint is not None:
        return setpoint

    # get last setpoint from yesterday
    yesterday = dt.datetime.today() - dt.timedelta(days=-1)
    yesterday_weekday = yesterday.weekday()
    return get_set_point(zone_schedule, yesterday_weekday, dt.time.max)


def get_schedules(client, zk):
    schedules = {}

    for client_zone in client._get_single_heating_system()._zones:
        schedule_path = f"{ZK_SCHEDULES_PATH}/{client_zone.zoneId}"
        try:
            stored_schedule = json.loads(zk.get(schedule_path)[0].decode("utf-8"))
        except Exception as e:
            logging.warn(f"Exception on loading schedule data from ZK: {e}")

            stored_schedule = (None, 0)
            zk.ensure_path(schedule_path)

        if stored_schedule[1] <= time.time():
            stored_schedule = [client_zone.schedule(), time.time() + gauss(3600, 300)]
            zk.set(schedule_path, json.dumps(stored_schedule).encode("utf-8"))

        schedules[client_zone.zoneId] = stored_schedule[0]

    return schedules


def initialise_settings():
    logging.info("Evohome exporter for Prometheus")
    settings = {}
    try:
        settings["username"] = environ[USERNAME_ENV_VAR].strip()
        settings["password"] = environ[PASSWORD_ENV_VAR].strip()
    except KeyError:
        logging.error("Missing environment variables for Evohome credentials:")
        logging.error(f"\t{USERNAME_ENV_VAR} - Evohome username")
        logging.error(f"\t{PASSWORD_ENV_VAR} - Evohome password")
        exit(1)

    settings["poll_interval"] = int(environ.get(POLL_INTERVAL_ENV_VAR, 60))
    settings["scrape_port"] = int(environ.get(SCRAPE_PORT_ENV_VAR, 8082))
    settings["zk_service"] = environ.get(ZK_SERVICE_ENV_VAR, "zk-cs")

    logging.info("Evohome exporter settings:")
    logging.info(f"Username: {settings['username']}")
    logging.info(f"Poll interval: {settings['poll_interval']} seconds")
    logging.info(f"Scrape port: {settings['scrape_port']}")

    return settings


def initialise_evohome(settings, zk):
    client = None
    token_path = f'{ZK_BASE_PATH}/{ZK_TOKEN_NODE}'
    while True:
        try:
            with zk.Lock(ZK_BASE_PATH, ZK_LOCK_NODE):
                try:
                    token_data = json.loads(zk.get(token_path)[0].decode("utf-8"))
                    access_token = token_data["access_token"]
                    access_token_expires = dt.datetime.fromtimestamp(token_data["access_token_expires_unixtime"])
                    refresh_token = token_data["refresh_token"]
                except Exception as e:
                    logging.warn(f"Exception on loading access tokens from ZK: {e}")
                    access_token = None
                    access_token_expires = None
                    refresh_token = None

                client = EvohomeClient(
                    settings["username"],
                    settings["password"],
                    refresh_token=refresh_token,
                    access_token=access_token,
                    access_token_expires=access_token_expires,
                )

                token_data_json = json.dumps({
                    "access_token": client.access_token,
                    "access_token_expires_unixtime": client.access_token_expires.timestamp(),
                    "refresh_token": client.refresh_token
                }).encode("utf-8")
                zk.set(token_path, token_data_json)

            return client
        except Exception as e:
            if len(e.args) > 0 and "attempt_limit_exceeded" in e.args[0]:
                logging.warning(f": {e}")
                time.sleep(30)
                continue

            logging.critical(f"Can't create Evohome client: {e}")
            sys.exit(99)


def initialise_zookeeper(settings):
    zk = KazooClient(hosts=settings["zk_service"])
    zk.start()
    zk.ensure_path(ZK_BASE_PATH)
    zk.ensure_path(ZK_SCHEDULES_PATH)

    return zk


def cleanup_zookeeper(zk, client):
    stored_zone_ids = set(zk.get_children(ZK_SCHEDULES_PATH))
    client_zone_ids = {client_zone.zoneId for client_zone in client._get_single_heating_system()._zones}
    to_delete = stored_zone_ids - client_zone_ids
    for zone_id in to_delete:
        zk.delete(f"{ZK_SCHEDULES_PATH}/{zone_id}")


def initialise_metrics(settings):
    metrics_list = [
        prom.Gauge(name="evohome_up", documentation="Evohome status"),
        prom.Gauge(
            name="evohome_tcs_active_faults",
            documentation="Evohome active faults",
        ),
        prom.Gauge(
            name="evohome_tcs_permanent",
            documentation="Evohome permanent state",
        ),
        prom.Enum(
            name="evohome_tcs_mode",
            documentation="Evohome temperatureControlSystem mode",
            states=[
                "Auto",
                "AutoWithEco",
                "AutoWithReset",
                "Away",
                "DayOff",
                "HeatingOff",
                "Custom",
            ],
        ),
        prom.Gauge(
            name="evohome_zone_up",
            documentation="Evohome zone status",
            labelnames=["zone_id", "zone_name"],
        ),
        prom.Enum(
            name="evohome_zone_mode",
            documentation="Evohome zone mode",
            states=[
                "FollowSchedule",
                "TemporaryOverride",
                "PermanentOverride",
            ],
            labelnames=["zone_id", "zone_name"],
        ),
        prom.Gauge(
            name="evohome_temperature",
            documentation="Evohome temperature",
            unit="celcius",
            labelnames=["zone_id", "zone_name", "type"],
        ),
        prom.Gauge(
            name="evohome_last_update", documentation="Evohome last update"
        ),
    ]

    prom.start_http_server(settings["scrape_port"])

    return {m._name.removeprefix("evohome_"): m for m in metrics_list}


# Create a metric to track time spent and requests made.
REQUEST_TIME = prom.Summary(
    "evohome_request_processing", "Time spent processing request"
)


# Decorate function with metric.
@REQUEST_TIME.time()
def get_evohome_data(client, zk):
    tcs = client._get_single_heating_system()
    tcs.location.status()
    data = {"tcs": tcs, "schedules": get_schedules(client, zk)}
    logging.debug("Retrieved data:")
    logging.debug(
        f"System location: {tcs.location.city}, {tcs.location.country}"
    )
    logging.debug(f"System time zone: {tcs.location.timeZone['displayName']}")
    logging.debug(f"System model type: {tcs.modelType}")
    return data


def set_prom_metrics(metrics, data):
    metrics["up"].set(1)

    system_mode_status = set_prom_metrics_mode_status(metrics, data)
    set_prom_metrics_system_mode(metrics, system_mode_status)
    set_prom_metrics_active_faults(metrics, data)

    for zone in data["tcs"].zones.values():
        if not set_prom_metrics_zone_up(metrics, zone):
            continue
        set_prom_metrics_zone_setpoint_mode(metrics, zone)
        set_prom_metrics_zone_measured_temperature(metrics, zone)
        set_prom_metrics_zone_target_temperature(metrics, data, zone)
        set_prom_metrics_zone_planned_temperature(metrics, data, zone)
    set_prom_metrics_last_update(metrics)


def set_prom_metrics_last_update(metrics):
    metrics["last_update"].set_to_current_time()
    logging.debug(f"System last update set to {time.time()}")


def set_prom_metrics_zone_up(metrics, zone):
    zone_temperature_up = zone.temperatureStatus.get("isAvailable", False)
    metrics["zone_up"].labels(zone_id=zone.zoneId, zone_name=zone.name).set(
        float(zone_temperature_up)
    )
    logging.debug(f"Zone {zone.name} temperature up: {zone_temperature_up}")
    return zone_temperature_up


def set_metric(metric, zone, temperature, setpoint_type):
    metric.labels(
        zone_id=zone.zoneId, zone_name=zone.name, type=setpoint_type
    ).set(temperature)
    logging.debug(
        f"Zone {zone.name} {setpoint_type} temperature: {temperature}"
    )


def set_prom_metrics_zone_target_temperature(metrics, data, zone):
    zone_target_temperature = zone.setpointStatus["targetHeatTemperature"]
    set_metric(
        metrics["temperature_celcius"], zone, zone_target_temperature, "target"
    )


def set_prom_metrics_zone_planned_temperature(metrics, data, zone):
    schedule = data["schedules"][zone.zoneId]
    zone_planned_temperature = calculate_planned_temperature(schedule)
    set_metric(
        metrics["temperature_celcius"],
        zone,
        zone_planned_temperature,
        "planned",
    )


def set_prom_metrics_zone_setpoint_mode(metrics, zone):
    zone_setpoint_mode = zone.setpointStatus["setpointMode"]
    metrics["zone_mode"].labels(
        zone_id=zone.zoneId, zone_name=zone.name
    ).state(zone_setpoint_mode)
    logging.debug(f"Zone {zone.name} setpoint mode: {zone_setpoint_mode}")


def set_prom_metrics_zone_measured_temperature(metrics, zone):
    zone_measured_temperature = zone.temperatureStatus["temperature"]
    set_metric(
        metrics["temperature_celcius"],
        zone,
        zone_measured_temperature,
        "measured",
    )


def set_prom_metrics_active_faults(metrics, data):
    active_faults = data["tcs"].activeFaults
    metrics["tcs_active_faults"].set(float(active_faults is not None))
    for active_fault in active_faults:
        logging.warning(f"Active fault: {active_fault}")


def set_prom_metrics_system_mode(metrics, system_mode_status):
    system_mode = system_mode_status.get("mode", "Auto")
    metrics["tcs_mode"].state(system_mode)
    logging.debug(f"System mode: {system_mode}")


def set_prom_metrics_mode_status(metrics, data):
    system_mode_status = data["tcs"].systemModeStatus
    system_mode_permanent_flag = system_mode_status.get("isPermanent", False)
    metrics["tcs_permanent"].set(float(system_mode_permanent_flag))
    logging.debug(f"System mode permanent: {system_mode_permanent_flag}")
    return system_mode_status

def get_data_and_report_metrics(client, metrics, zk, settings):
    while True:
        try:
            data = get_evohome_data(client, zk)
            set_prom_metrics(metrics, data)
        except Exception as e:
            logging.error(f"Error in evohome main loop: {e}")

        time.sleep(settings["poll_interval"])

def main():
    settings = initialise_settings()
    zk = initialise_zookeeper(settings)
    client = initialise_evohome(settings, zk)
    metrics = initialise_metrics(settings)

    cleanup_zookeeper(zk, client)

    election = zk.Election(ZK_BASE_PATH, ZK_ELECTION_NODE)
    election.run(get_data_and_report_metrics, client, metrics, zk, settings)


if __name__ == "__main__":
    main()
