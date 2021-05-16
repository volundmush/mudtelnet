# Volund's MudTelnet library for Python

## CONTACT INFO
**Name:** Volund

**Email:** volundmush@gmail.com

**PayPal:** volundmush@gmail.com

**Discord:** Volund#1206

**Patreon:** https://www.patreon.com/volund

**Home Repository:** https://github.com/volundmush/mudtelnet-python

## TERMS AND CONDITIONS

MIT license. In short: go nuts, but give credit where credit is due.

Please see the included LICENSE.txt for the legalese.

## INTRO
MUD (Multi-User Dungeon) games and their brethren like MUSH, MUX, MUCK, and MOO (look 'em up!) utilize a peculiar subset of telnet. At least, SOME do - there are servers and clients which don't bother with telnet negotiation. But, for those that do, the telnet features largely begin and end with using IAC WILL/WONT/DO/DONT Negotiation and IAC SB <option> <data> IAC SE to send arbitrary data. In a way, MUD Telnet has diverged to become its own dialect. Library support for MUD-specific features like MXP, MSSP, and MCCP2 can be hard to come by. This library attempts to provide a one-stop-shop for handling MUD Telnet.

This library isn't a MUD. It doesn't open any ports or send data. It's simply a tool for taking the bytes a program would receive from a client and turning it into a series of 'events' that user-given application logic can then utilize, and a way to encode 'outgoing events' into bytes to be sent back to a client.

## FEATURES
  * MCCP2 (Mud Client Compression Protocol v2)
  * MTTS (Mud Terminal Type Standard, aka TTYPE)
  * NAWS (Negotiate About Window Size)
  * Suppress_GA
  * Linemode
  * MSSP (Mud Server Status Protocol)
  * MXP (Mud eXtension Protocol)

## COMING SOON?
  * MCCP3 (Mud Client Compression Protocol v3)
  * MUD Prompt support
  * GMCP (Generic Mud Communication Protocol)
  * MSDP (Mud Server Data Protocol)
  * MNES (Mud New-Environ Standard)
  

## OKAY, BUT HOW DO I USE IT?
Glad you asked.

Input from clients must be converted to TelnetFrame, first.
```python
from mudtelnet import TelnetFrame
data = bytearray([255, 251, 31, 13])
frame, size = TelnetFrame.parse(data)
```
You'll notice that frame is a NEGOTIATION type. size is 3. data was read but not modified. in order to consume bytes, you would need to del data[:size] after verifying that a frame was parsed - if there wasn't enough bytes, then frame will be ```None```.

Each client session needs an associated TelnetConnection object.
```python
from mudtelnet import TelnetConnection

conn = TelnetConnection()

out_buffer = bytearray()
out_events = list()
changed = conn.process_frame(frame, out_buffer, out_events)
```
Once you have a frame, you feed it to TelnetConnection.process_frame(). This method accepts a bytearray to append outgoing bytes to (as certain input will result in immediate output, such as option negotiation) and also a list that protocol events (such as user commands) will be appended to. It returns a dictionary of what CHANGED, if anything - such as if MCCP2 was enabled or the client's name was identified via MTTS.

To send data...
```python
from mudtelnet import TelnetOutMessage, TelnetOutMessageType

msg = TelnetOutMessage(TelnetOutMessageType.LINE, "Mud Telnet makes it easy!")

conn.process_out_message(msg, out_buffer)
```
The message will be encoded to bytes, which are then appended to out_buffer.

## FAQ 
  __Q:__ This is cool! How can I help?  
  __A:__ Patreon support is always welcome. If you can code and have cool ideas or bug fixes, feel free to fork, edit, and pull request!

  __Q:__ I found a bug! What do I do?  
  __A:__ Post it on this GitHub's Issues tracker. I'll see what I can do when I have time. ... or you can try to fix it yourself and submit a Pull Request. That's cool too.

  __Q:__ But... I want a MUD! Where do I start making a MUD?  
  __A:__ Coming soon...

  __Q:__ Why not just feed data straight to TelnetConnection? Why manually create TelnetFrames first?  
  __A:__ Eventually, I want to add MCCP3 support, which would call for decompressing incoming data. Since the client will send data to trigger the server understanding that all following data will be compressed, Frames must be parsed one at a time so that any remaining data can be optionally decompressed. It's easy to create a 'BufferedTelnetConnection' subclass that handles all of this for you, though.

## Special Thanks
  * The Evennia Project.
  * All of my Patrons on Patreon.
  * Anyone who contributes to this project or my other ones.