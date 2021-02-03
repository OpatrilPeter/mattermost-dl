
import json
from pprint import pprint as pp
from pathlib import Path
from typing import cast, Optional, Set, Tuple
import sys

from bo import *
from config import ChannelOptions, ChannelSpec, ConfigFile, EntityLocator as ConfigEntityLocator, GroupChannelSpec, OrderDirection
from driver import MattermostDriver
import progress

@dataclass
class ChannelRequest:
    config: ChannelOptions
    metadata: Channel

@dataclass(init=False)
class ChannelHeader:
    # If set, posts from the start of the channel up to this time are archived
    lastPostTime: Time
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
        self.lastPostTime = Time(0)
        self.lastPostId = None
        self.usedUsers = set()
        self.usedEmojis = set()

    def load(self, info: dict, driver: MattermostDriver):
        '''
            Loading previously saved header.
        '''
        if 'lastPostTime' in info:
            self.lastPostTime = Time(info['lastPostTime'])
        if 'lastPostId' in info:
            self.lastPostId = Id(info['lastPostId'])
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

    def save(self) -> dict:
        content = {}
        if self.team:
            content.update(team=self.team.toJson(includeChannels=False))
        content.update(channel=self.channel.toJson())
        if self.lastPostId is not None:
            content.update(lastPostId=self.lastPostId)
        if self.lastPostTime.timestamp != 0:
            content.update(lastPostTime=self.lastPostTime)
        content.update(users=[u.toJson() for u in self.usedUsers])

        return content


