# Mattermost chat history downloader

## About

Simple local history downloader utility for Mattermost.

Saves posts and associated metadata about users, channels and servers into JSON format suitable for additional processing.
Logs in provided user as and saves only content visible to them.

## Overview of Mattermost entities

The basic entity is a communication Channel, where various Users add Posts. Post is single message created at specific time by one User composed mainly of text, with possible file Attachments and Reactions from other users. There are direct channels for private communication between two users, group channels for a fixed set of users and named channels for general public (with private, invitation only variant also available). Channels are grouped to a larger unit called a Team, useful as unit for managing membership and permissions. Mattermost server may have one or more Teams.

Note that there is only one instance of a given direct channel that all Teams share.

## Installation

This is a conventional Python utility installable via `setuptools` module, typically by `pip`, Python package manager.

This program is not available on its standard repository, as I make commitment to compatibility with future Mattermost versions.
Possible ways to install it directly from downloaded sources are following:

```sh
# Assumes your python instalation provides python and pip binaries in standard path
cd path/to/downloded/sources/mattermost-dl

# Now, any of the following commands should work

# (recommended) Through pip, user-wide
pip install --user .
# Through pip, system-wide. May require elevated privileges
pip install .

# For developers: editable install, so changed sources reflect immediately
pip install -e .
# or by invoking setup.py direcrly (useful as user-wide editable installs don't work in some pip versions - https://github.com/pypa/pip/issues/7953)
python setup.py develop
python setup.py --user develop
```

Dependencies should be downloaded automatically.

After installation, `mattermost-dl` should be available from command line.
Alternatively, running the module directly should also be possible:

```sh
python -m mattermost_dl
```

## Usage

`mattermost-dl` is a command-line tool mainly controlled by a single JSON or TOML configuration file of equivalent structure.
Rest of this document will usually use TOML format as it support comments.
This file is either passed explicitly as argument or read from `mattermost-dl.toml`/`mattermost-dl.json` in current working directory, `$XDG_CONFIG_HOME`, `$HOME/.config` or `$HOME`.

This configuration file allows high degree of configurability, setting options on level of concrete channels, channel kinds or specific teams. It also makes it easy to run the downloader repeatedly and download only new content since the last run.

The minimal amount of required settings include server's address and appropriate login credentials - the minimalist config may look like this:

```toml
version = "1"

[connection]
hostname = "https://mattermost-server.com"
username = "user.name"
# password = "swordfish"
token = "deadb33f"
```

Or in JSON:

```json
{
  "version": "1",
  "connection": {
    "hostname": "https://mattermost-server.com",
    "username": "user.name",
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

Required connection settings (described already above) are ommited for posterity.

If your test editor supports json schema based validation and suggestions, I'd recomend setting the configuration like this:

```json
{
  "$schema": "path/to/json/schema/file/mattermost-dl/mattermost_dl/config.schema.json"
}
```

### Download all available channels

This constitutes the default behavior and other settings are defined as overrides or amends of this behavior.

What "available" means? All channel user given user has access to. That means all

- channels currently being subscribed to
- all direct user-user and group channels featuring given user

Notably, left public & private channels aren't downloaded and private channels
once left cannot be reentered without the invite.

> Downloads posts, not auxiliary data like file attachments or custom emoji.

```json
{
}
```

### Customize download options for groups of channels

> Limit only up to total count of 10000 posts (to limit very spammy channels), with additional limit for this specific session to 1000 (to make the update faster).

```toml
[defaultChannelOptions]
maximumPostCount = 10000
sessionPostLimit = 1000

# Override for more specific group of channels
[userChannelOptions]
# For personal peer-to-peer channels, we don't want limits
maximumPostCount = -1
sessionPostLimit = -1

[[users]]
name = "spammy.mcperson"
# We can override settings per individual channel
sessionPostLimit = 100
```

Note that more specific channel download settings, if present, override more general settings.

> Download all private channels, but only selected public channels.

```toml
# Without this, all teams are downloaded - list in "teams" just specifies overrides
# With this, only teams mentioned in "teams" are downloaded
downloadTeamChannels = false

[publicChannelOptions]
# We only want a sample of those public channels
sessionPostLimit = 100

[[teams]]
team.name = "Team"
downloadPublicChannels = false
publicChannels = [
  {internalName = "public1"},
  {internalName = "public2"}
]
```

### Download specific channel

> Public/private channel:

```toml
# Download only explicitly chosen channels
downloadTeamChannels = false
downloadUserChannels = false
downloadGroupChannels = false

[[teams]]
# We could also identify team by its displaed `name` (which can be ambiguous) or internal `id`
team.internalName = "Team"
# Again, download only explicitly chosen channels
downloadPublicChannels = false
downloadPrivateChannels = false

# Settings for specific public channels. Equvalently we could specify `privateChannels`
[[teams.publicChannels]]
name = "Channel name"
# Channel specific download constraints go here

[[teams.publicChannels]]
name = "Another channel under team Team"
```

> Group channel:

```toml
[[groups]]
group = [
  {name = "member user 1"},
  {name = "member user 2"},
  {name = "member user 3"}
  # User we're downloading as is there implicitly
]
# Usual channel options are supported
downloadFromOldest = false

[[groups]]
# We could specify group by usual Channel Id as well
group = "abcdef"
```

> Direct (one-on-one, user-specific) channel:

```toml
# To stop downloading OTHER user cannels
downloadUserChannels = false

