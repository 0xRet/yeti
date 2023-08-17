import logging
from datetime import timedelta, datetime
from core.schemas import observable
from core.schemas import task
from core import taskmanager


class BlocklistdeMail(task.FeedTask):
    SOURCE = "https://lists.blocklist.de/lists/mail.txt"
    _defaults = {
        "frequency": timedelta(hours=1),
        "name": "BlocklistdeMail",
        "description": "All IP addresses which have been reported within the last 48 hours for attacks on the Service Mail.",
    }

    def run(self):
        response = self._make_request(self.SOURCE, verify=True)
        if response:
            data = response.text
            for item in data.split("\n"):
                self.analyze(item)

    def analyze(self, item):
        ip = item.strip()

        obs = observable.Observable.find(value=ip)
        if not obs:
            obs = observable.Observable(value=ip, type="ip").save()

        obs.tag(["blocklist", "mail"])


taskmanager.TaskManager.register_task(BlocklistdeMail)
