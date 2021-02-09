
import json
from mimetypes import guess_extension
import os
from pathlib import Path
import re
from typing import Callable, Collection, TypeVar, cast, Optional, Set, Tuple
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


class Saver:
    '''
        Main class responsible for orchestrating the downloading process.
        Should start from __call__ method.
    '''
    def __init__(self, configfile: ConfigFile, driver: Optional[MattermostDriver] = None):
        if not driver:
            driver = MattermostDriver(configfile)
        self.configfile = configfile
        self.driver: MattermostDriver = driver
        self.user: User # Conveniency, fetched on call

    def jsonDumpToFile(self, obj, fp):
        def fallback(obj):
            if hasattr(obj, 'toJson'):
                return obj.toJson()
            return str(obj)

        json.dump(obj, fp, default=fallback, ensure_ascii=False)

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
                    if ch.type in (ChannelType.Open, ChannelType.Private) and self.matchChannel(ch, wch.locator):
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
                    if len(ch.members) == 0:
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
                        groupChannels = getGroupChannelsForTeam(availableTeam, wantedTeam.groups)

                    res[availableTeam] = publicChannels, groupChannels
                    break
            else:
                logging.error(f'Team requested by {wantedTeam.locator} was not found!')
        return res

    def storeFile(self, url: str, filename: str, directoryName: Path, suffix: Optional[str] = None, redownload: bool = False) -> str:
        if '/' in filename:
            logging.warning(f'Refusing to store file with name "{filename}"')
            raise ValueError

        httpResponse = self.driver.getRaw(url)
        if suffix is None:
            if 'content-type' in httpResponse.headers:
                contentType = httpResponse.headers['content-type']
                suffixIdx = contentType.find(';')
                if suffixIdx != -1:
                    contentType = contentType[:suffixIdx]
                suffix = guess_extension(contentType)
                if suffix is None:
                    crudeParse = re.match(r'^[^/]+/(\S+)$', contentType)
                    if crudeParse is not None:
                        suffix = '.'+crudeParse[1]
                    else:
                        logging.warning(f"Can't guess extension from content type '{contentType}', leaving empty.")
                        suffix = ''
            else:
                suffix = ''
        fullFilename = directoryName / (filename + suffix)
        if fullFilename.exists() and not redownload:
            return filename + suffix
        with open(fullFilename, 'wb') as output:
            self.driver.storeUrlInto(url, output)
        return filename + suffix

    FileEntity = TypeVar('FileEntity')
    def processFiles(self, entities: Collection[FileEntity], directoryName: str, entitiesName: str,
            getFilenameFromEntity: Callable[[FileEntity], str], shouldDownload: Callable[[FileEntity], bool],
            getUrlFromEntity: Callable[[FileEntity], str], storeFilename: Callable[[FileEntity, str], None],
            getSuffixHint = (lambda e: None), redownload: bool = False):

        # Note: getSuffixHint: Callable[[FileEntity], Optional[str]] can't be assigned due to type checker failure
        if len(entities) == 0:
            return

        dirName: Path = self.configfile.outputDirectory / directoryName
        hasFolder = dirName.is_dir()
        if hasFolder:
            files: Dict[str, str] = {Path(name).stem: name for name in os.listdir(dirName)}
        else:
            files = {}

        if self.showProgressReport():
            reporter = progress.ProgressReporter(sys.stderr, settings=self.configfile.reportProgress,
                header='Progress: ', footer=f'/{len(entities)} {entitiesName} (upper limit approximate)',
                contentPadding=6, contentAlignLeft=False)
            reporter.open()
            reporter.update('0')
        else:
            reporter = None

        for i, entity in enumerate(entities):
            filename = getFilenameFromEntity(entity)
            if filename in files:
                storeFilename(entity, files[filename])
                continue
            if not shouldDownload(entity):
                continue
            url = getUrlFromEntity(entity)

            if not hasFolder:
                dirName.mkdir()
                hasFolder = True

            suffix = getSuffixHint(entity)
            storeFilename(entity, self.storeFile(
                url=url, filename=filename, directoryName=dirName,
                suffix=suffix, redownload=redownload))

            if self.showProgressReport():
                reporter.update(str(i+1))
        if self.showProgressReport():
            reporter.close()
        logging.info(f"Processed all {entitiesName}.")

    def processAttachments(self, directoryName: str, channelOpts: ChannelOptions, attachments: Collection[FileAttachment], redownload: bool = False):
        if not channelOpts.downloadAttachments:
            return
        def shouldDownload(attachment: FileAttachment) -> bool:
            return ((channelOpts.downloadAttachmentSizeLimit == 0 or attachment.byteSize <= channelOpts.downloadAttachmentSizeLimit)
                and (len(channelOpts.downloadAttachmentTypes) == 0 or attachment.mimeType in channelOpts.downloadAttachmentTypes))
        def storeFilename(attachment: FileAttachment, filename: str):
            pass
        def getSuffixHint(attachment: FileAttachment) -> Optional[str]:
            suffix = Path(attachment.name).suffix
            if suffix == '':
                return None
            else:
                return suffix

        self.processFiles(attachments, directoryName, 'files',
            getFilenameFromEntity=lambda attachment: str(attachment.id),
            shouldDownload=shouldDownload,
            getUrlFromEntity=lambda attachment: self.driver.getFileUrl(attachment),
            storeFilename=storeFilename,
            getSuffixHint=getSuffixHint,
            redownload=redownload
        )

    def processEmoji(self, directoryName: str, emojis: Collection[Emoji], redownload: bool = False):
        def storeFilename(emoji: Emoji, filename: str):
            emoji.imageFileName = filename
        self.processFiles(emojis, directoryName, 'emojis',
            getFilenameFromEntity=lambda e: e.name,
            shouldDownload=lambda e: True,
            getUrlFromEntity=lambda e: self.driver.getEmojiUrl(e),
            storeFilename=storeFilename,
            redownload=redownload
        )

    def processAvatars(self, directoryName: str, users: Collection[User], redownload: bool = False):
        def storeFilename(user: User, avatarFilename: str):
            user.avatarFilename = avatarFilename
        self.processFiles(users, directoryName, 'user avatars',
            getFilenameFromEntity=lambda u: u.name,
            shouldDownload=lambda u: True,
            getUrlFromEntity=lambda u: self.driver.getAvatarUrl(u),
            storeFilename=storeFilename,
            redownload=redownload
        )

    def enrichEmoji(self, emoji: Emoji):
        if self.configfile.verboseHumanFriendlyPosts:
            emoji.creatorName = self.driver.getUserById(emoji.creatorId).name

    def enrichPostReaction(self, reaction: PostReaction):
        if self.configfile.verboseHumanFriendlyPosts:
            reaction.userName = self.driver.getUserById(reaction.userId).name

    # Note: the post gets mutated, so we better not pass persistent copy
    def enrichPost(self, post: Post):
        if self.configfile.verboseHumanFriendlyPosts:
            post.userName = self.driver.getUserById(post.userId).name
        if len(post.reactions) != 0:
            for reaction in post.reactions:
                self.enrichPostReaction(reaction)

    def showProgressReport(self) -> bool:
        return (not self.configfile.verboseMode
            and self.configfile.reportProgress.mode != progress.VisualizationMode.DumbTerminal)

    def processChannel(self, channelOutfile: str, header: ChannelHeader, channelRequest: ChannelRequest):
        channel, options = channelRequest.metadata, channelRequest.config

        headerFilename = self.configfile.outputDirectory / (channelOutfile + '.meta.json')
        postsFilename = self.configfile.outputDirectory / (channelOutfile + '.data.json')

        attachments: List[FileAttachment] = []

        headerExists = headerFilename.is_file()

        with open(headerFilename, 'r+' if headerExists else 'w') as headerFile:
            if headerExists:
                try:
                    header.load(json.load(headerFile), driver=self.driver)
                except json.JSONDecodeError as err:
                    logging.warning(f"Unable to load previously saved metadata for channel {channel.internalName}, generating from scratch.\nError: {err}")

            if options.postLimit != 0:
                postIndex: int = 0
                if options.postLimit != -1:
                    estimatedPostLimit: int = options.postLimit
                else:
                    estimatedPostLimit: int = channel.messageCount
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

                    if self.showProgressReport():
                        progressReporter = progress.ProgressReporter(sys.stderr, settings=self.configfile.reportProgress,
                            contentPadding=10, contentAlignLeft=False,
                            header='Progress: ', footer=f'/{estimatedPostLimit} posts (upper limit approximate)')
                        progressReporter.open()
                        progressReporter.update(f'0')
                    else:
                        progressReporter = None

                    takeEmojis: bool = options.emojiMetadata or options.downloadEmoji

                    def perPost(p: Post):
                        nonlocal postIndex

                        header.usedUsers.add(self.driver.getUserById(p.userId))
                        if options.downloadAttachments:
                            for attachment in p.attachments:
                                attachments.append(attachment)
                        self.enrichPost(p)
                        if p.emojis:
                            if takeEmojis:
                                for emoji in p.emojis:
                                    assert isinstance(emoji, Emoji)
                                    header.usedEmojis.add(emoji)
                                p.emojis = [cast(Emoji, emoji).id for emoji in p.emojis]
                            else:
                                p.emojis = []
                        self.jsonDumpToFile(p.toJson(), output)
                        output.write('\n')

                        postIndex += 1
                        if self.showProgressReport():
                            progressReporter.update(str(postIndex))

                    self.driver.processPosts(processor=perPost, channel=channel, **params)

                    if self.showProgressReport():
                        progressReporter.close()
                    logging.info('Processed all posts.')

            if options.emojiMetadata:
                for emoji in header.usedEmojis:
                    self.enrichEmoji(emoji)
            if options.downloadEmoji and not self.configfile.downloadAllEmojis:
                self.processEmoji('emojis', emojis=header.usedEmojis)

            if options.downloadAttachments:
                self.processAttachments(channelOutfile+'--files', channelOpts=options, attachments=attachments)

            if self.configfile.downloadAvatars:
                self.processAvatars('avatars', users=header.usedUsers)

            if headerExists:
                headerFile.seek(0)
                headerFile.truncate()
            self.jsonDumpToFile(header.save(), headerFile)


    def processDirectChannel(self, otherUser: User, channelRequest: ChannelRequest):
        # channel, options = channelRequest.metadata, channelRequest.config
        logging.info(f"Processing conversation with {otherUser.name} ...")

        directChannelOutfile = f'{self.user.name}--{otherUser.name}'
        header = ChannelHeader(channel=channelRequest.metadata)
        header.usedUsers = {self.user, otherUser}

        self.processChannel(channelOutfile=directChannelOutfile, header=header, channelRequest=channelRequest)

    def processPublicChannel(self, team: Team, channelRequest: ChannelRequest):
        '''
            Processes public, private and group channels
        '''
        channel, options = channelRequest.metadata, channelRequest.config
        if channel.type == ChannelType.Group:
            if len(channel.members) == 0:
                self.driver.loadChannelMembers(channel)
            userlist = '-'.join(sorted(u.name for u in channel.members))
            if userlist == '':
                logging.warning(f'No users for group channel {channel.id}, using id as name!')
                userlist = str(channel.id)
            logging.info(f"Processing group chat {team.internalName}/{userlist} ...")
            channelOutfile = f'{team.internalName}--{userlist}'
        else:
            logging.info(f"Processing channel {team.internalName}/{channel.internalName} ...")
            channelOutfile = f'{team.internalName}--{channel.internalName}'

        header = ChannelHeader(channel=channel, team=team)

        self.processChannel(channelOutfile=channelOutfile, header=header, channelRequest=channelRequest)

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

        if self.configfile.downloadAllEmojis:
            emojis = self.driver.getEmojiList()
            for emoji in emojis:
                self.enrichEmoji(emoji)
            self.processEmoji('emojis', emojis)

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

