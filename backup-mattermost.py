#!/usr/bin/env python3

from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7, executed with version "+str(version_info)+"!"

from common import *
from config import readConfig
from saver import Saver

from argparse import ArgumentParser

argumentParser = ArgumentParser(description="Creates a local history dump of Mattermost.")
argumentParser.add_argument('--conf','-c', help='Configuration JSON file. For allowed options see config.schema.json in source code.', type=Path, default=Path('./config.json'))
argumentParser.add_argument('--verbose','-v', help='Verbose mode.', action='store_true')
args = argumentParser.parse_args()

conffile = readConfig(args.conf)

if args.verbose:
    conffile.verboseMode = True

logging.getLogger().setLevel(logging.DEBUG if conffile.verboseMode else logging.INFO)

Saver(conffile)()
