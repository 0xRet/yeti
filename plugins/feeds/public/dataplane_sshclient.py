"""
    Feed of ssh client bruteforce of Dataplane with IPs and ASNs 
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
from core.schemas import observable
from core.schemas import task
from core import taskmanager


class DataplaneSSHClient(task.FeedTask):
    """
    Feed of ssh client bruteforce of Dataplane with IPs and ASNs.
    """

    SOURCE = "https://dataplane.org/sshclient.txt"
    _defaults = {
        "frequency": timedelta(hours=12),
        "name": "DataplaneSSHClient",
        "description": "Feed of ssh client bruteforce of Dataplane with IPs and ASNs",
    }
    _NAMES = ["ASN", "ASname", "ipaddr", "lastseen", "category"]
    def run(self):
        response = self._make_request(self.SOURCE,sort=False)
        if response:
            lines = response.content.decode("utf-8").split("\n")[64:-5]
            df = pd.DataFrame([l.split("|") for l in lines], columns=self._NAMES)

            for c in self._NAMES:
                df[c] = df[c].str.strip()
            
            df["lastseen"] = pd.to_datetime(df["lastseen"])
            df.fillna("", inplace=True)
            df = self._filter_observables_by_time(df, "lastseen")

            for _, row in df.iterrows():
                self.analyze(row)

    def analyze(self, item):
        context_ip = {
            "source": self.name,
            "last_seen": item["lastseen"],
        }

        ip = observable.Observable.find(value=item["ipaddr"])
        if not ip:
            ip = observable.Observable(value=item["ipaddr"], type="ip").save()
        category = item["category"].lower()
        tags = ["dataplane", "bruteforce", "ssh", "scanning"]
        if category:
            tags.append(category)
        ip.add_context(self.name, context_ip)
        ip.tag(tags)

        asn_obs = observable.Observable.find(value=item["ASN"])
        if not asn_obs:
            asn_obs = observable.Observable(value=item["ASN"], type="asn").save()

        context_asn = {
            "source": self.name,
            "last_seen": item["lastseen"],
        }
        asn_obs.add_context(self.name, context_asn)
        asn_obs.tag(tags)
        asn_obs.link_to(ip, "ASN to IP", self.name)

taskmanager.TaskManager.register_task(DataplaneSSHClient)
