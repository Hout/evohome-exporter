import datetime as dt
import logging
from random import gauss
import sys
import time
from typing import Optional

import prometheus_client as prom
from evohomeclient2 import EvohomeClient

from evohome_zookeeper import EvohomeZookeeper
from evohome_settings import EvohomeSettings
from evohome_types import Schedules


logging.root.setLevel(logging.INFO)
logging.root.handlers[0].setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
)


def get_set_point(
    zone_schedule, day_of_week: int, spot_time: dt.time
) -> Optional[float]:
    # from list to dictionary { day of week: list of switchpoints}
    daily_schedules = {
        s["DayOfWeek"]: s["Switchpoints"] for s in zone_schedule["DailySchedules"]
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


def calculate_planned_temperature(zone_schedule) -> float:
    current_time = dt.datetime.now().time()
    day_of_week = dt.datetime.today().weekday()
    setpoint = get_set_point(zone_schedule, day_of_week, current_time)
    if setpoint:
        return setpoint

    # get last setpoint from yesterday
    yesterday = dt.datetime.today() - dt.timedelta(days=-1)
    yesterday_weekday = yesterday.weekday()
    setpoint = get_set_point(zone_schedule, yesterday_weekday, dt.time.max)
    assert setpoint
    return setpoint


def get_schedules(client, zk: EvohomeZookeeper) -> Schedules:
    schedules: Schedules = {}

    for zone in client._get_single_heating_system()._zones:
        zone_id = zone.zoneId
        try:
            schedule = zk.get_schedule(zone_id)
            if not schedule:
                schedule = zone.schedule()
                zk.set_schedule(zone_id, schedule)
        except Exception as e:
            logging.warn(f"Exception on getting schedule from ZK: {e}")
            schedule = zone.schedule()
            zk.set_schedule(zone_id, schedule)
        schedules[zone_id] = schedule

    return schedules


def initialise_settings() -> EvohomeSettings:
    logging.info("Evohome exporter for Prometheus")
    settings = EvohomeSettings()
    return settings


def initialise_evohome(settings: EvohomeSettings, zk: EvohomeZookeeper):
    client = None
    while True:
        try:
            with zk.lock_token():
                try:
                    token = zk.get_token()
                    access_token = token["access_token"]
                    access_token_expires = dt.datetime.fromtimestamp(
                        token["access_token_expires_unixtime"]
                    )
                    refresh_token = token["refresh_token"]
                except Exception as e:
                    logging.warn(f"Exception on loading access tokens from ZK: {e}")
                    access_token = None
                    access_token_expires = None
                    refresh_token = None

                client = EvohomeClient(
                    settings.username,
                    settings.password,
                    refresh_token=refresh_token,
                    access_token=access_token,
                    access_token_expires=access_token_expires,
                )

                token = {
                    "access_token": client.access_token,
                    "access_token_expires_unixtime": client.access_token_expires.timestamp(),
                    "refresh_token": client.refresh_token,
                }
                zk.set_token(token)

            return client
        except Exception as e:
            if len(e.args) > 0 and "attempt_limit_exceeded" in e.args[0]:
                logging.warning(f": {e}")
                time.sleep(gauss(30, 3))
                continue

            logging.critical(f"Can't create Evohome client: {e}")
            sys.exit(99)


def initialise_zookeeper(settings: EvohomeSettings):
    return EvohomeZookeeper(hosts=settings.zk_service)


def cleanup_zookeeper(zk: EvohomeZookeeper, client):
    zk.cleanup_schedule_zones(
        [
            client_zone.zoneId
            for client_zone in client._get_single_heating_system()._zones
        ]
    )


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

    prom.start_http_server(settings.scrape_port)

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
    logging.debug(f"System location: {tcs.location.city}, {tcs.location.country}")
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
    metric.labels(zone_id=zone.zoneId, zone_name=zone.name, type=setpoint_type).set(
        temperature
    )
    logging.debug(f"Zone {zone.name} {setpoint_type} temperature: {temperature}")


def set_prom_metrics_zone_target_temperature(metrics, data, zone):
    zone_target_temperature = zone.setpointStatus["targetHeatTemperature"]
    set_metric(metrics["temperature_celcius"], zone, zone_target_temperature, "target")


def set_prom_metrics_zone_planned_temperature(metrics, data, zone):
    schedule = data["schedules"][zone.zoneId]
    zone_planned_temperature = calculate_planned_temperature(schedule)
    set_metric(
        metrics["temperature_celcius"], zone, zone_planned_temperature, "planned"
    )


def set_prom_metrics_zone_setpoint_mode(metrics, zone):
    zone_setpoint_mode = zone.setpointStatus["setpointMode"]
    metrics["zone_mode"].labels(zone_id=zone.zoneId, zone_name=zone.name).state(
        zone_setpoint_mode
    )
    logging.debug(f"Zone {zone.name} setpoint mode: {zone_setpoint_mode}")


def set_prom_metrics_zone_measured_temperature(metrics, zone):
    zone_measured_temperature = zone.temperatureStatus["temperature"]
    set_metric(
        metrics["temperature_celcius"], zone, zone_measured_temperature, "measured"
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


def main():
    settings = initialise_settings()
    zk = initialise_zookeeper(settings)
    client = initialise_evohome(settings, zk)
    metrics = initialise_metrics(settings)

    cleanup_zookeeper(zk, client)

    # write readiness file
    open("/tmp/ready", "x").close()

    while True:
        # wait until its our time
        current_timestamp = int(time.time())
        logging.debug(
            f"Current time {time.strftime('%H:%M:%S', time.localtime(current_timestamp))}"
        )
        party_size, party_position = zk.party_data()
        logging.debug(f"Party size {party_size}")
        logging.debug(f"Party position {party_position}")
        cycle_duration = settings.poll_interval * party_size
        logging.debug(f"Cycle duration {cycle_duration}")
        my_offset = party_position * settings.poll_interval
        logging.debug(f"My offset {my_offset}")
        current_cycle_offset = current_timestamp % cycle_duration
        logging.debug(f"Current cycle offset {current_cycle_offset}")
        current_cycle_start = current_timestamp - current_cycle_offset
        logging.debug(f"Current cycle start {current_cycle_start}")
        current_poll_timestamp = current_cycle_start + my_offset
        logging.debug(f"Current poll timestamp {current_poll_timestamp}")
        next_poll_timestamp = (
            current_poll_timestamp
            if current_poll_timestamp > current_timestamp
            else current_poll_timestamp + cycle_duration
        )
        logging.debug(f"Next poll timestamp {next_poll_timestamp}")
        wait_time_seconds = next_poll_timestamp - current_timestamp
        logging.debug(f"Wait time {wait_time_seconds}")

        logging.info(
            f"Sleeping until {time.strftime('%H:%M:%S', time.localtime(next_poll_timestamp))}"
        )
        time.sleep(wait_time_seconds)

        try:
            logging.info("Woken up; getting data from evohome & set metrics")
            data = get_evohome_data(client, zk)
            set_prom_metrics(metrics, data)
        except Exception as e:
            logging.error(f"Error in evohome main loop: {e}")


if __name__ == "__main__":
    main()
