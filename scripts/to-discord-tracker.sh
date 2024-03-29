#!/bin/sh

print_help() {
    cat <<EOF
Converts the internal format to savefile format of Discord History Tracker (https://github.com/chylex/Discord-History-Tracker) as it features standalone HTML history viewer.
The conversion is lossy!

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


META=$1.meta.json
DATA=$1.data.json

minify() {
    sed --regexp-extended 's/^\s*#.*$//' | tr '\n' ' ' | sed --regexp-extended 's/(\s)\s+/ /g'
}

MAKE_USERS=$(minify <<'EOF'
.users | map({key: .id, value: {name: .name, tag: "0000", avatar: ""}}) | from_entries
| {
    users: .,
    userindex: (to_entries | map(.key))
}
EOF
)
USERS=$(<"$META" jq -c "$MAKE_USERS")
USERINDEX=$(echo "$USERS" | jq -c .userindex)

MAKE_SERVERS=$(minify <<'EOF'
{
    servers: [(
        if .channel.type == "Group" then
            {type: "GROUP", name: (.users | map(.name) | join(" "))}
        elif .channel.type == "Direct" then
            {type: "DM", name: (.users | .[1] | .name)}
        else
            {type: "SERVER", name: .team.name}
        end
    )],
    channels: (
        if .channel.type == "Group" then
            {(.channel.id): {
                server: 0,
                name: (.users | map(.name) | join(" "))
            }}
        elif .channel.type == "Direct" then
            {(.channel.id): {
                server: 0,
                name: (.users | .[1] | .name)
            }}
        else
            {(.channel.id): {
                server: 0,
                name: .channel.name
            }}
        end
    )
}
EOF
)
SERVERS=$(<"$META" jq "$MAKE_SERVERS")
CHANNELID=$(<"$META" jq '.channel.id')

RESULT_META=$(jq -c -n --argjson users "$USERS" --argjson servers "$SERVERS" '$users + $servers')

MAKE_POST=$(minify <<'EOF'
{
    u: (.userId as $userId | $userIndex | index($userId) // $userId),
    t: .createTime,
    m: .message
}
EOF
)
# We put messages in not ordered by real post id but by increasing integers to keep the result sorted
MAKE_DATA=$(minify <<EOF
    (map({key: .createTime | tostring, value: $MAKE_POST}) | from_entries)
EOF
)
<"$DATA" jq -c --slurp --argjson channelId "$CHANNELID" --argjson userIndex "$USERINDEX" "{meta: $RESULT_META, data: {($CHANNELID): $MAKE_DATA}}"
