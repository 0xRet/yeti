from flask import Blueprint, render_template, request

from core.observables import Observable
from core.web.api.analysis import match_observables

frontend = Blueprint("frontend", __name__, template_folder="templates", static_folder="staticfiles")


@frontend.route("/")
def browse():
    return render_template("browse.html")


@frontend.route("/query", methods=['GET', 'POST'])
def query():

    if request.method == "GET":
        return render_template("query.html")

    elif request.method == "POST":
        obs = [o.strip() for o in request.form['bulk-text'].split('\n')]
        data = match_observables(obs)
        return render_template("query_results.html", data=data)

@frontend.route("/observables/<id>")
def observable(id):
    o = Observable.objects.get(id=id)
    return render_template("observable.html", observable=o)
