#!/usr/bin/python
# -*- coding: utf-8 -*-

__description__ = 'Malcom - Malware communications analyzer'
__author__ = '@tomchop_'
__version__ = '1.0 alpha'
__license__ = "GPL"


#system
import os, datetime, time, sys, signal, argparse, re
import netifaces as ni

#db 
from pymongo import MongoClient

#json / bson
from bson.objectid import ObjectId
from bson.json_util import dumps, loads

#flask stuff
from werkzeug import secure_filename
from flask import Flask, request, render_template, redirect, url_for, g, make_response, abort, flash
from functools import wraps

#websockets
from geventwebsocket.handler import WebSocketHandler
from gevent.pywsgi import WSGIServer

# custom
from Malcom.auxiliary.toolbox import *
from Malcom.analytics.analytics import Analytics
from Malcom.feeds.feed import FeedEngine
from Malcom.model.datatypes import Hostname
from Malcom.networking import netsniffer
import Malcom

ALLOWED_EXTENSIONS = set(['txt', 'csv'])

app = Malcom.app
		
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.debug = True


# This enables the server to be ran behind a reverse-proxy
# Make sure you have an nginx configuraiton similar to this

# location = /malcom { rewrite ^ /malcom/; }
# location /malcom { try_files $uri @malcom; }

# # proxy
# location @malcom {
# 	proxy_pass http://127.0.0.1:8080;
# 	proxy_http_version 1.1;
# 	proxy_set_header SCRIPT_NAME /malcom;
# 	proxy_set_header Host $host;    
# 	proxy_set_header X-Scheme $scheme;
# 	proxy_set_header Upgrade $http_upgrade;
# 	proxy_set_header Connection "upgrade";
# }

def malcom_app(environ, start_response):  
	
	if environ.get('HTTP_SCRIPT_NAME'):
		# update path info 
		environ['PATH_INFO'] = environ['PATH_INFO'].replace(environ['HTTP_SCRIPT_NAME'], "")
		# declare SCRIPT_NAME
		environ['SCRIPT_NAME'] = environ['HTTP_SCRIPT_NAME']
	
	if environ.get('HTTP_X_SCHEME'):	
		# forward the scheme
		environ['wsgi.url_scheme'] = environ.get('HTTP_X_SCHEME')

	return app(environ, start_response)


@app.errorhandler(404)
def page_not_found(error):
	return 'This page does not exist', 404

@app.after_request
def after_request(response):
	origin = request.headers.get('Origin', '')
	# debug_output(origin, False)
	response.headers['Access-Control-Allow-Origin'] = origin
	response.headers['Access-Control-Allow-Credentials'] = 'true'
	return response

@app.before_request
def before_request():
	# make configuration and analytics engine available to views
	g.config = app.config
	g.a = Malcom.analytics_engine


