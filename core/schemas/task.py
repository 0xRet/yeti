import datetime
import requests
import pandas as pd
from io import BytesIO
from zipfile import ZipFile

from enum import Enum
import os
from dateutil import parser
from core.helpers import refang, REGEXES
from typing import Type

from pydantic import BaseModel, Field
from core import database_arango
from core.schemas.observable import Observable, ObservableType
from core.schemas.template import Template

from core.config.config import yeti_config


def now():
    return datetime.datetime.now(datetime.timezone.utc)


class TaskStatus(str, Enum):
    idle = 'idle'
    running = 'running'
    completed = 'completed'
    failed = 'failed'

class TaskType(str, Enum):
    feed = 'feed'
    analytics = 'analytics'
    export = 'export'
    oneshot = 'oneshot'
    inline = 'inline'

class Task(BaseModel, database_arango.ArangoYetiConnector):
    _collection_name: str = 'tasks'
    _type_filter: str = ''
    _defaults: dict = {}

    id: str | None = None
    name: str
    enabled: bool = True
    description: str = ''
    status: TaskStatus = TaskStatus.idle
    status_message: str = ''
    last_run: datetime.datetime | None = None

    # only used for cron tasks
    frequency: datetime.timedelta = datetime.timedelta(days=1)

    def run(self):
        """Runs the task"""
        raise NotImplementedError('run() must be implemented in subclass')

    @classmethod
    def load(cls, object: dict) -> "TaskTypes":
        # If this is called using Task, then return a Task or AnalyticsTask
        if cls == Task and object['type'] in TYPE_MAPPING:
            cls = TYPE_MAPPING[object['type']]
        # Otherwise, use the actual cls.
        return cls(**object)

class FeedTask(Task):
    type: str = Field(TaskType.feed, const=True)
    
    def _unzip_content(self, content: bytes) -> bytes:
        """Unzip the content of a response.

        Args:
            content: The content to unzip.

        Returns:
            The unzipped content.
        """
        f = ZipFile(BytesIO(content))
        name = f.namelist()[0]
        return f.read(name)
    
    def _filter_observables_by_time(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        """Filter a dataframe by comparing the datetime in a column to the last run time.

        Args:
            df: The dataframe to filter.
            column: The column containing the datetime to compare.

        Returns:
            A filtered dataframe.
        """
        if self.last_run:
            df = df[df[column] > self.last_run]
        return df
    
    def _make_request(
        self,
        url: str,
        method: str = "get",
        headers: dict = {},
        auth: tuple = (),
        params: dict = {},
        data: dict = {},
        verify: bool = True,
        sort: bool = True,
    ) -> requests.Response:
        """Helper function. Performs an HTTP request on ``source`` and returns request object.

        Args:
            method: Optional HTTP method to use, e.g. "get" or "post".
            headers: Optional headers to be added to the HTTP request.
            auth: Username / password tuple to be sent along with the HTTP request.
            params: Optional param to be added to the HTTP GET request.
            data: Optional param to be added to the HTTP POST request.
            verify: Enforce (True) or skip (False) SSL verification.

        Returns:
            requests object.
        """
        response = getattr(requests, method.lower())(
            url,
            headers=headers,
            auth=auth,
            proxies=yeti_config.proxy,
            params=params,
            data=data,
            verify=verify,
            stream=True,
        )

        if response.status_code != 200:
            raise RuntimeError(f"{url} returned code: {response.status_code}")

        if not sort:
            return response

        last_modified_header = response.headers.get("Last-Modified")
        if self.last_run is not None and last_modified_header:
            last_modified = parser.parse(last_modified_header)
            if self.last_run > last_modified.replace(tzinfo=None):
                msg = (f"{url}: Last-Modified header ({last_modified_header}) "
                       "before last-run ({self.last_run})")
                raise RuntimeError(msg)

        return response

class AnalyticsTask(Task):

    acts_on: list[str] = []  # By default act on all observables
    type: str = Field(TaskType.analytics, const=True)

    def run(self):
        """Filters observables to analyze and then calls each()"""
        targets = Observable.filter(args={'type__in': self.acts_on})[0]
        self.bulk(targets)

    def bulk(self, observables: list[Observable]):
        """Analyzes a set of observables. Can be overriden if needed."""
        for observable in observables:
            assert observable.id is not None
            self.each(observable)
            self.analysis_done(observable.id)

    def analysis_done(self, observable_id: str):
        """Updates the status of the analysis for a given observable"""
        # TODO: Write a function that just updates a single field.
        observable = Observable.get(observable_id)
        assert observable is not None
        observable.last_analysis[self.name] = now()
        observable.save()

    def each(self, observable: Observable) -> Observable:
        """Analyzes a single observable.

        Args:
            observable: The observable to analyze.

        Returns:
            The observable that was processed, to track last analysis."""
        raise NotImplementedError


class ExportTask(Task):

    type: str = Field(TaskType.export, const=True)

    include_tags: list[str] = []
    exclude_tags: list[str] = []
    ignore_tags: list[str] = []
    fresh_tags: bool = True
    output_dir: str = 'exports'
    acts_on: list[ObservableType] = []
    template_name: str
    sha256: str | None

    @property
    def output_file(self) -> str:
        return os.path.abspath(os.path.join(self.output_dir, self.name))

    def run(self) -> None:
        """Runs the export asynchronously."""
        export_data = self.get_tagged_data(
            acts_on=self.acts_on,
            include_tags=self.include_tags,
            exclude_tags=self.exclude_tags,
            ignore_tags=self.ignore_tags,
            fresh_tags=self.fresh_tags,
        )

        if not os.path.isdir(self.output_dir):
            os.mkdir(self.output_dir)
        template = Template.find(name=self.template_name)
        template.render(export_data, self.output_file)
        # hash output file and store result

    def get_tagged_data(
            self,
            acts_on: list[str],
            include_tags: list[str],
            exclude_tags: list[str],
            ignore_tags: list[str],
            fresh_tags: bool):

        args = {
            'acts_on': acts_on,
            'include': include_tags,
            'exclude': exclude_tags,
            'ignore': ignore_tags,
            'fresh': fresh_tags
        }

        results = database_arango.tagged_observables_export(Observable, args)
        return results


TYPE_MAPPING = {
    'analytics': AnalyticsTask,
    'feed': Task,
    'export': ExportTask
}


TaskTypes =  FeedTask | AnalyticsTask | ExportTask
