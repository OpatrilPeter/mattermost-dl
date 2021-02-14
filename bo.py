'''
    Defines "business objects",
    OOP representations of Mattermost entities
'''

__all__ = [
    'EntityLocator',
    'Id',
    'Time',
    'JsonMessage',
    'User',
    'Emoji',
    'FileAttachment',
    'PostReaction',
    'Post',
    'ChannelType',
    'Channel',
    'TeamType',
    'Team',
]

from common import *

from datetime import datetime
from functools import total_ordering

class EntityLocator:
    def __init__(self, info: dict):
        ok = False
        for key in info:
            if key in ('id', 'name', 'internalName'):
                if ok:
                    raise ValueError
                ok = True
        else:
            if not ok:
                raise ValueError
        if 'id' in info:
            self.id: Id = info['id']
        if 'name' in info:
            self.name: str = info['name']
        if 'internalName' in info:
            self.internalName: str = info['internalName']
    def __repr__(self) -> str:
        return f'EntityLocator({self.__dict__})'

@total_ordering
class Time:
    def __init__(self, time: Union[int, str]):
        self._time: Union[int, float]
        # time is unix timestamp in miliseconds
        if isinstance(time, int):
            self._time = time
        else:
            assert isinstance(time, str)
            self._time = datetime.fromisoformat(time).timestamp() * 1000

    # Returns unix timestamp in miliseconds
    @property
    def timestamp(self) -> Union[int, float]:
        return self._time
    def __eq__(self, other: 'Time'):
        return self._time == other._time
    def __lt__(self, other: 'Time'):
        return self._time < other._time

    def __str__(self):
        fmt = datetime.fromtimestamp(self._time/1000).isoformat()
        fractionStart = fmt.rfind('.')
        if fractionStart != -1:
            fmt = fmt[:fractionStart]
        return fmt
    def __repr__(self):
        return f"'{datetime.fromtimestamp(self._time/1000).isoformat()}'"

    def toJson(self) -> Union[int, float]:
        return self.timestamp

Id = NewType('Id', str)

@dataclass
class JsonMessage:
    # All otherwise unknown fields
    misc: Dict[str, Any]

    def drop(self, attrName: str):
        if attrName in self.misc:
            del self.misc[attrName]

    def extract(self, attrName: str) -> Any:
        assert attrName in self.misc
        res = self.misc[attrName]
        del self.misc[attrName]
        return res

    def extract_or(self, attrName: str, fallback: Any) -> Any:
        if attrName not in self.misc:
            return fallback
        res = self.extract(attrName)
        if res:
            return res
        else:
            return fallback

    # def __repr__(self):
    #     return f'{type(self).__name__}({ {key: val for key, val in self.__dict__.items() if not hasattr(val, "__call__")} })'

    def toJson(self) -> dict:
        return {key: value for key, value in self.__dict__.items() if value is not None
            and (not isinstance(value, Sized) or len(value) != 0)}

    def cleanMisc(self):
        '''
            Removes stuff from unknown data that seem like default values.
        '''
        self.misc = {key: value for key, value in self.misc.items()
            if not (
                value is None
                or value == ''
                or (isinstance(value, dict) and len(value) == 0))
        }

    def __eq__(self, other) -> bool:
        if hasattr(self, 'id'):
            return getattr(self, 'id') == getattr(other, 'id')
        else:
            return super().__eq__(other)

