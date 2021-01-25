#!/usr/bin/env python3

from saver import Saver
from sys import version_info

assert (version_info.major > 3 or version_info.major == 3 and version_info.minor >= 7), "Required at least python 3.7!"

import logging

from config import readConfig

logging.getLogger().setLevel(logging.DEBUG)

Saver(readConfig('config.json'))()
