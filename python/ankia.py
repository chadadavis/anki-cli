#!/usr/bin/env python
"""Anki add - fetch online definitions and add new cards to Anki vocabulary decks

Based on this API:
https://github.com/FooSoft/anki-connect/

A note on searching for declined / conjugated forms of words:

It would be nice to confirm that the content fetched corresponds to the term
searched, rather than a declined form. However, each dictionary provider does
this differently, and not even consistently within a given language, as it may
depend on the part of speech of the term. So, the user simply needs to be beware
that if the definition shows a different canonical form, then they should
re-search for the canonical form, and then add that term instead. (This should
be clearly visible if this has happened, because the search term, if present,
will be highlighted in the displayed text.)

For example, in Dutch searching for 'geoormerkt' (a past participle) will return
the definition for 'oormerken' (the infinitive). In that case, you'd rather not
add that card, but rather re-search for 'oormerken', now that you know what the
base form is, and add that card instead.

"""
import html
import json
import os
import readline  # Not referenced, but used by input()
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from optparse import OptionParser

# Note, that regex search in Anki is supported from 2.1.24+ onward
# https://apps.ankiweb.net/
# https://docs.ankiweb.net/searching.html
# https://docs.rs/regex/1.3.9/regex/#syntax
# But it unfortunately doesn't help much for the NL words from woorden.org due to the non-consistent format.

# This override is necessary for wildcard searches, due to extra interpolation.
# Otherwise 're' raises an exception. Search for 'regex' below.
# https://learnbyexample.github.io/py_regular_expressions/gotchas.html
# https://docs.python.org/3/library/re.html#re.sub
# "Unknown escapes of ASCII letters are reserved for future use and treated as errors."
import regex as re

import readchar
import unidecode
from bs4 import BeautifulSoup
from iso639 import languages # NB, the pip package is called iso-639 (with a -)
from nltk.stem.snowball import SnowballStemmer

# Backlog/TODO

# Port content cleanups (in the render() def) back into the card, via update()

# Replace 'poliek' category with 'politiek' in nl cards.
# And also the pipe '|' char in Verbuigingen lines.

# Just replace all (just NL?) cards with the version from render() ie HTML=>text
# That would solve a lot of the cleanup problems itself
# But maybe check that newer/HTML cards don't have too many \n\n in them
# Checked if rendered text is diff from stored text (in Anki DB).
# If so, add a menu item (not a prompt) to update card. Then I can still ignore, if I want.
# So, maybe also use the rendered text then when adding new cards? Or just enable the update menu option?
# But, what about other langs?
# Any good way to note cards that I've manually modified? eg just add my own tag CAD: somewhere?

# Anki add: replace cards with plain text and then either:
# 1: put inflections # into another field/tag
# 2:use single-line regex search to search # inflections/verbuigingen
# (since there's no consistent ending to anchor with a regex)

# Since I'd also like to try to make formatted text versions for other
# languages, maybe regex-based rendering isn't the most sustainable approach.
# Would an XSLT, per source, make sense for the HTML def content?

# Make constants for the keycodes, eg CTRL_C = '\x03'

# Enable searching for eg O&O (in the card encoded as O&amp;O )
# Consider alternative addons for Anki:
# https://ankiweb.net/shared/info/1807206748
# https://github.com/finalion/WordQuery
# All addons:
# https://ankiweb.net/shared/addons/

# note markup for antonyms - or check API -
# else replace <span class="Ant"> with something else (e.g. franc != menteur)

# bug with NL results from FD (for when Woorden isn't working).
# Why does EN work when NL doesn't?
# If Woorden is often unavailable, make this configurable in the menu (rather than hard-coded)?

# Terminal display - pager
# Pipe each bit of `content` or popped card_ids through less/PAGER --quit-if-one-screen
# https://stackoverflow.com/a/39587824/256856
# https://stackoverflow.com/questions/6728661/paging-output-from-python/18234081

# And any way to left-indent all output to the console, globally (eg 2-4 chars, because window borders, etc)
# Maybe also via textwrap ?

# Use freeDictionary API, so as to need less regex parsing
# https://github.com/Max-Zhenzhera/python-freeDictionaryAPI/

# Add support for wiktionary? (IPA?) ?

# Add nl-specific etymology?
# https://etymologiebank.nl/

