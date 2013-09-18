from flask import Flask

from toolbox import *
import dateutil
import logging
import time
import threading
from model import Model
from datatypes.element import Hostname, Ip, Url, As


class Worker(threading.Thread):

	def __init__(self, elt, engine):
		threading.Thread.__init__(self)
		self.elt = elt
		self.engine = engine
		self.thread = None
		

	def run(self):
		
		debug_output("Started thread on %s %s" % (self.elt['type'], self.elt['value']), type='analytics')
		etype = self.elt['type']
		tags = self.elt['tags']
		
		if self.elt.get('last_analysis', None): # check that last analysis is older than 24h 
			assert (datetime.datetime.utcnow() - self.elt['last_analysis'] >= datetime.timedelta(days=1))

		new = self.elt.analytics()
		for n in new:
			saved = self.engine.save_element(n[1])
			#do the link
			self.engine.data.connect(self.elt, saved, n[0])
		
		# this will update analysis time
		self.engine.save_element(self.elt, tags)

		self.engine.progress += 1
		self.engine.websocket_lock.acquire()
		self.engine.notify_progress()
		self.engine.websocket_lock.release()
		self.engine.max_threads.release()

class Analytics:

	def __init__(self, max_threads=4):
		self.data = Model()
		#self.max_threads = threading.Semaphore(app.config['THREADS'])
		self.active = False
		self.status = "Inactive"
		self.websocket = None
		self.thread = None
		self.websocket_lock = threading.Lock()
		self.stack_lock = threading.Lock()
		self.progress = 0
		self.total = 0

		self.max_threads = threading.Semaphore(4)

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
				_ip = self.save_element(_ip)
			
				if _as and _ip:
					self.data.connect(_ip, _as, 'net_info')
			done += len(results)
			results = [r for r in self.data.elements.find({ "$and": [{'type': 'ip'}, nobgp]})[:items]]



	def find_evil(self, elt, depth=2, node_links=([],[])):
		evil_nodes = []
		evil_links = []
		

		if depth > 0:
			# get a node's neighbors
			neighbors_n, neighbors_l = self.data.get_neighbors(elt)
			for i, node in enumerate(neighbors_n):
				# for each node, find evil (recursion)
				en, el = self.find_evil(node, depth=depth-1, node_links=node_links)
				
				# if we found evil nodes, add them to the evil_nodes list
				if len(en) > 0:
					evil_nodes += [n for n in en if n not in evil_nodes] + [node]
					evil_links += [l for l in el if l not in evil_links] + [neighbors_l[i]]
		else:
			
			# if recursion ends, then search for evil neighbors
			neighbors_n, neighbors_l = self.data.get_neighbors(elt, {'tags': {'$in': ['evil']}})
			
			# return evil neighbors if found
			if len(neighbors_n) > 0:
				evil_nodes += [n for n in neighbors_n if n not in evil_nodes]
				evil_links += [l for l in neighbors_l if l not in evil_links]
				
			# if not, return nothing
			else:
				evil_nodes = []
				evil_links = []

		return evil_nodes, evil_links


	def process(self):
		if self.thread:
			if self.thread.is_alive():
				return
		self.thread = threading.Thread(None, self.process_thread, None)
		self.thread.start()
		self.thread.join() # wait for analytics to finish
		# regroup ASN analytics to make only 1 query to Cymru / Shadowserver
		self.bulk_asn()
		self.active = False
		debug_output("Finished analyzing.")
		self.notify_progress("Finished analyzing.")

	def notify_progress(self, status=None):
		if status:
			self.status = status
		status = {'active': self.active, 'status': self.status}
		if self.progress != self.total:
			status['progress'] = '%s/%s' % (self.progress, self.total)
	
		send_msg(self.websocket, status, type='analyticsstatus')

	def process_thread(self, items=1000):
		
		self.active = True

		query = { '$or': [
						{ 'last_analysis': {"$lt": datetime.datetime.utcnow() - datetime.timedelta(days=1)} },
						{ 'last_analysis': None },
					 ]
			}

		results = self.data.elements.find(query)[:items]

		# load 100 results in memory
		results = [r for r in results]
		while len(results) > 0:

		#while results.count() > 0:

			threads = []

			# status reporting
			self.total = len(results)#results.count()
			self.progress = 0
			
			for r in results:

				self.stack_lock.acquire()
				self.max_threads.acquire()
				thread = Worker(r, self)
				threads.append(thread)
				thread.start()
				self.stack_lock.release()	
				
			for t in threads:
				t.join()

			results = self.data.elements.find(
				{ '$or': [
							{ 'last_analysis': {"$lt": datetime.datetime.utcnow() - datetime.timedelta(days=1)} },
							{ 'last_analysis': None },
						]
				}
			)[:items]
			results = [r for r in results]

		

		
