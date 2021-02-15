#!/usr/bin/env python
import urllib.request
import urllib.parse
import json
import re
from optparse import OptionParser

# TODOs

# REPL options (interactive mode)
# # open the GUI for the current search query in browse mode (to edit/append cards)
# # https://github.com/FooSoft/anki-connect/blob/master/actions/graphical.md
#
# when checking for an existing word, print stats on age (use case: "why don't I remember this one? still new?")
# See cardInfo response fields: interval, due, reps, lapses, left, (ord? , type?)
# Lookup defs of fields, or just compare to what's displayed in card browser for an example card

# TODO make a CLI/REPL option to delete (or edit?) a card (by ID), for debugging
# That could just be part of the REPL after rendering a (set of?) card

# Have a REPL option to 'f'etch the card I'm viewing, if it exists locally, show them for comparison
# Have a REPL option to 'r'eplace the local card with the fetched.

# REPL: option to open [G]oogle if no results found in online dictionary
# And then open GUI dialog to add a new card?

# Don't search 'B'ack by default, but make it a REPL option.
# Search for 'W'ild by default if no exact match?
# For both: Pipe it into $PAGER by default

# Send to RTM as a fallback, when I need more research? (better as a separate thing, don't integrate it)
# Or just a simple queue in the CLI, that stays pending, keep printing it out
# ie just an option to defer adding a definition until later (in the run)
# That would be for when woorden.nl has no results, for example.


# Is this even worth it? What's the value?
# Cleanup (does this only apply to the ones that aren't already HTML?)

# Also note that some of these cleanups are only for display (rendering HTML)
# And others should be permanently saved (removing junk)

# Remove: 'Toon all vervoegingen'
# Every occurrence of these words should be preceded by one/two newlines
# Use a negative look behind assertion? Or just cleanup 3+ newlines later
# (Could also put these bold/colored since they're headings, or maybe dim them since they're only structure not content)
# '(Uitspraak|Vervoegingen|Voorbeeld|Voorbeelden|Synoniem|Synoniemen|Antoniem|Antoniemen): '
# Also newline before these: '(?<=\s+)\S*(naamw|werkw|article|pronoun|...).*$'
# Lookup how to match to end of newline eg: '?m:(?<=\s+)\S*(naamw|werkw|article|pronoun|woord|...).*$'
# And also insert a newline before/after, to ease readability?
# Numbered section on its' own line? '?m:^([0-9]+)\)\s*'
# And all `text wrapped in backticks as quotes` should be on it's own line
# Also, remove/replace tab chars '	' (ever needed?)
# collapse 3+ newlines into 2 newlines everywhere
# Bug: I cannot search for uitlaatgassen , since the card only contains: Verbuigingen: uitlaatgas|sen (split)
# Remove those too? But only when it's in 'Verbuigingen: ...' (check that it's on the same line)
# If I prompt with a diff, then I don't need to be so careful, just prompt to remove all of them, show diff
# Collapse multiple spaces (in between newlines)?
# Remove whitespace at the start of a line
# If the back begins with the term, delete the term (multi-word)
# Insert a - before names of topical fields:
# culinair medisch informeel

# search for front:*style* to find cards w html on the front to clean (but then how to strip them ?)
# When cleaning, having a dry-mode to show what would change before saving
# Show a diff, so that I can see what chars changed where
# Warn before any mass changes to first do an export (via API?) See .config/backups/

# TODO Use colorama, or at least refactor into functions by intent (print_info vs print_diff etc)
# TODO look for log4j style console logging/printing (with colors)
LTYELLOW = "\033[1;33m"
LTRED = "\033[1;31m"
NOSTYLE = "\033[0;0m"

def request(action, **params):
    """Send a request to Anki desktop via anki_connect HTTP server addon

    https://foosoft.net/projects/anki-connect/
    """
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
        string = re.sub(highlight, f"{LTRED}{highlight}{NOSTYLE}", string)
    return string


def search_anki(term, deck='nl', wild=False, field='front', ):
    # TODO save global settings like 'nl' and 'Basic-nl' externally?
    # can't have a ' ' char, for some reason,
    search_term = re.sub(r' ', '_', term) # For Anki searches
    if field == 'back':
        wild = True
    if wild:
        search_term = f'*{search_term}*'
    card_ids = invoke('findCards', query=f'deck:{deck} {field}:{search_term}')
    return card_ids


def info_print(content=""):
    print()
    print(LTYELLOW, end='')
    print('=' * 80)
    print(content)
    print(NOSTYLE, end='')


def search_google(term):
    query_term = urllib.parse.quote(term) # For web searches
    print(LTYELLOW, end='')
    print()
    print('=' * 80)
    print(f"https://google.com/search?q={query_term}")
    print(NOSTYLE, end='')
    # TODO open in browser, via xdg in background process, disowned


