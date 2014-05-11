from gevent import monkey; monkey.patch_socket(dns=False); monkey.patch_time();

import dateutil

import threading, os

from pymongo import MongoClient
from pymongo.son_manipulator import SONManipulator
import pygeoip

from bson.objectid import ObjectId

from Malcom.auxiliary.toolbox import *
from Malcom.model.datatypes import Hostname, Url, Ip, As, Evil, DataTypes
import Malcom


class Transform(SONManipulator):
	def transform_incoming(self, son, collection):
		for (key, value) in son.items():
			if isinstance(value, dict):
				son[key] = self.transform_incoming(value, collection)
		return son

	def transform_outgoing(self, son, collection):
		if 'type' in son:
			t = son['type']
			return DataTypes[t].from_dict(son)
		else:
			return son

class Model:

	def __init__(self):
		self._connection = MongoClient()
		self._db = self._connection.malcom
		self._db.add_son_manipulator(Transform())
		
		# collections
		self.elements = self._db.elements
		self.graph = self._db.graph
		self.sniffer_sessions = self._db.sniffer_sessions
		self.history = self._db.history
		self.public_api = self._db.public_api

		self.db_lock = threading.Lock()

		# create indexes
		self.rebuild_indexes()

	def rebuild_indexes(self):
		# create indexes
		debug_output("Rebuliding indexes...", 'model')
		self.elements.ensure_index([('date_created', -1), ('value', 1)])
		self.elements.ensure_index('value')
		self.elements.ensure_index('tags')
		self.graph.ensure_index([('src', 1), ('dst', 1)])
		self.graph.ensure_index('src')
		self.graph.ensure_index('dst')

	def stats(self):
		stats = "DB loaded with %s elements\n" % self._db.elements.count()
		stats += "Graph has %s edges" % self._db.graph.count()
		return stats

	def find(self, query={}):
		return self.elements.find(query)
		
	def find_one(self, oid):
		return self.elements.find_one(oid)

	def clear_db(self):
		for c in self._db.collection_names():
			if c != "system.indexes":
				self._db[c].drop()
	
	def list_db(self):
		for e in self.elements.find():
			debug_output(e)


	def save_sniffer_session(self, session):
		dict = { 
			'name': session.name,
			'filter': session.filter,
			'intercept_tls': session.intercept_tls,
			'pcap': True,
			'packet_count': session.packet_count,
			}
		status = self.sniffer_sessions.update({'name': dict['name']}, dict, upsert=True)
		return status

	def get_sniffer_session(self, session_name):
		session = self.sniffer_sessions.find_one({'name': session_name})
		return session

	def del_sniffer_session(self, session_name):

		session = self.sniffer_sessions.find_one({'name': session_name})
			
		filename = session['name'] + ".pcap"
				
		try:
			os.remove(Malcom.config['SNIFFER_DIR'] + "/" + filename)
		except Exception, e:
			print e

		self.sniffer_sessions.remove({'name': session_name})

		return True

	def get_sniffer_sessions(self):
		return [s for s in self.sniffer_sessions.find()]
	
	def save(self, element, with_status=False):
	
		tags = []
		if 'tags' in element:
			tags = element['tags']
			del element['tags'] 	# so tags in the db do not get overwritten

		if '_id' in element:
			del element['_id']
		
		# check if existing
		_element = self.elements.find_one({'value': element['value']})
		if _element != None:
			for key in _element:
				element[key] = _element[key]
			print tags
			print element
			if key not in element:
				element[key] = {}
			element['tags'].extend(tags)
			new = False
		else:
			new = True

		if not new:
			debug_output("(updated %s %s)" % (element.type, element.value), type='model')
			assert element.get('date_created', None) != None
		else:
			debug_output("(added %s %s)" % (element.type, element.value), type='model')
			element['date_created'] = datetime.datetime.utcnow()
			element['next_analysis'] = datetime.datetime.utcnow()

		print element
		self.elements.save(element)
		assert element['date_created'] != None

		if not with_status:
			return element
		else:
			return element, new

	def remove(self, element_id):
		return self.elements.remove({'_id' : ObjectId(element_id)})

	def exists(self, element):
		return self.elements.find_one({ 'value': element.value })

	def connect(self, src, dst, attribs="", commit=True):
			if not src or not dst:
				return None
			
			conn = self.graph.find_one({ 'src': ObjectId(src._id), 'dst': ObjectId(dst._id) })
			
			# if the connection already exists, just modify attributes and last seen time
			if conn:
				if attribs != "": conn['attribs'] = attribs
				conn['last_seen'] = datetime.datetime.utcnow()

			# if not, change the connection
			else:
				conn = {}
				conn['src'] = src._id
				conn['dst'] = dst._id
				conn['attribs'] = attribs
				conn['first_seen'] = datetime.datetime.utcnow()
				conn['last_seen'] = datetime.datetime.utcnow()
				debug_output("(linked %s to %s [%s])" % (str(src._id), str(dst._id), attribs), type='model')
			
			if commit:
				self.graph.save(conn)
			
			return conn

	def add_feed(self, feed):
		elts = feed.get_info()
	  
		for e in elts:
			self.malware_add(e,e['tags'])

	def get_destinations(self, elt):
		return [e['value'] for e in self.graph.find({'src': elt['_id']}, 'value')]

	def get_neighbors_id(self, elts, query={}, include_original=True):

		original_ids = [e['_id'] for e in elts]

		new_edges = self.graph.find({'$or': [
				{'src': {'$in': original_ids}}, {'dst': {'$in': original_ids}}
			]})
		_new_edges = self.graph.find({'$or': [
				{'src': {'$in': original_ids}}, {'dst': {'$in': original_ids}}
			]})


		ids = {}

		for e in _new_edges:
			ids[e['src']] = e['src']
			ids[e['dst']] = e['dst']

		ids = [i for i in ids]

		if include_original:
			q = {'$and': [{'_id': {'$in': ids}}, query]}
			original = {'$or': [q, {'_id': {'$in': original_ids}}]}
			new_nodes = self.elements.find(original)
		else:
			new_nodes = self.elements.find({'$and': [{'_id': {'$in': ids}}, query]})

		new_nodes = [n for n in new_nodes]
		new_edges = [e for e in new_edges]
		
		return new_nodes, new_edges
			

	def get_neighbors_elt(self, elt, query={}, include_original=True):

		if not elt:
			return [], []

		d_new_edges = {}
		new_edges = []
		d_ids = { elt['_id']: elt['_id'] }

		# get all links to / from the required element

		for e in self.graph.find({'src': elt['_id']}):
			d_new_edges[e['_id']] = e
			d_ids[e['dst']] = e['dst']
		for e in self.graph.find({'dst': elt['_id']}):
			d_new_edges[e['_id']] = e
			d_ids[e['src']] = e['src']
		

		# get all IDs of the new nodes that have been discovered
		ids = [d_ids[i] for i in d_ids]

		# get the new node objects
		nodes = {}
		for node in self.elements.find( {'$and' : [{ "_id" : { '$in' : ids }}, query]}):
			nodes[node['_id']] = node
		
		# get incoming links (node weight)
		destinations = [d_new_edges[e]['dst'] for e in d_new_edges]
		for n in nodes:
			nodes[n]['incoming_links'] = destinations.count(nodes[n]['_id'])

		# get nodes IDs
		nodes_id = [nodes[n]['_id'] for n in nodes]
		# get links for new nodes, in case we use them
		for e in self.graph.find({'src': { '$in': nodes_id }}):
			d_new_edges[e['_id']] = e
		for e in self.graph.find({'dst': { '$in': nodes_id }}):
			d_new_edges[e['_id']] = e

		# if not include_original:
		# 	del nodes[elt['_id']]
		
		# create arrays
		new_edges = [d_new_edges[e] for e in d_new_edges]
		nodes = [nodes[n] for n in nodes]

		# display 
		for e in nodes:
			e['fields'] = e.display_fields

		return nodes, new_edges

	#Public API operations

	def add_tag_to_key(self, apikey, tag):
		k = self.public_api.find_one({'api-key': apikey})
		if not k:
			k = self.public_api.save({'api-key': apikey, 'available-tags': [tag]})
		else:
			if tag not in k['available-tags']:
				k['available-tags'].append(tag)
				self.public_api.save(k)

	def get_tags_for_key(self, apikey):
		tags = self.public_api.find_one({'api-key': apikey})
		if not tags:
			return []
		else:
			return tags.get('available-tags', [])

