import datetime as dt
import logging
import sys
import time
from os import environ

import prometheus_client as prom
from evohomeclient2 import EvohomeClient

logging.root.setLevel(logging.DEBUG)
logging.root.handlers[0].setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
)

username_env_var = "EVOHOME_USERNAME"
password_env_var = "EVOHOME_PASSWORD"
poll_interval_env_var = "EVOHOME_POLL_INTERVAL"
scrape_port_env_var = "EVOHOME_SCRAPE_PORT"


def get_set_point(zone_schedule, day_of_week, spot_time):
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
    setpoint = get_set_point(zone_schedule, day_of_week, current_time)
    if setpoint is not None:
        return setpoint
    yesterday = dt.datetime.today() - dt.timedelta(days=-1)
    yesterday_weekday = yesterday.weekday()
    return get_set_point(zone_schedule, yesterday_weekday, dt.time.max)


schedules_updated = dt.datetime.min
schedules = {}


def get_schedules(client):
    global schedules_updated
    global schedules

    # this takes time, update once per hour
    if schedules_updated < dt.datetime.now() - dt.timedelta(hours=1):
        schedules = {
            zone.zoneId: zone.schedule()
            for zone in client._get_single_heating_system()._zones
        }
        schedules_updated = dt.datetime.now()
    return schedules


def initialise_settings():
    logging.info("Evohome exporter for Prometheus")
    settings = {}
    try:
        settings["username"] = environ[username_env_var].strip()
        settings["password"] = environ[password_env_var].strip()
    except KeyError:
        logging.error("Missing environment variables for Evohome credentials:")
        logging.error(f"\t{username_env_var} - Evohome username")
        logging.error(f"\t{password_env_var} - Evohome password")
        exit(1)

    settings["poll_interval"] = int(environ.get(poll_interval_env_var, 60))
    settings["scrape_port"] = int(environ.get(scrape_port_env_var, 8082))

    logging.info("Evohome exporter settings:")
    logging.info(f"Username: {settings['username']}")
    logging.info(f"Poll interval: {settings['poll_interval']} seconds")
    logging.info(f"Scrape port: {settings['scrape_port']}")

    return settings


def initialise_evohome(settings):
    while True:
        try:
            return EvohomeClient(settings["username"], settings["password"])
        except Exception as e:
            if len(e.args) > 0 and "attempt_limit_exceeded" in e.args[0]:
                logging.warning(f": {e}")
                time.sleep(30)
                continue

            logging.critical(f"Can't create Evohome client: {e}")
            sys.exit(99)


def initialise_metrics(settings):
    metrics_list = [
        prom.Gauge(name="evohome_up", documentation="Evohome status"),
        prom.Gauge(
            name="evohome_tcs_active_faults", documentation="Evohome active faults"
        ),
        prom.Gauge(
            name="evohome_tcs_permanent", documentation="Evohome permanent state"
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
            states=["FollowSchedule", "TemporaryOverride", "PermanentOverride"],
            labelnames=["zone_id", "zone_name"],
        ),
        prom.Gauge(
            name="evohome_temperature",
            documentation="Evohome temperature",
            unit="celcius",
            labelnames=["zone_id", "zone_name", "type"],
        ),
        prom.Gauge(name="evohome_last_update", documentation="Evohome last update"),
    ]

    prom.start_http_server(settings["scrape_port"])

    return {m._name.removeprefix("evohome_"): m for m in metrics_list}


# Create a metric to track time spent and requests made.
REQUEST_TIME = prom.Summary(
    "evohome_request_processing", "Time spent processing request"
)


# Decorate function with metric.
@REQUEST_TIME.time()
def get_evohome_data(client):
    tcs = client._get_single_heating_system()
    tcs.location.status()
    data = {"tcs": tcs, "schedules": get_schedules(client)}
    logging.debug("Retrieved data:")
    logging.debug(f"System location: {tcs.location.city}, {tcs.location.country}")
    logging.debug(f"System time zone: {tcs.location.timeZone['displayName']}")
    logging.debug(f"System model type: {tcs.modelType}")
    return data


