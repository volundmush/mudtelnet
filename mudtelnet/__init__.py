import typing
import asyncio
import traceback
import json

from dataclasses import dataclass, field

from typing import Dict, Tuple, Optional, Union, List
from collections import defaultdict

from .parser import TelnetCode, TelnetCommand, TelnetData, TelnetNegotiate, TelnetSubNegotiate, parse_telnet
from .options import ALL_OPTIONS, TelnetOption
from .utils import ensure_crlf

@dataclass(slots=True)
class MudClientCapabilities:
    """
    A dataclass that holds the capabilities of the client. This is updated as negotiations occur and statuses change.
    It can be subclassed to add more fields as needed, if you need to implement more TelnetOption subtypes that aren't
    covered here.
    """
    client_name: str = "UNKNOWN"
    client_version: str = "UNKNOWN"
    encoding: str = "ascii"
    color: int = 0
    width: int = 78
    height: int = 24
    mccp2: bool = False
    mccp2_enabled: bool = False
    mccp3: bool = False
    mccp3_enabled: bool = False
    gmcp: bool = False
    msdp: bool = False
    mssp: bool = False
    mslp: bool = False
    mtts: bool = False
    naws: bool = False
    sga: bool = False
    linemode: bool = False
    force_endline: bool = False
    screen_reader: bool = False
    mouse_tracking: bool = False
    vt100: bool = False
    osc_color_palette: bool = False
    proxy: bool = False
    mnes: bool = False
    tls_support: bool = False


