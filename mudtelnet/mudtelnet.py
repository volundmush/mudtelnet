import zlib
from typing import Dict, Tuple, Optional, Union, List
from enum import IntEnum
from collections import defaultdict


class TC(IntEnum):
    NULL = 0
    BEL = 7
    CR = 13
    LF = 10
    SGA = 3
    TELOPT_EOR = 25
    NAWS = 31
    LINEMODE = 34
    EOR = 239
    SE = 240
    NOP = 241
    GA = 249
    SB = 250
    WILL = 251
    WONT = 252
    DO = 253
    DONT = 254
    IAC = 255

    # MNES: Mud New-Environ Standard
    MNES = 39

    # MXP: Mud eXtension Protocol
    MXP = 91

    # MSSP: Mud Server Status Protocol
    MSSP = 70

    # MCCP - Mud Client Compression Protocol
    MCCP2 = 86
    MCCP3 = 87

    # GMCP: Generic Mud Communication Protocol
    GMCP = 201

    # MSDP: Mud Server Data Protocol
    MSDP = 69

    # TTYPE - Terminal Type
    MTTS = 24

    @classmethod
    def from_int(cls, code: int) -> Union["TC", int]:
        try:
            return cls(code)
        except ValueError:
            return code

    def __repr__(self):
        return self.name


NEGOTIATORS = (TC.WILL, TC.WONT, TC.DO, TC.DONT)
ACK_OPPOSITES = {TC.WILL: TC.DO, TC.DO: TC.WILL}
NEG_OPPOSITES = {TC.WILL: TC.DONT, TC.DO: TC.WONT}


class TelnetInMessageType(IntEnum):
    LINE = 0
    DATA = 1
    CMD = 2
    GMCP = 3
    MSSP = 4


class TelnetInMessage:
    __slots__ = ['msg_type', 'data']

    def __init__(self, msg_type: TelnetInMessageType, data):
        self.msg_type = msg_type
        self.data = data


class TelnetOutMessageType(IntEnum):
    LINE = 0
    TEXT = 1
    BYTES = 2
    MSSP = 3
    GMCP = 4
    PROMPT = 5
    COMMAND = 6


class TelnetOutMessage:
    __slots__ = ['msg_type', 'data']

    def __init__(self, msg_type: TelnetOutMessageType, data):
        self.msg_type = msg_type
        self.data = data


class _InternalMsg:
    __slots__ = ['protocol', 'out_buffer', 'out_events', 'changed']

    def __init__(self, protocol, out_buffer: bytearray, out_events: List[TelnetInMessage]):
        self.protocol = protocol
        self.out_buffer: bytearray = out_buffer
        self.out_events: List[TelnetInMessage] = out_events
        self.changed: Dict = defaultdict(dict)


class TelnetFrameType(IntEnum):
    DATA = 0
    NEGOTIATION = 1
    SUBNEGOTIATION = 2
    COMMAND = 3


class TelnetFrame:
    __slots__ = ['msg_type', 'data']

    def __init__(self, msg_type: TelnetFrameType, data):
        self.msg_type = msg_type
        self.data = data

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.msg_type.name} - {self.data}>"

    @classmethod
    def parse(cls, buffer: Union[bytes, bytearray]) -> Tuple[Optional["TelnetFrame"], int]:
        if not len(buffer) > 0:
            return None, 0
        if buffer[0] == TC.IAC:
            if len(buffer) < 2:
                # not enough bytes available to do anything.
                return None, 0
            else:
                if buffer[1] == TC.IAC:
                    return cls(TelnetFrameType.DATA, TC.IAC), 2
                elif buffer[1] in NEGOTIATORS:
                    if len(buffer) > 2:
                        option = TC.from_int(buffer[2])
                        return cls(TelnetFrameType.NEGOTIATION, (TC(buffer[1]), option)), 3
                    else:
                        # it's a negotiation, but we need more.
                        return None, 0
                elif buffer[1] == TC.SB:
                    if len(buffer) >= 5:
                        match = bytearray()
                        match.append(TC.IAC)
                        match.append(TC.SE)
                        idx = buffer.find(match)
                        if idx == -1:
                            return None, 0
                        # hooray, idx is the beginning of our ending IAC SE!
                        option = TC.from_int(buffer[2])
                        data = buffer[3:idx]
                        return cls(TelnetFrameType.SUBNEGOTIATION, (option, data)), 5 + len(data)
                    else:
                        # it's a subnegotiate, but we need more.
                        return None, 0
                else:
                    option = TC.from_int(buffer[1])
                    return cls(TelnetFrameType.COMMAND, option), 2
        else:
            # we are dealing with 'just data!'
            idx = buffer.find(TC.IAC)
            if idx == -1:
                # no idx. consume entire remaining buffer.
                return cls(TelnetFrameType.DATA, bytes(buffer)), len(buffer)
            else:
                # There is an IAC ahead - consume up to it, and loop.
                data = buffer[:idx]
                return cls(TelnetFrameType.DATA, data), len(data)

    @classmethod
    def parse_consume(cls, buffer: bytearray) -> Optional["TelnetFrame"]:
        frame, size = cls.parse(buffer)
        if frame:
            del buffer[:size]
            return frame
        return None


