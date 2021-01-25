
from typing import Iterable, Optional, Set
from pprint import pprint as pp

from config import ConfigFile, EntityLocator as ConfigEntityLocator
from driver import MattermostDriver

from bo import *

class Saver:
    def __init__(self, configfile: ConfigFile, driver: Optional[MattermostDriver] = None):
        if not driver:
            driver = MattermostDriver(configfile)
        self.configfile = configfile
        self.driver: MattermostDriver = driver

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
                else:
                    logging.warning(f'Found no requested channel on team {team.internalName} via locator {wch}.')
            return res
            return [ch
                for ch in availableTeam.channels.values()
                for wch in wantedChannels if self.matchChannel(ch, wch)
            ]

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

    def processDirectChannel(self, otherUser: User, channel: Channel):
        logging.debug(f"Processing conversation with {otherUser.name} ...")
    def processPublicChannel(self, team: Team, channel: Channel):
        if channel.type == ChannelType.Group:
            logging.debug(f"Processing group chat {team.name}/{channel.name} ...")
        else:
            logging.debug(f"Processing channel {team.name}/{channel.name} ...")

    def __call__(self):
        if not self.configfile.outputDirectory.is_dir():
            self.configfile.outputDirectory.mkdir()
        m = self.driver

        if self.configfile.token == '':
            m.login()
        m.loadLocalUser()

        teams = m.getTeams()
        if len(teams) == 0:
            logging.fatal(f'User {self.configfile.username} is not member of any teams!')
            return

        defaultTeamId = next(t for t in teams)
        for team in teams.values():
            m.loadChannels(teamId=team.id)

        directChannels = self.getWantedDirectChannels()
        publicChannels = self.getWantedPublicChannels()
        for user, channel in directChannels.items():
            self.processDirectChannel(user, channel)
        for team in publicChannels:
            for channel in publicChannels[team]:
                self.processPublicChannel(team, channel)



