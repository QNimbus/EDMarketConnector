#!/usr/bin/python
# -*- coding: utf-8 -*-

import json
import requests
from collections import defaultdict
from cookielib import LWPCookieJar
import numbers
import os
from os.path import dirname, join
from requests.packages import urllib3
import sys
from sys import platform
import time

if __debug__:
    from traceback import print_exc

from config import config

holdoff = 120	# be nice


# Map values reported by the Companion interface to names displayed in-game and recognized by trade tools

categorymap = { 'Narcotics': 'Legal Drugs',
                'Slaves': 'Slavery',
                'NonMarketable': False, }

commoditymap= { 'Agricultural Medicines': 'Agri-Medicines',
                'Atmospheric Extractors': 'Atmospheric Processors',
                'Auto Fabricators': 'Auto-Fabricators',
                'Basic Narcotics': 'Narcotics',
                'Bio Reducing Lichen': 'Bioreducing Lichen',
                'Hazardous Environment Suits': 'H.E. Suits',
                'Heliostatic Furnaces': 'Microbial Furnaces',
                'Marine Supplies': 'Marine Equipment',
                'Non Lethal Weapons': 'Non-Lethal Weapons',
                'S A P8 Core Container': 'SAP 8 Core Container',
                'Terrain Enrichment Systems': 'Land Enrichment Systems', }

shipmap = {
    'Adder'               : 'Adder',
    'Anaconda'            : 'Anaconda',
    'Asp'                 : 'Asp',
    'CobraMkIII'          : 'Cobra Mk III',
    'DiamondBack'         : 'Diamondback Scout',
    'DiamondBackXL'       : 'Diamondback Explorer',
    'Eagle'               : 'Eagle',
    'Empire_Courier'      : 'Imperial Courier',
    'Empire_Fighter'      : 'Imperial Fighter',
    'Empire_Trader'       : 'Imperial Clipper',
    'Federation_Dropship' : 'Federal Dropship',
    'Federation_Fighter'  : 'F63 Condor',
    'FerDeLance'          : 'Fer-de-Lance',
    'Hauler'              : 'Hauler',
    'Orca'                : 'Orca',
    'Python'              : 'Python',
    'SideWinder'          : 'Sidewinder',
    'Type6'               : 'Type-6 Transporter',
    'Type7'               : 'Type-7 Transporter',
    'Type9'               : 'Type-9 Heavy',
    'Viper'               : 'Viper',
    'Vulture'             : 'Vulture',
}


class ServerError(Exception):
    def __str__(self):
        return 'Error: Server is down'

class CredentialsError(Exception):
    def __str__(self):
        return 'Error: Invalid Credentials'

class VerificationRequired(Exception):
    def __str__(self):
        return 'Authentication required'

# Server companion.orerve.net uses a session cookie ("CompanionApp") to tie together login, verification
# and query. So route all requests through a single Session object which holds this state.