class TelnetOptionPerspective:
    
    __slots__ = ['enabled', 'negotiating', 'heard_answer', 'asked']

    def __init__(self):
        self.enabled = False
        self.negotiating = False
        self.heard_answer = False
        self.asked = False


class TelnetHandshakeHolder:
    
    __slots__ = ['local', 'remote', 'special']

    def __init__(self,):
        self.local = set()
        self.remote = set()
        self.special = set()

    def has_remaining(self):
        return self.local or self.remote or self.special


class TelnetOptionHandler:
    opcode = 0
    opname = None
    support_local = False
    support_remote = False
    start_will = False
    start_do = False
    hs_local = []
    hs_remote = []
    hs_special = []

    __slots__ = ['local', 'remote']

    def __init__(self):
        self.local = TelnetOptionPerspective()
        self.remote = TelnetOptionPerspective()

    def subnegotiate(self, data: bytes, imsg: _InternalMsg):
        pass

    def negotiate(self, cmd: int, imsg: _InternalMsg):
        if cmd == TC.WILL:
            if self.support_remote:
                if self.remote.negotiating:
                    self.remote.negotiating = False
                    if not self.remote.enabled:
                        self.remote.enabled = True
                        imsg.protocol.send_negotiate(TC.DO, self.opcode, imsg)
                        imsg.changed['remote'][self.opname] = True
                        self.enable_remote(imsg)
                        if self.opcode in imsg.protocol.handshakes.remote:
                            imsg.protocol.handshakes.remote.remove(self.opcode)
                else:
                    self.remote.enabled = True
                    imsg.protocol.send_negotiate(TC.DO, self.opcode, imsg)
                    imsg.changed['remote'][self.opname] = True
                    self.enable_remote(imsg)
                    if self.opcode in imsg.protocol.handshakes.remote:
                        imsg.protocol.handshakes.remote.remove(self.opcode)
            else:
                imsg.protocol.send_negotiate(TC.DONT, self.opcode)

        elif cmd == TC.DO:
            if self.support_local:
                if self.local.negotiating:
                    self.local.negotiating = False
                    if not self.local.enabled:
                        self.local.enabled = True
                        imsg.protocol.send_negotiate(TC.WILL, self.opcode, imsg)
                        imsg.changed['local'][self.opname] = True
                        self.enable_local(imsg)
                        if self.opcode in imsg.protocol.handshakes.local:
                            imsg.protocol.handshakes.local.remove(self.opcode)
                else:
                    self.local.enabled = True
                    imsg.protocol.send_negotiate(TC.WILL, self.opcode, imsg)
                    imsg.changed['local'][self.opname] = True
                    self.enable_local(imsg)
                    if self.opcode in imsg.protocol.handshakes.local:
                        imsg.protocol.handshakes.local.remove(self.opcode)
            else:
                imsg.protocol.send_negotiate(TC.DONT, self.opcode)

        elif cmd == TC.WONT:
            if self.remote.enabled:
                imsg.changed['remote'][self.opname] = False
                self.disable_remote(imsg)
                if self.remote.negotiating:
                    self.remote.negotiating = False
                    if self.opcode in imsg.protocol.handshakes.remote:
                        imsg.protocol.handshakes.remote.remove(self.opcode)

        elif cmd == TC.DONT:
            if self.local.enabled:
                imsg.changed['local'][self.opname] = False
                self.disable_local(imsg)
                if self.local.negotiating:
                    self.local.negotiating = False
                    if self.opcode in imsg.protocol.handshakes.local:
                        imsg.protocol.handshakes.local.remove(self.opcode)

    def enable_local(self, imsg: _InternalMsg):
        pass

    def disable_local(self, imsg: _InternalMsg):
        pass

    def enable_remote(self, imsg: _InternalMsg):
        pass

    def disable_remote(self, imsg: _InternalMsg):
        pass


