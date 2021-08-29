#!/usr/bin/env python
"""Anki add - fetch one definitions and add new cards to Anki language decks

A note one searching for declined / conjugated forms of words:

It would be nice to confirm that the content fetched corresponds to the term
searched, rather than a declined form. However, each dictionary provider does
this differently, and not even consistently within a given language, as it may
depend on the part of speech of the term. So, the user simply needs to be beware
that if the definition shows a different canonical form, then they should
re-search for the canonical form, and then add that term instead. This should be
clearly visible, because the search term, if present, will be highlighted in the
displayed text.

For example, in Dutch searching for 'geoormerkt' (a past participle) will return
the definition for 'oormerken' (the infinitive). In that case, you'd rather not
add that card, but rather re-search for 'oormerken', now that you know it, and
add that card instead.

"""
import html
import json
import os
import re
import readline  # Not referenced, but used by input()
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from optparse import OptionParser

import readchar
import unidecode
from bs4 import BeautifulSoup
from iso639 import languages # NB, the pip package is called iso-639 (with a -)
from nltk.stem.snowball import SnowballStemmer

# Backlog/TODOs

# BUG: no way to delete cards when multiple matches, eg search for wennen, or just any wildcard search
# Could just process 'card_ids' the same way we already do for 'empty_ids', and get rid of `render_cards()`
# And see if diff keys could control scrolling to the rest of this card or going to
# the next card.

# Maybe related BUG:
# cant add card for stekken because it also matches existing card
# steken (and then there's no option to add). So I have to delete and add in reverse order

# TODO
# pipe each bit of `content` or popped card_ids through less/PAGER --quit-if-one-screen
# https://stackoverflow.com/a/39587824/256856
# https://stackoverflow.com/questions/6728661/paging-output-from-python/18234081

# Stemming

# Stemming for search?
# Or add the inflected forms to the card? as a new field?
# Most useful for langs that you don't know so well.
# (because those matches would be more important than just matching in the desc somewhere)
# Worst case, the online dictionary solves this anyway, so then I'll realize that I searched the wrong card.
# So, it's just one extra manual search. Maybe not worth optimizing. But more interesting for highlighting.

# Enable searching for plural forms on the back of cards:
# Find/remove/update all cards that have a pipe char | in the Verbuigingen/Vervoegingen:
# So that I can also search/find (not just highlight) eg bestek|ken without the pipe char
# Search: back:*Ver*gingen:*|* => 2585 cards
# Make a parser to grab and process it, like what's in the render() already, but then also replace it in the description.
# Maybe copy out some things from render() that should be permanent into it's own def
# And then update the card (like we did before to remove HTML from 'front')

# Replace regex doc parsing with eg
# https://www.scrapingbee.com/blog/python-web-scraping-beautiful-soup/
# And use CSS selectors to extract content more robustly

# Repo/Packaging:
# figure out how to package deps (eg readchar) and test it again after removing local install of readchar

# Logging:
# look for log4j style console logging/printing (with colors)

# UI:
# Consider make a web UI, via an HTTP server running as an anki-addon? (like anki-connect)

# anki: can I test if the deck has modifications since last sync, like anki droid
# does. If not I could at least count any updates or adds or deletes done
# (But this wouldn't tell me if I made any edits, since those are outside the scope)
# Any API to query modifications since sync?

################################################################################

# Color codes: https://stackoverflow.com/a/33206814/256856
YELLOW    = "\033[0;33m"
LT_YELLOW = "\033[1;33m"
RED       = "\033[0;31m"
LT_RED    = "\033[1;31m" # the '1;' makes it bold as well
GREY      = "\033[0;02m"
PLAIN     = "\033[0;00m"

LINE_WIDTH = os.get_terminal_size().columns
WRAP_WIDTH = 100

# q, ESC-ESC, Ctrl-C, Ctrl-D, Ctrl-W
KEYS_CLOSE = ('q', '\x1b\x1b', '\x03', '\x04', '\x17')

# NB, because the sync operation opens new windows, the window list keeps growing.
# So, you can't use a static window id here. So, use the classname to get them all.
MINIMIZER = 'for w in `xdotool search --classname "Anki"`; do xdotool windowminimize --sync $w; done'

