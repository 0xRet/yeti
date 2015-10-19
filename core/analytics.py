from datetime import datetime

from core.config.celeryctl import celery_app
from core.scheduling import ScheduleEntry, OneShotEntry
from core.datatypes import Element
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
        fltr &= Q(**self.CUSTOM_FILTER) & Q(_cls="Element.{}".format(self.ACTS_ON))
        self.bulk(Element.objects(fltr))

    @classmethod
    def bulk(cls, elts):
        """Bulk analytics. May be overridden in case the module needs to batch-analyze elements"""
        for e in elts:
            celery_app.send_task("core.analytics_tasks.each", [cls.__name__, e.to_json()])

    @classmethod
    def each(cls, element):
        raise NotImplementedError("This method must be overridden in each class it inherits from")


class OneShotAnalytics(OneShotEntry):

    @classmethod
    def run(cls, e):
        celery_app.send_task("core.analytics_tasks.single", [cls.__name__, e.to_json()])
