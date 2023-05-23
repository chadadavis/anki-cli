#!/usr/bin/env python3
"""Anki add - fetch online definitions and add cards to Anki vocabulary decks

Based on this API: https://github.com/FooSoft/anki-connect/

A note on searching for declined / conjugated forms of words:

It would be nice to confirm that the content fetched corresponds to the term
searched, rather than a declined form. However, each dictionary provider does
this differently, and not even consistently within a given language, as it may
depend on the part of speech of the term. So, the user simply needs to be beware
that if the definition shows a different canonical form, then they should
re-search for the canonical form, and then add that term instead. (This should
be clearly visible if this has happened, because the search term, if present,
will be highlighted in the displayed text.)

For example, in Dutch, searching for 'geoormerkt' (a past participle) will
return the definition for 'oormerken' (the infinitive). In that case, you'd
rather not add that card, but rather re-search for 'oormerken', now that you
know what the base form is, and add the latter as a new card instead.

A note regarding text-only (non-HTML) cards:

Using text-only cards (non-HTML) implies that when you want to use the Anki GUI
to edit a card, then you should be using the source editor (Ctrl-Shift-X),
rather than the WYSIWYG/rich-text editor.

Even with the source editor, if you ever edit a card in the Anki GUI and it
contains an ampersand `&`, eg `R&D` , in the front or back fields, then it'll be
automatically HTML-encoded anew as `R&amp;D` in the source. That means your text
searches for 'R&D' won't find that match.

If you re-view that card from this CLI, the source text can be fixed/updated
anew.

Cards should to use the CSS style: `white-space: pre-wrap;` to enable wrapping
of raw text.

"""

# Note, that regex search in Anki is supported from 2.1.24+ onward
# https://apps.ankiweb.net/
# https://docs.ankiweb.net/searching.html
# https://docs.rs/regex/1.3.9/regex/#syntax
# But it unfortunately doesn't help much for the NL words from woorden.org due to the non-consistent format.

import html
import json
import os
import readline
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from difflib import Differ
from enum import StrEnum
from optparse import OptionParser

import autopage
import readchar
# The override for `re` is necessary for wildcard searches, due to extra interpolation.
# Otherwise 're' raises an exception. Search for 'regex' below.
# https://learnbyexample.github.io/py_regular_expressions/gotchas.html
# https://docs.python.org/3/library/re.html#re.sub
# "Unknown escapes of ASCII letters are reserved for future use and treated as errors."
import regex as re
import unidecode
# NB, the pip package is called iso-639 (with "-"). And this is TODO DEPRECATED
# DEPRECATION: iso-639 is being installed using the legacy 'setup.py install'
# method, because it does not have a 'pyproject.toml' and the 'wheel' package is
# not installed. pip 23.1 will enforce this behavior change. A possible
# replacement is to enable the '--use-pep517' option. Discussion can be found at
# https://github.com/pypa/pip/issues/8559
from bs4 import BeautifulSoup
from iso639 import languages
from nltk.stem.snowball import SnowballStemmer


# This bogus def just makes it easier for me to jump here in my editor
def backlog():
    ...

# Backlog/TODO

# BUG parsing broken for words that aren't in Woorden, but extracted from 3rd parties, eg encyclo.nl
#  'stokken', 'tussenin', 'hangertje'

# Make the 'o' command open whatever the source page was (not just woorden.org)

# TODO make a class for a Card ?
# Easiest to just use:
# https://docs.python.org/3/library/dataclasses.html
# from dataclasses import dataclass
# @dataclass
# class Card:
#     front: str
#     back: str
#     ...
# So, we don't have to keep digging into card['fields']...
# But maybe I need some accessors ... or a constructor to breadown the card['fields']... Or maybe a 'match' statement?

# TODO Address Pylance issues, eg type hints

# TODO consider switching to curses lib

# Replace colors with `termcolor` lib?
# TODO consider colorama here?

# Run the queries needed to update the menu in a separate thread, update the UI quicker

# BUG no NL results from FD (from FreeDictionary)
# Why does EN work when NL doesn't?
# If Woorden is often unavailable, make this configurable in the menu (rather than hard-coded)?

# Is there an API for FD? Doesn't seem like it.

# Use freeDictionary API, so as to need less regex parsing
# https://github.com/Max-Zhenzhera/python-freeDictionaryAPI/

# Add support for wiktionary? (IPA?) ?
# eg via ? https://github.com/Suyash458/WiktionaryParser

# Add nl-specific etymology?
# https://etymologiebank.nl/

