import logging
from datetime import timedelta
from core.errors import ObservableValidationError
from core.feed import Feed
from core.observables import Ip


class BlocklistdeBots(Feed):

    default_values = {
        "frequency": timedelta(hours=1),
        "name": "BlocklistdeBots",
        "source": "https://lists.blocklist.de/lists/sip.txt",
        "description": "All IP addresses which have been reported within the last 48 hours as having run attacks attacks on the RFI-Attacks, REG-Bots, IRC-Bots or BadBots (BadBots = he has posted a Spam-Comment on a open Forum or Wiki).",
    }

    def update(self):
        for line in self.update_lines():
            self.analyze(line)

    def analyze(self, line):
        line = line.strip()

        ip = line

        context = {"source": self.name}

        try:
            obs = Ip.get_or_create(value=ip)
            obs.add_context(context)
            obs.add_source(self.name)
            obs.tag("blocklistde")
            obs.tag("bots")
        except ObservableValidationError as e:
            raise logging.error(e)
