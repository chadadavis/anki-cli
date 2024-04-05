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

Note, only the note type (model) called 'Basic' is supported. We assume that is
has the standard field names 'Front' and 'Back' Any other cards won't be
displayed

Note on Duplicate detection:
Android and Desktop apps: detects dupes across the same note type, not the same
deck. Desktop will allow you to see what the dupes are, ie if they're in a diff
deck. Android doesn't, though, so you might create dupes there when adding new
(empty) cards. That's ok. Once you get back to anki-add-cli, and dequeue the
empties, the existing card will be detected.

"""

# Note, that regex search in Anki is supported from 2.1.24+ onward
# https://apps.ankiweb.net/
# https://docs.ankiweb.net/searching.html
# https://docs.rs/regex/1.3.9/regex/#syntax
# But it unfortunately doesn't help much for the NL words from woorden.org due
# to the non-consistent format.

import argparse
import copy
import datetime
import difflib
import enum
import functools
import html
import json
import logging
import math
import os
import pprint
import random
import readline
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Optional
from urllib import request, parse
from urllib.error import HTTPError, URLError

import autopage
import bs4  # BeautifulSoup

# NB, the pip package is called iso-639 (with "-").
# And this is TODO DEPRECATED
# DEPRECATION: iso-639 is being installed using the legacy 'setup.py install'
# method, because it does not have a 'pyproject.toml' and the 'wheel' package is
# not installed. pip 23.1 will enforce this behavior change. A possible
# replacement is to enable the '--use-pep517' option. Discussion can be found at
# https://github.com/pypa/pip/issues/8559
# Alternatively, try: https://pypi.org/project/pycountry/
import iso639  # Map e.g. 'de' to 'german', as required by SnowballStemmer

import pyperclip
import readchar  # For reading single key-press commands

# The override for `re` is necessary for wildcard searches, due to extra
# interpolation. # Otherwise 're' raises an exception. Search for 'regex' below.
# https://learnbyexample.github.io/py_regular_expressions/gotchas.html
# https://docs.python.org/3/library/re.html#re.sub
# "Unknown escapes of ASCII letters are reserved for future use and treated as
# errors."
import regex as re

import unidecode
from nltk.stem.snowball import SnowballStemmer


# This bogus def just makes it easier for me to jump here in my editor
def backlog():
    ...

# Backlog/TODO

# Put this into its own repo (so that vscode uses just one venv per workspace/repo)
# And enable the debugger

# See the extension that tries to work around duplicate detection across the note type:
# https://ankiweb.net/shared/info/1587955871
# But, What about Android? Can just add the duplicate, and let this script figure it out later when dequeueing empties ...

# TODO rethink/refactor the sanity of this state machine in the main loop

# Add support for wiktionary? (has more words, eg botvieren)
# (But doesn't always have IPA?) ?
# Note that a word might also list homonyms in other langs. How to restrict to a given lang?
# eg via ? https://github.com/Suyash458/WiktionaryParser
# Consider making that its own Anki add-on, independent of this CLI

# Consider putting the menu at the top of the screen, since I focus on the top left to see the words anyway
# But then I'd still need to keep the search/input line at the bottom, due to the sequence of printing

# TODO card type dependency on 'Basic' :
# But rather than depend on 'Front' and 'Back', maybe we could generalize this to get the get_card()['question'] and ...['answer']
# Those are the rendered versions, which contains whatever necessary fields are defined by the card type, the rendered versions (full of HTML/CSS).
# So, we should try to detect if it's already normalized, as it never will be. For that we'd have to check the raw field content in the note (eg Front or Back)

# logging.error() should also go to the screen, somehow ...
# Maybe wait until I think of a better way to manage the UI

# Text UI libs? eg ncurses, etc ?
# https://www.willmcgugan.com/blog/tech/post/building-rich-terminal-dashboards/

# Make the 'o' command open whatever the source URL was (not just woorden.org)

# BUG no NL results from FD (from FreeDictionary)
# Why does EN work when NL doesn't?
# If Woorden is often unavailable, make this configurable in the menu (rather than hard-coded)?

# Use this freeDictionary API, so as to need less regex parsing
# https://github.com/Max-Zhenzhera/python-freeDictionaryAPI/

# Background thread to keep cached data up-to-date, eg when cached values need to be uncached/refreshed.
# Else eg the desk screen has to make many slow API calls
# Or, is there a way/an API call to get all the counts of new/learning/reviewing from all decks in one call?
# See getDeckStats which gives new_count, learn_count, review_count and "name", for each deck object

# TODO make a class for a Card ?
# Or at least wrap it in my `dictd` class (from startup.py), so that it could be:
#   card.fields.front.value (instead of the verbose syntax)
#
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
# Make a stringified version of the card, for logging, with just these fields:
# 'cardId' 'note' 'deckName' 'interval' ['fields']['front']['value']
# logging.debug(...)

# Also make a class to represent the ResultSet, so that we don't have to separately maintain card_ids_i ?
# Needs bidirectional/adhoc traversal, like a doubly linked list.
# (A iter() only allows forward traversal. And `deque` is for consuming elements out of the list.)
# I don't really need all the overhead of a doubly linked list (the list won't be modified, just deleted)
# I just need bidirectional iteration (maybe useful in general?)
# But a generator iterator might not work, since it's just freezing the state of a single function call.
# But I need to differentiate between next() vs prev()
# And what would happen if the underlying list were modified?
# Should I require the underlying DS to be a tuple for simplicity?
# Is there an existing PyPi for an iterator that has a prev() ?

# The 'u' 'update' (for normalization) should also prompt with a diff, before making the change (since there's no undo)
# Just like the 'r' replace function already does.

# Logging:
# Modifying it to send WARNING level messages also to logging.StreamHandler()
# And INFO also to the StreamHandler when in debug mode

# In highlighter() highlight `query` and `term` in diff colors

# BUG why does beep() not beep unless in debug mode ?

# TODO Address Pylance issues,
# eg type hints
# And then define types for defs

# Consider adding a GPT command/prompt to ask adhoc questions about this / other cards ?
# Also when no results found.
# Could use the embeddings to find synonyms, for example (and note which I have locally?)
# Might have to use stop tokens to limit the response to one line ?
# Or rather than customize it for one service, make a command (!) to pipe to a shell command
# Doesn't vim also have something like that?
# And save the last command in readline (or read from bash history?)
# Then use the chatgpt.py script to receive content piped in, along with a question on the CLI
# Make sure to also include the term (since it's not part of the def content)

# TODO
# Think about how to add multiples webservices for a single deck/lang (?)
# Like how we switch decks currently?
# Eg beyond a dictionary, what about extra (web) services for:
# synonyms, pronunciation, etymology, etc, or just allowing for multiple search providers
# Maybe just:
# { lang: en, dict: dictionary.com, syn/thes: somesynservice.com, ipa: some ipa service, etym: etymonline.com, ...}
# Get IPA from Wiktionary (rather than FreeDictionary)?
# And maybe later think about how to combine/concat these also to the same anki card ...
# Is there an API for FD? Doesn't seem like it.
# cf get_url()

# Add nl-specific etymology? (Wiktionary has some of this)
# https://etymologiebank.nl/

# using Wiktionary would enable mapping from conjugated forms eg postgevat because it links to the infinitives eg postvatten
# (but then search again locally first, since I might already have that verb)

# FR: Or use a diff source, eg TV5
# https://langue-francaise.tv5monde.com/decouvrir/dictionnaire/f/franc

# Add DWDS for better German defs (API?). But get IPA pronunciation elsewhere
# (eg FreeDictionary or Wiktionary)

# TODO consider switching to curses lib
# https://docs.python.org/3/howto/curses.html#curses-howto
# Alternative libs: urwid prompt_toolkit blessings npyscreen

# And then I can use something like a progress bar for showing the timeout on the http requests ...
# But, does anki-connect even process client requests async?

# Replace colors with `termcolor` lib?
# TODO consider colorama here?

# Run the queries needed to update the menu in a separate thread, update the UI quicker
# And maybe also the sync() since it should just be fire-and-forget (but then update empties count)
# TODO make menu rendering async, or just make all external queries async?
# Migrate from urrlib to httpx (or aiohttp) to use async

# Since I'd also like to try to make formatted text versions for other
# languages, maybe regex-based rendering isn't the most sustainable approach.
# Replace regex doc parsing with eg
# https://www.scrapingbee.com/blog/python-web-scraping-beautiful-soup/
# And use CSS selectors to extract content more robustly
# use BeautifulSoup?
# Convert HTML to Markdown?
# Consider library html2text
# Would an XSLT, per source, make sense for the HTML def content?
# eg this lib: https://lxml.de/
# https://www.w3schools.com/xml/xsl_intro.asp

# Consider alternative add-ons for Anki (for creating new cards using online dicts)
# https://ankiweb.net/shared/info/1807206748
# https://github.com/finalion/WordQuery
# All add-ons:
# https://ankiweb.net/shared/add-ons/

# Repo/Packaging:
# figure out how to package deps (eg readchar) and test it again after removing local install of readchar

# Move this dir to its own repo
# http://manpages.ubuntu.com/manpages/git-filter-repo
# or
# http://manpages.ubuntu.com/manpages/git-filter-branch

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

# See smaller, inline TODOs below ...

################################################################################


# Color codes:
# The leading '1;' makes a foreground color bold/bright as well.
# https://stackoverflow.com/a/33206814/256856
RESET    = "\033[0;00m"
GRAY_N   = "\033[0;02m"
GRAY_B   = "\033[1;02m"
RED_N    = "\033[0;31m"
RED_B    = "\033[1;31m"
GREEN_N  = "\033[0;32m"
GREEN_B  = "\033[1;32m"
YELLOW_N = "\033[0;33m"
YELLOW_B = "\033[1;33m"
BLUE_N   = "\033[0;34m"
BLUE_B   = "\033[1;34m"
# MAGENTA 35
# CYAN    36
WHITE_N  = "\033[0;37m"
WHITE_B  = "\033[1;37m"

YELLOW_L = "\033[0;93m" #Bright

# Abstract colors into use cases, in case we want to change the mapping later
COLOR_COMMAND   = WHITE_B
COLOR_WARN      = YELLOW_B
COLOR_INFO      = GRAY_N
COLOR_OK        = GREEN_B
COLOR_VALUE     = GREEN_N
COLOR_HIGHLIGHT = YELLOW_L
COLOR_RESET     = RESET

pp = pprint.PrettyPrinter(indent=4)


class Key(enum.StrEnum):
    # The Esc key is doubled, since it's is a modifier and isn't accepted solo
    ESC_ESC = '\x1b\x1b'
    CTRL_C  = '\x03'
    CTRL_D  = '\x04'
    CTRL_P  = '\x10'
    CTRL_W  = '\x17'
    UP      = '\x1b[A'
    DEL     = '\x1b[3~'


def assert_anki(retry=True):
    """Ping anki-connect to check if it's running, else launch anki

    NB, Anki is a singleton, so this wouldn't launch multiples
    """

    port = 8765
    host = 'localhost'
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except (ConnectionRefusedError, socket.timeout):
        if not retry:
            msg = (
                'Failed to connect to Anki. '
                'Make sure that Anki is running, '
                'and using the anki-connect add-on.'
            )
            logging.warning(msg)
            sys.exit(msg)

    # If you use os.system to background Anki here, it would launch, but it will
    # not understand redirecting stdout/stderr to a log file.
    # Output from Anki/add-ons would interfere with our CLI output on stdout.
    cmd = ['env', 'ANKI_WAYLAND=1', 'anki']
    logging.info(f'launching ... {cmd}')
    with open(f'anki.log', 'a') as log_file:
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
    time.sleep(1.0)
    # Try one last time
    return assert_anki(retry=False)


def invoke(action, **params):
    """Send a request to Anki desktop via the API for the anki-connect add-on

    Details:
    https://github.com/FooSoft/anki-connect/
    """

    struct = { 'action': action, 'params': params, 'version': 6 }
    reqJson = json.dumps(struct).encode('utf-8')
    logging.debug(b'invoke:' + reqJson, stacklevel=2)
    req = request.Request('http://localhost:8765', reqJson)

    try:
        response = json.load(request.urlopen(req))

        if options.debug:
            # Simplify some debug logging
            result_log = copy.deepcopy(response['result'])
            if isinstance(result_log, dict):
                result_log = [ result_log ]
            if isinstance(result_log, list):
                if len(result_log) > 10:
                    result_log = 'len:' + str(len(result_log))
                else:
                    for obj in result_log:
                        if not isinstance(obj, dict): continue
                        for field in ('question', 'answer', 'css'):
                            if field in obj: obj[field] = '<...>'
                        if 'fields' in obj and 'Back' in obj['fields']:
                            obj['fields']['Back']['value'] = '<...>'

            logging.debug('result:\n' + pp.pformat(result_log), stacklevel=2)

        error = response['error']
        if error is not None:
            beep(3)
            logging.error('error:\n' + str(error), stacklevel=2)
            logging.error('result:\n' + pp.pformat(response['result']), stacklevel=2)
            return None
        else:
            return response['result']
    except (ConnectionRefusedError, URLError) as e:
        if assert_anki():
            # Retry the request
            return invoke(action, **params)
        else:
            return None


def get_deck_names():
    names = sorted(invoke('deckNames'))
    # Filter out sub-decks ?
    names = [ i for i in names if i != 'Default' and not '::' in i]
    return names


def renderer(string, query='', *, term='', deck=None):
    """For displaying (normalized) definition entries on the console/CLI"""

    # Prepend term in canonical format, for display only
    if term:
        hr = '─' * len(term)
        string = '\n'.join(['', term, hr, string])

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

    # Remove tags that are usually inside the IPA/phonetic markup
    string = re.sub(r'</?a\s+.*?>', '', string)

    # Replace IPA stress marks that are not commonly represented in fonts.
    # IPA Primary Stress Mark   (Unicode U+02C8) ie the [ˈ] character => apostrophe [']
    # IPA Secondary Stress Mark (Unicode U+02CC) ie the [ˌ] character => comma [,]
    # IPA Long vowel length     (Unicode U+02D0) ie the [ː] character => colon [:]
    # eg for the NL word "apostrof", change the IPA: [ ˌapɔsˈtrɔf ] => [ ,apɔs'trɔf ]
    string = re.sub(r'\u02C8', "'", string)
    string = re.sub(r'\u02CC', ",", string)
    string = re.sub(r'\u02D0', ":", string)

    # Remove numeric references like [3]; we probably don't have the footnotes anyway
    string = re.sub(r'\[\d+\]', '', string)

    # NL-specific (or specific to woorden.org).
    # Segregate topical category names e.g. 'informeel' .
    # Definitions in plain text will often have the tags already stripped out.
    # So, also use this manually curated list.

    # spell-checker:disable
    categories = [
        *[]
        # These are just suffixes that mean "study of a(ny) field"
        ,r'\S+kunde'
        ,r'\S+ografie'
        ,r'\S+ologie'
        ,r'\S+onomie'
        ,r'\S*techniek'
        ,r'financ[a-z]+'

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
        ,'scheepvaart'
        ,'slang'
        ,'speelgoed'
        ,'sport'
        ,'spreektaal'
        ,'taal'
        ,'technisch'
        ,'theater'
        ,'transport'
        ,'verkeer'
        ,'verouderd'
        ,'visserij'
        ,'vulgair'
    ]
    # spell-checker:enable

    # If we still have the HTML tags, then we can see if this topic category is
    # new to us. Optionally, it can then be manually added to the list above.
    # Otherwise, they wouldn't be detected in old cards, if it's not already in
    # [brackets] .
    for match in re.findall(r'<sup>([a-z]+?)</sup>', string) :
        category = match
        # logging.debug(f'{category=}')
        # If this is a known category, just format it as such.
        # (We're doing a regex match here; a category name might be a regex.)
        string = re.sub(r'<sup>(\w+)</sup>', r'[\1]', string)
        if any([ re.search(c, category, re.IGNORECASE) for c in categories ]):
            ...
        else:
            # Notify, so you can (manually) add this one to the 'categories'
            # list above.
            print(f'\nNew category [{COLOR_WARN}{category}{COLOR_RESET}]\n',)
            beep()
            # time.sleep(5)

    # Replace remaining <sup> tags
    string = re.sub(r'<sup>', r'^', string)

    # Specific to: PONS Großwörterbuch Deutsch als Fremdsprache
    string = re.sub('<span class="illustration">', '\n', string)

    # Specific to fr.thefreedictionary.com (Maxipoche 2014 © Larousse 2013)
    string = re.sub('<span class="Ant">', '\nantonyme: ', string)
    string = re.sub('<span class="Syn">', '\nsynonyme: ', string)

    # Specific to en.thefreedictionary.com
    # (American Heritage® Dictionary of the English Language)
    string = re.sub(r'<span class="pron".*?</span>', '', string)
    # Replace headings that just break up the word into syl·la·bles,
    # since we get that from IPA already
    string = re.sub(r'<h2>.*?·.*?</h2>', '', string)
    # For each new part-of-speech block
    string = re.sub(r'<div class="pseg">', '\n\n', string)

    # Add spaces around em dash — for readability
    string = re.sub(r'(\S)—(\S)', r'\1 — \2', string)

    # HTML-specific:
    # Remove span/font tags, so that the text can stay on one line
    string = re.sub(r'<span\s+.*?>', '', string)
    string = re.sub(r'<font\s+.*?>', '', string)
    # These HTML tags <i> <b> <u> <em> are usually used inline and should not
    # have a line break (below, we replace remaining tags with \n ...)
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
    # Ensure headings begin on their own line
    # (also covers plural forms, eg "Synoniemen")
    string = re.sub(
        r'(?m)(?<!^)(Afbreekpatroon|Uitspraak|Vervoeging|Verbuiging|Synoniem|Antoniem)',
        r'\n\1',
        string
    )

    # NL-specific: Newlines (just one) before example `phrases in backticks`
    # (but not *after*, else you'd get single commas on a line, etc)
    string = re.sub(r'(?m)(?:\n*)(`.*?`)', r'\n\1', string)

    # One, and only one, newline \n after colon :
    # (but only if the colon : is not already inside of a (short) parenthetical)
    string = re.sub(r'(?m):([\s\n]+)(?![^(]{,20}\))', r':\n', string)

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
    # Newline after /slashes/ often used as context, if at the start of the line
    string = re.sub(r'(?m)^\s*(/.*?/)\s*', r'\1\n', string)

    # Max 2x newlines in a row
    string = re.sub(r'(\s*\n\s*){3,}', '\n\n', string)

    # Delete leading/trailing space on each line
    string = re.sub(r'(?m)^ +', '', string)
    string = re.sub(r'(?m) +$', '', string)

    # Delete leading space on the entry as a whole
    string = re.sub(r'^\s+', '', string)

    # Strip redundant term at start of card, if it's a whole word, non-prefix
    if term:
        string = re.sub(r'^\s*' + term + r'\s+', r'', string)

    # Delete trailing space, and add canonical final newline
    string = re.sub(r'\s*$', '', string)
    if string != '':
        string = string + '\n'

    return string


def highlighter(string, query, *, term='', deck=None):

    # Map wildcard search chars to regex syntax
    query = re.sub(r'[.]', r'\.', query)
    query = re.sub(r'[_]', r'.', query)

    # Even though this is a raw string, the '\' needs to be escaped, because
    # the 're' module raises an exception for any escape sequences that are
    # not valid in a standard string. (The 'regex' module doesn't.)
    # https://learnbyexample.github.io/py_regular_expressions/gotchas.html
    # https://docs.python.org/3/library/re.html#re.sub
    # "Unknown escapes of ASCII letters are reserved for future use and treated
    # as errors."
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
    # Map e.g. 'de' to 'german', as required by SnowballStemmer
    if deck and deck in iso639.languages.part1:
        lang = iso639.languages.get(part1=deck).name.lower()
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
        # Theoretically, we could not have a double loop here, but this makes it
        # easier to read. There can be multiple inflections in one line (eg
        # prijzen), so it's easier to have two loops.
        inflections = re.findall(
            r'(?m)^\s*(?:Vervoegingen|Verbuigingen):\s*(.*?)\s*$',
            string
        )
        for inflection in inflections:
            # There is not always a parenthetical part-of-speech after the
            # inflection of plurals. Sometimes it's just eol (eg "nederlaag") .
            # So, it ends either with eol $ or open paren (
            match = re.findall(r'(?s)(?:\)|^)\s*(.+?)\s*(?:\(|$)', inflection)
            matches += match

        for match in matches:

            # Remove separators, e.g. in "Verbuigingen: uitlaatgas|sen (...)"
            match = re.sub(r'\|', '', match)

            # If past participle, remove the 'is' or 'heeft'
            # Sometimes as eg:
            # uitrusten: 'is, heeft uitgerust' or 'heeft, is uitgerust'
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

            # Hack stemming for infinitive forms with a consonant change in
            # simple past tense:
            # dreef => drij(ven) => drij(f)
            # koos => kie(zen) => kie(s)
            if term_or_query.endswith('ven') and match.endswith('f'):
                highlights.add( re.sub(r'ven$', '', term_or_query) + 'f' )
            if term_or_query.endswith('zen') and match.endswith('s'):
                highlights.add( re.sub(r'zen$', '', term_or_query) + 's' )

            # Allow separable verbs to be separated, in both directions.
            # ineenstorten => 'stortte ineen'
            # BUG capture canonical forms that end with known prepositions
            # (make a list)
            # eg teruggaan op => ging terug op (doesn't work here)
            # We should maybe just remove the trailing preposition
            # (if it was also a trailing word in the 'front')
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
        string = re.sub(
            f"(?i:({highlight_re}))",
            COLOR_HIGHLIGHT + r'\1' + COLOR_RESET,
            string
        )

    return string


def get_url(term, *, lang):
    """Get a dict of source URL(s) for a given query term/expression"""

    quoted = parse.quote(term) # URL quoting

    # TODO could perhaps generalize this further into a list or (per-lang) providers
    # That would provide both source URLs, as well as parsing rules for the response
    url = {}
    url['google'] = f'https://google.com/search?q={quoted}'
    url['freedictionary'] = f'https://{lang}.thefreedictionary.com/{quoted}'
    url['wiktionary'] = f'https://{lang}.wiktionary.org/wiki/{quoted}'

    # TODO add lang-specific dicts ?
    # TODO add a default per language, eg 'nl' aliases to 'woorden'

    return url


def search(term, *, lang):
    obj = {}

    if lang == 'nl':
        content = search_woorden(term)
        obj['definition'] = content
        return obj

    obj = search_thefreedictionary(term, lang=lang)
    return obj


def search_anki(query, *, deck, wild=False, field='front', browse=False, term=''):
    """Local search of Anki"""

    # If term contains whitespace, either must quote the whole thing, or replace
    # spaces:
    search_query = re.sub(r' ', '_', query) # For Anki searches

    # TODO accent-insensitive search?
    # eg exploit should find geëxploiteerd
    # It should be possible with Anki's non-combining mode: nc:geëxploiteerd
    # https://docs.ankiweb.net/#/searching
    # But doesn't seem to work
    # Or see how it's being done inside this add-on:
    # https://ankiweb.net/shared/info/1924690148

    search_terms = [search_query]

    # Collapse double letters \p{L} into a disjunction, eg: (NL-specific)
    # This implies that the user should, when in doubt, use double chars to search
    # deck:nl (front:maaken OR front:maken)
    # or use a re: (but that doesn't seem to work)
    # BUG: this isn't a proper Combination (maths), so it misses some cases
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

        search_terms = map(lambda x: f'"{field}:{x}"', search_terms)

        # Regex search of declinations:

        # This doesn't really work, since the text in the 'back' field isn't
        # consistent. Sometimes there's a parenthetical expression after the
        # declination, sometimes not. So, I can't anchor the end of it, which
        # means it's the same as just a wildcard search across the whole back.
        # eg 'Verbuigingen.*{term}', and that's not any more specific than just
        # searching the whole back ...

        # if field == 'front' and deck == 'nl':
        #     # Note, Anki needs the term in the query that uses "re:" to be wrapped in double quotes (also in the GUI)
        #     terms = [*terms, f'"back:re:(?s)(Verbuiging|Vervoeging)(en)?:(&nbsp;|\s|<.*?>|heeft|is)*{term}\\b"' ]

        # TODO since we parse these out from the highlighter() (if it's
        # reliable), we could (auto?) add these as tags to the cards, and then
        # also search the tags (?)

    search_query = f'deck:{deck} (' + ' OR '.join([*search_terms]) + ')'
    logging.debug(f'{query=}')

    if browse:
        # In browse mode, also search for any singular term. This is useful when
        # paging through a resultset, but I want to edit the current card. Then
        # the browse UI will only show this one card, but if I want to see the
        # rest of the cards, then I can just delete this final term from the
        # query field in the UI.
        card_ids = invoke('guiBrowse', query=search_query + ' ' + f'"{term}"')
    else:
        card_ids = invoke('findCards', query=search_query)
        card_ids = card_ids or []
    return card_ids


@functools.lru_cache(maxsize=10)
def get_new(deck, ts=None):
    """Get the IDs of all new cards (those that have never been reviewed)

    Note, this also includes the empty cards.
    cf. get_emtpy(), is_empty()

    """
    card_ids = invoke('findCards', query=f"deck:{deck} is:new")
    return card_ids


def is_new(card_id):
    """Card is new, aka. unseen, never yet reviewed

    """

    card = get_card(card_id)
    card_ids = get_new(card['deckName'], ts=time.time()//3600)
    return card_id in card_ids


@functools.lru_cache(maxsize=10)
def get_unreviewed(deck, ts=None):
    """
    If there hasn't been a review today (since midnight), show the count of
    cards due.

    This is to stimulate doing a review today, if it has any cards that can be
    reviewed. This set does not overlap with `get_new()` .

    TODO this seems to wrongly return `epoch_review == 0` for hierarchical decks
    (eg "Python")
    """

    card_ids = []

    # Anki uses millisecond epochs
    review_id = invoke('getLatestReviewID', deck=deck)
    # Convert millisecond epoch to second epoch, truncate milliseconds off the
    # timestamp (which is the review ID)
    epoch_review = int(review_id/1000)

    # Get the (epoch) time at midnight this morning,
    # by converting now to a date (stripping the time off)
    # then converting the date back to to a time
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    epoch_midnight = int(
        datetime.datetime.strptime(date_today, '%Y-%m-%d').timestamp()
    )

    logging.debug(f"if {epoch_review=} < {epoch_midnight=} : ...")
    if epoch_review < epoch_midnight :
        card_ids = get_due(deck, ts=time.time()//3600)
    return card_ids


def get_due(deck, ts=None):
    """"
    A list of all cards (IDs) due (learning cards before reviewing cards).

    Note, `findCards` returns cards in order of creation
    (which isn't quite the same as when they're due).

    This function ignores whether a review on this deck was already done today.
    cf. `get_unreviewed()`

    The cards due (`is:due`) are made up of two disjunct sets:
    * learn(ing) cards:  `is:due  is:learn`
    * review(ing) cards: `is:due -is:learn`

    Note, the `ts` param is just for cache invalidation,
    not for querying cards due before a certain date/time.
    """

    learning_ids  = get_learning(deck, ts)
    reviewing_ids = get_reviewing(deck, ts)

    return [ *learning_ids, *reviewing_ids ]


@functools.lru_cache(maxsize=10)
def get_learning(deck, ts=None):
    learning_ids  = invoke('findCards', query=f"deck:{deck} is:due  is:learn")
    return learning_ids


@functools.lru_cache(maxsize=10)
def get_reviewing(deck, ts=None):
    reviewing_ids = invoke('findCards', query=f"deck:{deck} is:due -is:learn")
    return reviewing_ids


# Cards that aren't due within this many days are considered 'mature'
MATURE_INTERVAL = 365

# Mature cards
# This set does not overlap with get_new() nor get_mid()
@functools.lru_cache(maxsize=10)
def get_old(deck, ts=None):
    card_ids = invoke(
        'findCards',
        query=f"deck:{deck} (is:review OR is:learn) prop:ivl>={MATURE_INTERVAL}"
    )
    return card_ids


# # Immature cards, short interval
# # This set does not overlap with get_new() nor get_old()
# @functools.lru_cache(maxsize=10)
# def get_mid(deck, ts=None):
#     card_ids = invoke(
#         'findCards',
#         query=f"deck:{deck} (is:review OR is:learn) prop:ivl<{MATURE_INTERVAL}"
#     )
#     return card_ids


@functools.lru_cache
def get_empty(deck, ts=None):
    card_ids = search_anki('', deck=deck, field='back')
    return card_ids


@functools.lru_cache
def get_deck_stats(decks=None, *, ts=None):
    decks = decks or get_deck_names()
    response = invoke('getDeckStats', decks=decks)
    stats = {
        response[deck_name]['name']: {
            'new'    :response[deck_name]['new_count'],
            'learn'  :response[deck_name]['learn_count'],
            'review' :response[deck_name]['review_count'],
        } for deck_name in response
    }
    return stats


def are_due(card_ids):
    """Deprecated. Card is ready to review (either due, or new)

    Based on the `areDue` API call, which seems to differ from querying is:due .
    The `is:due` query seems to return cards due later today, but not due now.
    The `areDue` seems to hide cards due later today, but not due now.

    The Anki UI seems consistent with `is:due`, and not with `areDue`
    """
    r = invoke('areDue', cards=card_ids)
    if r:
        return r[0]


def is_due(card_id):
    """Card is ready to review (due)

    Does not include new cards.
    cf. is_new(card_id)

    Based on the `is:due` query, which seems to differ from the `areDue` API.
    The `is:due` query seems to return cards due later today, but not due now.
    The `areDue` seems to hide cards due later today, but not due now.

    The Anki UI seems consistent with `is:due`, and not with `areDue`
    """

    card = get_card(card_id)
    card_ids = get_due(card['deckName'], ts=time.time()//3600)
    return card_id in card_ids


def is_empty(card_id):
    """Card was enqueued, to be looked up, but hasn't been looked up yet.

    Technically, this is a 'is_new' card as well, but it has no content yet.
    (It has a 'front' field, but the 'back' field is '')

    cf. is_new(card_id), is_due(card_id)
    """

    card = get_card(card_id)
    return not card['fields']['Back']['value']


def hr():
    LINE_WIDTH = os.get_terminal_size().columns
    print(COLOR_INFO, end='')
    print('─' * LINE_WIDTH, end='\n')
    print(COLOR_RESET, end='')


def launch_url(url):
    cmd = f'xdg-open {url} >/dev/null 2>&1 &'
    logging.info(f"Opening: {url}", stacklevel=2)
    os.system(cmd)


def search_google(term):
    # Copy to clipboard; I might also want to use the term to search other sites too
    pyperclip.copy(term)

    query_term = parse.quote(term) # For web searches
    url=f'https://google.com/search?q={query_term}'
    launch_url(url)


def search_woorden(term, *, url='http://www.woorden.org/woord/'):
    query_term = parse.quote(term) # For web searches
    url = url + query_term
    logging.info(url)
    # TODO factor this out into an on-screen status() func (curses?)
    clear_line()
    print(COLOR_INFO + f"Fetching: {url} ..." + COLOR_RESET, end='', flush=True)

    try:
        response = request.urlopen(url)
        content = response.read().decode('utf-8')
    except (Exception, KeyboardInterrupt) as e:
        logging.info(e)
        return

    clear_line()

    # Pages in different formats, for testing:
    # encyclo:     https://www.woorden.org/woord/hangertje
    # urlencoding: https://www.woorden.org/woord/op zich
    # none:        https://www.woorden.org/woord/spacen
    # ?:           https://www.woorden.org/woord/backspacen #
    # &copy:       http://www.woorden.org/woord/zien
    # Bron:        http://www.woorden.org/woord/glashelder

    match = re.search(
        f"(?s)(<h[1-9].*?{term}.*?)(?=&copy|Bron:|<div|</div)",
        content
    )
    if not match:
        logging.info(term + ": No match in HTML document")
        return
    definition = match.group()
    return definition


def search_thefreedictionary(term, *, lang):
    return_obj = {}
    if not term or '*' in term:
        return
    query_term = parse.quote(term) # For web searches
    url = f'https://{lang}.thefreedictionary.com/{query_term}'
    logging.info(url)

    # TODO factor this out into status() func or something (curses?)
    clear_line()
    print(COLOR_INFO + f"Fetching: {url} ..." + COLOR_RESET, end='', flush=True)

    try:
        response = request.urlopen(url)
        content = response.read().decode('utf-8')
    except HTTPError as response:
        # Usually these are server-side errors, throttling, timeouts, etc
        if response.code != 404:
            logging.warning(response)
            return

        # NB urllib raises an exception on 404 pages. The content of the 404
        # page (eg spellchecker suggestions) is in the Error.
        content = response.read().decode('utf-8')
        # Parse out spellcheck suggestions via CSS selector: .suggestions a
        soup = bs4.BeautifulSoup(content, 'html.parser')
        suggestions = [ r.text for r in soup.select('.suggestions a') ]
        return_obj['suggestions'] = sorted(suggestions, key=str.casefold)
    except (Exception, KeyboardInterrupt) as e:
        logging.info(e)
        return

    clear_line()
    match = re.search('<div id="Definition"><section .*?>.*?</section>', content)
    if not match:
        return return_obj

    definition = match.group()
    # Remove citations, just to keep Anki cards terse
    definition = re.sub('<div class="cprh">.*?</div>', '', definition)

    # Get pronunciation (the IPA version) via Kerneman/Collins (multiple
    # languages), and prepend it, in [brackets].
    match = re.search(' class="pron">(.*?)</span>', content)
    if match:
        ipa_str = '[' + match.group(1) + ']'
        definition = "\n".join([ipa_str, definition])
    return_obj['definition'] = definition
    return return_obj


@functools.lru_cache(maxsize=100)
def get_card(id):
    """Only works for cards with note type 'Basic' (with fields 'Front', 'Back')
    """

    cardsInfo = invoke('cardsInfo', cards=[id])
    if not cardsInfo: return
    card = cardsInfo[0]
    logging.debug(f"Model/Note type:" + card['modelName'])
    if card['modelName'] != 'Basic' :
        return
    return card


def add_card(term, definition=None, *, deck):
    """Create a new Note.

    (If you want the card_id, do another search for it)
    """
    get_new.cache_clear()
    get_empty.cache_clear()
    note = {
        'deckName': deck,
        'modelName': 'Basic',
        'fields': {'Front': term},
        'options': {
            'closeAfterAdding': True,
            'duplicateScope': 'deck',
        },
    }
    # If there's no definition/content, allow user to write/paste some
    definition = definition or editor(term + '\n\n')
    definition = normalizer(definition, term=term)
    note['fields']['Back'] = definition
    # NB, duplicate check (at deck scope) enabled by default
    note_id = invoke('addNote', note=note)

    # Alternatively, use the Anki GUI to add a new card
    #     # NB, this card_id won't exist if the user aborts the dialog.
    #     # But, that's also handled by delete_card() if it should be called.
    #     note_id = invoke('guiAddCards', note=note)


def answer_card(card_id, ease: int):
    """Review this card and set ease. 1: Again/New, 2: Hard, 3: Good, 4: Easy
    """
    # Note, functools.lru_cache doesn't allow removing single items
    get_card.cache_clear()
    get_new.cache_clear()
    get_learning.cache_clear()
    get_reviewing.cache_clear()
    get_unreviewed.cache_clear()
    get_deck_stats.cache_clear()
    invoke('answerCards', answers=[{'cardId': card_id, 'ease': ease}])


def update_card(card_id, *, front=None, back=None):
    get_card.cache_clear()
    get_empty.cache_clear()
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
        raise RuntimeError(response['error'])


def edit_card(card_id):
    card = get_card(card_id)
    content_a = normalize_card(card)
    content_b = editor(content_a)
    content_b = normalizer(content_b)
    if content_a != content_b:
        update_card(card_id, back=content_b)


def editor(content_a: str='', /) -> str:
    """Edit a (multi-line) string, by running your $EDITOR on a temp file

    Note, this does not call normalizer() automatically
    TODO: put this in a module
    """

    tf_name = '/tmp/' + os.path.basename(__file__).removesuffix('.py') + '.tmp'
    with open(tf_name, 'w') as tf:
        tf.write(content_a)
        # temp_file_name = tf.name

    # The split() is necessary because $EDITOR might contain multiple words
    subprocess.call(os.getenv('EDITOR', 'nano').split() + [tf_name])

    with open(tf_name, 'r') as tf:
        content_b = tf.read()
    os.unlink(tf_name)
    return content_b


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
    get_empty.cache_clear()
    note_id = card_to_note(card_id)
    if not note_id:
        # This happens if the card wasn't saved when first being added.
        # So, the note_id that we were given no longer exists
        return None

    # This unfortunately doesn't return any success code
    invoke('deleteNotes', notes=[note_id])
    return True


def wrapper(string, indent=' ' * 4):
    '''Wrap the lines of string with a number of spaces, default 4
    '''
    LINE_WIDTH = os.get_terminal_size().columns
    # WRAP_WIDTH = int(LINE_WIDTH * .8)
    WRAP_WIDTH = 80

    lines_wrapped = []
    for line in string.splitlines():
        line_wrap = textwrap.wrap(
            line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=True
        )
        line_wrap = line_wrap or ['']
        lines_wrapped += line_wrap
    string = f"\n{indent}".join(lines_wrapped)
    # And indent the first line:
    return indent + string


def normalize_card(card):
    front = card['fields']['Front']['value']
    back = card['fields']['Back']['value']
    normalized = normalizer(back, term=front)

    if re.findall(r'<|&[A-Za-z]+;', front) :
        logging.warning("'Front' field with HTML hinders exact match search.")

        # Auto-clean it?
        if options.update :
            # Rendering removes the HTML, for console printing
            cleaned = normalizer(front).strip()
            logging.info(f'{cleaned=}')
            card_id = card['cardId']
            update_card(card_id, front=cleaned)
            logging.info(f"Updated to:")
            # Get again from Anki to verify updated card
            return normalize_card(get_card(card_id))

    return normalized


def sync():
    invoke('sync')
    # And in case we downloaded new empty cards:
    get_empty.cache_clear()
    # And in case we want to sync reviews done elsewhere:
    get_learning.cache_clear()
    get_reviewing.cache_clear()
    get_deck_stats.cache_clear()

    # These will expire in time ... can also just reload the script with key '.'
    # get_new.cache_clear()
    # get_mid.cache_clear()
    # get_old.cache_clear()


def clear_line():
    LINE_WIDTH = os.get_terminal_size().columns
    print('\r' + (' ' * LINE_WIDTH) + '\r', end='', flush=True)


def clear_screen():
    """Wipes out the terminal buffer"""
    if not options.debug:
        print('\033c')


def scroll_screen():
    """
    Scrolls previous content off the visible screen, retaining scroll buffer.
    """
    print("\n" * os.get_terminal_size().lines)


def scroll_screen_to_menu(content="", line_pos=None):
    """The content is the whatever might have already been printed at the top

    Else line_pos is how many lines were already printed since the top
    """

    # What line number are we at already on the screen (counting top down)
    if not line_pos:
        line_pos = 1 + len(re.findall("\n", content))

    # Example:
    # screen height is 10,
    # already printed "hey\nthere" (so 2 lines, since it'll have a final \n)
    # Menu will take 2 at the bottom
    # So, we need 6 more lines printed, with end=''
    OFFSET = 2

    # Remaining newlines to be scrolled down
    lines_n = os.get_terminal_size().lines - line_pos - OFFSET
    logging.debug(f'{line_pos=} {lines_n=}')
    print("\n" * lines_n, end='')


def beep(n: int = 2):
    for _ in range(n):
        print("\a", end='', flush=True)


def main(deck):
    global options

    # TODO wrap all of this state into an object,
    # then we can also attrs that trigger clearing of dependent values, etc

    # The previous search term
    term = ''

    # The locally found card(s)
    card_ids = []
    card_ids_i = 0
    card_id = None
    card = None

    # Is the current result set a review (else it's a search result)
    is_reviewing = False
    # Show the content only after user was prompted to review
    do_reveal = False

    # Across the deck, the number(s) of wildcard matches on the front/back of
    # other cards
    wild_n = None

    # The content/definition of the current (locally/remotely) found card
    content = None
    normalized = None
    menu = ''

    # Spell-scheck suggestions returned from the remote fetch/search?
    global suggestions
    suggestions = []

    # Count num of local changes (new/deleted cards) pending sync?
    edits_n = 0
    sync_last_epoch = int(time.time())

    # The IDs of cards that only have a front, but not back (no definition)
    # This works like a queue of cards to be deleted, fetched and (re)added.
    # (Because it's easier to just delete and re-add than to update)
    empty_ids = []

    while True:

        clear_screen()
        key = None

        # Testing if the content from the Anki DB differs from the rendered
        # content
        updatable = False
        normalized = ''
        card_id = None
        if card_ids:
            # Set card_id and content based on card_ids and card_ids_i
            card = get_card(card_ids[card_ids_i])
            if card:
                card_id = card_ids[card_ids_i]
                normalized = normalize_card(card)
                if normalized != card['fields']['Back']['value']:
                    updatable = True
        else:
            # Remind the user of any previous context, (eg to allow to Add)
            if content:
                normalized = normalizer(content, term=term)

        logging.debug(f'{term=}')
        # Save the content, before further display-only modifications
        content = normalized
        if normalized:
            front = (card_ids and card['fields']['Front']['value']) or term or ''
            logging.debug(f'{front=}')
            normalized = renderer(normalized, term, term=front, deck=deck)

            # If this card is due, prompt to review, don't reveal the content
            # until keypress. Ignore new/unseen cards here, because new cards
            # are lower priority than (over-)due reviews. (But we can still
            # enable the menu item to review new cards below ...)


        # How many lines down the screen are we already?
        line_pos = 0

        # If using --auto-scroll (ie when using --auto-update), then
        # no need to print every definition along the way
        if not options.scroll :
            # Hide content of to-be-reviewed card back until next iteration/keypress
            if card_id and (not do_reveal) and (is_due(card_id) or (is_reviewing and is_new(card_id))):
                normalized = renderer('Press [Space] to review ...', term, term=front, deck=deck)

                # Push reviewed term onto readline history,
                # if it wasn't already the search term
                if term != front:
                    readline.add_history(front)

            with autopage.AutoPager() as out:
                print(normalized, file=out)

        if content:
            # +1 because of default end='\n'
            line_pos = 1 + len(re.findall("\n", normalized))
        elif term:
            hr()
            # TODO factor this out into status() func or something (curses?)
            print("No results: " + term)
            line_pos = 3
            if wild_n:
                hr()
                # TODO factor this out into status() func or something (curses?)
                print(f"(W)ilds:" + COLOR_VALUE + str(wild_n) + COLOR_RESET)
                line_pos += 3

        if suggestions:
            hr()
            # TODO factor this out into status() func or something (curses?)
            print("Did you mean:\n")
            print("\n".join(suggestions))
            line_pos += len(suggestions) + 2

        scroll_screen_to_menu(line_pos=line_pos)

        # Print the menu (TODO factor this out)
        # spell-checker:disable
        menu = [ '' ]

        if not card_id:
            if term:
                menu += [ COLOR_WARN + "+" + COLOR_RESET ]
                menu += [ "(A)dd    " ]
                menu += [ "(F)etch  " ]
            else:
                menu += [ "        " ]
        if card_id:
            if updatable:
                menu += [ COLOR_WARN + "⬆" + COLOR_RESET]
                menu += [ "(U)pdate " ]
            else:
                menu += [ COLOR_OK + "✓" + COLOR_RESET]
                menu += [ "Dele(t)e " ]

            menu += [ "(E)dit" ]
            menu += [ "(R)eplace" ]

            # if is_due(card_id) or is_new(card_id):
            if do_reveal:
                menu += [ '(1-4) ' + COLOR_WARN + '?' + COLOR_RESET]
                # menu += [ f"{card['interval']:5d} d" ]
            else:
                # menu += [ "             " ]
                menu += [ "     " ]

        menu += [ '│' ]
        menu += [ "(D)eck:" + COLOR_VALUE + deck + COLOR_RESET]

        # Check for incoming changes periodically.
        # But push outgoing changes sooner, since we know if any are pending.
        sync_thresh_edits = 10 if not options.scroll else float('inf')
        sync_thresh_secs = 60 * 60
        if (0
            or  int(time.time()) > sync_last_epoch + sync_thresh_secs
            or (int(time.time()) > sync_last_epoch + sync_thresh_secs//10 and edits_n)
            or edits_n > sync_thresh_edits
        ):
            sync()
            sync_last_epoch = int(time.time())
            edits_n = 0

        # if edits_n > sync_thresh_edits :
        #     menu += [ COLOR_WARN + "*" + COLOR_RESET ]
        # else:
        #     menu += [ ' ' ]

        # if n_old := deck and len(get_old(deck, ts=time.time()//3600)) :
        #     menu += [ "mature:" + COLOR_VALUE + str(n_old) + COLOR_RESET ]
        # if n_mid := deck and len(get_mid(deck, ts=time.time()//3600)) :
        #     menu += [ "young:"  + COLOR_VALUE + str(n_mid) + COLOR_RESET ]
        # if n_due := deck and len(get_unreviewed(deck, ts=time.time()//3600)) :
        #     menu += [ "Re(v)iew:"    + COLOR_VALUE + str(n_due) + COLOR_RESET ]
        # if n_new := deck and len(get_new(deck, ts=time.time()//3600)) :
        #     menu += [ "new:" + COLOR_VALUE + str(n_new) + RESET ]

        stats = get_deck_stats(ts=time.time()//60)
        if deck:
            new_n = stats[deck]['new']
            learn_n = stats[deck]['learn']
            review_n = stats[deck]['review']
            if is_reviewing or learn_n or review_n :
                menu += [ ''
                    + "Re(v)iew: "
                    + (BLUE_N if new_n > 0 else GRAY_N) + f'{new_n:4d}'
                    + (GREEN_N if review_n > 0 else GRAY_N) + f'{review_n:2d}'
                    + (RED_N if learn_n > 0 else GRAY_N) + f'{learn_n:2d}'
                    + COLOR_RESET
                ]

        if empty_ids := deck and get_empty(deck):
            menu += [
                "E(m)pties:" + COLOR_WARN + str(len(empty_ids)) + COLOR_RESET
            ]

        menu += [ '│' ]

        if len(card_ids) > 1:
            card_ids_n = len(card_ids)
            # Variable-width display, based on how many cards found
            digits = 1+int(math.log10(card_ids_n))
            # Display index in 1-based counting
            menu += [ ''
                + "(N)/(P):"
                + COLOR_VALUE
                + f"{card_ids_i+1:{digits}d}/{card_ids_n}"
                + COLOR_RESET
            ]

        if term:
            menu += [
                "(B)rowse",
                "(S)earch",
                COLOR_HIGHLIGHT + term + COLOR_RESET,
                # "(G)oogle",
            ]

            if wild_n:
                menu += [ ''
                    + f"(W)ilds:"
                    + COLOR_VALUE
                    + str(wild_n)
                    + COLOR_RESET
                    + ' more'
                ]

        # spell-checker:enable

        menu = ' '.join(menu)
        menu = re.sub(r'\(', COLOR_COMMAND, menu)
        menu = re.sub(r'\)', COLOR_RESET, menu)

        if not options.deck:
            key = 'd'
        elif options.update and updatable and content:
            # Auto-update this card
            key = 'u'
        elif options.scroll and card_ids and card_ids_i < len(card_ids) - 1 :
            logging.debug(f'{card_ids_i=}/{len(card_ids)=}')
            # Auto-scroll through the resultset to the next card. Since the
            # 'update' is checked first, the current card will be updated, if
            # possible, before proceeding to the next card.
            key = 'n'

        hr()
        while not key:
            clear_line()
            print(menu + '\r', end='', flush=True)
            key = readchar.readkey()

            # Don't accept space(s),
            # It might be the user not realizing the pager has ended.
            # NB, this breaks using Space to do_reveal the content when is_reviewing
            # if re.fullmatch(r'\s*', key) :
            #     key = None

        logging.debug(f'{key=}')
        clear_line()

        # TODO smarter way to clear relevant state vars ?
        # What's the state machine/diagram behind all these?

        # TODO refactor the below into a dispatch table
        # Does this really add much value to use 'match'
        # Better to first just refactor big blocks into functions ...
        # Eg:
        # match key:
        #     case 'n' if card_ids_i < len(card_ids) - 1:
        #         card_ids_i += 1
        #     case 'p' | 'N' if card_ids_i > 0:
        #         card_ids_i -= 1

        is_reviewing = False

        if key in ('x', 'q', Key.ESC_ESC) :
            clear_line()
            sys.exit(0)
        elif key in ('.') :
            # Reload this script (for latest changes)
            # And show the last modification time of this file
            tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
            ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
            logging.debug(f"{os.getpid()=} mtime={ts} {sys.argv[0]=}")
            os.execv(sys.argv[0], sys.argv)
        elif key == 'l':
            # Clear screen/card/search
            clear_screen()
            # TODO this needs to be wrapped in a resultset that can be cleared
            # in one command
            term = ''
            card_id = None
            card_ids = []
            card_ids_i = 0
            wild_n = None
            suggestions = []
            content = None
            # scroll_screen()
        elif key == 'd':
            # Switch deck
            clear_screen()

            # TODO this needs to be wrapped in a resultset that can be cleared
            # in one command
            term = ''
            card_id = None
            card_ids = []
            card_ids_i = 0
            wild_n = None
            suggestions = []
            content = None

            decks = get_deck_names()

            # TODO factor out the rendering of table with headings and columns
            # (auto-calculate widths)
            print('  ' + (' ') * 10,
                  BLUE_N,  f'{"N":>4s}',
                  GREEN_N, f'{"R":>3s}',
                  RED_N,   f'{"L":>3s}',
                  COLOR_RESET,
                  sep='',
                  end='\n',
            )
            for dn in decks:
                # This is a bit too slow:
                # empty_n = len(get_empty(dn, ts=time.time()//3600))

                # TODO this is duplicated above, factor out the string(s) for counting/displaying count of new/learn/review
                new_n = stats[dn]['new']
                learn_n = stats[dn]['learn']
                review_n = stats[dn]['review']

                print('* ', f'{dn:10s}', sep='', end='')
                print(BLUE_N  if new_n > 0    else GRAY_N, f'{new_n:4d}',    sep='', end='')
                print(GREEN_N if review_n > 0 else GRAY_N, f'{review_n:3d}', sep='', end='')
                print(RED_N   if learn_n > 0  else GRAY_N, f'{learn_n:3d}',  sep='', end='')

                # TODO factor out the scaling and tick marks drawing

                # Draw a histogram to emphasize the count of due cards, as a per mille ‰
                width = 100
                scale = 1000
                due_n = int( (learn_n+review_n) * width / scale )
                # For tick marks on the axis:
                mod   = int( 100 * width / scale )
                quot = due_n // mod
                rem = due_n % mod
                print(
                    COLOR_RESET,
                    ' |',
                    ('─' * (mod-1) + '|') * quot,
                    '─' * rem,
                    sep=''
                )

            scroll_screen_to_menu(line_pos=len(decks)+1)
            sync()

            deck_prev = options.deck

            # Block autocomplete of dictionary words while choosing a deck,
            # since we want to limit it to deck names
            options.deck = None
            # Push deck names onto readline history stack, for ability to
            # autocomplete, and to be able to Ctrl-P to just scroll up through
            # the list.
            hist_len_pre = readline.get_current_history_length()
            for d in decks:
                readline.add_history(d)

            try:
                selected = input("Switch to deck: ")
                # Remove any leading slash.
                # cf. the Anki GUI; that's how you start a review
                selected = selected.strip()
                selected = selected.lstrip('/')
                if not selected:
                    raise ValueError()
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

            if selected not in decks:
                beep()
                continue
            deck = selected
            # This is so that `completer()` can know what lang/deck we're using
            # for future word autocompletions
            options.deck = deck

            # scroll_screen()
        elif key in ('y', '*') :
            sync()
            edits_n = 0
            sync_last_epoch = int(time.time())
        elif key in ('t', Key.DEL) and card_id:
            if delete_card(card_id):
                edits_n += 1
                del card_ids[card_ids_i]
                card_ids_i = max(0, card_ids_i - 1)
                content = None
                # scroll_screen()
            else:
                beep()
        elif key == 'b' and term:
            # Open Anki GUI Card browser/list, for the sake of editing/custom
            # searches. If there's a term, also append it, so that it'll
            # (likely) be the first result.
            search_anki(term, deck=deck, field='front', browse=True, term=card and card['fields']['Front']['value'])
        elif key == 'e' and card_id:
            # invoke('guiEditNote', note=card_to_note(card_id))
            clear_line()
            print(f'Editing "{front}" ... ', end='', flush=True)
            edit_card(card_id)
        elif key == 'w' and wild_n:
            # wildcard search all fields (front, back, etc)
            card_ids = search_anki(term, deck=deck, field=None)
            card_ids_i = 0
            wild_n = None
            suggestions = []
        elif key in ('n') and card_ids_i < len(card_ids) - 1:
            card_ids_i += 1
            do_reveal = False
        elif key in ('p', 'N') and card_ids_i > 0:
            card_ids_i -= 1
            do_reveal = False
        elif key == 'f' and term:
            # Fetch (remote dictionary service)
            obj = search(term, lang=deck)
            content = obj and obj.get('definition')
            suggestions = obj and obj.get('suggestions') or []
            if content:
                card_id = None
                card_ids = []
            # If any, suggestions/content printed on next iteration.

        elif key == 'r' and card:
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
                    logging.warning("Normalizer not idempotent")

                if content_old == normalized :
                    logging.debug("Identical to origin (normalized)")
                    continue

                hr()
                print(renderer(normalized, front, term=front, deck=deck))

                # print a diff to make it easier to see if any important
                # customizations would be lost
                hr()
                diff_lines = list(difflib.Differ().compare(content_old.splitlines(),normalized.splitlines()))
                for i in range(len(diff_lines)) :
                    diff_lines[i] = re.sub(r'^(\+\s*\S+.*?)$',    GREEN_N + r'\1' + COLOR_RESET, diff_lines[i])
                    diff_lines[i] = re.sub(r'^(\-\s*\S+.*?)$',      RED_N + r'\1' + COLOR_RESET, diff_lines[i])
                    diff_lines[i] = re.sub(r'^(\?\s*\S+.*?)$', WHITE_B + r'\1' + COLOR_RESET, diff_lines[i])
                print(*diff_lines, sep='\n')

                prompt = (''
                    + "\nReplace "
                    + COLOR_COMMAND
                    + front
                    + COLOR_RESET
                    + " with this definition? [N]/y: "
                )
                print(prompt, end='')
                try:
                    reply = readchar.readkey()
                except (KeyboardInterrupt) as e:
                    ...
                if reply and reply.casefold() == 'y':
                    update_card(card_id, back=normalized)
                    edits_n += 1

        elif key == 'o' and term:
            pyperclip.copy(term)
            url = get_url(term, lang=lang)
            for k, v in url.items():
                print(v)
            launch_url(url['wiktionary'])
        elif key == 'a' and term and not card_id:
            add_card(term, content, deck=deck)
            edits_n += 1

            # And search it to verify
            card_ids = search_anki(term, deck=deck)
            card_ids_i = 0
        elif (key in ('1','2','3','4')
            and card_id
            and (is_due(card_id) or is_new(card_id))
        ):
            answer_card(card_id, int(key))
            edits_n += 1
            # Auto-advance
            if card_ids_i < len(card_ids) - 1:
                card_ids_i += 1
            is_reviewing = True
            do_reveal = False
        elif key in (' ') and content:
            is_reviewing = True
            # This allows the content to be revealed on next round
            do_reveal = True
        elif key == 'm' and empty_ids:
            card_id = empty_ids[0]
            term = get_card(card_id)['fields']['Front']['value']
            delete_card(card_id)
            edits_n += 1
            get_empty.cache_clear()
            empty_ids = get_empty(deck)
            card_ids = []
            card_id = None
            wild_n  = None
            # Update readline, as if I had typed this term
            readline.add_history(term)

            # Already have this card in this deck, duplicate ?
            if card_ids := search_anki(term, deck=deck) :
                # BUG this should be an exact search. Implement that flag. Other
                # callers need it too?
                card_ids_i = 0
                continue

            # auto fetch
            clear_line()
            obj = search(term, lang=deck)
            content = obj and obj.get('definition')
            suggestions = obj and obj.get('suggestions') or []
            # If any, suggestions/content printed on next iteration.

        elif key in ('/', 'v'):
            term = ''
            content = None
            # If no cards are due, allow reviewing of new cards, if any
            card_ids = ([]
                or get_due(deck, ts=time.time()//3600)
                or get_new(deck, ts=time.time()//3600)
            )
            card_ids_i = 0
            is_reviewing = True
            do_reveal = False
        elif key in ('s', Key.CTRL_P, Key.UP):
            is_reviewing = False
            do_reveal = False

            # Exact match search

            content = None
            suggestions = []

            # TODO factor the prompt of 'term' into a function?
            clear_line()
            try:
                term = input(f"Search: {deck + '/'}")
            except:
                continue
            term = term.strip()
            if not term:
                card_ids = []
                continue

            # Allow to switch deck and search in one step, via a namespace-like
            # search. (Assumes that deck names are 2-letter language codes.)
            # e.g. 'nl:zien' would switch deck to 'nl' first, and then search
            # for 'zien'. Also allow separators [;/:] to obviate pressing Shift.
            decks_re = '|'.join(decks := get_deck_names())
            if match := re.match('\s*([a-z]{2})\s*[/]\s*(.*)', term):
                lang, term = match.groups()
                if re.match(f'({decks_re})', lang):
                    deck = lang
            else:
                lang = deck

            card_ids = search_anki(term, deck=deck)
            card_ids_i = 0
            # Check other possible query types:
            # TODO: Do all the searches (by trying to minimise exact and wildcard into one request).
            # eg 'wild_n' will always contain the exact match, if there is one, so it's redundant

            wild_n = len(
                set(search_anki(term, deck=deck, field=None)) - set(card_ids)
            )
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
            logging.info(f"\t\t\t\t\t\tUpdated {card_id}\t{front}")
            edits_n += 1

        else:
            logging.debug(f'No matching command for {key=}')
            # Unrecognized command.
            beep()
            # TODO add a '?' function that programmatically lists available
            # shortcuts (if they're available in a dict)

            # TODO could set a flag here to skip (re-)rendering the next round,
            # since redundant


def completer(text: str, state: int) -> Optional[str]:
    completions = []
    if not text:
        return None

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
        s for s in suggestions if ud(s).casefold().startswith(text.casefold())
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

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-k',
        "--deck",
        help=
        "Name of Anki deck to use (must be a 2-letter language code, e.g. 'en')",
    )
    parser.add_argument(
        '-l',
        "--level",
        help=
        "Logging level, eg: [deb(ug), info, warn(ing), err(or), crit(ical)]",
    )
    parser.add_argument(
        '-d',
        "--debug",
        action='store_true',
    )
    parser.add_argument(
        '-s',
        "--scroll",
        action='store_true',
        help=
        "(Auto) iterate over all cards when multiple results. Useful in combo with --update",
    )
    parser.add_argument(
        '-u',
        "--update",
        action='store_true',
        help=
        "(Auto) replace the source of each viewed card with the rendered plain text, if different",
    )
    options = parser.parse_args()

    # Running within a debugger?
    options.debug = options.debug or bool(sys.gettrace())
    # Logging level and defaults
    options.level = options.level or (options.debug and 'DEBUG') or 'WARNING'
    # Allow for prefix-matching too, eg deb => DEBUG, crit => CRITICAL, etc
    levels = logging.getLevelNamesMapping()
    for level_str in levels:
        if level_str.startswith(options.level.upper()):
            options.level = level_str
    level_int = levels.get(options.level, levels['WARNING'])
    level_int = level_int or 1 # The 0 gets ignored, so fallback to 1 for TRACE
    # Also set our general debug mode/flag when loglevel is NOTSET (trace everything)
    options.debug = (options.level in ('NOTSET', 'DEBUG')) or options.debug
    # TODO rather than basicConfig() use custom handlers to also get warnings on stderr
    # And factor that out into a init_log() function
    # stream_handler = logging.StreamHandler(sys.stderr)
    # stream_handler.setLevel(logging.WARNING)
    logging.basicConfig(filename=__file__ + '.log',
                        filemode='a',
                        level=level_int,
                        format=f'%(asctime)s %(levelname)-8s %(lineno)4d %(funcName)-20s %(message)s'
                        )
    logging.info('__main__')

    decks = get_deck_names()
    if not options.deck:
        # This will force the deck selector to open at startup
        options.deck = ''

    logging.debug('options:\n' + pp.pformat(options))

    readline.set_completer(completer)
    readline.set_completer_delims('')
    readline.parse_and_bind("tab:menu-complete")

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
