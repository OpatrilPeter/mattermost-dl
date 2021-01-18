
from datetime import datetime
from dataclasses import dataclass, field as dataclassfield
from enum import Enum
import logging
from typing import Dict, List, Optional

class Time:
    def __init__(self, posixTimestamp):
        self._time = datetime.fromtimestamp(posixTimestamp)
    def __str__(self):
        fmt = self._time.isoformat()
        fractionStart = fmt.rfind('.')
        if fractionStart != -1:
            fmt = fmt[:fractionStart]
        return fmt
    def __repr__(self):
        return f"'{self._time.isoformat()}'"
    @classmethod
    def load(cls, number: int) -> 'Time':
        return cls(posixTimestamp=number/1000)

Id = str

@dataclass
class User:
    id: str
    userName: str
    firstName: str
    lastName: str

    @classmethod
    def load(cls, info: dict) -> 'User':
        return cls(
            id=info['id'],
            userName=info['username'],
            firstName=info['first_name'],
            lastName=info['last_name'],
        )

# @dataclass
# class PostMetadata:
#     pass

@dataclass
class Emoji:
    id: Id
    creatorId: Id
    name: str
    url: str
    createTime: Time
    updateTime: Time
    deleteTime: Time

@dataclass
class FileAttachment:
    name: str
    url: str

@dataclass
class PostReaction:
    userId: Id
    createTime: Time
    emoji: Emoji

@dataclass
class Post:
    id: Id
    userId: Id
    createTime: Time
    message: str
    updateTime: Optional[Time] # Last update time
    publicUpdateTime: Optional[Time] # Last "visible edit" time (small updates after posting/public update are ignored)
    deleteTime: Optional[Time]
    parent: Optional[Id] # For chained messages
    isPinned: Optional[bool] # True or None

    # If message is nonstandard, this describes its kind
    specialMsgType: Optional[str]
    # Arguments for given special message
    specialMsgProperties: Optional[dict]
    attachments: List[FileAttachment]
    reactions: List[PostReaction]

    @classmethod
    def load(cls, info: dict) -> 'Post':
        return cls(
            id=info['id'],
            userId=info['user_id'],
            createTime=Time.load(info['create_at']),
            message=info['message'],
            updateTime=Time.load(info['update_at']) if info['update_at'] != info['create_at'] else None,
            publicUpdateTime=Time.load(info['edit_at']) if info['edit_at'] != 0 else None,
            deleteTime=Time.load(info['delete_at']) if info['delete_at'] != 0 else None,
            parent=info['parent_id'] if info['parent_id'] != '' else None,
            isPinned=info['is_pinned'] if info['is_pinned'] == True else None,
            specialMsgType=info['type'] if info['type'] != '' else None,
            specialMsgProperties=info['props'] if info['type'] != '' else None,
            attachments=[], # TODO
            reactions=[] # TODO
        )

class ChannelType(Enum):
    Open = 0
    Private = 1
    Group = 2
    Direct = 3

    @classmethod
    def load(cls, info: str) -> 'ChannelType':
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

@dataclass
class Channel:
    id: str
    name: str # display_name
    internalName: str
    type: ChannelType
    header: str
    purpose: str
    messageCount: int
    creatorUserId: Optional[Id]
    creationTime: Time

    @classmethod
    def load(cls, info: dict) -> 'Channel':
        return cls(
            id=info['id'],
            name=info['display_name'],
            type=ChannelType.load(info['type']),
            internalName=info['name'],
            header=info['header'],
            purpose=info['purpose'],
            messageCount=info['total_msg_count'],
            creatorUserId=info['creator_id'] if info['creator_id'] != '' else None,
            creationTime=Time.load(info['create_at'])
        )


@dataclass
class Team:
    id: str
    name: str # display_name
    description: Optional[str] = None
    channels: Dict[Id, Channel] = dataclassfield(default_factory=dict)

    @classmethod
    def load(cls, info: dict) -> 'Team':
        return cls(
            id=info['id'],
            name=info['display_name'],
            description=info['description'],
        )
