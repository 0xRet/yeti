from datetime import datetime
import logging

from core.config.celeryctl import celery_app
from core.observables import Observable
from core.config.celeryimports import loaded_modules
from core.analytics import ScheduledAnalytics, AnalyticsResults

from mongoengine import DoesNotExist


@celery_app.task
def each(module_name, observable_json):
    o = Observable.from_json(observable_json)
    logging.warning("Launching {} on {}".format(module_name, o))
    mod = loaded_modules[module_name]
    mod.each(o)
    o.analysis_done(module_name)


@celery_app.task
def schedule(id):

    try:
        a = ScheduledAnalytics.objects.get(id=id, lock=None)  # check if we have implemented locking mechanisms
    except DoesNotExist:
        try:
            ScheduledAnalytics.objects.get(id=id, lock=False).modify(lock=True)  # get object and change lock
            a = ScheduledAnalytics.objects.get(id=id)
        except DoesNotExist:
            # no unlocked ScheduledAnalytics was found, notify and return...
            logging.info("Task {} is already running...".format(ScheduledAnalytics.objects.get(id=id).name))
            return

    if a.enabled:  # check if Analytics is enabled
        logging.warning("Running analytics {}".format(a.name))
        a.update_status("Running...")
        a.analyze_outdated()
        a.last_run = datetime.now()
    else:
        logging.error("Analytics {} is disabled".format(a.name))

    if a.lock:  # release lock if it was set
        a.lock = False

    a.save()
    a.update_status("OK")


@celery_app.task
def single(results_id):
    results = AnalyticsResults.objects.get(id=results_id)
    analytics = loaded_modules[results.analytics]
    logging.warning("Running one-shot query {} on {}".format(analytics.name, results.observable))
    results.update(status="running")
    links = analytics.analyze(results.observable)
    results.update(status="finished", results=links)
