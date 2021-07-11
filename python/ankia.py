#!/usr/bin/env python
from optparse import OptionParser
import json
import os
import re
import readchar
import readline # Not referenced, but used by input()
import sys
import time
import urllib.parse
import urllib.request

# TODO

# REPL options (interactive mode)
# # open the GUI for the current search query in browse mode (to edit/append cards)
# # https://github.com/FooSoft/anki-connect/blob/master/actions/graphical.md
#
# when checking for an existing word, print stats on age (use case: "why don't I remember this one? still new?")
# See cardInfo response fields: interval, due, reps, lapses, left, (ord? , type?)
# Lookup defs of fields, or just compare to what's displayed in card browser for an example card

# Anki Add: figure out how to package deps (eg readchar) and test it again after removing local install of readchar

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
# Remove: tweede betekenisomschrijving
# If the back begins with the term, delete the term (multi-word)

# newline before these: '(?<=\s+)\S*(naamw|werkw|article|pronoun|...).*$'
# Lookup how to match to end of newline eg: '?m:(?<=\s+)\S*(naamw|werkw|article|pronoun|woord|...).*$'
# And also insert a newline before/after, to ease readability?

# Numbered section on its' own line? '?m:^([0-9]+)\)\s*'
# And all `text wrapped in backticks as quotes` should be on it's own line
# Also, remove/replace tab chars '	' (ever needed?)


# Bug: I cannot search for uitlaatgassen , since the card only contains: Verbuigingen: uitlaatgas|sen (split)
# Remove those too? But only when it's in 'Verbuigingen: ...' (check that it's on the same line)

# If I prompt with a diff, then I don't need to be so careful, just prompt to remove all of them, show diff

# Anki add: when populating readline with seen cards, the front field should be stripped of HTML, like the render function does already
# search for front:*style* to find cards w html on the front to clean (but then how to strip them ?)

# When cleaning, having a dry-mode to show what would change before saving
# Show a diff, so that I can see what chars changed where
# Warn before any mass changes to first do an export (via API?) See .config/backups/

# Anki Add, also parse out the spellcheck suggestions on the fetched page (test: hoiberg) and enable them to be fetched by eg assigning them numbers (single key press?)

# Anki add: pipe each display through less/PAGER --quit-if-one-screen
# https://stackoverflow.com/a/39587824/256856
# https://stackoverflow.com/questions/6728661/paging-output-from-python/18234081

# TODO at least refactor into functions by intent (print_info vs print_diff etc)
# TODO look for log4j style console logging/printing (with colors)

# Color codes: https://stackoverflow.com/a/33206814/256856
GREY      = "\033[0;02m"
YELLOW    = "\033[0;33m"
LT_YELLOW = "\033[1;33m"
LT_RED    = "\033[1;31m" # the '1;' makes it bold as well
PLAIN     = "\033[0;0m"

def request(action, **params):
    """Send a request to Anki desktop via anki_connect HTTP server addon

    https://foosoft.net/projects/anki-connect/
    """
    return {'action': action, 'params': params, 'version': 6}


def launch_anki():
    info_print('Launching anki ...')
    os.system('anki >/dev/null 2>&1 &')


def invoke(action, **params):
    reqJson = json.dumps(request(action, **params)).encode('utf-8')
    req = urllib.request.Request('http://localhost:8765', reqJson)
    response = json.load(urllib.request.urlopen(req))
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']