# decorator for URLs that should not be public
def private_url(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if app.config['PUBLIC']:
            abort(404)
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
	return redirect(url_for('dataset'))

# feeds ========================================================

@app.route('/feeds')
def feeds():
	alpha = sorted(Malcom.feed_engine.feeds, key=lambda name: name)
	return render_template('feeds.html', feed_names=alpha, feeds=Malcom.feed_engine.feeds)

@app.route('/feeds/run/<feed_name>')
@private_url
def run_feed(feed_name):
	Malcom.feed_engine.run_feed(feed_name)
	return redirect(url_for('feeds'))


# graph operations =============================================

@app.route('/nodes/<field>/<path:value>')
def nodes(field, value):
	return render_template('dynamic_nodes.html', field=field, value=value)

@app.route('/graph/<field>/<path:value>')
def graph(field, value):
	a = g.a
	#query = { field: re.compile(re.escape(value), re.IGNORECASE) }
	# faster query
	query = { field: value }
	base_elts = [e for e in a.data.elements.find( query )]

	total_nodes = []
	total_edges = []
	nodes = []
	edges = []
	for elt in base_elts:
		nodes, edges = a.data.get_neighbors(elt)
		total_nodes.extend(nodes)
		total_edges.extend(edges)

	data = { 'query': base_elts, 'edges': total_edges, 'nodes': total_nodes }
	ids = [node['_id'] for node in nodes]

	debug_output("query: %s, edges found: %s, nodes found: %s" % (len(base_elts), len(edges), len(nodes)))
	return (dumps(data))

@app.route('/neighbors', methods=['POST'])
def neighbors():
	a = g.a
	allnodes = []
	alledges = []
	msg = ""
	if len(request.form.getlist('ids')) == 0:
		return dumps({})

	for id in request.form.getlist('ids'):
		elt = a.data.elements.find_one({'_id': ObjectId(id) })
		nodes, edges = a.data.get_neighbors(elt)
		if len(nodes) > 2000 or len(edges) > 2000:
			msg = "TOO_MANY_ELEMENTS" # at least, we notify the user that we're doing something dirty
		allnodes += [n for n in nodes[:2000] if n not in allnodes] # this is a really expensive operation
		alledges += [e for e in edges[:2000] if e not in alledges] # dirty solution, limit to 1000 results
		
	data = { 'query': elt, 'nodes':allnodes, 'edges': alledges, 'msg': msg }

	return (dumps(data))

@app.route('/evil', methods=['POST'])
def evil():
	a = g.a
	allnodes = []
	alledges = []
	msg = ""
	for id in request.form.getlist('ids'):
		elt = a.data.elements.find_one({'_id': ObjectId(id) })
		nodes, edges = a.find_evil(elt)
		allnodes += [n for n in nodes if n not in allnodes]
		alledges += [e for e in edges if e not in alledges]
		
	data = { 'query': None, 'nodes':allnodes, 'edges': alledges, 'msg': msg }

	return (dumps(data))


# dataset operations ======================================================

def allowed_file(filename):
	return '.' in filename and \
		   filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

@app.route('/dataset/')
def dataset():
	return render_template("dataset.html")


@app.route('/dataset/list/') # ajax method for sarching dataset and populating dataset table
def list():
	a = g.a
	query = {}
	try:
		page = int(request.args['page'])
	except Exception, e:
		page = 0

	fuzzy = False if request.args['fuzzy']=='false' else True

	for key in request.args:
		if key not in  ['page', 'fuzzy']:
			if request.args[key].find(',') != -1: # split request arguments
				if fuzzy:
					query['$and'] = [{ key: re.compile(split, re.IGNORECASE)} for split in request.args[key].split(',')]
				else:
					query['$and'] = [{ key: split} for split in request.args[key].split(',')]
			else:
				if fuzzy:
					query[key] = re.compile(request.args[key], re.IGNORECASE) # {"$regex": request.args[key]}
				else:
					query[key] = request.args[key]

	per_page = 50

	chrono_query = datetime.datetime.now()
	elts = [e for e in a.data.find(query).sort('date_created', -1)[page*per_page:page*per_page+per_page]]
	chrono_query = datetime.datetime.now() - chrono_query
	debug_output("Query completed in %s" % chrono_query)
	
	
	for elt in elts:
		elt['link_value'] = url_for('nodes', field='value', value=elt['value'])
		elt['link_type'] = url_for('nodes', field='type', value=elt['type'])

	data = {}
	if len(elts) > 0:
		data['fields'] = elts[0].display_fields
		data['elements'] = elts
	else:
		data['fields'] = [('value', 'Value'), ('type', 'Type'), ('tags', 'Tags')]
		data['elements'] = []
	
	data['page'] = page
	data['per_page'] = per_page

	chrono_count = datetime.datetime.now()
	data['total_results'] = a.data.find(query).count()
	chrono_count = datetime.datetime.now() - chrono_count
	debug_output("Count completed in %s" % chrono_count)
	data['chrono_query'] = str(chrono_query)
	data['chrono_count'] = str(chrono_count)
	return dumps(data)

@app.route('/dataset/list/csv')
def dataset_csv():
	a = g.a
	filename = []
	query = {}
	fuzzy = False if request.args['fuzzy'] == 'false' else True

	for key in request.args:
		if key != '' and key not in ['fuzzy']:
			if fuzzy:
				# slow
				query[key] = re.compile(re.escape(request.args[key]), re.IGNORECASE)
			else:
				# skip regex to make it faster
				query[key] = request.args[key]
			filename.append("%s_%s" % (key, request.args[key]))
		else:
			filename.append('all')

	filename = "-".join(filename)
	results = a.data.find(query).sort('date_created', -1)
	
	if results.count() == 0:
		flash("You're about to download an empty .csv",'warning')
		return redirect(url_for('dataset'))
	else:
		response = make_response()
		response.headers['Cache-Control'] = 'no-cache'
		response.headers['Content-Type'] = 'text/csv'
		response.headers['Content-Disposition'] = 'attachment; filename='+filename+'-extract.csv'
		fields = results[0].display_fields
		data = ";".join([f[1] for f in fields ]) + "\n"
		for e in results:
			data += ";".join([list_to_str(e.get(f[0],"-")) for f in fields]) + "\n"

		response.data = data
		response.headers['Content-Length'] = len(response.data)

		return response


@app.route('/dataset/add', methods=['POST'])
@private_url
def add_data():
	
	if request.method == "POST":
		file = request.files.get('element-list')
		if file:  #we're dealing with a list of elements
			if allowed_file(file.filename):
				elements = file.read()
				elements = elements.split("\n")
			else:
				return 'filename not allowed'
		else:
			elements = [request.form['element']]

		tags = request.form.get('tags', None)
		
		if len(elements) == 0 or not tags:
			flash("You must specify an element and tags", 'warning')
			return redirect(url_for('dataset'))

		a = g.a
		tags = tags.strip().split(";")
		a.add_text(elements, tags)

		if request.form.get('analyse', None):
			a.process()

		return redirect(url_for('dataset'))

	else:
		return "Not allowed"

@app.route('/dataset/remove/<id>')
def delete(id):
	a = g.a 
	result = a.data.remove(id)
	return dumps(result)

@app.route('/dataset/clear/')
@private_url
def clear():
	g.a.data.clear_db()
	return redirect(url_for('dataset'))

@app.route('/analytics')
def analytics():
	g.a.process()
	return "Analytics: Done."

# Sniffer ============================================

@app.route('/sniffer/',  methods=['GET', 'POST'])
def sniffer():
	if request.method == 'POST':
		filter = request.form['filter']
		
		session_name = request.form['session_name']
		if session_name == "":
			flash("Please specify a session name", 'warning')
			return redirect(url_for('sniffer'))

		debug_output("Creating session %s" % session_name)

		# intercept TLS ?
		tls_proxy_port = request.form.get('tls_proxy_port', None)
		# create iptables entry?

		Malcom.sniffer_sessions[session_name] = netsniffer.Sniffer(Analytics(), session_name, str(request.remote_addr), filter, g.config['IFACES'], tls_proxy_port)
		
		
		pcap = None
		# if we're dealing with an uploaded PCAP file
		file = request.files.get('pcap-file')
		if file:
			Malcom.sniffer_sessions[session_name].pcap = file.read()

		# start sniffing right away
		if request.form.get('startnow', None):
			Malcom.sniffer_sessions[session_name].start(str(request.remote_addr))
		
		return redirect(url_for('sniffer_session', session_name=session_name, pcap_filename=pcap))


	return render_template('sniffer_new.html')

@app.route('/sniffer/sessionlist/')
def sniffer_sessionlist():
	session_list = []
	for s in Malcom.sniffer_sessions:
		session_list.append({
								'name': s, 
								'packets': len(Malcom.sniffer_sessions[s].pkts),
								'nodes': len(Malcom.sniffer_sessions[s].nodes),
								'edges': len(Malcom.sniffer_sessions[s].edges),
								'status': "Running" if Malcom.sniffer_sessions[s].status() else "Stopped"
							})
	return dumps({'session_list': session_list})


@app.route('/sniffer/<session_name>/')
def sniffer_session(session_name, pcap_filename=None):
	# check if session exists
	if session_name not in Malcom.sniffer_sessions:
		debug_output("Sniffing session '%s' does not exist" % session_name, 'error')
		flash("Sniffing session '%s' does not exist" % session_name, 'warning')
		return redirect(url_for('sniffer'))
	
	return render_template('sniffer.html', session=Malcom.sniffer_sessions[session_name], session_name=session_name)
	

@app.route('/sniffer/<session_name>/pcap')
def pcap(session_name):
	if session_name not in Malcom.sniffer_sessions:
		abort(404)
	response = make_response()
	response.headers['Cache-Control'] = 'no-cache'
	response.headers['Content-Type'] = 'application/vnd.tcpdump.pcap'
	response.headers['Content-Disposition'] = 'attachment; filename='+session_name+'_capture.pcap'
	response.data = Malcom.sniffer_sessions[session_name].get_pcap()
	response.headers['Content-Length'] = len(response.data)

	return response



@app.route("/sniffer/<session_name>/<flowid>/raw")
def send_raw_payload(session_name, flowid):
	if session_name not in Malcom.sniffer_sessions:
		abort(404)
	if flowid not in Malcom.sniffer_sessions[session_name].flows:
		abort(404)
			
	response = make_response()
	response.headers['Cache-Control'] = 'no-cache'
	response.headers['Content-Type'] = 'application/octet-stream'
	response.headers['Content-Disposition'] = 'attachment; filename=%s_%s_dump.raw' % (session_name, flowid)
	response.data = Malcom.sniffer_sessions[session_name].flows[flowid].get_payload(encoding='raw')
	response.headers['Content-Length'] = len(response.data)

	return response


# APIs =========================================


@app.route('/api/analytics')
def analytics_api():
	debug_output("Call to analytics API")

	if request.environ.get('wsgi.websocket'):
		debug_output("Got websocket")

		ws = request.environ['wsgi.websocket']
		g.a.websocket = ws

		while True:
			try:
				message = loads(ws.receive())
				debug_output("Received: %s" % message)
			except Exception, e:
				return ""

			cmd = message['cmd']

			if cmd == 'analyticsstatus':
				g.a.notify_progress()


			


@app.route('/api/sniffer')
def sniffer_api():
	debug_output("call to sniffer API")

	if request.environ.get('wsgi.websocket'):

		ws = request.environ['wsgi.websocket']

		while True:
			try:
				message = loads(ws.receive())
			except Exception, e:
				debug_output("Could not decode JSON message: %s" %e)
				return ""
			
			debug_output("Received: %s" % message)



			cmd = message['cmd']
			session_name = message['session_name']

			if session_name in Malcom.sniffer_sessions:
				session = Malcom.sniffer_sessions[session_name]
			else:
				send_msg(ws, "Session %s not foud" % session_name, type=cmd)
				continue

			session.ws = ws


			# websocket commands

			if cmd == 'sessionlist':
				session_list = [s for s in Malcom.sniffer_sessions]
				send_msg(ws, {'session_list': session_list}, type=cmd)
				continue

			if cmd == 'sniffstart':
				session.start(str(request.remote_addr), public=g.config['PUBLIC'])
				send_msg(ws, "OK", type=cmd)
				continue

			if cmd == 'sniffstop':
				if g.config['PUBLIC']:
					continue
				if session.status():
					session.stop()
					send_msg(ws, 'OK', type=cmd)
				else:
					send_msg(ws, 'Error: sniffer not running', type=cmd)
				continue

			if cmd == 'sniffstatus':
				if session.status():
					status = 'active'
					debug_output("Session %s is active" % session.name)
					send_msg(ws, {'status': 'active', 'session_name': session.name}, type=cmd)
				else:
					status = 'inactive'
					debug_output("Session %s is inactive" % session.name)
					send_msg(ws, {'status': 'inactive', 'session_name': session.name}, type=cmd)
				continue
					
			if cmd == 'sniffupdate':
				data = session.update_nodes()
				data['type'] = cmd
				if data:
					ws.send(dumps(data))
				continue

			if cmd == 'flowstatus':
				data = session.flow_status()
				data['type'] = cmd
				if data:
					ws.send(dumps(data))
				continue

			if cmd == 'get_flow_payload':
				fid = message['flowid']
				flow = session.flows[fid]
				data = {}
				data['payload'] = flow.get_payload()

				data['type'] = cmd
				ws.send(dumps(data))
				continue
		
	return ""


class MalcomWeb(object):
	"""docstring for MalcomWeb"""
	def __init__(self, public, listen_port, listen_interface):
		self.public = public
		self.listen_port = listen_port
		self.listen_interface = listen_interface
		self.start_server()

	def start_server(self):
		for key in Malcom.config:
			app.config[key] = Malcom.config[key]
		app.config['UPLOAD_FOLDER'] = ""
		
		sys.stderr.write("Starting webserver in %s mode...\n" % ("public" if self.public else "private"))
		try:
			http_server = WSGIServer((self.listen_interface, self.listen_port), malcom_app, handler_class=WebSocketHandler)
			sys.stderr.write("Webserver listening on %s:%s\n\n" % (self.listen_interface, self.listen_port))
			http_server.serve_forever()
		except KeyboardInterrupt:

			sys.stderr.write(" caught: Exiting gracefully\n")

			if len(Malcom.sniffer_sessions) > 0:
				debug_output('Stopping sniffing sessions...')
				for s in Malcom.sniffer_sessions:
					session = Malcom.sniffer_sessions[s]
					session.stop()
					if session.tls_proxy:
						session.tls_proxy.stop()

			Malcom.feed_engine.stop_all_feeds()
			exit(0)