class Session:

    STATE_NONE, STATE_INIT, STATE_AUTH, STATE_OK = range(4)

    def __init__(self):
        self.state = Session.STATE_INIT
        self.credentials = None

        urllib3.disable_warnings()	# yuck suppress InsecurePlatformWarning
        if platform=='win32' and getattr(sys, 'frozen', False):
            os.environ['REQUESTS_CA_BUNDLE'] = join(dirname(sys.executable), 'cacert.pem')

        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 7_1_2 like Mac OS X) AppleWebKit/537.51.2 (KHTML, like Gecko) Mobile/11D257'
        self.session.cookies = LWPCookieJar(join(config.app_dir, 'cookies.txt'))
        try:
            self.session.cookies.load()
        except IOError:
            pass

    def login(self, username=None, password=None):
        self.state = Session.STATE_INIT
        if (not username or not password):
            if not self.credentials:
                raise CredentialsError()
        else:
            self.credentials = { 'email' : username, 'password' : password }
        r = self.session.post('https://companion.orerve.net/user/login', data = self.credentials)
        if r.status_code != requests.codes.ok:
            self.dump(r)
        r.raise_for_status()

        if 'server error' in r.text:
            self.dump(r)
            raise ServerError()
        elif 'Password' in r.text:
            self.dump(r)
            raise CredentialsError()
        elif 'Verification Code' in r.text:
            self.state = Session.STATE_AUTH
            raise VerificationRequired()
        else:
            self.state = Session.STATE_OK
            return r.status_code

    def verify(self, code):
        r = self.session.post('https://companion.orerve.net/user/confirm',
                              data = { 'code' : code })
        r.raise_for_status()
        # verification doesn't actually return a yes/no, so log in again to determine state
        try:
            self.login()
        except:
            pass

    def query(self):
        if self.state == Session.STATE_NONE:
            raise Exception('General error')	# Shouldn't happen
        elif self.state == Session.STATE_INIT:
            self.login()
        elif self.state == Session.STATE_AUTH:
            raise VerificationRequired()
        r = self.session.get('https://companion.orerve.net/profile')

        if r.status_code != requests.codes.ok:
            self.dump(r)
        if r.status_code == requests.codes.forbidden:
            # Start again - maybe our session cookie expired?
            self.login()
            self.query()

        r.raise_for_status()
        try:
            data = json.loads(r.text)
        except:
            self.dump(r)
            raise ServerError()

        # Recording
        if __debug__:
            with open('%s.%s.%s.json' % (data['lastSystem']['name'].strip(), data['lastStarport']['name'].strip(), time.strftime('%Y-%m-%dT%H.%M.%S', time.localtime())), 'wt') as h:
                h.write(json.dumps(data, indent=2))

        return self.fixup(data)

    def close(self):
        self.state = Session.STATE_NONE
        try:
            self.session.cookies.save()
            self.session.close()
        except:
            pass
        self.session = None


    # Fixup anomalies in the recieved data
    def fixup(self, data):
        commodities = data.get('lastStarport') and data['lastStarport'].get('commodities') or []
        i=0
        while i<len(commodities):
            commodity = commodities[i]

            # Check all required numeric fields are present and are numeric
            # Catches "demandBracket": "" for some phantom commodites in ED 1.3
            for thing in ['buyPrice', 'sellPrice', 'demand', 'demandBracket', 'stock', 'stockBracket']:
                if not isinstance(commodity.get(thing), numbers.Number):
                    if __debug__: print 'Invalid "%s":"%s" (%s) for "%s"' % (thing, commodity.get(thing), type(commodity.get(thing)), commodity.get('name', ''))
                    break
            else:
                if not categorymap.get(commodity['categoryname'], True):	# Check marketable
                    pass
                elif not commodity.get('categoryname', '').strip():
                    if __debug__: print 'Missing "categoryname" for "%s"' % commodity.get('name', '')
                elif not commodity.get('name', '').strip():
                    if __debug__: print 'Missing "name" for a commodity in "%s"' % commodity.get('categoryname', '')
                elif not commodity['demandBracket'] in range(4):
                    if __debug__: print 'Invalid "demandBracket":"%s" for "%s"' % (commodity['demandBracket'], commodity['name'])
                elif not commodity['stockBracket'] in range(4):
                    if __debug__: print 'Invalid "stockBracket":"%s" for "%s"' % (commodity['stockBracket'], commodity['name'])
                else:
                    # Rewrite text fields
                    commodity['categoryname'] = categorymap.get(commodity['categoryname'].strip(),
                                                                commodity['categoryname'].strip())
                    commodity['name'] = commoditymap.get(commodity['name'].strip(),
                                                         commodity['name'].strip())

                    # Force demand and stock to zero if their corresponding bracket is zero
                    # Fixes spurious "demand": 1 in ED 1.3
                    if not commodity['demandBracket']:
                        commodity['demand'] = 0
                    if not commodity['stockBracket']:
                        commodity['stock'] = 0

                    # We're good
                    i+=1
                    continue

            # Skip the commodity
            commodities.pop(i)

        if data['lastStarport'].get('ships'):
            for ship in data['lastStarport']['ships'].get('shipyard_list', {}).values() + data['lastStarport']['ships'].get('unavailable_list', []):
                if shipmap.get(ship['name']):
                    ship['name'] = shipmap[ship['name']]

        return data

    def dump(self, r):
        if __debug__:
            print 'Status\t%s'  % r.status_code
            print 'URL\t%s' % r.url
            print 'Headers\t%s' % r.headers
            print ('Content:\n%s' % r.text).encode('utf-8')
