#!/usr/bin/env python3

from argparse import ArgumentError, ArgumentParser, Namespace as ArgNamespace
from os import environ
from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7, executed with version "+str(version_info)+"!"

from .common import *
from .config import ConfigFile, ConfigurationError, LogVerbosity
from .saver import Saver


def setupLogging(verbosity: LogVerbosity):
    # We assume this already happened, note multiple operations are NOP
    logging.basicConfig()
    rootLogger = logging.getLogger()
    if verbosity == LogVerbosity.Verbose:
        rootLogger.setLevel(logging.DEBUG)
        rootLogger.handlers[0].setFormatter(
            logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:%(filename)s:%(lineno)s: %(message)s')
        )
    elif verbosity == LogVerbosity.Normal:
        rootLogger.setLevel(logging.INFO)
        rootLogger.handlers[0].setFormatter(
            logging.Formatter('%(message)s')
        )
    else:
        assert verbosity == LogVerbosity.ProblemsOnly
        rootLogger.setLevel(logging.WARNING)
        rootLogger.handlers[0].setFormatter(
            logging.Formatter('%(message)s')
        )

def parseArgs() -> ArgNamespace:
    argumentParser = ArgumentParser(description="Creates a local history dump of Mattermost.")
    argumentParser.add_argument('--conf','-c', help='Configuration JSON file. For allowed options see config.schema.json in source code. If ommited, standard locations are checked.', type=Path)
    verbosity = argumentParser.add_mutually_exclusive_group()
    verbosity.add_argument('--verbose', '-v', help='Verbose mode.', const=LogVerbosity.Verbose,
                           action='store_const', default=LogVerbosity.Normal, dest='verbosity')
    verbosity.add_argument(
        '--quiet', '-q', help='Quiet mode. Removes outputs if no problems occur.',  action='store_const', const=LogVerbosity.ProblemsOnly, dest='verbosity')
    args = argumentParser.parse_args()
    return args

def selectConfigFile() -> Optional[Path]:
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
        confPath = Path(os.environ['HOME'])/'.config/mattermost-dl.json'
        if confPath.is_file():
            return confPath
        locations.append(confPath)

    logging.error(f'No configuration file found, searched locations follow: {locations}')
    return None

def main():
    args = parseArgs()
    setupLogging(args.verbosity)

    if args.conf is None:
        args.conf = selectConfigFile()
        if args.conf is None:
            sys.exit(1)

    try:
        conffile = ConfigFile.fromFile(args.conf)
        if args.verbosity != LogVerbosity.Normal:
            conffile.verbosity = args.verbosity
    except ConfigurationError as err:
        logging.fatal(f'Configuration file {err.filename} couldn\'t be loaded.')
        sys.exit(1)
    setupLogging(conffile.verbosity)

    Saver(conffile)()
