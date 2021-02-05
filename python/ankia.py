#!/usr/bin/env python
import re
import sys
import json
import urllib.request

from pprint import pprint
def pvars(_extra:dict=None):
    """Also pass pp(vars()) from inside a def"""
    _vars = { **globals(), **locals(), **(_extra if _extra else {}) }
    pprint([ [k,_vars[k]] for k in _vars if re.match(r'[a-z]', k)])



def request(action, **params):
    return {'action': action, 'params': params, 'version': 6}

def invoke(action, **params):
    requestJson = json.dumps(request(action, **params)).encode('utf-8')
    response = json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8765', requestJson)))
    if len(response) != 2:
        raise Exception('response has an unexpected number of fields')
    if 'error' not in response:
        raise Exception('response is missing required error field')
    if 'result' not in response:
        raise Exception('response is missing required result field')
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']

deck='nl'
term=len(sys.argv) > 1 and sys.argv[1]
term=term or input("Gimme: ")
wild=f'*{term}*'
result = invoke('findCards', query=f'deck:{deck} front:{term}')
if not result:
    print("No exact match")
    result = invoke('findCards', query=f'deck:{deck} front:{wild}')

for card_id in result:
    cardsInfo = invoke('cardsInfo', cards=[card_id])
    card = cardsInfo[0]
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    print(f)
    print(b)

# If not present, search http://www.woorden.org/woord/%s (exact match, URL encoded)

# Start from ... <div class="slider-wrap" style="padding:10px">
# But not including © (not always present)