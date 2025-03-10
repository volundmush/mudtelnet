def ensure_crlf(input_str: str) -> str:
    """
    Ensure that every newline in the input string is preceded by a carriage return.
    Also, escape any Telnet IAC (255) characters by duplicating them.

    Args:
        input_str: The input string.

    Returns:
        A new string with CRLF line endings and escaped IAC characters.
    """
    result = []  # We'll build the output as a list of characters
    prev_char_is_cr = False
    iac = chr(255)

    for c in input_str:
        if c == "\r":
            # Only add a CR if the previous character wasn't a CR.
            if not prev_char_is_cr:
                result.append("\r")
            prev_char_is_cr = True
        elif c == "\n":
            # If the previous char wasn't a CR, add one before the newline.
            if not prev_char_is_cr:
                result.append("\r")
            result.append("\n")
            prev_char_is_cr = False
        elif c == iac:
            # Telnet IAC character: escape it by adding it twice.
            result.append(c)
            result.append(c)
            prev_char_is_cr = False
        else:
            result.append(c)
            prev_char_is_cr = False

    return "".join(result)