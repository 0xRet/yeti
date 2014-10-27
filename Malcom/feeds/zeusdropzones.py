import urllib2
import datetime, re
from lxml import etree
import Malcom.auxiliary.toolbox as toolbox
from bson.objectid import ObjectId
from bson.json_util import dumps
from Malcom.model.datatypes import Evil, Url
from feed import Feed



class ZeusTrackerDropzones(Feed):

	def __init__(self, name):
		super(ZeusTrackerDropzones, self).__init__(name, run_every="1h")
		self.name = "ZeusTrackerDropzones"
		self.source = "https://zeustracker.abuse.ch/monitor.php?urlfeed=dropzones"
		self.description = "This feed shows the latest 50 ZeuS dropzone URLs."
		
	def update(self):
		self.update_xml('item', ["title", "link", "description", "guid"])


	def analyze(self, dict):
			
		# We create an Evil object. Evil objects are what Malcom uses
		# to store anything it considers evil. Malware, spam sources, etc.
		# Remember that you can create your own datatypes, if need be.

		evil = Evil()

		# We start populating the Evil() object's attributes with
		# information from the dict we parsed earlier
		
		# description
		evil['description'] = dict['description'] 

		# status
		if dict['description'].find("offline") != -1:
			evil['status'] = "offline"
		else:
			evil['status'] = "online"

		# md5 
		md5 = re.search("MD5 hash: (?P<md5>[0-9a-f]{32,32})",dict['description'])
		if md5 != None:
			evil['md5'] = md5.group('md5')
		else:
			evil['md5'] = "No MD5"
		
		# linkback
		evil['guid'] = dict['guid']

		# tags
		evil['tags'] += ['zeus', 'malware', 'ZeusTrackerDropzones']

		# Create an URL element
		url = Url(toolbox.find_urls(dict['description'])[0], ['evil', 'ZeusTrackerDropzones'])

		# This is important. Values have to be unique, since it's this way that
		# Malcom will identify them in the database.
		# This is probably not the best way, but it will do for now.

		evil['value'] = "ZeuS Dropzone"
		if md5:
			evil['value'] += " (MD5: %s)" % evil['md5']
		else:
			evil['value'] += " (URL: %s)" % url['value']

		# Save elements to DB. The status field will contain information on 
		# whether this element already existed in the DB.

		return url, evil
