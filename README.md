# Mattermost chat history downloader

## About

Simple local history downloader utility for Mattermost.

## Usage

_More detailed usage guide will be written later._

Fill `mattermost-dl.json` config file with appropriate login requirements (see config.schema.json for guidenance about supported contents). If not using user/password pair, you can also use access token - either a permanent one or take one from cookies of conventional logged in browser session (stored as `MMAUTHTOKEN`).

Run the `mattermost_dl` module with provided config file (either passed explicitly or read from `mattermost-dl.json` in current working directory, `$XDG_CONFIG_HOME` or `$HOME/.config`).
Module may be also installed as a console script, then `mattermost-dl` should be executable directly.

Downloaded archives are stored as pair of files containing JSON data, pair for each channel.

## How do I see the downloaded messages?

While _presentation_ of the stored data is technically out of scope of this project,
if you're on Unix-based platform with Bourne shell and [jq](https://github.com/stedolan/jq), you can use simple utilities provided in `scripts/` folder.

Notably,

- `read-channel.sh` will format message contents to the terminal as basic viewer (not necessarily with all possible information)
- `to-discord-tracker.sh` will perform lossy conversion to format used by [Discord History Tracker](https://github.com/chylex/Discord-History-Tracker)'s archives, a project of similar intent that comes with offline HTML based archive viewer

## Internal design

Code is written in statically typed Python 3.7+.

As this is a one-time side project and Mattermost's API availabilty is fundamentally ephemeral, the code isn't tested to "production-ready" standards.

Additionally, I've opted for some design choices not usual for Python code, such as

- camel case / lowercase naming convention
- common prelude over explicit imports everywhere
- prefer handling (reporting) problem context locally rather than creating exceptions with complex payloads

The internal data format was chosen carefully to be

- forward compatible (explicit versioning)
- data source independent (not mirroring Mattermost's API - should be good enough even with later versions or similar platforms such as Discord)
- lossless (unknown fetches fields are preserved in untyped dict fields `misc` of appropriate entity)
- well defined (see provided json schemas)
- optimized for efficient appending (the header containing metadata is separate file from the (generally) presorted payload (requiring no read, append-only))

## References

- API reference - <https://api.mattermost.com>
- alternative, fully featured Python MM client library - <https://github.com/Vaelor/python-mattermost-driver>
