import zlib
import asyncio
from dataclasses import dataclass, field
from .parser import TelnetCode, TelnetNegotiate, TelnetSubNegotiate, TelnetData, TelnetCommand

@dataclass(slots=True)
class TelnetOptionState:
    enabled: bool = False
    negotiating: bool = False


@dataclass(slots=True)
class TelnetOptionPerspective:
    local: TelnetOptionState = field(default_factory=TelnetOptionState)
    remote: TelnetOptionState = field(default_factory=TelnetOptionState)


class TelnetOption:
    code: TelnetCode = TelnetCode.NULL
    support_local: bool = False
    support_remote: bool = False
    start_local: bool = False
    start_remote: bool = False

    __slots__ = ("protocol", "status", "negotiation")

    def __init__(self, protocol):
        self.protocol = protocol
        self.status = TelnetOptionPerspective()
        self.negotiation = asyncio.Event()

    async def send_subnegotiate(self, data: bytes):
        msg = TelnetSubNegotiate(self.code, data)
        await self.protocol._tn_out_queue.put(msg)

    async def send_negotiate(self, command: TelnetCode):
        msg = TelnetNegotiate(command, self.code)
        await self.protocol._tn_out_queue.put(msg)

    async def start(self):
        if self.start_local:
            await self.send_negotiate(TelnetCode.WILL)
            self.status.local.negotiating = True
        if self.start_remote:
            await self.send_negotiate(TelnetCode.DO)
            self.status.remote.negotiating = True

    async def at_send_negotiate(self, msg: TelnetNegotiate):
        pass

    async def at_send_subnegotiate(self, msg: TelnetSubNegotiate):
        pass

    async def at_receive_negotiate(self, msg: TelnetNegotiate):
        match msg.command:
            case TelnetCode.WILL:
                if self.support_remote:
                    state = self.status.remote
                    if not state.enabled:
                        state.enabled = True
                        if not state.negotiating:
                            await self.send_negotiate(TelnetCode.DO)
                        await self.at_remote_enable()
                else:
                    await self.send_negotiate(TelnetCode.DONT)
            case TelnetCode.DO:
                if self.support_local:
                    state = self.status.local
                    if not state.enabled:
                        state.enabled = True
                        if not state.negotiating:
                            await self.send_negotiate(TelnetCode.WILL)
                        await self.at_local_enable()
                else:
                    await self.send_negotiate(TelnetCode.DONT)
            case TelnetCode.WONT:
                if self.support_remote:
                    state = self.status.remote
                    if state.enabled:
                        state.enabled = False
                        await self.at_remote_disable()
                    if state.negotiating:
                        state.negotiating = False
                        await self.at_remote_reject()
            case TelnetCode.DONT:
                if self.support_local:
                    state = self.status.local
                    if state.enabled:
                        state.enabled = False
                        await self.at_local_disable()
                    if state.negotiating:
                        state.negotiating = False
                        await self.at_local_reject()

    async def at_local_reject(self):
        self.negotiation.set()

    async def at_remote_reject(self):
        self.negotiation.set()

    async def at_receive_subnegotiate(self, msg: TelnetSubNegotiate):
        pass

    async def at_local_enable(self):
        self.negotiation.set()

    async def at_local_disable(self):
        pass

    async def at_remote_enable(self):
        self.negotiation.set()

    async def at_remote_disable(self):
        pass

    async def transform_outgoing_data(self, data: bytes) -> bytes:
        return data

    async def transform_incoming_data(self, data: bytes) -> bytes:
        return data


class SGAOption(TelnetOption):
    code = TelnetCode.SGA
    support_local = True
    start_local = True


class NAWSOption(TelnetOption):
    code = TelnetCode.NAWS
    support_remote = True
    start_remote = True

    async def at_receive_subnegotiate(self, msg):
        data = msg.data
        if len(data) != 4:
            return
        new_size = {
            "width": int.from_bytes(data[0:2], "big"),
            "height": int.from_bytes(data[2:4], "big"),
        }
        await self.protocol.change_capabilities(new_size)

    async def at_remote_enable(self):
        await self.protocol.change_capabilities({"naws": True})
        self.negotiation.set()


