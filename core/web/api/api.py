from flask import Blueprint, request
from flask_restful import Resource, Api, reqparse
from flask.ext.negotiation import Render
from flask.ext.negotiation.renderers import renderer, template_renderer, json_renderer
from bson.json_util import dumps, loads

from core.indicators import Indicator
from core.entities import Entity
from core.observables import Observable

api = Blueprint("api", __name__, template_folder="templates")
api_restful = Api(api)


@renderer('application/json')
def bson_renderer(data, template=None, ctx=None):
    return dumps(data)

render = Render(renderers=[template_renderer, bson_renderer])


class ObservableApi(Resource):

    def put(self):
        q = request.json
        data = {"count": 0}
        for o in q["observables"]:
            obs = Observable.add_text(o["value"])
            if "tags" in o:
                obs.tag(o["tags"])
            if "context" in o:
                obs.add_context(o["context"])
            data["count"] += 1

        return render(data)

    def post(self):
        q = request.json

        for o in q['observables']:
            pass

    def get(self):

        # try to get json body
        q = request.get_json(silent=True)

        if not q:  # if no json body is present, return list of all observables
            return render([o.info() for o in Observable.objects()])

        else:
            data = {"matches": [], "known": [], "unknown": [], "entities": []}
            added_entities = set()
            for o, i in Indicator.search(q["observables"]):
                match = i.info()
                match.update({"observable": o, "related": []})

                for nodes in i.neighbors().values():
                    for l, node in nodes:
                        # add node name and link description to indicator
                        node_data = {"entity": node.type, "name": node.name, "link_description": l.description or l.tag}
                        match["related"].append(node_data)

                        # uniquely add node information to related entitites
                        if node.name not in added_entities:
                            nodeinfo = node.info()
                            nodeinfo['type'] = node.type
                            data["entities"].append(nodeinfo)
                            added_entities.add(node.name)

                data["matches"].append(match)
                # try to fetch the observable from db, if not found
                # add it to "unkown" array
                try:
                    data['known'].append(Observable.obejcts.get(value=o).info())
                except Exception:
                    data["unknown"].append({"observable": o})

            return render(data, "observables.html")

api_restful.add_resource(ObservableApi, '/observables/')
