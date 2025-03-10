# Volund's AioMudTelnet library for Python

## CONTACT INFO
**Name:** Volund

**Email:** volundmush@gmail.com

**PayPal:** volundmush@gmail.com

**Discord:** VolundMush

**Discord Channel:** https://discord.gg/Sxuz3QNU8U

**Patreon:** https://www.patreon.com/volund

**Home Repository:** https://github.com/volundmush/mudtelnet

## TERMS AND CONDITIONS

MIT license. In short: go nuts, but give credit where credit is due.

Please see the included LICENSE.txt for the legalese.

## INTRO
MUD (Multi-User Dungeon) games and their brethren like MUSH, MUX, MUCK, and MOO (look 'em up!) utilize a peculiar subset of telnet. At least, SOME do - there are servers and clients which don't bother with telnet negotiation. But, for those that do, the telnet features largely begin and end with using IAC WILL/WONT/DO/DONT Negotiation and IAC SB <option> <data> IAC SE to send arbitrary data. In a way, MUD Telnet has diverged to become its own dialect. Library support for MUD-specific features like MSSP, GMCP, MTTS, and MCCP2 can be hard to come by. This library attempts to provide a one-stop-shop for handling MUD Telnet.

This library isn't a MUD. It doesn't open any ports or send data. It's simply a tool for taking the bytes a program would receive from a client and turning it into a series of 'events' that user-given application logic can then utilize, and a way to encode 'outgoing events' into bytes to be sent back to a client.

## FEATURES
  * Asyncio-Centric: Designed to be used with asyncio. It is fully asynchronous.
  * Loosely Coupled: The library is designed to be easily integrated into other projects. It uses async callbacks to notify the parent application of events. It's easy to use in a simple TaskGroup managing a StreamReader and StreamWriter.

## TELNET OPTION FEATURES
  * MCCP2 and MCCP3 (Mud Client Compression Protocol, incoming and outgoing)
  * MTTS (Mud Terminal Type Standard, aka TTYPE)
  * NAWS (Negotiate About Window Size)
  * MSSP (Mud Server Status Protocol)
  * GMCP (Generic Mud Communication Protocol)
  * CHARSET (Negotiate and set client encoding)

## COMING SOON?
  * MNES (Mud New-Environ Standard)

## NOT HAPPENING!
  * Pueblo/MXP (Mud eXtension Protocol) - Although it's technically impressive, I do not think modifying the in-band data stream to be a bastardized subset of HTML is a good idea. It causes more problems than it solves, sorry.

## OKAY, BUT HOW DO I USE IT?
Glad you asked.


```python
import asyncio
import typing
from aiomudtelnet import MudTelnetProtocol, MudClientCapabilities
from aiomudtelnet.options import ALL_OPTIONS

class TelnetConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.client_capabilities = MudClientCapabilities()
        self.telnet = MudTelnetProtocol(capabilities=self.client_capabilities, supported_options=ALL_OPTIONS)
        self.reader = reader
        self.writer = writer
        self.shutdown_cause = None
        self.shutdown_event = asyncio.Event()
        self.task_group = None
        
        self.telnet.callbacks["line"] = self.at_line_received
        self.telnet.callbacks["gmcp"] = self.at_gmcp_received
        self.telnet.callbacks["command"] = self.at_command_received
        self.telnet.callbacks["change_capabilities"] = self.at_change_capabilities

    async def at_line_received(self, line: str):
        # A line. Probably a text command. the newline at the end is already stripped.
        print(f"Received line: {line}")
    
    async def at_command_received(self, command: int):
        # an IAC command like IAC NOP. These traditionally have little use in MUD operations
        # but IAC NOP is a good way to keep a connection alive.
        print(f"Received a command: {command}")
    
    async def at_gmcp_received(self, command: str, data: dict):
        # GMCP data.
        print(f"received GMCP: {command} - {data}")
    
    async def at_change_capabilities(self, capability: str, new_value: typing.Any):
        print(f"Received a change in capabilities: {capability} - {new_value}")
    
    async def run_reader(self):
        try:
            while True:
                data = await self.reader.read(1024)
                if not data:
                  self.shutdown_cause = "reader_eof"
                  self.shutdown_event.set()
                  return
                await self.telnet.receive_data(data)
        except asyncio.CancelledError:
            return

    async def run_writer(self):
        try:
            async for data in self.telnet.output_stream():
                await self.writer.write(data)
                await self.writer.drain()
        except asyncio.CancelledError:
            return
    
    async def run_negotiator(self):
        ops = await self.telnet.start()

        try:
            await asyncio.wait_for(asyncio.gather(*ops), 0.5)
        except asyncio.TimeoutError as err:
            pass
        
        await self.run_game()
    
    async def run_game(self):
        # Display welcome screen, register connection, etc.
        pass
        
    async def run(self):
        async with asyncio.TaskGroup() as tg:
            self.task_group = tg
            tg.create_task(self.run_reader())
            tg.create_task(self.run_writer())
            tg.create_task(self.run_negotiator())

            await self.shutdown_event.wait()
            raise asyncio.CancelledError()
```

## FAQ 
  __Q:__ This is cool! How can I help?  
  __A:__ [Patreon](https://www.patreon.com/volund) support is always welcome. If you can code and have cool ideas or bug fixes, feel free to fork, edit, and pull request! Join our [discord](https://discord.gg/Sxuz3QNU8U) to really get cranking away though.

  __Q:__ I found a bug! What do I do?  
  __A:__ Post it on this GitHub's Issues tracker. I'll see what I can do when I have time. ... or you can try to fix it yourself and submit a Pull Request. That's cool too.

  __Q:__ But... I want a MUD! Where do I start making a MUD?  
  __A:__ Coming soon...

  __Q:__ Any other libraries I should look into for making a MUD?  
  __A:__ [Evennia](https://www.evennia.com/) is a full-fledged MUD SDK in python. If it suits your needs, I recommend using it instead of starting from scratch. If you ARE starting from scratch, then [Rich](https://github.com/Textualize/rich) offers some amazing ANSI coloring support that works well with aiomudtelnet. Just give each connection a rich.Console.Console, use its record feature, alter color systems and other things by responding to capability changes, and then send the recorded output to the client.

## Special Thanks
  * The [Evennia](https://www.evennia.com/) community. I've learned a lot from their code.
  * The [BeipMU](https://beipdev.github.io/BeipMU/) project. Their client has been amazing for testing this library.
  * The TinTin++ community. Their archive on [MUD protocols](https://tintin.mudhalla.net/protocols/) is n absolute godsend and a treasure.
  * All of my Patrons on Patreon.
  * Anyone who contributes to this project or my other ones.