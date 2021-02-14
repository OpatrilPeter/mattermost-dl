'''
    Contains the history storage format and related utilites

    The format currently looks like
    channelname.meta.json
        - contains json equivalent of ChannelHeader
    channelname.data.json
        - contains newline separated sequence of compact json serializations of Post
'''

from bo import *
from common import *
from driver import MattermostDriver

@dataclass
class ChannelHeader:
    firstPostTime: Optional[Time]
    firstPostId: Optional[Id]
    # If set, posts from the start of the channel up to this time are archived
    lastPostTime: Optional[Time]
    # If set, posts from the start of the channel up to this post id are archived
    lastPostId: Optional[Id]
    # Users that appeared in conversations
    usedUsers: Set[User]
    # Emojis that appeared in conversations
    usedEmojis: Set[Emoji]
    team: Optional[Team]
    channel: Channel

    def __init__(self, channel: Channel, team: Team = None):
        self.channel: Channel = channel
        self.team = team
        self.firstPostTime = None
        self.firstPostId = None
        self.lastPostTime = None
        self.lastPostId = None
        self.usedUsers = set()
        self.usedEmojis = set()

    def load(self, info: dict, driver: MattermostDriver):
        '''
            Loading previously saved header.
        '''
        if 'storage' in info:
            storageInfo = info['storage']
            self.firstPostTime: Optional[Time] = Time(storageInfo['firstPostTime'])
            self.firstPostId: Optional[Id] = storageInfo['fistPostId']
            self.lastPostTime: Optional[Time] = Time(storageInfo['lastPostTime'])
            self.lastPostId: Optional[Id] = Id(storageInfo['lastPostId'])
        else:
            self.firstPostTime = None
            self.firstPostId = None
            self.lastPostTime = None
            self.lastPostId = None
        if 'users' in info:
            # TODO: load users from json
            for userInfo in info['users']:
                u = None
                if 'id' in userInfo:
                    u = driver.getUserById(userInfo['id'])
                elif 'name' in userInfo:
                    u = driver.getUserByName(userInfo['name'])
                if u is not None:
                    self.usedUsers.add(u)
            # TODO: load emojis

    def save(self) -> dict:
        content = {}
        if self.team:
            content.update(team=self.team.toJson(includeChannels=False))
        content.update(channel=self.channel.toJson())
        if self.firstPostId is not None:
            content.update(storage={
                'firstPostTime': self.firstPostTime,
                'firstPostId': self.firstPostId,
                'lastPostTime': self.lastPostTime,
                'lastPostId': self.lastPostId,
            })
        content.update(users=[u.toJson() for u in self.usedUsers])
        content.update(emojis=[e.toJson() for e in self.usedEmojis])

        return content
