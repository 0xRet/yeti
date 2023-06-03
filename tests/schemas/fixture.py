import datetime

from typing import Optional

from core import database_arango
from core.schemas.observable import Observable
from core.schemas.entity import ThreatActor
from core.schemas.tag import Tag
from core.schemas.indicator import Regex
from core.schemas.template import Template
from core.schemas.task import ExportTask

import unittest

class TagTest(unittest.TestCase):

    def setUp(self) -> None:
        database_arango.db.clear()

    def test_something(self):
        ip_hacker = Observable(value="8.8.8.8", type="ip").save()
        c2_hacker = Observable(value="c2.hacker.com", type="hostname").save()
        www_hacker = Observable(value="www.hacker.com", type="hostname").save()
        hacker = Observable(value="hacker.com", type="hostname").save()
        hacker.link_to(www_hacker, 'domain', 'Domain')
        hacker.link_to(c2_hacker, 'domain', 'Domain')
        hacker.link_to(ip_hacker, 'ip', 'IP')
        hacker.tag(['hacker'])
        ta = ThreatActor(name="HackerActor", relevant_tags=["hacker_sus"]).save()
        ta.link_to(hacker, 'c2', 'C2 infrastructure')
        www_hacker.tag(['web', 'hacker'])
        c2_hacker.tag(['web', 'hacker'])
        sus_hacker = Observable(value="sus.hacker.com", type="hostname").save()
        sus_hacker.tag(['web', 'hacker', 'hacker_sus'])
        regex = Regex(name='Hacker regex', pattern="^hacker.*", location="network").save()

        template = Template(name="RandomTemplate", template='<blah></blah>').save()
        export = ExportTask(
            name='RandomExport',
            template_name=template.name,
            include_tags=['include'],
            exclude_tags=['exclude'],
            ignore_tags=['ignore'],
            acts_on=['url']
            ).save()