class MCCP2Handler(TelnetOptionHandler):
    opcode = TC.MCCP2
    opname = 'mccp2'
    support_local = True
    start_will = True
    hs_local = [opcode]

    def enable_local(self, imsg: _InternalMsg):
        imsg.changed['mccp2']['active'] = True
        imsg.protocol.send_subnegotiate(self.opcode, [], imsg)
        imsg.protocol.out_compressor = zlib.compressobj(9)

    def disable_local(self, imsg: _InternalMsg):
        imsg.changed['mccp2']['active'] = False
        imsg.protocol.out_compressor = None


class MTTSHandler(TelnetOptionHandler):
    opcode = TC.MTTS
    opname = 'mtts'
    support_remote = True
    start_do = True
    hs_remote = [opcode]
    hs_special = [0, 1, 2]
    # terminal capabilities and their codes
    mtts = [
        (128, "proxy"),
        (64, "screen_reader"),
        (32, "osc_color_palette"),
        (16, "mouse_tracking"),
        (8, "xterm256"),
        (4, "utf8"),
        (2, "vt100"),
        (1, "ansi"),
    ]

    __slots__ = ['stage', 'previous']

    def __init__(self):
        super().__init__()
        self.stage: int = 0
        self.previous: Optional[bytes] = None

    def request(self, imsg: _InternalMsg):
        imsg.protocol.send_subnegotiate(self.opcode, [1], imsg)

    def enable_remote(self, imsg: _InternalMsg):
        imsg.protocol.handshakes.special.update(self.hs_special)
        self.request(imsg)

    def subnegotiate(self, data: bytes, imsg: _InternalMsg):
        if data == self.previous:
            # we're not going to learn anything new from this client...
            for code in self.hs_special:
                if code in imsg.protocol.handshakes.special:
                    imsg.protocol.handshakes.special.remove(code)
            self.previous = None

        if data[0] == 0:
            self.previous = data
            data = data[1:]
            data = data.decode(errors='ignore')
            if not data:
                return

            if self.stage == 0:
                self.receive_stage_0(data, imsg)
                self.stage = 1
                self.request(imsg)
            elif self.stage == 1:
                self.receive_stage_1(data, imsg)
                self.stage = 2
            elif self.stage == 2:
                self.receive_stage_2(data, imsg)
                self.stage = 3

    def receive_stage_0(self, data: str, imsg: _InternalMsg):
        # Code adapted from Evennia! Credit where credit is due.

        # this is supposed to be the name of the client/terminal.
        # For clients not supporting the extended TTYPE
        # definition, subsequent calls will just repeat-return this.
        clientname = data.upper()

        if ' ' in clientname:
            clientname, version = clientname.split(' ', 1)
        else:
            version = 'UNKNOWN'
        imsg.changed['mtts']['client_name'] = clientname
        imsg.changed['mtts']['client_version'] = version

        # use name to identify support for xterm256. Many of these
        # only support after a certain version, but all support
        # it since at least 4 years. We assume recent client here for now.
        xterm256 = False
        if clientname.startswith("MUDLET"):
            # supports xterm256 stably since 1.1 (2010?)
            xterm256 = version >= "1.1"
            imsg.changed['mtts']['force_endline'] = False

        if clientname.startswith("TINTIN++"):
            imsg.changed['mtts']['force_endline'] = True

        if (
                clientname.startswith("XTERM")
                or clientname.endswith("-256COLOR")
                or clientname
                in (
                "ATLANTIS",  # > 0.9.9.0 (aug 2009)
                "CMUD",  # > 3.04 (mar 2009)
                "KILDCLIENT",  # > 2.2.0 (sep 2005)
                "MUDLET",  # > beta 15 (sep 2009)
                "MUSHCLIENT",  # > 4.02 (apr 2007)
                "PUTTY",  # > 0.58 (apr 2005)
                "BEIP",  # > 2.00.206 (late 2009) (BeipMu)
                "POTATO",  # > 2.00 (maybe earlier)
                "TINYFUGUE",  # > 4.x (maybe earlier)
        )
        ):
            xterm256 = True

        # all clients supporting TTYPE at all seem to support ANSI
        if xterm256:
            imsg.changed['mtts']['xterm256'] = True
            imsg.changed['mtts']['ansi'] = True

    def receive_stage_1(self, term: str, imsg: _InternalMsg):
        # this is a term capabilities flag
        tupper = term.upper()
        # identify xterm256 based on flag
        xterm256 = (
                tupper.endswith("-256COLOR")
                or tupper.endswith("XTERM")  # Apple Terminal, old Tintin
                and not tupper.endswith("-COLOR")  # old Tintin, Putty
        )
        if xterm256:
            imsg.changed['mtts']['xterm256'] = True
        imsg.changed['mtts']['ttype'] = term

    def receive_stage_2(self, option: str, imsg: _InternalMsg):
        # the MTTS bitstring identifying term capabilities
        if option.startswith("MTTS"):
            option = option[4:].strip()
            if option.isdigit():
                # a number - determine the actual capabilities
                option = int(option)
                for k, v in {capability: True for bitval, capability in self.mtts if option & bitval > 0}:
                    imsg.changed['mtts'][k] = v
            else:
                # some clients send erroneous MTTS as a string. Add directly.
                imsg.changed['mttts']['mtts'] = True
        imsg.changed['mtts']['ttype'] = True


