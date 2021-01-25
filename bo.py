'''
    Defines "business objects",
    OOP representations of Mattermost entities
'''

from datetime import datetime
from dataclasses import dataclass, field as dataclassfield
from enum import Enum
from functools import total_ordering
import logging
from typing import Any, Dict, List, Optional

@total_ordering
class Time:
    def __init__(self, posixTimestampMs: int):
        self._time: int = posixTimestampMs

    # Returns unix timestamp in miliseconds
    @property
    def timestamp(self) -> int:
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

Id = str

class JsonMessage:
    def __init__(self, info: dict):
        self.misc = info

    def extract(self, attrName: str) -> Any:
        assert attrName in self.misc
        res = self.misc[attrName]
        del self.misc[attrName]
        if len(self.misc) == 0:
            del self.misc
        return res

    def extract_or(self, attrName: str, fallback: Any) -> Any:
        if attrName not in self.misc:
            return fallback
        res = self.extract(attrName)
        if res:
            return res
        else:
            return fallback
    def __repr__(self):
        return f'{type(self).__name__}({ {key: val for key, val in self.__dict__.items() if not hasattr(val, "__call__")} })'

class User(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        self.id: Id = self.extract('id')
        self.name: str = self.extract('username')
        self.nickname: str = self.extract('nickname')
        self.firstName: str = self.extract('first_name')
        self.lastName: str = self.extract('last_name')

class Emoji(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.creatorId: Id = self.extract('creator_id')
        self.name: str = self.extract('name')
        self.createTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deleteTime: Time = Time(x)

# @dataclass
# class FileAttachment:
#     name: str
#     url: str

# @dataclass
# class PostReaction:
#     userId: Id
#     createTime: Time
#     emoji: Emoji

@dataclass
class Post(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)
        x: Any
        self.id: Id = self.extract('id')
        self.userId: Id = self.extract('user_id')
        self.createTime: Time = Time(self.extract('create_at'))
        self.message: str = self.extract('message')
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        # Last "visible edit" time (small updates after posting/public update are ignored)
        x = self.extract('edit_at')
        if x != 0:
            self.publicUpdateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deleteTime: Time = Time(x)
        x = self.extract_or('parent_id', 0)
        if x:
            self.parent: Id = x
        if self.extract_or('is_pinned', False):
            self.isPinned: bool = True
        x = self.extract('type')
        if x:
            self.specialMsgType: str = x
            self.specialMsgProperties: dict = self.extract('props')

        self.attachments = [], # TODO
        self.reactions = [] # TODO

    def __str__(self):
        return f'Post(u={self.userId}, t={self.createTime}, m={self.message})'


class ChannelType(Enum):
    Open = 0
    Private = 1
    Group = 2
    Direct = 3

    @staticmethod
    def load(info: str) -> 'ChannelType':
        if info == 'D':
            return ChannelType.Direct
        elif info == 'P':
            return ChannelType.Private
        elif info == 'G':
            return ChannelType.Group
        else:
            if info != 'O':
                logging.warning(f"Unknown channel type '{info}', assumed open.")
            return ChannelType.Open

class Channel(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.name: str = self.extract('display_name')
        self.internalName: str = self.extract('name')
        self.creationTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.creationTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deletionTime: Time = Time(x)
        self.type: ChannelType = ChannelType.load(self.extract('type'))
        x = self.extract('header')
        if x:
            self.header: str = x
        x = self.extract('purpose')
        if x:
            self.purpose: str = x

        self.lastMessageTime: Time = Time(self.extract('last_post_at'))
        self.messageCount = self.extract('total_msg_count')
        x = self.extract('creator_id')
        if x:
            self.creatorUserId: Id = x

        self.extract('team_id')
        self.extract('extra_update_at')

    def __str__(self):
        return f'Channel({self.internalName})'

class Team(JsonMessage):
    def __init__(self, info: dict) -> None:
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.name: str = self.extract('display_name')
        self.internalName: str = self.extract('name')

        x = self.extract('description')
        if x:
            self.description: str = x

        self.channels: Dict[Id, Channel] = {}

    def __str__(self):
        return f'Team({self.internalName})'

