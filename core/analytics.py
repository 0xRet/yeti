from datetime import datetime

from core.config.celeryctl import celery_app
from core.scheduling import ScheduleEntry, OneShotEntry
from core.observables import Observable
from mongoengine import *


class ScheduledAnalytics(ScheduleEntry):
    """Base class for analytics. All analytics must inherit from this"""

    SCHEDULED_TASK = 'core.analytics_tasks.schedule'
    CUSTOM_FILTER = {}

    def analyze_outdated(self):
        # do outdated logic
        fltr = Q(**{"last_analyses__{}__exists".format(self.name): False})
        if self.EXPIRATION:
            fltr |= Q(**{"last_analyses__{}__lte".format(self.name): datetime.now() - self.EXPIRATION})
        fltr &= Q(**self.CUSTOM_FILTER) & Q(_cls__contains=self.ACTS_ON)
        self.bulk(Observable.objects(fltr))

    @classmethod
    def bulk(cls, elts):
        """Bulk analytics. May be overridden in case the module needs to batch-analyze observables"""
        for e in elts:
            celery_app.send_task("core.analytics_tasks.each", [cls.__name__, e.to_json()])

    @classmethod
    def each(cls, observable):
        raise NotImplementedError("This method must be overridden in each class it inherits from")

    def info(self):
        i = {k: v for k, v in self._data.items() if k in ["name", "description", "last_run", "enabled", "status"]}
        i['frequency'] = str(self.frequency)
        i['expiration'] = str(self.EXPIRATION)
        i['acts_on'] = self.ACTS_ON
        return i


class OneShotAnalytics(OneShotEntry):

    @classmethod
    def run(cls, e):
        celery_app.send_task("core.analytics_tasks.single", [cls.__name__, e.to_json()])

    def info(self):
        i = {k: v for k, v in self._data.items() if k in ["name", "description", "enabled"]}
        i['acts_on'] = self.ACTS_ON
        return i