# Replace regex doc parsing with eg
# https://www.scrapingbee.com/blog/python-web-scraping-beautiful-soup/
# And use CSS selectors to extract content more robustly

# Repo/Packaging:
# figure out how to package deps (eg readchar) and test it again after removing local install of readchar

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

# Add DWDS for better German defs. But get IPA pronunciation elsewhere
# (eg FreeDictionary or Wiktionary)

# TODO
# Think about how to add multiples webservices for a single deck/lang (?)
# Eg beyond a dictionary, what about extra (web) services for:
# synonyms, pronunciation, etymology, etc, or just allowing for multiple search providers
# Maybe just:
# { lang: en, dict: dictionary.com, syn/thes: somesynservice.com, ipa: some ipa service, etym: etymonline.com, ...}
# Get IPA from wiktionary (rather than FreeDictionary)?
# And maybe later think about how to combine/concat these also to the same anki card ...

# Logging:
# look for log4j style debug mode console logging/printing (with colors)

# Anki: unify note types (inheritance), not for this code, but in the app.
# Learn what the purpose of different notes types is, and then make them all use
# the same, or make them inherit from each other, so that I don't have to
# configure/style a separate note type for each language.


################################################################################

# TODO consider colorama here?

# Color codes:
# The '1;' makes a foreground color bold/bright as well.
# https://stackoverflow.com/a/33206814/256856
YELLOW    = "\033[0;33m"
YELLOW_LT = "\033[1;33m"
GREEN     = "\033[0;32m"
GREEN_LT  = "\033[1;32m"
BLUE      = "\033[0;34m"
BLUE_LT   = "\033[1;34m"
RED       = "\033[0;31m"
RED_LT    = "\033[1;31m"
GREY      = "\033[0;02m"
GRAY_LT   = "\033[1;02m"
WHITE     = "\033[0;37m"
WHITE_LT  = "\033[1;37m"
RESET     = "\033[0;00m"

# Abstract colors into use cases, in case we want to change the mapping later
COLOR_COMMAND   = WHITE_LT
COLOR_WARN      = YELLOW_LT
COLOR_VALUE     = BLUE_LT
COLOR_OK        = GREEN_LT
COLOR_HIGHLIGHT = YELLOW
# TODO update render() and info_print() to use these too

# Key commands that close the app
KEYS_CLOSE = (
    'q',
    'x',
    '\x1b\x1b', # ESC-ESC
    # '\x03',     # Ctrl-C
    # '\x04',     # Ctrl-D
    '\x17',     # Ctrl-W
    )

# NB, because the sync operation opens new windows, the window list keeps growing.
# So, you can't use a static window id here. So, use the classname to get them all.
WINDOW_MIN =   'for w in `xdotool search --classname "Anki"`; do xdotool windowminimize --sync $w; done'
WINDOW_RAISE = 'for w in `xdotool search --classname "Anki"`; do xdotool windowraise $w; done'

def __launch_anki():
    """Try to launch Anki, if not already running, and verify launch.

    This is quite fragile. Since it's not very reliable, it might be more
    effective to not run this every time on startup, but only e.g. after an API
    call fails.

    Also attempts to minimize Anki after successful launch.

    BUG: The sleep 2 at the start seems needed because `MINIMIZER` succeeds
    because the app is running, but it hasn't finished creating the window yet?
    """
    os.system(f'anki >/dev/null & for i in 1 2 3 4 5; do sleep 2; if {WINDOW_MIN}; then break; else echo Waiting ... $i; sleep 1; fi; done')


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
            info_print('error: ', response['error'])
            return None
        else:
            return response['result']
    except (ConnectionRefusedError, urllib.error.URLError) as e:
        print(""""
            Failed to connect to Anki. Make sure that Anki is running, and using the anki_connect addon.
            https://github.com/FooSoft/anki-connect/
        """)
        exit()


def get_deck_names():
    names = sorted(invoke('deckNames'))
    # Filter out sub-decks
    # names = [ i for i in names if not '::' in i]
    return names


