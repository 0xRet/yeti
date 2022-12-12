from __future__ import unicode_literals

import os
from importlib import import_module
from bson.json_util import dumps
from mongoengine import connect

from flask import Flask, url_for, request, current_app, session
from flask_login import LoginManager, current_user

from core.config.config import yeti_config
from core.user import User
from core.web.json import JSONDecoder
from core.web.api import api
from mongoengine.errors import DoesNotExist
from core.yeti_plugins import get_plugins

webapp = Flask(__name__, static_folder="frontend")

webapp.secret_key = os.urandom(24)
webapp.json_decoder = JSONDecoder
webapp.before_first_request(get_plugins)

login_manager = LoginManager()
login_manager.init_app(webapp)
login_manager.login_view = "/login"

auth_module = import_module("core.auth.%s" % yeti_config.auth.module)
webapp.register_blueprint(auth_module.auth)
is_true = False

if yeti_config.mongodb.tls:
    is_true = True

connect(
    yeti_config.mongodb.database,
    host=yeti_config.mongodb.host,
    port=yeti_config.mongodb.port,
    username=yeti_config.mongodb.username,
    password=yeti_config.mongodb.password,
    connect=False,
    tls=False,
)


# Handle authentication
@login_manager.user_loader
def load_user(session_token):
    try:
        # Requires to use login_user() in the auth methods
        return User.objects.get(session_token=session_token)
    except DoesNotExist:
        return None


@login_manager.request_loader
def api_auth(request):
    try:
        return User.objects.get(api_key=request.headers.get("X-Api-Key"))
    except DoesNotExist:
        return None


login_manager.anonymous_user = auth_module.get_default_user


@api.before_request
def api_login_required():
    if not current_user.is_active and not request.method == "OPTIONS":
        return dumps({"error": "unauthorized"}), 401


webapp.register_blueprint(api, url_prefix="/api")


@webapp.route("/", defaults={"path": ""})
@webapp.route("/<path:path>")
def index(path):
    if path.startswith("css/") or path.startswith("js/"):
        return current_app.send_static_file(path)
    return current_app.send_static_file("index.html")


@webapp.route("/list_routes")
def list_routes():
    import urllib

    output = []
    for rule in webapp.url_map.iter_rules():

        options = {}
        for arg in rule.arguments:
            options[arg] = "[{0}]".format(arg)

        methods = ",".join(rule.methods)
        url = url_for(rule.endpoint, **options)
        line = "{:50s} {:20s} {}".format(rule.endpoint, methods, url)
        output.append(line)

    for line in sorted(output):
        print(line)

    return "\n".join(output)


@webapp.template_test()
def startswith(string, pattern):
    return string.startswith(pattern)
