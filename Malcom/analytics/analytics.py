from flask import Flask
import dateutil, time, threading, pickle, gc

from bson.objectid import ObjectId
from multiprocessing import Pool, Process, Queue

from Malcom.auxiliary.toolbox import *
from Malcom.model.model import Model
from Malcom.model.datatypes import Hostname, Ip, Url, As
import Malcom


class Worker(Process):

	def __init__(self, queue):
		super(Worker, self).__init__()
		self.queue = queue
		self.engine = Analytics()
		
	def run(self):
		for elt in iter (self.queue.get, None):
			elt = pickle.loads(elt)
			#print elt
			debug_output("[%s] Started work on %s %s" % (self.name, elt['type'], elt['value']), type='analytics')
			etype = elt['type']
			tags = elt['tags']

			new = elt.analytics()
			
			for n in new:
				saved = self.engine.save_element(n[1])

				#do the link
				self.engine.data.connect(elt, saved, n[0])
			
			# this will change updated time
			self.engine.save_element(elt, tags)

			self.engine.progress += 1
			self.engine.notify_progress(elt['value'])

class Analytics:

	def __init__(self):
		self.data = Model()
		self.max_workers = Malcom.config.get('MAX_WORKERS', 4)
		self.active = False
		self.status = "Inactive"
		self.websocket = None
		self.thread = None
		self.websocket_lock = threading.Lock()
		self.stack_lock = threading.Lock()
		self.progress = 0
		self.total = 0

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
					added.append(self.save_element(elt, tags))
					
		if len(added) == 1:
			return added[0]
		else:
			return added
		

	def save_element(self, element, tags=[], with_status=False):
		element.upgrade_tags(tags)
		return self.data.save(element, with_status=with_status)
		


	# graph function
	def add_artifacts(self, data, tags=[]):
		artifacts = find_artifacts(data)
		
		added = []
		for url in artifacts['urls']:
			added.append(self.save_element(url, tags))

		for hostname in artifacts['hostnames']:
			added.append(self.save_element(hostname, tags))

		for ip in artifacts['ips']:
			added.append(self.save_element(ip, tags))

		return added        


	# elements analytics

	def bulk_asn(self, items=1000):

		last_analysis = {'$or': [
									{ 'last_analysis': {"$lt": datetime.datetime.utcnow() - datetime.timedelta(days=7)} },
									{ 'last_analysis': None },
								]
						}

		nobgp = {"$or": [{'bgp': None}, last_analysis ]}

		total = self.data.elements.find({ "$and": [{'type': 'ip'}, nobgp]}).count()
		done = 0
		results = [r for r in self.data.elements.find({ "$and": [{'type': 'ip'}, nobgp]})[:items]]

		while len(results) > 0:
		
			ips = []
			debug_output("(getting ASNs for %s IPs - %s/%s done)" % (len(results), done, total), type='analytics')
			
			for r in results:
				ips.append(r)

			as_info = {}
			
			try:
				as_info = get_net_info_shadowserver(ips)
			except Exception, e:
				debug_output("Could not get AS for IPs: %s" % e)
			
			if as_info == {}:
				debug_output("as_info empty", 'error')
				return

			for ip in as_info:
				
				_as = as_info[ip]
				_ip = self.data.find_one({'value': ip})

				if not _ip:
					return

				del _as['ip']
				for key in _as:
					if key not in ['type', 'value', 'tags']:
						_ip[key] = _as[key]
				del _as['bgp']

				_as = As.from_dict(_as)

				# commit any changes to DB
				_as = self.save_element(_as)
				_ip['last_analysis'] = datetime.datetime.now()
				_ip = self.save_element(_ip)
			
				if _as and _ip:
					self.data.connect(_ip, _as, 'net_info')
			done += len(results)
			results = [r for r in self.data.elements.find({ "$and": [{'type': 'ip'}, nobgp]})[:items]]

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

		elts = self.data.elements.find({'$and': final_query})
		
		nodes, edges = self.data.get_neighbors_id(elts, include_original=include_original)
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

	def multi_graph_find(self, query, graph_query, depth=2):
		total_nodes = {}
		total_edges = {}

		for key in query:

			for value in query[key]:
				
				if key == '_id': value = ObjectId(value)

				elt = self.data.elements.find_one({key: value})
				
				nodes, edges = self.single_graph_find(elt, graph_query, depth)
				
				for n in nodes:
					total_nodes[n['_id']] = n
				for e in edges:
					total_edges[e['_id']] = e
			
		total_nodes = [total_nodes[n] for n in total_nodes]	
		total_edges = [total_edges[e] for e in total_edges]

		data = {'nodes':total_nodes, 'edges': total_edges }

		return data


	def single_graph_find(self, elt, query, depth=2):
		chosen_nodes = []
		chosen_links = []
		
		if depth > 0:
			# get a node's neighbors
			neighbors_n, neighbors_l = self.data.get_neighbors_elt(elt, include_original=False)
			
			for i, node in enumerate(neighbors_n):
				# for each node, find evil (recursion)
				en, el = self.single_graph_find(node, query, depth=depth-1)
				
				# if we found evil nodes, add them to the chosen_nodes list
				if len(en) > 0:
					chosen_nodes += [n for n in en if n not in chosen_nodes] + [node]
					chosen_links += [l for l in el if l not in chosen_links] + [neighbors_l[i]]
		else:
			
			# if recursion ends, then search for evil neighbors
			neighbors_n, neighbors_l = self.data.get_neighbors_elt(elt, {query['key']: {'$in': [query['value']]}}, include_original=False)
			
			# return evil neighbors if found
			if len(neighbors_n) > 0:
				chosen_nodes += [n for n in neighbors_n if n not in chosen_nodes]
				chosen_links += [l for l in neighbors_l if l not in chosen_links]
				
			# if not, return nothing
			else:
				chosen_nodes = []
				chosen_links = []

		return chosen_nodes, chosen_links


	def process(self):
		if self.thread:
			if self.thread.is_alive():
				return

		self.thread = threading.Thread(None, self.process_thread, None)

		then = time.datetime.utcnow()
		self.thread.start()
		self.thread.join() # wait for analytics to finish
		now = time.datetime.utcnow()

		# regroup ASN analytics to make only 1 query to Cymru / Shadowserver
		self.bulk_asn()
		self.active = False
		debug_output("Finished analyzing (run time: %s)." % str(now-then))
		self.notify_progress("Finished analyzing.")

	def notify_progress(self, msg=None):

		status = {'active': self.active, 'msg': msg}
		status['progress'] = '%s' % (self.progress)
		send_msg(self.websocket, status, type='analyticsstatus')
		

	def process_thread(self):

		self.active = True
		
		i = 0
		total = 1
		
		while total > 0:

			query = {'next_analysis' : {'$lt': datetime.datetime.utcnow()}}
			total = self.data.elements.find(query).count()
			results = self.data.elements.find(query)
			if total == 0: break # exit loop if there are no new elements to analyze

			# build process Queue (1000 elements max) and workers
			elements_queue = Queue(1000)
			workers = []

			for i in range(Malcom.config['MAX_WORKERS']):
				w = Worker(elements_queue)
				workers.append(w)
				w.start()

			# add elements to Queue			
			for elt in results:
				elements_queue.put(pickle.dumps(elt))

			# Worker cleanup
			for i in range(Malcom.config['MAX_WORKERS']):
				elements_queue.put(None)
			elements_queue.close()

			# Wait for workers to finish
			for w in workers:
				w.join()

			workers[:] = []

		self.active = False

			
			








