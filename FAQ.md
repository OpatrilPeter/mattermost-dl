# Frequently asked questions

## Why does download of long channel with certain time constraints take such long time to start?
Current Mattermost API is suited for fetching posts from latest to oldest and only certain constraints can be evaluated serverside.
In certain cases, such as "downloading from oldest, grab 100 posts after certain date.", we must actually process all posts from the channel begginning right until the time condition starts passing.
In general, it's very fast to download posts before or after some explicit post, which makes successive downloads (fetching updates) much faster.
