#!/usr/bin/python

# The readers come from the factory in KB emulation mode, and will
# read all tracks if present.  The factory omegas want them to only
# send track 2.

import magtek
import sys

if len(sys.argv) < 2:
    print >>sys.stderr, "Usage: %s command"
    sys.exit(1)

def info(r):
    print "Reader mode: %s\nSoftware ID: %s\n" % (r.getMode(), 
                                                  r.getSoftwareID())

def switchToKB(r):
    r.setInterfaceType(magtek.MagTek.INTERFACE_TYPE_KB)
    r.resetDevice()

def switchToHID(r):
    r.setInterfaceType(magtek.MagTek.INTERFACE_TYPE_HID)
    r.resetDevice()

def getTrackFormat(r):
    print "Track Format:\n", r.getTrackFormat()

def enableTrack(r):
    n = int(sys.argv.pop())
    trackformat = reader.getTrackFormat()
    trackformat.enableTrack(n)
    reader.setTrackFormat(trackformat)
    r.resetDevice()

def disableTrack(r):
    n = int(sys.argv.pop())
    trackformat = reader.getTrackFormat()
    trackformat.disableTrack(n)
    reader.setTrackFormat(trackformat)
    r.resetDevice()

_cmdTable = { 'show': info,
              'kbmode': switchToKB,
              'hidmode': switchToHID,
              'show-tracks': getTrackFormat,
              'enable-track': enableTrack,
              'disable-track': disableTrack }

if sys.argv[1] not in _cmdTable:
    print >>sys.stderr, "Invalid command: %s" % sys.argv[0]
    sys.exit(1)

print "Connecting to reader..."
reader = magtek.MagTek()
_cmdTable[sys.argv[1]](reader)
sys.exit(0)
