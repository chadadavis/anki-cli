#!/usr/bin/env python
from optparse import OptionParser
import html
import json
import os
import re
import readchar
import readline # Not referenced, but used by input()
import sys
import time
import urllib.parse
import urllib.request

# TODO Backlog

# NL-specific pre-processing
# Bug: I cannot search for uitlaatgassen , since the card only contains: Verbuigingen: uitlaatgas|sen (split)
# Remove those too? But only when it's in 'Verbuigingen: ...' (check that it's on the same line)

# Autocomplete ideas:
# Implement search autocomplete (emacs-style?) based on wildcar search for 'term*'
# Or:
# in-line autocomplete/spell check when searching? based on existing cards ? or just a web service ?
# Or:
# Parse out the spellcheck suggestions on the fetched page (test: hoiberg)
# and enable them to be fetched by eg assigning them numbers (single key press?)
# Consider adding these to autocomplete when searching? Or at least after failed search

# repo/Packaging figure out how to package deps (eg readchar) and test it again after removing local install of readchar

# TODO look for log4j style console logging/printing (with colors)

# when checking for an existing word, print stats on age (use case: "why don't I remember this one? still new?")
# See cardInfo response fields: interval, due, reps, lapses, left, (ord? , type?)
# Lookup defs of fields, or just compare to what's displayed in card browser for an example card

# Color codes: https://stackoverflow.com/a/33206814/256856
GREY      = "\033[0;02m"
YELLOW    = "\033[0;33m"
LT_YELLOW = "\033[1;33m"
LT_RED    = "\033[1;31m" # the '1;' makes it bold as well
PLAIN     = "\033[0;0m"

# TODO set to the whole width of the terminal?
LINE_WIDTH = 160

# NB, because the sync operation opens new windows, the window list keeps growing
MINIMIZER = 'for w in `xdotool search --classname "Anki"`; do xdotool windowminimize --sync $w; done'

def launch_anki():
    """Launch anki (in the background) if not already running.
    """
    info_print('Launching anki ...')
    # And try to minimize it, after giving it a couple seconds to launch:
    # TODO the sleep 2 at the start seems needed because MINIMIZER succeeds because the app is running, but it hasn't finished creating the window yet?
    # Or check the window class / name via some tool for getting the window ID / settings
    # Better to have a separate function to test if it's already running, like get_deck_names()
    # And only if that fails, then launch (and minimize)
    os.system(f'anki >/dev/null & for i in 1 2 3 4 5; do sleep 2; if {MINIMIZER}; then break; else echo Waiting ... $i; sleep 1; fi; done')


def request(action, **params):
    """Send a request to Anki desktop via anki_connect HTTP server addon

    https://github.com/FooSoft/anki-connect/
    https://foosoft.net/projects/anki-connect/
    """
    return {'action': action, 'params': params, 'version': 6}


def invoke(action, **params):
    reqJson = json.dumps(request(action, **params)).encode('utf-8')
    req = urllib.request.Request('http://localhost:8765', reqJson)

    # TODO try / except here and then consider auto-launching anki?

    response = json.load(urllib.request.urlopen(req))
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']


def get_deck_names():
    names = sorted(invoke('deckNames'))
    return names