def __launch_anki():
    """Try to launch Anki, if not already running, and verify launch.

    This is quite fragile. Since it's not very reliable, it might be more
    effective to not run this every time on startup, but only e.g. after an API
    call fails.

    Also attempts to minimize Anki after successful launch.

    BUG: The sleep 2 at the start seems needed because `MINIMIZER` succeeds
    because the app is running, but it hasn't finished creating the window yet?
    """
    os.system(f'anki >/dev/null & for i in 1 2 3 4 5; do sleep 2; if {MINIMIZER}; then break; else echo Waiting ... $i; sleep 1; fi; done')


def request(action, **params):
    """Send a request to Anki desktop via the API for the anki_connect addon

    Details:
    https://github.com/FooSoft/anki-connect/
    """
    return {'action': action, 'params': params, 'version': 6}


def invoke(action, **params):
    reqJson = json.dumps(request(action, **params)).encode('utf-8')
    req = urllib.request.Request('http://localhost:8765', reqJson)

    try:
        response = json.load(urllib.request.urlopen(req))
        if response['error'] is not None:
            raise Exception(response['error'])
        return response['result']
    except (ConnectionRefusedError, urllib.error.URLError) as e:
        print(""""
            Failed to connect to Anki. Make sure that Anki is running, and using the anki_connect addon.
            https://github.com/FooSoft/anki-connect/
        """)
        exit()


def get_deck_names():
    names = sorted(invoke('deckNames'))
    return names


