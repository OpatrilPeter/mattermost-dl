
import json
from pprint import pprint as pp
from pathlib import Path
from typing import Iterable, Optional, Set

from bo import *
from config import ConfigFile, EntityLocator as ConfigEntityLocator
from driver import MattermostDriver


class Saver:
    def __init__(self, configfile: ConfigFile, driver: Optional[MattermostDriver] = None):
        if not driver:
            driver = MattermostDriver(configfile)
        self.configfile = configfile
        self.driver: MattermostDriver = driver
        self.user: User # Conveniency, fetched on call

    def matchChannel(self, channel: Channel, locator: ConfigEntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return channel.id == locator.id
        elif hasattr(locator, 'name'):
            return channel.name == locator.name
        else:
            assert hasattr(locator, 'internalName')
            return channel.internalName == locator.internalName
    def matchTeam(self, team: Team, locator: ConfigEntityLocator) -> bool:
        if hasattr(locator, 'id'):
            return team.id == locator.id
        elif hasattr(locator, 'name'):
            return team.name == locator.name
        else:
            assert hasattr(locator, 'internalName')
            return team.internalName == locator.internalName

    def getWantedUsers(self) -> Set[User]:
        res = set()
        if not isinstance(self.configfile.users, list):
            return res
        for userLocator in self.configfile.users:
            if hasattr(userLocator, 'id'):
                res.add(self.driver.getUserById(userLocator.id))
            elif hasattr(userLocator, 'name'):
                res.add(self.driver.getUserByName(userLocator.name))
            elif hasattr(userLocator, 'internalName'):
                res.add(self.driver.getUserByName(userLocator.internalName))
        return res

    def getWantedDirectChannels(self) -> Dict[User, Channel]:
        res: Dict[User, Channel] = {}
        channelNames = {self.driver.getDirectChannelNameByUserId(u.id): u for u in self.getWantedUsers()}
        for team in self.driver.getTeams().values():
            for channel in team.channels.values():
                if channel.type == ChannelType.Direct and (self.configfile.users is True or channel.internalName in channelNames):
                    if channel.id not in (ch.id for ch in res.values()):
                        if self.configfile.users is True:
                            otherUser = self.driver.getUserById(self.driver.getUserIdFromDirectChannelName(channel.internalName))
                            res.update({otherUser: channel})
                        else:
                            res.update({channelNames[channel.internalName]: channel})
                            del channelNames[channel.internalName]

        # Have not found all channels!
        for user in channelNames.values():
            logging.warning(f'Found no direct channel with {user.name}.')
        return res

    def getWantedPublicChannels(self) -> Dict[Team, List[Channel]]:
        res: Dict[Team, List[Channel]] = {}
        teams = self.driver.getTeams()

        def getChannelsForTeam(team: Team, wantedChannels: List[ConfigEntityLocator]) -> List[Channel]:
            res = []
            for wch in wantedChannels:
                for ch in availableTeam.channels.values():
                    if ch.type != ChannelType.Direct and self.matchChannel(ch, wch):
                        res.append(ch)
                        break
                else:
                    logging.warning(f'Found no requested channel on team {team.internalName} ({team.name}) via locator {wch}.')
            return res

        if self.configfile.teams is True:
            res = {t: [ch for ch in t.channels.values()] for t in teams.values()}
        elif self.configfile.teams is False:
            pass
        else:
            assert isinstance(self.configfile.teams, list)
            for wantedTeam in self.configfile.teams:
                for availableTeam in teams.values():
                    if self.matchTeam(availableTeam, wantedTeam.team):
                        if wantedTeam.channels is True:
                            res[availableTeam] = [ch for ch in availableTeam.channels.values()
                                if ch.type != ChannelType.Direct
                            ]
                            # addChannels(team, [ch for ch in availableTeam.])
                        elif wantedTeam.channels is False:
                            pass
                        else:
                            assert isinstance(wantedTeam.channels, list)
                            res[availableTeam] = getChannelsForTeam(availableTeam, wantedTeam.channels)
                            # addChannels(team, wantedTeam.channels)
                        break
                else:
                    logging.error(f'Team requested by {wantedTeam.team} was not found!')
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
            del post.userId
            if hasattr(post, 'parent'):
                del post.parent # Without post.id the parent id is useless
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

    def processDirectChannel(self, otherUser: User, channel: Channel):
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

    def processPublicChannel(self, team: Team, channel: Channel):
        if channel.type == ChannelType.Group:
            logging.debug(f"Processing group chat {team.internalName}/{channel.internalName} ...")
        else:
            logging.debug(f"Processing channel {team.internalName}/{channel.internalName} ...")

        channelOutfile = f'{team.internalName}-{channel.internalName}'

        with open(self.configfile.outputDirectory / Path(channelOutfile + '.meta.json'), 'w') as output:
            content = {
                'team': team.toJson(includeChannels=False),
                'channel': channel.toJson()
            }
            self.jsonDumpToFile(content, output)
        with open(self.configfile.outputDirectory / Path(channelOutfile + '.data.json'), 'w') as output:
            def perPost(p: Post):
                self.enrichPost(p)
                self.jsonDumpToFile(p.__dict__, output)
                output.write('\n')
            self.driver.processPosts(processor=perPost, channel=channel)


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
        publicChannels = self.getWantedPublicChannels()
        for user, channel in directChannels.items():
            self.processDirectChannel(user, channel)
        for team in publicChannels:
            for channel in publicChannels[team]:
                self.processPublicChannel(team, channel)
