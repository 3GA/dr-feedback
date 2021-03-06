#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# feedback_inspector.py
#
# Copyright (C) 2014 Kano Computing Ltd.
# License: http://www.gnu.org/licenses/gpl-2.0.txt GNU General Public License v2
#
#  Module to provide inspectors for each logfile received via Kano Feedback
#

import json
import re
import gzip
import urllib2
import tempfile


#
# Subclass your inspector from this class below
#
class FeedbackInspector:
    '''
    Each inspector focuses on undrstanding a logfile and provides inspect, a method that parses the log
    The purpose is to fill the object 'report' with info, warn and error data.
    '''
    def __init__(self, logfile):
        self.logfile = logfile
        self.report = {'info': [], 'warn': [], 'error': []}
        pass

    def get_info(self):
        return self.report['info']

    def get_warn(self):
        return self.report['warn']

    def get_error(self):
        return self.report['error']

    def add_info(self, entry):
        self.report['info'].append(entry)

    def add_warn(self, entry):
        self.report['warn'].append(entry)

    def add_error(self, entry):
        self.report['error'].append(entry)

    def __assert_finder__(self, logdata, expected, message):
        found_it = False
        for log in logdata:
            if log.find(expected) != -1:
                found_it = True

        return found_it

    def assert_exists(self, logdata, expected, message):
        found_it = self.__assert_finder__(logdata, expected, message)
        if not found_it:
            self.add_warn(message)

        return found_it

    def assert_not_exists(self, logdata, expected, message):
        found_it = self.__assert_finder__(logdata, expected, message)
        if found_it:
            self.add_warn(message)

        return found_it

    def inspect(self, logdata):
        '''
        Parse logdata and add relevant information to the report, for example:
        self.add_error('something went wrong')
        You can use assert_exists / not_exists to make things easy
        self.assert_exists(logdata, 'I have booted up', 'This unit is not working :-)')
        '''
        pass

    def get_format(self, logdata):
        # FIXME: Find a more elegant way to detect a screenshot file
        if logdata.startswith('\x89PNG\r\n'):
            format = 'image'
        else:
            format = 'text'
        import sys
        print >>sys.stderr, self.logfile, format
        return format

#
# Instantiate your specific Inspector for a new logfile parser below
#

class InspectorAppLogsRaw(FeedbackInspector):
    def inspect(self, logdata):
        self.assert_not_exists(logdata, 'rdate FAIL', 'Rdate has failed at least once')
        self.assert_not_exists(logdata, 'make-minecraft error', 'Make Minecraft has reported problems')


class InspectorAppLogsJson(FeedbackInspector):
    def inspect(self, logdata):

        # Parse each component log entries separately
        try:
            jsonlog = json.loads(''.join(logdata))
            for component_name in jsonlog:

                # Search for relevant events on each component
                for component_entry in jsonlog[component_name]:
                    if component_entry['level'] == 'error':
                        self.add_error("%s reported errors" % (component_name))
                        break
        except:
            self.add_error('Could not read logs in Json format')
            raise


class InspectorCmdline(FeedbackInspector):
    def inspect(self, logdata):
        self.assert_exists(logdata, 'ipv6.disable=1', 'IPv6 is not forcibly disabled through the kernel command line')


class InspectorConfig(FeedbackInspector):
    pass


class InspectorDmesg(FeedbackInspector):
    def inspect(self, logdata):
        self.assert_exists(logdata, 'wlan0: associated', 'This unit has not been wirelessly associated since it last booted')


class InspectorHdmiInfo(FeedbackInspector):
    def inspect(self, logdata):

        minimum_display_width = 1024
        minimum_display_height = 768

        # search for the current video mode (CEA / DMT) and the current display resolution
        try:
            for line in logdata:
                if re.search('HDMI: bad EDID header', ''.join(logdata)):
                    self.add_error(line)

            m = re.search('HDMI:EDID found preferred (.*) detail timing format: (.*)x(.*)p.*', ''.join(logdata))
            if m:
                video_mode = m.group(1)
                display_width = m.group(2)
                display_height = m.group(3)

                self.add_info('Video mode is set to: %s' % video_mode)

                if int(display_width) < minimum_display_width or int(display_height) < minimum_display_height:
                    self.add_error('Current display mode is too small: %sx%s (minimum: %sx%s)' %
                                   (display_width, display_height, minimum_display_width, minimum_display_height))
                else:
                    self.add_info('Current display mode should be ok: %sx%s' % (display_width, display_height))
            else:
                self.add_error("HDMI didn't find preferred timing")
        except:
            self.add_error('Could not determine current display mode')
            raise


