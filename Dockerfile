# set base image (host OS)
FROM python:3-slim

# install git
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

# set the run user & set working dir to its home dir
RUN useradd --create-home pythonuser
USER pythonuser
WORKDIR /home/pythonuser

# copy the requirements file, install it & clean up
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

# copy the content of the local src directory to the working directory
COPY src/evohome-exporter.py ./

# Expose the port for Prometheus to scrape from
RUN export EVOHOME_SCRAPE_PORT=8082
EXPOSE 8082

# command to run on container start
ENTRYPOINT [ "python", "-u", "evohome-exporter.py"]
CMD ["--bind", "0.0.0.0"]
