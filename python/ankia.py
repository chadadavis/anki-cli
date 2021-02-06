#!/usr/bin/env python
import re
import sys
import json
import urllib.request
import re

from pprint import pprint
def pvars(_extra:dict=None):
    """Also pass pp(vars()) from inside a def"""
    _vars = { **globals(), **locals(), **(_extra if _extra else {}) }
    pprint([ [k,_vars[k]] for k in _vars if re.match(r'[a-z]', k)])

# https://foosoft.net/projects/anki-connect/

# TODOs
# startup options / CLI options:
# # support a CLI option to search Back field (eg for idioms), and highlight matches
# # CLI option to sync on exit, via GUI (if new cards successfully added)

# REPL options
# # open the GUI for the current search query in browse mode (to edit/append cards)
# # https://github.com/FooSoft/anki-connect/blob/master/actions/graphical.md
#
# when checking for an existing word, print stats on age (use case: "why don't I remember this one? still new?")
# See cardInfo response fields: interval, due, reps, lapses, left, (ord? , type?)
# Lookup defs of fields, or just compare to what's displayed in card browser for an example card

# Send to RTM as a fallback, when I need more research? (better as a separate thing, don't integrate it)
# Or just a simple queue in the CLI, that stays pending, keep printing it out
# ie just an option to defer adding a definition until later (in the run)
# That would be for when woorden.nl has no results, for example.


def request(action, **params):
    return {'action': action, 'params': params, 'version': 6}

def invoke(action, **params):
    requestJson = json.dumps(request(action, **params)).encode('utf-8')
    response = json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8765', requestJson)))
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']

deck='nl'
term=len(sys.argv) > 1 and sys.argv[1]
term=term or input("Find or create term: ")
wild=f'*{term}*'
result = invoke('findCards', query=f'deck:{deck} front:{term}')
if not result:
    print("No exact match. Wildcard matches:")
    result = invoke('findCards', query=f'deck:{deck} front:{wild}')

for card_id in result:
    cardsInfo = invoke('cardsInfo', cards=[card_id])
    card = cardsInfo[0]
    f = card['fields']['Front']['value']
    # print(f)
    b = card['fields']['Back']['value']
    # TODO render HTML another way? eg as Markdown instead?
    b = re.sub(r'&nbsp;', ' ', b)
    # Replace opening tags with a newline
    b = re.sub(r'\<[^/].*?\>', '\n', b)
    # Remove remaining tags
    b = re.sub(r'\<.*?\>', '', b)
    # Max 2x newlines in a row
    b = re.sub(r'\n{3,}', '\n\n', b)
    print(b)

if not result:
    url = 'http://www.woorden.org/woord/' + term
    print(f"No matches. Fetching: {url}")
    # This does an exact match for {term}
    content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    # print(content)

# TODO extract smarter
# Start from ... <div class="slider-wrap" style="padding:10px">
# But not including © (not always present)

    match = re.search(f"(\<h2.*?{term}.*?)Kernerman Dictionaries", content)
    # TODO validate match is not None
    definition = match.group()
    # Duplicate check (deck scope) enabled by default
    note = {
        'deckName': 'nl',
        'modelName': 'Basic-nl',
        'fields': { 'Front': term, 'Back': definition },
        }
    # print(note)

    card_id = invoke('addNote', note=note)

    # TODO make a separate def for displaying a card, rendered
    print(card_id)
    cardsInfo = invoke('cardsInfo', cards=[card_id])
    card = cardsInfo[0]
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    print(f)
    print(b)

# sync on exit. Note, this will focus the GUI
# TODO, add CLI option to enable/disable
# invoke('sync')