# FR: Or use a diff source, eg TV5
# https://langue-francaise.tv5monde.com/decouvrir/dictionnaire/f/franc

# Add DWDS for better German defs (API?). But get IPA pronunciation elsewhere
# (eg FreeDictionary or Wiktionary)

# TODO
# Think about how to add multiples webservices for a single deck/lang (?)
# Eg beyond a dictionary, what about extra (web) services for:
# synonyms, pronunciation, etymology, etc, or just allowing for multiple search providers
# Maybe just:
# { lang: en, dict: dictionary.com, syn/thes: somesynservice.com, ipa: some ipa service, etym: etymonline.com, ...}
# Get IPA from Wiktionary (rather than FreeDictionary)?
# And maybe later think about how to combine/concat these also to the same anki card ...

# Logging:
# look for log4j style debug mode console logging/printing (with colors)

# Anki: unify note types (inheritance), not for this code, but in the app.
# Learn what the purpose of different notes types is, and then make them all use
# the same, or make them inherit from each other, so that I don't have to
# configure/style a separate note type for each language.

# Since I'd also like to try to make formatted text versions for other
# languages, maybe regex-based rendering isn't the most sustainable approach.
# Replace regex doc parsing with eg
# https://www.scrapingbee.com/blog/python-web-scraping-beautiful-soup/
# And use CSS selectors to extract content more robustly
# use BeautifulSoup?
# Convert HTML to Markdown?
# Consider library html2text
# Would an XSLT, per source, make sense for the HTML def content?
# https://www.w3schools.com/xml/xsl_intro.asp

# Consider alternative addons for Anki (for creating new cards using online dicts)
# https://ankiweb.net/shared/info/1807206748
# https://github.com/finalion/WordQuery
# All addons:
# https://ankiweb.net/shared/addons/

# Repo/Packaging:
# figure out how to package deps (eg readchar) and test it again after removing local install of readchar

# Move this dir to its own repo
# https://manpages.ubuntu.com/manpages/kinetic/en/man1/git-filter-repo.1.html

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

# See other TODOs below ...

################################################################################


# Color codes:
# The leading '1;' makes a foreground color bold/bright as well.
# https://stackoverflow.com/a/33206814/256856
YELLOW    = "\033[0;33m"
YELLOW_LT = "\033[1;33m"
YELLOW_BT = "\033[0;93m" #Bright
GREEN     = "\033[0;32m"
GREEN_LT  = "\033[1;32m"
BLUE      = "\033[0;34m"
BLUE_LT   = "\033[1;34m"
RED       = "\033[0;31m"
RED_LT    = "\033[1;31m"
GRAY      = "\033[0;02m"
GRAY_LT   = "\033[1;02m"
WHITE     = "\033[0;37m"
WHITE_LT  = "\033[1;37m"
RESET     = "\033[0;00m"

# Abstract colors into use cases, in case we want to change the mapping later
COLOR_COMMAND   = WHITE_LT
COLOR_WARN      = YELLOW_LT
COLOR_INFO      = GRAY
COLOR_OK        = GREEN_LT
COLOR_VALUE     = GREEN_LT
COLOR_HIGHLIGHT = YELLOW_BT
COLOR_RESET     = RESET


class Key(StrEnum):
    # The Esc key is doubled, since it's is a modifier and isn't accepted solo
    ESC_ESC = '\x1b\x1b'
    CTRL_C  = '\x03'
    CTRL_D  = '\x04'
    CTRL_P  = '\x10'
    CTRL_W  = '\x17'
    UP      = '\x1b[A'


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
        return None


def get_deck_names():
    names = sorted(invoke('deckNames'))
    # Filter out sub-decks
    # names = [ i for i in names if not '::' in i]
    return names


def renderer(string, query=None, *, term=None, deck=None):
    """For displaying (already normalized) definition entries on the terminal/console/CLI"""

    # Prepend term in canonical format, for display only
    if term:
        string = term + "\n\n" + string

    string = wrapper(string)
    # Ensure one newline at the end
    string = re.sub(r'\n*$', '\n', string)
    string = highlighter(string, query, term=term, deck=deck)

    return string