def render(string, *, highlight=None, front=None):
    # This is just makes the HTML string easier to read on the terminal console
    # This changes are not saved in the cards

    # TODO render HTML another way? eg as Markdown instead?

    # HTML-specific:
    string = re.sub(r'&nbsp;', ' ', string)
    string = re.sub(r'&[gl]t;', ' ', string)
    string = re.sub(r'&quot;', '\'', string)

    # Remove tags that are usually in the phonetic markup
    string = re.sub(r'\<\/?a.*?\>', '', string)

    # NL-specific (or specific to woorden.org)
    # Segregate topical category names e.g. 'informeel'
    # Definitions in plain text cards will often have the tags already stripped out.
    # So, also use this manually curated list.
    categories = [
        *[]
        ,'\S+ologie'
        ,'\S+kunde'
        ,'algemeen'
        ,'anatomie'
        ,'architectuur'
        ,'commercie'
        ,'constructie'
        ,'culinair'
        ,'defensie'
        ,'educatie'
        ,'electronica'
        ,'financieel'
        ,'formeel'
        ,'geschiedenis'
        ,'informatica'
        ,'informeel'
        ,'juridisch'
        ,'kunst'
        ,'landbouw'
        ,'medisch'
        ,'ouderwets'
        ,'religie'
        ,'speelgoed'
        ,'sport'
        ,'spreektaal'
        ,'technisch'
        ,'transport'
        ,'vulgair'
    ]

    # If we still have the HTML tags, then we can see if this category is new to us.
    match = re.search(r'<sup>(.*?)</sup>', string)
    category = None
    if match:
        category = match.group(1)
        # Highlight it, if it's new, so you can update the 'categories' list above.
        # TODO find a way to save those changes back into the card definition/back.
        if category in categories:
            string = re.sub(r'<sup>(.*?)</sup>', '[\g<1>]', string)
        else:
            string = re.sub(r'<sup>(.*?)</sup>', f'[{LT_YELLOW}\g<1>{PLAIN}]', string)

    # HTML-specific:
    # Replace opening tags with a newline, since usually a new section
    string = re.sub(r'\<[^/].*?\>', '\n', string)
    # Remove remaining tags
    string = re.sub(r'\<.*?\>', '', string)

    # Segregate pre-defined topical category names
    # Wrap in '[]', the names of topical fields.
    # (when it's last (and not first) on the line)
    categories_re = '|'.join(categories)
    string = re.sub(f'(?m)(?<!^)\\s+({categories_re})$', ' [\g<1>]', string)

    # Non-HTML-specific:
    # Collapse sequences of space/tab chars
    string = re.sub(r'\t', ' ', string)
    string = re.sub(r' {2,}', ' ', string)

    # NL-specific (or specific to woorden.org)
    string = re.sub(r'Toon alle vervoegingen', '', string)
    # Ensure headings begin on their own line (also covers plural forms, eg "Synoniemen")
    # TODO Also put these bold/colored/dimmed since they're headings?
    string = re.sub(r'(?<!\n)(Uitspraak|Vervoeging|Voorbeeld|Synoniem|Antoniem)', '\n\g<1>', string)
    # Remove seperators in plurals (eg in the section: "Verbuigingen")
    # (note, just for display here; this doesn't help with matching)
    string = re.sub(r'\|', '', string)

    # TODO how to match (either direction) verdwaz(en) <=> verdwaas(de)
    #      Look into stemming libraries? (Could be a useful Addon for Anki too)
    #      And one that also maps irregular verbs? liggen => gelegen ?

    # TODO look into NL spellcheck libs / services (Google?)

    # NL-specific: Newlines before example `phrases in backticks`
    # (but not *after*, else you'd get single commas on a line, etc)
    # (using a negative lookbehind assertion here)
    string = re.sub(r'(?<!\n)(`.*?`)', '\n\g<1>', string)

    # Max 2x newlines in a row
    string = re.sub(r'\n{3,}', '\n\n', string)

    # Delete leading/trailing space per line
    string = re.sub(r'(?m)^ +', '', string)
    string = re.sub(r'(?m) +$', '', string)

    # DE-specific: Newlines before each definition on the card, marked by eg: 2.
    # string = re.sub(r';?\s*(\d+\.)', '\n\n\g<1>', string)
    # And sub-definitions, marked by eg: b)
    string = re.sub(r';?\s+([a-z]\)\s+)', '\n  \g<1>', string)
    # Split sub-sub-definitions onto newlines
    # TODO: BUG: this breaks text in nl deck like '... [meteorologie]' for some reason
    # string = re.sub(r'\s*\;\s*', '\n     ', string)

    # Delete leading/trailing space on the entry as a whole
    string = re.sub(r'^\s+', '', string)
    string = re.sub(r'\s+$', '', string)
    # Canonical newline to start/end
    string = "\n" + string + "\n"

    if front:
        # Strip the term from the start of the definition, if present (redundant for infinitives, adjectives, etc)
        string = re.sub(f'^\s*{front}\s*', '', string)
        # And add it back canonically
        string = YELLOW + front + PLAIN + '\n' + string

    if highlight:
        highlight = re.sub(r'[.]', '\.', highlight)
        highlight = re.sub(r'[_]', '.', highlight)
        highlight = re.sub(r'[*]', r'\\w*', highlight)


        # NL-specific
        # Hack stemming
        suffixes = 'ende|end|en|de|d|ste|st|ten|te|t|sen|zen|ze|jes|je|es|e|\'?s'
        highlight = re.sub(f'({suffixes})$', '', highlight)
        highlight = f"(ge)?{highlight}({suffixes})?"

        # Collapse double letters in the search term
        # eg ledemaat => ledema{1,2}t can now also match 'ledematen'
        # This is because the examples in the 'back' field will include declined forms
        highlight = re.sub(r'(.)\1', '\g<1>{1,2}', highlight)

        # Case insensitive highlighting
        # Note, the (?i:...) doesn't create a group.
        # That's why ({highlight}) needs it's own parens here.
        string = re.sub(f"(?i:({highlight}))", f"{LT_RED}\g<1>{PLAIN}", string)

        # TODO Highlight accent-insensitive? (Because accents don't change the semantics in NL)
        # eg exploit should find geëxploiteerd
        # It should be possible with non-combining mode: nc:geëxploiteerd but doesn't seem to work
        # https://docs.ankiweb.net/#/searching
        # Probably need to:
        # Apply search to a unidecode'd copy.
        # Then record all the patch positions, as [start,end) pairs,
        # then, in reverse order (to preserve position numbers), wrap formatting markup around matches

    return string


