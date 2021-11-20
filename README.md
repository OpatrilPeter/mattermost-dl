# Mattermost chat history downloader

## About

Simple local history downloader utility for Mattermost.

Saves posts and associated metadata about users, channels and servers into JSON format suitable for additional processing.
Logs in provided user as and saves only content visible to them.

## Overview of Mattermost entities

The basic entity is a communication Channel, where various Users add Posts. Post is single message created at specific time by one User composed mainly of text, with possible file Attachments and Reactions from other users. There are direct channels for private communication between two users, group channels for a fixed set of users and named channels for general public (with private, invitation only variant also available). Channels are grouped to a larger unit called a Team, useful as unit for managing membership and permissions. Mattermost server may have one or more Teams.

Note that there is only one instance of a given direct channel that all Teams share.

## Usage

`mattermost-dl` is a command-line tool mainly controlled by a single JSON configuration file.
This file is either passed explicitly as argument or read from `mattermost-dl.json` in current working directory, `$XDG_CONFIG_HOME` or `$HOME/.config`.

This configuration file allows high degree of configurability, setting options on level of concrete channels, channel kinds or specific teams. It also makes it easy to run the downloader repeatedly and download only new content since the last run.

The minimal amount of required settings include server's address and appropriate login credentials - the minimalist config may look like this:

```json
{
  "version": "0",
  "connection": {
    "hostname": "https://mattermost-server.com",
    "username": "user.name",
    // "password": "swordfish",
    "token": "deadb33f"
  }
}
```

Of these, either password or Mattermost access token may be provided. Token is preferred if possible - either make a permanent one if your permissions allow it or extract a session token from your conventional interactive session (such as the `MMAUTHTOKEN` cookie in a browser session).

You may also specify/override those fields from following alternate sources in order of priority:

- command line (run with `--help` for list of options)
- environmental variables (see later section for list of supported ones)

On default settings, all channels gets downloaded with unbounded history, so you may consider adding limits - recommended ways are:

- downloading only specific channel(s)
- download only all direct channels
- limit maximum number of posts that'd be ever downloaded from a channel
- download only content made after specific date

Full configuration options are described via configuration file's [JSON schema](mattermost_dl/config.schema.json).

Contents are saved in a directory set by the `output.directory` setting (current working directory by default) - each channel gets stored in two files as described in section Storage format, data files are stored in respective subdirectories.

## Configuration examples

Required connection settings described already above are ommited for posterity.

Note that comments (lines with `#`) are not actually allowed in json.

If your test editor supports json schema based validation and suggestions, I'd recomend setting the configuration like this:

```json
{
  "$schema": "path/to/json/schema/file/config.schema.json"
}
```

### Download all channels

Downloads complete history of all available channels.
Doesn't download auxiliary data like file attachments or custom emoji.

```json
{
}
```

### Customize download options for groups of channels

Limit only up to total count of 10000 posts (to limit very spammy channels), with additional limit for this specific session to 1000 (to make the update faster).

```json
{
  "defaultChannelOptions": {
    "maximumPostCount": 10000,
    "sessionPostLimit": 1000
  },
  # Override for more specific group of channels
  "directChannelOptions": {
    # For personal peer-to-peer channels, we don't want limits
    "maximumPostCount": -1,
    "sessionPostLimit": -1
  }
  "users": [
    {
      "name": "spammy.mcperson",
      # We can override settings per individual channel
      "sessionPostLimit": 100
    }
  ]
}
```

Note that more specific channel settings, if present, _completely replace_ more general settings - settings are not merged.

Download all private channels, but only selected public channels.

```json
{
  # Without this, all teams are downloaded - list in "teams" just specifies overrides
  # With this, only teams mentioned in "teams" are downloaded
  "downloadTeams": false,
  "teams": [
    {
      "team": {"name": "Team"},
      "downloadPublicChannels": false,
      "publicChannels": [
        {"internalName": "public1"},
        {"internalName": "public2"}
      ],
      "publicChannelOptions": {
        # We only want a sample of those public channels
        "sessionPostLimit": 100
      }
    }
  ]
}
```

### Download specific channel

Public/private channel:

```json
{
  # Download only explicitly chosen channels
  "downloadTeams": false,
  "downloadUserChannels": false,
  "downloadGroupChannels": false,

  "teams": [
    {
      "team": {
        "name": "Team"
        # We could also identify team by its internal name - `internalName` (which is unambiguous) or internal id
      },
      # Again, download only explicitly chosen channels
      "downloadPublicChannels": false,
      "downloadPrivateChannels": false,

      # Or `privateChannels`
      "publicChannels": [
        {
          "name": "Channel name"
          # Channel specific download constraints go here
        }
      ]
    }
  ]
}
```

Group channel:

```json
{
  "groups": [
    {
      "group": [
        {"name": "member user 1"},
        {"name": "member user 2"},
        {"name": "member user 3"}
      ],
      # Usual channel options are supported
      "downloadFromOldest": false
    },
    {
      "group": "abcdef" # Channel Id is also supported
    }
  ]
}
```

Direct (one-on-one, user-specific) channel:

```json
{
  # To stop downloading OTHER user cannels
  "downloadUserChannels": false,

  "users": [
    {
      "name": "username",
      # Usual channel options are supported
    }
  ]
}
```

