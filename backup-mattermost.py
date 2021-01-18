

from datetime import time
import json
import os
import logging
from typing import Any, Callable, Dict, NamedTuple, NoReturn, Optional, TextIO, Union, cast
from pprint import pprint as pp
import requests
from time import sleep

from orm import *

config = json.load(open('config.json'))

class ConfigFile(NamedTuple):
    hostname: str
    username: str
    password: str = ''
    token: str = ''

config = ConfigFile(
    hostname=config['hostname'],
    username=config['username'],
    password=config.get('password', os.environ.get('MATTERMOST_PASSWORD', '')),
    token=config.get('token', os.environ.get('MATTERMOST_TOKEN', '')),
)

@dataclass
class Cache:
    users: Dict[Id, User] = dataclassfield(default_factory=dict)
    teams: Dict[Id, Team] = dataclassfield(default_factory=dict)
    emojis: Dict[Id, Emoji] = dataclassfield(default_factory=dict)

class Mattermost:
    def __init__(self, config):
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

    def getRaw(self, apiCommand: str, params: dict = {}) -> requests.Response:
        '''
            Common json returning request of GET variety.
            Arguments shall be already encoded in command
        '''
        headers = {}
        if self.authorizationToken:
            headers.update({'Authorization': 'Bearer '+self.authorizationToken})
        r = requests.get(self.configfile.hostname + '/api/v4/' + apiCommand, headers=headers, params=params)
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

    def postRaw(self, apiCommand: str, data: Union[bytes, str]) -> requests.Response:
        '''
            Common json passing returning request of POST variety.
        '''
        headers = {}
        if self.authorizationToken:
            headers.update({'Token': self.authorizationToken})
        r = requests.post(self.configfile.hostname + '/api/v4/' + apiCommand, json.dumps(data), headers=headers)
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

    def loadLocalUser(self):
        m.context['userId'] = cast(dict, m.get('users/username/'+config.username))['id']

    def getUserById(self, id: Id) -> User:
        if id in self.cache.users:
            return self.cache.users[id]

        userInfo = self.get('users/'+id)
        assert isinstance(userInfo, dict)
        u = User.load(userInfo)
        self.cache.users.update({u.id: u})
        return u

    def getUserByName(self, userName: str) -> User:
        for user in self.cache.users.values():
            if user.userName == userName:
                return user

        userInfo = self.get('users/username/'+userName)
        assert isinstance(userInfo, dict)
        u = User.load(userInfo)
        self.cache.users.update({u.id: u})
        return u

    def loadTeams(self):
        teamInfos = m.get('users/{userId}/teams')
        assert isinstance(teamInfos, list)
        for teamInfo in teamInfos:
            t = Team.load(teamInfo)
            self.cache.teams.update({t.id: t})

    def getTeamByName(self, name: str) -> Team:
        for team in self.cache.teams.values():
            if team.name == name:
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
            ch = Channel.load(chInfo)
            t.channels.update({ch.id: ch})

    def getChannelByName(self, name: str, teamId = None) -> Channel:
        if not teamId:
            teamId = self.context['teamId']
        for channel in self.cache.teams[teamId].channels.values():
            if channel.name == name:
                return channel
        else:
            raise KeyError

    def getDirectChannelByUserName(self, otherUserName: str, teamId = None) -> Channel:
        if not teamId:
            teamId = self.context['teamId']
        otherUser = self.getUserByName(otherUserName)
        if self.context['userId'] < otherUser.id:
            channelName = f'{self.context["userId"]}__{otherUser.id}'
        else:
            channelName = f'{otherUser.id}__{self.context["userId"]}'
        for channel in self.cache.teams[teamId].channels.values():
            if channel.type == ChannelType.Direct and channel.internalName == channelName:
                return channel
        else:
            raise KeyError

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
                processor(Post.load(p))

            postsRecieved += len(postWindow['order'])
            if len(postWindow['order']) == 0 or postWindow['prev_post_id'] == '' or (maxCount and postsRecieved >= maxCount):
                break
            else:
                params.update({'before': postWindow['order'][-1]})
            sleep(1) # Dump rate limit avoidance

    def getPosts(self, channel: Channel = None, *args, **kwargs) -> List[Post]:
        result = []
        def process(p: Post):
            result.append(p)
        self.processPosts(channel=channel, processor=process, *args, **kwargs)
        return result
    # def savePrivateHistory(self, otherUserName: str, outputFp: TextIO):
    #     otherUserId = self.getUserByName(otherUserName).id


m = Mattermost(config)

# m.onBadHttpResponse = lambda a, b: breakpoint()
if config.token == '':
    m.login()
m.loadLocalUser()
m.loadTeams()
# m.context['teamId'] = m.getTeamByName('TeamName').id
m.loadChannels()
# pp(m.getPosts(m.getChannelByName('channelName'), maxCount=3))
# m.processPosts(channel=m.getDirectChannelByUserName('user.name'), processor=pp, maxCount=0)
# with open('user.json', 'a') as of:
#     m.savePrivateHistory('user.name, of)
# pp([team['display_name'] for team in m.get('teams')])
# print(m.get('users/aj9dfroweinpjnxcorxbqqwfyw/teams/8g9zx693efnnuxdyu7muqcsf6e/channels'))

# response = requests.get('https://www.seznam.cz')
# print('Headers: ', response.headers)
# # print('Content: ', response.content[1000:], '...')
# print('Content-length: ', len(response.content))
# with open('output.html', 'wb') as out:
#     out.write(response.content)
