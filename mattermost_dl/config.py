'''
    Defines configuration options of the program
    and handles their loading from JSON
'''

from .common import *
from .bo import EntityLocator, Id, Time
from . import jsonvalidation
from .jsonvalidation import ValidationErrors, validate as validateJson, formatValidationErrors
from . import progress
from .progress import ProgressSettings
from .recovery_actions import RBackup, RDelete, RReuse, RSkipDownload

import argparse
from collections.abc import Iterable
from copy import deepcopy
import json
from json.decoder import JSONDecodeError
import jsonschema
# HACK: Pyright linter doesn't recognize special meaning of ClassVar from .common in dataclasses
from typing import ClassVar


class LogVerbosity(Enum):
    ProblemsOnly = enumerator()
    Normal = enumerator()
    Verbose = enumerator()

class ConfigurationError(Exception):
    '''Invalid or missing configuration.'''
    def __init__(self, filename: Optional[Path] = None, *args):
        super().__init__(*args)
        self.filename = filename

class OrderDirection(Enum):
    Asc = 0
    Desc = 1

@dataclass
class ChannelOptions:
    postsAfterId: Optional[Id] = None
    postsBeforeId: Optional[Id] = None
    postsBeforeTime: Optional[Time] = None
    postsAfterTime: Optional[Time] = None
    postLimit: int = -1 # 0 is allowed and fetches only channel metadata
    postSessionLimit: int = -1 # 0 is allowed and fetches only channel metadata
    onExistingCompatibleArchive: Union[RBackup, RDelete, RReuse, RSkipDownload] = RReuse()
    onExistingIncompatibleArchive: Union[RBackup, RDelete, RSkipDownload] = RBackup()
    downloadTimeDirection: OrderDirection = OrderDirection.Asc
    downloadAttachments: bool = False
    downloadAttachmentTypes: List[str] = dataclassfield(default_factory=list)
    downloadAttachmentSizeLimit: int = 0 # 0 means no limit
    emojiMetadata: bool = False
    downloadEmoji: bool = False
    downloadAvatars: bool = False

    def update(self, info: dict):
        x: Any

        self.postsBeforeId = info.get('beforePost', self.postsBeforeId)
        self.postsAfterId = info.get('afterPost', self.postsAfterId)

        x = info.get('beforeTime', None)
        if x is not None:
            self.postsBeforeTime = Time(x)
        x = info.get('afterTime', None)
        if x is not None:
            self.postsAfterTime = Time(x)

        self.postLimit = info.get('maximumPostCount', self.postLimit)
        self.postSessionLimit = info.get('sessionPostLimit', self.postSessionLimit)

        x = info.get('onExistingCompatible', None)
        if x is not None:
            self.onExistingCompatibleArchive = {
                'backup': RBackup(),
                'delete': RDelete(),
                'skip': RSkipDownload(),
                'update': RReuse(),
            }.get(x, self.onExistingCompatibleArchive)
        x = info.get('onExistingIncompatible', None)
        if x is not None:
            self.onExistingIncompatibleArchive = {
                'backup': RBackup(),
                'delete': RDelete(),
                'skip': RSkipDownload(),
            }.get(x, self.onExistingIncompatibleArchive)

        x = info.get('downloadFromOldest', None)
        if x is not None:
            self.downloadTimeDirection = OrderDirection.Asc if x else OrderDirection.Desc
        if 'attachments' in info:
            attachments = info['attachments']
            self.downloadAttachments = attachments.get('download', self.downloadAttachments)
            self.downloadAttachmentSizeLimit = attachments.get('maxSize', self.downloadAttachmentSizeLimit)
            self.downloadAttachmentTypes = attachments.get('allowedMimeTypes', self.downloadAttachmentTypes)
        if 'emojis' in info:
            emojis = info['emojis']
            self.downloadEmoji = emojis.get('download', self.downloadEmoji)
            self.emojiMetadata = emojis.get('metadata', self.emojiMetadata)
        if 'avatars' in info and 'download' in info['avatars']:
            self.downloadAvatars = info['avatars']['download']

        return self

