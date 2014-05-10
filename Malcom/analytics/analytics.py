from flask import Flask
import Malcom
import dateutil, time, threading, pickle, gc, datetime
from bson.objectid import ObjectId
from multiprocessing import Process, Queue
from Malcom.auxiliary.toolbox import *
from Malcom.model.model import Model
from Malcom.model.datatypes import Hostname, Ip, Url, As

# from gevent.queue import Queue
from gevent import Greenlet


class Worker(Process):

	def __init__(self, queue):
		super(Worker, self).__init__()
		self.queue = queue
		self.engine = Analytics()
		self.work = False
		
	def run(self):
		self.work = True
		try:
			while self.work:
				print "Worker working"
			#for elt in iter(self.queue.get, None):
				print "Worker queue %s" % self.queue
				elt = self.queue.get()
				if elt == None:
					break
				elt = pickle.loads(elt)

				debug_output("[%s] Started work on %s %s. Queue size: %s" % ("AnonGreenlet", elt['type'], elt['value'], self.queue.qsize()), type='analytics')
				etype = elt['type']
				tags = elt['tags']

				new = elt.analytics()

				last_connect = elt.get('date_updated', datetime.datetime.utcnow())
				
				for n in new:
					saved = self.engine.save_element(n[1])
					# do the link
					conn = self.engine.data.connect(elt, saved, n[0])
					first_seen = conn['first_seen']
					last_seen = conn['last_seen']

					# update date updated if there's a new connection
					if first_seen > last_connect:
						last_connect = first_seen

				# this will change updated time
				elt['date_updated'] = last_connect
				self.engine.save_element(elt, tags)

				self.engine.progress += 1
				self.engine.notify_progress(elt['value'])
			return

		except Exception, e:
			debug_output("An error occured in %s: %s" % ("AnonGreenlet", e), type="error")
		except KeyboardInterrupt, e:
			pass

	def stop(self):
		self.work = False


class Analytics(Greenlet):

	def __init__(self):
		Greenlet.__init__(self)
		self.data = Model()
		self.max_workers = Malcom.config.get('MAX_WORKERS', 4)
		self.active = False
		self.active_lock = threading.Lock()
		self.status = "Inactive"
		self.websocket = None
		self.thread = None
		self.websocket_lock = threading.Lock()
		self.stack_lock = threading.Lock()
		self.progress = 0
		self.total = 0
		self.workers = []
		self.elements_queue = None
		self.once = False


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
				_ip['last_analysis'] = datetime.datetime.utcnow()
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

	def run(self):
		self.run_analysis = True
		while self.run_analysis:
			debug_output("Launching analytics")
			time.sleep(1) # run a new thread every period seconds
			self.active_lock.acquire()
			if self.run_analysis:
				self.process(10000)
			self.active_lock.release()
			if self.once: self.run_analysis = False; self.once = False

	def stop(self):
		self.run_analysis = False
		for w in self.workers:
			try:
				w.stop()
			except Exception, e:
				pass

		self.join()

		try:
			while True:
				self.elements_queue.get(False)
		except Exception, e:
			pass
			

	def process(self, batch_size=10000):
		if self.thread:
			if self.thread.is_alive():
				return

		then = datetime.datetime.utcnow()
		
		self.active = True
		self.workers = []
		self.work_done = False

		query = {'next_analysis' : {'$lt': datetime.datetime.utcnow()}}
		results = [r for r in self.data.elements.find(query)[:batch_size]]
		total_elts = 0

		if len(results) > 0:

			# build process Queue (10000 elements max)
			self.elements_queue = Queue(batch_size)

			# start workers
			workers = []
			for i in range(Malcom.config['MAX_WORKERS']):
				w = Worker(self.elements_queue)
				w.start()
				workers.append(w)

			self.workers = workers
			
			# add elements to Queue
			print 'adding elts (from query %s in queue %s)' % (query, self.elements_queue)
			for elt in results:
				self.elements_queue.put(pickle.dumps(elt))
				print "just put %s" %elt
				total_elts += 1
				work_done = True
			print 'done'

			for i in range(Malcom.config['MAX_WORKERS']):
				self.elements_queue.put(None)
			print "none added"

			for w in self.workers:
				w.join()	
			print "waiting for join"
			# regroup ASN analytics to make only 1 query to Cymru / Shadowserver
			self.bulk_asn()
		
		self.active = False

		now = datetime.datetime.utcnow()
		
		msg = "Analyzed %s elements (run time: %s)" % (total_elts, str(now-then)) 
		debug_output(msg)
		self.notify_progress(msg)

		

	def notify_progress(self, msg=None):

		status = {'active': self.active, 'msg': msg}
		status['progress'] = '%s' % (self.progress)
		send_msg(self.websocket, status, type='analyticsstatus')