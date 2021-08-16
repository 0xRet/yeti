import logging
import pandas as pd
from datetime import timedelta
from core.errors import ObservableValidationError
from core.feed import Feed
from core.observables import Ip, AutonomousSystem


class DataplaneSIPInvite(Feed):

    default_values = {
        "frequency": timedelta(hours=2),
        "name": "DataplaneSIPInvite",
        "source": "https://dataplane.org/sipinvitation.txt",
        "description": "Entries below are records of source IP addresses that have been identified as sending SIP INVITE operations.",
    }

    def update(self):
        resp = self._make_request(sort=False)
        lines = resp.content.decode("utf-8").split("\n")[64:-5]
        columns = ["ASN", "ASname", "ipaddr", "lastseen", "category"]
        df = pd.DataFrame([l.split("|") for l in lines], columns=columns)

        for c in columns:
            df[c] = df[c].str.strip()
        df = df.dropna()
        df["lastseen"] = pd.to_datetime(df["lastseen"])
        if self.last_run:
            df = df[df["lastseen"] > self.last_run]
        for count, row in df.iterrows():
            self.analyze(row)

    def analyze(self, row):

        context_ip = {"source": self.name, "lastseen": row["lastseen"]}

        try:
            ip = Ip.get_or_create(value=row["ipaddr"])
            ip.add_context(context_ip)
            ip.add_source(self.name)
            ip.tag("dataplane")
            ip.tag("sip")
            ip.tag(row["category"])

            asn = AutonomousSystem.get_or_create(value=row["ASN"])
            context_ans = {"source": self.name, "name": row["ASname"]}
            asn.add_context(context_ans)
            asn.add_source(self.name)
            asn.tag("dataplane")
            asn.active_link_to(ip, "AS", self.name)
        except ObservableValidationError as e:
            raise logging.error(e)
