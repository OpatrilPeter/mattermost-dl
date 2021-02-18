
from common import *
from bo import EntityLocator, Id, Time
import progress
from progress import ProgressSettings

import dataclasses
import json

# Options are All (true), None (false), or explicit list
T = TypeVar('T')
EntityList = Union[bool, List[T]]

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

@dataclass(init=False)
class TeamSpec:
    locator: EntityLocator
    privateChannels: EntityList[ChannelSpec] = True
    publicChannels: EntityList[ChannelSpec] = True
    privateChannelDefaults: ChannelOptions = ChannelOptions()
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    def __init__(self, info: dict, globalPrivateDefaults: ChannelOptions, globalPublicDefaults: ChannelOptions):
        self.locator = EntityLocator(info['team'])

        if 'defaultChannelOptions' in info:
            channelDefaults = ChannelOptions(info['defaultChannelOptions'])
        else:
            channelDefaults = None
        if 'privateChannelOptions' in info:
            self.privateChannelOptions = ChannelOptions(info['privateChannelOptions'])
        elif channelDefaults:
            self.privateChannelOptions = channelDefaults
        else:
            self.privateChannelOptions = globalPrivateDefaults
        if 'publicChannelOptions' in info:
            self.publicChannelDefaults = ChannelOptions(info['publicChannelOptions'])
        elif channelDefaults:
            self.publicChannelDefaults = channelDefaults
        else:
            self.publicChannelDefaults = globalPublicDefaults

        if 'privateChannels' in info:
            if len(info['privateChannels']) == 0:
                self.privateChannels = False
            else:
                self.privateChannels = [ChannelSpec(chan, self.privateChannelDefaults) for chan in info['privateChannels']]
        if 'publicChannels' in info:
            if len(info['publicChannels']) == 0:
                self.publicChannels = False
            else:
                self.publicChannels = [ChannelSpec(chan, self.privateChannelDefaults) for chan in info['publicChannels']]

@dataclass
class ConfigFile:
    hostname: str = ''
    username: str = ''
    password: str = ''
    token: str = ''

    throttlingLoopDelay: int = 0
    teams: EntityList[TeamSpec] = True
    users: EntityList[ChannelSpec] = True
    groups: EntityList[GroupChannelSpec] = True
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

        res.hostname = config['hostname']
        res.username = config['username']
        res.password = config.get('password', os.environ.get('MATTERMOST_PASSWORD', ''))
        res.token = config.get('token', os.environ.get('MATTERMOST_TOKEN', ''))

        if 'throttling' in config:
            res.throttlingLoopDelay = config['throttling']['loopDelay']
        if 'output' in config:
            output = config['output']
            if 'directory' in output:
                res.outputDirectory = Path(output['directory'])
            # if 'standalonePosts' in output:
            #     res.verboseStandalonePosts = output['standalonePosts']
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

        if 'teams' in config:
            assert isinstance(config['teams'], list)
            if len(config['teams']) == 0:
                res.teams = False
            else:
                res.teams = [
                    TeamSpec(teamDict, res.groupChannelDefaults, res.publicChannelDefaults)
                    for teamDict in config['teams']
                ]
        if 'users' in config:
            assert isinstance(config['users'], list)
            if len(config['users']) == 0:
                res.users = False
            else:
                res.users = [
                    ChannelSpec(userChannel, res.directChannelDefaults)
                    for userChannel in config['users']
                ]
        if 'groups' in config:
            if len(config['groups']) == 0:
                res.groups = False
            else:
                res.groups = [GroupChannelSpec(chan, res.groupChannelDefaults) for chan in config['groups']]

        if 'downloadAllEmojis' in config and config['downloadAllEmojis']:
            res.downloadAllEmojis = True

    return res
