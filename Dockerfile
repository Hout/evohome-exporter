# set base image (host OS)
FROM python AS build-image

# copy the requirements file & install
COPY requirements.txt requirements.txt
RUN pip install --user -r requirements.txt

# set base image (host OS)
FROM python:slim AS run-image

# set the run user & set working dir to its home dir
RUN useradd --create-home pythonuser
USER pythonuser
WORKDIR /home/pythonuser

# copy the python environment from the build image and set the path
COPY --from=build-image /root/.local /home/pythonuser/.local
ENV PATH=/home/pythonuser/.local:$PATH

# copy the content of the local src directory to the working directory
COPY src/*.py ./

# Expose the port for Prometheus to scrape from
RUN export EVOHOME_SCRAPE_PORT=8082
EXPOSE 8082

# command to run on container start
ENTRYPOINT [ "python", "-u", "evohome_exporter.py"]
CMD ["--bind", "0.0.0.0"]
