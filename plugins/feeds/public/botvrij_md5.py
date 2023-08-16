import logging
from datetime import timedelta, datetime
from core.schemas import observable
from core.schemas import task
from core import taskmanager


class BotvrijMD5(task.FeedTask):
    URL_FEED = "https://www.botvrij.eu/data/ioclist.md5"
    _defaults = {
        "frequency": timedelta(hours=12),
        "name": "BotvrijMD5",
        "description": "Botvrij.eu is a project of the Dutch National Cyber Security Centre (NCSC-NL) and SIDN Labs, the R&D team of SIDN, the registry for the .nl domain.",
    }

    def run(self):
        response = self._make_request(self.URL_FEED, verify=True)
        if response:
            data = response.text
            for item in data.split("\n")[6:-1]:
                self.analyze(item.strip())

    def analyze(self, item):
        val, descr = item.split(" # md5 - ")

        context = {
            "source": self.name,
            "description": descr,
            "date_added": datetime.utcnow(),
        }

        obs = observable.Observable.find(value=val)
        if not obs:
            obs = observable.Observable(value=val, type="md5").save()
        obs.add_context(self.name, context)
        obs.tag(["botvrij"])

taskmanager.TaskManager.register_task(BotvrijMD5)
