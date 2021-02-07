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

JQLIB=$(cat <<'EOF'
# multiset (aka bag) is a dict value -> occurence_count and can incrementally compute histogram of of stream
def multiset(stream):
    reduce stream as $x ({}; .[$x|tojson] += 1 );
def multiset: multiset(.[]);
# Prints as array of pairs (value, occurences)
def multiset_show: to_entries | map([(.key | fromjson), .value]);

def hist(stream): multiset(stream) | multiset_show | sort_by(-.[1]);
EOF
)
# Minify
JQLIB=$(echo "$JQLIB" | sed 's/^\s*#.*$//' | tr '\n' ' ' | sed 's/\s\s+//')

users=$(<"$META" jq -c '.users | map({key: .id, value: .name}) | from_entries')

<"$DATA" jq -c .userId | jq -r --argjson users "$users" "$JQLIB"'hist(.,inputs) | map({user: (.[0] as $id | $users | .[$id]), counts: .[1]} | "\(.user) has \(.counts) posts") | .[]'
