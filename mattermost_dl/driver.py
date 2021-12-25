'''
    Implements Mattermost driver, object that logically
    represent (connection to) Mattermost server
'''

from .common import *
from .bo import *
from .config import ConfigFile, OrderDirection

import json
import requests
from time import sleep

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
        self.context: Dict[str, Any] = {}
        self.cache = Cache()
        self.session = requests.Session()

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
        r = self.session.get(self.configfile.hostname + self.API_PART + apiCommand, headers=headers, params=params)
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
        r = r.json()
        # We're guaranteeing certain types on output
        if not isinstance(r, (dict, list)):
            raise TypeError
        return r

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
        r = self.session.post(self.configfile.hostname + self.API_PART + apiCommand, data, headers=headers)
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
        u = User.fromMattermost(userInfo)
        self.cache.users.update({u.id: u})
        return u

    def getUserByName(self, userName: str) -> User:
        for user in self.cache.users.values():
            if user.name == userName:
                return user

        userInfo = self.get('users/username/'+userName)
        assert isinstance(userInfo, dict)
        u = User.fromMattermost(userInfo)
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
            t = Team.fromMattermost(teamInfo)
            self.cache.teams.update({t.id: t})
        return self.cache.teams

    def getTeamById(self, teamId: Id) -> Team:
        return self.getTeams()[teamId]
    def getTeamByName(self, name: str) -> Team:
        teams = self.getTeams()
        for team in teams.values():
            if team.name == name:
                return team
        raise KeyError
    def getTeamByIntenalName(self, name: str) -> Team:
        teams = self.getTeams()
        for team in teams.values():
            if team.internalName == name:
                return team
        raise KeyError

    def loadChannels(self, teamId: Id = None):
        if not teamId:
            teamId = Id(self.context['teamId'])
        channelInfos = self.get(f'users/{{userId}}/teams/{teamId}/channels')
        t = self.cache.teams[teamId]
        assert isinstance(channelInfos, list)
        for chInfo in channelInfos:
            ch = Channel.fromMattermost(chInfo)
            t.channels.update({ch.id: ch})

    def getChannelById(self, channelId: Id, teamId: Id = None) -> Channel:
        if teamId is None:
            teamId = self.context['teamId']
            assert teamId is not None
        return self.cache.teams[teamId].channels[channelId]
    def getChannelByName(self, name: str, teamId: Id = None) -> Channel:
        if teamId is None:
            teamId = self.context['teamId']
            assert teamId is not None
        for channel in self.cache.teams[teamId].channels.values():
            if channel.name == name:
                return channel
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
        raise KeyError

    def getUserIdFromDirectChannelName(self, channelName: str) -> Id:
        '''
            Gets userId of the nonlocal user in direct (private) channel.
        '''
        left, right = channelName.split('__')
        if left == self.context['userId']:
            return Id(right)
        else:
            return Id(left)

    def loadChannelMembers(self, channel: Channel):
        if channel.members is not None:
            return

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

        channel.members = res

    def getPostById(self, postId: Id) -> Post:
        postInfo = self.get(f'/posts/{postId}')
        assert isinstance(postInfo, dict)
        return Post.fromMattermost(postInfo)

    @dataclass
    class PostHints:
        processedCount: int = 0
        # Id of post directly chronologically preceding current one. None if the post is first in channel
        postIdBefore: Optional[Id] = None
        # Id of post directly chronologically succeeding current one. None if the post is last in channel
        postIdAfter: Optional[Id] = None

    class ProcessPostResult(Enum):
        NothingRequested = enumerator()
        NoMorePosts = enumerator()
        MaxCountReached = enumerator()
        ConditionReached = enumerator()

    # REFACTORME: this function could be simplified, possibly separate downloading from filtering by additional callbacks
    def processPosts(self, processor: Callable[[Post, 'MattermostDriver.PostHints'], None],
            channel: Optional[Channel] = None, *,
            beforePost: Optional[Id] = None, afterPost: Optional[Id] = None,
            beforeTime: Optional[Time] = None, afterTime: Optional[Time] = None,
            bufferSize: int = 60, maxCount: int = 0, offset: int = 0,
            timeDirection: OrderDirection = OrderDirection.Asc,
            onSkippedPost: Callable[[], None] = (lambda: None)
            ) -> 'MattermostDriver.ProcessPostResult':
        '''
            Main function to load all channel's posts.
            Loading happens lazily in batches, each post is passed to external callable.

            Processing order works according to following logic:
                - add afterPost/beforePost filters. They work serverside and will limit the fetched output
                - in descending order
                    - apply offset
                    - start reading pages, after first page set beforePost to earliest post and read page 0
                        - skip until beforeTime filter matches, then start processing
                        - continue collecting until end, maxCount or afterTime is reached
                - in ascending order
                    - if afterPost filter exist
                        - apply offset
                    - else
                        - set page according to total message count so that the final page would be shown
                        - if the fetched page isn't, in fact, final (due to total message count being approximate),
                            continue into history
                        - subtract offset
                    - start reading pages, after first page set afterPost to latest post and read page 0
                    - skip until afterTime filter matches, then start processing
                    - continue collecting until end, maxCount or beforeTime is reached
        '''
        if channel:
            channelId = channel.id
        else:
            channelId = Id(self.context['channelId'])
            channel = self.getChannelById(channelId)

        params: Dict[str, Any] = {
            'per_page': bufferSize
        }
        if afterPost:
            params.update(after=afterPost)
        if beforePost:
            params.update(before=beforePost)

        if afterTime and beforeTime and afterTime < beforeTime:
            return self.ProcessPostResult.NothingRequested
        # Note that messageCount may be inaccurate
        # if offset >= channel.messageCount:
        #     return self.ProcessPostResult.NoMorePosts

        page: int = 0
        # How many messages on page shall be ignored (in the download direction)
        pageOffset: int = 0
        if timeDirection == OrderDirection.Desc or afterPost:
            page = offset // bufferSize
            pageOffset = offset % bufferSize
        else:
            absoluteMessageOffset = channel.messageCount
            page = max(0, channel.messageCount // bufferSize - int(channel.messageCount % bufferSize == 0))
            while True:
                postWindow = self.get(f'channels/{channelId}/posts', {'per_page': bufferSize, 'page': page})
                assert isinstance(postWindow, dict)

                # We're touching last page, yet there's more posts -> not truly last page
                if postWindow['prev_post_id'] != '':
                    page += 1
                    continue
                break

            absoluteMessageOffset = page * bufferSize + len(postWindow['order']) - offset
            page = max(0, absoluteMessageOffset // bufferSize - int(absoluteMessageOffset % bufferSize == 0))
            if offset > channel.messageCount % bufferSize:
                pageOffset = bufferSize - absoluteMessageOffset % bufferSize
            else:
                pageOffset = offset
            assert pageOffset < bufferSize # Sanity check

        postHints = self.PostHints()
        while True:
            if page != 0:
                params.update(page=page)
            postWindow = self.get(f'channels/{channelId}/posts', params=params)
            assert isinstance(postWindow, dict)

            stopReason: Optional[MattermostDriver.ProcessPostResult] = None

            if timeDirection == OrderDirection.Desc:
                for windowIndex, postId in enumerate(postWindow['order'][pageOffset:]):
                    p = postWindow['posts'][postId]
                    postHints.postIdBefore = postWindow['order'][windowIndex + 1] if windowIndex + 1 < len(postWindow['order']) else postWindow['prev_post_id'] if postWindow['prev_post_id'] != '' else None
                    postHints.postIdAfter = postWindow['order'][windowIndex - 1] if windowIndex - 1 >= 0 else postWindow['next_post_id'] if postWindow['next_post_id'] != '' else None
                    if ((afterPost and p['id'] == afterPost)
                        or (afterTime and p['create_at'] < afterTime.timestamp)):
                        stopReason = self.ProcessPostResult.ConditionReached
                        break
                    if maxCount and postHints.processedCount == maxCount:
                        stopReason = self.ProcessPostResult.MaxCountReached
                        break
                    if beforeTime and p['create_at'] >= beforeTime.timestamp:
                        onSkippedPost()
                        continue
                    processor(Post.fromMattermost(p), postHints)
                    postHints.processedCount += 1
            else: # timeDirection == OrderDirection.Asc
                windowIndex = len(postWindow['order'])-pageOffset - 1
                for postId in reversed(postWindow['order'][:windowIndex + 1]):
                    p = postWindow['posts'][postId]
                    postHints.postIdBefore = postWindow['order'][windowIndex + 1] if windowIndex + 1 < len(postWindow['order']) else postWindow['prev_post_id'] if postWindow['prev_post_id'] != '' else None
                    postHints.postIdAfter = postWindow['order'][windowIndex - 1] if windowIndex - 1 >= 0 else postWindow['next_post_id'] if postWindow['next_post_id'] != '' else None
                    windowIndex -= 1
                    if ((beforePost and p['id'] == beforePost)
                        or (beforeTime and p['create_at'] > beforeTime.timestamp)):
                        stopReason = self.ProcessPostResult.ConditionReached
                        break
                    if maxCount and postHints.processedCount == maxCount:
                        stopReason = self.ProcessPostResult.MaxCountReached
                        break
                    if afterTime and p['create_at'] <= afterTime.timestamp:
                        onSkippedPost()
                        continue
                    processor(Post.fromMattermost(p), postHints)
                    postHints.processedCount += 1

            # No messages recieved?
            if len(postWindow['order']) == 0:
                # If we iterate from the end of the list, we may simply look beyond the end as channel message count is approximate
                # (doesn't subtract deleted messages that aren't returned for common users)
                if timeDirection == OrderDirection.Asc and not afterPost and page != 0:
                    page -= 1
                    continue
                else:
                    return self.ProcessPostResult.NoMorePosts

            if stopReason is not None:
                return stopReason
            if len(postWindow['order']) == 0:
                return self.ProcessPostResult.NoMorePosts
            if maxCount and postHints.processedCount >= maxCount:
                return self.ProcessPostResult.MaxCountReached

            if timeDirection == OrderDirection.Desc:
                if postWindow['prev_post_id'] == '':
                    return self.ProcessPostResult.NoMorePosts
                params.update(before = postWindow['order'][-1])
            else:
                if postWindow['next_post_id'] == '':
                    return self.ProcessPostResult.NoMorePosts
                params.update(after = postWindow['order'][0])

            if page != 0:
                page = 0
                del params['page']
            if pageOffset != 0:
                pageOffset = 0
            if self.configfile.throttlingLoopDelay:
                sleep(self.configfile.throttlingLoopDelay / 1000) # Dump rate limit avoidance

    def getPosts(self, channel: Channel = None, *args, **kwargs) -> List[Post]:
        result = []
        def process(p: Post, hints: 'MattermostDriver.PostHints'):
            result.append(p)
        self.processPosts(channel=channel, processor=process, *args, **kwargs)
        return result

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
                e = Emoji.fromMattermost(emojiInfo)
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
        raise KeyError

    def getEmojiUrl(self, emoji: Emoji) -> str:
        return f'emoji/{emoji.id}/image'

    def getFileUrl(self, file: FileAttachment, publicUrl = False) -> str:
        # Note: public access links may be unimplemented by server
        if publicUrl:
            return f'{self.configfile.hostname}{self.API_PART}files/{file.id}/link'
        else:
            return f'files/{file.id}'

    def getAvatarUrl(self, user: User) -> str:
        return f'users/{user.id}/image'
