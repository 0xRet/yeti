from __future__ import unicode_literals

from mongoengine import *
from flask_mongoengine.wtf import model_form

from core.database import Node
from core.indicators import DIAMOND_EDGES
from core.database import Node, EntityListField


class Indicator(Node):
    SEARCH_ALIASES = {}

    DISPLAY_FIELDS = [
        ("name", "Name"),
        ("pattern", "Pattern"),
        ("location", "Location"),
    ]

    name = StringField(required=True, max_length=1024, verbose_name="Name")
    pattern = StringField(required=True, verbose_name="Pattern")
    location = StringField(required=True, max_length=255, verbose_name="Location")
    description = StringField(verbose_name="Description")

    meta = {
        "allow_inheritance": True,
        "ordering": ["name"],
    }

    def __unicode__(self):
        return "{} (pattern: '{}')".format(self.name, self.pattern)

    @classmethod
    def search(cls, observables):
        indicators = list(Indicator.objects())
        for o in observables:
            for i in indicators:
                if i.match(o):
                    yield o, i

    def match(self, value):
        raise NotImplementedError(
            "match() method must be implemented in Indicator subclasses"
        )

    def action(self, target, source, verb="Indicates"):
        self.active_link_to(target, verb, source)

    def generate_tags(self):
        return [self.diamond.lower(), self.name.lower()]

    def info(self):
        i = {
            k: v
            for k, v in self._data.items()
            if k in ["name", "pattern", "description", "location"]
        }
        i["id"] = str(self.id)
        i["type"] = self.type.lower()
        return i
