import re
import logging

from flask import request, url_for, abort
from flask.ext.classy import FlaskView, route
from mongoengine.errors import InvalidQueryError

from core.web.api.api import render


class CrudSearchApi(FlaskView):
    SEARCH_ALIASES = {
        'tags': 'tags__name',
    }

    def get_queryset(self, filters, regex):
        result_filters = dict()

        queryset = self.objectmanager.objects
        if "order_by" in filters:
            queryset = queryset.order_by(filters.pop("order_by"))

        for alias in self.SEARCH_ALIASES:
            if alias in filters:
                filters[self.SEARCH_ALIASES[alias]] = filters.pop(alias)

        for key, value in filters.items():
            key = key.replace(".", "__")
            if key in self.SEARCH_ALIASES:
                key = self.SEARCH_ALIASES[key]

            if regex:
                value = re.compile(value)

            if isinstance(value, list):
                key += "__all"

            result_filters[key] = value

        print "[{}] Filter: {}".format(self.__class__.__name__, result_filters)

        return queryset.filter(**result_filters)

    def search(self, query):
        fltr = query.get('filter', {})
        params = query.get('params', {})
        regex = params.pop('regex', False)
        page = params.pop('page', 1) - 1
        rng = params.pop('range', 50)

        data = []
        for o in self.get_queryset(fltr, regex)[page * rng:(page + 1) * rng]:
            o.uri = url_for("api.{}:post".format(self.objectmanager.__name__), id=str(o.id))
            data.append(o)

        return data

    def post(self):
        query = request.get_json(silent=True) or {}

        try:
            data = self.search(query)
        except InvalidQueryError as e:
            logging.error(e)
            abort(400)

        return render(data, self.template)


class CrudApi(FlaskView):

    template = None
    template_single = None

    def delete(self, id):
        obj = self.objectmanager.objects.get(id=id)
        obj.delete()
        return render({"status": "ok"})

    def index(self):
        data = []
        for obj in self.objectmanager.objects.all():
            obj.uri = url_for("api.{}:get".format(self.__class__.__name__), id=str(obj.id))
            data.append(obj)
        return render(data, template=self.template)

    # This method can be overridden if needed
    def _parse_request(self, json):
        return json

    def get(self, id):
        obj = self.objectmanager.objects.get(id=id)
        obj.uri = url_for("api.{}:post".format(self.__class__.__name__), id=str(obj.id))
        return render(obj, self.template_single)

    @route("/", methods=["POST"])
    def new(self):
        params = self._parse_request(request.json)
        obj = self.objectmanager(**params).save()
        obj.uri = url_for("api.{}:post".format(self.__class__.__name__), id=str(obj.id))
        return render(obj)

    def post(self, id):
        obj = self.objectmanager.objects.get(id=id)
        params = self._parse_request(request.json)
        obj = obj.clean_update(**params)
        obj.uri = url_for("api.{}:post".format(self.__class__.__name__), id=str(obj.id))
        return render(obj)