@dataclass(init=False)
class ChannelSpec:
    locator: EntityLocator
    opts: ChannelOptions = ChannelOptions()

    def __init__(self, info: dict, defaultOpts: ChannelOptions):
        self.locator = EntityLocator(info)

        self.opts = deepcopy(defaultOpts).update(info)

@dataclass(init=False)
class GroupChannelSpec:
    locator: Union[Id, FrozenSet[EntityLocator]]
    opts: ChannelOptions = ChannelOptions()

    def __init__(self, info: dict, defaultOpts: ChannelOptions):
        groupLocator = info['group']
        if isinstance(groupLocator, str):
            self.locator = cast(Id, groupLocator)
        else:
            assert isinstance(groupLocator, list)
            self.locator = frozenset(EntityLocator(chan) for chan in groupLocator)

        self.opts = deepcopy(defaultOpts).update(info)

    def __hash__(self) -> int:
        return hash(self.locator)

@dataclass
class TeamSpec:
    locator: EntityLocator
    miscPrivateChannels: bool = True
    explicitPrivateChannels: List[ChannelSpec] = dataclassfield(default_factory=list)
    privateChannelDefaults: ChannelOptions = ChannelOptions()
    miscPublicChannels: bool = True
    explicitPublicChannels: List[ChannelSpec] = dataclassfield(default_factory=list)
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    @staticmethod
    def fromConfig(info: dict, globalPrivateDefaults: ChannelOptions, globalPublicDefaults: ChannelOptions) -> 'TeamSpec':
        self = TeamSpec(locator=EntityLocator(info['team']))

        if 'defaultChannelOptions' in info:
            channelDefaultDict = info['defaultChannelOptions']
        else:
            channelDefaultDict = None
        if channelDefaultDict or 'privateChannelOptions' in info:
            self.privateChannelDefaults = deepcopy(globalPrivateDefaults)
            if channelDefaultDict:
                self.privateChannelDefaults = self.privateChannelDefaults.update(channelDefaultDict)
            if 'privateChannelOptions' in info:
                self.privateChannelDefaults = self.privateChannelDefaults.update(info['privateChannelOptions'])
        else:
            self.privateChannelDefaults = globalPrivateDefaults
        if channelDefaultDict or 'publicChannelOptions' in info:
            self.publicChannelDefaults = deepcopy(globalPublicDefaults)
            if channelDefaultDict:
                self.publicChannelDefaults = self.publicChannelDefaults.update(channelDefaultDict)
            if 'publicChannelOptions' in info:
                self.publicChannelDefaults = self.publicChannelDefaults.update(info['publicChannelOptions'])
        else:
            self.publicChannelDefaults = globalPublicDefaults

        if 'downloadPrivateChannels' in info:
            self.miscPrivateChannels = info['downloadPrivateChannels']
        if 'privateChannels' in info:
            assert isinstance(info['privateChannels'], list)
            self.explicitPrivateChannels = [ChannelSpec(chan, self.privateChannelDefaults) for chan in info['privateChannels']]
        if 'downloadPublicChannels' in info:
            self.miscPublicChannels = info['downloadPublicChannels']
        if 'publicChannels' in info:
            assert isinstance(info['publicChannels'], list)
            self.explicitPublicChannels = [ChannelSpec(chan, self.publicChannelDefaults) for chan in info['publicChannels']]

        return self

