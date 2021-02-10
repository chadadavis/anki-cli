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

# REPL options (interactive mode)
# # open the GUI for the current search query in browse mode (to edit/append cards)
# # https://github.com/FooSoft/anki-connect/blob/master/actions/graphical.md
#
# when checking for an existing word, print stats on age (use case: "why don't I remember this one? still new?")
# See cardInfo response fields: interval, due, reps, lapses, left, (ord? , type?)
# Lookup defs of fields, or just compare to what's displayed in card browser for an example card

# Have a REPL option to 'f'etch the card I'm viewing, if it exists locally, show them for comparison
# Have a REPL option to 'r'eplace the local card with the fetched.

# Send to RTM as a fallback, when I need more research? (better as a separate thing, don't integrate it)
# Or just a simple queue in the CLI, that stays pending, keep printing it out
# ie just an option to defer adding a definition until later (in the run)
# That would be for when woorden.nl has no results, for example.

# Is this even worth it? What's the value?
# Cleanup (does this only apply to the ones that aren't already HTML?)
# Every occurrence of these words in a def (case sensitive) should be preceded by one/two newlines
# Use a negative look behind assertion?
# '(Uitspraak|Vervoegingen|Voorbeeld|Voorbeelden|Synoniem|Synoniem|Antoniem|Antoniemen): '
# Also newline before these: ' .*?\.(naamw|werkw|article|pronoun|...)\..*$' # how to match until line end?
# And also insert a newline before/after, to ease readability?
# And all `text wrapped in backticks as quotes` should be on it's own line
# Remove: 'Toon all vervoegingen'
# Also, remove/replace tab chars '	' in defs
# collapse 3+ newlines into 2 newlines everywhere

def request(action, **params):
    return {'action': action, 'params': params, 'version': 6}


def invoke(action, **params):
    requestJson = json.dumps(request(action, **params)).encode('utf-8')
    response = json.load(urllib.request.urlopen(
        urllib.request.Request('http://localhost:8765', requestJson)))
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']


def render(string, highlight=None):
    # TODO render HTML another way? eg as Markdown instead?
    string = re.sub(r'&nbsp;', ' ', string)
    # Remove tags that are usually in the phonetic markup
    string = re.sub(r'\<\/?a.*?\>', '', string)
    # Replace opening tags with a newline, since usually a new section
    string = re.sub(r'\<[^/].*?\>', '\n', string)
    # Remove remaining tags
    string = re.sub(r'\<.*?\>', '', string)
    # Max 2x newlines in a row
    string = re.sub(r'\n{3,}', '\n\n', string)
    if highlight:
        # TODO Use colorama
        LTYELLOW = "\033[1;33m"
        LTRED = "\033[1;31m"
        NOSTYLE = "\033[0;0m"
        string = re.sub(highlight, f"{LTRED}{highlight}{NOSTYLE}", string)

    return string


parser = OptionParser()
parser.add_option("-y", "--sync", dest="sync",
                  action="store_true", help="Sync DB to Anki Web and exit")
parser.add_option("-w", "--wild", dest="wild", action="store_true",
                  help="Do wildcard search (of card front)")
parser.add_option("-b", "--back", dest="back", action="store_true",
                  help="Do (wildcard) search of card back")
parser.add_option("-f", "--fetch", dest="fetch", action="store_true",
                  help="Fetch defnition, even if card already exists")
parser.add_option("-a", "--add", dest="add", action="store_true",
                  help="Add any fetched defnition")

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
result_exact = invoke('findCards', query=f'deck:{deck} {field}:{search_term}')
# Keep track of whether this card already exists
results = result_exact

# TODO CLI option to also search wildcard, even if exact match
if not results or opt.wild:
    # print("Searching for wildcard matches:")
    # No need to append / prepend, because the wildcard match will include any exact match
    results = invoke('findCards', query=f'deck:{deck} {field}:{wild}')

# TODO CLI option to also search definitions, even if prev match
if not results or opt.back:
    # print("Searching in definitions:")
    field = 'back'
    # No need to append / prepend, because the wildcard match will include any exact match
    results = invoke('findCards', query=f'deck:{deck} {field}:{wild}')

# TODO wrap this for loop in a while/REPL
# TODO make a CLI option to delete (or edit?) a card by ID, for debugging
# That could just be part of the REPL after rendering a (set of?) card
for card_id in results:
    cardsInfo = invoke('cardsInfo', cards=[card_id])
    card = cardsInfo[0]

    # TODO warn when f contains HTML, and prompt to open in browser, to clean it?
    # But I can't see it in the GUI, since WYSIWYG
    # Auto replace, and use the updateNoteFields API? (after prompting)
    # https://github.com/FooSoft/anki-connect/blob/master/actions/notes.md
    print('=' * 80)
    f = card['fields']['Front']['value']
    print(render(f, highlight=term))

    b = card['fields']['Back']['value']
    print(render(b, highlight=term))

# TODO if not opt.fetch (make it default to True, but allow --no-fetch to disable ?)
# Or better to prompt, if we're making a REPL ?
if not result_exact or opt.fetch:
    url = 'http://www.woorden.org/woord/' + re.sub(' ', ' ', term)
    print('=' * 80)
    print(f"Fetching: {url}")
    # This service does an exact match for {term}
    content = urllib.request.urlopen(
        urllib.request.Request(url)).read().decode('utf-8')
    # TODO find something Devel::Comments to enable/disable debug mode printing

    # TODO extract smarter. Check DOM parsing libs
    # Pages in different formats
    # encyclo:     https://www.woorden.org/woord/hangertje
    # urlencoding: https://www.woorden.org/woord/op zich
    # none:        https://www.woorden.org/woord/spacen
    # ?:           https://www.woorden.org/woord/backspacen #
    # &copy:       http://www.woorden.org/woord/zien
    # Bron:        http://www.woorden.org/woord/glashelder
    match = re.search(f"(\<h2.*?{term}.*?)(?=&copy|Bron:|\<div|\<\/div)", content)
    # match = re.search(f'(\<h2.*?{term}.*?)(?=div)', content) # This should handle all cases (first new/closing div)
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
    print(render(definition, highlight=term))

    if opt.add:
        card_id = invoke('addNote', note=note)
        print(f"Added card: {card_id} :")
        # TODO call def to search and display this newly added card (to verify)
