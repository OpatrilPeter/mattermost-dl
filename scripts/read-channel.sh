#!/bin/sh

# $1 is channel name

META=$1.meta.json
DATA=$1.data.json

if [ $# -ne 1 ]; then
    echo "Missing channel name." >&2
    exit 1
fi
if ! [ -f "$META" -o -f "$DATA" ]; then
    echo "Can't find required data for channel named '$1'." >&2
    exit 1
fi

users=$(<"$META" jq -c '.users | map({key: .id, value: .name}) | from_entries')

format='"[32;1m\(.userName)[0m·[34;1m\(.createTime)[0m:\n\(.message)\n[35m⋯⋯⋯⋯⋯[0m"'

<"$META" jq -r '"[93m## \(.channel.name) ##[0m\n"'
<"$DATA" jq -r --argjson users "$users" '.userName = (.userId as $id | $users | .[$id]) | .createTime |= (./1000 | todateiso8601) | '"$format"
