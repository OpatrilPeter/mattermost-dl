'''
    Contains the history storage format and related utilites

    The format currently looks like
    channelname.meta.json
        - contains json equivalent of ChannelHeader
    channelname.data.json
        - contains newline separated sequence of compact json serializations of Post
        - posts are ordered by timestamp and should be continous (precise ordering is specified in header)
'''

from .common import *

from .bo import *
from .config import ChannelOptions, OrderDirection
from .driver import MattermostDriver
from .jsonvalidation import validate as validateJson, formatValidationErrors
from . import jsonvalidation

from collections.abc import Iterable
import json
import jsonschema
from os import stat_result
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
        Note that if count == 0, other fields do not have to hold meaningful values.
    '''

    # Number of posts
    count: int = 0
    organization: PostOrdering = PostOrdering.Unsorted
    byteSize: int = 0
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
    def fromOptions(options: ChannelOptions) -> 'PostStorage':
        '''
            Constructs fresh, partially initialized storage suitable
            for incremental filling by `addSortedPost`, followed
            by correcting the byteSize.
        '''
        storage = PostStorage(misc={})
        if options.downloadTimeDirection == OrderDirection.Asc:
            storage.organization = PostOrdering.AscendingContinuous

            if options.postsAfterTime is not None:
                storage.beginTime = options.postsAfterTime
        else:
            assert options.downloadTimeDirection == OrderDirection.Desc
            storage.organization = PostOrdering.DescendingContinuous

            if options.postsBeforeTime is not None:
                storage.beginTime = options.postsBeforeTime
        return storage


    def addSortedPost(self, p: Post, postOrderHints: MattermostDriver.PostHints, ordering: OrderDirection):
        if self.count == 0:
            self.firstPostId = p.id
            if self.beginTime == Time(0):
                self.beginTime = p.createTime
            self.postIdBeforeFirst = postOrderHints.postIdBefore if ordering == OrderDirection.Asc else postOrderHints.postIdAfter
        self.lastPostId = p.id
        self.endTime = p.createTime
        self.postIdAfterLast = postOrderHints.postIdAfter if ordering == OrderDirection.Asc else postOrderHints.postIdBefore

        self.count += 1


    def update(self, other: 'PostStorage'):
        '''
            Updates old post storage with freshly downloaded content.
            Does not represent concatenation of arbitrary storages.
        '''
        assert other.organization == self.organization
        if other.count > 0:
            assert self.lastPostId == other.postIdBeforeFirst
            self.count += other.count
            self.byteSize = other.byteSize
            self.lastPostId = other.lastPostId
            self.endTime = other.endTime
            self.postIdAfterLast = other.postIdAfterLast

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
    # (as long as header is not currently getting filled)
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
                logging.error("Channel header didn't match expected schema. " + formatValidationErrors(e))
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
            storage = PostStorage.fromStore(info['storage'])
            if storage.count != 0:
                self.storage = storage
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
                self.storage.update(other.storage)
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

@dataclass
class ChannelFileInfo:
    '''
        Represents information about stored channel archive.

        Contains file stats for header and data (posts containg) file, useful mainly for
        checking that files weren't modified since they were read from.
    '''
    header: ChannelHeader
    headerFileStats: stat_result
    dataFileStats: Optional[stat_result] = None

    @classmethod
    def load(cls, channel: Channel, headerFilename: Path, dataFilename: Path) -> Optional['ChannelFileInfo']:
        '''
            Attempts to load channel header, without validation of the posts storage.
        '''
        if not headerFilename.is_file():
            return None

        headerStat = headerFilename.stat()
        dataStat = dataFilename.stat() if dataFilename.is_file() else None

        with open(headerFilename, 'r', encoding='utf8') as headerFile:
            try:
                return ChannelFileInfo(ChannelHeader.fromStore(json.load(headerFile)), headerStat, dataStat)
            except Exception:
                logging.warning(exceptionFormatter(f"Unable to load existing metadata for channel '{channel.internalName}'."))
                return None
