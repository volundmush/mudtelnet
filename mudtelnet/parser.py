import typing
from enum import IntEnum


class TelnetCode(IntEnum):
    NULL = 0
    SGA = 3
    BEL = 7
    LF = 10
    CR = 13

    # MTTS - Terminal Type
    MTTS = 24

    TELOPT_EOR = 25

    # NAWS: Negotiate About Window Size
    NAWS = 31
    LINEMODE = 34

    # Negotiate about charset in use.
    CHARSET = 42

    # MNES: Mud New - Environ standard
    MNES = 39

    # MSDP - Mud Server Data Protocol
    MSDP = 69

    # Mud Server Status Protocol
    MSSP = 70

    # Compression
    # MCCP1: u8 = 85 - this is deprecrated
    # NOTE: MCCP2 and MCCP3 is currently disabled.
    MCCP2 = 86
    MCCP3 = 87

    # MUD eXtension Protocol
    # NOTE: Disabled due to too many issues with it.
    MXP = 91

    # GMCP - Generic Mud  Communication Protocol
    GMCP = 201

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

    def __str__(self):
        return str(self.name)

    @classmethod
    def to_str(cls, val: int):
        try:
            return cls(val).name
        except ValueError:
            return str(val)


class TelnetData:

    __slots__ = ["data"]

    def __init__(self, data: bytes):
        self.data = data

    def __bytes__(self):
        return self.data

    def __str__(self):
        return self.data.decode()

    def __repr__(self):
        return f"<TelnetData: {self.data}>"


class TelnetCommand:

    __slots__ = ["command"]

    def __init__(self, command: int):
        self.command = command

    def __bytes__(self):
        return bytes([TelnetCode.IAC, self.command])

    def __str__(self):
        out = [TelnetCode.IAC.name, TelnetCode.to_str(self.command)]
        return " ".join(out)

    def __repr__(self):
        return f"<TelnetCommand: {self}>"


class TelnetNegotiate:

    __slots__ = ["command", "option"]

    def __init__(self, command: int, option: int):
        self.command = int(command)
        self.option = int(option)

    def __bytes__(self):
        return bytes([TelnetCode.IAC.value, self.command, self.option])

    def __str__(self):
        out = [
            TelnetCode.IAC.name,
            TelnetCode.to_str(self.command),
            TelnetCode.to_str(self.option),
        ]
        return " ".join(out)

    def __repr__(self):
        return f"<TelnetNegotiate: {self}>"


class TelnetSubNegotiate:

    __slots__ = ["option", "data"]

    def __init__(self, option: int, data: bytes):
        self.option = option
        self.data = data

    def __bytes__(self):
        return bytes(
            [
                TelnetCode.IAC.value,
                TelnetCode.SB.value,
                self.option,
                *self.data,
                TelnetCode.IAC.value,
                TelnetCode.SE.value,
            ]
        )

    def __str__(self):
        out = [
            TelnetCode.IAC.name,
            TelnetCode.SB.name,
            TelnetCode.to_str(self.option),
            repr(self.data),
            TelnetCode.IAC.name,
            TelnetCode.SE.name,
        ]
        return " ".join(out)

    def __repr__(self):
        return f"<TelnetSubNegotiate: {self}>"


def _scan_until_iac(data: bytes) -> int:
    for i in range(len(data)):
        if data[i] == TelnetCode.IAC:  # 255 is the IAC byte
            return i
    return len(data)  # Return the length if IAC is not found


def _scan_until_iac_se(data: bytes) -> int:
    i = 0
    while i < len(data) - 1:  # -1 because we need at least 2 bytes for IAC SE
        if data[i] == TelnetCode.IAC:
            if data[i + 1] == TelnetCode.SE:
                # Found unescaped IAC SE
                return i + 2  # Return the length including IAC SE
            elif data[i + 1] == TelnetCode.IAC:
                # Escaped IAC, skip this and the next byte
                i += 2
                continue
            # Else it's an IAC followed by something other than SE or another IAC,
            # which is unexpected in subnegotiation. Handle as needed.
        i += 1
    return -1  # Return -1 to indicate that IAC SE was not found


def parse_telnet(
        data: bytes,
) -> tuple[
    int,
    typing.Union[None, TelnetCommand, TelnetData, TelnetNegotiate, TelnetSubNegotiate],
]:
    """
    Parse a raw byte sequence and return a tuple consisting of bytes-to-consume/advance by,
    and an optional Telnet message.
    """
    if len(data) < 1:
        return 0, None

    if data[0] == TelnetCode.IAC:
        if len(data) < 2:
            # we need at least 2 bytes for an IAC to mean anything.
            return 0, None

        if data[1] == TelnetCode.IAC:
            # Escaped IAC
            return 2, TelnetData(data[:1])
        elif data[1] in (
                TelnetCode.WILL,
                TelnetCode.WONT,
                TelnetCode.DO,
                TelnetCode.DONT,
        ):
            if len(data) < 3:
                return 0, None
            return 3, TelnetNegotiate(data[1], data[2])
        elif data[1] == TelnetCode.SB:
            length = _scan_until_iac_se(data)
            if length < 5:
                return 0, None
            return length, TelnetSubNegotiate(data[2], data[3 : length - 2])
        else:
            # Other command
            return 2, TelnetCommand(data[1])

    # If the first byte isn't an IAC, scan until the first IAC or end of data
    length = _scan_until_iac(data)
    return length, TelnetData(data[:length])