class MNEShandler(TelnetOptionHandler):
    """
    Not ready. do not enable.
    """
    opcode = TC.MNES
    opname = 'mnes'
    start_do = True
    support_remote = True
    hs_remote = [opcode]


class MCCP3Handler(TelnetOptionHandler):
    """
    Note: Disabled because I can't get this working in tintin++
    It works, but not in conjunction with MCCP2.
    """
    opcode = TC.MCCP3
    opname = 'mccp3'
    support_local = True
    start_will = True
    hs_local = [opcode]


class NAWSHandler(TelnetOptionHandler):
    opcode = TC.NAWS
    opname = 'naws'
    support_remote = True
    start_do = True

    def enable_remote(self, imsg: _InternalMsg):
        imsg.changed['remote']['naws'] = True

    def subnegotiate(self, data: bytes, imsg: _InternalMsg):
        if len(data) >= 4:
            # NAWS is negotiated with 16bit words
            imsg.changed['naws']['width'] = int.from_bytes(data[0:2], byteorder="big", signed=False)
            imsg.changed['naws']['height'] = int.from_bytes(data[2:2], byteorder="big", signed=False)


class SGAHandler(TelnetOptionHandler):
    opcode = TC.SGA
    opname = 'suppress_ga'
    start_will = True
    support_local = True

    def enable_local(self, imsg: _InternalMsg):
        imsg.protocol.sga = True

    def disable_local(self, imsg: _InternalMsg):
        imsg.protocol.sga = False


class LinemodeHandler(TelnetOptionHandler):
    opcode = TC.LINEMODE
    opname = 'linemode'
    start_do = True
    support_remote = True


class MSSPHandler(TelnetOptionHandler):
    opcode = TC.MSSP
    opname = 'mssp'
    start_will = True
    support_local = True

    def send(self, data: Dict[str, str], imsg: _InternalMsg):
        out = bytearray()
        for k, v in data.items():
            out += 1
            out += bytes(k)
            out += 2
            out += bytes(v)
        imsg.protocol.send_subnegotiate(self.opcode, out, imsg)