def search_anki(term, *, deck, wild=False, field='front', browse=False):

    # If term contains whitespace, either must quote the whole thing, or replace spaces:
    search_term = re.sub(r' ', '_', term) # For Anki searches

    # Collapse double letters into a disjunction, eg: (NL-specific)
    # This implies that the user should, when in doubt, use double chars in the query
    # deck:nl (front:dooen OR front:doen)
    # or use a re: (but that doesn't seem to work)
    # TODO BUG: this isn't a proper Combination (maths), so it misses some cases

    terms = [search_term]
    while True:
        next_term = re.sub(r'(.)\1', '\g<1>', search_term, count=1)
        if next_term == search_term:
            break
        terms += [next_term]
        search_term = next_term

    if field == 'back':
        wild = True
    if wild:
        terms = map(lambda x: f'*{x}*', terms)
    terms = map(lambda x: field + ':' + x, terms)
    query = f'deck:{deck} (' + ' OR '.join([*terms]) + ')'
    # info_print(f'query:{query}')

    if browse:
        card_ids = invoke('guiBrowse', query=query)
    else:
        card_ids = invoke('findCards', query=query)
    return card_ids


def info_print(*values):
    # TODO Use colorama
    print(GREY, end='')
    # TODO set to the whole width of the terminal?
    print('_' * 80)
    print(*values)
    print(PLAIN, end='')
    if values:
        print()


def search_google(term):
    query_term = urllib.parse.quote(term) # For web searches
    url=f'https://google.com/search?q={query_term}'
    cmd = f'xdg-open {url} >/dev/null 2>&1 &'
    info_print(f"Opening: {url}")
    os.system(cmd)


def search_woorden(term, *, url='http://www.woorden.org/woord/'):
    """The term will be appended to the url"""
    # TODO generalize this for other online dictionaries?
    # eg parameterize base_url (with a %s substitute, and the regex ?)
    query_term = urllib.parse.quote(term) # For web searches
    url = url + query_term
    info_print(f"Fetching: {url}")

    content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    # Pages in different formats, for testing:
    # encyclo:     https://www.woorden.org/woord/hangertje
    # urlencoding: https://www.woorden.org/woord/op zich
    # none:        https://www.woorden.org/woord/spacen
    # ?:           https://www.woorden.org/woord/backspacen #
    # &copy:       http://www.woorden.org/woord/zien
    # Bron:        http://www.woorden.org/woord/glashelder

    # TODO extract smarter. Check DOM parsing libs

    # BUG parsing broken for 'stokken'
    # BUG parsing broken for http://www.woorden.org/woord/tussenin

    match = re.search(f"(\<h2.*?{term}.*?)(?=&copy|Bron:|\<div|\<\/div)", content)
    # match = re.search(f'(\<h2.*?{term}.*?)(?=div)', content) # This should handle all cases (first new/closing div)
    if not match:
        return
    # TODO also parse out the term in the definition, as it might differ from the search term
    # eg searching for a past participle: geoormerkt => oormerken
    definition = match.group()
    return definition