@dataclass
class ConfigFile:
    _schemaValidator: ClassVar[jsonschema.Draft7Validator]

    hostname: str = ''
    username: str = ''
    password: str = ''
    token: str = ''

    throttlingLoopDelay: int = 0
    miscTeams: bool = True
    explicitTeams: List[TeamSpec] = dataclassfield(default_factory=list)
    miscDirectChannels: bool = True
    explicitUsers: List[ChannelSpec] = dataclassfield(default_factory=list)
    miscGroupChannels: bool = True
    explicitGroups: List[GroupChannelSpec] = dataclassfield(default_factory=list)
    channelDefaults: ChannelOptions = ChannelOptions()
    directChannelDefaults: ChannelOptions = ChannelOptions()
    groupChannelDefaults: ChannelOptions = ChannelOptions()
    privateChannelDefaults: ChannelOptions = ChannelOptions()
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    outputDirectory: Path = Path()
    verboseHumanFriendlyPosts: bool = False
    downloadAllEmojis: bool = False

    verbosity: LogVerbosity = LogVerbosity.Normal
    reportProgress: ProgressSettings = ProgressSettings(mode=progress.VisualizationMode.AnsiEscapes)
    progressInterval: int = 500

    @staticmethod
    def loadSchemaValidator() -> jsonschema.Draft7Validator:
        with open(sourceDirectory(__file__)/'config.schema.json') as schemaFile:
            return jsonschema.Draft7Validator(json.load(schemaFile))

    @staticmethod
    def loadFile(filename: Path) -> Any:
        '''
            Loads Json or supported Json-like structured data from file.
            Raises ConfigurationError on failure
        '''
        ftype = '.json'
        if filename.suffix in ('.json', '.toml'):
            ftype = filename.suffix
        else:
            if filename.suffix == '':
                logging.warning('Missing configuration suffix, assuming json.')
            else:
                logging.warning(f'Unrecognized configuration suffix "{filename.suffix}", assuming json.')

        with open(filename) as f:
            if ftype == '.json':
                try:
                    config = json.load(f)
                except JSONDecodeError as err:
                    logging.error(exceptionFormatter('Failed to load configuration file.'))
                    raise ConfigurationError(filename) from err
            else:
                assert ftype == '.toml'
                import toml # Late import as this feature is otherwise optional

                try:
                    config = toml.load(f)
                except toml.TomlDecodeError as err:
                    logging.error(exceptionFormatter('Failed to load configuration file.'))
                    raise ConfigurationError(filename) from err

        return config

    @classmethod
    def fromFile(cls, filename: Path) -> 'ConfigFile':
        config = cls.loadFile(filename)

        def onWarning(w):
            logging.warning(f"Encountered warning '{w}', configuration may not be correctly loadable.")
        def onError(e: ValidationErrors):
            if isinstance(e, jsonvalidation.BadObject):
                logging.error(f"Failed to load configuration, loaded json object has unsupported type {e.recieved}.")
            else:
                assert isinstance(e, Iterable)
                logging.error("Configuration didn't match expected schema. " + formatValidationErrors(e))
            raise ConfigurationError(filename=filename)

        validateJson(config, ConfigFile._schemaValidator,
            acceptedVersion='1',
            onWarning=onWarning,
            onError=onError,
        )
        assert isinstance(config, Mapping)

        return ConfigFile.fromJson(config)

    @staticmethod
    def fromJson(config: Mapping) -> 'ConfigFile':
        self = cast(ConfigFile, ClassMock())
        if 'connection' in config:
            connection = config['connection']
            if 'hostname' in connection:
                self.hostname = connection['hostname']
            if 'username' in connection:
                self.username = connection['username']
            if 'password' in connection:
                self.password = connection['password']
            if 'token' in connection:
                self.token = connection['token']

        if 'throttling' in config:
            self.throttlingLoopDelay = config['throttling']['loopDelay']
        if 'output' in config:
            output = config['output']
            if 'directory' in output:
                self.outputDirectory = Path(output['directory'])
            if 'humanFriendlyPosts' in output:
                self.verboseHumanFriendlyPosts = output['humanFriendlyPosts']

        if 'report' in config:
            reportingOptions = config['report']

            if 'verbosity' in reportingOptions:
                level = reportingOptions['verbosity']
                assert isinstance(level, int)
                self.verbosity = LogVerbosity(level + 1)
            if 'showProgress' in reportingOptions and reportingOptions['showProgress'] is not None:
                if not reportingOptions['showProgress']:
                    self.reportProgress = progress.ProgressSettings(mode=progress.VisualizationMode.DumbTerminal, forceMode=True)
                else:
                    self.reportProgress = progress.ProgressSettings(mode=progress.VisualizationMode.AnsiEscapes, forceMode=True)
            if 'progressInterval' in reportingOptions:
                self.progressInterval = reportingOptions['progressInterval']


        if 'defaultChannelOptions' in config:
            self.channelDefaults = ChannelOptions().update(config['defaultChannelOptions'])
        else:
            self.channelDefaults = ChannelOptions()
        if 'userChannelOptions' in config:
            self.directChannelDefaults = deepcopy(self.channelDefaults).update(config['userChannelOptions'])
        else:
            self.directChannelDefaults = self.channelDefaults
        if 'groupChannelOptions' in config:
            self.groupChannelDefaults = deepcopy(self.channelDefaults).update(config['groupChannelOptions'])
        else:
            self.groupChannelDefaults = self.channelDefaults
        if 'privateChannelOptions' in config:
            self.privateChannelDefaults = deepcopy(self.channelDefaults).update(config['privateChannelOptions'])
        else:
            self.privateChannelDefaults = self.channelDefaults
        if 'publicChannelOptions' in config:
            self.publicChannelDefaults = deepcopy(self.channelDefaults).update(config['publicChannelOptions'])
        else:
            self.publicChannelDefaults = self.channelDefaults

        if 'downloadTeamChannels' in config:
            self.miscTeams = config['downloadTeamChannels']
        if 'teams' in config:
            assert isinstance(config['teams'], list)
            self.explicitTeams = [
                TeamSpec.fromConfig(teamDict, self.groupChannelDefaults, self.publicChannelDefaults)
                for teamDict in config['teams']
            ]
        if 'downloadUserChannels' in config:
            self.miscDirectChannels = config['downloadUserChannels']
        if 'users' in config:
            assert isinstance(config['users'], list)
            self.explicitUsers = [
                ChannelSpec(userChannel, self.directChannelDefaults)
                for userChannel in config['users']
            ]
        if 'downloadGroupChannels' in config:
            self.miscGroupChannels = config['downloadGroupChannels']
        if 'groups' in config:
            assert isinstance(config['groups'], list)
            self.explicitGroups = [
                GroupChannelSpec(chan, self.groupChannelDefaults)
                for chan in config['groups']
            ]

        if 'downloadEmojis' in config and config['downloadEmojis']:
            self.downloadAllEmojis = True

        return ConfigFile(**self.__dict__)

    def updateFromEnv(self):
        env = os.environ
        if 'MATTERMOST_SERVER' in env:
            self.hostname = env['MATTERMOST_SERVER']
        if 'MATTERMOST_USERNAME' in env:
            self.username = env['MATTERMOST_USERNAME']
        if 'MATTERMOST_PASSWORD' in env:
            self.password = env['MATTERMOST_PASSWORD']
        if 'MATTERMOST_TOKEN' in env:
            self.token = env['MATTERMOST_TOKEN']

    def updateFromArgs(self, args: argparse.Namespace):
        if args.hostname is not None:
            self.hostname = args.hostname
        if args.username is not None:
            self.username = args.username
        if args.password is not None:
            self.password = args.password
        if args.token is not None:
            self.token = args.token

        assert 'verbosity' in args
        if args.verbosity != LogVerbosity.Normal:
            self.verbosity = args.verbosity

    def validate(self):
        '''
            Delayed validation after loading configuration from all override sources.
        '''
        def require(name):
            if getattr(self, name) == '':
                logging.error(f'Required property \'{name}\' was not specified in config file nor on command line.')
                raise ConfigurationError
        require('hostname')
        require('username')

ConfigFile._schemaValidator = ConfigFile.loadSchemaValidator()
