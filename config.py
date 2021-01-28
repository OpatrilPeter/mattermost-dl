
from dataclasses import dataclass
import json
from pathlib import Path
import os
from typing import List, NamedTuple, Union

from bo import Id

class EntityLocator:
    def __init__(self, info: dict):
        if len(info) != 1:
            raise ValueError
        for key in info:
            if key not in ('id', 'name', 'internalName'):
                raise ValueError
        if 'id' in info:
            self.id: Id = info['id']
        if 'name' in info:
            self.name: str = info['name']
        if 'internalName' in info:
            self.internalName: str = info['internalName']
    def __repr__(self) -> str:
        return f'EntityLocator({self.__dict__})'

# Options are All (true), None (false), or explicit list
EntityList = Union[bool, List[EntityLocator]]

@dataclass
class TeamSpec:
    team: EntityLocator
    channels: EntityList = True

@dataclass
class ConfigFile:
    hostname: str
    username: str
    password: str = ''
    token: str = ''

    throttlingLoopDelay: int = 0
    teams: Union[bool, List[TeamSpec]] = True
    users: EntityList = True

    outputDirectory: Path = Path()
    verboseStandalonePosts: bool = False
    verboseHumanFriendlyPosts: bool = False

def readConfig(filename):
    with open(filename) as f:
        config = json.load(f)
        res = ConfigFile(
            hostname=config['hostname'],
            username=config['username'],
            password=config.get('password', os.environ.get('MATTERMOST_PASSWORD', '')),
            token=config.get('token', os.environ.get('MATTERMOST_TOKEN', '')),
        )
        if 'throttling' in config:
            res.throttlingLoopDelay = config['throttling']['loopDelay']
        if 'output' in config:
            if 'directory' in config['output']:
                res.outputDirectory = Path(config['output']['directory'])
            if 'standalonePosts' in config['output']:
                res.verboseStandalonePosts = config['output']['standalonePosts']
            if 'humanFriendlyPosts' in config['output']:
                res.verboseHumanFriendlyPosts = config['output']['humanFriendlyPosts']

        if 'teams' in config:
            assert isinstance(config['teams'], list)
            if len(config['teams']) == 0:
                res.teams = False
            else:
                res.teams = []
                for teamDict in config['teams']:
                    teamspec = TeamSpec(team=EntityLocator(teamDict['team']))
                    if 'channels' in teamDict:
                        assert isinstance(teamDict['channels'], list)
                        teamspec.channels = [EntityLocator(chan) for chan in teamDict['channels']]
                    res.teams.append(teamspec)

        if 'users' in config:
            assert isinstance(config['users'], list)
            if len(config['users']) == 0:
                res.users = False
            else:
                res.users = [EntityLocator(user) for user in config['users']]

    return res
