
from common import *
from bo import EntityLocator, Id, Time
import progress
from progress import ProgressSettings

import dataclasses
import json


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
            self.miscPrivateChannels = bool(info['downloadPrivateChannels'])
        if 'privateChannels' in info:
            assert isinstance(info['privateChannels'], list)
            self.explicitPrivateChannels = [ChannelSpec(chan, self.privateChannelDefaults) for chan in info['privateChannels']]
        if 'downloadPublicChannels' in info:
            self.miscPublicChannels = bool(info['downloadPublicChannels'])
        if 'publicChannels' in info:
            assert isinstance(info['publicChannels'], list)
            self.explicitPublicChannels = [ChannelSpec(chan, self.publicChannelDefaults) for chan in info['publicChannels']]

        return self

@dataclass
class ConfigFile:
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
    # verboseStandalonePosts: bool = False
    verboseHumanFriendlyPosts: bool = False
    downloadAllEmojis: bool = False

    verboseMode: bool = False
    reportProgress: ProgressSettings = ProgressSettings(mode=progress.VisualizationMode.AnsiEscapes)

# Note: types are not extensively checked, as we already have json schema for that
def readConfig(filename: str) -> ConfigFile:
    with open(filename) as f:
        config = json.load(f)
        res = ConfigFile()

        assert 'connection' in config
        connection = config['connection']
        res.hostname = connection['hostname']
        res.username = connection.get('username', '')
        if res.username == '':
            res.username = os.environ.get('MATTERMOST_USER', '')
            if res.username == '':
                logging.error(f'Field connection.username is missing in configuration.')
                raise ValueError
        res.password = connection.get('password', os.environ.get('MATTERMOST_PASSWORD', ''))
        res.token = connection.get('token', os.environ.get('MATTERMOST_TOKEN', ''))

        if 'throttling' in config:
            res.throttlingLoopDelay = config['throttling']['loopDelay']
        if 'output' in config:
            output = config['output']
            if 'directory' in output:
                res.outputDirectory = Path(output['directory'])
            if 'humanFriendlyPosts' in output:
                res.verboseHumanFriendlyPosts = output['humanFriendlyPosts']

        if 'report' in config:
            reportingOptions = config['report']

            if 'verbose' in reportingOptions and reportingOptions['verbose']:
                res.verboseMode = True
            if 'showProgress' in reportingOptions and reportingOptions['showProgress'] is not None:
                if not reportingOptions['showProgress']:
                    res.reportProgress = dataclasses.replace(
                        res.reportProgress, mode=progress.VisualizationMode.DumbTerminal, forceMode=True)
                else:
                    res.reportProgress = dataclasses.replace(
                        res.reportProgress, mode=progress.VisualizationMode.AnsiEscapes, forceMode=True)


        if 'defaultChannelOptions' in config:
            res.channelDefaults = ChannelOptions().update(config['defaultChannelOptions'])
        if 'directChannelOptions' in config:
            res.channelDefaults = ChannelOptions().update(config['directChannelOptions'])
        else:
            res.directChannelDefaults = res.channelDefaults
        if 'groupChannelOptions' in config:
            res.groupChannelDefaults = ChannelOptions().update(config['groupChannelOptions'])
        else:
            res.groupChannelDefaults = res.channelDefaults
        if 'privateChannelOptions' in config:
            res.privateChannelDefaults = ChannelOptions().update(config['privateChannelOptions'])
        else:
            res.privateChannelDefaults = res.channelDefaults
        if 'publicChannelOptions' in config:
            res.publicChannelDefaults = ChannelOptions().update(config['publicChannelOptions'])
        else:
            res.publicChannelDefaults = res.channelDefaults

        if 'downloadTeams' in config:
            res.miscTeams = bool(config['downloadTeams'])
        if 'teams' in config:
            assert isinstance(config['teams'], list)
            res.explicitTeams = [
                TeamSpec.fromConfig(teamDict, res.groupChannelDefaults, res.publicChannelDefaults)
                for teamDict in config['teams']
            ]
        if 'downloadUserChannels' in config:
            res.miscUserChannels = bool(config['downloadUserChannels'])
        if 'users' in config:
            assert isinstance(config['users'], list)
            res.explicitUsers = [
                ChannelSpec(userChannel, res.directChannelDefaults)
                for userChannel in config['users']
            ]
        if 'downloadGroupChannels' in config:
            res.miscGroupChannels = bool(config['downloadGroupChannels'])
        if 'groups' in config:
            assert isinstance(config['groups'], list)
            res.explicitGroups = [
                GroupChannelSpec(chan, res.groupChannelDefaults)
                for chan in config['groups']
            ]

        if 'downloadEmojis' in config and config['downloadEmojis']:
            res.downloadAllEmojis = True

    return res
