'''
    Defines "business objects",
    OOP representations of Mattermost entities
'''

from datetime import datetime
from dataclasses import dataclass, field as dataclassfield
from enum import Enum
from functools import total_ordering
import logging
from numbers import Number
from typing import Any, Dict, List, Optional, Union

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

Id = str

class JsonMessage:
    def __init__(self, info: dict):
        self.misc = info

    def drop(self, attrName: str):
        if attrName in self.misc:
            del self.misc[attrName]

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

    def toJson(self) -> Any:
        return self.__dict__

    def cleanMisc(self):
        '''
            Removes stuff from unknown post data that seem like default values.
        '''
        if hasattr(self, 'misc'):
            newMisc = {key: value for key, value in self.misc.items()
                if not (
                    value is None
                    or value == ''
                    or (isinstance(value, dict) and len(value) == 0))
            }
            if len(newMisc) == 0:
                del self.misc
            else:
                self.misc = newMisc

class User(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.name: str = self.extract('username')
        x = self.extract('nickname')
        if x:
            self.nickname: str = x
        self.firstName: str = self.extract('first_name')
        self.lastName: str = self.extract('last_name')

        self.createTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deleteTime: Time = Time(x)
        x = self.extract_or('last_picture_update', 0)
        if x != 0 and x != self.createTime.timestamp:
            self.updateAvatarTime = Time(x)

        x = self.extract('roles').split(',')
        if 'system_user' in x and len(x) == 1:
            pass
        else:
            self.roles: List[str] = x

        # Things we explicitly don't care about
        self.drop('locale')
        self.drop('timezone')
        self.drop('notify_props')
        self.drop('email')
        self.drop('email_verified')
        self.drop('auth_service')
        self.drop('last_password_update')

        self.cleanMisc()

class Emoji(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.creatorId: Id = self.extract('creator_id')
        self.creator: User # Redundant, optional
        self.creatorName: str # Redundant, optional
        self.name: str = self.extract('name')
        self.imageUrl: str
        self.createTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deleteTime: Time = Time(x)

        self.cleanMisc()

class FileAttachment(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.name: str = self.extract('name')
        self.url: str
        self.byteSize: int = self.extract('size')
        self.mimeType: int = self.extract('mime_type')
        self.createTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x:
            self.deleteTime: Time = Time(x)

        # We don't need derived properties
        self.drop('user_id')
        self.drop('post_id')
        self.drop('width')
        self.drop('height')
        self.drop('has_preview_image')
        self.drop('mini_preview')
        self.drop('extension')

        self.cleanMisc()

class PostReaction(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        self.userId: Id = self.extract('user_id')
        self.userName: str # redundant, optional
        self.createTime: Time = Time(self.extract('create_at'))
        self.emojiName: str = self.extract('emoji_name')
        self.emoji: Emoji # redundant, optional

        self.drop('post_id')

        self.cleanMisc()

@dataclass
class Post(JsonMessage):
    def __init__(self, info: dict):
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.userId: Id = self.extract('user_id')
        self.userName: str # redundant, optional
        self.user: User # redundant, optional
        self.createTime: Time = Time(self.extract('create_at'))
        self.message: str = self.extract('message')
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        # Last "visible edit" time (small updates after posting/public update are ignored)
        x = self.extract('edit_at')
        if x != 0 and x != self.updateTime.timestamp:
            self.publicUpdateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x != 0:
            self.deleteTime: Time = Time(x)
        # Parent post (if this post is a reply)
        x = self.extract_or('parent_id', 0)
        if x:
            self.parent: Id = x
        if self.extract_or('is_pinned', False):
            self.isPinned: bool = True
        x = self.extract('type')
        if x:
            self.specialMsgType: str = x
            self.specialMsgProperties: dict = self.extract('props')
        else:
            self.misc['props'] = {
                key: value for key, value in self.misc['props'].items()
                    if key not in ('disable_group_highlight')
            }

        metadata = self.extract('metadata')
        if 'embeds' in metadata:
            # We ignore these, as there is nothing that can't be restructured from message
            # TODO: remove warning
            logging.warning("Ignoring embeds: {}", metadata['embeds'])
            del metadata['embeds']
        if 'emojis' in metadata:
            self.emojis: Union[List[Emoji], List[Id]] = [Emoji(emoji)
                for emoji in metadata['emojis']
            ]
            del metadata['emojis']
        if 'files' in metadata:
            self.attachments: List[FileAttachment] = [FileAttachment(fileInfo)
                for fileInfo in metadata['files']
            ]
            del metadata['files']
        if 'images' in metadata:
            # images only contain redundant metadata
            del metadata['images']
        if 'reactions' in metadata:
            self.reactions: List[PostReaction] = [PostReaction(reaction)
                for reaction in metadata['reactions']
            ]
            del metadata['reactions']
        if len(metadata) != 0:
            self.misc['metadata'] = metadata

        self.drop('channel_id')
        self.drop('root_id')
        self.drop('reply_count')
        self.drop('has_reactions')
        # Deprecated form of file attachment metadata
        self.drop('file_ids')
        # Contains automatically extracted hashtags from the message (usually wrong)
        self.drop('hashtags')

        self.cleanMisc()

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

    def toJson(self) -> str:
        return self.name

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

        self.drop('team_id')
        self.drop('extra_update_at')

        self.cleanMisc()

    def __str__(self):
        return f'Channel({self.internalName})'

class Team(JsonMessage):
    def __init__(self, info: dict) -> None:
        super().__init__(info)

        x: Any

        self.id: Id = self.extract('id')
        self.name: str = self.extract('display_name')
        self.internalName: str = self.extract('name')
        self.createTime: Time = Time(self.extract('create_at'))
        x = self.extract('update_at')
        if x != self.createTime.timestamp:
            self.updateTime: Time = Time(x)
        x = self.extract('delete_at')
        if x:
            self.deleteTime: Time = Time(x)
        x = self.extract('description')
        if x:
            self.description: str = x

        x = self.extract_or('last_team_icon_update', 0)
        if x != 0 and x != self.createTime.timestamp:
            self.updateAvatarTime = Time(x)


        self.drop('allowed_domains')

        self.cleanMisc()


        self.channels: Dict[Id, Channel] = {}


    def toJson(self, includeChannels = True):
        return { key: value for key, value in self.__dict__.items()
            if (includeChannels or key != 'channels')
        }

    def __str__(self):
        return f'Team({self.internalName})'

