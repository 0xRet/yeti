#!/bin/bash
set -euo pipefail

if [ ! -f yeti.conf ]; then
    echo "No yeti.conf file found. Copying sample config file."
    cp yeti.conf.sample yeti.conf
    sed -i '35s/# host = 127.0.0.1/host = mongodb/' yeti.conf
    sed -i '49s/# host = 127.0.0.1/host = redis/' yeti.conf
fi

if [ "$1" = 'webserver' ]; then
    poetry poetry run uvicorn core.web.webapp:app --reload --host 0.0.0.0
elif  [ "$1" = 'analytics' ]; then
    poetry run celery -A core.config.celeryctl.celery_app worker -Ofair --autoscale=10,2 --purge -Q analytics -n analytics
elif  [ "$1" = 'beat' ]; then
    poetry run celery -A core.config.celeryctl beat -S core.scheduling.Scheduler
elif  [ "$1" = 'exports' ]; then
    poetry run celery -A core.config.celeryctl.celery_app worker -Ofair --autoscale=10,2 -Q exports -n exports --purge
elif  [ "$1" = 'feeds' ]; then
    poetry run celery -A core.config.celeryctl.celery_app worker -Ofair --autoscale=10,2 -Q feeds -n feeds --purge
elif  [ "$1" = 'oneshot' ]; then
    poetry run celery -A core.config.celeryctl.celery_app worker --autoscale=4,2 -Q oneshot -n oneshot --purge
elif  [ "$1" = 'envshell' ]; then
    poetry shell
fi

exec "$@"
