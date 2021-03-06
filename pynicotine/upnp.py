# COPYRIGHT (C) 2020 Nicotine+ Team
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2009-2010 Quinox <quinox@users.sf.net>
#
# GNU GENERAL PUBLIC LICENSE
#    Version 3, 29 June 2007
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
from gettext import gettext as _
from subprocess import PIPE
from subprocess import STDOUT
from subprocess import Popen

from pynicotine.logfacility import log


class UPnPPortMapping:
    """Class that handle UPnP Port Mapping"""

    def __init__(self):
        """Initialize the UPnP Port Mapping object."""

        # Default discovery delay (ms)
        self.discoverdelay = 2000

        # List of existing port mappings
        self.existingportsmappings = []

        # Initial value that determine if a port mapping already exist to the
        # client
        self.foundexistingmapping = False

        # We try to find the miniupnpc binary in the $PATH
        self.upnpcbinary = 'upnpc'

    def run_binary(self, cmd):
        """Function used to call the upnpc binary.

        Redirect stderr to stdout since we don't really care having
        two distinct streams.

        Also prevent the command prompt from being shown on Windows.
        """

        p = Popen(cmd, stdout=PIPE, stderr=STDOUT)

        (out, err) = p.communicate()

        return out.decode('utf-8').rstrip()

    def is_possible(self):
        """Function to check the requirements for doing a port mapping.

        It tries to import the MiniUPnPc python binding: miniupnpc.
        If it fails, it tries to use the MiniUPnPc binary: upnpc.
        If neither of them are available UPnP Port Mapping is unavailable.
        """

        try:
            # First we try to import the python binding
            import miniupnpc  # noqa: F401
        except ImportError as e1:
            try:
                # We fail to import the python module: fallback to the binary.
                self.run_binary([self.upnpcbinary])
            except Exception as e2:
                # Nothing works :/
                errors = [
                    _('Failed to import miniupnpc module: %(error)s') %
                    {'error': str(e1)},
                    _('Failed to run upnpc binary: %(error)s') %
                    {'error': str(e2)}
                ]
                return (False, errors)
            else:
                # If the binary is available we define the resulting mode
                self.mode = '_binary'
                return (True, None)
        else:
            # If the python binding import is successful we define the
            # resulting mode
            self.mode = '_module'
            return (True, None)

    def add_port_mapping(self, np):
        """Wrapper to redirect the Port Mapping creation to either:

        - The MiniUPnPc binary: upnpc.
        - The python binding to the MiniUPnPc binary: miniupnpc.

        Both method support creating a Port Mapping
        via the UPnP IGDv1 and IGDv2 protocol.

        Need a reference to the np object to extract the internal LAN
        local from the protothread socket.

        From the UPnP IGD reference:
        http://upnp.org/specs/gw/UPnP-gw-WANIPConnection-v2-Service.pdf

        IGDv1 and IGDV2: AddPortMapping:
        This action creates a new port mapping or overwrites
        an existing mapping with the same internal client.
        If the ExternalPort and PortMappingProtocol pair is already mapped
        to another internal client, an error is returned.

        IGDv1: NewLeaseDuration:
        This argument defines the duration of the port mapping.
        If the value of this argument is 0, it means it's a static port mapping
        that never expire.

        IGDv2: NewLeaseDuration:
        This argument defines the duration of the port mapping.
        The value of this argument MUST be greater than 0.
        A NewLeaseDuration with value 0 means static port mapping,
        but static port mappings can only be created through
        an out-of-band mechanism.
        If this parameter is set to 0, default value of 604800 MUST be used.

        BTW since we don't recheck periodically ports mappings
        while nicotine+ runs, any UPnP port mapping done with IGDv2
        (any modern router does that) will expire after 7 days.
        The client won't be able to send/receive files anymore...
        """

        log.add(_('Creating Port Mapping rule via UPnP...'))

        # Placeholder LAN IP address, updated in AddPortMappingBinary or AddPortMappingModule
        self.internalipaddress = "127.0.0.1"

        # Store the Local LAN port
        self.internallanport = np.protothread._p.getsockname()[1]
        self.externalwanport = self.internallanport

        # The function depends on what method of configuring port mapping is
        # available
        functiontocall = getattr(self, 'add_port_mapping' + self.mode)

        try:
            functiontocall()
        except Exception as e:
            log.add_warning(_('UPnP exception: %(error)s'), {'error': str(e)})
            log.add_warning(
                _('Failed to automate the creation of ' +
                    'UPnP Port Mapping rule.'))
            return

        log.add_debug(
            _('Managed to map external WAN port %(externalwanport)s ' +
                'on your external IP %(externalipaddress)s ' +
                'to your local host %(internalipaddress)s ' +
                'port %(internallanport)s.'),
            {
                'externalwanport': self.externalwanport,
                'externalipaddress': self.externalipaddress,
                'internalipaddress': self.internalipaddress,
                'internallanport': self.internallanport
            }
        )

    def add_port_mapping_binary(self):
        """Function to create a Port Mapping via MiniUPnPc binary: upnpc.

        It tries to reconstruct a datastructure identical to what the python
        module does by parsing the output of the binary.
        This help to have a bunch of common code to find a suitable
        external WAN port later.

        IGDv1: If a Port Mapping already exist:
            It's updated with a new static port mapping that does not expire.
        IGDv2: If a Port Mapping already exist:
            It's updated with a new lease duration of 7 days.
        """

        # Listing existing ports mappings
        log.add_debug('Listing existing Ports Mappings...')

        command = [self.upnpcbinary, '-l']
        try:
            output = self.run_binary(command)
        except Exception as e:
            raise RuntimeError(
                _('Failed to use UPnPc binary: %(error)s') % {'error': str(e)})

        # Build a list of tuples of the mappings
        # with the same format as in the python module
        # (ePort, protocol, (intClient, iPort), desc, enabled, rHost, duration)
        # (15000, 'TCP', ('192.168.0.1', 2234), 'Nicotine+', '1', '', 0)
        #
        # Also get the external WAN IP
        #
        # Output format :
        # ...
        # ExternalIPAddress = X.X.X.X
        # ...
        #  i protocol exPort->inAddr:inPort description remoteHost leaseTime
        #  0 TCP 15000->192.168.0.1:2234  'Nicotine+' '' 0

        re_internal_ip = re.compile(r"""
            ^
                Local \s+ LAN \s+ ip \s+ address
                \s+ : \s+
                (?P<ip> \d+ \. \d+ \. \d+ \. \d+ )?
            $
        """, re.VERBOSE)

        re_external_ip = re.compile(r"""
            ^
                ExternalIPAddress
                \s+ = \s+
                (?P<ip> \d+ \. \d+ \. \d+ \. \d+ )?
            $
        """, re.VERBOSE)

        re_mapping = re.compile(r"""
            ^
                \d+ \s+
                (?P<protocol> \w+ ) \s+
                (?P<ePort> \d+ ) ->
                (?P<intClient> \d+ \. \d+ \. \d+ \. \d+ ) :
                (?P<iPort> \d+ ) \s+
                ' (?P<desc> .* ) ' \s+
                ' (?P<rHost> .* ) ' \s+
                (?P<duration> \d+ )
            $
        """, re.VERBOSE)

        for line in output.split('\n'):

            line = line.strip()

            internal_ip_match = re.match(re_internal_ip, line)
            external_ip_match = re.match(re_external_ip, line)
            mapping_match = re.match(re_mapping, line)

            if internal_ip_match:
                self.internalipaddress = internal_ip_match.group('ip')
                continue

            if external_ip_match:
                self.externalipaddress = external_ip_match.group('ip')
                continue

            if mapping_match:
                enabled = '1'
                self.existingportsmappings.append(
                    (
                        int(mapping_match.group('ePort')),
                        mapping_match.group('protocol'),
                        (mapping_match.group('intClient'),
                         int(mapping_match.group('iPort'))),
                        mapping_match.group('desc'),
                        enabled,
                        mapping_match.group('rHost'),
                        int(mapping_match.group('duration'))
                    )
                )

        # Find a suitable external WAN port to map to based
        # on the existing mappings
        self.find_suitable_external_wan_port()

        # Do the port mapping
        log.add_debug('Trying to redirect %s port %s TCP => %s port %s TCP', (
            self.externalipaddress,
            self.externalwanport,
            self.internalipaddress,
            self.internallanport
        ))

        command = [
            self.upnpcbinary,
            '-e',
            'Nicotine+',
            '-a',
            str(self.internalipaddress),
            str(self.internallanport),
            str(self.externalwanport),
            'TCP'
        ]

        try:
            output = self.run_binary(command)
        except Exception as e:
            raise RuntimeError(
                _('Failed to use UPnPc binary: %(error)s') % {'error': str(e)})

        for line in output.split('\n'):
            if line.startswith("external ") and \
               line.find(" is redirected to internal ") > -1:
                log.add_debug('Success')
                return
            if line.find(" failed with code ") > -1:
                log.add_debug('Failed')
                raise RuntimeError(
                    _('Failed to map the external WAN port: %(error)s') %
                    {'error': str(line)})

        raise AssertionError(
            _('UPnPc binary failed, could not parse output: %(output)s') %
            {'output': str(output)})

    def add_port_mapping_module(self):
        """Function to create a Port Mapping via the python binding: miniupnpc.

        IGDv1: If a Port Mapping already exist:
            It's updated with a new static port mapping that does not expire.
        IGDv2: If a Port Mapping already exist:
            It's updated with a new lease duration of 7 days.
        """

        import miniupnpc

        u = miniupnpc.UPnP()
        u.discoverdelay = self.discoverdelay

        # Discovering devices
        log.add_debug('Discovering... delay=%sms', u.discoverdelay)

        try:
            log.add_debug('%s device(s) detected', u.discover())
        except Exception as e:
            raise RuntimeError(
                _('UPnP exception (should never happen): %(error)s') %
                {'error': str(e)})

        # Select an IGD
        try:
            u.selectigd()
        except Exception as e:
            raise RuntimeError(
                _('Cannot select an IGD : %(error)s') %
                {'error': str(e)})

        self.internalipaddress = u.lanaddr
        self.externalipaddress = u.externalipaddress()
        log.add_debug('IGD selected : External IP address: %s', self.externalipaddress)

        # Build existing ports mappings list
        log.add_debug('Listing existing Ports Mappings...')

        i = 0
        while True:
            p = u.getgenericportmapping(i)
            if p is None:
                break
            self.existingportsmappings.append(p)
            i += 1

        # Find a suitable external WAN port to map to based on the existing
        # mappings
        self.find_suitable_external_wan_port()

        # Do the port mapping
        log.add_debug('Trying to redirect %s port %s TCP => %s port %s TCP', (
            self.externalipaddress,
            self.externalwanport,
            self.internalipaddress,
            self.internallanport
        ))

        try:
            u.addportmapping(self.externalwanport, 'TCP',
                             self.internalipaddress,
                             self.internallanport, 'Nicotine+', '')
        except Exception as e:
            log.add_debug('Failed')
            raise RuntimeError(
                _('Failed to map the external WAN port: %(error)s') %
                {'error': str(e)}
            )

        log.add_debug('Success')

    def find_suitable_external_wan_port(self):
        """Function to find a suitable external WAN port to map to the client.

        It will detect if a port mapping to the client already exist.
        """

        # Output format: (e_port, protocol, (int_client, iport), desc, enabled,
        # rHost, duration)
        log.add_debug('Existing Port Mappings: %s', (
            sorted(self.existingportsmappings, key=lambda tup: tup[0])))

        # Analyze ports mappings
        for m in sorted(self.existingportsmappings, key=lambda tup: tup[0]):

            (e_port, protocol, (int_client, iport),
             desc, enabled, rhost, duration) = m

            # A Port Mapping is already in place with the client: we will
            # rewrite it to avoid a timeout on the duration of the mapping
            if protocol == "TCP" and \
               str(int_client) == str(self.internalipaddress) and \
               iport == self.internallanport:
                log.add_debug('Port Mapping already in place: %s', str(m))
                self.externalwanport = e_port
                self.foundexistingmapping = True
                break

        # If no mapping already in place we try to found a suitable external
        # WAN port
        if not self.foundexistingmapping:

            # Find the first external WAN port > requestedwanport that's not
            # already reserved
            tcpportsreserved = [x[0] for x in sorted(
                self.existingportsmappings) if x[1] == "TCP"]

            while self.externalwanport in tcpportsreserved:
                if self.externalwanport + 1 <= 65535:
                    self.externalwanport += 1
                else:
                    raise AssertionError(
                        _('Failed to find a suitable external WAN port, ' +
                            'bailing out.'))