def normalizer(string, *, term=None):
    """Converts HTML to text, for saving in Anki DB"""

    # Specific to woorden.org
    # Before unescaping HTML entities: Replace (&lt; and &gt;) with ( and )
    string = re.sub(r'&lt;|《', '(', string)
    string = re.sub(r'&gt;|》', ')', string)
    string = re.sub(r'&nbsp;', ' ', string)
    # Other superfluous chars:
    string = re.sub(r'《/?em》|«|»', '', string)

    # Replace HTML entities with unicode chars (for IPA symbols, etc)
    string = html.unescape(string)

    # Remove tags that are usually in the phonetic markup
    string = re.sub(r'</?a\s+.*?>', '', string)

    # Remove references like [3], since we probably don't have the footnotes too
    string = re.sub(r'\[\d+\]', '', string)

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
        ,'cinema'
        ,'commercie'
        ,'computers?'
        ,'constructie'
        ,'culinair'
        ,'defensie'
        ,'educatie'
        ,'electriciteit'
        ,'electronica'
        ,'financieel'
        ,'formeel'
        ,'geschiedenis'
        ,'handel'
        ,'informatica'
        ,'informeel'
        ,'internet'
        ,'juridisch'
        ,'kunst'
        ,'landbouw'
        ,'medisch'
        ,'metselen'
        ,'muziek'
        ,'ouderwets'
        ,'politiek'
        ,'religie'
        ,'slang'
        ,'speelgoed'
        ,'sport'
        ,'spreektaal'
        ,'taal'
        ,'technisch'
        ,'theater'
        ,'transport'
        ,'verouderd'
        ,'visserij'
        ,'vulgair'
    ]
    # spell-checker:enable

    # If we still have the HTML tags, then we can see if this topic category is new to us.
    # Optionally, it can then be manually added to the list above.
    # Otherwise, they wouldn't be detected in old cards, if it's not already in [brackets]
    for match in re.findall(r'<sup>([a-z]+?)</sup>', string) :
        category = match
        # debug_print(f'{category=}')
        # If this is a known category, just format it as such.
        # (We're doing a regex match here, since a category name might be a regex.)
        string = re.sub(r'<sup>(\w+)</sup>', r'[\1]', string)
        if any([ re.search(c, category, re.IGNORECASE) for c in categories ]):
            ...
        else:
            # Notify, so you can (manually) add this one to the 'categories' list above.
            print(f'\nNew category [{COLOR_WARN}{category}{COLOR_RESET}]\n',)
            beep()
            time.sleep(5)

    # Replace remaining <sup> tags
    string = re.sub(r'<sup>', r'^', string)

    # Specific to: PONS Großwörterbuch Deutsch als Fremdsprache
    string = re.sub('<span class="illustration">', '\n', string)

    # Specific to fr.thefreedictionary.com (Maxipoche 2014 © Larousse 2013)
    string = re.sub('<span class="Ant">', '\nantonyme: ', string)
    string = re.sub('<span class="Syn">', '\nsynonyme: ', string)

    # Specific to en.thefreedictionary.com (American Heritage® Dictionary of the English Language)
    string = re.sub(r'<span class="pron".*?</span>', '', string)
    # Replace headings that just break up the word into syl·la·bles, since we get that from IPA already
    string = re.sub(r'<h2>.*?·.*?</h2>', '', string)
    # For each new part-of-speech block
    string = re.sub(r'<div class="pseg">', '\n\n', string)

    # Add spaces around em dash — for readability
    string = re.sub(r'(\S)—(\S)', r'\1 — \2', string)

    # HTML-specific:
    # Remove span/font tags, so that the text can stay on one line
    string = re.sub(r'<span\s+.*?>', '', string)
    string = re.sub(r'<font\s+.*?>', '', string)
    # These HTML tags <i> <b> <u> <em> are usually used inline and should not have a line break
    string = re.sub(r'<(i|b|u|em)>', '', string)

    string = re.sub(r'<br\s*/?>', '\n\n', string)
    string = re.sub(r'<hr.*?>', '\n\n___\n\n', string)

    # Headings on their own line, by replacing the closing tag with \n
    string = re.sub(r'</h\d>\s*', '\n', string)

    # Tables, with \n\n between rows
    string = re.sub(r'<td.*?>', '', string)
    string = re.sub(r'<tr.*?>', '\n\n', string)

    # Replace remaining opening tags with a newline, since usually a new section
    string = re.sub(r'<[^/].*?>', '\n', string)
    # Remove remaining (closing) tags
    string = re.sub(r'<.*?>', '', string)

    # Segregate pre-defined topical category names
    # Wrap in '[]', the names of topical fields.
    # (when it's last (and not first) on the line)
    categories_re = '|'.join(categories)
    string = re.sub(f'(?m)(?<!^)\\s+({categories_re})$', r' [\1]', string)

    # Non-HTML-specific:
    # Collapse sequences of space/tab chars
    string = re.sub(r'\t', ' ', string)
    string = re.sub(r' {2,}', ' ', string)

    # NL-specific (or specific to woorden.org)
    string = re.sub(r'Toon alle vervoegingen', '', string)
    # Remove hover tip on IPA pronunciation
    string = re.sub(r'(?s)<a class="?help"? .*?>', '', string)
    # Ensure headings begin on their own line (also covers plural forms, eg "Synoniemen")
    string = re.sub(r'(?m)(?:\n*)(Afbreekpatroon|Uitspraak|Vervoeging|Verbuiging|Synoniem|Antoniem)', r'\n\1', string)

    # NL-specific: Newlines (just one) before example `phrases in backticks`
    # (but not *after*, else you'd get single commas on a line, etc)
    string = re.sub(r'(?m)(?:\n*)(`.*?`)', r'\n\1', string)

    # One, and only one, newline \n after colon :
    string = re.sub(r'(?m):(\s+|$)\n*', r':\n', string)

    # Remove seperators in plurals (eg in the section: "Verbuigingen")
    string = re.sub(r'\|', '', string)

    # Ensure 1) and 2) sections start a new paragraph
    string = re.sub(r'(?m)^(\d+\))', r'\n\n\1', string)
    # Ensure new sections start a new paragraph, eg I. II. III. IV.
    string = re.sub(r'(?m)^(I{1,3}V?\s+)', r'\n\n\1', string)

    # DE-specific:
    # Ensure new sections start a new paragraph, eg I. II. III. IV.
    string = re.sub(r'\s+(I{1,3}V?\.)', r'\n\n\1', string)
    # New paragraph for each definition on the card, marked by eg: ...; 1. ...
    string = re.sub(r';\s*(\d+\. +)', r'\n\n\1', string)
    string = re.sub(r'(?m)^\s*(\d+\. +)', r'\n\n\1', string)
    # And sub-definitions, also indented, marked by eg: a) or b)
    string = re.sub(r';?\s+([a-z]\) +)', r'\n  \1', string)
    # Newline after /Phrases in slashes/ often used a context, if it's the start of the line
    string = re.sub(r'(?m)^\s*(/.*?/)\s*', r'\1\n', string)

    # Max 2x newlines in a row
    string = re.sub(r'(\s*\n\s*){3,}', '\n\n', string)

    # Delete leading/trailing space on each line
    string = re.sub(r'(?m)^ +', '', string)
    string = re.sub(r'(?m) +$', '', string)

    # Delete leading space on the entry as a whole
    string = re.sub(r'^\s+', '', string)

    # Canonical final newline
    string = re.sub(r'\s*$', '', string)
    string = string + '\n'

    if term:
        # Strip redundant term at start of card
        string = re.sub(r'^\s*' + term + r'\s*', r'', string)

    return string