class MudTelnetProtocol:
    """
    This is the main class for handling Mud Telnet connections. It can be used as-is, or subclassed.
    It's meant to be used with an asyncio. It doesn't provide any networking capabilities itself, however.

    Using it involves primarily the following methods:
    - async def start(self): This should be called first thing after hooking it up to any networking code. It will initiate
        any Telnet Option negotiations and provides a list of asyncio.Events that can be awaited on to determine when the
        negotiations are complete. We recommend a timeout on this, since many clients don't do anything with Telnet Options.
    - async def receive_data(self, data: bytes) -> int: This is the main entry point for incoming data. Just dump all incoming bytes
        into this method, and it will handle the rest.
    - async def send_text(self, text: str): This is the main method for sending text to the client. It will automatically
        convert and encode the text as needed. There are also send_mssp, send_gmcp, and send_line methods.
    - async def output_stream(self): This is an async generator that yields bytes to be sent to the client. It should be used
        in an async for loop. It's the main output mechanism.
    - callbacks: This is a dictionary of callbacks that can be set to handle various events. The keys are "line", "command",
        and "change_capabilities". The values should be async callables that accept the appropriate arguments. Just
        check out how they're called in the code to see what they should look like.

    """

    def __init__(self, capabilities: MudClientCapabilities, supported_options: typing.List[typing.Type[TelnetOption]] = None,
                 logger=None, text_encoding: str = "utf-8", json_library = None):
        """
        Initialize a MudTelnetProtocol instance.

        Args:
            capabilities (MudClientCapabilities): The capabilities of the client. This will be updated as negotiations
                occur and statuses change. To observe these changes, you can set a callback for the "change_capabilities"
                event.
            supported_options (list): A list of TelnetOption classes that the server supports. If this is None, all
                advanced features are disabled. It's recommended to use the ALL_OPTIONS list from the options module.
            logger: The logger object to use for reporting errors.
            text_encoding (str): The encoding to use for text. This is utf-8 by default. We recommend sticking to it.
            json_library: An object which is compatible with json.loads and json.dumps. This is used for GMCP.
                The default Python library will be used if not provided. orjson or similar are recommended.
        """
        self.capabilities = capabilities
        self.logger = logger
        self.text_encoding = text_encoding
        self.supported_options = supported_options or list()
        # Various callbacks with different call signatures will be stored here.
        # set them after initializing with telnet.callbacks["name"] = some_async_callable.
        self.callbacks: Dict[str, typing.Callable[..., typing.Awaitable[typing.Any]]] = {}
        self.json_library = json_library or json
        # Raw bytes come in and are appended to the _tn_in_buffer.
        self._tn_in_buffer = bytearray()
        # Private message queue that holds messages like TelnetData, TelnetCommand, TelnetNegotiate, TelnetSubNegotiate.
        # Used by self.output_stream
        self._tn_out_queue = asyncio.Queue()
        # Holds text data sent by client that has yet to have a line ending.
        self._tn_app_data = bytearray()
        self._tn_options: dict[int, TelnetOption] = {}
        # These are currently only used by MCCP2 and MCCP3. They cause byte transformations/encoding/decoding.
        # It's probably not possible to have too many things mucking with bytes in/out. Really, MCCP2 and MCCP3 are
        # terrible enough to deal with as it is.
        self._out_transformers = list()
        self._in_transformers = list()

        # Initialize all provided Telnet Option handlers.
        for op in self.supported_options:
            self._tn_options[op.code] = op(self)

    async def start(self) -> typing.List[typing.Coroutine[typing.Any, typing.Any, typing.Literal[True]]]:
        """
        Fires off the initial barrage of negotiations and prepares events that signify end of negotiations.

        This is meant to be used by the application via something like
        asyncio.wait_for(asyncio.gather(*ops)),  perhaps with a timeout
        in case a client doesn't respond.
        """
        for code, op in self._tn_options.items():
            await op.start()

        ops = [op.negotiation.wait() for op in self._tn_options.values()]

        return ops

    async def receive_data(self, data: bytes) -> int:
        """
        This is the main entry point for incoming data.
        It will process at most one TelnetMessage from the incoming data.
        Extra bytes are held onto in the _tn_in_buffer until they can be processed.

        It returns the size of the in_buffer in bytes after processing.
        This is useful for determining if the buffer is growing or shrinking too much.
        """
        # Route all bytes through the incoming transformers. This is
        # probably only MCCP3.
        in_data = data
        for op in self._in_transformers:
            in_data = await op.transform_incoming_data(in_data)

        self._tn_in_buffer.extend(data)

        while True:
            # Try to parse a message from the buffer
            consumed, message = parse_telnet(self._tn_in_buffer)
            if message is None:
                break
            # advance the buffer by the number of bytes consumed
            del self._tn_in_buffer[consumed:]
            # Do something with the message.
            # If MCCP3 engages it will actually decompress self._tn_in_buffer in-place
            # so it's safe to keep iterating.
            await self._tn_at_telnet_message(message)

        return len(self._tn_in_buffer)

    async def change_capabilities(self, changes: dict[str, typing.Any]):
        cb = self.callbacks.get("change_capabilities", None)
        for key, value in changes.items():
            setattr(self.capabilities, key, value)
            if cb:
                await cb(key, value)

    async def _tn_at_telnet_message(self, message):
        """
        Responds to data converted from raw data after possible decompression.
        """
        match message:
            case TelnetData():
                await self._tn_handle_data(message)
            case TelnetCommand():
                await self._tn_handle_command(message)
            case TelnetNegotiate():
                await self._tn_handle_negotiate(message)
            case TelnetSubNegotiate():
                await self._tn_handle_subnegotiate(message)

    async def _tn_handle_data(self, message: TelnetData):
        self._tn_app_data.extend(message.data)

        # scan self._app_data for lines ending in \r\n...
        while True:
            # Find the position of the next newline character
            newline_pos = self._tn_app_data.find(b"\n")
            if newline_pos == -1:
                break  # No more newlines

            # Extract the line, trimming \r\n at the end
            line = (
                self._tn_app_data[:newline_pos]
                .rstrip(b"\r\n")
                .decode(self.text_encoding, errors="ignore")
            )

            # Remove the processed line from _app_data
            self._tn_app_data = self._tn_app_data[newline_pos + 1 :]

            # Call the line callback if it exists
            if cb := self.callbacks.get("line", None):
                await cb(line)

    async def _tn_handle_negotiate(self, message: TelnetNegotiate):
        if op := self._tn_options.get(message.option, None):
            await op.at_receive_negotiate(message)
            return

        # but if we don't have any handler for it...
        match message.command:
            case TelnetCode.WILL:
                msg = TelnetNegotiate(TelnetCode.DONT, message.option)
                await self._tn_out_queue.put(msg)
            case TelnetCode.DO:
                msg = TelnetNegotiate(TelnetCode.WONT, message.option)
                await self._tn_out_queue.put(msg)

    async def _tn_handle_subnegotiate(self, message: TelnetSubNegotiate):
        if op := self._tn_options.get(message.option, None):
            await op.at_receive_subnegotiate(message)

    async def _tn_handle_command(self, message: TelnetCommand):
        if cb := self.callbacks.get("command", None):
            await cb(message.command)

    async def _tn_encode_outgoing_data(self, data: typing.Union[TelnetData, TelnetCommand, TelnetNegotiate, TelnetSubNegotiate]) -> bytes:
        # First we'll convert our object to bytes. It might be a TelnetData, TelnetCommand,
        # TelnetNegotiate, or TelnetSubNegotiate.
        encoded = bytes(data)
        # pass it through any applicable transformations. This is probably only MCCP2.
        for op in self._out_transformers:
            encoded = await op.transform_outgoing_data(encoded)
        # return the encoded data.
        return encoded

    async def output_stream(self) -> typing.AsyncGenerator[bytes, None]:
        """
        This is the main output stream generator. It takes data from the _tn_out_queue,
        encodes it as bytes, and yields it the caller. This is meant to be used in an
        async for loop like so:

        async for data in protocol.output_stream():
            await writer.write(data)

        """
        while data := await self._tn_out_queue.get():
            encoded = await self._tn_encode_outgoing_data(data)
            # certain options need to know when things happen. Primarily MCCP2. So we'll notify them
            # of the data that we now know "has been sent to the client".
            match data:
                case TelnetNegotiate():
                    if op := self._tn_options.get(data.option, None):
                        await op.at_send_negotiate(data)
                case TelnetSubNegotiate():
                    if op := self._tn_options.get(data.option, None):
                        await op.at_send_subnegotiate(data)
            yield encoded

    async def send_line(self, text: str):
        if not text.endswith("\n"):
            text += "\n"
        await self.send_text(text)

    async def send_text(self, text: str):
        converted = ensure_crlf(text)
        await self._tn_out_queue.put(TelnetData(data=converted.encode()))

    async def send_gmcp(self, command: str, data=None):
        if self.capabilities.gmcp:
            op = self._tn_options.get(TelnetCode.GMCP)
            await op.send_gmcp(command, data)

    async def send_mssp(self, data: dict[str, str]):
        if self.capabilities.mssp:
            op = self._tn_options.get(TelnetCode.MSSP)
            await op.send_mssp(data)