def search_thefreedictionary(term, *, lang):
    query_term = urllib.parse.quote(term) # For web searches
    url = f'https://{lang}.thefreedictionary.com/{query_term}'
    info_print(f"Fetching: {url}")
    content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    # TODO extract smarter. Check DOM parsing libs
    match = re.search('<div id="Definition"><section .*?>.*?<\/section>', content)
    if not match:
        return
    definition = match.group()
    definition = re.sub('<div class="cprh">.*?</div>', '', definition)

    # Get pronunciation via Kerneman (multiple languages), and prepend it
    match = re.search(' class="pron">(.*?)</span>', content)
    if match:
        definition = f"[{match.group(1)}]\n{definition}"
    else:
        info_print("No pron(unciation)")

    return definition


def get_card(id):
    cardsInfo = invoke('cardsInfo', cards=[id])
    card = cardsInfo[0]
    return card


# TODO this should return a string, rather than print
def render_card(card, *, term=None):
    # TODO when front contains HTML, warn, dump it, and clean it and show diff
    # Auto replace, and use the updateNoteFields API? (after prompting)
    # https://github.com/FooSoft/anki-connect/blob/master/actions/notes.md

    info_print()
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    print(render(b, highlight=term, front=f))
    # # Update readline, to easily complete previously searched/found cards
    # if term and term != f:
    #     readline.add_history(f)


# TODO deprecate
def search(term, *, deck):
    # TODO trim whitespace
    # Search Anki: exact, then wildcard (front), then the back
    try:
        while not term:
            term = input("\nSearch: ")
    except:
        return
    card_ids = search_anki(term, deck=deck)
    card_ids = card_ids or search_anki(term, deck=deck, wild=True)
    card_ids = card_ids or search_anki(term, deck=deck, field='back')
    return card_ids


def add_card(term, definition=None, *, deck):

    note = {
        'deckName': deck,
        'modelName': 'Basic-' + deck,
        'fields': {'Front': term},
        'options': {'closeAfterAdding': True},
    }
    if definition:
        note['fields']['Back'] = definition
        # Note, duplicate check (deck scope) enabled by default
        card_id = invoke('addNote', note=note)
    else:
        card_id = invoke('guiAddCards', note=note)
    return card_id


def sync():
    try:
        invoke('sync')
    except:
        # Probably just not running (don't loop on this assumption)
        launch_anki()
        time.sleep(5)
        invoke('sync')

def render_cards(card_ids, *, term=None):
    c = -1
    for card_id in card_ids:
        # This is just for paginating results
        c += 1
        if c > 0:
            print(f"{GREY}{c} of {len(card_ids)}{PLAIN} ", end='', flush=True)
            key = readchar.readkey()
            print((' ' * 80) + '\r', end='', flush=True)
            if key in ('q', '\x1b\x1b', '\x03', '\x04'): # q, ESC-ESC, Ctrl-C, Ctrl-D
                break

        card = get_card(card_id)
        # TODO render_card should return a string
        render_card(card, term=term)