class InspectorKanuxVersion(FeedbackInspector):
    def inspect(self, logdata):
        self.add_info('Current Kanux Version: %s' % logdata[1])
        self.add_info('Last updated on: %s' % logdata[0])


class InspectorKanuxStamp(FeedbackInspector):
    def inspect(self, logdata):
        pass


class InspectorKwifiCache(FeedbackInspector):
    def inspect(self, logdata):
        if not len(logdata):
            self.add_warn('Looks like there is no wireless credentials cache, \
                           unit is connected over Ethernet')
            return

        self.assert_exists(logdata, 'encryption": "wpa"', 'There is a non-WPA \
                                     connection in the cache (WEP or Open)')


class InspectorPackages(FeedbackInspector):
    def inspect(self, logdata):

        # list of all locally installed packages
        packages = logdata

        # Make sure the unit is using the latest versions of all Kano Software
        # Fetch the list of all latest debian Packages that we supply at our
        # repository server
        url_kano = 'http://repo.kano.me'
        url_kano_packages = url_kano + '/archive-jessie/dists/release/main/binary-armhf/Packages.gz'

        # A temporary file to Kano Release file because gzip needs random access - tell() function
        html_tmpfile = tempfile.TemporaryFile(mode='w+b')

        # some packages we do not want to match because are meant for internal use
        internal_packages = ('libraspberrypi-bin', 'libraspberrypi-dev',
                             'libraspberrypi-doc', 'gnome-panel-control',
                             'openbox-dev')

        # Contact Kano repo to get the Release package file, save to a temporary file
        try:
            fresponse = urllib2.urlopen(url_kano_packages)
            html_tmpfile.write(fresponse.read())
            html_tmpfile.seek(0)
        except:
            self.add_error('Could not contact %s to fetch package list' % url_kano)
            raise

        # loop through the Release file and match against local package log
        gzpkgs = gzip.GzipFile(mode='r', fileobj=html_tmpfile)
        for count, line in enumerate(gzpkgs):

            # We search for the package name alone (Package)
            if line.startswith('Package: '):
                pkg_name = line[9:].strip()
                if pkg_name in internal_packages:
                    pkg_name = None
                else:
                    pass

            # Concatenate the version number, found on line that follows (Version)
            if line.startswith('Version: ') and pkg_name:
                pkg_name_version = '%s-%s' % (pkg_name, line[9:].strip())

                # match the package against the Kit's package list
                try:
                    m = re.search('.*^(%s)(.*)\n' % pkg_name, ''.join(packages), re.MULTILINE)
                    assert(m)

                    # (1) is the package name (2) version number
                    pkg_name_version_installed = m.group(1) + m.group(2)
                except:
                    pkg_name_version_installed = None
                    self.add_error('Package "%s" is not installed' % pkg_name_version)
                    pass

                if pkg_name_version_installed:
                    if pkg_name_version_installed != pkg_name_version:
                        self.add_error('Package version mismatch, installed: \
                                       "%s" repo: "%s"' % (pkg_name_version_installed, pkg_name_version))

        html_tmpfile.close()


class InspectorProcess(FeedbackInspector):
    pass


class InspectorUsbDevices(FeedbackInspector):
    def inspect(self, logdata):
        kano_wireless_dongle = 'Ralink Technology, Corp. RT5370 Wireless Adapter'
        kano_keyboard = 'ID 1997:2433'

        self.assert_exists(logdata, kano_wireless_dongle, 'This Kit is not using the de-facto wireless dongle provided by Kano (or is an RPI3)')
        self.assert_exists(logdata, kano_keyboard, 'This Kit is not using the de-facto Kano Keyboard')


class InspectorWpalog(FeedbackInspector):
    def inspect(self, logdata):
        # This parser is obsoleted by InspectorWifiInfo
        # It is provided by backwards compatibility
        wifi_inspector = InspectorWifiInfo()
        wifi_inspector.inspect_wpa_log(logdata)


