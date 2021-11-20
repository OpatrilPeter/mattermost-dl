'''
    Defines "business objects",
    OOP representations of Mattermost entities
'''

__all__ = [
    'StoreError',
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

from .common import *
from .jsonvalidation import validate as validateJson, formatValidationErrors
from . import jsonvalidation

from collections.abc import Iterable
from datetime import datetime
from functools import total_ordering
import json
import jsonschema

class StoreError(Exception):
    '''Failed to load from the storage of downloaded content.'''
    pass

class EntityLocator:
    def __init__(self, info: dict):
        ok = False
        for key in info:
            if key in ('id', 'name', 'internalName'):
                if ok:
                    raise ValueError('EntityLocator with multiple (possibly conflicting) identificators.')
                ok = True
        else:
            if not ok:
                raise ValueError('EntityLocator has no identificator.')
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
        self._time: int
        # time is unix timestamp in miliseconds
        if isinstance(time, int):
            self._time = time
        else:
            assert isinstance(time, str)
            self._time = int(datetime.fromisoformat(time).timestamp() * 1000)

    # Returns unix timestamp in miliseconds
    @property
    def timestamp(self) -> int:
        return self._time
    def __eq__(self, other: 'Time'):
        return self._time == other._time
    def __lt__(self, other: 'Time'):
        return self._time < other._time
    # Needed to silence linter
    def __gt__(self, other: 'Time'):
        return self._time > other._time

    def __str__(self):
        fmt = datetime.fromtimestamp(self._time/1000).isoformat()
        fractionStart = fmt.rfind('.')
        if fractionStart != -1:
            fmt = fmt[:fractionStart]
        return fmt
    def __repr__(self):
        return f"'{datetime.fromtimestamp(self._time/1000).isoformat()}'"

    def toStore(self) -> int:
        return self.timestamp

Id = NewType('Id', str)

@dataclass
class JsonMessage:
    '''
        Base class for all Json based data structures, notably all Mattermost entities.
        Contains common code for loading from Mattermost representation while keeping
        unknown fields available and facilities for saving and loading to internal store.
    '''

    # All otherwise unknown fields are collected in this generic dict
    # Note: Without default value, as that would force all dataclass based subclasses to have all members optional
    misc: Dict[str, Any]

    def drop(self, attrName: str):
        if attrName in self.misc:
            del self.misc[attrName]

    def extract(self, attrName: str) -> Any:
        assert attrName in self.misc
        res = self.misc[attrName]
        del self.misc[attrName]
        return res

    def extractOr(self, attrName: str, fallback: Any) -> Any:
        if attrName not in self.misc:
            return fallback
        res = self.extract(attrName)
        if res:
            return res
        else:
            return fallback

    def toStore(self) -> dict:
        def transform(value):
            if hasattr(value, 'toStore'):
                return value.toStore()
            return value

        return {key: transform(value) for key, value in self.__dict__.items() if value is not None
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

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any) -> Any:
        '''
            Provides a callback that subclasses of JsonMessage can override use
            to simplify their deserialization (fromStore method).
            Instead of writing full fromStore override, universal version
            can be used and only individual members not handleable by normal system can
            be resolved by this method - members that are unknown or handleable by
            universal solution shall return NotImplemented constant.
        '''
        return NotImplemented

    _T = TypeVar('_T', bound='JsonMessage')
    @classmethod
    def fromStore(cls: Type[_T], info: dict) -> _T:
        misc = info['misc'] if 'misc' in info else {}
        knownInfo = {}
        fields = {f.name: f for f in dataclasses.fields(cls)}
        for key, value in info.items():
            if key == 'misc':
                continue
            if key not in fields:
                misc[key] = value
                continue
            FieldType = fields[key].type
            if hasattr(cls, 'memberFromStore'):
                possibleMemberValue = cls.memberFromStore(key, value)
                if possibleMemberValue is not NotImplemented:
                    knownInfo[key] = possibleMemberValue
                    continue
            if hasattr(FieldType, 'fromStore'):
                knownInfo[key] = FieldType.fromStore(value)
            # Not typing-based pseudotype or primitive type
            elif isinstance(FieldType, type):
                if issubclass(FieldType, Enum):
                    knownInfo[key] = FieldType[value]
                elif FieldType not in (str, int, float, bool):
                    knownInfo[key] = FieldType(value)
                else:
                    knownInfo[key] = value
            else:
                logging.error(f"Can't load type `{cls.__name__}` from JSON form automatically, field `{key}` of type `{FieldType.__name__ if hasattr(FieldType, '__name__') else FieldType}` can't be converted.")
                raise StoreError
        return cls(misc=misc, **knownInfo)

@dataclass
class User(JsonMessage):
    id: Id
    name: str
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    nickname: Optional[str] = None
    updateAvatarTime: Optional[Time] = None
    position: Optional[str] = None
    roles: List[str] = dataclassfield(default_factory=list)
    avatarFileName: Optional[str] = None

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
        x = u.extract('first_name')
        if x:
            u.firstName = x
        x = u.extract('last_name')
        if x:
            u.lastName = x

        u.createTime = Time(u.extract('create_at'))
        x = u.extract('update_at')
        if x != u.createTime.timestamp:
            u.updateTime = Time(x)
        x = u.extract('delete_at')
        if x != 0:
            u.deleteTime = Time(x)
        x = u.extractOr('last_picture_update', 0)
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

        x = u.extractOr('props', {})
        x = {key: value
            for key, value in x.items()
                # Drop fields that are known to be unnecessary
                # Notably, custom status is dropped as its ephemeral, while User info is mostly treated as constant in time
                if (key not in ('customStatus',)
                    and value != "")
        }
        if x:
            u.misc['props'] = x

        # Things we explicitly don't care about
        u.drop('auth_service')
        u.drop('email')
        u.drop('email_verified')
        u.drop('disable_welcome_email')
        u.drop('last_password_update')
        u.drop('locale')
        u.drop('timezone')
        u.drop('notify_props')

        u.cleanMisc()
        return cls(**u.__dict__)

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime', 'updateAvatarTime'):
            return Time(jsonMemberValue)
        elif memberName in ('id', 'firstName', 'lastName', 'nickname', 'position', 'roles', 'avatarFileName'):
            return jsonMemberValue
        return NotImplemented

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

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime'):
            return Time(jsonMemberValue)
        elif memberName in ('id', 'creatorId', 'creatorName', 'imageFileName'):
            return jsonMemberValue
        return NotImplemented

@dataclass
class FileAttachment(JsonMessage):
    id: Id
    name: str
    byteSize: int
    createTime: Time
    mimeType: Optional[str] = None
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

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime'):
            return Time(jsonMemberValue)
        elif memberName in ('id', 'mimeType'):
            return jsonMemberValue
        return NotImplemented

@dataclass
class PostReaction(JsonMessage):
    userId: Id
    createTime: Time
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    emojiId: Optional[Id] = None
    emojiName: Optional[str] = None

    emoji: Optional[Emoji] = None # redundant
    userName: Optional[str] = None # redundant

    @classmethod
    def fromMattermost(cls, info: dict):
        r: PostReaction = cast(PostReaction, JsonMessage(misc=info))

        r.userId = r.extract('user_id')
        r.createTime = Time(r.extract('create_at'))
        x = r.extractOr('update_at', 0)
        if x != r.createTime.timestamp:
            r.updateTime = Time(x)
        x = r.extractOr('delete_at', 0)
        if x != 0:
            r.deleteTime = Time(x)

        r.emojiName = r.extract('emoji_name')

        r.drop('post_id')

        r.cleanMisc()

        return cls(**r.__dict__)

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime'):
            return Time(jsonMemberValue)
        elif memberName in ('userId', 'emojiId', 'userName'):
            return jsonMemberValue
        elif memberName == 'emoji':
            return Emoji.fromStore(jsonMemberValue)
        return NotImplemented

@dataclass
class Post(JsonMessage):
    _schemaValidator: ClassVar[jsonschema.Draft7Validator]

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
        if x != 0 and (p.updateTime is None or x != p.updateTime.timestamp):
            p.publicUpdateTime = Time(x)
        x = p.extract('delete_at')
        if x != 0:
            p.deleteTime = Time(x)
        # Parent post (if this post is a reply)
        x = p.extractOr('parent_id', 0)
        if x:
            p.parentPostId = x
        x = p.extractOr('root_id', 0)
        if x and (not hasattr(p, 'parentPostId') or x != p.parentPostId):
            p.rootPostId = x
        if p.extractOr('is_pinned', False):
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
        p.drop('last_reply_at')

        p.cleanMisc()

        return cls(**p.__dict__)

    def __str__(self):
        return f'Post(u={self.userId}, t={self.createTime}, m={self.message})'

    @classmethod
    def fromStore(cls, info: dict,
        onWarning: Optional[Callable[[jsonvalidation.ValidationWarnings], None]] = None,
        onError: Optional[Callable[[jsonvalidation.ValidationErrors], NoReturn]] = None):

        if onWarning is None:
            def onWarningDefault(w):
                logging.warning(f"Load of post caused warning '{w}', it may not be loadable correctly.")
            onWarning = onWarningDefault
        if onError is None:
            def onErrorDefault(e):
                if isinstance(e, jsonvalidation.BadObject):
                    logging.error(f"Failed to load post, loaded json object has unsupported type {e.recieved}.")
                else:
                    assert isinstance(e, Iterable)
                    logging.error("Post didn't match expected schema. " + formatValidationErrors(e))
                raise StoreError
            onError = onErrorDefault
        validateJson(info, cls._schemaValidator, acceptedVersion='0', onWarning=onWarning, onError=onError)
        cls._schemaValidator.validate(info)
        return super().fromStore(info)

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'publicUpdateTime', 'deleteTime'):
            return Time(jsonMemberValue)
        # Note: emojis from JSON shall be only List[str]
        elif memberName in ('id', 'userId', 'isPinned', 'parentPostId', 'rootPostId', 'specialMsgType', 'emojis', 'userName'):
            return jsonMemberValue
        elif memberName == 'attachments':
            assert isinstance(jsonMemberValue, list)
            return [FileAttachment.fromStore(a) for a in jsonMemberValue]
        elif memberName == 'reactions':
            assert isinstance(jsonMemberValue, list)
            return [PostReaction.fromStore(r) for r in jsonMemberValue]
        return NotImplemented

    @staticmethod
    def loadSchemaValidator() -> jsonschema.Draft7Validator:
        with open(sourceDirectory(__file__)/'post.schema.json') as schemaFile:
            return jsonschema.Draft7Validator(json.load(schemaFile))