def render(string, *, highlight=None, front=None, deck=None):
    # This is just makes the HTML string easier to read on the terminal console
    # This changes are not saved in the cards
    # TODO render HTML another way? eg as Markdown instead?

    # Replace HTML entities with unicode chars (for IPA symbols, etc)
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
    # (NB, just for display here; this doesn't help with matching)
    string = re.sub(r'\|', '', string)

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
    # And sub-definitions, marked by eg: a) or b)
    string = re.sub(r';?\s+([a-z]\)\s+)', '\n  \g<1>', string)

    # Delete leading/trailing space on the entry as a whole
    string = re.sub(r'^\s+', '', string)
    string = re.sub(r'\s+$', '', string)

    if string:
        # Canonical newline to end
        string = string + "\n"

    if front:
        # Strip the term from the start of the definition, if present (redundant for infinitives, adjectives, etc)
        string = re.sub(f'^\s*{front}\s*', '', string)

    # TODO refactor this out
    if highlight and deck:
        highlight = re.sub(r'[.]', '\.', highlight)
        highlight = re.sub(r'[_]', '.', highlight)
        highlight = re.sub(r'[*]', r'\\w*', highlight)

        # Terms to highlight, in addition to the query term
        highlights = { highlight }

        # Collapse double letters in the search term
        # eg ledemaat => ledemat
        # So that can now also match 'ledematen'
        # This is because the examples in the 'back' field will include declined forms
        collapsed = re.sub(r'(.)\1', '\g<1>', highlight)
        if collapsed != highlight:
            highlights.add(collapsed)

        if front:
            # Also highlight the canonical form, in case the search term was different
            highlights.add(front)

        # TODO also factor out the stemming (separate from highlighting, since lang-specific)

        # Map e.g. 'de' to 'german', as required by SnowballStemmer
        lang = languages.get(alpha2=deck).name.lower()
        stemmer = SnowballStemmer(lang)
        stem = stemmer.stem(highlight)
        if stem != highlight:
            highlights.add(stem)
        front_or_highlight = unidecode.unidecode(front or highlight)

        # Language/source-specific extraction of inflected forms
        if deck == 'nl':
            # Hack stemming, assuming -en suffix
            # For cases: verb infinitives, or plural nouns without singular
            # eg ski-ën, hersen-en
            highlights.add( re.sub(r'en$', '', front_or_highlight) )

            # Find given inflections

            matches = []
            # Theoretically, we could not have a double loop here, but this makes it easier to read.
            # There can be multiple inflections in one line (eg prijzen), so it's easier to have two loops.
            for inflection in re.findall(r'(?ms)^(?:Vervoegingen|Verbuigingen):\s*(.*?)\s*\n{1,2}', string):
                # There is not always a parenthetical part-of-speech after the inflection of plurals.
                # Sometimes it's just eol (eg "nederlaag") . So, it ends either with eol $ or open paren (
                matches += re.findall(r'(?s)(?:\)|^)\s*(.+?)\s*(?:\(|$)', inflection)

            for match in matches:

                # Remove separators, e.g. in "Verbuigingen: uitlaatgas|sen (...)"
                match = re.sub(r'|', '', match)

                # If past participle, remove the 'is' or 'heeft'
                # Sometimes as eg: uitrusten: 'is, heeft uitgerust' or 'heeft, is uitgerust'
                match = re.sub(r'^(is|heeft)(,\s+(is|heeft))?\s+', '', match)
                # And the reflexive portion 'zich' isn't necessary, eg: "begeven"
                match = re.sub(r'\bzich\b', '', match)

                # This is for descriptions with a placeholder char like:
                # "kind - Verbuigingen: -eren" : "kinderen", or "'s" for "solo" => "solo's"
                match = re.sub(r"^[-'~]", front_or_highlight, match)

                # plural nouns with multiple declensions, CSV
                # eg waarde => waarden, waardes
                if ',' in match:
                    highlights.update(re.split(r',\s*', match))
                    match = ''

                # Collapse spaces, and trim
                match = re.sub(r'\s+', ' ', match)
                match = match.strip()

                # Hack stemming for infinitive forms with a consonant change in simple past tense:
                # dreef => drij(ven) => drij(f)
                # koos => kie(zen) => kie(s)
                if front_or_highlight.endswith('ven') and match.endswith('f'):
                    highlights.add( re.sub(r'ven$', '', front_or_highlight) + 'f' )
                if front_or_highlight.endswith('zen') and match.endswith('s'):
                    highlights.add( re.sub(r'zen$', '', front_or_highlight) + 's' )

                # Allow separable verbs to be separated, in both directions.
                # ineenstorten => 'stortte ineen'
                # TODO BUG capture canonical forms that end with known prepositions (make a list)
                # eg teruggaan op => ging terug op (doesn't work here)
                # We should maybe just remove the trailing preposition (if it was also a trailing word in the 'front')
                if separable := re.findall(r'^(\S+)\s+(\S+)$', match):
                    # NB, the `pre` is anchored with \b because the prepositions
                    # are short and there would otherwise be many false positive
                    # matches

                    # eg stortte, ineen
                    (conjugated, pre), = separable
                    highlights.add( f'{conjugated}.*?\\b{pre}\\b' )
                    highlights.add( f'\\b{pre}\\b.*?{conjugated}' )

                    # eg storten
                    base = re.sub(f'^{pre}', '', front_or_highlight)
                    highlights.add( f'{base}.*?\\b{pre}\\b' )
                    highlights.add( f'\\b{pre}\\b.*?{base}' )

                    # eg stort
                    stem = re.sub(f'en$', '', base)
                    highlights.add( f'{stem}.*?\\b{pre}\\b' )
                    highlights.add( f'\\b{pre}\\b.*?{stem}' )

                    match = ''

                if match:
                    highlights.add(match)

        elif deck == 'de':
            if front_or_highlight.endswith('en'):
                highlights.add( re.sub(r'en$', '', front_or_highlight) )

            # TODO use the debugger to test
            # DE: <gehst, ging, ist gegangen> gehen

            # Could also get the conjugations via the section (online):
            # Collins German Verb Tables (and for French, English)
            # Or try Verbix? (API? Other APIs online for inflected forms?)
            ...
        elif deck == 'en':
            ...
            # TODO
            # EN: v. walked, walk·ing, walks

        else:
            ...

        # Sort the highlight terms so that the longest are first.
        # Since inflections might be prefixes.
        # i.e. this will prefer matching 'kinderen' before 'kind'
        highlight_re = '|'.join(reversed(sorted(highlights, key=len)))

        # Highlight accent-insensitive:
        # Start on a copy without accents:
        string_decoded = unidecode.unidecode(string)
        # NB, the string length will be the same if accents are simply removed.
        # However, chars like the German 'ß' could make the decoded longer.
        # So, first test if it's safe to use this position-based approach:
        if len(string) == len(string_decoded):
            # And the terms to highlight need to be normalized then too:
            highlight_re_decoded = unidecode.unidecode(highlight_re)
            # Get all match position intervals (half-open intervals)
            i = re.finditer(f"(?i:{highlight_re_decoded})", string_decoded)
            spans = [m.span() for m in i]
            l = list(string)
            # Process the string back-to-front, since inserting changes indexes
            for t in reversed(spans):
                x,y = t
                # Also, here, y before x, since back-to-front
                l.insert(y, PLAIN)
                l.insert(x, YELLOW)

            string = ''.join(l)
        else:
            # We can't do accent-insensitive hightlighting.
            # Just do case-insensitive highlighting.
            # NB, the (?i:...) doesn't create a group.
            # That's why ({highlight}) needs it's own parens here.
            string = re.sub(f"(?i:({highlight_re}))", f"{YELLOW}\g<1>{PLAIN}", string)

    if front:
        # And the front back canonically
        string = YELLOW + front + PLAIN + '\n\n' + string

    return string