class Saver:
    def __init__(self, configfile: ConfigFile, driver: Optional[MattermostDriver] = None):
        if not driver:
            driver = MattermostDriver(configfile)
        self.configfile = configfile
        self.driver: MattermostDriver = driver
        self.user: User # Conveniency, fetched on call

    def getUserByLocator(self, locator: ConfigEntityLocator) -> User:
        if hasattr(locator, 'id'):
            return self.driver.getUserById(locator.id)
        elif hasattr(locator, 'name'):
            return self.driver.getUserByName(locator.name)
        elif hasattr(locator, 'internalName'):
            return self.driver.getUserByName(locator.internalName)
        else:
            raise ValueError

    def matchChannel(self, channel: Channel, locator: ConfigEntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return channel.id == locator.id
        elif hasattr(locator, 'name'):
            return channel.name == locator.name
        else:
            assert hasattr(locator, 'internalName')
            return channel.internalName == locator.internalName
    def matchGroupChannel(self, channel: Channel, locator: Union[Id, List[ConfigEntityLocator]]) -> bool:
        if isinstance(locator, str):
            return channel.id == locator
        else:
            assert isinstance(locator, list)
            users = set(self.getUserByLocator(userLocator)
                for userLocator in locator
            )
            return users == set(u for u in channel.members)
    def matchTeam(self, team: Team, locator: ConfigEntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return team.id == locator.id
        elif hasattr(locator, 'name'):
            return team.name == locator.name
        else:
            assert hasattr(locator, 'internalName')
            return team.internalName == locator.internalName

    def getWantedUsers(self) -> List[Tuple[User, ChannelOptions]]:
        userIds = set()
        res = []
        if not isinstance(self.configfile.users, list):
            return res
        for userSpec in self.configfile.users:
            u = self.getUserByLocator(userSpec.locator)
            if u.id in userIds:
                logging.warning(f"Explicitly requesting direct messages for user {u.name} more than once.")
            else:
                userIds.add(u.id)
                res.append((u, userSpec.opts))
        return res

    def getWantedDirectChannels(self) -> Dict[User, ChannelRequest]:
        res: Dict[User, ChannelRequest] = {}
        channelNames = {self.driver.getDirectChannelNameByUserId(u.id): (u, opts) for u, opts in self.getWantedUsers()}
        for team in self.driver.getTeams().values():
            for channel in team.channels.values():
                if channel.type == ChannelType.Direct and (self.configfile.users is True or channel.internalName in channelNames):
                    if channel.id not in (ch.metadata.id for ch in res.values()):
                        if self.configfile.users is True:
                            otherUser = self.driver.getUserById(self.driver.getUserIdFromDirectChannelName(channel.internalName))
                            res.update({otherUser: ChannelRequest(config=self.configfile.directChannelDefaults, metadata=channel)})
                        else:
                            u, opts = channelNames[channel.internalName]
                            res.update({u: ChannelRequest(config=opts, metadata=channel)})
                            del channelNames[channel.internalName]

        # Have not found all channels!
        for user, _ in channelNames.values():
            logging.warning(f'Found no direct channel with {user.name}.')
        return res

    def getWantedPerTeamChannels(self) -> Dict[Team, Tuple[List[ChannelRequest], List[ChannelRequest]]]:
        if self.configfile.teams is False:
            return {}

        res: Dict[Team, Tuple[List[ChannelRequest], List[ChannelRequest]]] = {}
        teams = self.driver.getTeams()

        def getPublicChannelsForTeam(team: Team, wantedChannels: List[ChannelSpec]) -> List[ChannelRequest]:
            publicChannels = []
            for wch in wantedChannels:
                for ch in team.channels.values():
                    if ch.type == ChannelType.Open and self.matchChannel(ch, wch.locator):
                        publicChannels.append(ChannelRequest(config=wch.opts, metadata=ch))
                        break
                else:
                    logging.warning(f'Found no requested public channel on team {team.internalName} ({team.name}) via locator {wch.locator}.')
            return publicChannels

        def getGroupChannelsForTeam(team: Team, wantedChannels: List[GroupChannelSpec]) -> List[ChannelRequest]:
            groupChannels = []
            for wch in wantedChannels:
                for ch in team.channels.values():
                    if ch.type != ChannelType.Group:
                        continue
                    if not hasattr(ch, 'members'):
                        self.driver.loadChannelMembers(ch)
                    if self.matchGroupChannel(ch, wch.locator):
                        groupChannels.append(ChannelRequest(config=wch.opts, metadata=ch))
                        break
                else:
                    logging.warning(f'Found no requested group channel on team {team.internalName} ({team.name}) via locator {wch.locator}.')
            return groupChannels

        if self.configfile.teams is True:
            for t in teams.values():
                publicChannels, groupChannels = [], []
                for ch in t.channels.values():
                    if ch.type == ChannelType.Open:
                        publicChannels.append(ChannelRequest(config=self.configfile.publicChannelDefaults, metadata=ch))
                    elif ch.type == ChannelType.Group:
                        groupChannels.append(ChannelRequest(config=self.configfile.groupChannelDefaults, metadata=ch))
                res[t] = publicChannels, groupChannels
            return res

        assert isinstance(self.configfile.teams, list)
        for wantedTeam in self.configfile.teams:
            for availableTeam in teams.values():
                if self.matchTeam(availableTeam, wantedTeam.locator):
                    publicChannels, groupChannels = [], []

                    if wantedTeam.channels is True:
                        publicChannels = [ChannelRequest(config=wantedTeam.publicChannelDefaults, metadata=ch) for ch in availableTeam.channels.values()
                            if ch.type == ChannelType.Open
                        ]
                    elif wantedTeam.channels is False:
                        pass
                    else:
                        assert isinstance(wantedTeam.channels, list)
                        publicChannels = getPublicChannelsForTeam(availableTeam, wantedTeam.channels)

                    if wantedTeam.groups is True:
                        groupChannels = [ChannelRequest(config=wantedTeam.groupChannelDefaults, metadata=ch) for ch in availableTeam.channels.values()
                            if ch.type == ChannelType.Group
                        ]
                    elif wantedTeam.groups is False:
                        pass
                    else:
                        assert isinstance(wantedTeam.groups, list)
                        publicChannels = getGroupChannelsForTeam(availableTeam, wantedTeam.groups)

                    res[availableTeam] = publicChannels, groupChannels
                    break
            else:
                logging.error(f'Team requested by {wantedTeam.locator} was not found!')
        return res

    def enrichPostReaction(self, reaction: PostReaction):
        if self.configfile.verboseStandalonePosts:
            reaction.emoji = self.driver.getEmojiByName(reaction.emojiName)
        elif self.configfile.verboseHumanFriendlyPosts:
            reaction.userName = self.driver.getUserById(reaction.userId).name
            del reaction.userId

    def enrichEmoji(self, emoji: Emoji):
        if self.configfile.verboseStandalonePosts or self.configfile.verboseHumanFriendlyPosts:
            emoji.imageUrl = self.driver.getEmojiUrl(emoji)
        if self.configfile.verboseStandalonePosts:
            emoji.creator = self.driver.getUserById(emoji.creatorId)
        elif self.configfile.verboseHumanFriendlyPosts:
            emoji.creatorName = self.driver.getUserById(emoji.creatorId).name
            del emoji.creatorId

    # Note: the post gets mutated, so we better not pass persistent copy
    def enrichPost(self, post: Post):
        if self.configfile.verboseStandalonePosts:
            post.user = self.driver.getUserById(post.userId)
        elif self.configfile.verboseHumanFriendlyPosts:
            post.userName = self.driver.getUserById(post.userId).name
            del post.id
        if hasattr(post, 'attachments'):
            for file in post.attachments:
                if self.configfile.verboseStandalonePosts or self.configfile.verboseHumanFriendlyPosts:
                    file.url = self.driver.getFileUrl(file)
                if self.configfile.verboseHumanFriendlyPosts:
                    del file.id
        if hasattr(post, 'reactions'):
            for reaction in post.reactions:
                self.enrichPostReaction(reaction)


    def jsonDumpToFile(self, obj, fp):
        json.dump(obj, fp, default=lambda obj: obj.toJson(), ensure_ascii=False)

    def processDirectChannel(self, otherUser: User, channelRequest: ChannelRequest):
        channel, options = channelRequest.metadata, channelRequest.config
        logging.debug(f"Processing conversation with {otherUser.name} ...")

        directChannelOutfile = f'{self.user.name}-{otherUser.name}'

        with open(self.configfile.outputDirectory / Path(directChannelOutfile + '.meta.json'), 'w') as output:
            content = {
                'channel': channel.toJson(),
                'users': [self.user.toJson(), otherUser.toJson()]
            }
            self.jsonDumpToFile(content, output)
        with open(self.configfile.outputDirectory / Path(directChannelOutfile + '.data.json'), 'w') as output:
            def perPost(p: Post):
                self.enrichPost(p)
                self.jsonDumpToFile(p.__dict__, output)
                output.write('\n')
            self.driver.processPosts(processor=perPost, channel=channel)

    def processPublicChannel(self, team: Team, channelRequest: ChannelRequest):
        channel, options = channelRequest.metadata, channelRequest.config
        if channel.type == ChannelType.Group:
            userlist = '-'.join(sorted(u.name for u in channel.members))
            logging.info(f"Processing group chat {team.internalName}/{userlist} ...")
            channelOutfile = f'{team.internalName}--{userlist}'
        else:
            logging.info(f"Processing channel {team.internalName}/{channel.internalName} ...")
            channelOutfile = f'{team.internalName}--{channel.internalName}'

        headerFilename = self.configfile.outputDirectory / Path(channelOutfile + '.meta.json')
        postsFilename = self.configfile.outputDirectory / Path(channelOutfile + '.data.json')
        header = ChannelHeader(channel=channel, team=team)

        headerExists = headerFilename.is_file()
        with open(headerFilename, 'r+' if headerExists else 'w') as headerFile:
            if headerExists:
                header.load(json.load(headerFile), driver=self.driver)

            if options.postLimit != 0:
                with open(postsFilename, 'w') as output:
                    params: Dict[str, Any] = {
                        'timeDirection': options.downloadTimeDirection
                    }
                    if options.postLimit > 0:
                        params.update(maxCount=options.postLimit)
                    if options.postsAfterId:
                        if options.redownload and header.lastPostTime:
                            selectedPostTime = self.driver.getPostById(options.postsAfterId).createTime
                            if header.lastPostTime > selectedPostTime:
                                params.update(afterPost=header.lastPostId)
                            else:
                                params.update(afterPost=options.postsAfterId)
                        else:
                            params.update(afterPost=options.postsAfterId)
                    elif options.redownload and header.lastPostId:
                        params.update(afterPost=header.lastPostId)
                    if options.postsBeforeId:
                        params.update(beforePost=options.postsBeforeId)
                    if options.postsAfterTime:
                        if options.redownload and header.lastPostTime:
                            params.update(afterTime=max(options.postsAfterTime, header.lastPostTime))
                        else:
                            params.update(afterTime=options.postsAfterTime)
                    elif options.redownload and header.lastPostTime and not header.lastPostId:
                        params.update(afterTime=header.lastPostTime)
                    if options.postsBeforeTime:
                        params.update(beforeTime=options.postsBeforeTime)

                    if self.configfile.outputReportingProgress.mode != progress.VisualizationMode.DumbTerminal:
                        postIndex = 1
                        if options.postLimit != -1:
                            postLimit = options.postLimit
                        else:
                            postLimit = channel.messageCount
                        progressReporter = progress.ProgressReporter(sys.stdout, self.configfile.outputReportingProgress,
                            contentPadding=20, contentAlignLeft=False,
                            header='Progress: ', footer=' posts (upper limit approximate)')
                        progressReporter.open()

                    def perPost(p: Post):
                        if self.configfile.outputReportingProgress.mode != progress.VisualizationMode.DumbTerminal:
                            nonlocal postIndex
                            progressReporter.update(f"{postIndex}/{postLimit}")
                            postIndex += 1
                        header.usedUsers.add(self.driver.getUserById(p.userId))
                        self.enrichPost(p)
                        if options.emojiMetadata and 'emojis' in p:
                            for emoji in p.emojis:
                                if isinstance(emoji, Emoji):
                                    header.usedEmojis.add(emoji)
                                else:
                                    header.usedEmojis.add(self.driver.getEmojiById(cast(Id, emoji)))
                        self.jsonDumpToFile(p.toJson(), output)
                        output.write('\n')
                    self.driver.processPosts(processor=perPost, channel=channel, **params)

                    if self.configfile.outputReportingProgress.mode != progress.VisualizationMode.DumbTerminal:
                        progressReporter.close()

            if headerExists:
                headerFile.seek(0)
                headerFile.truncate()
            self.jsonDumpToFile(header.save(), headerFile)

    def __call__(self):
        if not self.configfile.outputDirectory.is_dir():
            self.configfile.outputDirectory.mkdir()
        m = self.driver

        if self.configfile.token == '':
            m.login()
        self.user = m.loadLocalUser()

        teams = m.getTeams()
        if len(teams) == 0:
            logging.fatal(f'User {self.configfile.username} is not member of any teams!')
            return

        for team in teams.values():
            m.loadChannels(teamId=team.id)

        directChannels = self.getWantedDirectChannels()
        teamChannels = self.getWantedPerTeamChannels()
        for user, channel in directChannels.items():
            self.processDirectChannel(user, channel)
        for team in teamChannels:
            publicChannels, groupChannels = teamChannels[team]
            for channel in publicChannels:
                self.processPublicChannel(team, channel)
            for channel in groupChannels:
                self.processPublicChannel(team, channel)