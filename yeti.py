#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import time

from core.web import webapp

logging.basicConfig(format='%(levelname)s:%(module)s:%(message)s', level=logging.INFO)

if __name__ == '__main__':
    webapp.run()
