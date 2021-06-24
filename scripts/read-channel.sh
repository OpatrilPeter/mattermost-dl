#!/bin/sh

print_help() {
    cat <<EOF
Provides basic visualization of channel's posts suitable for ANSI terminal.

Usage:
$0 <CHANNEL_NAME>
where
    CHANNEL_NAME is archive's filename,
        for example 'd.user1--user2' for pair of files
            'd.user1--user2.meta.json', 'd.user1--user2.data.json'
EOF
}

require_tool() {
    if ! which $1 >/dev/null; then
        echo "Cannot find required tool '$1' in path." >&2
        exit 1
    fi
}

require_tool jq


META=$1.meta.json
DATA=$1.data.json

if [ $# -ne 1 ]; then
    echo "Missing channel name." >&2
    print_help
    exit 1
fi
if [ "$1" = "-h" -o "$1" = "--help" ]; then
    print_help
    exit 0
fi
if ! [ -f "$META" -o -f "$DATA" ]; then
    echo "Can't find required data for channel named '$1'." >&2
    print_help
    exit 1
fi


users=$(<"$META" jq -c '.users | map({key: .id, value: .name}) | from_entries')

format='"[32;1m\(.userName)[0m·[34;1m\(.createTime)[0m:\n\(.message)\n[35m⋯⋯⋯⋯⋯[0m"'

<"$META" jq -r '"[93m## \(.channel.name) ##[0m\n"'
<"$DATA" jq -r --argjson users "$users" '.userName = (.userId as $id | $users | .[$id]) | .createTime |= (./1000 | todateiso8601) | '"$format"