class TelnetConnection:
    handler_classes = [MCCP2Handler, MTTSHandler, NAWSHandler, SGAHandler, LinemodeHandler, MSSPHandler]

    __slots__ = ['cmdbuff', 'handlers', 'out_compressor', 'handshakes', 'app_linemode', 'sga']

    def __init__(self, app_linemode: bool = True, sga: bool = True):
        self.cmdbuff = bytearray()
        self.handlers = {hc.opcode: hc() for hc in self.handler_classes}
        self.out_compressor = None
        self.handshakes = TelnetHandshakeHolder()
        self.app_linemode = app_linemode
        self.sga = sga

    def start(self, out: bytearray):
        for k, v in self.handlers.items():
            if v.start_will:
                out.extend(bytearray([TC.IAC, TC.WILL, k]))
                v.local.negotiating = True
                v.local.asked = True

            if v.start_do:
                out.extend(bytearray([TC.IAC, TC.DO, k]))
                v.remote.negotiating = True
                v.remote.asked = True

            if v.hs_local:
                self.handshakes.local.update(v.hs_local)
            if v.hs_remote:
                self.handshakes.remote.update(v.hs_remote)

    def sanitize_text(self, data: Union[str, bytes, bytearray]) -> bytearray:
        data = bytearray(data)
        data = data.replace(b'\r', b'')
        data = data.replace(b'\n', b'\r\n')
        data = data.replace(b'\xFF', b'\xFF\xFF')
        return data

    def send_line(self, data: Union[str, bytes, bytearray], imsg: _InternalMsg):
        data = self.sanitize_text(data)
        if not data.endswith(b'\r\n'):
            data += b'\r\n'
        self.send_bytes(data, imsg)

    def send_text(self, data: Union[str, bytes, bytearray], imsg: _InternalMsg):
        data = self.sanitize_text(data)
        self.send_bytes(data, imsg)

    def send_prompt(self, data: Union[str, bytes, bytearray], imsg: _InternalMsg):
        data = self.sanitize_text(data)
        self.send_bytes(data, imsg)

    def send_mssp(self, data: Dict[str, str], imsg):
        self.handlers[TC.MSSP].send(data, imsg)

    def send_command(self, data: int, imsg: _InternalMsg):
        self.send_bytes(bytes([data]), imsg)

    def send_gmcp(self, data, imsg: _InternalMsg):
        self.handlers[TC.GMCP].send(data, imsg)

    def process_out_message(self, msg: TelnetOutMessage, out_buffer: bytearray):
        imsg = _InternalMsg(self, out_buffer, list())

        if msg.msg_type == TelnetOutMessageType.LINE:
            self.send_line(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.TEXT:
            self.send_text(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.MSSP:
            self.send_mssp(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.BYTES:
            self.send_bytes(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.COMMAND:
            self.send_command(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.PROMPT:
            self.send_prompt(msg.data, imsg)
        elif msg.msg_type == TelnetOutMessageType.GMCP:
            self.send_gmcp(msg.data, imsg)

        return imsg.changed

    def process_frame(self, msg: TelnetFrame, out_buffer: bytearray, out_events: List[TelnetInMessage]) -> dict:
        imsg = _InternalMsg(self, out_buffer, out_events)
        
        if msg.msg_type == TelnetFrameType.DATA:
            self.handle_data(msg.data, imsg)
        elif msg.msg_type == TelnetFrameType.COMMAND:
            self.handle_command(msg.data, imsg)
        elif msg.msg_type == TelnetFrameType.NEGOTIATION:
            self.negotiate(msg.data[0], msg.data[1], imsg)
        elif msg.msg_type == TelnetFrameType.SUBNEGOTIATION:
            self.subnegotiate(msg.data[0], msg.data[1], imsg)
        
        if len(imsg.out_buffer):
            if not self.sga:
                self.send_bytes(bytes([TC.GA]), imsg)

        return imsg.changed

    def handle_command(self, cmd, imsg: _InternalMsg):
        pass

    def handle_data(self, data: Union[bytes, bytearray], imsg: _InternalMsg):
        if self.app_linemode:
            self.cmdbuff.extend(data)
            while True:
                idx = self.cmdbuff.find(TC.LF)
                if idx == -1:
                    break
                found = self.cmdbuff[:idx]
                self.cmdbuff = self.cmdbuff[idx+1:]
                if found.endswith(b'\r'):
                    del found[-1]
                if found:
                    imsg.out_events.append(TelnetInMessage(TelnetInMessageType.LINE, found))
        else:
            imsg.out_events.append(TelnetInMessage(TelnetInMessageType.DATA, bytes(data)))

    def negotiate(self, cmd: int, option: int, imsg: _InternalMsg):
        handler = self.handlers.get(option, None)
        if handler:
            handler.negotiate(cmd, imsg)
        else:
            response = NEG_OPPOSITES.get(cmd, None)
            self.send_negotiate(response, option, imsg)

    def subnegotiate(self, option: int, data: bytes, imsg: _InternalMsg):
        handler = self.handlers.get(option, None)
        if handler:
            handler.subnegotiate(data, imsg)

    def send_negotiate(self, cmd: int, option: int, imsg: _InternalMsg):
        self.send_bytes(bytes([TC.IAC, cmd, option]), imsg)

    def send_subnegotiate(self, cmd: int, data: bytes, imsg: _InternalMsg):
        out = bytearray([TC.IAC, TC.SB, cmd])
        out.extend(data)
        out.extend([TC.IAC, TC.SE])
        self.send_bytes(out, imsg)

    def send_bytes(self, data: Union[bytes, bytearray], imsg: _InternalMsg):
        if self.out_compressor:
            data = self.out_compressor.compress(data) + self.out_compressor.flush(zlib.Z_SYNC_FLUSH)
        imsg.out_buffer.extend(data)
