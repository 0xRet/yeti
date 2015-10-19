from mongoengine import *

connect('malcom-v2')

from core.datatypes.tag import Tag
from core.datatypes.element import Element
from core.datatypes.link import LinkHistory, Link
from core.datatypes.ip import Ip
from core.datatypes.url import Url
from core.datatypes.hostname import Hostname
from core.datatypes.hash import Hash
