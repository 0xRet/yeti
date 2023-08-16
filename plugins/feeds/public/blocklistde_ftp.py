import logging
from datetime import timedelta, datetime
from core.schemas import observable
from core.schemas import task
from core import taskmanager


class BlocklistdeFTP(task.FeedTask):
    URL_FEED = "https://lists.blocklist.de/lists/ftp.txt"
    default_values = {
        "frequency": timedelta(hours=1),
        "name": "BlocklistdeFTP",
        "description": "All IP addresses which have been reported within the last 48 hours for attacks on the Service FTP.",
    }

    def run(self):
        response = self._make_request(self.URL_FEED, verify=True)
        if response:
            data = response.text
            for item in data.split("\n"):
                self.analyze(item)

    def analyze(self, item):
        ip = item.strip()

        context = {"source": self.name, "date_added": datetime.utcnow()}

        obs = observable.Observable.find(value=ip)
        if not obs:
            obs = observable.Observable(value=ip, type="ip").save()
        obs.add_context(self.name, context)
        obs.tag(["blocklist", "ftp"])


taskmanager.TaskManager.register_task(BlocklistdeFTP)
