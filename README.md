# This is evohome-exporter

A Honeywell Evohome data exporter for prometheus in Docker

Uses the python evohomeclient from:
https://pypi.org/project/evohomeclient/
https://github.com/watchforstock/evohome-client

## Prerequisites

Store your credentials in a file:

```shell
echo <<EOF > .env
EVOHOME_USERNAME=johndoe@people.org
EVOHOME_PASSWORD=My-v3ry-secret-p4$sWord
EOF
```

There are additional settings for the poll interval in seconds and the scrape port.
Specifying this is optional; the default values are 150 seconds and 8082 respectively:

Note: temperatures generally do not evolve quick so setting this value anything less than 150 has na added value.
Session timeout is 900 seconds so you might want to use value smaller than that.

```shell
echo <<EOF >> .env
EVOHOME_POLL_INTERVAL=300
EVOHOME_SCRAPE_PORT=8082
EOF
```

## Build & run in Docker

```shell
docker build . -t <image-name>
```
Adjust the image name (currently ``locahost:32000/evohome-exporter:registry``) in the deployment file .

```shell
docker run --rm -it --name evohome-exporter -p 8082:8082 <image-name>
```

## Run in Kubernetes

- store the image in a repository and adjust the image name in the deployment file ``k8s-evohome-exporter-deployment.yaml``.
- store the credentials in the secret file ``k8s-evohome-exporter-secret.yaml``. The secrets are base64 encoded.
  Create them with ``echo -n secret-word | base64``.
- apply in this order:
  * namespace
  * secret
  * service
  * deployment
  * monitor

The configuration is set to be scraped by the Prometheus Operator configuration.

## Example output

> $ curl -s http://localhost:8082
> &#35; HELP python_gc_objects_collected_total Objects collected during gc
> &#35; TYPE python_gc_objects_collected_total counter
> python_gc_objects_collected_total{generation="0"} 425.0
> python_gc_objects_collected_total{generation="1"} 286.0
> python_gc_objects_collected_total{generation="2"} 0.0
> &#35; HELP python_gc_objects_uncollectable_total Uncollectable object found during GC
> &#35; TYPE python_gc_objects_uncollectable_total counter
> python_gc_objects_uncollectable_total{generation="0"} 0.0
> python_gc_objects_uncollectable_total{generation="1"} 0.0
> python_gc_objects_uncollectable_total{generation="2"} 0.0
> &#35; HELP python_gc_collections_total Number of times this generation was collected
> &#35; TYPE python_gc_collections_total counter
> python_gc_collections_total{generation="0"} 53.0
> python_gc_collections_total{generation="1"} 4.0
> python_gc_collections_total{generation="2"} 0.0
> &#35; HELP python_info Python platform information
> &#35; TYPE python_info gauge
> python_info{implementation="CPython",major="3",minor="7",patchlevel="3",version="3.7.3"} 1.0
> &#35; HELP process_virtual_memory_bytes Virtual memory size in bytes.
> &#35; TYPE process_virtual_memory_bytes gauge
> process_virtual_memory_bytes 1.871872e+08
> &#35; HELP process_resident_memory_bytes Resident memory size in bytes.
> &#35; TYPE process_resident_memory_bytes gauge
> process_resident_memory_bytes 2.3478272e+07
> &#35; HELP process_start_time_seconds Start time of the process since unix epoch in seconds.
> &#35; TYPE process_start_time_seconds gauge
> process_start_time_seconds 1.60567689293e+09
> &#35; HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.
> &#35; TYPE process_cpu_seconds_total counter
> process_cpu_seconds_total 0.43000000000000005
> &#35; HELP process_open_fds Number of open file descriptors.
> &#35; TYPE process_open_fds gauge
> process_open_fds 6.0
> &#35; HELP process_max_fds Maximum number of open file descriptors.
> &#35; TYPE process_max_fds gauge
> process_max_fds 1024.0
> &#35; HELP evohome_temperature_celcius Evohome temperatuur in celsius
> &#35; TYPE evohome_temperature_celcius gauge
> evohome_temperature_celcius{id="1234501",name="Livingroom",thermostat="EMEA_ZONE",type="measured"} 15.5
> evohome_temperature_celcius{id="1234501",name="Livingroom",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> evohome_temperature_celcius{id="1234502",name="Kitchen",thermostat="EMEA_ZONE",type="measured"} 15.5
> evohome_temperature_celcius{id="1234502",name="Kitchen",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> evohome_temperature_celcius{id="1234503",name="Hall",thermostat="EMEA_ZONE",type="measured"} 15.5
> evohome_temperature_celcius{id="1234503",name="Hall",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> evohome_temperature_celcius{id="1244504",name="Bathroom",thermostat="EMEA_ZONE",type="measured"} 18.5
> evohome_temperature_celcius{id="1234504",name="Bathroom",thermostat="EMEA_ZONE",type="setpoint"} 20.0
> evohome_temperature_celcius{id="1234505",name="Garage",thermostat="EMEA_ZONE",type="measured"} 15.0
> evohome_temperature_celcius{id="1234505",name="Garage",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> evohome_temperature_celcius{id="1234506",name="Study",thermostat="EMEA_ZONE",type="measured"} 20.0
> evohome_temperature_celcius{id="1234506",name="Study",thermostat="EMEA_ZONE",type="setpoint"} 19.5
> evohome_temperature_celcius{id="1234507",name="Bedroom1",thermostat="EMEA_ZONE",type="measured"} 15.5
> evohome_temperature_celcius{id="1234507",name="Bedroom1",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> evohome_temperature_celcius{id="1234508",name="Bedroom2",thermostat="EMEA_ZONE",type="measured"} 15.0
> evohome_temperature_celcius{id="1234508",name="Bedroom2",thermostat="EMEA_ZONE",type="setpoint"} 15.0
> &#35; HELP evohome_updated Evohome client last updated
> &#35; TYPE evohome_updated gauge
> evohome_updated 1.6056773322508168e+09
> &#35; HELP evohome_up Evohome client status
> &#35; TYPE evohome_up gauge
> evohome_up 1.0
