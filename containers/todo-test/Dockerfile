FROM python:3.11-slim

COPY requirements.lock /opt/todo-requirements.lock
RUN python -m pip install --disable-pip-version-check --no-cache-dir \
    -r /opt/todo-requirements.lock

WORKDIR /workspace
USER 65534:65534