class CHARSETOption(TelnetOption):
    code = TelnetCode.CHARSET
    support_local = True
    support_remote = True
    start_local = True
    start_remote = True

    __slots__ = ("enabled",)

    def __init__(self, protocol):
        super().__init__(protocol)
        self.enabled = None

    async def at_receive_subnegotiate(self, msg):
        if len(msg.data) < 2:
            return
        if msg.data[0] == 0x02:
            encoding = msg.data[1:].decode()
            await self.protocol.change_capabilities({"encoding": encoding})
            self.negotiation.set()

    async def request_charset(self):
        data = bytearray()
        data.append(0x01)  # REQUEST
        data.extend(b" ascii utf-8")

        await self.send_subnegotiate(data)

    async def at_remote_enable(self):
        if not self.enabled:
            self.enabled = "remote"
            await self.request_charset()

    async def at_local_enable(self):
        if not self.enabled:
            self.enabled = "local"
            await self.request_charset()


class MTTSOption(TelnetOption):
    code = TelnetCode.MTTS
    support_remote = True
    start_remote = True

    MTTS = [
        (2048, "encryption"),
        (1024, "mslp"),
        (512, "mnes"),
        (256, "truecolor"),
        (128, "proxy"),
        (64, "screenreader"),
        (32, "osc_color_palette"),
        (16, "mouse_tracking"),
        (8, "xterm256"),
        (4, "utf8"),
        (2, "vt100"),
        (1, "ansi"),
    ]

    __slots__ = ("number_requests", "last_received")

    def __init__(self, protocol):
        super().__init__(protocol)
        self.number_requests = 0
        self.last_received = ""

    async def at_remote_enable(self):
        await self.protocol.change_capabilities({"mtts": True})
        await self.request()

    async def request(self):
        self.number_requests += 1
        await self.send_subnegotiate(bytes([1]))

    async def at_receive_subnegotiate(self, msg):
        data = msg.data
        if not len(data):
            return
        if data[0] != 0:
            return
        payload = data[1:].decode()

        if payload == self.last_received:
            self.negotiation.set()
            return

        match self.number_requests:
            case 1:
                await self.handle_name(payload)
                await self.request()
            case 2:
                await self.handle_ttype(payload)
                await self.request()
            case 3:
                await self.handle_standard(payload)
                self.negotiation.set()

    async def handle_name(self, data: str):
        out = dict()
        if " " in data:
            client_name, client_version = data.split(" ", 1)
        else:
            client_name = data
            client_version = None
        out["client_name"] = client_name
        if client_version:
            out["client_version"] = client_version

        # Anything which supports MTTS definitely supports basic ANSI.
        max_color = 1

        match client_name.upper():
            case (
            "ATLANTIS"
            | "CMUD"
            | "KILDCLIENT"
            | "MUDLET"
            | "MUSHCLIENT"
            | "PUTTY"
            # | "BEIP"
            | "POTATO"
            | "TINYFUGUE"
            ):
                max_color = max(max_color, 2)
            case "BEIP":
                max_color = max(max_color, 3)
            case "MUDLET":
                if client_version is not None and client_version.startswith("1.1"):
                    max_color = max(max_color, 2)

        if max_color != self.protocol.capabilities.color:
            out["color"] = max_color
        await self.protocol.change_capabilities(out)

    async def handle_ttype(self, data: str):
        if "-" in data:
            first, second = data.split("-", 1)
        else:
            first = data
            second = ""

        max_color = self.protocol.capabilities.color

        if max_color < 2:
            if (
                    first.endswith("-256COLOR")
                    or first.endswith("XTERM")  # Apple Terminal, old Tintin
                    and not first.endswith("-COLOR")  # old Tintin, Putty
            ):
                max_color = 2

        out = dict()

        match first.upper():
            case "DUMB":
                pass
            case "ANSI":
                pass
            case "VT100":
                out["vt100"] = True
            case "XTERM":
                max_color = max(max_color, 2)

        if max_color != self.protocol.capabilities.color:
            out["color"] = max_color

        if out:
            await self.protocol.change_capabilities(out)

    async def handle_standard(self, data: str):
        if not data.startswith("MTTS "):
            return
        mtts, num = data.split(" ", 1)

        number = 0
        try:
            number = int(num)
        except ValueError as err:
            return

        supported = {
            capability for bitval, capability in self.MTTS if number & bitval > 0
        }

        out = dict()
        max_color = self.protocol.capabilities.color

        for c in supported:
            match c:
                case (
                "encryption"
                | "mslp"
                | "mnes"
                | "proxy"
                | "vt100"
                | "screenreader"
                | "osc_color_palette"
                | "mouse_tracking"
                ):
                    out[c] = True
                case "truecolor":
                    max_color = max(3, max_color)
                case "xterm256":
                    max_color = max(2, max_color)
                case "ansi":
                    max_color = max(1, max_color)
                case "utf8":
                    out["encoding"] = "utf-8"

        if max_color != self.protocol.capabilities.color:
            out["color"] = max_color

        await self.protocol.change_capabilities(out)