class InspectorWifiInfo(FeedbackInspector):
    def inspect(self, logdata):
        find_more_dongles = '.*(wlan[1-9])(.*)'
        try:
            # Try to find if there are more connected wireless devices
            m = re.search(find_more_dongles, ''.join(logdata), re.MULTILINE)
            additional_dongle = m.group(1)
            self.add_warn('There is at least one extra wireless device: %s' % additional_dongle)
        except:
            pass

        self.inspect_wpa_log(logdata)
        self.inspect_ifconfig(logdata)

    def inspect_wpa_log(self, logdata):
        wpa_authenticated = 'EAPOL authentication completed successfully'
        self.assert_exists(logdata, wpa_authenticated, 'There is no indication of a successfull WPA wireless association')

    def inspect_ifconfig(self, logdata):
        # Determine if Ethernet, Wireless, both, or none
        find_ip_regex = '%s.*\n.*inet addr:([0-9\.]*) (.*)'
        ip_ethernet = ip_wireless = None

        try:
            # Find if we have an assigned IP address on the Ethernet interface
            m = re.search(find_ip_regex % 'eth0', ''.join(logdata), re.MULTILINE)
            ip_ethernet = m.group(1)
        except:
            pass

        try:
            # Same for the wireless device
            m = re.search(find_ip_regex % 'wlan0', ''.join(logdata), re.MULTILINE)
            ip_wireless = m.group(1)
        except:
            pass

        # Find out how the unit is network connected and explain it
        if not ip_ethernet and not ip_wireless:
            self.add_warn('This unit does *not* have an IP on Ethernet or Wireless')
        elif ip_ethernet and not ip_wireless:
            self.add_info('This unit is connected through the Ethernet device: %s' % ip_ethernet)
        elif not ip_ethernet and ip_wireless:
            self.add_info('This unit is connected through the Wireless device: %s' % ip_wireless)
        elif ip_ethernet and ip_wireless:
            self.add_error('This unit is connected through *both* the Wireless and Ethernet devices: %s - %s'
                           % ip_wireless, ip_ethernet)


class InspectorScreenshot(FeedbackInspector):
    def inspect(self, logdata):
        self.add_info('This feedback report contains a screenshot')


class InspectorCPUInfo(FeedbackInspector):
    def inspect(self, logdata):
        model = 'Model: unknown'
        for log in logdata:
            if log.startswith('Model:'):
                model = log.strip()
        self.add_info('This is a RaspberryPI ' + model)


class InspectorXorg(FeedbackInspector):
    def inspect(self, logdata):
        pass


class InspectorSyslog(FeedbackInspector):
    def inspect(self, logdata):
        pass


class InspectorLSof(FeedbackInspector):
    def inspect(self, logdata):
        pass


class InspectorContentObjects(FeedbackInspector):
    def inspect(self, logdata):
        pass


class InspectorBinary(FeedbackInspector):
    def inspect(self, logdata):
        pass

    def get_format(self, logdata):
        return 'binary'


class InspectorScreenLog(FeedbackInspector):
    def inspect(self, logdata):
        pass


#
# Add your inspector to the list
#
inspectors = {
    'app-logs.txt': InspectorAppLogsRaw,
    'app-logs-json.txt': InspectorAppLogsJson,
    'cmdline.txt': InspectorCmdline,
    'config.txt': InspectorConfig,
    'dmesg.txt': InspectorDmesg,
    'edid.dat': InspectorBinary,
    'screen-log.txt': InspectorScreenLog,
    'hdmi-info.txt': InspectorHdmiInfo,
    'kanux_version.txt': InspectorKanuxVersion,
    'kanux_stamp.txt': InspectorKanuxStamp,
    'kwificache.txt': InspectorKwifiCache,
    'packages.txt': InspectorPackages,
    'process.txt': InspectorProcess,
    'syslog.txt': InspectorSyslog,
    'usbdevices.txt': InspectorUsbDevices,
    'wpalog.txt': InspectorWpalog,
    'wifi-info.txt': InspectorWifiInfo,
    'cpu-info.txt': InspectorCPUInfo,
    'xorg-log.txt': InspectorXorg,
    'lsof.txt': InspectorLSof,
    'screenshot.png': InspectorScreenshot,
    'content-objects.txt': InspectorContentObjects
}


def get_inspector(filename):
    if filename in inspectors:
        return inspectors[filename]
    elif filename.startswith('core-'):
        return InspectorBinary
    else:
        raise
