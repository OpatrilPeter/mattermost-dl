#!/usr/bin/env python3

from argparse import ArgumentError, ArgumentParser, Namespace as ArgNamespace
from os import environ
from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7, executed with version "+str(version_info)+"!"

from .common import *
from .config import ConfigFile, ConfigurationError
from .saver import Saver


def setupLogging(verboseMode: bool):
    # We assume this already happened, note multiple operations are NOP
    logging.basicConfig()
    rootLogger = logging.getLogger()
    if verboseMode:
        rootLogger.setLevel(logging.DEBUG)
        rootLogger.handlers[0].setFormatter(
            logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:%(filename)s:%(lineno)s: %(message)s')
        )
    else:
        rootLogger.setLevel(logging.INFO)
        rootLogger.handlers[0].setFormatter(
            logging.Formatter('%(message)s')
        )

def parseArgs() -> ArgNamespace:
    argumentParser = ArgumentParser(description="Creates a local history dump of Mattermost.")
    argumentParser.add_argument('--conf','-c', help='Configuration JSON file. For allowed options see config.schema.json in source code. If ommited, standard locations are checked.', type=Path)
    argumentParser.add_argument('--verbose','-v', help='Verbose mode.', action='store_true')
    args = argumentParser.parse_args()
    return args

def selectConfigFile() -> Path:
    locations = []
    confPath = Path('./mattermost-dl.json')
    if confPath.is_file():
        return confPath
    locations.append(confPath)
    if 'XDG_CONFIG_HOME' in os.environ:
        confPath = Path(os.environ['XDG_CONFIG_HOME'])/'mattermost-dl.json'
        if confPath.is_file():
            return confPath
        locations.append(confPath)
    if 'HOME' in os.environ:
        confPath = Path(os.environ['HOME'])/'.config/.mattermost-dl.json'
        if confPath.is_file():
            return confPath
        locations.append(confPath)

    logging.error(f'No configuration file found, searched locations follow: {locations}')
    raise ConfigurationError

def main():
    args = parseArgs()
    setupLogging(verboseMode=args.verbose)

    if args.conf is None:
        args.conf = selectConfigFile()

    conffile = ConfigFile()
    conffile.readFile(args.conf)
    conffile.verboseMode = any((conffile.verboseMode, args.verbose))
    setupLogging(verboseMode=conffile.verboseMode)

    Saver(conffile)()
