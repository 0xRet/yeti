import os
import codecs
import logging
from datetime import datetime
import traceback

from mongoengine import ListField, StringField, Q, ReferenceField, PULL
from jinja2 import Template
from flask.ext.mongoengine.wtf import model_form

from core.database import YetiDocument
from core.config.celeryctl import celery_app
from core.observables import Observable, Tag
from core.scheduling import ScheduleEntry


class ExportTemplate(YetiDocument):
    name = StringField(required=True, max_length=255, verbose_name="Name")
    template = StringField(required=True)

    def render(self, elements):
        t = Template(self.template)
        return t.render(elements=elements)

    def stream(self, elements):
        t = Template(self.template)
        s = t.stream(elements=elements)
        s.enable_buffering(5)
        return s

    def info(self):
        return {"name": self.name, "template": self.template, "id": self.id}


@celery_app.task
def execute_export(export_id):

    export = Export.objects.get(id=export_id)
    try:
        if export.enabled:
            logging.info("Running export {}".format(export.name))
            export.update_status("Exporting...")
            export.execute()
            export.update_status("OK")
        else:
            logging.error("Export {} has been disabled".format(export.name))
    except Exception as e:
        msg = "ERROR executing export: {}".format(e)
        logging.error(msg)
        logging.error(traceback.format_exc())
        export.update_status(msg)

    export.last_run = datetime.now()
    export.save()


class Export(ScheduleEntry):

    SCHEDULED_TASK = 'core.exports.execute_export'
    CUSTOM_FILTER = {}

    include_tags = ListField(ReferenceField(Tag, reverse_delete_rule=PULL))
    exclude_tags = ListField(ReferenceField(Tag, reverse_delete_rule=PULL))
    output_dir = StringField(default='exports')
    acts_on = StringField(verbose_name="Acts on", required=True)
    template = ReferenceField(ExportTemplate)

    def __init__(self, *args, **kwargs):
        super(Export, self).__init__(*args, **kwargs)
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    @property
    def output_file(self):
        return os.path.abspath(os.path.join(self.output_dir, self.name))

    def execute(self):
        self.export_file_handle = codecs.open(self.output_file, 'w+', "utf-8")
        q = Q(tags__name__in=[t.name for t in self.include_tags]) & Q(tags__name__nin=[t.name for t in self.exclude_tags])
        q &= Q(_cls__contains=self.acts_on)

        output = self.template.stream(Observable.objects(q))
        output.enable_buffering(5)
        for o in output:
            self.write(o)

        self.export_file_handle.close()

    def write(self, output):
        self.export_file_handle.write(output)

    def info(self):
        i = {k: v for k, v in self._data.items() if k in ["name", "output_dir", "enabled", "description", "status", "last_run", "include_tags", "exclude_tags"]}
        i['frequency'] = str(self.frequency)
        i['id'] = str(self.id)
        i['include_tags'] = [tag.name for tag in self.include_tags]
        i['exclude_tags'] = [tag.name for tag in self.exclude_tags]
        i['template'] = self.template.name
        i['acts_on'] = self.acts_on
        return i
