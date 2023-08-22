"""
    Feed of Dataplane SSH bruteforce IPs and ASNs
"""
import logging
from datetime import datetime, timedelta

import pandas as pd
from core.schemas import observable
from core.schemas import task
from core import taskmanager


class DataplaneVNC(task.FeedTask):
    """
    Feed of VNC dataplane IPs.
    """

    SOURCE = "https://dataplane.org/vncrfb.txt"
    _NAMES = ["ASN", "ASname", "ipaddr", "lastseen", "category"]
    _defaults = {
        "frequency": timedelta(hours=12),
        "name": "DataplaneVNC",
        "description": "Feed of VNC dataplane IPs.",
    }

    def run(self):
        response = self._make_request(self.SOURCE, sort=False)
        if response:
            lines = response.content.decode("utf-8").split("\n")[68:-5]

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
        tags = ["dataplane", "vnc", "scanning"]
        if category:
            tags.append(category)
        ip.add_context(self.name, context_ip)
        ip.tag(tags)

        asn_obs = observable.Observable.find(value=item["ASN"])
        if not asn_obs:
            asn_obs = observable.Observable(value=item["ASN"], type="asn").save()

        context_asn = {
            "source": self.name,
        }
        asn_obs.add_context(self.name, context_asn)
        asn_obs.tag(tags)
        asn_obs.link_to(ip, "ASN_IP", self.name)


taskmanager.TaskManager.register_task(DataplaneVNC)
