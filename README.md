# aikta

irc bot for me

## things it does

1. .np - last.fm (now playin)
2. .wp - last.fm for the channel (we playin)
3. !ab - archivebot lookup for a domain or link (last job, shallow, subdomains)

## how it stores data

sqlite

## per-channel commands

every command can be enabled/disabled per channel with `.cmd-on <command>` / `.cmd-off <command>` (channel ops, or the `AIKTA_ADMIN` nick). default policy comes from `AIKTA_CMD_DEFAULT` (`on` = all enabled unless disabled per channel, `off` = all disabled unless enabled per channel). toggles persist in sqlite and apply immediately. disabled commands are ignored silently.

## requirements

oci, python 3.13+, uv, asyncio, aiohttp, aiosqlite
