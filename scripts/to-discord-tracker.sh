#!/bin/sh

# Converts the internal format to savefile format of Discord History Tracker (https://github.com/chylex/Discord-History-Tracker) as it features standalone HTML history viewer.
# The conversion is lossy

# $1 is channel name



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
                name: .name
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