def render(string, *, highlight=None, front=None, deck=None):
    # This is just makes the HTML string easier to read on the terminal console
    # This changes are not saved in the cards
    # TODO render HTML another way? eg as Markdown instead?

    # Specific to woorden.org
    # Before unescaping HTML entities: Replace (&lt; and &gt;) with ( and )
    string = re.sub(r'\(&lt;', '(', string)
    string = re.sub(r'\&gt;\)', ')', string)

    # Replace HTML entities with unicode chars (for IPA symbols, etc)
    string = html.unescape(string)

    # Remove tags that are usually in the phonetic markup
    string = re.sub(r'\<\/?a.*?\>', '', string)

    # NL-specific (woorden.org)
    string = re.sub(r'poliek', 'politiek', string)

    # NL-specific (or specific to woorden.org)
    # Segregate topical category names e.g. 'informeel'
    # Definitions in plain text cards will often have the tags already stripped out.
    # So, also use this manually curated list.
    # spell-checker:disable
    categories = [
        *[]
        # These are just suffixes that mean "study of a(ny) field"
        ,'\S+kunde'
        ,'\S+ografie'
        ,'\S+ologie'
        ,'\S+onomie'
        ,'\S*techniek'

        ,'algemeen'
        ,'ambacht'
        ,'anatomie'
        ,'architectuur'
        ,'commercie'
        ,'computers'
        ,'constructie'
        ,'culinair'
        ,'defensie'
        ,'educatie'
        ,'electriciteit'
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
        ,'muziek'
        ,'ouderwets'
        ,'politiek'
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
            string = re.sub(r'<sup>(.*?)</sup>', f'[{YELLOW_LT}\g<1>{RESET}]', string)

    # Specific to: PONS Großwörterbuch Deutsch als Fremdsprache
    string = re.sub('<span class="illustration">', '\n', string)

    # HTML-specific:
    # Remove span tags, so that the text can stay on one line
    string = re.sub('<span.*?>', '', string)
    string = re.sub('<\/span>', '', string)
    # These HTML tags are usually used inline and should not have a line break
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
    # Remove hover tip on IPA pronunciation
    string = re.sub(r'(?s)<a class="?help"? .*?>', '', string)
    # Ensure headings begin on their own line (also covers plural forms, eg "Synoniemen")
    string = re.sub(r'(?<!\n)(Uitspraak|Vervoeging|Voorbeeld|Synoniem|Antoniem)', '\n\g<1>', string)
    # Remove seperators in plurals (eg in the section: "Verbuigingen")
    # (NB, just for display here; this doesn't help with matching)
    string = re.sub(r'\|', '', string)

    # NL-specific: Newlines before example `phrases in backticks`
    # (but not *after*, else you'd get single commas on a line, etc)
    # (using a negative lookbehind assertion here)
    string = re.sub(r'(?<!\n)(`.*?`)', '\n\g<1>', string)

    # NL-specific: Ensure that Voorbeeld(en): has a \n\n before it,
    # to make the actual defnition stand out more.
    string = re.sub(r'(?<!\n\n)(Voorbeeld(en)?:)', '\n\n\g<1>', string)

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
        highlight = re.sub(r'[.]', r'\.', highlight)
        highlight = re.sub(r'[_]', r'.', highlight)

        # Even though this is a raw string, the '\' needs to be escaped, because
        # the 're' module throws an exception for any escape sequences that are
        # not valid in a standard string. (The 'regex' module doesn't.)
        # https://learnbyexample.github.io/py_regular_expressions/gotchas.html
        # https://docs.python.org/3/library/re.html#re.sub
        # "Unknown escapes of ASCII letters are reserved for future use and treated as errors."
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
            highlights.add( re.sub(r'en$', r'\\S*', front_or_highlight) )

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
                # "kind - Verbuigingen: -eren" : "kinderen", or "'s" for "homo" => "homo's"
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
                l.insert(y, RESET)
                l.insert(x, YELLOW)

            string = ''.join(l)
        else:
            # We can't do accent-insensitive hightlighting.
            # Just do case-insensitive highlighting.
            # NB, the (?i:...) doesn't create a group.
            # That's why ({highlight}) needs it's own parens here.
            string = re.sub(f"(?i:({highlight_re}))", f"{YELLOW}\g<1>{RESET}", string)

    if front:
        # And the front back canonically
        string = YELLOW + front + RESET + '\n\n' + string

    return string


def search(term, *, lang):
    obj = {}

    if lang == 'nl':
        content = search_woorden(term)
        obj['definition'] = content
        return obj

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
    # Or see how it's being done inside this addon:
    # https://ankiweb.net/shared/info/1924690148

    terms = [search_term]

    # Collapse double letters into a disjunction, eg: (NL-specific)
    # This implies that the user should, when in doubt, use double chars in the query
    # deck:nl (front:maaken OR front:maken)
    # or use a re: (but that doesn't seem to work)
    # TODO BUG: this isn't a proper Combination (maths), so it misses some cases
    # TODO consider a stemming library here?
    if deck == 'nl':
        while True:
            next_term = re.sub(r'(.)\1', '\g<1>', search_term, count=1)
            if next_term == search_term:
                break
            terms += [next_term]
            search_term = next_term

    if field:
        # info_print(f'field:{field}')
        if wild:
            # Wrap *stars* around (each) term.
            # Note, only necessary if using 'field', since it's default otherwise
            terms = map(lambda x: f'*{x}*', terms)
        terms = map(lambda x: field + ':' + x, terms)

        # Regex search of declinations:
        # This doesn't really work, since the text in the 'back' field isn't consistent.
        # Sometimes there's a parenthetical expression after the declination, sometimes not
        # So, I can''t anchor the end of it, which means it's the same as just a wildcard search across the whole back.
        # eg 'Verbuigingen.*{term}', and that's not any more specific than just searching the whole back ...
        # if field == 'front' and deck == 'nl':
        #     # Note, Anki needs the term in the query that uses "re:" to be wrapped in double quotes (also in the GUI)
        #     terms = [*terms, f'"back:re:(?s)(Verbuiging|Vervoeging)(en)?:(&nbsp;|\s|<.*?>|heeft|is)*{term}\\b"' ]

    query = f'deck:{deck} (' + ' OR '.join([*terms]) + ')'
    # info_print(f'query:{query}')

    if browse:
        card_ids = invoke('guiBrowse', query=query)
    else:
        card_ids = invoke('findCards', query=query)
        card_ids = card_ids or []
    return card_ids


# This set does not overlap with get_mid() nor get_old()
def get_new(deck):
    card_ids = invoke('findCards', query=f"deck:{deck} is:new")
    return len(card_ids)


# Cards due before 0 days from now.
# Only if no reviews were done since midnight, since user has already reviewed deck today.
# This is to stimulate doing a review today, if it has any cards that can be reviewed.
# This set does not overlap with get_new()
# This set does overlap with get_mid() or get_old()
# TODO this wrongly returns epoch_review == 0 for hierarchical decks (eg "Python")
# TODO does this need to match the Anki setting "Next day begins N hours *after* midnight" ?
def get_due(deck):
    card_ids = []
    review_id = invoke('getLatestReviewID', deck=deck)
    # Truncate milliseconds
    epoch_review = int(review_id/1000)
    # This just gets the YYYY,MM,DD out of the struct_time
    # TODO find a more intuitive way to do this
    epoch_midnight = int(time.mktime(tuple([ *time.localtime()[0:3], *[0]*5, -1 ])))
    if epoch_review < epoch_midnight :
        card_ids = invoke('findCards', query=f"deck:{deck} (prop:due<=0)")
    return len(card_ids)


# Immature cards, short interval
# This set does not overlap with get_new() nor get_old()
def get_mid(deck):
    card_ids = invoke('findCards', query=f"deck:{deck} (is:review OR is:learn) prop:ivl<21")
    return len(card_ids)


# Mature cards
# This set does not overlap with get_new() nor get_mid()
def get_old(deck):
    card_ids = invoke('findCards', query=f"deck:{deck} (is:review OR is:learn) prop:ivl>=21")
    return len(card_ids)


def get_empties(deck):
    card_ids = search_anki('', deck=deck, field='back')
    return card_ids


def info_print(*values):
    # TODO Use colorama
    LINE_WIDTH = os.get_terminal_size().columns

    print(GREY, end='')
    print('_' * LINE_WIDTH)
    print(*values)
    print(RESET, end='')
    if values:
        print()


def debug_print(*values):
    if not options.debug:
        return
    info_print(*values)


def launch_url(url):
    cmd = f'xdg-open {url} >/dev/null 2>&1 &'
    info_print(f"Opening: {url}")
    os.system(cmd)


def search_google(term):
    query_term = urllib.parse.quote(term) # For web searches
    url=f'https://google.com/search?q={query_term}'
    launch_url(url)


def search_woorden(term, *, url='http://www.woorden.org/woord/'):
    query_term = urllib.parse.quote(term) # For web searches
    url = url + query_term
    clear_line()
    print(GREY + f"Fetching: {url} ..." + RESET, end='', flush=True)

    try:
        response = urllib.request.urlopen(urllib.request.Request(url))
        content = response.read().decode('utf-8')
    except (Exception, KeyboardInterrupt) as e:
        print("\n")
        info_print(e)
        return

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

    match = re.search(f"(?s)(\<h2.*?{term}.*?)(?=&copy|Bron:|\<div|\<\/div)", content)
    if not match:
        debug_print("No match in HTML document")
        return
    definition = match.group()
    return definition


def search_thefreedictionary(term, *, lang):
    return_obj = {}
    if not term or '*' in term:
        return
    query_term = urllib.parse.quote(term) # For web searches
    url = f'https://{lang}.thefreedictionary.com/{query_term}'
    clear_line()
    print(GREY + f"Fetching: {url} ..." + RESET, end='', flush=True)
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
    except (Exception, KeyboardInterrupt) as e:
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
    """Create a new Note. (If you want the card_id, do another search for it)"""

    note = {
        'deckName': deck,
        'modelName': 'Basic-' + deck,
        'fields': {'Front': term},
        'options': {'closeAfterAdding': True},
    }
    if definition:
        note['fields']['Back'] = definition
        # NB, duplicate check (deck scope) enabled by default
        note_id = invoke('addNote', note=note)
    else:
        # NB, this card_id won't exist if the user aborts the dialog.
        # But, that's also handled by delete_card() if it should be called.
        note_id = invoke('guiAddCards', note=note)


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
    # If the card doesn't exist, there's no parent.
    # (That happens if you're adding a card in the GUI, but don't save it.)
    note_ids = invoke('cardsToNotes', cards=[card_id])
    if not note_ids:
        return

    note_id, = note_ids
    return note_id


def delete_card(card_id):
    note_id = card_to_note(card_id)
    if not note_id:
        # This happens if the card wasn't saved when first being added.
        # So, the note_id that we were given no longer exists
        return None

    # This unfortunately doesn't return any success code
    invoke('deleteNotes', notes=[note_id])
    return True


def wrapper(string):
    LINE_WIDTH = os.get_terminal_size().columns
    WRAP_WIDTH = int(LINE_WIDTH * .8)

    lines_wrapped = []
    for line in string.splitlines():
        line_wrap = textwrap.wrap(line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=False)
        line_wrap = line_wrap or ['']
        lines_wrapped += line_wrap
    string = "\n".join(lines_wrapped)
    return string


def render_card(card, *, term=None):
    f = card['fields']['Front']['value']
    b = card['fields']['Back']['value']
    deck = card['deckName']

    b_rendered = render(b, highlight=term, front=f, deck=deck)

    if '<' in f or '&nbsp;' in f:
        # TODO technically this should be a warn_print
        info_print("Warning: 'Front' field with HTML hinders exact match search.")
        # Auto-clean it?
        if True:
            # Rendering removes the HTML, for console printing
            cleaned = render(f).strip()
            card_id = card['cardId']
            update_card(card_id, front=cleaned)
            info_print(f"Updated to:")
            # Get again from Anki to verify updated card
            return render_card(get_card(card_id))

    return b_rendered


def sync():
    invoke('sync')
    # And minimize it again
    os.system(WINDOW_MIN)


def clear_line():
    if options.debug:
        print()
    LINE_WIDTH = os.get_terminal_size().columns
    print('\r' + (' ' * LINE_WIDTH) + '\r', end='', flush='True')


def clear_screen():
    if not options.debug:
        print('\033c')


def scroll_screen():
    if not options.debug:
        print("\n" * os.get_terminal_size().lines)


def beep():
    print("\a", end='', flush=True)


def main(deck):
    global options

    # The previous search term
    term = None

    # The locally found card(s)
    card_ids = []
    card_ids_i = 0
    card_id = None

    # Across the deck, the number(s) of wildcard matches on the front/back of other cards
    wild_n = None

    # The content/definition of the current (locally/remotely) found card
    content = None
    menu = ''

    # Spell-scheck suggestions returned from the remote fetch/search?
    global suggestions
    suggestions = []

    # Any local changes (new/deleted cards) pending sync?
    edits_n = 0

    # The IDs of cards that only have a front, but not back (no definition)
    # This works like a queue of cards to be deleted, fetched and (re)added.
    # (Because it's easier to just delete and re-add than to update ? TODO)
    empty_ids = []

    # Clear/Scroll screen (we scroll here because 'clear' would erase history)
    # TODO consider switching to curses lib
    if not options.debug:
        scroll_screen()

    while True:
        # Set card_id and content based on card_ids and card_ids_i
        if card_ids:
            # TODO cache/memoize get_card() results
            cards = [ { 'id': id,'term': get_card(id)['fields']['Front']['value'] } for id in card_ids ]

            # TODO consider caching get_card() and render_card() for the cards in this set.
            # And maybe use card_ids_i = None as a signal that sort is needed, since it's not always needed.
            # cards = sorted(cards, key=lambda x: x['term'])

            card_ids = [c['id'] for c in cards ]
            card_id = card_ids[card_ids_i]
            card = get_card(card_id)
            content = render_card(card)
        else:
            card_id = None

        # Remind the user of any previous context, and then allow to Add
        content = content or ''

        # Clear the top of the screen
        # But ensure that it lines up, so that PgUp and PgDown on the terminal work one-def-at-a-time
        # TODO refactor this into scroll_screen
        rendered = render(content, highlight=term, deck=deck)
        rendered = wrapper(rendered)
        if not options.debug:
            lines_n = os.get_terminal_size().lines - len(re.findall("\n", rendered))
            # TODO refactor this out into a scroll() def and call it also after changing deck
            # With default being os.get_terminal_size().lines - 4 (or whatever lines up)
            # And make the 4 a constant BORDERS_HEIGHT
            info_print()
            print("\n" * lines_n)
        print(rendered, "\n")

        if term and not content:
            info_print("No results: " + term)
            if wild_n:
                info_print(f"(W)ilds:" + COLOR_VALUE + str(wild_n) + RESET)

        if suggestions:
            info_print("Did you mean: (press TAB for autocomplete)")
            print("\n".join(suggestions))

        print(menu + '\r', end='', flush=True)

        # spell-checker:disable
        menu = [ '' ]

        if not term:
            menu += [ "        " ]
        else:
            if not card_id:
                menu += [ COLOR_WARN + "?" + RESET ]
                menu += [ "(A)dd    " ]
                menu += [ "(F)etch  " ]
            else:
                menu += [ COLOR_OK + "✓" + RESET]
                menu += [ "Dele(t)e " ]
                menu += [ "(R)eplace" ]
                if len(card_ids) > 1:
                    # Display in 1-based counting
                    menu += [
                        "(N)/(P):" + COLOR_VALUE + f"{card_ids_i+1:2d}/{len(card_ids):2d}" + RESET,
                    ]

        menu += [ '|' ]
        menu += [ "(D)eck:" + COLOR_VALUE + deck + RESET]
        if edits_n:
            menu += [ COLOR_WARN + "*" + RESET ]
        else:
            menu += [ ' ' ]

        if n_old := get_old(deck) :
            menu += [ "mature:" + COLOR_VALUE + str(n_old) + RESET ]
        if n_mid := get_mid(deck) :
            menu += [ "young:"  + COLOR_VALUE + str(n_mid) + RESET ]
        if n_due := get_due(deck) :
            menu += [ "due:"    + COLOR_VALUE + str(n_due) + RESET ]
        # if n_new := get_new(deck) :
        #     menu += [ "new:" + COLOR_VALUE + str(n_new) + RESET ]

        # TODO send each popped result through $PAGER .
        # Rather, since it's just a Fetch, do the $PAGER for any Fetch
        if empty_ids := get_empties(deck):
            menu += [ "(E)mpties:" + COLOR_WARN + str(len(empty_ids)) + RESET ]

        menu += [ "|", "(S)earch" ]
        if term:
            menu += [
                COLOR_VALUE + term + RESET,
                "(G)oogle", "(B)rowse",
            ]

            if wild_n:
                menu += [ f"(W)ilds:" + COLOR_VALUE + str(wild_n) + RESET + ' more' ]

        # spell-checker:enable

        menu = ' '.join(menu)
        menu = re.sub(r'\(', COLOR_COMMAND, menu)
        menu = re.sub(r'\)', RESET, menu)

        key = None
        while not key:
            clear_line()
            print(menu + '\r', end='', flush=True)
            key = readchar.readkey()

            # TODO smarter way to clear relevant state vars ?
            # What's the state machine/diagram behind all these?

            # / ↑ Search
            # a Add
            # b Browse/list matching cards in Anki GUI
            # d Deck
            # f Fetch / lookup / Definition / Query
            # g Google
            # n Next
            # p Prev / Shift-n, or up key ↑
            # r Replace
            # s Search, or '/' key
            # t Delete
            # w Wildcard matches (in front or back fields)
            # y Sync
            # * Sync

            if key in KEYS_CLOSE:
                clear_line()
                exit()
            elif key == '.':
                # Reload (for 'live' editing / debugging)
                tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
                ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
                info_print(f"pid: {os.getpid()} mtime: {ts} execv: {sys.argv[0]}")
                os.execv(sys.argv[0], sys.argv)
            elif key in ('\x0c', '\x03'):
                # Ctrl-L or Ctrl-C clear screen
                clear_screen()
            elif key == 'd':
                # Switch deck
                # TODO refactor this out. Or use a curses lib.
                decks = get_deck_names()
                scroll_screen()
                print(COLOR_COMMAND)
                print("\n * ".join(['', *decks]))
                print(RESET)

                deck_prev = options.deck
                # Block autocomplete of dictionary entries
                options.deck = None
                # Push deck names onto readline history stack, for ability to autocomplete
                hist_len_pre = readline.get_current_history_length()
                for d in decks:
                    readline.add_history(d)

                try:
                    selected = input("Switch to deck: ")
                except:
                    options.deck = deck_prev
                    continue
                finally:
                    # Remove the deck names, as no longer needed in (word) history.
                    # This isn't just (hist_len_post - hist_len_pre) , because it
                    # depends on how many times the user completed.
                    hist_len_post = readline.get_current_history_length()
                    for i in range(hist_len_post, hist_len_pre, -1):
                        readline.remove_history_item(i-1) # zero-based indexes

                if not selected in decks:
                    beep()
                    continue
                deck = selected
                # This is so that `completer()` can know what lang/deck we're using
                options.deck = deck

                term = None
                card_id = None
                card_ids = []
                card_ids_i = 0
                wild_n = None
                suggestions = []
                content = None
                scroll_screen()
            elif key in ['y', '*']:
                sync()
                edits_n = 0
            elif key == 't' and card_id:
                if delete_card(card_id):
                    edits_n += 1
                    del card_ids[card_ids_i]
                    card_ids_i = max(0, card_ids_i - 1)
                    content = None
                    scroll_screen()
                else:
                    beep()
            elif key == 'b' and term:
                # Open Anki GUI Card browser/list,
                # for the sake of editing/custom searches
                if len(card_ids) > 1:
                    # Wildcard search fronts and backs
                    search_anki(term, deck=deck, field=None, browse=True)
                else:
                    # Search 'front' for this one card
                    search_anki(term, deck=deck, field='front', browse=True)
            elif key == 'w' and wild_n:
                # wildcard search all fields (front, back, etc)
                card_ids = search_anki(term, deck=deck, field=None)
                card_ids_i = 0
                wild_n = None
                suggestions = []
            elif key in ('n') and card_ids_i < len(card_ids) - 1:
                card_ids_i += 1
            elif key in ('p', 'N') and card_ids_i > 0:
                card_ids_i -= 1

            elif key == 'f' and term:
                # Fetch (remote dictionary service)
                obj = search(term, lang=deck)
                content = obj and obj.get('definition')
                suggestions = obj and obj.get('suggestions') or []
                if content:
                    card_id = None
                    card_ids = []
                # If any, suggestions/content printed on next iteration.

            elif key == 'r' and term:
                # Replace old content (check remote dictionary service first).
                # Get the 'front' value of the last displayed card,
                # since this might be a multi-resultset
                front = card['fields']['Front']['value']
                obj = search(front, lang=deck)
                content = obj and obj.get('definition')
                suggestions = obj and obj.get('suggestions') or []

                if card_id and content:
                    rendered = render(content, highlight=front, deck=deck)
                    rendered = wrapper(rendered)
                    info_print()
                    print(rendered, "\n")
                    try:
                        prompt = "Replace " + COLOR_COMMAND + front + RESET + " with this definition? N/y: "
                        reply = input(prompt)
                    except:
                        reply = None
                    if reply and reply.casefold() == 'y':
                        update_card(card_id, back=content)

            elif key == 'g' and term:
                search_google(term)
            elif key == 'o' and term:
                url_term = urllib.parse.quote(term) # For web searches
                # TODO this should use whatever the currently active dictionary is
                url=f'http://www.woorden.org/woord/{url_term}'
                launch_url(url)
            elif key == 'a' and not card_id:
                add_card(term, content, deck=deck)
                edits_n += 1

                # And search it to verify
                card_ids = search_anki(term, deck=deck)
                card_ids_i = 0
            elif key == 'e' and empty_ids:
                card_id = empty_ids[0]
                term = get_card(card_id)['fields']['Front']['value']
                delete_card(card_id)
                empty_ids = get_empties(deck)
                card_id = None
                card_ids = []
                wild_n  = None
                edits_n += 1
                # Update readline, as if I had searched for this term
                readline.add_history(term)

                # auto fetch
                clear_line()
                obj = search(term, lang=deck)
                content = obj and obj.get('definition')
                suggestions = obj and obj.get('suggestions') or []
                # If any, suggestions/content printed on next iteration.

            elif key in ('s', '/', '\x10', '\x1b[A'):
                # Exact match search
                # The \x10 is Ctrl-P which is readline muscle memory for 'previous' line.
                # The \x1b[A is the up key ↑ which is readline muscle memory for 'previous' line.

                content = None
                suggestions = []

                # TODO factor the prompt of 'term' into a function?
                clear_line()
                try:
                    term = input(f"Search: {COLOR_VALUE + deck + RESET}/")
                except:
                    continue
                term = term.strip()
                if not term:
                    continue

                # Allow to switch deck and search in one step, via a namespace-like search.
                # (Assumes that deck names are 2-letter language codes)
                # e.g. 'nl:zien' would switch deck to 'nl' first, and then search for 'zien'.
                # Also allow separators [;/:] to obviate pressing Shift
                decks_re = '|'.join(decks := get_deck_names())
                if match := re.match('\s*([a-z]{2})\s*[:;/]\s*(.*)', term):
                    lang, term = match.groups()
                    if re.match(f'({decks_re})', lang):
                        deck = lang
                else:
                    lang = deck

                card_ids = search_anki(term, deck=deck)
                card_ids_i = 0
                # Check other possible query types:
                # TODO do all the searches (by try to minimise exact and wildcard into one request)
                # eg 'wild_n' will always contain the exact match, if there is one, so it's redundant

                wild_n = len(set(search_anki(term, deck=deck, field=None)) - set(card_ids))
                if not card_ids: # and not wild_n:
                    # Fetch (automatically when no local matches)
                    card_id = None
                    content = None

                    if '*' in term:
                        continue

                    obj = search(term, lang=lang)
                    content = obj and obj.get('definition')
                    suggestions = obj and obj.get('suggestions') or []
                    # If any, suggestions/content printed on next iteration.

            else:
                # Unrecognized command.
                print("\a", end='', flush=True)


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
    global options
    if options.deck and not completions:
        card_ids = search_anki(text + '*', deck=options.deck)
        for card_id in card_ids:
            term = get_card(card_id)['fields']['Front']['value']
            if ud(term).casefold().startswith(text.casefold()):
                completions += [ term ]

    if state < len(completions):
        return completions[state]

    if state == 0:
        # text doesn't match any possible completion
        beep()


if __name__ == "__main__":
    decks = get_deck_names()
    parser = OptionParser()
    parser.add_option('-d', "--debug", dest='debug', action='store_true')
    parser.add_option("-k", "--deck", dest="deck",
        help="Name of Anki deck to use (must be a 2-letter language code, e.g. 'en')"
        )
    (options, args) = parser.parse_args()
    if not options.deck:
        # Take the first deck by default; fail if there are none
        options.deck = decks[0]

    readline.set_completer(completer)
    readline.set_completer_delims('')
    readline.parse_and_bind("tab: complete")

    # Set terminal title, to be able to search through windows
    sys.stdout.write('\x1b]2;' + "Anki CLI card mgr" + '\x07')

    main(options.deck)
