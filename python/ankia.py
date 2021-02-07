#!/usr/bin/env python
import sys
import urllib.request
import json
import re
from optparse import OptionParser

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
    response = json.load(urllib.request.urlopen(
        urllib.request.Request('http://localhost:8765', requestJson)))
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']


parser = OptionParser()
parser.add_option("-y", "--sync", dest="sync",
                  action="store_true", help="Sync DB to Anki Web and exit")
parser.add_option("-w", "--wild", dest="wild", action="store_true",
                  help="Do wildcard search (of card front)")
parser.add_option("-b", "--back", dest="back", action="store_true",
                  help="Do (wildcard) search of card back")

(opt, args) = parser.parse_args()
if opt.sync:
    invoke('sync')
    exit()

# Check remaining CLI args for term(s)
term = len(args) and ' '.join(args)
term = term or input("Find or create term: ")
deck = 'nl'
# TODO for searching, can't have a ' ' char, for some reason,
# but we also don't want to the newly created 'front' field to have '_' in it
# So make a separate search_term with '_' in it, and maybe also canonicalize whitespace here
search_term = re.sub(r' ', '_', term)
wild = f'*{search_term}*'
field = 'front'
result_exact = invoke('findCards', query=f'deck:{deck} {field}:{term}')
# Keep track of whether this card already exists
results = result_exact

# TODO CLI option to also search wildcard, even if exact match
if not results or opt.wild:
    print("Searching for wildcard matches:")
    # No need to append / prepend, because the wildcard match will include any exact match
    results = invoke('findCards', query=f'deck:{deck} {field}:{wild}')

# TODO CLI option to also search definitions, even if prev match
if not results or opt.back:
    print("No matches. Searching in definitions:")
    field = 'back'
    # Prepend, so that front matches / exact matches are at the bottom of the screen output
    results = invoke(
        'findCards', query=f'deck:{deck} {field}:{wild}') + results

# TODO wrap this for loop in a while/REPL
# TODO make a CLI option to delete (or edit?) a card by ID, for debugging
# That could just be part of the REPL after rendering a (set of?) card
for card_id in results:
    cardsInfo = invoke('cardsInfo', cards=[card_id])
    card = cardsInfo[0]
    print('=' * 80)
    f = card['fields']['Front']['value']

    # TODO warn when f contains HTML, and prompt to open in browser, to clean it?
    # But I can't see it in the GUI, since WYSIWYG
    # Auto replace, and use the updateNoteFields API? (after prompting)
    # https://github.com/FooSoft/anki-connect/blob/master/actions/notes.md

    # TODO highlight 'term' in output (console colors). Use colorama
    LTYELLOW = "\033[1;33m"
    LTRED = "\033[1;31m"
    NOSTYLE = "\033[0;0m"
    f = re.sub(term, f"{LTRED}{term}{NOSTYLE}", f)
    print(f)

    b = card['fields']['Back']['value']

    # TODO render HTML another way? eg as Markdown instead?
    b = re.sub(r'&nbsp;', ' ', b)
    # Remove tags that are usually in the phonetic markup
    b = re.sub(r'\<\/?a.*?\>', '', b)
    # Replace opening tags with a newline, since usually a new section
    b = re.sub(r'\<[^/].*?\>', '\n', b)
    # Remove remaining tags
    b = re.sub(r'\<.*?\>', '', b)
    # Max 2x newlines in a row
    b = re.sub(r'\n{3,}', '\n\n', b)

    # TODO highlight 'term' in output (console colors). Use colorama
    LTYELLOW = "\033[1;33m"
    LTRED = "\033[1;31m"
    NOSTYLE = "\033[0;0m"
    b = re.sub(term, f"{LTRED}{term}{NOSTYLE}", b)
    print(b)

# TODO if not opt.fetch (make it default to True, but allow --no-fetch to disable ?)
# Or better to prompt, if we're making a REPL ?
if not result_exact:
    url = 'http://www.woorden.org/woord/' + term
    print(f"No exact match. Fetching: {url}")
    # This service does an exact match for {term}
    content = urllib.request.urlopen(
        urllib.request.Request(url)).read().decode('utf-8')
    # TODO find something Devel::Comments to enable/disable debug mode printing

    # TODO extract smarter. Check DOM parsing libs
    match = re.search(f"(\<h2.*?{term}.*?)(?=&copy|Bron:)", content)
    if not match:
        print("No matches.")
        exit()  # TODO wrap this in a def and just return / raise exception
    definition = match.group()
    # Note, duplicate check (deck scope) enabled by default
    note = {
        'deckName': 'nl',
        'modelName': 'Basic-nl',
        'fields': {'Front': term, 'Back': definition},
    }
    card_id = invoke('addNote', note=note)
    print(f"Added card: {card_id}")
    # TODO call def to fetch and display this newly added exact match