Post._schemaValidator = Post.loadSchemaValidator()

class ChannelType(Enum):
    Open = 'O'
    Private = 'P'
    Group = 'G'
    Direct = 'D'

    @classmethod
    def fromMattermost(cls, info: str) -> 'ChannelType':
        for member in cls:
            if member.value == info:
                return member
        logging.warning(f"Unknown channel type '{info}', assumed open.")
        return ChannelType.Open

    def toStore(self) -> str:
        return self.name

@dataclass
class Channel(JsonMessage):
    id: Id
    internalName: str
    createTime: Time
    type: ChannelType
    messageCount: int

    name: Optional[str] = None
    creatorUserId: Optional[Id] = None
    updateTime: Optional[Time] = None
    deleteTime: Optional[Time] = None
    header: Optional[str] = None
    purpose: Optional[str] = None

    # How many messages are not replies
    rootMessageCount: Optional[int] = None
    lastMessageTime: Optional[Time] = None
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
        ch.createTime = Time(ch.extract('create_at'))
        x = ch.extract('update_at')
        if x != ch.createTime.timestamp:
            ch.updateTime = Time(x)
        x = ch.extract('delete_at')
        if x != 0:
            ch.deleteTime = Time(x)
        ch.type = ChannelType.fromMattermost(ch.extract('type'))
        x = ch.extract('header')
        if x:
            ch.header = x
        x = ch.extract('purpose')
        if x:
            ch.purpose = x

        x = ch.extract('last_post_at')
        if x != 0:
            ch.lastMessageTime = Time(x)
        ch.messageCount = ch.extract('total_msg_count')
        ch.rootMessageCount = ch.extractOr('total_msg_count_root', None)
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

    def toStore(self, includeMembers = True) -> dict:
        return { key: value for key, value in super().toStore().items()
            if (includeMembers or key != 'members')
        }

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime', 'lastMessageTime'):
            return Time(jsonMemberValue)
        elif memberName in ('id', 'name', 'creatorUserId', 'header', 'purpose', 'rootMessageCount'):
            return jsonMemberValue
        elif memberName == 'members':
            assert isinstance(jsonMemberValue, list)
            return [User.fromStore(u) for u in jsonMemberValue]
        return NotImplemented

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
    def fromMattermost(cls, info: str) -> 'TeamType':
        for member in cls:
            if member.value == info:
                return member
        logging.warning(f"Unknown team type '{info}', assumed open.")
        return TeamType.Open

    def toStore(self) -> str:
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

        x = t.extractOr('last_team_icon_update', 0)
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

    def toStore(self, includeChannels = True) -> dict:
        return { key: value for key, value in super().toStore().items()
            if (includeChannels or key != 'channels')
        }

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any):
        if memberName in ('updateTime', 'deleteTime', 'updateAvatarTime'):
            return Time(jsonMemberValue)
        elif memberName in ('id', 'description', 'inviteId'):
            return jsonMemberValue
        return NotImplemented

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