Skip downloading specific channel:

```json
{
  "users": [
    {
      "name": "unwanted-chatter",
      "maximumPostCount": 0
    }
  ]
}
```

### Download only messages in some time range

Download things after date:

```json
{
  "defaultChannelOptions": {
    "afterTime": "1970-01-01"
  }
}
```

Available time formats are:

- ISO datetime (`"1970-01-01T01:23:45.832330"`)
- Unix timestamp in ms (`12345`)

Download things in interval:

```json
{
  "defaultChannelOptions": {
    "afterTime": "1970-01-01",
    "beforeTime": "2000-01-01"
  }
}
```

Download thing after specific post:

```json
{
  "defaultChannelOptions": {
    "afterPost": "abcdef" # Post Id
  }
}
```

Download and keep only last 10 messages:

```json
{
  "users": [
    {
      "name": "username",
      "downloadFromOldest": false,
      "messageCount": 10,
      "onExistingIncompatible": "delete"
    }
  ]
}
```

### Download everything we can

```json
{
  # These are on by default
  "downloadTeams": true,
  "downloadUserChannels": true,
  "downloadGroupChannels": true,

  # Custom (non-builtin) emojis can be downloaded either completely this way or just the ones being used (in channel options)
  "downloadEmojis": true,

  "defaultChannelOptions": {
    "emojis": {
      "download": true
    },
    "avatars": {
      "download": true
    }
  },
  "directChannelOptions": {
    # Downloading files in public channels could be bad idea
    "attachments": {
      "download": true,
      # Optional sanity filters
      "maxSize": 10485760, # 10MB
      "allowedMimeTypes": [
        "application/pdf"
      ]
    }
  }
}
```

### Reduce backup creation

By default, lot of care exist to prevent loss of already downloaded data.
That leads to keeping intermediate data on errors and interrupted downloads and backing up the channel in case it's redownloaded when the required options for that channel aren't compatible with appending into previous storage.
Those backups can be distingushed by having `--backup` in their name and should be removed manually if not required.

The redownload case can be configured like so:

```json
{
  "defaultChannelOptions": {
    # If we can append into current archive, should we do it or redownload from scratch?
    "onExistingCompatible": "update",
    # If we do have to redownload, don't keep old archive
    "onExistingIncompatible": "delete"
  }
}
```

## Supported environmental variables

- `MATTERMOST_SERVER`
- `MATTERMOST_USERNAME`
- `MATTERMOST_PASSWORD`
- `MATTERMOST_TOKEN`

## Storage format

Downloaded archives are stored as pair of files containing JSON data, pair for each channel.

The `*.data.json` file contains newline-delimited Post data - that is, each line is a single post, along with additional post's metadata such as file attachments.

The matching `*.meta.json` contains single object describing Channel, it's encompassing Team, participating Users (along with their metadata) and information about downloaded posts. It's important that both files are kept in sync, as knowledge of post's storage state allows efficient incremental download resulting in append-only optimization in typical case.

Precise format is formally described in detail via following schemas - [of meta file](mattermost_dl/header.schema.json) and [of individual posts](mattermost_dl/post.schema.json).

The format was chosen carefully to be

- forward compatible (explicit versioning)
- data source independent (not mirroring Mattermost's API - should be good enough even with later versions or similar platforms such as Discord)
- lossless (unknown fetches fields are preserved in untyped dict fields `misc` of appropriate entity)
- well defined (see provided JSON schemas)
- optimized for efficient appending (as described earlier)

## How do I see the downloaded messages?

While _presentation_ of the stored data is technically out of scope of this project,
if you're on Unix-based platform with Bourne shell and [jq](https://github.com/stedolan/jq), you can use simple utilities provided in `scripts/` folder.

Notably,

- `read-channel.sh` will format message contents to the terminal as basic viewer (not necessarily with all possible information)
- `to-discord-tracker.sh` will perform lossy conversion to format used by [Discord History Tracker](https://github.com/chylex/Discord-History-Tracker)'s archives, a project of similar intent that comes with offline HTML based archive viewer

## Internal design

Code is written in statically typed Python 3.7+.

As this is a one-time side project and Mattermost's API availabilty is fundamentally ephemeral, the code isn't tested to rigorous "production-ready" standards.
In particular, many combinations of configuration options are not tested enough and would benefit from proper unit tests and/or whole program tests with mocked REST endpoints.

Additionally, as this project served as personal evaluation of coding styles, I've opted for some design choices not usual for Python code, such as:

- camel case / lowercase naming convention
- common prelude over explicit imports everywhere
- prefer handling (reporting) problem context locally over creating exceptions with complex payloads
- do not typically name private methods with prefix underscore - rationale is decreased readibility that isn't worth it, especially as this module is not primarily intended to be library.
  The only methods that ought to be marked private would be those that could break class invariants. Usage of the class ought to be still clear, though, documented in class if needed
- line wrapping is capped on around 110 as a soft limit, actual wrapping is judged on case-by-case basis

## References

- API reference - <https://api.mattermost.com>
- alternative, fully featured Python MM client library - <https://github.com/Vaelor/python-mattermost-driver>