def search(term, *, lang):
    obj = {}
    if lang == 'nl':
        content = search_woorden(term)
        obj['definition'] = content
    else:
        obj = search_thefreedictionary(term, lang=lang)
    return obj


def search_anki(term, *, deck, wild=False, field='front', browse=False):

    # If term contains whitespace, either must quote the whole thing, or replace spaces:
    search_term = re.sub(r' ', '_', term) # For Anki searches

    # TODO accent-insensitive search?
    # eg exploit should find geëxploiteerd
    # It should be possible with Anki's non-combining mode: nc:geëxploiteerd
    # https://docs.ankiweb.net/#/searching
    # But doesn't seem to work

    # Collapse double letters into a disjunction, eg: (NL-specific)
    # This implies that the user should, when in doubt, use double chars in the query
    # deck:nl (front:dooen OR front:doen)
    # or use a re: (but that doesn't seem to work)
    # TODO BUG: this isn't a proper Combination (maths), so it misses some cases
    # TODO consider a stemming library here?

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

    # TODO extract smarter. Check DOM parsing libs / XPATH selection / CSS selectors

    # BUG parsing broken for 'stokken'
    # BUG parsing broken for http://www.woorden.org/woord/tussenin

    match = re.search(f"(\<h2.*?{term}.*?)(?=&copy|Bron:|\<div|\<\/div)", content)
    # match = re.search(f'(\<h2.*?{term}.*?)(?=div)', content) # This should handle all cases (first new/closing div)
    if not match:
        return
    definition = match.group()
    return definition


def search_thefreedictionary(term, *, lang):
    return_obj = {}
    if not term or '*' in term:
        return
    query_term = urllib.parse.quote(term) # For web searches
    url = f'https://{lang}.thefreedictionary.com/{query_term}'
    print(GREY + f"Fetching: {url} ..." + PLAIN, end='', flush=True)
    try:
        response = urllib.request.urlopen(urllib.request.Request(url))
        content = response.read().decode('utf-8')
    except urllib.error.HTTPError as response:
        # NB urllib raises an exception on 404 pages. The content is in the Error.
        if response.code == 404:
            content = response.read().decode('utf-8')
            # Parse out spellcheck suggestions via CSS selector: .suggestions a
            soup = BeautifulSoup(content, 'html.parser')
            suggestions = [ r.text for r in soup.select('.suggestions a') ]
            return_obj['suggestions'] = sorted(suggestions, key=str.casefold)
    except Exception as e:
        print("\n")
        info_print(e)
        return

    clear_line()
    # TODO extract smarter. Check DOM parsing libs / XPATH / CSS selector
    match = re.search('<div id="Definition"><section .*?>.*?<\/section>', content)
    if not match:
        return return_obj

    definition = match.group()
    # Remove citations, just to keep Anki cards terse
    definition = re.sub('<div class="cprh">.*?</div>', '', definition)

    # Get pronunciation (the IPA version) via Kerneman/Collins (multiple languages), and prepend it
    match = re.search(' class="pron">(.*?)</span>', content)
    if match:
        ipa_str = '[' + match.group(1) + ']'
        definition = "\n".join([ipa_str, definition])
    return_obj['definition'] = definition
    return return_obj


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
        # NB, duplicate check (deck scope) enabled by default
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


def wrapper(string):
    lines_wrapped = []
    for line in string.splitlines():
        line_wrap = textwrap.wrap(line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=False)
        line_wrap = line_wrap or ['']
        lines_wrapped += line_wrap
    string = "\n".join(lines_wrapped)
    return string


def render_card(card, *, term=None):
    info_print()
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    deck = card['deckName']

    b_rendered = render(b, highlight=term, front=f, deck=deck)
    b_wrapped = wrapper(b_rendered)

    # TODO refactor: return a string here
    print(b_wrapped + "\n")

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
            if key in KEYS_CLOSE:
                break

        card = get_card(card_id)
        # TODO refactor: render_card should return a string
        render_card(card, term=term)


