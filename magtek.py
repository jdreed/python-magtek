# pyusb 1.0 required -- install via PyPI
import usb.core
import usb.util
import array
import sys
import os
import errno

# MagTek's Vendor ID
VENDOR_ID = 0x0801
# The product could either be in HID mode or KB emulation mode
KB_PRODUCT_ID = 0x0001
HID_PRODUCT_ID = 0x0002
# Feature reports are fixed at 24 bytes for this device (see technical
# reference manual: 1 byte command, 1 byte data length, 22 byte data
# field)
BUFSIZE = 24

# Card data is sent in an input report of a fixed size
INPUT_REPORT_SIZE = 337

# USB constants
# Go read sections 7.2.1 and 7.2.2 of the HID spec if you care

# The bRequest value for the request types
# Why are these not constants in PyUSB?
# From the USB HID spec
BREQ_SET_REPORT = 0x09
BREQ_GET_REPORT = 0x01

# bmRequestType for reports
# These do correspond to usb.TYPE_CLASS | usb.RECIP_INTERFACE | usb.ENDPOINT_IN
# and usb.TYPE_CLASS | usb.RECIP_INTERFACE | usb.ENDPOINT_OUT respectively.
# however, the spec is clear that we're talking to the control pipe, not the
# in or out pipes.  (Rather, in this case, there's only one pipe, the IN pipe,
# that is also the control pipe)
# I'm listing them separately in the hopes that this helps someone
# down the line, because too many PyUSB programs are full of
# completely uncommented, seemingly arbitrary hex codes
BMREQ_GET_REPORT = 0xa1
BMREQ_SET_REPORT = 0x21

# wValue: 
# From the HID spec: "The wValue field specifies the Report Type in
# the high byte and the Report ID in the low byte. Set Report ID to 0
# (zero) if Report IDs are not used."
# We only use report type 3 (feature report)
REPORT_TYPE = 0x03
# From the vendor specs, there is only one report id number: 0
REPORT_NUM = 0x00
# Byte shift
WVALUE = REPORT_NUM | (REPORT_TYPE << 8)

# Return codes specified by the vendor
RC_SUCCESS = 0x00
RC_FAIL = 0x01
RC_BADPARAM = 0x02

# A class holding swipe data
# Card type enum is from vendor data
class MagTekSwipeData:
    _cardTypes = { 0: 'ISO/ABA',
                   1: 'AAMVA',
                   2: 'CADL',
                   3: 'Blank',
                   4: 'Other',
                   5: 'Undetermined',
                   6: 'None' }
    def __init__(self, byteString):
        if not isinstance(byteString, array.array):
            raise MagTekException('Swipe data must be array.array')
        if len(byteString) != 337:
            raise MagTekException('Swipe data was not 337 bytes!')
        self.trackDecodeStatus = byteString[0:3]
        self.trackLengths = byteString[3:6]
        self._cardType = byteString[6]
        self.trackData = [byteString[7:116], byteString[117:226], byteString[227:336]]

    def __str__(self):
        try:
            rv = "Card type: %s\n" % (self._cardTypes[self._cardType])
            for i in (1, 2, 3):
                rv += "Track %d Decode: %s\n" % (i, "Error" if self.trackDecodeStatus[i-1] else "OK")
                rv += "Track %d Length: %d\n" % (i, self.trackLengths[i-1])
                rv += "Track %d Raw Data: %s\n" % (i, self.trackData[i-1][0:self.trackLengths[i-1]].tolist())
                rv += "Track %d String Data: %s\n" % (i, self.trackData[i-1][0:self.trackLengths[i-1]].tostring())
        except KeyError:
            rv = "Exception occurred while formatting string (incomplete/bad swipe data)\n";
            rv += "Raw array data: " + trackData.tolist()
        return rv

    def getTrack(self, trackNum):
        if trackNum not in (1, 2, 3):
            raise MagTekException('Invalid Track Number')
        if not self.trackDecodeStatus[trackNum-1]:
            return self.trackData[trackNum-1][0:self.trackLengths[trackNum-1]].tostring()
        else:
            return None

# A representation of the track status of the reader, suitable for
# conversion to a byte string for the commands.
class MagTekTrackFormat:
    _trackModes = { 1: 'Enabled', 
                    2: 'Enabled and Required',
                    0: 'Disabled' }

    def __init__(self, value):
        # The track format field is a 1 byte field
        # | x | 0 | t3 t3 | t2 t2 | t1 t1
        # x is 1 or 0 for decode all formats or ISO/ABA only
        # t3, t2, t1 are 2-byte fields for each track
        # 00 = disable, 01 = enable, 10 = enable+require (error if blank)
        self.tracks = []
        for i in range(0, 3):
            self.tracks.append(3 & value)
            value = value >> 2
        self.decodeAll = value
        
    def __str__(self):
        rv = "MagTekTrackFormat:\n"
        for i in (1, 2, 3):
            rv += "Track %d: %s\n" % (i, self._trackModes[self.tracks[i-1]])
        rv += "Decode all card formats" if self.decodeAll else "Decode ISO/ABA only"
        rv += "\n"
        return rv
    
    def enableTrack(self, trackNum, required=False):
        if trackNum not in (1, 2, 3):
            raise MagTekException("Invalid track number")
        self.tracks[trackNum - 1] = 2 if required else 1

    def disableTrack(self, trackNum):
        if trackNum not in (1, 2, 3):
            raise MagTekException("Invalid track number")
        self.tracks[trackNum - 1] = 0

    def _byte(self):
        value = self.decodeAll
        for i in reversed(self.tracks):
            value = value << 2
            value += i
        return value

