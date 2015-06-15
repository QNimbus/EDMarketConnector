# Export to EDDN

import hashlib
import json
import numbers
import requests
from platform import system
from sys import platform
import time

from config import applongname, appversion, config

upload = 'http://eddn-gateway.elite-markets.net:8080/upload/'

bracketmap = { 1: 'Low',
               2: 'Med',
               3: 'High', }

def export(data):

    def send(msg):
        r = requests.post(upload, data=json.dumps(msg))
        if __debug__ and r.status_code != requests.codes.ok:
            print 'Status\t%s'  % r.status_code
            print 'URL\t%s'  % r.url
            print 'Headers\t%s' % r.headers
            print ('Content:\n%s' % r.text).encode('utf-8')
        r.raise_for_status()

    querytime = config.getint('querytime') or int(time.time())

    header = {
        'uploaderID'      : config.getint('anonymous') and hashlib.md5(data['commander']['name'].strip().encode('utf-8')).hexdigest() or data['commander']['name'].strip(),
        'softwareName'    : '%s [%s]' % (applongname, platform=='darwin' and "Mac OS" or system()),
        'softwareVersion' : appversion,
    }

    commodities = []
    for commodity in data['lastStarport'].get('commodities', []):
        commodities.append({
            'name'      : commodity['name'],
            'buyPrice'  : commodity['buyPrice'],
            'supply'    : int(commodity['stock']),
            'sellPrice' : commodity['sellPrice'],
            'demand'    : int(commodity['demand']),
        })
        if commodity['stockBracket']:
            commodities[-1]['supplyLevel'] = bracketmap[commodity['stockBracket']]
        if commodity['demandBracket']:
            commodities[-1]['demandLevel'] = bracketmap[commodity['demandBracket']]

    if data['lastStarport']['commodities']:
        send({
            '$schemaRef' : 'http://schemas.elite-markets.net/eddn/commodity/2',
            'header'     : header,
            'message'    : {
                'systemName'  : data['lastSystem']['name'].strip(),
                'stationName' : data['lastStarport']['name'].strip(),
                'timestamp'   : time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(querytime)),
                'commodities' : commodities,
            }
        })

    send({
        '$schemaRef' : 'http://schemas.elite-markets.net/eddn/outfitting/1',
        'header'     : header,
        'message'    : {
            'systemName'  : data['lastSystem']['name'].strip(),
            'stationName' : data['lastStarport']['name'].strip(),
            'timestamp'   : time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(querytime)),
            'modules'     : [int(k) for k,v in data['lastStarport'].get('modules', {}).iteritems() if v['category'] not in ['decal', 'paintjob']],
        }
    })

    # Shipyard data is only guaranteed present if user has visited the shipyard. Otherwise omit the "ships" property.
    if data['lastStarport'].get('ships'):
        send({
            '$schemaRef' : 'http://schemas.elite-markets.net/eddn/shipyard/1',
            'header'     : header,
            'message'    : {
                'systemName'  : data['lastSystem']['name'].strip(),
                'stationName' : data['lastStarport']['name'].strip(),
                'timestamp'   : time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(querytime)),
                'ships'       : [ship['name'] for ship in data['lastStarport']['ships'].get('shipyard_list', {}).values() + data['lastStarport']['ships'].get('unavailable_list', [])],
                }
            })