[[users]]
name = "username"
# Usual channel options are supported
```

> Skip downloading specific channel:

```toml
[[users]]
name = "unwanted-chatter"
maximumPostCount = 0
```

### Download only messages in some time range

> Download things after date:

```toml
[defaultChannelOptions]
afterTime = "1970-01-01"
```

Available time formats are:

- ISO datetime (`"1970-01-01T01:23:45.832330"`)
- Unix timestamp in ms (`12345`)

> Download things in interval:

```toml
[defaultChannelOptions]
afterTime = "1970-01-01"
beforeTime = "2000-01-01"
```

> Download thing after specific post:

```toml
[defaultChannelOptions]
afterPost = "abcdef" # Post Id
```

> Download and keep only last 10 messages:

```toml
[[users]]
name = "username"
downloadFromOldest = false
maximumPostCount = 10
onExistingIncompatible = "delete"
```

### Download everything we can

```toml
# These are on by default
downloadTeamChannels = true
downloadUserChannels = true
downloadGroupChannels = true

# Custom (non-builtin) emojis can be downloaded either completely this way or just the ones being used (in channel options)
downloadEmojis = true

[defaultChannelOptions]
# Downloading files blindly in public channels could be bad idea
attachments.download = false # Is false by default
avatars.download = true
emojis.download = true

[userChannelOptions.attachments]
download = true
# Optional sanity filters
maxSize = 10485760 # 10MB
allowedMimeTypes = [
  "application/pdf"
]
```

### Reduce backup creation

By default, lot of care exist to prevent loss of already downloaded data.
That leads to keeping intermediate data on errors + interrupted downloads and backing up the channel in case it's redownloaded when the required options for that channel aren't compatible with appending into previous storage.
Those backups can be distingushed by having `--backup` in their name and should be removed manually if not required.

The redownload case can be configured like so:

```toml
[defaultChannelOptions]
# If we can append into current archive, should we do it or redownload from scratch?
onExistingCompatible = "update"
# If we do have to redownload, don't keep old archive
onExistingIncompatible = "delete"
```

## Supported environmental variables

(Overrides respective config setting.)

- `MATTERMOST_SERVER`
- `MATTERMOST_USERNAME`
- `MATTERMOST_PASSWORD`
- `MATTERMOST_TOKEN`

## Automation

`mattermost-dl` doesn't have any direct provisions for automatic (scheduled) mode of execution, however, it's not hard to wrap it for any scheduling system capable of running CLI scripts.
Sample implementation for Bourne shell ([mattermost-dl-job.sh](scripts/mattermost-dl-job.sh)) and related [`cron`](scripts/mattermost-dl.cron) schedule specification is provided.

## Storage format

Downloaded archives are stored as pair of files containing JSON data, pair for each channel.

The `*.data.json` file contains newline-delimited Post data - that is, each line is a single post, along with additional post's metadata such as file attachments.

The matching `*.meta.json` contains single object describing Channel, it's encompassing Team, participating Users (along with their metadata) and information about downloaded posts. It's important that both files are kept in sync, as knowledge of post's storage state allows efficient incremental download resulting in append-only optimization in typical case.

Precise format is formally described in detail via following schemas - [of meta file](mattermost_dl/header.schema.json) and [of individual posts](mattermost_dl/post.schema.json).

The format was chosen carefully to be

- forward compatible (explicit versioning)
- data source independent (not mirroring Mattermost's API - should be good enough even with later versions or similar platforms such as Discord)
- lossless (unknown fetches fields are preserved in untyped dict fields `misc` of appropriate entity)
  - note that some metadata provided by Mattermost API are known to not be useful for keeping local history and are dropped
- well defined (see provided JSON schemas)
- optimized for efficient appending (as described earlier)

## Frequently asked questions

### How can I display the downloaded messages?

While _presentation_ of the stored data is technically out of scope of this project,
if you're on Unix-based platform with Bourne shell and [jq](https://github.com/stedolan/jq), you can use simple utilities provided in `scripts/` folder.

Notably,

- `read-channel.sh` will format message contents to the terminal as basic viewer (not necessarily with all possible information)
- `to-discord-tracker.sh` will perform lossy conversion to format used by [Discord History Tracker](https://github.com/chylex/Discord-History-Tracker)'s archives, a project of similar intent that comes with offline HTML based archive viewer

### Why does download of long channel with certain time constraints take such long time to start?

Current Mattermost API is suited for fetching posts from latest to oldest and only certain constraints can be evaluated serverside.
In certain cases, such as "downloading from oldest, grab 100 posts after certain date.", we must actually process all posts from the channel begginning right until the time condition starts passing.
In general, it's very fast to download posts before or after some explicit post, which makes successive downloads (fetching updates) much faster.

### What does "upper limit approximate" mean during download?

In many cases, it's unclear or impractical to calculate how many posts will actually be downloaded.
For example, if our selection condition is arbitrary such as "1000 posts after date 2020-01-01" - we don't know until how many messages would match that.
Sometimes, we may have an estimation; for example, hard limit of 10 posts mean we surely won't get _more_ than 10, but we still don't know if less than 10 are really available.
Likewise, Mattermost server may provide total number of channel's posts, but this count doesn't have to reflect what we can actually download even if we're downloading the whole channel, as it's approximate - for example, deleted posts are not fetched.

### Known issues?

Unknown configuration options are warned about in general case, but some more advanced cases aren't caught by used underlying json schema validation library, such as unknown channel options.
Caused by combination of anchor (`$ref`) and disallowed `additionalProperties`.

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

## Project status

After 1.0 release there are currently no guarantees for further active development, aside from bugfixes. That notably includes support for possible later Mattermost APIs.

## References

- API reference - <https://api.mattermost.com>
- alternative, fully featured Python MM client library - <https://github.com/Vaelor/python-mattermost-driver>
