from __future__ import unicode_literals
from datetime import timedelta
import logging
import os

from core.analytics import ScheduledAnalytics
from core.errors import ObservableValidationError
import geoip2.database
from geoip2.errors import AddressNotFoundError

path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "GeoLite2-City.mmdb")

reader = geoip2.database.Reader(path)


class ProcessIp(ScheduledAnalytics):

    default_values = {
        "frequency": timedelta(hours=1),
        "name": "ProcessIp",
        "description": "Extracts information from IP addresses",
    }

    ACTS_ON = 'Ip'
    EXPIRATION = None  # only run this once

    @staticmethod
    def each(ip):
        try:
            response = reader.city(ip.value)
            ip.geoip = {
                "country": response.country.iso_code,
                "city": response.city.name
            }
            ip.save()
        except ObservableValidationError:
            logging.error("An error occurred when trying to add {} to the database".format(ip.value))
        except AddressNotFoundError:
            logging.error("{} was not found in the GeoIp database".format(ip.value))
