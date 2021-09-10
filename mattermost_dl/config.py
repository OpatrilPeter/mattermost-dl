'''
    Defines configuration options of the program
    and handles their loading from JSON
'''

from .common import *
from .bo import EntityLocator, Id, Time
from . import jsonvalidation
from .jsonvalidation import validate as validateJson, formatValidationErrors
from . import progress
from .progress import ProgressSettings

from collections.abc import Iterable
import dataclasses
import json
from json.decoder import JSONDecodeError
import jsonschema

class ConfigurationError(Exception):
    '''Invalid or missing configuration.'''
    def __init__(self, filename: Path, *args):
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
    redownload: bool = False
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
        if x:
            self.postsBeforeTime = Time(x)
        x = info.get('afterTime', None)
        if x:
            self.postsAfterTime = Time(x)

        self.postLimit = info.get('maximumPostCount', self.postLimit)
        self.postSessionLimit = info.get('sessionPostLimit', self.postSessionLimit)
        self.redownload = info.get('redownload', self.redownload)
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

        self.opts = dataclasses.replace(defaultOpts)
        self.opts.update(info)

@dataclass(init=False)
class GroupChannelSpec:
    locator: Union[Id, List[EntityLocator]]
    opts: ChannelOptions = ChannelOptions()

    def __init__(self, info: dict, defaultOpts: ChannelOptions):
        groupLocator = info['group']
        if isinstance(groupLocator, str):
            self.locator = cast(Id, groupLocator)
        else:
            assert isinstance(groupLocator, list)
            self.locator = [EntityLocator(chan) for chan in groupLocator]

        self.opts = dataclasses.replace(defaultOpts)
        self.opts.update(info)

@dataclass
class TeamSpec:
    locator: EntityLocator
    miscPrivateChannels: bool = True
    explicitPrivateChannels: List[ChannelSpec] = dataclasses.field(default_factory=list)
    privateChannelDefaults: ChannelOptions = ChannelOptions()
    miscPublicChannels: bool = True
    explicitPublicChannels: List[ChannelSpec] = dataclasses.field(default_factory=list)
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    @staticmethod
    def fromConfig(info: dict, globalPrivateDefaults: ChannelOptions, globalPublicDefaults: ChannelOptions) -> 'TeamSpec':
        self = TeamSpec(locator=EntityLocator(info['team']))

        if 'defaultChannelOptions' in info:
            channelDefaults = ChannelOptions(info['defaultChannelOptions'])
        else:
            channelDefaults = None
        if 'privateChannelOptions' in info:
            self.privateChannelDefaults = ChannelOptions(info['privateChannelOptions'])
        elif channelDefaults:
            self.privateChannelDefaults = channelDefaults
        else:
            self.privateChannelDefaults = globalPrivateDefaults
        if 'publicChannelOptions' in info:
            self.publicChannelDefaults = ChannelOptions(info['publicChannelOptions'])
        elif channelDefaults:
            self.publicChannelDefaults = channelDefaults
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
    explicitTeams: List[TeamSpec] = dataclasses.field(default_factory=list)
    miscUserChannels: bool = True
    explicitUsers: List[ChannelSpec] = dataclasses.field(default_factory=list)
    miscGroupChannels: bool = True
    explicitGroups: List[GroupChannelSpec] = dataclasses.field(default_factory=list)
    channelDefaults: ChannelOptions = ChannelOptions()
    directChannelDefaults: ChannelOptions = ChannelOptions()
    groupChannelDefaults: ChannelOptions = ChannelOptions()
    privateChannelDefaults: ChannelOptions = ChannelOptions()
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    outputDirectory: Path = Path()
    verboseHumanFriendlyPosts: bool = False
    downloadAllEmojis: bool = False

    verboseMode: bool = False
    reportProgress: ProgressSettings = ProgressSettings(mode=progress.VisualizationMode.AnsiEscapes)
    progressInterval: int = 500

    @staticmethod
    def loadSchemaValidator() -> jsonschema.Draft7Validator:
        with open(sourceDirectory(__file__)/'config.schema.json') as schemaFile:
            return jsonschema.Draft7Validator(json.load(schemaFile))

    @staticmethod
    def fromFile(filename: Path) -> 'ConfigFile':
        with open(filename) as f:
            try:
                config = json.load(f)
            except JSONDecodeError as exc:
                raise ConfigurationError(filename) from exc

            def onWarning(w):
                logging.warning(f"Encountered warning '{w}', configuration may not be correctly loadable.")
            def onError(e):
                if isinstance(e, jsonvalidation.BadObject):
                    logging.error(f"Failed to load configuration, loaded json object has unsupported type {e.recieved}.")
                else:
                    assert isinstance(e, Iterable)
                    logging.error("Configuration didn't match expected schema. " + formatValidationErrors(e))
                raise ConfigurationError(filename=filename)

            validateJson(config, ConfigFile._schemaValidator,
                acceptedVersion='0',
                onWarning=onWarning,
                onError=onError,
            )

            return ConfigFile.fromJson(config)

    @staticmethod
    def fromJson(config: dict) -> 'ConfigFile':
        self = cast(ConfigFile, ClassMock())
        connection = config['connection']
        self.hostname = connection['hostname']
        self.username = connection['username']
        self.password = connection.get('password', os.environ.get('MATTERMOST_PASSWORD', ''))
        self.token = connection.get('token', os.environ.get('MATTERMOST_TOKEN', ''))

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

            if 'verbose' in reportingOptions and reportingOptions['verbose']:
                self.verboseMode = True
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
        if 'directChannelOptions' in config:
            self.directChannelDefaults = ChannelOptions().update(config['directChannelOptions'])
        else:
            self.directChannelDefaults = self.channelDefaults
        if 'groupChannelOptions' in config:
            self.groupChannelDefaults = ChannelOptions().update(config['groupChannelOptions'])
        else:
            self.groupChannelDefaults = self.channelDefaults
        if 'privateChannelOptions' in config:
            self.privateChannelDefaults = ChannelOptions().update(config['privateChannelOptions'])
        else:
            self.privateChannelDefaults = self.channelDefaults
        if 'publicChannelOptions' in config:
            self.publicChannelDefaults = ChannelOptions().update(config['publicChannelOptions'])
        else:
            self.publicChannelDefaults = self.channelDefaults

        if 'downloadTeams' in config:
            self.miscTeams = config['downloadTeams']
        if 'teams' in config:
            assert isinstance(config['teams'], list)
            self.explicitTeams = [
                TeamSpec.fromConfig(teamDict, self.groupChannelDefaults, self.publicChannelDefaults)
                for teamDict in config['teams']
            ]
        if 'downloadUserChannels' in config:
            self.miscUserChannels = config['downloadUserChannels']
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

ConfigFile._schemaValidator = ConfigFile.loadSchemaValidator()
