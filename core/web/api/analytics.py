from flask_restful import reqparse

from core.observables import Observable
from core.web.api.crud import CrudApi
from core.analytics import ScheduledAnalytics, OneShotAnalytics, AnalyticsResults
from core.analytics_tasks import schedule
from core.web.api.api import render
from core.web.helpers import get_object_or_404, find_method


class ScheduledAnalyticsApi(CrudApi):
    template = 'scheduled_analytics_api.html'
    objectmanager = ScheduledAnalytics

    def post(self, name, action):
        method = find_method(self, action, 'action')

        return method(name)

    def refresh(self, name):
        schedule.delay(name)

        return render({"name": name})

    def toggle(self, name):
        a = ScheduledAnalytics.objects.get(name=name)
        a.enabled = not a.enabled
        a.save()

        return render({"name": name, "status": a.enabled})


class OneShotAnalyticsApi(CrudApi):
    template = "oneshot_analytics_api.html"
    objectmanager = OneShotAnalytics

    parser = reqparse.RequestParser()
    parser.add_argument('id', required=True, help="You must specify an ID.")

    def post(self, name, action):
        method = find_method(self, action, 'action')
        analytics = get_object_or_404(OneShotAnalytics, name=name)

        return method(analytics)

    def toggle(self, analytics):
        analytics.enabled = not analytics.enabled
        analytics.save()

        return render({"name": analytics.name, "status": analytics.enabled})

    def run(self, analytics):
        args = self.parser.parse_args()
        observable = get_object_or_404(Observable, id=args['id'])

        return render(analytics.run(observable).to_mongo())

    def status(self, analytics):
        args = self.parser.parse_args()
        results = AnalyticsResults.objects.get(id=args['id'])

        return render(results.to_mongo())