class MSSPOption(TelnetOption):
    code = TelnetCode.MSSP
    support_local = True
    start_local = True

    async def at_local_enable(self):
        self.negotiation.set()
        await self.protocol.change_capabilities({"mssp": True})

    async def send_mssp(self, data: dict[str, str]):
        if not data:
            return

        out = bytearray()
        for k, v in data.items():
            out.append(1)
            out.extend(k.encode())
            out.append(2)
            out.extend(v.encode())

        await self.send_subnegotiate(out)


class MCCP2Option(TelnetOption):
    code: TelnetCode = TelnetCode.MCCP2
    support_local: bool = True
    start_local: bool = True

    def __init__(self, protocol):
        super().__init__(protocol)
        self.compressor = None

    async def at_send_subnegotiate(self, msg):
        if not self.protocol.capabilities.mccp2_enabled:
            await self.protocol.change_capabilities({"mccp2_enabled": True})
            self.protocol._out_transformers.append(self)
            self.compressor = zlib.compressobj(9)

    async def at_local_enable(self):
        await self.protocol.change_capabilities({"mccp2": True})
        self.negotiation.set()
        await self.send_subnegotiate(b"")

    async def transform_outgoing_data(self, data):
        if self.compressor:
            return self.compressor.compress(
                bytes(data)
            ) + self.compressor.flush(zlib.Z_SYNC_FLUSH)
        else:
            return data


class MCCP3Option(TelnetOption):
    code: TelnetCode = TelnetCode.MCCP3
    support_local: bool = True
    start_local: bool = True

    def __init__(self, protocol):
        super().__init__(protocol)
        self.decompressor = None

    async def at_receive_subnegotiate(self, msg):
        if not self.protocol.capabilities.mccp3_enabled:
            await self.protocol.change_capabilities({"mccp3_enabled": True})
            self.protocol._in_transformers.append(self)
            self.decompressor = zlib.decompressobj()

            # everything in the buffer after this message must be
            # decompressed. We'll do this now.
            try:
                self.protocol._tn_read_buffer = bytearray(
                    self.decompressor.decompress(self.protocol._tn_in_buffer)
                )
            except zlib.error as e:
                pass  # todo: handle this

    async def transform_incoming_data(self, data):
        if self.decompressor:
            return self.decompressor.decompress(data)
        else:
            return data

    async def at_decompress_end(self):
        """
        If the compression ends, we must immediately disable MCCP3.
        """
        self.decompressor = None
        await self.protocol.change_capabilities({"mccp3_enabled": False})

    async def at_decompress_error(self):
        self.decompressor = None
        await self.protocol.change_capabilities({"mccp3_enabled": False})
        await self.send_negotiate(TelnetCode.WONT)

    async def at_local_enable(self):
        await self.protocol.change_capabilities({"mccp3": True})
        self.negotiation.set()


class GMCPOption(TelnetOption):
    code: TelnetCode = TelnetCode.GMCP
    support_local: bool = True
    start_local: bool = True

    async def send_gmcp(self, command: str, data: "Any" = None):
        to_send = bytearray()
        to_send.extend(command.encode())
        if data is not None:
            gmcp_data = f" {self.protocol.json_library.dumps(data)}"
            to_send.extend(gmcp_data.encode())
        await self.send_subnegotiate(to_send)

    async def at_receive_subnegotiate(self, msg: TelnetSubNegotiate):
        data = msg.data.decode()
        if " " in data:
            command, json_data = data.split(" ", 1)
        else:
            command = data
            json_data = None
        try:
            data = self.protocol.json_library.loads(json_data)
        except (self.protocol.json_library.JSONDecodeError, TypeError):
            data = None
        if cb := self.protocol.callbacks.get("gmcp", None):
            await cb(command, data)


class LineModeOption(TelnetOption):
    code: TelnetCode = TelnetCode.LINEMODE
    support_local: bool = True
    start_local: bool = True


class EOROption(TelnetOption):
    code = TelnetCode.TELOPT_EOR

ALL_OPTIONS = [SGAOption, NAWSOption, CHARSETOption, MTTSOption, MSSPOption, MCCP2Option, MCCP3Option,
               GMCPOption, LineModeOption, EOROption]