from ircrobots import Bot as BaseBot, Server as BaseServer, ConnectionParams
from irctokens import build, Line
from aikta.sqlite import Storage
from aikta.settings import SERVER, PORT, NICK, LASTFM_API_KEY, CHANNELS, DATA_DIR, CMD_DEFAULT_ON, ADMIN
from aikta.lastfm import LastFM
import asyncio
import aiohttp
import os
from pathlib import Path

class Server(BaseServer):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.storage = Storage(db=Path(DATA_DIR) / "aikta.db")
        self.lastfm = LastFM(LASTFM_API_KEY, self.storage)

        # Parse multiple extra commands
        self.extra_commands = {}
        extra_config = os.getenv("EXTRA_COMMANDS", "")
        if extra_config:
            for command_spec in extra_config.split(";"):
                parts = command_spec.split(",")
                if len(parts) >= 2:
                    cmd = parts[0].strip().lower()
                    api = parts[1].strip()
                    transform = parts[2].strip() if len(parts) > 2 else ""
                    self.extra_commands[cmd] = {"api": api, "transform": transform}
        self.builtin_commands = {"np", "wp", "v"}

    async def line_read(self, line: Line):
        print(f"{self.name} < {line.format()}")
        match line.command:
            case "001":
                print(f"connected to {self.isupport.network}")
                for channel in CHANNELS:
                    await self.send(build("JOIN", [channel]))
            case "PRIVMSG":
                target, msg = line.params[:2]
                nick = line.source.split("!")[0]
                cmd = msg.split()[0].lower()

                match cmd:
                    case ".cmd-on" | "!cmd-on":
                        await self._handle_cmd_toggle(target, nick, msg, True)
                    case ".cmd-off" | "!cmd-off":
                        await self._handle_cmd_toggle(target, nick, msg, False)
                    case ".np" if await self._cmd_enabled(target, "np"):
                        await self._handle_np(target, nick, msg)
                    case ".wp" if await self._cmd_enabled(target, "wp"):
                        await self._handle_wp(target)
                    case ".v" if await self._cmd_enabled(target, "v"):
                        await self._handle_version(target)
                    case _ if cmd in self.extra_commands and await self._cmd_enabled(target, cmd.lstrip(".!")):
                        await self._handle_extra(target, cmd)
    
    async def _handle_np(self, target, nick, msg):
        args = msg.split()[1:]
        lfm_user = args[0] if args else await self.storage.read(f"lastfm:{nick}")
        if args:
            await self.storage.write(f"lastfm:{nick}", lfm_user)
        if not lfm_user:
            return await self.send(build("PRIVMSG", [target, f"{nick}: set your lastfm: .np username"]))
        data = await self.lastfm.get_now_playing(lfm=lfm_user, nick=nick)
        resp = data["formatted"] if data and data["song"]["artist"] else f"{nick}: No recent track found."
        await self.send(build("PRIVMSG", [target, resp]))
    
    async def _handle_wp(self, target):
        if not (channel := self.channels.get(target)):
            return
        users = list(set([{"id": n, "display_name": n} for n in channel.users]))
        results = await self.lastfm.now_playing_for_users(users)
        for result in results or ["..."]:
            await self.send(build("PRIVMSG", [target, result]))
            await asyncio.sleep(1.0)
    
    async def _handle_version(self, target):
        version_file = Path("/app/.venv/.git_commit")
        version = version_file.read_text().strip() if version_file.exists() else "idk (file not found)"
        await self.send(build("PRIVMSG", [target, version]))
    
    async def _handle_extra(self, target, cmd):
        config = self.extra_commands.get(cmd)
        if not config or not config["api"]:
            return
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(config["api"]) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    
                    if config["transform"]:
                        result = eval(
                            config["transform"],
                            {"__builtins__": {"float": float, "int": int, "str": str}},
                            {"data": data}
                        )
                    else:
                        result = data
                    
                    await self.send(build("PRIVMSG", [target, str(result)]))
        except:
            pass

    def _known_commands(self):
        return self.builtin_commands | set(self.extra_commands)

    async def _cmd_enabled(self, target, cmd):
        # private messages are not per-channel; policy applies to channels only
        if not target.startswith("#"):
            return True
        raw = await self.storage.read(f"cmdchan:{target.lower()}")
        overrides = set(raw.split(",")) if raw else set()
        # overrides hold names that differ from the configured default policy
        return (cmd in overrides) if not CMD_DEFAULT_ON else (cmd not in overrides)

    def _is_op(self, target, nick):
        if ADMIN and nick.lower() == ADMIN.lower():
            return True
        channel = self.channels.get(target)
        user = channel.users.get(self.casefold(nick)) if channel else None
        return bool(user and user.modes & set("oOaq"))

    async def _handle_cmd_toggle(self, target, nick, msg, enable):
        # unauthorized or private-message toggles are ignored silently
        if not target.startswith("#") or not self._is_op(target, nick):
            return
        args = msg.split()[1:]
        name = args[0].lstrip(".!").lower() if args else ""
        if name not in self._known_commands():
            return await self.send(build("PRIVMSG", [target, f"{nick}: unknown command: {name or '(none)'}"]))
        key = f"cmdchan:{target.lower()}"
        raw = await self.storage.read(key)
        overrides = set(raw.split(",")) if raw else set()
        if enable != CMD_DEFAULT_ON:
            overrides.add(name)
        else:
            overrides.discard(name)
        if overrides:
            await self.storage.write(key, ",".join(sorted(overrides)))
        else:
            await self.storage.delete(key)
        resp = f"{nick}: {name} {'enabled' if enable else 'disabled'} in {target}"
        await self.send(build("PRIVMSG", [target, resp]))

    async def line_send(self, line: Line):
        print(f"{self.name} > {line.format()}")

class Bot(BaseBot):
    def create_server(self, name: str) -> Server:
        return Server(self, name)

async def _main():
    bot = Bot()
    await bot.add_server('default', ConnectionParams(NICK, SERVER, PORT))
    await bot.run()

def main():
    """Synchronous entry point for CLI script"""
    asyncio.run(_main())

if __name__ == "__main__":
    main()