def highlighter(string, query, *, term=None, deck=None):

    # Map wildcard search chars to regex syntax
    query = re.sub(r'[.]', r'\.', query)
    query = re.sub(r'[_]', r'.', query)

    # Even though this is a raw string, the '\' needs to be escaped, because
    # the 're' module raises an exception for any escape sequences that are
    # not valid in a standard string. (The 'regex' module doesn't.)
    # https://learnbyexample.github.io/py_regular_expressions/gotchas.html
    # https://docs.python.org/3/library/re.html#re.sub
    # "Unknown escapes of ASCII letters are reserved for future use and treated as errors."
    query = re.sub(r'[*]', r'[^ ]*', query)

    # Terms to highlight
    highlights = { query }

    # Collapse double letters in the search term
    # eg ledemaat => ledemat
    # So that can now also match 'ledematen'
    # This is because the examples in the 'back' field will include declined forms
    collapsed = re.sub(r'(.)\1', r'\1', query)
    if collapsed != query:
        highlights.add(collapsed)

    if term:
        # Also highlight the canonical form, in case the search query was different
        highlights.add(term)

    term_or_query = unidecode.unidecode(term or query)

    # TODO also factor out the stemming (separate from highlighting, since lang-specific)
    if deck:
        # Map e.g. 'de' to 'german', as required by SnowballStemmer
        lang = languages.get(alpha2=deck).name.lower()
        stemmer = SnowballStemmer(lang)
        stem = stemmer.stem(query)
        if stem != query:
            highlights.add(stem)

    # Language/source-specific extraction of inflected forms
    if deck == 'nl':
        # Hack stemming, assuming -en suffix, but not for short words like 'een'
        # For cases: verb infinitives, or plural nouns without singular
        # eg ski-ën, hersen-en
        highlights.add( re.sub(r'(..)en$', r'\1\\S*', term_or_query) )

        # And adjectives/nouns like vicieus/vicieuze or reus/reuze or keus/keuze
        if term_or_query.endswith('eus') :
            highlights.add( re.sub(r'eus$', r'euz\\S*', term_or_query) )

        # Find given inflections

        matches = []
        # Theoretically, we could not have a double loop here, but this makes it easier to read.
        # There can be multiple inflections in one line (eg prijzen), so it's easier to have two loops.
        for inflection in re.findall(r'(?m)^\s*(?:Vervoegingen|Verbuigingen):\s*(.*?)\s*$', string):
            # There is not always a parenthetical part-of-speech after the inflection of plurals.
            # Sometimes it's just eol (eg "nederlaag") . So, it ends either with eol $ or open paren (
            match = re.findall(r'(?s)(?:\)|^)\s*(.+?)\s*(?:\(|$)', inflection)
            matches += match

        for match in matches:

            # Remove separators, e.g. in "Verbuigingen: uitlaatgas|sen (...)"
            match = re.sub(r'\|', '', match)

            # If past participle, remove the 'is' or 'heeft'
            # Sometimes as eg: uitrusten: 'is, heeft uitgerust' or 'heeft, is uitgerust'
            match = re.sub(r'^(is|heeft)(,\s+(is|heeft))?\s+', '', match)
            # And the reflexive portion 'zich' isn't necessary, eg: "begeven"
            match = re.sub(r'\bzich\b', '', match)

            # This is for descriptions with a placeholder char like:
            # "kind": "Verbuigingen: -eren" => "kinderen"
            # "homo": "'s" => "homo's"
            match = re.sub(r"^[-'~]", term_or_query, match)

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
            if term_or_query.endswith('ven') and match.endswith('f'):
                highlights.add( re.sub(r'ven$', '', term_or_query) + 'f' )
            if term_or_query.endswith('zen') and match.endswith('s'):
                highlights.add( re.sub(r'zen$', '', term_or_query) + 's' )

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
                base = re.sub(f'^{pre}', '', term_or_query)
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
        if term_or_query.endswith('en'):
            highlights.add( re.sub(r'en$', '', term_or_query) )

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
            l.insert(y, COLOR_RESET)
            l.insert(x, COLOR_HIGHLIGHT)

        string = ''.join(l)
    else:
        # We can't do accent-insensitive hightlighting.
        # Just do case-insensitive highlighting.
        # NB, the (?i:...) doesn't create a group.
        # That's why ({highlight}) needs it's own parens here.
        string = re.sub(f"(?i:({highlight_re}))", COLOR_HIGHLIGHT + r'\1' + COLOR_RESET, string)

    return string


