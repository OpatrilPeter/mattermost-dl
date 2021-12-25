'''
    Contains high level logic of history downloading
'''

from .common import *

from .bo import *
from .config import ChannelOptions, ConfigFile, GroupChannelSpec, LogVerbosity, OrderDirection, TeamSpec
from .driver import MattermostDriver
from . import progress
from .recovery import RReuse, RecoveryArbiter, RBackup, RDelete, RSkipDownload
from .store import ChannelFileInfo, ChannelHeader, PostOrdering, PostStorage

import json
from mimetypes import guess_extension

@dataclass
class ChannelRequest:
    config: ChannelOptions
    metadata: Channel

    def __hash__(self) -> int:
        return hash(self.metadata.id)

class SavingFailed(Exception):
    '''
        Invocation of Saver failed due to known external problem, such as failing to log in.
        Unlike logical errors, dumping stack trace to users is not necessary.

        Should stringify into problem description and if caused by internal exception that
        may provide additional info, such subexception may be chained into it.
    '''
    pass


class Saver:
    '''
        Main class responsible for orchestrating the downloading process.
        Should start from __call__ method.
    '''
    def __init__(self, configfile: ConfigFile, driver: Optional[MattermostDriver] = None,
            recoveryArbiter: Optional[RecoveryArbiter] = None
            ):
        if driver is None:
            driver = MattermostDriver(configfile)
        if recoveryArbiter is None:
            recoveryArbiter = RecoveryArbiter(configfile)
        self.configfile = configfile
        self.driver: MattermostDriver = driver
        self.recoveryArbiter: RecoveryArbiter = recoveryArbiter
        self.user: User # Conveniency, fetched on call

    def jsonDumpToFile(self, obj, fp):
        def fallback(obj):
            if hasattr(obj, 'toStore'):
                return obj.toStore()
            return str(obj)

        json.dump(obj, fp, default=fallback, ensure_ascii=False)

    def getUserByLocator(self, locator: EntityLocator) -> User:
        if hasattr(locator, 'id'):
            return self.driver.getUserById(locator.id)
        elif hasattr(locator, 'name'):
            return self.driver.getUserByName(locator.name)
        elif hasattr(locator, 'internalName'):
            return self.driver.getUserByName(locator.internalName)
        else:
            raise ValueError

    def matchGroupChannel(self, channel: Channel, locator: Union[Id, FrozenSet[EntityLocator]]) -> bool:
        if isinstance(locator, str):
            return channel.id == locator
        else:
            assert isinstance(locator, frozenset)
            if channel.members is None:
                self.driver.loadChannelMembers(channel)
                assert channel.members is not None
            users = set(self.getUserByLocator(userLocator)
                for userLocator in locator
            )
            users.add(self.user)
            return users == set(u for u in channel.members)

    def getWantedUsers(self) -> List[Tuple[User, ChannelOptions]]:
        userIds = set()
        res = []
        for userSpec in self.configfile.explicitUsers:
            u = self.getUserByLocator(userSpec.locator)
            if u.id in userIds:
                logging.warning(f"Explicitly requesting direct messages for user {u.name} more than once.")
            else:
                userIds.add(u.id)
                res.append((u, userSpec.opts))
        return res

    def getWantedGlobalChannels(self) -> Tuple[Dict[User, ChannelRequest], Set[ChannelRequest]]:
        '''
            Collects a list of channels requested by configfile that aren't scoped under Team.
            Returns pair representing channel requests for users and groups respectively.
        '''
        wantedDirectChannels: Dict[User, ChannelRequest] = {}
        wantedGroupChannels: Set[ChannelRequest] = set()
        explicitDirectChannelNames = {self.driver.getDirectChannelNameByUserId(u.id): (u, opts) for u, opts in self.getWantedUsers()}
        matchedGroupChannels: Set[GroupChannelSpec] = set()
        for team in self.driver.getTeams().values():
            for channel in team.channels.values():
                if channel.type == ChannelType.Direct:
                    # If we don't have this channel already
                    if channel.id not in (ch.metadata.id for ch in wantedDirectChannels.values()):
                        if channel.internalName in explicitDirectChannelNames:
                            u, opts = explicitDirectChannelNames[channel.internalName]
                            wantedDirectChannels.update({u: ChannelRequest(config=opts, metadata=channel)})
                            del explicitDirectChannelNames[channel.internalName]
                        elif self.configfile.miscDirectChannels:
                            otherUser = self.driver.getUserById(self.driver.getUserIdFromDirectChannelName(channel.internalName))
                            wantedDirectChannels.update({otherUser: ChannelRequest(config=self.configfile.directChannelDefaults, metadata=channel)})
                elif channel.type == ChannelType.Group:
                    for wch in self.configfile.explicitGroups:
                        if self.matchGroupChannel(channel, wch.locator):
                            wantedGroupChannels.add(ChannelRequest(config=wch.opts, metadata=channel))
                            matchedGroupChannels.add(wch)
                            break
                    else:
                        if self.configfile.miscGroupChannels:
                            wantedGroupChannels.add(ChannelRequest(config=self.configfile.groupChannelDefaults, metadata=channel))

        # Have not found all channels?
        for user, _ in explicitDirectChannelNames.values():
            logging.warning(f'Found no direct channel with {user.name}.')
        for wch in self.configfile.explicitGroups:
            if wch not in matchedGroupChannels:
                logging.warning(f'Found no group channel via locator {wch.locator}.')
        return wantedDirectChannels, wantedGroupChannels

    def getWantedPerTeamChannels(self) -> Dict[Team, List[ChannelRequest]]:
        if self.configfile.miscTeams is False and len(self.configfile.explicitTeams) == 0:
            return {}

        res: Dict[Team, List[ChannelRequest]] = {}
        teams = self.driver.getTeams()

        def getChannelsForTeam(team: Team, wantedTeam: TeamSpec) -> List[ChannelRequest]:
            channels = []
            explicitPublicLocators = {ch.locator for ch in wantedTeam.explicitPublicChannels}
            explicitPrivateLocators = {ch.locator for ch in wantedTeam.explicitPrivateChannels}

            for availableChannel in team.channels.values():
                if availableChannel.type == ChannelType.Open:
                    for wch in wantedTeam.explicitPublicChannels:
                        if availableChannel.match(wch.locator):
                            channels.append(ChannelRequest(config=wch.opts, metadata=availableChannel))
                            explicitPublicLocators.remove(wch.locator)
                            break
                    else:
                        if wantedTeam.miscPublicChannels:
                            channels.append(ChannelRequest(config=wantedTeam.publicChannelDefaults, metadata=availableChannel))
                elif availableChannel.type == ChannelType.Private:
                    for wch in wantedTeam.explicitPrivateChannels:
                        if availableChannel.match(wch.locator):
                            channels.append(ChannelRequest(config=wch.opts, metadata=availableChannel))
                            explicitPrivateLocators.remove(wch.locator)
                            break
                    else:
                        if wantedTeam.miscPrivateChannels:
                            channels.append(ChannelRequest(config=wantedTeam.privateChannelDefaults, metadata=availableChannel))
            for loc in explicitPublicLocators:
                logging.warning(f'Found no requested public channel on team {team.internalName} ({team.name}) via locator {loc}.')
            for loc in explicitPrivateLocators:
                logging.warning(f'Found no requested private channel on team {team.internalName} ({team.name}) via locator {loc}.')
            return channels

        explicitTeamLocators: Set[EntityLocator] = {t.locator for t in self.configfile.explicitTeams}
        for availableTeam in teams.values():
            for wantedTeam in self.configfile.explicitTeams:
                if availableTeam.match(wantedTeam.locator):
                    res[availableTeam] = getChannelsForTeam(availableTeam, wantedTeam)
                    explicitTeamLocators.remove(wantedTeam.locator)
                    break
            else:
                if self.configfile.miscTeams:
                    channels = []
                    for ch in availableTeam.channels.values():
                        if ch.type == ChannelType.Open:
                            channels.append(ChannelRequest(config=self.configfile.publicChannelDefaults, metadata=ch))
                        elif ch.type == ChannelType.Private:
                            channels.append(ChannelRequest(config=self.configfile.privateChannelDefaults, metadata=ch))
                    res[availableTeam] = channels
        for loc in explicitTeamLocators:
            logging.error(f'Team requested by {loc} was not found!')
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
        assert isinstance(suffix, str)
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

        showProgressReport = self.showProgressReport()

        if showProgressReport:
            reporter = progress.ProgressReporter(sys.stderr, settings=self.configfile.reportProgress,
                header='Progress: ', footer=f'/{len(entities)} {entitiesName} (upper limit approximate)',
                contentPadding=6, contentAlignLeft=False, updateIntervalMs=self.configfile.progressInterval)
            reporter.open()
            reporter.update('0')
        else:
            # Reporter should be never accessed in this case, but we want clear type for linting
            reporter = cast(progress.ProgressReporter, UnboundLocalError)

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

            if showProgressReport:
                reporter.update(str(i+1))
        if showProgressReport:
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
            shouldDownload=lambda _: True,
            getUrlFromEntity=lambda e: self.driver.getEmojiUrl(e),
            storeFilename=storeFilename,
            redownload=redownload
        )

    def processAvatars(self, directoryName: str, users: Collection[User], redownload: bool = False):
        def storeFilename(user: User, avatarFilename: str):
            user.avatarFileName = avatarFilename
        self.processFiles(users, directoryName, 'user avatars',
            getFilenameFromEntity=lambda u: u.name,
            shouldDownload=lambda _: True,
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
        return (self.configfile.verbosity == LogVerbosity.Normal
            and self.configfile.reportProgress.mode != progress.VisualizationMode.DumbTerminal)

    def reduceChannelDownloadConstraints(self, channelOptions: ChannelOptions, storage: PostStorage, lastChannelMessageTime: Time) -> Union[bool, ChannelOptions]:
        '''
            Updates constraints in channel options based on what's already downloaded in archive.

            Note that archive may contain more posts than current download options demand, but the
            posts will stay in one continuous interval.

            Reflects following options:
                - organization
                - postsAfterId
                - postsBeforeId
                - postsBeforeTime
                - postsAfterTime
                - postLimit

            @param storage archive's storage
            @returns either
                - False if no download is necessary
                - True if download should be done from scratch as current channel options
                  are incompatible with current request
                - updated ChannelOptions, if current archive can be appended into

            Note that as lastChannelMessageTime could also be time of last update,
            while storage only tracks message creation time, it may suggest updating otherwise complete archive
        '''

        '''
            This is one of the most complex functions, so here's overview of the internal logic:

            - note that storage begin and end depends on order, while ChannelOptions does not
            - only continuous, single interval storage is supported
            - postLimit is already considered nonzero
            - channel is not empty, because we have nonempty storage from previous download
            - we assume here that multiple posts do not happen at exactly same timestamp (in miliseconds)
            - post Ids have no ordering, but we can fetch posts's creation time if really needed
                - but this is expensive, so we prefer to do that only as last resort

            Time intervals in ascending direction has following time points:
                - first message in channel
                    - generally unknown, but if storage.postIdBeforeFirst is None, it must be storage.firstPostId
                - post before first
                    - if None, we know we have start of storage
                - first post of storage
                - last post of storage
                - post after last
                    - if None, we have downloaded channel up to the end at the time
                        - if lastChannelMessageTime == storage.endTime, storage has last message in channel
                            - if we also start at the beginning, we can full channel history already
                        - if lastChannelMessageTime > storage.endTime, we must download from scratch unless we want content before storage.endTime
                - last message in channel
                    - known only by lastChannelMessageTime

            Requested interval stops ...
                - at the last message
                - at beforeId/beforeTime
                    - if both are specified, it is converted to time and minimum is used
            Requested interval starts ...
                - at the first message (if afterId/afterTime is unspecified)
                    - if storage doesn't start at first message, we need to redownload
                - at later point specified by afterId/afterTime
                    - as there is no ordering on postIds, we must transform it into time, unless it's one one the known ids
                        - if both are specified, it is converted to time and maximum is used

                - if requested interval ends before it starts
                    - do nothing

                - if it's before storage, we need to redownload
                - if it's at storage start (common case in incremental downloading)
                    - if the storage size is >= postLimit
                        - do nothing
                    - else
                        - if requested interval stops before or at the end of storage
                            - do nothing
                        - else
                            - append to storage (consider postLimit, decrease be storage size)
                - it it's in the middle of the storage
                    - if requested interval stops before or at the end of storage
                        - do nothing
                    - else
                        - if there's no post limit
                            - append to storage
                        - else
                            - we don't know exactly where in the storage we are, so we don't know how to decrease the limit of if the limit is reached yet
                            - we could iterate through the storage and find exact position, but that's too much work
                            - => redownload
                - if it's at storage end
                    - if requested interval stops before or at the end of storage
                        - do nothing
                    - else
                        - append to storage
                - if it's after storage, we need to redownload

            Descending direction works with equivalent logic, just with time points reversed. Mattermost's API is optimized for this case,
            but since its default start timepoint is mutable (latest post), every time new post arrive, archive must be redownloaded, that's why it's not the default.
        '''

        newOrganization = PostOrdering.AscendingContinuous if channelOptions.downloadTimeDirection == OrderDirection.Asc else PostOrdering.DescendingContinuous
        if newOrganization != storage.organization:
            return True

        options = copy(channelOptions)

        def getBeginIdTime() -> Time:
            nonlocal options
            if options.downloadTimeDirection == OrderDirection.Asc:
                assert options.postsAfterId is not None
                postTime = self.driver.getPostById(options.postsAfterId).createTime
                options.postsAfterTime = max(postTime, options.postsAfterTime) if options.postsAfterTime is not None else postTime
                return options.postsAfterTime
            else:
                assert options.postsBeforeId is not None
                postTime = self.driver.getPostById(options.postsBeforeId).createTime
                options.postsBeforeTime = min(postTime, options.postsBeforeTime) if options.postsBeforeTime is not None else postTime
                return options.postsBeforeTime

        def getEndIdTime() -> Time:
            nonlocal options
            if options.downloadTimeDirection == OrderDirection.Asc:
                assert options.postsBeforeId is not None
                postTime = self.driver.getPostById(options.postsBeforeId).createTime
                options.postsBeforeTime = min(postTime, options.postsBeforeTime) if options.postsBeforeTime is not None else postTime
                return options.postsBeforeTime
            else:
                assert options.postsAfterId is not None
                postTime = self.driver.getPostById(options.postsAfterId).createTime
                options.postsAfterTime = max(postTime, options.postsAfterTime) if options.postsAfterTime is not None else postTime
                return options.postsAfterTime

        def getEndTime() -> Time:
            nonlocal options
            if options.downloadTimeDirection == OrderDirection.Asc:
                if options.postsBeforeId is not None or options.postsBeforeTime is not None:
                    if options.postsBeforeId is not None:
                        if options.postsBeforeId == storage.firstPostId:
                            options.postsBeforeTime = min(options.postsBeforeTime, storage.beginTime) if options.postsBeforeTime is not None else storage.beginTime
                        elif options.postsBeforeId == storage.lastPostId:
                            options.postsBeforeTime = min(options.postsBeforeTime, storage.endTime) if options.postsBeforeTime is not None else storage.endTime
                        else:
                            getEndIdTime()
                    assert options.postsBeforeTime is not None
                else:
                    options.postsBeforeTime = Time(lastChannelMessageTime.timestamp+1)
                return options.postsBeforeTime
            else:
                if options.postsAfterId is not None or options.postsAfterTime is not None:
                    if options.postsAfterId is not None:
                        if options.postsAfterId == storage.firstPostId:
                            options.postsAfterTime = min(options.postsAfterTime, storage.beginTime) if options.postsAfterTime is not None else storage.beginTime
                        elif options.postsAfterId == storage.lastPostId:
                            options.postsAfterTime = min(options.postsAfterTime, storage.endTime) if options.postsAfterTime is not None else storage.endTime
                        else:
                            getEndIdTime()
                    assert options.postsAfterTime is not None
                else:
                    options.postsAfterTime = Time(0)
                return options.postsAfterTime

        def continueStorage():
            '''Called if exactly all posts in storage are part of requested data.'''
            nonlocal options
            if options.downloadTimeDirection == OrderDirection.Asc:
                if options.postLimit != -1:
                    if options.postLimit <= storage.count:
                        return False
                    else:
                        options.postLimit -= storage.count
                        options.postsAfterId = storage.lastPostId
                        options.postsAfterTime = storage.endTime
                else:
                    options.postsAfterId = storage.lastPostId
                    options.postsAfterTime = storage.endTime
            else:
                if options.postLimit != -1:
                    if options.postLimit <= storage.count:
                        return False
                    else:
                        options.postLimit -= storage.count
                        options.postsBeforeId = storage.lastPostId
                        options.postsBeforeTime = storage.endTime
                else:
                    options.postsBeforeId = storage.lastPostId
                    options.postsBeforeTime = storage.endTime

        def updateOptsWithBeginTime():
            nonlocal options
            if options.downloadTimeDirection == OrderDirection.Asc:
                assert options.postsAfterTime is not None

                if options.postsAfterTime < storage.beginTime:
                    return True
                elif options.postsAfterTime < storage.endTime:
                    res = continueStorage()
                    if res is not None:
                        return res
                elif options.postsAfterTime == storage.endTime:
                    pass
                else:
                    return True
            else:
                assert options.postsBeforeTime is not None

                if options.postsBeforeTime > storage.beginTime:
                    return True
                elif options.postsBeforeTime > storage.endTime:
                    res = continueStorage()
                    if res is not None:
                        return res
                elif options.postsBeforeTime == storage.endTime:
                    pass
                else:
                    return True

        if options.downloadTimeDirection == OrderDirection.Asc:

            if options.postsAfterTime is not None or options.postsAfterId is not None:
                if options.postsAfterId is not None:
                    if options.postsAfterId == storage.postIdBeforeFirst:
                        res = continueStorage()
                        if res is not None:
                            return res
                    elif options.postsAfterId == storage.lastPostId:
                        options.postsAfterTime = storage.endTime
                    else: # We don't specialize otherwise
                        getBeginIdTime()
                    assert options.postsAfterTime is not None

                ret = updateOptsWithBeginTime()
                if ret is not None:
                    return ret
            else: # Starting from first message
                if storage.postIdBeforeFirst is not None:
                    return True
                elif storage.endTime == lastChannelMessageTime:
                    return False
                else:
                    assert lastChannelMessageTime > storage.endTime
                    res = continueStorage()
                    if res is not None:
                        return res
            assert options.postsAfterTime is not None # Also in or at the end of archive

            if options.postsBeforeId is not None:
                if options.postsBeforeId in (storage.postIdBeforeFirst, storage.firstPostId, storage.lastPostId, storage.postIdAfterLast):
                    return False
            getEndTime()
            assert options.postsBeforeTime is not None

            if options.postsBeforeTime <= storage.endTime:
                return False
            if options.postsBeforeTime < options.postsAfterTime:
                return False

            return options

        else: # options.downloadTimeDirection == OrderDirection.Desc
            # Mostly mirrored all conditions from above branch in other time direction

            if options.postsBeforeTime is not None or options.postsBeforeId is not None:
                if options.postsBeforeId is not None:
                    if options.postsBeforeId == storage.postIdBeforeFirst:
                        res = continueStorage()
                        if res is not None:
                            return res
                    elif options.postsBeforeId == storage.lastPostId:
                        options.postsBeforeTime = storage.endTime
                    else: # We don't specialize otherwise
                        getBeginIdTime()
                    assert options.postsBeforeTime is not None

                ret = updateOptsWithBeginTime()
                if ret is not None:
                    return ret
            else: # Starting from last message
                if storage.postIdBeforeFirst is not None:
                    return True
                elif lastChannelMessageTime > storage.beginTime:
                    return True
                else:
                    assert lastChannelMessageTime == storage.beginTime
                    res = continueStorage()
                    if res is not None:
                        return res
            assert options.postsBeforeTime is not None # Also in or at the end of archive

            if options.postsAfterId is not None:
                if options.postsAfterId in (storage.postIdBeforeFirst, storage.firstPostId, storage.lastPostId, storage.postIdAfterLast):
                    return False
            getEndTime()
            assert options.postsAfterTime is not None

            if options.postsAfterTime >= storage.endTime:
                return False
            if options.postsAfterTime < options.postsBeforeTime:
                return False

            return options

    def getChannelDownloaderParams(self, options: ChannelOptions, archiveHeader: Optional[ChannelHeader],
            lastChannelMessageTime: Optional[Time]
        ) -> Union[None, Tuple[bool, Dict[str, Any]]]:
        '''
            Returns params suitable for MattermostDriver's post downloading
            and indicator whether current archive content is unsuitable for appending (requiring creation of archive from scratch).
            If archive's channel header indicates that all required posts are already present, returns None.
        '''

        emptyArchive = archiveHeader is None or archiveHeader.storage is None
        truncateArchive = archiveHeader is None

        if emptyArchive and lastChannelMessageTime is None:
            return None

        if not (emptyArchive or truncateArchive):
            assert archiveHeader is not None # Redundant, for linter
            assert archiveHeader.storage is not None
            # If we downloaded channel before there must be some messages available
            assert lastChannelMessageTime is not None

            opts = self.reduceChannelDownloadConstraints(options, archiveHeader.storage, lastChannelMessageTime)
            if isinstance(opts, bool):
                if opts:
                    truncateArchive = True
                else:
                    return None
            else:
                assert isinstance(opts, ChannelOptions)
                options = opts

        params: Dict[str, Any] = {
            'timeDirection': options.downloadTimeDirection
        }

        if options.postLimit > 0 or options.postSessionLimit > 0:
            if options.postLimit == -1:
                params.update(maxCount=options.postSessionLimit)
            elif options.postSessionLimit == -1:
                params.update(maxCount=options.postLimit)
            else:
                params.update(maxCount=min(options.postLimit, options.postSessionLimit))

        if options.postsAfterId:
            params.update(afterPost=options.postsAfterId)
        elif options.postsAfterTime:
            if options.postsBeforeTime and options.postsBeforeTime < options.postsAfterTime: # type: ignore
                return None
            params.update(afterTime=options.postsAfterTime)
        if options.postsBeforeId:
            params.update(beforePost=options.postsBeforeId)
        elif options.postsBeforeTime:
            params.update(beforeTime=options.postsBeforeTime)

        return truncateArchive, params

    def makeArchiveFilenames(self, stem: str) -> Tuple[Path, Path]:
        '''
            Helper that returns pair of filenames for header and data file of channel archive
        '''
        return (
            self.configfile.outputDirectory / (stem + '.meta.json'),
            self.configfile.outputDirectory / (stem + '.data.json')
        )

    def getUnusedArchiveBackupFilenames(self, backupAlternatives: Generator[str, None, None]) -> Tuple[Path, Path]:
        while True:
            fname = next(backupAlternatives)
            headerFname, dataFname = self.makeArchiveFilenames(fname)
            if not headerFname.is_file() and not dataFname.is_file():
                return headerFname, dataFname

    def backupArchive(self, channel: Channel, channelOutfile: str,
            backupOutfile: str, backupAlternatives: Generator[str, None, None],
            headerOnly: bool = False
        ) -> Union[None, RSkipDownload]:
        '''
            Backups existing archive of selected filename by renaming it.
            Header only mode, as name suggests, backs only header file. This is efficient if data file gets changed in write-only way,
            as it allows to recover the data file by trimming it to original size (preserved in header).
            Consults arbiter on overwrites of existing backups  - if the chosen action is to not lose anything and not creating redundant data,
            RSkipDownload is returned.

            Outfile parameters represent root of the channel's name, without suffixes.
            `backupAlternatives` shall yield alternate backup outfile.
        '''

        headerFname, dataFname = self.makeArchiveFilenames(channelOutfile)
        headerBackupFname, dataBackupFname = self.makeArchiveFilenames(backupOutfile)

        headerExist = headerFname.is_file()
        dataExist = dataFname.is_file()

        if not headerExist and (headerOnly or not dataExist):
            return None

        # Backups already exist
        if headerBackupFname.is_file() or dataBackupFname.is_file():
            opts = self.recoveryArbiter.onExistingChannelBackup(channel, headerBackupFname, dataBackupFname)
            if isinstance(opts, RSkipDownload):
                return opts
            elif isinstance(opts, RDelete):
                if headerBackupFname.is_file():
                    headerBackupFname.unlink()
                if dataBackupFname.is_file():
                    dataBackupFname.unlink()
            else:
                assert opts == RBackup()
                headerAltBackupFname, dataAltBackupFname = self.getUnusedArchiveBackupFilenames(backupAlternatives)
                if headerBackupFname.is_file():
                    headerBackupFname.rename(headerAltBackupFname)
                if dataBackupFname.is_file():
                    dataBackupFname.rename(dataAltBackupFname)

        if headerExist:
            headerFname.rename(headerBackupFname)
        if not headerOnly and dataExist:
            dataFname.rename(dataBackupFname)

        return None

    def restoreArchiveBackup(self, channelOutfile: str, backupOutfile: str, oldDataFileSize: Optional[int] = None):
        '''
            Replaces current state of the archive of given name from existing backup.

            Outfile parameters represent root of the channel's name, without suffixes.

            Expects one of following scenarios:
            - rollbacked from-scratch download
                Current state is already fully deleted. Backup replaces it
            - rollbacked appending download
                Current state contains only post storage. Backup contains only header
                and corrects the size of the storage. The corret size is already known
                and passed through `oldPostSize` parameter
        '''

        headerFname, dataFname = self.makeArchiveFilenames(channelOutfile)
        headerBackupFname, dataBackupFname = self.makeArchiveFilenames(backupOutfile)

        assert headerBackupFname.is_file() and not headerFname.is_file()
        if dataBackupFname.is_file():
            assert not dataFname.is_file()
            dataBackupFname.rename(dataFname)
            headerBackupFname.rename(headerFname)
        else:
            assert dataFname.is_file() and oldDataFileSize is not None
            os.truncate(dataFname, oldDataFileSize)
            headerBackupFname.rename(headerFname)

    def loadPreviousChannelArchive(self, channel: Channel, headerFilename: Path, dataFilename: Path
        ) -> Union[ChannelFileInfo, RBackup, RDelete, RSkipDownload]:
        '''
            Loads all data about possible previously downloaded channel archive
            in preparation of new download and decides how to replace the previous content.

            @returns ChannelFileInfo if archive exists, can be loaded successfully and
                is suitable for reuse.
                Otherwise, returns one of recovery strategies of previous content:
                    - RBackup - previous content shall be backed up.
                    - RDelete - previous content shall be deleted.
                    - RSkipDownload - previous content shall be preserved, download is cancelled.
        '''

        headerInfo = ChannelFileInfo.load(channel, headerFilename, dataFilename)
        if headerInfo is None:
            return self.recoveryArbiter.onUnloadableHeader(channel, headerFilename, dataFilename)
        archiveHeader, dataFileStats = headerInfo.header, headerInfo.dataFileStats

        # Check whether post storage file matches header
        if archiveHeader.storage is not None:
            if dataFileStats is None:
                if archiveHeader.storage.byteSize > 0: # File may be missing if it would be empty
                    opts = self.recoveryArbiter.onMissizedDataFile(
                        archiveHeader, dataFilename=dataFilename, size=None)
                    assert isinstance(opts, (RBackup, RDelete, RSkipDownload))
                    return opts
            else:
                if archiveHeader.storage.byteSize != dataFileStats.st_size:
                    opts = self.recoveryArbiter.onMissizedDataFile(
                        archiveHeader, dataFilename=dataFilename, size=dataFileStats.st_size)
                    if isinstance(opts, (RBackup, RDelete, RSkipDownload)):
                        return opts
                    else:
                        assert isinstance(opts, RReuse) # Correcting previous downloads
                        assert archiveHeader.storage.byteSize < dataFileStats.st_size
                        os.truncate(dataFilename, archiveHeader.storage.byteSize)
        else:
            if dataFileStats is not None and dataFileStats.st_size > 0: # Unexpected data file
                opts = self.recoveryArbiter.onMissizedDataFile(
                    archiveHeader, dataFilename=dataFilename, size=dataFileStats.st_size)
                if isinstance(opts, (RBackup, RDelete, RSkipDownload)):
                    return opts

        return headerInfo

    def processChannelAuxiliaries(self, channelOutfile: str, header: ChannelHeader, options: ChannelOptions, usedAttachments: List[FileAttachment]):
        '''Fetches additional data beside posts for given channel.'''
        if options.emojiMetadata:
            for emoji in header.usedEmojis:
                self.enrichEmoji(emoji)
        if options.downloadEmoji and not self.configfile.downloadAllEmojis:
            self.processEmoji('emojis', emojis=header.usedEmojis)

        if options.downloadAttachments and len(usedAttachments) > 0:
            self.processAttachments(channelOutfile+'--files', channelOpts=options, attachments=usedAttachments)

        if options.downloadAvatars:
            self.processAvatars('avatars', users=header.usedUsers)


    def processChannel(self, channelOutfile: str, header: ChannelHeader, channelRequest: ChannelRequest):
        channel, options = channelRequest.metadata, channelRequest.config

        headerFilename, dataFilename = self.makeArchiveFilenames(channelOutfile)
        showProgressReport = self.showProgressReport()

        def backupAltNames() -> Generator[str, None, None]:
            '''Yields alternative filenames for archive backups.'''
            i = 1
            while True:
                yield f'{channelOutfile}--backup~{i}'
                i += 1

        if options.postLimit == 0 or options.postSessionLimit == 0:
            return # Early exit - nothing downloaded, no need to touch header

        paramPack = self.loadPreviousChannelArchive(channel, headerFilename, dataFilename)
        if isinstance(paramPack, ChannelFileInfo):
            archiveFileInfo = paramPack
            archiveRecoveryStrategy = RReuse()
        else:
            archiveFileInfo = None
            archiveRecoveryStrategy = paramPack

        if isinstance(archiveRecoveryStrategy, RSkipDownload):
            return
        elif isinstance(archiveRecoveryStrategy, RDelete):
            if headerFilename.is_file():
                headerFilename.unlink()
            if dataFilename.is_file():
                dataFilename.unlink()
        elif isinstance(archiveRecoveryStrategy, RBackup):
            if self.backupArchive(channel, channelOutfile, channelOutfile+'--backup', backupAltNames()) == RSkipDownload():
                return

        header.storage = PostStorage.fromOptions(options)

        paramPack = self.getChannelDownloaderParams(options=options,
            archiveHeader=archiveFileInfo.header if archiveFileInfo is not None else None,
            lastChannelMessageTime=channel.lastMessageTime
        )
        if paramPack is None:
            return # Early exit - we don't need to download anything
        fromScratch, dlParams = paramPack

        if archiveFileInfo is not None:
            assert isinstance(archiveRecoveryStrategy, RReuse)

            opts = self.recoveryArbiter.onArchiveReuse(archiveFileInfo.header, options, reusable=not fromScratch)

            if isinstance(opts, RSkipDownload):
                return
            elif isinstance(opts, RDelete):
                if headerFilename.is_file():
                    headerFilename.unlink()
                if dataFilename.is_file():
                    dataFilename.unlink()
                archiveFileInfo = None
            elif isinstance(opts, RBackup):
                if self.backupArchive(channel, channelOutfile, channelOutfile+'--backup', backupAltNames()) == RSkipDownload():
                    return
                archiveFileInfo = None
            else:
                assert isinstance(opts, RReuse)
                # Old header is backed up for rollback
                if self.backupArchive(channel, channelOutfile, channelOutfile+'--backup', backupAltNames(), headerOnly=not fromScratch) == RSkipDownload():
                    return

        # By now, header file shouldn't exist and posts file should exist only if we're planning to append
        archiveHeader = archiveFileInfo.header if archiveFileInfo is not None else None

        try:
            attachments: List[FileAttachment] = []

            with open(dataFilename, 'w' if fromScratch else 'a', encoding='utf8') as output:
                if showProgressReport:
                    estimatedPostLimit: int = channel.messageCount
                    if options.postLimit != -1:
                        estimatedPostLimit = min(estimatedPostLimit, options.postLimit)
                    if options.postSessionLimit != -1:
                        estimatedPostLimit = min(estimatedPostLimit, options.postSessionLimit)

                    progressReporter = progress.ProgressReporter(sys.stderr, settings=self.configfile.reportProgress,
                        contentPadding=10, contentAlignLeft=False,
                        header='Progress: ', footer=f'/{estimatedPostLimit} posts (upper limit approximate)',
                        updateIntervalMs=self.configfile.progressInterval)
                    progressReporter.open()
                    progressReporter.update(f'0')
                else:
                    # Reporter should be never accessed in this case, but we want clear type for linting
                    progressReporter = cast(progress.ProgressReporter, UnboundLocalError)

                takeEmojis: bool = options.emojiMetadata or options.downloadEmoji

                def perPost(p: Post, hints: MattermostDriver.PostHints):
                    assert header.storage is not None

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
                    self.jsonDumpToFile(p.toStore(), output)
                    output.write('\n')

                    header.storage.addSortedPost(p, hints, options.downloadTimeDirection)
                    if showProgressReport:
                        progressReporter.update(str(header.storage.count))

                if showProgressReport:
                    skippedPostCount = 0
                    skippedLeadingMsg = False
                    def onSkippedPost():
                        nonlocal skippedLeadingMsg, skippedPostCount
                        if showProgressReport and skippedPostCount % 99 == 0:
                            if skippedLeadingMsg:
                                print('.', end='', file=sys.stderr, flush=True)
                            else:
                                print(' ...skipping posts not matching condition...', end='', file=sys.stderr, flush=True)
                                skippedLeadingMsg = True
                        skippedPostCount += 1
                else:
                    def onSkippedPost():
                        pass
                postProcessRes = self.driver.processPosts(processor=perPost, channel=channel, **dlParams, onSkippedPost=onSkippedPost)

                if showProgressReport:
                    progressReporter.close()
                if postProcessRes == MattermostDriver.ProcessPostResult.NothingRequested:
                    logging.info('Nothing to download.')
                elif postProcessRes == MattermostDriver.ProcessPostResult.NoMorePosts:
                    logging.info('Processed all posts.')
                elif postProcessRes == MattermostDriver.ProcessPostResult.MaxCountReached:
                    logging.info('Processed posts up to condition count.')
                else:
                    assert postProcessRes == MattermostDriver.ProcessPostResult.ConditionReached
                    logging.info('Processed up to selected condition.')

                # Update header's bytesize
                output.flush()
                header.storage.byteSize = os.fstat(output.fileno()).st_size

            self.processChannelAuxiliaries(channelOutfile, header, options, attachments)

            # Add to header content that is only relevant for nonfresh posts
            if archiveHeader is not None and not fromScratch:
                archiveHeader.update(header)
                header = archiveHeader

            # Store new header file
            headerContent = header.toStore()
            with open(headerFilename, 'w', encoding='utf8') as headerFile:
                self.jsonDumpToFile(headerContent, headerFile)
        except BaseException as err:
            # In appending mode, revert to pre-download state is done unconditionally
            if (isinstance(archiveRecoveryStrategy, RReuse) and not fromScratch):
                assert archiveFileInfo is not None
                oldDataFileSize = archiveFileInfo.dataFileStats.st_size if archiveFileInfo.dataFileStats is not None else None
                self.restoreArchiveBackup(channelOutfile, channelOutfile+'--backup', oldDataFileSize=oldDataFileSize)
            else:
                opts = self.recoveryArbiter.onPostLoadingFailure(header, headerFilename, dataFilename, err)
                if isinstance(opts, RDelete):
                    if headerFilename.is_file():
                        headerFilename.unlink()
                    if dataFilename.is_file():
                        dataFilename.unlink()
                    if isinstance(archiveRecoveryStrategy, RReuse):
                        assert fromScratch
                        # If we're willing to reuse, but started from the scratch,
                        # we can restore the backup back into primary
                        self.restoreArchiveBackup(channelOutfile, channelOutfile+'--backup')
                else:
                    assert isinstance(opts, RBackup)
                    # Just keep broken downloaded state
            raise

        # Now we can remove temporary backup
        if isinstance(archiveRecoveryStrategy, RReuse):
            backup1, backup2 = self.makeArchiveFilenames(channelOutfile+'--backup')
            if backup1.is_file():
                backup1.unlink()
            if backup2.is_file():
                backup2.unlink()

    def processDirectChannel(self, otherUser: User, channelRequest: ChannelRequest):
        # channel, options = channelRequest.metadata, channelRequest.config
        logging.info(f"Processing conversation with {otherUser.name} ...")

        directChannelOutfile = f'd.{self.user.name}--{otherUser.name}'
        header = ChannelHeader(channel=channelRequest.metadata)
        header.usedUsers = {self.user, otherUser}

        self.processChannel(channelOutfile=directChannelOutfile, header=header, channelRequest=channelRequest)

    def processGroupChannel(self, channelRequest: ChannelRequest):
        channel, options = channelRequest.metadata, channelRequest.config
        if channel.members is None:
            self.driver.loadChannelMembers(channel)
            assert channel.members is not None
        userlist = '-'.join(sorted(u.name for u in channel.members))
        if userlist == '':
            logging.warning(f'No users for group channel {channel.id}, using id as name!')
            userlist = str(channel.id)
        logging.info(f"Processing group chat {userlist} ...")
        channelOutfile = f'g.{userlist}'

        header = ChannelHeader(channel=channel)

        self.processChannel(channelOutfile=channelOutfile, header=header, channelRequest=channelRequest)

    def processTeamChannel(self, team: Team, channelRequest: ChannelRequest):
        '''
            Processes public and private channels
        '''
        channel, options = channelRequest.metadata, channelRequest.config

        private = channelRequest.metadata.type == ChannelType.Private

        logging.info(f'Processing {"private" if private else "public"} channel {team.internalName}/{channel.internalName} ...')
        channelOutfile = f'{"p" if private else "o"}.{team.internalName}--{channel.internalName}'

        header = ChannelHeader(channel=channel, team=team)

        self.processChannel(channelOutfile=channelOutfile, header=header, channelRequest=channelRequest)

    def __call__(self):
        '''
            Entrypoint of the Saver logic. Throws SavingFailed on known errors.
        '''
        if not self.configfile.outputDirectory.is_dir():
            self.configfile.outputDirectory.mkdir()
        m = self.driver

        logging.info(f'Logging in as {self.configfile.username}.')
        try:
            if self.configfile.token == '':
                m.login()
            self.user = m.loadLocalUser()
        except Exception as e:
            raise SavingFailed("Failed to log in. Check your credentials.") from e

        try:
            logging.info('Collecting metadata about available teams ...')
            teams = m.getTeams()
            if len(teams) == 0:
                raise SavingFailed(f'User {self.configfile.username} is not member of any teams!')

            logging.info('Collecting metadata about available channels ...')
            for team in teams.values():
                m.loadChannels(teamId=team.id)

            if self.configfile.downloadAllEmojis:
                logging.info('Downloading emoji database ...')
                emojis = self.driver.getEmojiList()
                for emoji in emojis:
                    self.enrichEmoji(emoji)
                self.processEmoji('emojis', emojis)

            logging.info('Selecting channels to download ...')
            directChannels, groupChannels = self.getWantedGlobalChannels()
            teamChannels = self.getWantedPerTeamChannels()

            logging.info('Processing channels ...')
            for user, channel in directChannels.items():
                self.processDirectChannel(user, channel)
            for channel in groupChannels:
                self.processGroupChannel(channel)
            for team, perTeamChannels in teamChannels.items():
                for channel in perTeamChannels:
                    self.processTeamChannel(team, channel)
        except KeyboardInterrupt:
            logging.info('Downloading interrupted.')
            return

        logging.info('Download process completed succesfully.')
