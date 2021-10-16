'''
    Contains the history storage format and related utilites

    The format currently looks like
    channelname.meta.json
        - contains json equivalent of ChannelHeader
    channelname.data.json
        - contains newline separated sequence of compact json serializations of Post
        - posts are ordered by timestamp and should be continous
'''

from .bo import *
from .common import *
from .jsonvalidation import validate as validateJson, formatValidationErrors
from . import jsonvalidation
from collections.abc import Iterable

import json
import jsonschema
# HACK: Pyright linter doesn't recognize special meaning of ClassVar from .common in dataclasses
from typing import ClassVar


class PostOrdering(Enum):
    '''
        Describes how posts are organized in the storage
    '''

    Unsorted = 0  # May even have duplicates
    Ascending = 1  # Sorted from oldest to newest
    Descending = 2  # Sorted from newest to oldest
    AscendingContinuous = 3  # Sorted from oldest to newest, no posts missing in interval
    DescendingContinuous = 4  # Sorted from newest to oldest, no posts missing in interval

    @classmethod
    def fromStore(cls, info: str) -> 'PostOrdering':
        for member in cls:
            if info == member.name:
                return member
        else:
            logging.warning(
                f"Unknown channel ordering type '{info}', assumed unsorted.")
            return PostOrdering.Unsorted

    def toStore(self) -> str:
        return self.name

@dataclass
class PostStorage(JsonMessage):
    '''
        Note that if count == 0, other fields do not hold meaningful values.
    '''

    # Number of posts
    count: int = 0
    organization: PostOrdering = PostOrdering.Unsorted
    # If the first post is not completely first, here is post that we known to be before it (respecting ordering)
    postIdBeforeFirst: Optional[Id] = None
    # Create time of first post in the storage or some time point before it, if there are no posts up to that
    beginTime: Time = Time(0)
    firstPostId: Id = Id('')
    # Create time of last post in the storage or some time point after it, if there are no posts up to that
    endTime: Time = Time(0)
    lastPostId: Id = Id('')
    # If the post is not latest, this one shall be after it (respecting ordering)
    postIdAfterLast: Optional[Id] = None

    @staticmethod
    def empty() -> 'PostStorage':
        return PostStorage(misc={})

    def extend(self, other: 'PostStorage'):
        assert other.organization == self.organization
        if other.count > 0:
            assert self.lastPostId == other.postIdBeforeFirst
            self.count += other.count
            self.lastPostId = other.lastPostId
            self.endTime = other.endTime
            self.postIdAfterLast = other.postIdAfterLast

    @classmethod
    def fromStore(cls, info: dict) -> Optional['PostStorage']:
        storage = super().fromStore(info)
        if storage.count == 0:
            return None
        return storage

    @classmethod
    def memberFromStore(cls, memberName: str, jsonMemberValue: Any) -> Any:
        if memberName in ('firstPostId', 'lastPostId', 'postIdBeforeFirst', 'postIdAfterLast'):
            return jsonMemberValue
        return NotImplemented


@dataclass
class ChannelHeader:
    _schemaValidator: ClassVar[jsonschema.Draft7Validator]

    channel: Channel
    team: Optional[Team] = None  # Missing if channel is not scoped under team
    # Missing if channel has no messages, so `storage.count > 0` shall hold
    storage: Optional[PostStorage] = None
    # Users that appeared in conversations
    usedUsers: Set[User] = dataclassfield(default_factory=set)
    # Emojis that appeared in conversations
    usedEmojis: Set[Emoji] = dataclassfield(default_factory=set)

    @classmethod
    def fromStore(cls, info: Any):
        '''
            Loading previously saved header.
        '''
        def onWarning(w):
            if isinstance(w, jsonvalidation.UnsupportedVersion):
                logging.warning(
                    f'Loading channel from future version {w.found}, current version is 0. It may not be loadable and some data may be lost.')
            else:
                logging.warning(f"Channel header encountered warning '{w}', it may not be loadable correctly.")
        def onError(e):
            if isinstance(e, jsonvalidation.BadObject):
                logging.error(f"Failed to load channel header, loaded json object has unsupported type {e.recieved}.")
            else:
                assert isinstance(e, Iterable)
                logging.error("Configuration didn't match expected schema. " + formatValidationErrors(e))
            raise StoreError
        info = validateJson(info, cls._schemaValidator,
                            acceptedVersion='0', onWarning=onWarning, onError=onError)

        self = cast(ChannelHeader, ClassMock())
        self.channel = Channel.fromStore(info['channel'])
        if 'users' in info:
            self.usedUsers = set()
            for userInfo in info['users']:
                self.usedUsers.add(User.fromStore(userInfo))
        if 'team' in info:
            self.team = Team.fromStore(info['team'])
        if 'storage' in info:
            self.storage = PostStorage.fromStore(info['storage'])
        if 'emojis' in info:
            self.usedEmojis = set()
            for emojiInfo in info['emojis']:
                self.usedEmojis.add(Emoji.fromStore(emojiInfo))
        return cls(**self.__dict__)

    def update(self, other: 'ChannelHeader'):
        self.channel = other.channel
        if other.team is not None:
            self.team = other.team
        if other.storage is not None:
            if self.storage is not None:
                self.storage.extend(other.storage)
            else:
                self.storage = copy(other.storage)
        self.usedUsers = other.usedUsers | self.usedUsers
        self.usedEmojis = other.usedEmojis | self.usedEmojis

    def toStore(self) -> dict:
        content: Dict[str, Any] = {
            'version': '0'
        }
        if self.team:
            content.update(team=self.team.toStore(includeChannels=False))
        content.update(channel=self.channel.toStore())
        if self.storage is not None and self.storage.count > 0:
            content.update(storage=self.storage.toStore())
        if self.usedUsers:
            content.update(users=[u.toStore() for u in self.usedUsers])
        if self.usedEmojis:
            content.update(emojis=[e.toStore() for e in self.usedEmojis])

        return content

    @staticmethod
    def loadSchemaValidator() -> jsonschema.Draft7Validator:
        with open(sourceDirectory(__file__)/'header.schema.json') as schemaFile:
            return jsonschema.Draft7Validator(json.load(schemaFile))

ChannelHeader._schemaValidator = ChannelHeader.loadSchemaValidator()
