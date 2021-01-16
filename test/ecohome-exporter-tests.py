from evohome_exporter import get_set_point
import mocker

schedule = {}


def setup():
    switchPoints = [
        {"TimeOfDay": "8:00:00", "heatSetPoint": 18},
        {"TimeOfDay": "18:00:00", "heatSetPoint": 20},
        {"TimeOfDay": "23:00:00", "heatSetPoint": 15},
    ]
    daily_schedules = []
    for dayOfWeek in range(7):
        daySchedule = {"DayOfWeek": dayOfWeek, "SwitchPoints": switchPoints}
        daily_schedules.append(daySchedule)

    global schedule
    schedule = {"DailySchedules": daily_schedules}


def get_set_point_should_report_proper_setpoints():

    assert get_set_point() == 15
