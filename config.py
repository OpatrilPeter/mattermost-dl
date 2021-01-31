
import dataclasses
from enum import Enum
from dataclasses import dataclass, field as dataclassfield
import json
import os
from typing import Any, Generic, List, NamedTuple, Optional, TypeVar, Union, cast
from pathlib import Path


from bo import Id, Time

class EntityLocator:
    def __init__(self, info: dict):
        if len(info) != 1:
            raise ValueError
        for key in info:
            if key not in ('id', 'name', 'internalName'):
                raise ValueError
        if 'id' in info:
            self.id: Id = info['id']
        if 'name' in info:
            self.name: str = info['name']
        if 'internalName' in info:
            self.internalName: str = info['internalName']
    def __repr__(self) -> str:
        return f'EntityLocator({self.__dict__})'

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
            self.downloadAttachments = attachments.get('allow', self.downloadAttachments)
            self.downloadAttachmentSizeLimit = attachments.get('maxSize', self.downloadAttachmentSizeLimit)
            self.downloadAttachmentTypes = attachments.get('allowedMimeTypes', self.downloadAttachmentTypes)
        if 'emojis' in info:
            emojis = info['emojis']
            self.downloadEmoji = emojis.get('download', self.downloadEmoji)
            self.emojiMetadata = emojis.get('metadata', self.emojiMetadata)

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
    channels: EntityList[ChannelSpec] = True
    groups: EntityList[GroupChannelSpec] = True
    groupChannelDefaults: ChannelOptions = ChannelOptions()
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    def __init__(self, info: dict, group: ChannelOptions, public: ChannelOptions):
        self.locator = EntityLocator(info['team'])

        if 'defaultChannelOptions' in info:
            channelDefaults = ChannelOptions(info['defaultChannelOptions'])
        else:
            channelDefaults = None
        if 'groupChannelOptions' in info:
            self.groupChannelDefaults = ChannelOptions(info['groupChannelOptions'])
        elif channelDefaults:
            self.groupChannelDefaults = channelDefaults
        else:
            self.groupChannelDefaults = group
        if 'publicChannelOptions' in info:
            self.publicChannelDefaults = ChannelOptions(info['publicChannelOptions'])
        elif channelDefaults:
            self.publicChannelDefaults = channelDefaults
        else:
            self.publicChannelDefaults = public

        if 'channels' in info:
            if len(info['channels']) == 0:
                self.channels = False
            else:
                self.channels = [ChannelSpec(chan, self.publicChannelDefaults) for chan in info['channels']]

        if 'groups' in info:
            if len(info['groups']) == 0:
                self.groups = False
            else:
                self.groups = [GroupChannelSpec(chan, self.groupChannelDefaults) for chan in info['groups']]

@dataclass
class ConfigFile:
    hostname: str = ''
    username: str = ''
    password: str = ''
    token: str = ''

    throttlingLoopDelay: int = 0
    teams: EntityList[TeamSpec] = True
    users: EntityList[ChannelSpec] = True
    channelDefaults: ChannelOptions = ChannelOptions()
    directChannelDefaults: ChannelOptions = ChannelOptions()
    groupChannelDefaults: ChannelOptions = ChannelOptions()
    publicChannelDefaults: ChannelOptions = ChannelOptions()

    outputDirectory: Path = Path()
    verboseStandalonePosts: bool = False
    verboseHumanFriendlyPosts: bool = False

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
            if 'directory' in config['output']:
                res.outputDirectory = Path(config['output']['directory'])
            if 'standalonePosts' in config['output']:
                res.verboseStandalonePosts = config['output']['standalonePosts']
            if 'humanFriendlyPosts' in config['output']:
                res.verboseHumanFriendlyPosts = config['output']['humanFriendlyPosts']

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

    return res