def search_woorden(term, url='http://www.woorden.org/woord/'):
    # TODO generalize this for other online dictionaries?
    # eg parameterize base_url (with a %s substitute, and the regex ?)
    """The term will be appended to the url"""
    query_term = urllib.parse.quote(term) # For web searches
    url = url + query_term
    print(LTYELLOW, end='')
    print('=' * 80)
    # TODO use something log log4j with INFO level here, or Devel::Comments like?
    print(f"Fetching: {url}")
    print(NOSTYLE, end='')
    content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    # Pages in different formats, for testing:
    # encyclo:     https://www.woorden.org/woord/hangertje
    # urlencoding: https://www.woorden.org/woord/op zich
    # none:        https://www.woorden.org/woord/spacen
    # ?:           https://www.woorden.org/woord/backspacen #
    # &copy:       http://www.woorden.org/woord/zien
    # Bron:        http://www.woorden.org/woord/glashelder

    # TODO extract smarter. Check DOM parsing libs
    match = re.search(f"(\<h2.*?{term}.*?)(?=&copy|Bron:|\<div|\<\/div)", content)
    # match = re.search(f'(\<h2.*?{term}.*?)(?=div)', content) # This should handle all cases (first new/closing div)
    if not match:
        return
    definition = match.group()
    return definition


def get_card(id):
    cardsInfo = invoke('cardsInfo', cards=[id])
    card = cardsInfo[0]
    return card


def render_card(card, term=None):
    # TODO when front contains HTML, warn, dump it, and clean it and show diff
    # Auto replace, and use the updateNoteFields API? (after prompting)
    # https://github.com/FooSoft/anki-connect/blob/master/actions/notes.md
    print(LTYELLOW, end='')
    print('=' * 80)
    print(NOSTYLE, end='')
    f = card['fields']['Front']['value']
    print(render(f, highlight=term))
    b = card['fields']['Back']['value']
    print(render(b, highlight=term))


def search(term):
    # Search Anki: exact, then wildcard (front), then the back, then defer to Google
    try:
        # TODO enable readline?
        # TODO keep looping if term is empty
        term = term or input("Search: ")
    except:
        return
    card_ids = search_anki(term)
    card_ids = card_ids or search_anki(term, wild=True)
    card_ids = card_ids or search_anki(term, field='back')
    return card_ids


def add_card(term, definition, deck='nl'):
    # TODO save global settings like 'nl' and 'Basic-nl' externally?
    note = {
        'deckName': 'nl',
        'modelName': 'Basic-nl',
        'fields': {'Front': term, 'Back': definition},
    }
    # Note, duplicate check (deck scope) enabled by default
    card_id = invoke('addNote', note=note)
    # TODO color INFO print
    print(f"Added card: {card_id}")

    # TODO call def to search, and render, this newly added card (to verify it's findable)
    # Seems to be a race condition after adding a new card, before we can get_card()
    card_id = search(term)[0]

    card = get_card(card_id)
    # print("card:\n")
    # print(card)
    
    render_card(card, term)



def sync():
    invoke('sync')


def main():

    # Some menu options are global (sYnc) and others act on the displayed result
    # TODO remember the last query_term/card/note/content/card_id displayed

    # Leave the search field always visible, editable
    # TODO replace the search field with the last query, so that it's easy to edit/re-search
    # Or use readline?

    # Use Ctrl-A combos for Add, etc, so that the search field is always just for searching?
    menu = [
        [ 's', '[S]earch', search],
        # '[S]earch': search,
        # 'Wild'  : ...,
        # 'Back'  : ...,
        # 'Add'   : add_card,
        # 'sYnc'  : sync,
        # ' '     : ..., # next_result
        # }
    ]

    # Menu loop
    while True:
        # try:
        #     # TODO build this from the dispatch table
        #     # cmd = input("[S]earch [A]dd S[y]nc [Q]uit ")
        #     # term = input("Search: ")
        # except:
        #     return

        # TODO colored INFO print
        try:
            term = input(f"Search: ")
        except:
            print()
            return
        card_ids = search(term)
        exact = False
        c = -1
        for card_id in card_ids:
            c += 1
            if c > 0:
                try:
                    # TODO coloured info print (maybe a grey colour, or make content brighter)
                    input(f"{c} of {len(card_ids)}\n")
                except:
                    print()
                    break

            card = get_card(card_id)
            if card['fields']['Front']['value'] == term:
                exact = True
            render_card(card, term)
            # TODO options for eg edit a single card?


        if exact:
            continue
        # No local results. Now search web services:
        try:
            # TODO INFO print
            input("No exact match. Fetch?\n")
        except:
            print()
            continue
        definition = search_woorden(term)
        if definition:
            print(render(definition, highlight=term))
            try:
                input(f"Add?\n")
            except:
                print()
                continue
            add_card(term, definition)
            continue

        search_google(term)


if __name__ == "__main__":
    main()