def main(deck):

    # TODO
    # Some menu options are global (sYnc) and others act on the displayed result

    term = None # term = input(f"Search: ") # Factor this into a function
    content = None
    card_id = None
    wild_n = None
    back_n = None
    while True:
        menu = [
            '', deck.upper(), '/ [S]earch', '|', 'S[y]nc', '[Q]uit', '|',
        ]
        # Remind the user of any previous context, and then allow to Add
        if content:
            print(render(content, highlight=term))
        if term:
            menu += ['B[r]owse', '[F]etch', '[G]oogle', '[A]dd', '|']
            if wild_n:
                wild = f"[W]ild [{wild_n}]"
                menu += [wild]
            if back_n:
                back = f"[B]ack [{back_n}]"
                menu += [back]
            menu = menu + [f"Term: [{term}]"]
        if card_id:
            menu = menu + [f"Card: [{str(card_id)}]"]

        menu = ' '.join(menu)
        menu = re.sub(r'\[', '[' + LT_YELLOW, menu)
        menu = re.sub(r'\]', PLAIN + ']' , menu)

        key = None
        while not key:
            print('\r' + menu + '\r', end='', flush=True)
            key = readchar.readkey()
            # Clear the menu:
            # TODO detect screen width (or try curses lib)
            # print('\r' + (' ' * 80) + '\r', end='', flush='True')
            print('\r' + (' ' * 160) + '\r', end='', flush='True')

            if key in ('q', '\x1b\x1b', '\x03', '\x04'): # q, ESC-ESC, Ctrl-C, Ctrl-D
                exit()
            elif key == '.':
                # Reload (for 'live' editing / debugging)
                tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
                ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
                info_print(f"pid: {os.getpid()} mtime: {ts} execv: {sys.argv[0]}")
                os.execv(sys.argv[0], sys.argv)
            elif key == '\x0c': # Ctrl-L clear screen
                print('\033c')
            elif key == 'y':
                sync()
            elif term and key == 'r': # Open Anki browser, for the sake of delete/edit/etc
                search_anki(term, deck=deck, browse=True)
            elif wild_n and key == 'w': # Search front with wildcard, or just search for *term*
                card_ids = search_anki(term, deck=deck, wild=True)
                # TODO report if no results?
                render_cards(card_ids, term=term)
            elif back_n and key == 'b': # Search back (implies wildcard matching)
                card_ids = search_anki(term, deck=deck, field='back')
                # TODO report if no results?
                render_cards(card_ids, term=term)
            elif term and key == 'f':
                if deck == 'nl':
                    content = search_woorden(term)
                else:
                    content = search_thefreedictionary(term, lang=deck)
                if not content:
                    info_print("No results")
                # Don't need to do anything else here, since it's printed next round
            elif term and key == 'g':
                search_google(term)
            elif key == 'a':
                card_id = add_card(term, content, deck=deck)
                content = None
                # Search again, to confirm that it's added/findable
                # (The add_card() doesn't sync immediately, so don't bother re-searching)
                # time.sleep(5)
                # card_ids = search_anki(term)
                # render_cards(card_ids, term=term)
            elif key in ('s', '/'): # Exact match search
                content = None

                # TODO factor the prompt of 'term' into a function?
                try:
                    # TODO colored INFO print
                    term = input(f"Search: ")
                except:
                    continue # TODO why is this necessary to ignore exceptions?
                card_ids = search_anki(term, deck=deck)
                # Check other possible query types:
                # TODO do all the searches (by try to minimise exact and wildcard into one request)
                # eg 'wild_n' will always contain the exact match, if there is one, so it's redundant
                wild_n = len(search_anki(term, deck=deck, wild=True))
                back_n = len(search_anki(term, deck=deck, field='back'))
                if not card_ids:
                    print(f"{LT_RED}No exact match\n{PLAIN}")
                    card_id = None
                    content = None
                    continue
                # TODO bug, since we collapse doubles, this could have more than one result, eg 'maan'/'man'
                # Factor out into eg render_cards()
                if len(card_ids) == 1:
                    card_id, = card_ids
                else:
                    card_id = None
                # card = get_card(card_id)
                # TODO make render_card just return the rendered definition as string,
                # save in 'content', let it print on next iteration
                render_cards(card_ids, term=term)
            else:
                # Unrecognized command. Beep.
                print("\a", end='', flush=True)
                # Repeat input
                key = None


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-d", "--deck", dest="deck",
        help="Name of Anki deck to use (a 2-letter language code, e.g. 'nl')"
        )
    (options, args) = parser.parse_args()
    if not options.deck:
        parser.print_help()
        exit(1)
    main(options.deck)
