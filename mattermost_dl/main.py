#!/usr/bin/env python3

from argparse import ArgumentError, ArgumentParser, Namespace as ArgNamespace
from os import environ
from sys import version_info
assert version_info >= (3, 7), "Required at least python 3.7, executed with version "+str(version_info)+"!"

from .common import *
from .config import ConfigFile, ConfigurationError, LogVerbosity
from .saver import Saver, SavingFailed


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

    quickConf = argumentParser.add_argument_group()
    quickConf.add_argument(
        '--server', '-s', help="Mattermost server instance, like config setting 'connection.hostname'.", dest='hostname')
    quickConf.add_argument(
        '--user', '-u', help="Mattermost username, like config setting 'connection.username'.", dest='username')
    quickConf.add_argument('--pass', '-p', help="Password to given account, like config setting 'connection.password'.\n"
        + 'Not recommended to be set from command line for security reasons - prefer access tokens or at least passing through config file or env variable instead.',
        dest='password')
    quickConf.add_argument(
        '--token', '-t', help="Mattermost access token, like config setting 'connection.token'.")

    args = argumentParser.parse_args()
    return args

def selectConfigFile() -> Optional[Path]:
    def suffixes():
        yield 'toml'
        yield 'json'
    locations = []
    for confPath in (Path(f'./mattermost-dl.{sfx}') for sfx in suffixes()):
        if confPath.is_file():
            return confPath
        locations.append(confPath)
    if 'XDG_CONFIG_HOME' in os.environ:
        for confPath in (Path(os.environ['XDG_CONFIG_HOME'])/f'mattermost-dl.{sfx}' for sfx in suffixes()):
            if confPath.is_file():
                return confPath
            locations.append(confPath)
    if 'HOME' in os.environ:
        for confPath in (Path(os.environ['HOME'])/f'mattermost-dl.{sfx}' for sfx in suffixes()):
            if confPath.is_file():
                return confPath
            locations.append(confPath)

    logging.warning(f'No configuration file found, searched locations follow: {locations}')
    return None

def main():
    args = parseArgs()
    setupLogging(args.verbosity)

    if args.conf is None:
        args.conf = selectConfigFile()

    try:
        if args.conf is not None:
            logging.debug(f'Loading configuration file {args.conf}.')
            conffile = ConfigFile.fromFile(args.conf)
        else:
            conffile = ConfigFile()
        conffile.updateFromEnv()
        conffile.updateFromArgs(args)
        conffile.validate()
    except ConfigurationError as err:
        if args.conf is not None:
            logging.fatal(f'Configuration file {args.conf} failed to be be loaded.')
        else:
            logging.fatal(f'Configuration failed to be be loaded.')
        sys.exit(1)
    setupLogging(conffile.verbosity)

    try:
        Saver(conffile)()
    except SavingFailed as err:
        logging.fatal(err)
        if conffile.verbosity == LogVerbosity.Verbose:
            text = ''
            while hasattr(err, '__cause__'):
                err = err.__cause__
                if err is None:
                    break
                text += f'Caused by: {err}'
            logging.fatal(text)

        sys.exit(1)
    except:
        logging.info("-----\n")
        logging.fatal("Application encountered unexpected situation and will terminate, sorry for inconvenience.\nFollowing information can be useful for developers:")
        raise
