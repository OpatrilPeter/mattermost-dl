#!/bin/sh

print_help() {
    cat <<EOF
Prints number of posts per user of the given channel.

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


minify() {
    sed --regexp-extended 's/^\s*#.*$//' | tr '\n' ' ' | sed --regexp-extended 's/(\s)\s+/ /g'
}

JQLIB=$(minify <<'EOF'
# multiset (aka bag) is a dict value -> occurence_count and can incrementally compute histogram of of stream
def multiset(stream):
    reduce stream as $x ({}; .[$x|tojson] += 1 );
def multiset: multiset(.[]);
# Prints as array of pairs (value, occurences)
def multiset_show: to_entries | map([(.key | fromjson), .value]);

def hist(stream): multiset(stream) | multiset_show | sort_by(-.[1]);
EOF
)

users=$(<"$META" jq -c '.users | map({key: .id, value: .name}) | from_entries')

<"$DATA" jq -c .userId | jq -r --argjson users "$users" "$JQLIB"'hist(.,inputs) | map({user: (.[0] as $id | $users | .[$id]), counts: .[1]} | "\(.user) has \(.counts) posts") | .[]'
