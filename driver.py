import json
# import os
import logging
import requests
from time import sleep
from typing import Any, BinaryIO, Callable, Dict, NamedTuple, NoReturn, Optional, TextIO, Union, cast


from bo import *
from config import ConfigFile

@dataclass
class Cache:
    users: Dict[Id, User] = dataclassfield(default_factory=dict)
    teams: Dict[Id, Team] = dataclassfield(default_factory=dict)
    emojis: Dict[Id, Emoji] = dataclassfield(default_factory=dict)

class MattermostDriver:
    API_PART = '/api/v4/'

    def __init__(self, config: ConfigFile):
        self.configfile: ConfigFile = config
        self.authorizationToken: Optional[str] = config.token if config.token else None
        # Information we get along the way
        self.context: Dict[str, str] = {}
        self.cache = Cache()

    def onBadHttpResponse(self, request: str, result: requests.Response) -> NoReturn:
        message = None
        messageExtra = None
        try:
            jsn = result.json()
            message = jsn['message']
            messageExtra = jsn['detailed_error']
        except Exception:
            pass
        logmessage = f"Request '{request}' failed with status code {result.status_code}.\nHTTP status: {result.reason}"
        if message:
            logmessage += "\nError message: " + message
        if messageExtra:
            logmessage += "\nError details: " + messageExtra
        logging.error(logmessage)
        result.raise_for_status()
        raise AssertionError # Never

    def delay(self):
        logging.debug(f"Waiting for {self.configfile.throttlingLoopDelay/1000}s ...")
        sleep(self.configfile.throttlingLoopDelay/1000)

    def getRaw(self, apiCommand: str, params: dict = {}) -> requests.Response:
        '''
            Common json returning request of GET variety.
            Arguments shall be already encoded in command
        '''
        headers = {}
        if self.authorizationToken:
            headers.update({'Authorization': 'Bearer '+self.authorizationToken})
        r = requests.get(self.configfile.hostname + self.API_PART + apiCommand, headers=headers, params=params)
        if r.status_code != 200:
            self.onBadHttpResponse(apiCommand, r)
        return r

    def get(self, apiCommand: str, params: dict = {}) -> Union[dict, list]:
        '''
            Common json returning request of GET variety.
            Arguments shall be already encoded in command
        '''
        apiCommand = apiCommand.format(**self.context)
        r = self.getRaw(apiCommand, params)
        return r.json()

    def storeUrlInto(self, url: str, fp: BinaryIO):
        response = self.getRaw(url)
        fp.write(response.content)

    def postRaw(self, apiCommand: str, data: Union[bytes, str]) -> requests.Response:
        '''
            Common json passing returning request of POST variety.
        '''
        headers = {}
        if self.authorizationToken:
            headers.update({'Token': self.authorizationToken})
        r = requests.post(self.configfile.hostname + self.API_PART + apiCommand, json.dumps(data), headers=headers)
        if r.status_code != 200:
            self.onBadHttpResponse(apiCommand, r)
        return r

    def post(self, apiCommand: str, data: dict) -> dict:
        '''
            Common json passing returning request of POST variety.
        '''
        apiCommand = apiCommand.format(**self.context)
        r = self.postRaw(apiCommand, data=json.dumps(data))
        return r.json()

    def login(self):
        r = self.postRaw('users/login', json.dumps({
            'login_id': self.configfile.username,
            'password': self.configfile.password
        }))

        self.authorizationToken = r.headers['Token']

    def getUserById(self, id: Id) -> User:
        if id in self.cache.users:
            return self.cache.users[id]

        userInfo = self.get('users/'+id)
        assert isinstance(userInfo, dict)
        u = User(userInfo)
        self.cache.users.update({u.id: u})
        return u

    def getUserByName(self, userName: str) -> User:
        for user in self.cache.users.values():
            if user.name == userName:
                return user

        userInfo = self.get('users/username/'+userName)
        assert isinstance(userInfo, dict)
        u = User(userInfo)
        self.cache.users.update({u.id: u})
        return u

    def loadLocalUser(self) -> User:
        u = self.getUserByName(self.configfile.username)
        self.context['userId'] = u.id
        return u

    def getTeams(self) -> Dict[Id, Team]:
        if len(self.cache.teams) != 0:
            return self.cache.teams
        teamInfos = self.get('users/{userId}/teams')
        assert isinstance(teamInfos, list)
        for teamInfo in teamInfos:
            t = Team(teamInfo)
            self.cache.teams.update({t.id: t})
        return self.cache.teams

    def getTeamById(self, teamId: Id) -> Team:
        return self.getTeams()[teamId]
    def getTeamByName(self, name: str) -> Team:
        teams = self.getTeams()
        for team in teams.values():
            if team.name == name:
                return team
        else:
            raise KeyError
    def getTeamByIntenalName(self, name: str) -> Team:
        teams = self.getTeams()
        for team in teams.values():
            if team.internalName == name:
                return team
        else:
            raise KeyError

    def loadChannels(self, teamId: Id = None):
        if not teamId:
            teamId = self.context['teamId']
        channelInfos = self.get(f'users/{{userId}}/teams/{teamId}/channels')
        t = self.cache.teams[teamId]
        assert isinstance(channelInfos, list)
        for chInfo in channelInfos:
            ch = Channel(chInfo)
            t.channels.update({ch.id: ch})

    def getChannelById(self, channelId: Id, teamId = None) -> Channel:
        if not teamId:
            teamId = self.context['teamId']
        return self.cache.teams[teamId].channels[channelId]
    def getChannelByName(self, name: str, teamId = None) -> Channel:
        if not teamId:
            teamId = self.context['teamId']
        for channel in self.cache.teams[teamId].channels.values():
            if channel.name == name:
                return channel
        else:
            raise KeyError

    def getDirectChannelNameByUserId(self, otherUserId: Id):
        localUserId = self.context['userId']
        if localUserId < otherUserId:
            return f'{localUserId}__{otherUserId}'
        else:
            return f'{otherUserId}__{localUserId}'
    def getDirectChannelNameByUserName(self, otherUserName: str):
        return self.getDirectChannelNameByUserId(self.getUserByName(otherUserName).id)

    def getDirectChannelByUserName(self, otherUserName: str, teamId = None) -> Channel:
        if not teamId:
            teamId = self.context['teamId']
        channelName = self.getDirectChannelNameByUserName(otherUserName)
        for channel in self.cache.teams[teamId].channels.values():
            if channel.type == ChannelType.Direct and channel.internalName == channelName:
                return channel
        else:
            raise KeyError

    def getUserIdFromDirectChannelName(self, channelName: str) -> Id:
        '''
            Gets userId of the nonlocal user in direct (private) channel.
        '''
        left, right = channelName.split('__')
        if left == self.context['userId']:
            return right
        else:
            return left


    def getChannelMembers(self, channel: Channel) -> List[User]:
        res = []

        page = 0
        params = {
            'per_page': 100
        }
        while True:
            params.update({'page': page})
            memberWindow = self.get(f'channels/{channel.id}/members', params)
            assert isinstance(memberWindow, list)
            for m in memberWindow:
                res.append(self.getUserById(m['user_id']))

            if len(memberWindow) == 0 or len(memberWindow) < 100:
                break

            page += 1
            self.delay()
        return res


    def processPosts(self, processor: Callable[[Post], None], channel: Channel = None, beforePost: Id = None, afterPost: Id = None, bufferSize: int = 60, maxCount: int = 0, offset: int = 0):
        if channel:
            channelId = channel.id
        else:
            channelId = self.context['channelId']

        params: Dict[str, Any] = {
            'per_page': bufferSize
        }
        if afterPost:
            params.update({'after': afterPost})
        if beforePost:
            params.update({'before': beforePost})

        postsRecieved = 0
        while True:
            if maxCount and maxCount - postsRecieved < bufferSize:
                params.update({'per_page': maxCount - postsRecieved})
            postWindow = self.get(f'channels/{channelId}/posts', params=params)
            assert isinstance(postWindow, dict)

            for postId in postWindow['order']:
                p = postWindow['posts'][postId]
                processor(Post(p))

            postsRecieved += len(postWindow['order'])
            if len(postWindow['order']) == 0 or postWindow['prev_post_id'] == '' or (maxCount and postsRecieved >= maxCount):
                break
            else:
                params.update({'before': postWindow['order'][-1]})
            sleep(self.configfile.throttlingLoopDelay / 1000) # Dump rate limit avoidance

    def getPosts(self, channel: Channel = None, *args, **kwargs) -> List[Post]:
        result = []
        def process(p: Post):
            result.append(p)
        self.processPosts(channel=channel, processor=process, *args, **kwargs)
        return result
    # def savePrivateHistory(self, otherUserName: str, outputFp: TextIO):
    #     otherUserId = self.getUserByName(otherUserName).id

    def processEmojiList(self, processor: Callable[[Emoji], None], bufferSize: int = 60, maxCount: int = 0):
        params = {
            'per_page': bufferSize
        }

        recieved = 0
        page = 0
        while True:
            if maxCount and maxCount - recieved < bufferSize:
                params.update({"per_page": maxCount - recieved})
            params.update({"page": page})
            emojiWindow = self.get('emoji', params)
            assert isinstance(emojiWindow, list)
            for emojiInfo in emojiWindow:
                e = Emoji(emojiInfo)
                self.cache.emojis.update({e.id: e})
                processor(e)
            recieved += len(emojiWindow)
            if len(emojiWindow) < bufferSize or (maxCount and recieved >= maxCount):
                break
            page += 1
            self.delay()

    def getEmojiList(self, *args, **kwargs) -> List[Emoji]:
        result = []
        def process(p: Emoji):
            result.append(p)
        self.processEmojiList(processor=process, *args, **kwargs)
        return result

    def getEmojiById(self, emojiId: Id) -> Emoji:
        if len(self.cache.emojis) == 0:
            self.getEmojiList()
        if emojiId in self.cache.emojis:
            return self.cache.emojis[emojiId]
        else:
            raise KeyError

    def getEmojiByName(self, emojiName: str) -> Emoji:
        if len(self.cache.emojis) == 0:
            self.getEmojiList()
        for emoji in self.cache.emojis.values():
            if emoji.name == emojiName:
                return emoji
        else:
            raise KeyError

    def getEmojiUrl(self, emoji: Emoji):
        return f'{self.configfile.hostname}{self.API_PART}emoji/{emoji.id}/image'

    def getFileUrl(self, file: FileAttachment, apiUrl = False) -> str:
        # Note: public access links may be available at files/{fileId}/link, but may be unimplemented by server
        if apiUrl:
            return f'files/{file.id}'
        else:
            return f'{self.configfile.hostname}{self.API_PART}files/{file.id}'