def clear_metric(metric, label_values):
    if label_values in metric._metrics:
        metric.remove(label_values)


def set_prom_metrics(metrics, data):
    metrics["up"].set(1)

    system_mode_status = data["tcs"].systemModeStatus
    system_mode_permanent_flag = system_mode_status.get("isPermanent", False)
    metrics["tcs_permanent"].set(float(system_mode_permanent_flag))
    logging.debug(f"System mode permanent: {system_mode_permanent_flag}")

    system_mode = system_mode_status.get("mode", "Auto")
    metrics["tcs_mode"].state(system_mode)
    logging.debug(f"System mode: {system_mode}")

    active_faults = data["tcs"].activeFaults
    metrics["tcs_active_faults"].set(float(active_faults is not None))
    for active_fault in active_faults:
        logging.warning(f"Active fault: {active_fault}")

    for zone in data["tcs"].zones.values():

        zone_temperature_up = zone.temperatureStatus.get("isAvailable", False)
        metrics["zone_up"].labels(zone_id=zone.zoneId, zone_name=zone.name).set(
            float(zone_temperature_up)
        )
        logging.debug(f"Zone {zone.name} temperature up: {zone_temperature_up}")

        if zone_temperature_up:
            zone_measured_temperature = zone.temperatureStatus["temperature"]
            metrics["temperature_celcius"].labels(
                zone_id=zone.zoneId, zone_name=zone.name, type="measured"
            ).set(zone_measured_temperature)
            logging.debug(
                f"Zone {zone.name} measured temperature: {zone_measured_temperature}"
            )

            zone_target_temperature = zone.setpointStatus["targetHeatTemperature"]
            metrics["temperature_celcius"].labels(
                zone_id=zone.zoneId, zone_name=zone.name, type="setpoint"
            ).set(zone_target_temperature)
            logging.debug(
                f"Zone {zone.name} target temperature: {zone_target_temperature}"
            )

            zone_setpoint_mode = zone.setpointStatus["setpointMode"]
            metrics["zone_mode"].labels(zone_id=zone.zoneId, zone_name=zone.name).state(
                zone_setpoint_mode
            )
            logging.debug(f"Zone {zone.name} setpoint mode: {zone_setpoint_mode}")
            if zone_setpoint_mode == "FollowSchedule":
                schedule = data["schedules"][zone.zoneId]
                zone_planned_temperature = calculate_planned_temperature(schedule)
                metrics["temperature_celcius"].labels(
                    zone_id=zone.zoneId, zone_name=zone.name, type="planned"
                ).set(zone_planned_temperature)
                logging.debug(
                    f"Zone {zone.name} planned temperature: {zone_planned_temperature}"
                )
            else:
                clear_metric(
                    metrics["temperature_celcius"], (zone.zoneId, zone.name, "planned")
                )

        else:
            for type in ["measured", "setpoint", "planned"]:
                clear_metric(
                    metrics["temperature_celcius"], (zone.zoneId, zone.name, type)
                )
            clear_metric(metrics["zone_mode"], (zone.zoneId, zone.name))

    metrics["last_update"].set_to_current_time()
    logging.debug(f"System last update set to {time.time()}")


def clear_prom_metrics(metrics):
    for k, m in metrics.items():
        if k == "up":
            m.set(0)
            continue
        for label_values in m._metrics:
            m.remove(label_values)


def main():
    settings = initialise_settings()
    client = initialise_evohome(settings)
    metrics = initialise_metrics(settings)

    while True:
        data = {}
        try:
            data = get_evohome_data(client)
        except Exception as e:
            logging.warning(f"Error while retrieving evohome data: {e}")
            if data is None or len(data) == 0 or data.get("tcs", None) is None:
                clear_prom_metrics(metrics)
        else:
            try:
                set_prom_metrics(metrics, data)
            except Exception as e:
                logging.warning(f"Error while setting prometheus metrics: {e}")

        time.sleep(settings["poll_interval"])


if __name__ == "__main__":
    main()
