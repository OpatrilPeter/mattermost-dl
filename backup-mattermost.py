#!/usr/bin/env python3

from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7!"

from saver import Saver

import logging

from config import readConfig

logging.getLogger().setLevel(logging.DEBUG)

Saver(readConfig('config.json'))()
