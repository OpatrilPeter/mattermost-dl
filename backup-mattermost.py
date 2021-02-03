#!/usr/bin/env python3

from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7, executed with version "+str(version_info)+"!"

from argparse import ArgumentParser
import logging
from pathlib import Path

from config import readConfig
from saver import Saver

argumentParser = ArgumentParser(description="Creates a local history dump of Mattermost.")
argumentParser.add_argument('--conf','-c', help='Configuration JSON file. For allowed options see config.schema.json in source code.', type=Path, default=Path('./config.json'))
argumentParser.add_argument('--verbose','-v', help='Verbose mode.', action='store_true')
args = argumentParser.parse_args()

logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

Saver(readConfig(args.conf))()
