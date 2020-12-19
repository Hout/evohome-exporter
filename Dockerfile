# set base image (host OS)
FROM python:3-slim

# set the run user & set working dir to its home dir
RUN useradd --create-home pythonuser
USER pythonuser
WORKDIR /home/pythonuser/code

# copy the requirements file, install it & clean up
COPY requirements.txt .
RUN pip install  --no-cache-dir -r requirements.txt
RUN rm requirements.txt

# copy the content of the local src directory to the working directory
COPY src/evohome-exporter.py ./

# Expose the port for Prometheus to scrape from
EXPOSE 8082

# command to run on container start
CMD [ "python", "evohome-exporter.py", "--bind", "0.0.0.0"]