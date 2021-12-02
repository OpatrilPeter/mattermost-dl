#!/bin/sh

set -o errexit

print_help() {
    cat >&2 <<EOF
This script runs mattermost-dl noninteractively, typically from scheduler system
Stays silent on success, calls error report handler sh script (with application's output) on failure

Usage:
$0 <OPTS> [-- <EXTRA_ARGS>]
Options:
  --cwd  <DIR>       Use given current working directory
  --conf  <CONF>     [default: none (inherited from mattermost-dl defaults]
  --handler <CMD>    [default: printing downloader's output on standard output]
                     Describes handling of case where mattermost-dl failed (produced content on
                     standard error output). Takes form of line evaluated as sh script,
                     with following substituable wildcards:
                       {retcode} - return code of the invocation
                       {date} - time of invocation in format viable for inclusion in filenames
                       {stdout} - temporary file containing downloader's standard output
                       {stderr} - temporary file containing downloader's standard error output
                     example:
                       'cat {stdout} {stderr} >~/mattermost-dl-fail-report-{date}.txt'
EOF
}

require_tool() {
    if ! which $1 >/dev/null; then
        echo "Cannot find required tool '$1' in path." >&2
        exit 1
    fi
}

require_tool mattermost-dl
require_tool date
require_tool sed
require_tool tr

parse_args() {
    CONFIG_PATH="" # Invalid value
    ERR_HANDLER="printf 'Invocation of mattermost-dl failed with status code {retcode}.\nProgram output:\n===\n'; cat {stdout}; printf '===\nProgram error output:\n===\n'; cat {stderr}"
    EXTRA_ARGS=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --help)
                print_help
                exit 0
                ;;
            --cwd)
                if [ $# -eq 1 ]; then
                    echo "Missing argument for '$1'." >&2
                    print_help
                    exit 1
                fi
                cd "$2"
                shift
                ;;
            --conf)
                if [ $# -eq 1 ]; then
                    echo "Missing argument for '$1'." >&2
                    print_help
                    exit 1
                fi
                CONFIG_PATH="$2"
                shift
                ;;
            --handler)
                if [ $# -eq 1 ]; then
                    echo "Missing argument for '$1'." >&2
                    print_help
                    exit 1
                fi
                ERR_HANDLER="$2"
                shift
                ;;
            --)
                shift
                EXTRA_ARGS="$@"
                return 0
                ;;
            *)
                echo "Unknown argument '$1'." >&2
                print_help
                exit 1
        esac
        shift
    done
}

parse_args "$@"

get_date_str() {
    date --iso-8601=minutes | tr ':' '-'
}

TEMP_STDOUT=$(mktemp)
TEMP_STDERR=$(mktemp)
trap "rm -f '$TEMP_STDOUT' '$TEMP_STDERR'" EXIT

RETCODE=0
if [ -z "$CONFIG_PATH" ]; then
    mattermost-dl --quiet $EXTRA_ARGS >"$TEMP_STDOUT" 2>"$TEMP_STDERR" || RETCODE=$?
else
    mattermost-dl --conf "$CONFIG_PATH" --quiet $EXTRA_ARGS >"$TEMP_STDOUT" 2>"$TEMP_STDERR" || RETCODE=$?
fi

if [ $RETCODE -gt 0 -o $(stat --printf="%s" "$TEMP_STDERR") -gt 0 ]; then
    eval $(echo "$ERR_HANDLER" \
        | sed s/{date}/"$(get_date_str)"/ \
        | sed s/{retcode}/"$RETCODE"/ \
        | sed 's|{stdout}|'"$TEMP_STDOUT"'|' \
        | sed 's|{stderr}|'"$TEMP_STDERR"'|' \
    )
fi

exit $RETCODE