def render(string, *, highlight=None, front=None):
    # This is just makes the HTML string easier to read on the terminal console
    # This changes are not saved in the cards
    # TODO render HTML another way? eg as Markdown instead?
    # At least replace HTML entities with unicode chars (for IPA symbols, etc)
    string = html.unescape(string)

    # Remove tags that are usually in the phonetic markup
    string = re.sub(r'\<\/?a.*?\>', '', string)

    # NL-specific (or specific to woorden.org)
    # Segregate topical category names e.g. 'informeel'
    # Definitions in plain text cards will often have the tags already stripped out.
    # So, also use this manually curated list.
    # spell-checker:disable
    categories = [
        *[]
        ,'\S+kunde'
        ,'\S+ologie'
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
    # spell-checker:enable

    # If we still have the HTML tags, then we can see if this topic category is new to us.
    # Optionally, it can then be manually added to the list above.
    # Otherwise, they wouldn't be detected in old cards, if it's not already in [brackets]
    match = re.search(r'<sup>(.*?)</sup>', string)
    category = None
    if match:
        category = match.group(1)
        # Highlight it, if it's new, so you can (manually) update the 'categories' list above.
        if category in categories:
            string = re.sub(r'<sup>(.*?)</sup>', '[\g<1>]', string)
        else:
            string = re.sub(r'<sup>(.*?)</sup>', f'[{LT_YELLOW}\g<1>{PLAIN}]', string)

    # Specific to: PONS Großwörterbuch Deutsch als Fremdsprache
    string = re.sub('<span class="illustration">', '\n', string)

    # HTML-specific:
    # Remove span tags, so that the text can stay on one line
    string = re.sub('<span.*?>', '', string)
    string = re.sub('<\/span>', '', string)
    # These tags are usually used inline and should not have a line break
    string = re.sub('<[ibu]\/?>', '', string)

    # Replace remaining opening tags with a newline, since usually a new section
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
    string = re.sub(r';?\s*(\d+\.)', '\n\n\g<1>', string)
    # And sub-definitions, marked by eg: b)
    string = re.sub(r';?\s+([a-z]\)\s+)', '\n  \g<1>', string)
    # Split sub-sub-definitions onto newlines
    # TODO: BUG: this breaks text in nl deck like '... [meteorologie]' for some reason
    # string = re.sub(r'\s*\;\s*', '\n     ', string)

    # Delete leading/trailing space on the entry as a whole
    string = re.sub(r'^\s+', '', string)
    string = re.sub(r'\s+$', '', string)

    if string:
        # Canonical newline to end
        string = string + "\n"

    if front:
        # Strip the term from the start of the definition, if present (redundant for infinitives, adjectives, etc)
        string = re.sub(f'^\s*{front}\s*', '', string)

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
        string = re.sub(f"(?i:({highlight}))", f"{YELLOW}\g<1>{PLAIN}", string)

        # TODO Highlight accent-insensitive? (Because accents don't change the semantics in NL)
        # eg exploit should find geëxploiteerd
        # It should be possible with non-combining mode: nc:geëxploiteerd but doesn't seem to work
        # https://docs.ankiweb.net/#/searching
        # Probably need to:
        # Apply search to a unidecoded copy.
        # Then record all the match positions, as [start,end) pairs,
        # then, in reverse order (to preserve position numbers), wrap formatting markup around matches

    if front:
        # And the front back canonically
        string = YELLOW + front + PLAIN + '\n\n' + string

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

def get_empties(deck):
    card_ids = search_anki('', deck=deck, field='back')
    return card_ids


def info_print(*values):
    # TODO Use colorama
    print(GREY, end='')
    print('_' * LINE_WIDTH)
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
    query_term = urllib.parse.quote(term) # For web searches
    url = url + query_term
    print(GREY + f"Fetching: {url} ..." + PLAIN, end='', flush=True)

    content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    clear_line()

    # Pages in different formats, for testing:
    # encyclo:     https://www.woorden.org/woord/hangertje
    # urlencoding: https://www.woorden.org/woord/op zich
    # none:        https://www.woorden.org/woord/spacen
    # ?:           https://www.woorden.org/woord/backspacen #
    # &copy:       http://www.woorden.org/woord/zien
    # Bron:        http://www.woorden.org/woord/glashelder

    # TODO extract smarter. Check DOM parsing libs / XPATH selection

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
    if not term or '*' in term:
        return
    query_term = urllib.parse.quote(term) # For web searches
    url = f'https://{lang}.thefreedictionary.com/{query_term}'
    print(GREY + f"Fetching: {url} ..." + PLAIN, end='', flush=True)
    try:
        content = urllib.request.urlopen(urllib.request.Request(url)).read().decode('utf-8')
    except Exception as e:
        print("\n")
        info_print(e)
        return
    clear_line()
    # TODO extract smarter. Check DOM parsing libs / XPATH expressions
    match = re.search('<div id="Definition"><section .*?>.*?<\/section>', content)
    if not match:
        return
    definition = match.group()

    # Remove citations, just to keep Anki cards terse
    definition = re.sub('<div class="cprh">.*?</div>', '', definition)

    # Get pronunciation (the IPA version) via Kerneman/Collins (multiple languages), and prepend it
    match = re.search(' class="pron">(.*?)</span>', content)
    if match:
        ipa_str = '[' + match.group(1) + ']'
        definition = "\n".join([ipa_str, definition])

    return definition


def get_card(id):
    cardsInfo = invoke('cardsInfo', cards=[id])
    card = cardsInfo[0]
    return card


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


def update_card(card_id, *, front=None, back=None):
    note_id = card_to_note(card_id)
    note = {
        'id': note_id,
        'fields': {},
    }
    if front:
        note['fields']['Front'] = front
    if back:
        note['fields']['Back'] = back
    response = invoke('updateNoteFields', note=note)
    if response and response['error'] is not None:
        raise Exception(response['error'])


def card_to_note(card_id):
    # The notes-to-cards relation is 1-to-many.
    # So, each card has exactly 1 parent note.
    note_id, = invoke('cardsToNotes', cards=[card_id])
    return note_id


def delete_card(card_id):
    note_id = card_to_note(card_id)
    invoke('deleteNotes', notes=[note_id])


# TODO this should return a string, rather than print
def render_card(card, *, term=None):
    info_print()
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    print(render(b, highlight=term, front=f))

    if '<' in f or '&nbsp;' in f:
        info_print("Warning: 'Front' field with HTML hinders exact match search.")
        # Auto-clean it?
        # This is likley useless after cleaning all decks once.
        # As long as you continue to use this script to add cards.
        if True:
            cleaned = render(f).strip()
            card_id = card['cardId']
            update_card(card_id, front=cleaned)
            info_print(f"Updated to:")
            # Get again from Anki to verify updated card
            render_card(get_card(card_id))


def render_cards(card_ids, *, term=None):
    c = -1
    for card_id in card_ids:
        # This is just for paginating results
        c += 1
        if c > 0:
            print(f"{GREY}{c} of {len(card_ids)}{PLAIN} ", end='', flush=True)
            key = readchar.readkey()
            clear_line()
            if key in ('q', '\x1b\x1b', '\x03', '\x04'): # q, ESC-ESC, Ctrl-C, Ctrl-D
                break

        card = get_card(card_id)
        # TODO render_card should return a string
        render_card(card, term=term)


def sync():
    invoke('sync')
    # And minimize it again
    os.system(MINIMIZER)


def clear_line():
    # TODO detect screen width (or try curses lib)
    print('\r' + (' ' * LINE_WIDTH) + '\r', end='', flush='True')


def main(deck):
    term = None # term = input(f"Search: ") # Factor this into a function
    content = None
    card_id = None
    wild_n = None
    back_n = None

        # TODO
        # pipe each display through less/PAGER --quit-if-one-screen
        # https://stackoverflow.com/a/39587824/256856
        # https://stackoverflow.com/questions/6728661/paging-output-from-python/18234081

    while True:
        # Remind the user of any previous context, and then allow to Add
        if content:
            info_print()
            print(render(content, highlight=term))

        # spell-checker:disable
        menu = [
            "", "S[y]nc",
            '|', f"Dec[k]: [{deck.upper()}]",
        ]

        empty_ids = get_empties(deck)
        if empty_ids:
            menu += [f"[E]mpties [{len(empty_ids)}]"]

        menu += ["|", "[S]earch:"]
        if term:
            menu += [f"[{term}]", "B[r]owse", "[G]oogle", "[F]etch", ]

            if wild_n:
                wild = f"[W]ilds [{wild_n}]"
                menu += [wild]
            if back_n:
                back = f"[B]acks [{back_n}]"
                menu += [back]

            menu += ["|", "Card:"]
            if card_id:
                menu = menu + [f"[{card_id}]", "[D]elete"]
            else:
                menu = menu + ["[A]dd"]

        # spell-checker:enable

        menu = ' '.join(menu)
        menu = re.sub(r'\[', '[' + LT_YELLOW, menu)
        menu = re.sub(r'\]', PLAIN + ']' , menu)

        key = None
        while not key:
            print('\r' + menu + '\r', end='', flush=True)
            key = readchar.readkey()
            # Clear the menu:
            clear_line()

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
            elif key == 'k':
                deck = None
                while not deck:
                    decks = get_deck_names()
                    try:
                        deck = input(f"Deck name {decks}: ")
                        if not deck in decks:
                            deck = None
                    except:
                        clear_line()
                card_id = None
            elif key == 'y':
                sync()
            elif card_id and key == 'd':
                delete_card(card_id)
                card_id = None
            elif term and key == 'r': # Open Anki browser, for the sake of delete/edit/etc
                search_anki(term, deck=deck, browse=True)
            elif wild_n and key == 'w': # Search front with wildcard, or just search for *term*
                card_ids = search_anki(term, deck=deck, wild=True)
                render_cards(card_ids, term=term)
            elif back_n and key == 'b': # Search back (with wildcard matching)
                card_ids = search_anki(term, deck=deck, field='back', wild=True)
                render_cards(card_ids, term=term)
            elif term and key == 'f':
                # TODO refactor out into a separate function
                if deck == 'nl':
                    content = search_woorden(term)
                else:
                    content = search_thefreedictionary(term, lang=deck)
                if not content:
                    info_print("No results")
                # content is printed on next iteration.
            elif term and key == 'g':
                search_google(term)
            elif not card_id and key == 'a':
                card_id = add_card(term, content, deck=deck)
                content = None
                # Search again, to confirm that it's added/findable
                # (The add_card() doesn't sync immediately, so don't bother re-searching)
                # time.sleep(5)
                # card_ids = search_anki(term)
                # render_cards(card_ids, term=term)
            elif empty_ids and key == 'e':
                empty_ids = get_empties(deck)
                card_id = empty_ids[0]
                term = get_card(card_id)['fields']['Front']['value']
                delete_card(card_id)
                card_id = None
                wild_n  = None
                back_n  = None

                # Update readline, as if I had searched for this term
                readline.add_history(term)

                # auto fetch
                # TODO refactor out into a separate function
                if deck == 'nl':
                    content = search_woorden(term)
                else:
                    content = search_thefreedictionary(term, lang=deck)
                if not content:
                    info_print("No results")

            elif key in ('s', '/'): # Exact match search
                content = None

                # TODO factor the prompt of 'term' into a function?
                try:
                    term = input(f"Search: ")
                except:
                    continue
                card_ids = search_anki(term, deck=deck)
                # Check other possible query types:
                # TODO do all the searches (by try to minimise exact and wildcard into one request)
                # eg 'wild_n' will always contain the exact match, if there is one, so it's redundant

                wild_n = len(set(search_anki(term, deck=deck, wild=True)) - set(card_ids))
                back_n = len(search_anki(term, deck=deck, wild=True, field='back'))
                if not card_ids:
                    print(f"{LT_RED}No exact match\n{PLAIN}")
                    card_id = None
                    content = None
                    # Fetch
                    # TODO refactor out into a separate function
                    if deck == 'nl':
                        content = search_woorden(term)
                    else:
                        content = search_thefreedictionary(term, lang=deck)
                    if not content:
                        info_print("No results")
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
    # launch_anki()
    decks = get_deck_names()
    parser = OptionParser()
    parser.add_option("-d", "--deck", dest="deck",
        help="Name of Anki deck to use (must be a 2-letter language code, e.g. 'de')"
        )
    (options, args) = parser.parse_args()
    if not options.deck:
        # Take the first deck by default; fail if there are none
        options.deck = decks[0]
    main(options.deck)
