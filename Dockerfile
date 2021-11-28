# Each instruction in this file generatalpnes a new layer that gets pushed to your local image cache

FROM python:3.9-slim-buster

#
# Identify the maintainer of an image
LABEL maintainer="jonhall@us.ibm.com"

#
# Install NGINX to test.
COPY . /app
WORKDIR /app
RUN apt-get update
RUN pip install -r requirements.txt --user
CMD python invoiceAnalysis.py