def sync():
    invoke('sync')
    # And minimize it again
    os.system(MINIMIZER)


def clear_line():
    print('\r' + (' ' * LINE_WIDTH) + '\r', end='', flush='True')


def clear_screen():
    print('\033c')


def main(deck):
    global options
    global suggestions
    suggestions = []
    term = None
    content = None
    card_id = None
    wild_n = None
    back_n = None

    while True:
        # Remind the user of any previous context, and then allow to Add
        if content:
            info_print()
            print(render(content, highlight=term, deck=deck))


        if suggestions:
            info_print("Did you mean: (press TAB for autocomplete)")
            print("\n".join(suggestions))

        # spell-checker:disable
        menu = [
            "", "S[y]nc",
            '|', f"Dec[k]: [{deck.upper()}]",
        ]

        # TODO instead of separate def for render_cards(), process them like a
        # queue, like we do here with empty_ids, so that we still have all the
        # menu options, like delete a card when there are multiple matches, etc
        # Apply this to card_ids as well.
        # That will then also make it easier to then send each popped result through $PAGER .
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
            # This works, but then the menu is always one a diff line.
            # Also, clearing the screen erases history, which isn't great.
            # clear_screen()

            if key in (KEYS_CLOSE):
                exit()
            elif key == '.':
                # Reload (for 'live' editing / debugging)
                tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
                ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
                info_print(f"pid: {os.getpid()} mtime: {ts} execv: {sys.argv[0]}")
                os.execv(sys.argv[0], sys.argv)
            elif key == '\x0c': # Ctrl-L clear screen
                clear_screen()
            elif key == 'k':
                # TODO refactor this out
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
                wild_n = None
                back_n = None

                # This is so that `completer()` can know what lang/deck we're using
                options.deck = deck
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
                obj = search(term, lang=deck)
                content = obj and obj.get('definition')
                suggestions = obj and obj.get('suggestions') or []
                if not obj or not content:
                    info_print("No results")
                # If any, suggestions/content printed on next iteration.
            elif term and key == 'g':
                search_google(term)
            elif not card_id and key == 'a':
                card_id = add_card(term, content, deck=deck)
                content = None
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
                obj = search(term, lang=deck)
                content = obj and obj.get('definition')
                suggestions = obj and obj.get('suggestions') or []
                if not obj or not content:
                    info_print("No results")
                # If any, suggestions/content printed on next iteration.

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
                    print(f"{RED}No exact match\n{PLAIN}")
                    card_id = None
                    content = None

                    if '*' in term:
                        continue
                    # Fetch
                    obj = search(term, lang=deck)
                    content = obj and obj.get('definition')
                    suggestions = obj and obj.get('suggestions') or []
                    if not obj or not content:
                        info_print("No results")
                    # If any, suggestions/content printed on next iteration.

                    continue
                # TODO bug, since we collapse double chars, this could have more than one result, eg 'maan'/'man'
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


def completer(text: str, state: int) -> str:
    completions = []
    if not text:
        return

    # Unidecode allows accent-insensitive autocomplete
    ud = unidecode.unidecode
    text = ud(text)

    # Completions via readline history
    for i in range(1, readline.get_current_history_length() + 1):
        i = readline.get_history_item(i)
        if ud(i).casefold().startswith(text.casefold()):
            completions += [ i ]

    # Completions via recent spellcheck suggestions (from last online fetch)
    completions += [
                    s for s in suggestions
                    if ud(s).casefold().startswith(text.casefold())
                    ]

    # Autocomplete via prefix search in Anki (via local HTTP server)
    if not completions:
        global options
        card_ids = search_anki(text + '*', deck=options.deck)
        for card_id in card_ids:
            term = get_card(card_id)['fields']['Front']['value']
            if ud(term).casefold().startswith(text.casefold()):
                completions += [ term ]

    if state < len(completions):
        return completions[state]

    if state == 0:
        # Beep, if the text doesn't match any possible completion
        print("\a", end='', flush=True)


if __name__ == "__main__":
    decks = get_deck_names()
    parser = OptionParser()
    parser.add_option("-d", "--deck", dest="deck",
        help="Name of Anki deck to use (must be a 2-letter language code, e.g. 'de')"
        )
    (options, args) = parser.parse_args()
    if not options.deck:
        # Take the first deck by default; fail if there are none
        options.deck = decks[0]

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")

    main(options.deck)