def search(term, *, lang):
    obj = {}

    if lang == 'nl':
        content = search_woorden(term)
        obj['definition'] = content
        return obj

    obj = search_thefreedictionary(term, lang=lang)
    return obj


def search_anki(query, *, deck, wild=False, field='front', browse=False, term=''):

    # If term contains whitespace, either must quote the whole thing, or replace spaces:
    search_query = re.sub(r' ', '_', query) # For Anki searches

    # TODO accent-insensitive search?
    # eg exploit should find geëxploiteerd
    # It should be possible with Anki's non-combining mode: nc:geëxploiteerd
    # https://docs.ankiweb.net/#/searching
    # But doesn't seem to work
    # Or see how it's being done inside this addon:
    # https://ankiweb.net/shared/info/1924690148

    search_terms = [search_query]

    # Collapse double letters \p{L} into a disjunction, eg: (NL-specific)
    # This implies that the user should, when in doubt, use double chars in the query
    # deck:nl (front:maaken OR front:maken)
    # or use a re: (but that doesn't seem to work)
    # TODO BUG: this isn't a proper Combination (maths), so it misses some cases
    # TODO consider a stemming library here?
    if deck == 'nl':
        while True:
            next_term = re.sub(r'(\p{L})\1', r'\1', search_query, count=1)
            if next_term == search_query:
                break
            search_terms += [next_term]
            search_query = next_term

    if field:
        if wild:
            # Wrap *stars* around (each) term.
            # Note, only necessary if using 'field', since it's default otherwise
            search_terms = map(lambda x: f'*{x}*', search_terms)

        search_terms = map(lambda x: field + ':' + x, search_terms)

        # Regex search of declinations:
        # This doesn't really work, since the text in the 'back' field isn't consistent.
        # Sometimes there's a parenthetical expression after the declination, sometimes not
        # So, I can''t anchor the end of it, which means it's the same as just a wildcard search across the whole back.
        # eg 'Verbuigingen.*{term}', and that's not any more specific than just searching the whole back ...
        # if field == 'front' and deck == 'nl':
        #     # Note, Anki needs the term in the query that uses "re:" to be wrapped in double quotes (also in the GUI)
        #     terms = [*terms, f'"back:re:(?s)(Verbuiging|Vervoeging)(en)?:(&nbsp;|\s|<.*?>|heeft|is)*{term}\\b"' ]

        # TODO since we parse these out from the highlighter() (if it's
        # reliable), we could (auto?) add these as tags to the cards, and then
        # also search the tags (?)

    search_query = f'deck:{deck} (' + ' OR '.join([*search_terms]) + ')'
    # debug_print(f'{query=}')

    if browse:
        # In browse mode, also search for any singular term. This is useful when
        # paging through a resultset, but I want to edit the current card. Then
        # the browse UI will only show this one card, but if I want to see the
        # rest of the cards, then I can just delete this final term from the
        # query field in the UI.
        card_ids = invoke('guiBrowse', query=search_query + ' ' + term)
    else:
        card_ids = invoke('findCards', query=search_query)
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
    LINE_WIDTH = os.get_terminal_size().columns

    print(COLOR_INFO, end='')
    print('─' * LINE_WIDTH)
    print(COLOR_RESET, end='')
    if values:
        print(*values)
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
    print(COLOR_INFO + f"Fetching: {url} ..." + COLOR_RESET, end='', flush=True)

    try:
        response = urllib.request.urlopen(url)
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

    match = re.search(f"(?s)(<h2.*?{term}.*?)(?=&copy|Bron:|<div|</div)", content)
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
    print(COLOR_INFO + f"Fetching: {url} ..." + COLOR_RESET, end='', flush=True)
    try:
        response = urllib.request.urlopen(url)
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
    match = re.search('<div id="Definition"><section .*?>.*?</section>', content)
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
        line_wrap = textwrap.wrap(line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=True)
        line_wrap = line_wrap or ['']
        lines_wrapped += line_wrap
    string = "\n ".join(lines_wrapped)
    return string