@dataclass
class User(JsonMessage):
    id: Id
    name: str
    firstName: str
    lastName: str
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    nickname: Optional[str] = None
    updateAvatarTime: Optional[Time] = None
    position: Optional[str] = None
    roles: List[str] = dataclassfield(default_factory=list)
    avatarFilename: Optional[str] = None

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        u: User = cast(User, JsonMessage(misc=info))
        u.id = u.extract('id')
        u.name = u.extract('username')
        x = u.extract('nickname')
        if x:
            u.nickname = x
        u.firstName = u.extract('first_name')
        u.lastName = u.extract('last_name')

        u.createTime = Time(u.extract('create_at'))
        x = u.extract('update_at')
        if x != u.createTime.timestamp:
            u.updateTime = Time(x)
        x = u.extract('delete_at')
        if x != 0:
            u.deleteTime = Time(x)
        x = u.extract_or('last_picture_update', 0)
        if x != 0 and x != u.createTime.timestamp:
            u.updateAvatarTime = Time(x)
        x = u.extract('position')
        if x:
            u.position = x

        x = u.extract('roles').split(' ')
        if 'system_user' in x and len(x) == 1:
            pass
        else:
            u.roles = x

        # Things we explicitly don't care about
        u.drop('locale')
        u.drop('timezone')
        u.drop('notify_props')
        u.drop('email')
        u.drop('email_verified')
        u.drop('auth_service')
        u.drop('last_password_update')

        u.cleanMisc()
        return cls(**u.__dict__)

    def match(self, locator: EntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return self.id == locator.id
        elif hasattr(locator, 'name'):
            return self.name == locator.name
        else:
            assert hasattr(locator, 'internalName')
            return self.name == locator.internalName


@dataclass
class Emoji(JsonMessage):
    id: Id
    creatorId: Id
    name: str
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    creatorName: Optional[str] = None # Redundant
    imageFileName: Optional[str] = None # Filename used for storage if file gets downloaded

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        e = cast(Emoji, JsonMessage(misc=info))

        x: Any

        e.id = e.extract('id')
        e.creatorId = e.extract('creator_id')
        e.name = e.extract('name')
        e.createTime = Time(e.extract('create_at'))
        x = e.extract('update_at')
        if x != e.createTime.timestamp:
            e.updateTime = Time(x)
        x = e.extract('delete_at')
        if x != 0:
            e.deleteTime = Time(x)

        e.cleanMisc()

        return cls(**e.__dict__)

@dataclass
class FileAttachment(JsonMessage):
    id: Id
    name: str
    byteSize: int
    mimeType: str
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        f: FileAttachment = cast(FileAttachment, JsonMessage(misc=info))

        x: Any

        f.id = f.extract('id')
        f.name = f.extract('name')
        f.byteSize = f.extract('size')
        f.mimeType = f.extract('mime_type')
        f.createTime = Time(f.extract('create_at'))
        x = f.extract('update_at')
        if x != f.createTime.timestamp:
            f.updateTime = Time(x)
        x = f.extract('delete_at')
        if x:
            f.deleteTime = Time(x)

        # We don't need derived properties
        f.drop('user_id')
        f.drop('post_id')
        f.drop('width')
        f.drop('height')
        f.drop('has_preview_image')
        f.drop('mini_preview')
        f.drop('extension')

        f.cleanMisc()

        return cls(**f.__dict__)

@dataclass
class PostReaction(JsonMessage):
    userId: Id
    createTime: Time
    emojiName: str

    emoji: Optional[Emoji] = None # redundant
    userName: Optional[str] = None # redundant

    @classmethod
    def fromMattermost(cls, info: dict):
        r: PostReaction = cast(PostReaction, JsonMessage(misc=info))

        r.userId = r.extract('user_id')
        r.createTime = Time(r.extract('create_at'))
        r.emojiName = r.extract('emoji_name')

        r.drop('post_id')

        r.cleanMisc()

        return cls(**r.__dict__)

@dataclass
class Post(JsonMessage):
    id: Id
    userId: Id
    createTime: Time
    message: str

    isPinned: Optional[bool] = None
    updateTime: Optional[Time] = None
    # Last "visible edit" time (small updates after posting/public update are ignored)
    publicUpdateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    # Parent post (if this post is a reply)
    # Note: mattermost seem to disagree self and returns root
    parentPostId: Optional[Id] = None
    # Root of reply chain
    rootPostId: Optional[Id] = None

    specialMsgType: Optional[str] = None
    # Set only if specialMsgType is nonempty
    specialMsgProperties: Optional[dict] = None

    # May contain emojis directly or indirectly
    emojis: Union[List[Emoji], List[Id]] = dataclassfield(default_factory=list)
    attachments: List[FileAttachment] = dataclassfield(default_factory=list)
    reactions: List[PostReaction] = dataclassfield(default_factory=list)

    userName: Optional[str] = None # redundant
    user: Optional[User] = None # redundant

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        p = cast(Post, JsonMessage(misc=info))

        x: Any

        p.id = p.extract('id')
        p.userId = p.extract('user_id')
        p.createTime = Time(p.extract('create_at'))
        p.message = p.extract('message')
        x = p.extract('update_at')
        if x != p.createTime.timestamp:
            p.updateTime = Time(x)
        # Last "visible edit" time (small updates after posting/public update are ignored)
        x = p.extract('edit_at')
        if x != 0 and x != p.updateTime.timestamp:
            p.publicUpdateTime = Time(x)
        x = p.extract('delete_at')
        if x != 0:
            p.deleteTime = Time(x)
        # Parent post (if this post is a reply)
        x = p.extract_or('parent_id', 0)
        if x:
            p.parentPostId = x
        x = p.extract_or('root_id', 0)
        if x and (not hasattr(p, 'parentPostId') or x != p.parentPostId):
            p.rootPostId = x
        if p.extract_or('is_pinned', False):
            p.isPinned = True

        x = p.extract('props')
        x = {key: value
            for key, value in x.items()
                # Drop fields that are known to be unnecessary
                if (key not in ('disable_group_highlight', 'channel_mentions')
                    and value != "")
        }
        if x:
            p.misc['props'] = x

        x = p.extract('type')
        if x:
            p.specialMsgType = x

        metadata = p.extract('metadata')
        if 'embeds' in metadata:
            # We ignore these, as there is nothing that can't be restructured from message
            del metadata['embeds']
        if 'emojis' in metadata:
            p.emojis = [Emoji.fromMattermost(emoji)
                for emoji in metadata['emojis']
            ]
            del metadata['emojis']
        if 'files' in metadata:
            p.attachments = [FileAttachment.fromMattermost(fileInfo)
                for fileInfo in metadata['files']
            ]
            del metadata['files']
        if 'images' in metadata:
            # images only contain redundant metadata
            del metadata['images']
        if 'reactions' in metadata:
            p.reactions = [PostReaction.fromMattermost(reaction)
                for reaction in metadata['reactions']
            ]
            del metadata['reactions']
        if len(metadata) != 0:
            p.misc['metadata'] = metadata

        p.drop('channel_id')
        # Redundant as we can reach the root by following a chain of parent posts
        # p.drop('root_id')
        p.drop('reply_count')
        p.drop('has_reactions')
        # Deprecated form of file attachment metadata
        p.drop('file_ids')
        # Contains automatically extracted hashtags from the message (usually wrong)
        p.drop('hashtags')

        p.cleanMisc()

        return cls(**p.__dict__)

    def __str__(self):
        return f'Post(u={self.userId}, t={self.createTime}, m={self.message})'


class ChannelType(Enum):
    Open = 'O'
    Private = 'P'
    Group = 'G'
    Direct = 'D'

    @classmethod
    def load(cls, info: str) -> 'ChannelType':
        for member in cls:
            if member.value == info:
                return member
        logging.warning(f"Unknown channel type '{info}', assumed open.")
        return ChannelType.Open

    def toJson(self) -> str:
        return self.name

@dataclass
class Channel(JsonMessage):
    id: Id
    name: str
    internalName: str
    creationTime: Time
    type: ChannelType
    lastMessageTime: Time
    messageCount: int

    creatorUserId: Optional[Id] = None
    updateTime: Optional[Time] = None
    deletionTime: Optional[Time] = None
    header: Optional[str] = None
    purpose: Optional[str] = None

    members: List[User] = dataclassfield(default_factory=list)

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        ch = cast(Channel, JsonMessage(misc=info))

        x: Any

        ch.id = ch.extract('id')
        ch.name = ch.extract('display_name')
        ch.internalName = ch.extract('name')
        ch.creationTime = Time(ch.extract('create_at'))
        x = ch.extract('update_at')
        if x != ch.creationTime.timestamp:
            ch.updateTime = Time(x)
        x = ch.extract('delete_at')
        if x != 0:
            ch.deletionTime = Time(x)
        ch.type = ChannelType.load(ch.extract('type'))
        x = ch.extract('header')
        if x:
            ch.header = x
        x = ch.extract('purpose')
        if x:
            ch.purpose = x

        ch.lastMessageTime = Time(ch.extract('last_post_at'))
        ch.messageCount = ch.extract('total_msg_count')
        x = ch.extract('creator_id')
        if x:
            ch.creatorUserId = x

        ch.drop('team_id')
        ch.drop('extra_update_at')
        ch.drop('group_constrained')

        ch.cleanMisc()

        return cls(**ch.__dict__)

    def __str__(self) -> str:
        return f'Channel({self.internalName})'

    def toJson(self, includeMembers = True) -> dict:
        return { key: value for key, value in super().toJson().items()
            if (includeMembers or key != 'members')
        }

    def match(self, locator: EntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return self.id == locator.id
        elif hasattr(locator, 'internalName'):
            return self.internalName == locator.internalName
        else:
            assert hasattr(locator, 'name')
            return self.name == locator.name


class TeamType(Enum):
    Open = 'O'
    InviteOnly = 'I'

    @classmethod
    def load(cls, info: str) -> 'TeamType':
        for member in cls:
            if member.value == info:
                return member
        logging.warning(f"Unknown team type '{info}', assumed open.")
        return TeamType.Open

    def toJson(self) -> str:
        return self.name

@dataclass
class Team(JsonMessage):
    id: Id
    name: str
    internalName: str
    type: TeamType
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    description: Optional[str] = None
    updateAvatarTime: Optional[Time] = None
    inviteId: Optional[Id] = None

    channels: Dict[Id, Channel] = dataclassfield(default_factory=dict)

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def fromMattermost(cls, info: dict):
        t = cast(Team, JsonMessage(misc=info))

        x: Any

        t.id = t.extract('id')
        t.name = t.extract('display_name')
        t.internalName = t.extract('name')
        t.type = TeamType(t.extract('type'))
        t.createTime = Time(t.extract('create_at'))
        x = t.extract('update_at')
        if x != t.createTime.timestamp:
            t.updateTime = Time(x)
        x = t.extract('delete_at')
        if x:
            t.deleteTime = Time(x)
        x = t.extract('description')
        if x:
            t.description = x

        x = t.extract_or('last_team_icon_update', 0)
        if x != 0 and x != t.createTime.timestamp:
            t.updateAvatarTime = Time(x)

        x = t.extract('invite_id')
        if x:
            t.inviteId = x

        # Uninteresting fields for achivation
        t.drop('allow_open_invite')
        t.drop('allowed_domains')

        t.cleanMisc()

        return cls(**t.__dict__)

    def toJson(self, includeChannels = True) -> dict:
        return { key: value for key, value in super().toJson().items()
            if (includeChannels or key != 'channels')
        }

    def __str__(self):
        return f'Team({self.internalName})'

    def match(self, locator: EntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return self.id == locator.id
        elif hasattr(locator, 'internalName'):
            return self.internalName == locator.internalName
        else:
            assert hasattr(locator, 'name')
            return self.name == locator.name