class MagTekException(BaseException):
    pass

class MagTekUSBException(BaseException):
    pass

class MagTek:
    INTERFACE_TYPE_HID = 0
    INTERFACE_TYPE_KB = 1
    _modeNames = { INTERFACE_TYPE_HID: 'Raw HID mode',
                   INTERFACE_TYPE_KB: 'KB emulation mode' }

    

    def __init__(self):
        self._dev = None
        self._handle = None
        # Default mode in factory config
        self._mode = self.INTERFACE_TYPE_KB
        self._dev = usb.core.find(idVendor=VENDOR_ID,
                                  idProduct=KB_PRODUCT_ID)
        if self._dev == None:
            self._dev = usb.core.find(idVendor=VENDOR_ID,
                                      idProduct=HID_PRODUCT_ID)
            self._mode = self.INTERFACE_TYPE_HID
        if self._dev == None:
            raise MagTekException('Could not find MagTek reader')

        try:
            if self._dev.is_kernel_driver_active(0):
                self._dev.detach_kernel_driver(0)
        except usb.core.USBError as e:
            raise MagTekUSBException("Could not detach kernel driver (are you root?)", str(e))
        
        try:
            self._dev.set_configuration()
        except usb.core.USBError as e:
            raise MagTekUSBException("Could not set configuration", str(e))

        try:
            self._dev.reset()
        except usb.core.USBError as e:
            raise MagTekUSBException("Could not reset device", str(e))

    def getMode(self):
        # Maybe we should getInterfaceType() here?
        return self._modeNames[self._mode]

    def getSoftwareID(self):
        return self._get_property(0x00).tostring()

    def getTrackFormat(self):
        return MagTekTrackFormat(self._get_property(0x03))
        
    def setTrackFormat(self, trackFormat):
        if not isinstance(trackFormat, MagTekTrackFormat):
            raise TypeError('trackFormat must be an instance of MagTekTrackFormat')
        self._set_property(0x03, trackFormat._byte())

    def getInterfaceType(self):
        return self._get_property(0x10)

    def setInterfaceType(self, ifType):
        self._set_property(0x10, ifType)

    def _get_property(self, propNum):
        return self._send_command(0x00, [propNum])

    def _set_property(self, propNum, value):
        return self._send_command(0x01, [propNum, value])
    
    def resetDevice(self):
        # This is not a usb reset() command, this reboots the device
        self._send_command(0x02, [])

    def readCard(self, loopCallback=None):
        # See pyusb docs for the subscript operators.  This device only
        # has one configuration, one interface, and one endpoint.  For
        # more complicated devices, you want usb.util.find_descriptor
        if self._mode != 0:
            raise MagTekException('Cannot call readCard on devices in KB emulation mode')
        self._endpoint = self._dev[0][(0,0)][0]
        if usb.util.endpoint_direction(self._endpoint.bEndpointAddress) != usb.util.ENDPOINT_IN:
            raise MagTekException("Couldn't find an IN endpoint!")
        bytesRead = 0
        cardData = array.array('B')
        while bytesRead < INPUT_REPORT_SIZE:
            if loopCallback is not None and loopCallback() != True:
                return None
            try:
                cardData += self._dev.read(self._endpoint.bEndpointAddress,
                                           self._endpoint.wMaxPacketSize)
                bytesRead = len(cardData)
            except usb.core.USBError as e:
                if e.args[0] != errno.ETIMEDOUT:
                    raise MagTekException(e)
        # Flush the input, in case someone swipes twice, or there was stray swipe data
        # There's probably a better way to deal with this
        # But this avoids the problem of bad data (or limits it to one read)
        try:
            self._dev.read(self._endpoint.bEndpointAddress,
                           self._endpoint.wMaxPacketSize)
        except usb.core.USBError as e:
            pass
        return MagTekSwipeData(cardData)

    def _send_command(self, cmdNum, data):
        # Commands are sent in feature reports. Feature reports are
        # fixed at 24 bytes for this device (see technical reference
        # manual: 1 byte command, 1 byte data length, 22 byte data
        # field)
        # 
        try:
            it = iter(data)
        except TypeError:
            raise MagTekException("data is not iterable")
        if len(data) > 22:
            raise MagTekException("data too long")

        # Create a zeroed-out buffer
        buf = [0] * BUFSIZE
        buf[0] = cmdNum
        buf[1] = len(data)
        data_idx = 2
        for i in data:
            buf[data_idx] = i
            data_idx += 1

        if BUFSIZE != self._dev.ctrl_transfer(BMREQ_SET_REPORT, 
                                              BREQ_SET_REPORT, 
                                              wValue=WVALUE, 
                                              data_or_wLength=buf):
            raise MagTekUSBException("Failed to send control request!")
        result = self._dev.ctrl_transfer(BMREQ_GET_REPORT,
                                         BREQ_GET_REPORT,
                                         wValue=WVALUE, 
                                         data_or_wLength=BUFSIZE)        
        rc = result.pop(0)
        if rc != RC_SUCCESS:
            if rc == RC_FAIL:
                raise MagTekException("Command failed.")
            if rc == RC_BADPARAM:
                raise MagTekException("Command failed due to bad parameter or syntax error.")
        length = result.pop(0)
        if length == 1:
            return result.pop(0)
        if length > 0:
            return result[0:length]
        else:
            return None
            
        