def normalize_card(card):
    front = card['fields']['Front']['value']
    back = card['fields']['Back']['value']
    normalized = normalizer(back, term=front)

    if re.findall(r'<|&[A-Za-z]+;', front) :
        info_print("'Front' field with HTML hinders exact match search.")

        # Auto-clean it?
        if options.debug :
            # Rendering removes the HTML, for console printing
            cleaned = normalizer(front).strip()
            info_print(f'{cleaned=}')
            card_id = card['cardId']
            update_card(card_id, front=cleaned)
            info_print(f"Updated to:")
            # Get again from Anki to verify updated card
            return normalize_card(get_card(card_id))

    return normalized


def sync():
    invoke('sync')


def clear_line():
    if options.debug:
        print()
    LINE_WIDTH = os.get_terminal_size().columns
    print('\r' + (' ' * LINE_WIDTH) + '\r', end='', flush=True)


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
    card = None

    # Across the deck, the number(s) of wildcard matches on the front/back of other cards
    wild_n = None

    # The content/definition of the current (locally/remotely) found card
    content = None
    normalized = None
    menu = ''

    # Spell-scheck suggestions returned from the remote fetch/search?
    global suggestions
    suggestions = []

    # Any local changes (new/deleted cards) pending sync?
    edits_n = 0

    # The IDs of cards that only have a front, but not back (no definition)
    # This works like a queue of cards to be deleted, fetched and (re)added.
    # (Because it's easier to just delete and re-add than to update)
    empty_ids = []

    # Clear/Scroll screen (we scroll here because 'clear' would erase history)
    if not options.debug:
        scroll_screen()

    while True:
        updatable = False
        normalized = ''

        if card_ids:
            # Set card_id and content based on card_ids and card_ids_i
            card_id = card_ids[card_ids_i]
            card = get_card(card_id)
            normalized = normalize_card(card)
            if normalized != card['fields']['Back']['value']:
                updatable = True
        else:
            card_id = None
            # Remind the user of any previous context, (eg to allow to Add)
            if content:
                normalized = normalizer(content, term=term)

        # Save the content, before further display-only modifications
        content = normalized
        if normalized:
            front = (card_ids and card['fields']['Front']['value']) or term or ''
            normalized = renderer(normalized, term, term=front, deck=deck)

        # Clear the top of the screen
        # But ensure that it lines up, so that PgUp and PgDown on the terminal work one-def-at-a-time
        # TODO refactor this into scroll_screen
        if not options.debug:
            lines_n = os.get_terminal_size().lines - len(re.findall("\n", normalized))
            # TODO refactor this out into a scroll() def and call it also after changing deck
            # With default being os.get_terminal_size().lines - 4 (or whatever lines up)
            # And make the 4 a constant BORDERS_HEIGHT
            info_print()
            print("\n" * lines_n)

        # If --auto-scroll (ie when using --auto-update), no need to print every definition along the way
        if not options.scroll :
            with autopage.AutoPager() as out:
                print('\n' + normalized, file=out)

        if term and not content:
            info_print("No results: " + term)
            if wild_n:
                info_print(f"(W)ilds:" + COLOR_VALUE + str(wild_n) + COLOR_RESET)

        if suggestions:
            info_print("Did you mean: (press TAB for autocomplete)")
            print("\n".join(suggestions) + "\n")

        # spell-checker:disable
        menu = [ '' ]

        if options.debug:
            menu += [ COLOR_WARN + "D" + COLOR_RESET]
        if not term:
            menu += [ "        " ]
        else:
            if not card_id:
                menu += [ COLOR_WARN + "+" + COLOR_RESET ]
                menu += [ "(A)dd    " ]
                menu += [ "(F)etch  " ]
            else:
                if updatable:
                    menu += [ COLOR_WARN + "⬆" + COLOR_RESET]
                    menu += [ "(U)pdate " ]
                else:
                    menu += [ COLOR_OK + "✓" + COLOR_RESET]
                    menu += [ "Dele(t)e " ]
                menu += [ "(R)eplace" ]
                if len(card_ids) > 1:
                    # Display in 1-based counting
                    menu += [
                        "(N)/(P):" + COLOR_VALUE + f"{card_ids_i+1:2d}/{len(card_ids):2d}" + COLOR_RESET,
                    ]

        menu += [ '|' ]
        menu += [ "(D)eck:" + COLOR_VALUE + deck + COLOR_RESET]
        if edits_n:
            menu += [ COLOR_WARN + "*" + COLOR_RESET ]
        else:
            menu += [ ' ' ]

        if n_old := get_old(deck) :
            menu += [ "mature:" + COLOR_VALUE + str(n_old) + COLOR_RESET ]
        if n_mid := get_mid(deck) :
            menu += [ "young:"  + COLOR_VALUE + str(n_mid) + COLOR_RESET ]
        if n_due := get_due(deck) :
            menu += [ "due:"    + COLOR_VALUE + str(n_due) + COLOR_RESET ]
        # if n_new := get_new(deck) :
        #     menu += [ "new:" + COLOR_VALUE + str(n_new) + RESET ]

        if empty_ids := get_empties(deck):
            menu += [ "(E)mpties:" + COLOR_WARN + str(len(empty_ids)) + COLOR_RESET ]

        menu += [ "|", "(S)earch" ]
        if term:
            menu += [
                COLOR_VALUE + term + COLOR_RESET,
                "(G)oogle", "(B)rowse",
            ]

            if wild_n:
                menu += [ f"(W)ilds:" + COLOR_VALUE + str(wild_n) + COLOR_RESET + ' more' ]

        # spell-checker:enable

        menu = ' '.join(menu)
        menu = re.sub(r'\(', COLOR_COMMAND, menu)
        menu = re.sub(r'\)', COLOR_RESET, menu)

        key = None
        if options.update and updatable and content:
            # Auto-update this card
            key = 'u'
        elif options.scroll and card_ids and card_ids_i < len(card_ids) - 1 :
            # Auto-scroll through the resultset to the next card. Since the
            # 'update' is checked first, the current card will be updated, if
            # possible, before proceeding to the next card.
            key = 'n'


        info_print()
        while not key:
            clear_line()
            print(menu + '\r', end='', flush=True)
            key = readchar.readkey()
            debug_print(f'{key=}')
            # Don't accept space(s),
            # because it might be the user not realizing the pager has ended
            if re.search(r'^\s+$', key) :
                key = None

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
        # u Update
        # w Wildcard matches (in front or back fields)
        # y Sync
        # * Sync

        # TODO refactor the below into a dispatch table
        # Does this really add much value to use 'match'
        # Better to first just refactor big blocks into functions ...

        # match key:
        #     case 'n' if card_ids_i < len(card_ids) - 1:
        #         card_ids_i += 1
        #     case 'p' | 'N' if card_ids_i > 0:
        #         card_ids_i -= 1

        if key in ('x', 'q', Key.ESC_ESC) :
            clear_line()
            exit()
        elif key in ('.') :
            # Reload (for 'live' editing / debugging)
            tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
            ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
            info_print(f"{os.getpid()=} mtime={ts} {sys.argv[0]=}")
            os.execv(sys.argv[0], sys.argv)
        elif key == 'd':
            # Switch deck
            decks = get_deck_names()
            scroll_screen()
            print(COLOR_COMMAND)
            print("\n * ".join(['', *decks]))
            print(COLOR_RESET)

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
        elif key in ('y', '*') :
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
                search_anki(term, deck=deck, field=None, browse=True, term=card and card['fields']['Front']['value'])
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
            content_old = content
            # Get the 'front' value of the last displayed card,
            # since this might be a multi-resultset
            front = card['fields']['Front']['value']
            obj = search(front, lang=deck)
            content = obj and obj.get('definition')
            suggestions = obj and obj.get('suggestions') or []

            if not content and not suggestions:
                ...
                # TODO warn

            if card_id and content:
                normalized = normalizer(content, term=front)

                # idempotent?
                normalized2 = normalizer(normalized, term=front)
                if normalized != normalized2:
                    # TODO WARN
                    info_print("Normalizer not idempotent")

                if content_old == normalized :
                    info_print("Identical to origin (normalized)")
                    continue

                info_print()
                print(renderer(normalized, front, term=front, deck=deck))

                # print a diff to make it easier to see if any important customizations would be lost
                info_print()
                diff_lines = list(Differ().compare(content_old.splitlines(),normalized.splitlines()))
                for i in range(len(diff_lines)) :
                    diff_lines[i] = re.sub(r'^(\+\s*\S+.*?)$',    GREEN + r'\1' + COLOR_RESET, diff_lines[i])
                    diff_lines[i] = re.sub(r'^(\-\s*\S+.*?)$',      RED + r'\1' + COLOR_RESET, diff_lines[i])
                    diff_lines[i] = re.sub(r'^(\?\s*\S+.*?)$', WHITE_LT + r'\1' + COLOR_RESET, diff_lines[i])
                print(*diff_lines, sep='\n')

                try:
                    prompt = "\nReplace " + COLOR_COMMAND + front + COLOR_RESET + " with this definition? N/y: "
                    reply = input(prompt)
                except:
                    reply = None
                if reply:
                    # Don't litter readline history with 'y' and 'n'
                    readline.remove_history_item(readline.get_current_history_length() - 1)
                    if reply.casefold() == 'y':
                        update_card(card_id, back=normalized)
                        edits_n += 1

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

        elif key in ('s', '/', Key.CTRL_P, Key.UP):
            # Exact match search

            content = None
            suggestions = []

            # TODO factor the prompt of 'term' into a function?
            clear_line()
            try:
                term = input(f"Search: {COLOR_VALUE + deck + COLOR_RESET}/")
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

        elif key == 'u' and updatable:
            update_card(card_id, back=content)
            info_print(f"\t\t\t\t\t\tUpdated {card_id}\t{front}")
            edits_n += 1

        else:
            # Unrecognized command.
            beep()
            # add a '?' function that programmatically lists available shortcuts (if they're available in a dict)



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
    parser.add_option('-d', "--debug",       dest='debug',  action='store_true')
    parser.add_option('-s', "--auto-scroll", dest='scroll', action='store_true',
        help="Iterate over all cards when multiple results. Useful in combo with --auto-update"
        )
    parser.add_option('-u', "--auto-update", dest='update', action='store_true',
        help="Replace the source of each viewed card with the rendered plain text, if different"
        )
    parser.add_option('-k', "--deck",        dest='deck',
        help="Name of Anki deck to use (must be a 2-letter language code, e.g. 'en')"
        )
    (options, args) = parser.parse_args()

    options.debug = options.debug or bool(sys.gettrace())

    if not options.deck:
        # Take the first deck by default; fail if there are none
        options.deck = decks[0]

    readline.set_completer(completer)
    readline.set_completer_delims('')
    readline.parse_and_bind("tab: complete")

    # For autopage. When the EOF of the long definition is printed,
    # automatically end the pager process, without requiring the user to press
    # another key to ACK the EOF.
    os.environ['LESS'] = os.environ['LESS'] + ' --QUIT-AT-EOF'

    # Set terminal title, to be able to search through windows
    title = "anki-add-cli : card mgr"
    if options.debug:
        title = "debug: " + title
    sys.stdout.write('\x1b]2;' + title + '\x07')

    main(options.deck)
