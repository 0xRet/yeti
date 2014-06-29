# from gevent import monkey; monkey.patch_socket()#subprocess()#socket(dns=False); monkey.patch_time();

import dateutil
import threading
import os

from pymongo import MongoClient
from pymongo.son_manipulator import SONManipulator
import pymongo.errors
import pygeoip
from bson.objectid import ObjectId

from Malcom.auxiliary.toolbox import *
from Malcom.model.datatypes import Hostname, Url, Ip, As, Evil, DataTypes


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
		self.feeds = self._db.feeds
		self.history = self._db.history
		self.public_api = self._db.public_api

		# create indexes
		self.rebuild_indexes()

		# locks
		self.db_lock = threading.Lock()

	def rebuild_indexes(self):
		# create indexes
		self.elements.ensure_index([('date_created', -1), ('value', 1)])
		self.elements.ensure_index('value', unique=True)
		self.elements.ensure_index('tags')
		self.graph.ensure_index([('src', 1), ('dst', 1)])
		self.graph.ensure_index('src')
		self.graph.ensure_index('dst')

	def stats(self):
		stats = "DB loaded with %s elements\n" % self._db.elements.count()
		stats += "Graph has %s edges" % self._db.graph.count()
		return stats


	# =============== link operations =================

	def connect(self, src, dst, attribs="", commit=True):
		if not src or not dst:
			return None

		while True:
			try:
				conn = self.graph.find_one({ 'src': ObjectId(src._id), 'dst': ObjectId(dst._id) })
				break
			except Exception, e:
				debug_output("Could not find connection from %s: %s" %(ObjectId(src._id), e), 'error')
		
		
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
			while True:
				try:
					self.graph.save(conn)
					break
				except Exception, e:
					debug_output("Could not save %s: %s" %(conn, e), 'error')

		return conn

	def get_destinations(self, elt):
		return [e['value'] for e in self.graph.find({'src': elt['_id']}, 'value')]





	# =========== elements operations ============

	def find(self, query={}):
		return self.elements.find(query)

	def get(self, **kwargs):
		while True:
			try:
				return self.elements.find_one(kwargs)
			except Exception, e:
				pass
		
	def find_one(self, oid):
		return self.elements.find_one(oid)

	def find_neighbors(self, query, include_original=True):
		
		total_nodes = {}
		total_edges = {}
		final_query = []

		for key in query:

			if key == '_id': 
				values = [ObjectId(v) for v in query[key]]
			else:
				values = [v for v in query[key]]

			final_query.append({key: {'$in': values}})

		elts = self.elements.find({'$and': final_query})
		
		nodes, edges = self.get_neighbors_id(elts, include_original=include_original)
		for n in nodes:
			total_nodes[n['_id']] = n
		for e in edges:
			total_edges[e['_id']] = e
			
		total_nodes = [total_nodes[n] for n in total_nodes]	
		total_edges = [total_edges[e] for e in total_edges]

		# display 
		for e in total_nodes:
			e['fields'] = e.display_fields

		data = {'nodes':total_nodes, 'edges': total_edges }

		return data

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
		
		# create arrays
		new_edges = [d_new_edges[e] for e in d_new_edges]

		if not include_original:
			nodes = [nodes[n] for n in nodes if nodes[n]['value'] != elt['value']]
		else:
			nodes = [nodes[n] for n in nodes]

		# display 
		for e in nodes:
			e['fields'] = e.display_fields

		return nodes, new_edges

	def single_graph_find(self, elt, query, depth=2):
		chosen_nodes = []
		chosen_links = []
		
		if depth > 0:
			# get a node's neighbors
			neighbors_n, neighbors_l = self.get_neighbors_elt(elt, include_original=False)
			
			for i, node in enumerate(neighbors_n):
				# for each node, find evil (recursion)
				en, el = self.single_graph_find(node, query, depth=depth-1)
				
				# if we found evil nodes, add them to the chosen_nodes list
				if len(en) > 0:
					chosen_nodes += [n for n in en if n not in chosen_nodes] + [node]
					chosen_links += [l for l in el if l not in chosen_links] + [neighbors_l[i]]
		else:
			
			# if recursion ends, then search for evil neighbors
			neighbors_n, neighbors_l = self.get_neighbors_elt(elt, {query['key']: {'$in': [query['value']]}}, include_original=False)
			
			# return evil neighbors if found
			if len(neighbors_n) > 0:
				chosen_nodes += [n for n in neighbors_n if n not in chosen_nodes]
				chosen_links += [l for l in neighbors_l if l not in chosen_links]
				
			# if not, return nothing
			else:
				chosen_nodes = []
				chosen_links = []

		return chosen_nodes, chosen_links

	def multi_graph_find(self, query, graph_query, depth=2):
		total_nodes = {}
		total_edges = {}

		for key in query:

			for value in query[key]:
				
				if key == '_id': value = ObjectId(value)

				elt = self.elements.find_one({key: value})
				
				nodes, edges = self.single_graph_find(elt, graph_query, depth)
				
				for n in nodes:
					total_nodes[n['_id']] = n
				for e in edges:
					total_edges[e['_id']] = e
			
		total_nodes = [total_nodes[n] for n in total_nodes]	
		total_edges = [total_edges[e] for e in total_edges]

		data = {'nodes': total_nodes, 'edges': total_edges }

		return data

	# ---- update & save operations ----

	def bulk_insert(self, elements):
		return self.elements.insert(elements)


	def save(self, element, with_status=False):
		if None in [element['value'], element['type']]:
			raise ValueError("Invalid value for element: %s" % element)

		with self.db_lock:
			# critical section starts here
			tags = []
			if 'tags' in element:
				tags = element['tags']
				del element['tags'] 	# so tags in the db do not get overwritten

			if '_id' in element:
				del element['_id']
			
			# check if existing
			while True:
				try:
					_element = self.elements.find_one({'value': element['value']})
					break
				except Exception, e:
					debug_output("Could not fetch %s: %s" %(element['value'], e), 'error')
			
			if _element != None:
				for key in element:
					if key=='tags': continue
					_element[key] = element[key]
				if key not in _element:
					_element[key] = {}
				_element['tags'] = list(set(_element['tags'] + tags))
				element = _element
				new = False
			else:
				new = True
				element['tags'] = tags

			if not new:
				debug_output("(updated %s %s)" % (element.type, element.value), type='model')
				assert element.get('date_created', None) != None
			else:
				debug_output("(added %s %s)" % (element.type, element.value), type='model')
				element['date_created'] = datetime.datetime.utcnow()
				element['next_analysis'] = datetime.datetime.utcnow()
			
			while True:
				try:
					self.elements.save(element)
					break
				except pymongo.errors.DuplicateKeyError as e:
					break
				except Exception as e:
					debug_output("Could not save %s: %s (%s)" % (element, e, type(e)), 'error')

			# end of critical section
			
		assert element['date_created'] != None

		if not with_status:
			return element
		else:
			return element, new

	def add_text(self, text, tags=[]):
		added = []
		for t in text:
			elt = None
			if t.strip() != "":
				if is_url(t):
					elt = Url(is_url(t), [])
				elif is_hostname(t):
					elt = Hostname(is_hostname(t), [])
				elif is_ip(t):
					elt = Ip(is_ip(t), [])
				if elt:
					elt['tags'] = tags
					added.append(self.save(elt))
					
		if len(added) == 1:
			return added[0]
		else:
			return added
		

	# ---- remove operations ----

	def remove_element(self, element):
		self.remove_connections(element['_id'])
		return self.elements.remove({'_id' : element['_id']})
		

	def remove_by_id(self, element_id):
		self.remove_connections(ObjectId(element_id))
		return self.elements.remove({'_id' : ObjectId(element_id)})

	def remove_by_value(self, element_value):
		e = self.elements.find({'value': element_value})
		self.remove_connections(e['_id'])
		return self.elements.remove({'value' : element_value})

	def remove_connections(self, element_id):
		self.graph.remove({'$or': [{'src': element_id}, {'dst': element_id}] })


	# ============= clear / list db ================

	def clear_db(self):
		for c in self._db.collection_names():
			if c != "system.indexes":
				self._db[c].drop()
	
	def list_db(self):
		for e in self.elements.find():
			debug_output(e)





	














	# ============ sniffer operations ==============

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

	def del_sniffer_session(self, session_name, sniffer_dir):

		session = self.sniffer_sessions.find_one({'name': session_name})
			
		filename = session['name'] + ".pcap"
				
		try:
			os.remove(sniffer_dir + "/" + filename)
		except Exception, e:
			print e

		self.sniffer_sessions.remove({'name': session_name})

		return True

	def get_sniffer_sessions(self):
		return [s for s in self.sniffer_sessions.find()]


	






	# =========== Feed operations =====================

	def add_feed(self, feed):
		elts = feed.get_info()
	  
		for e in elts:
			self.malware_add(e,e['tags'])

	def feed_last_run(self, feed_name):
		self.feeds.update({'name': feed_name}, {'$set': {'last_run': datetime.datetime.utcnow()} }, upsert=True)

	def get_feed_progress(self, feed_names):
		feeds = [f for f in self.feeds.find({'name': {'$in': feed_names}})]
		return feeds

	

	# ============ Public API operations ===============

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

