#!/usr/bin/env python3
"""
Scraper for the ISI Web of Science

See README.md for goals and overview.

Example:
```
S = AnonymizedUWISISession()  #unfortunately, this has only be designed and tested with @uwaterloo.ca
S.login(your, credentials)
Q = S.generalSearch(("TS", "cats"), "OR", ("PY", 2007)) #search: subject 'cats' or year '2007'
len(Q)
Q.export("manycats.ciw", 22, 78)

from isiparse import reader
p1 = next(iter(reader("manycats.ciw")))
print(p1['TI'])  #display title

Q2 = S.inlinks(p1['UT'])
print(len(Q2), p1['TC']) #ISI's citation counts are inconsistent, hinging on which sub-database getting searched    lov
Q2.rip("catlovers.ciw")
```

Query objects are static for the duration of a session---internally ISI doesn't
let you do anything until it has first made a temporary SQL materialized view
(or something equivalent) and tagged it with a qid number.
The bonus is that there is no concern about accidentally missing records during a long running scrape due to data entry.

Be very very very careful with this. It would be very easy to accidentally start
downloading a million records and find a lawyer-happy Thomson-Reuters pie on your face.
"""

#TODO:
# [ ] Obvious refactoring: roll all the extract_() calls into ISIQuery.__init__()
# [ ] rearchitect so that passwords are passed at __init__
# [ ] Rearchitect to use composition instead of inheritence (namely: it's awks that ISISession exposes .post() and .get()) 
#     Doing this while still maintaining the proxy trickery will be a sop.
# [ ] advancedSearch()
#   [ ] besides a manual query string, advanced search has a few extra params like "articles only": support these
# [ ] Use logging.debug() instead of print() everywhere
# [x] Outlinks:
#     Using OutboundService.do with "CITREF" in filters
#     WOS's full_record.do has a "Citation Network" div which links to
#     InterService.do which has the export options of the regular page;
#     indeed, clicking this makes a new qid (hidden) number.
#     This route gives a full ISI record for each
# [x] Inlinks:
#     On a query result page, the "Times Cited" links go to
#     CitingArticles.do which provides all the inlinks.
#     Extract these.
#   [ ] Handle the case where a article has zero inlinks (in which 
# [ ] Make python2 compatible (probably with liberal use of the python-future module)
# [ ] Make ISIQuery more fully featured; in particular, it should be a lazily-loaded sequence which you can iterate over, extracting the basics (via screen scraping)
# [ ] .rip() is a very scripty function. It basically expects an interactive user with a pristine filesystem; it should be not so noisy!
#       -> this is an MVC problem creeping in
# [ ] make Queries record their parameters and write a __str__ which canonicallizes them into a text form, then implicitly use this as fname. Done right, this will really help provenance.
#   -> or at the very least
#   -> tricky because there are soooooooooooooooo many parameters; 
# [ ] add random jitter between requests so we don't look so bottyen as an iterator over the result files? And then that could be combined inline with isijoin.py, and the 


# stdlib imports
import sys, os
#import argparse, optparse, ...
from warnings import warn
import traceback

from itertools import count, cycle
import copy
from urllib.parse import urlparse, urlunparse, quote as urlquote, parse_qsl, urljoin

# library imports
# (users will need to `pip install` these)
import requests
from requests.exceptions import HTTPError
from bs4 import BeautifulSoup

# local package imports
from isiparse import is_WOS_number
from util import *
from httputil import *


class ISIError(HTTPError):
    # TODO: ISI has an inheritence tree of errors available in query param "message_key"; is that tree worth replicating?
    # TODO: this isn't integrating with the requests exception tree properly
    KEY = None #override this in subclasses
    def __init__(self, message_key, msg = None):
        assert self.KEY is None or message_key == self.KEY
        self.message_key = message_key
        self.msg = msg
    def __str__(self):
        return "<%s: %s%s>" % (type(self).__name__, self.message_key, ": " + self.msg if self.msg else "")
        

class InvalidInput(ISIError):
    KEY = "Server.invalidInput"
    
class NoRecordsFound(ISIError):
    KEY = "errors.search.noRecordsFound"
    

# ISIErrors map themelves to error codes 
# make a reverse mapping, so we can look them up at runtime
ISIError.ALL = {e.KEY: e for e in list(locals().values())  if isinstance(e, type) and issubclass(e, ISIError)}

def extract_qid(soup):
    """
    screenscrape the qid of the given query result page
    
    """
    # depending on page, the qid shows up in multiple places
    # The most reliable choice seems to be the hidden form field
    # used so that when you do a refinement search the qid you're coming from gets remembered
    return int(soup.find("input", {"name": "qid"})['value'])

def extract_count(soup):
    """
    screenscrape the count of records for the current qid
    this returns a flag if the result is estimated (to be passed through to ISIQuery).
     This is complexity, but there's just no other way: sometimes we simply do not have enough data.
    
    returns: (count, estimated)
    """
    
    # ideas:
    # - the hitCount.top div (unreliable because on some but not all pages, is constructed *by javascript*)
    # - take the page count, multiply by the page step (inaccurate)
    # - look at the bottom of the page (again, unreliable)
    
    estimated = True #default to the conservative option: saying 'this result sucks'
    
    count = soup.find(id="footer_formatted_count")
    if count is not None:
        # found at the bottom of the page
        count = count.text
        estimated = "approximately" in count.lower()
        
        count = count.split()[-1] #chomps the 'approximately', if it exists
    else:
        # 
        count = soup.find(id="hitCount.top")
        if count is not None:
            # found in hitCount.top div
            count = count.text
            #TODO: there's probably hitCount.top pages that have estimated results, and we totally ignore that case
        else:
            raise ValueError("Query count not found on page")
    
    count = parse_american_int(count)
    return count, estimated

def extract_search_mode(soup):
    """
    [...]
    """
    search_mode = soup.find("input", {"name": "search_mode"})
    if search_mode is None:
        # retry with 'search_mode1', which shows up on some but not all pages
        search_mode = soup.find("input", {"name": "search_mode1"}) #LOL
        if search_mode is None:
            raise ValueError("search_mode not found on page")
    
    search_mode = search_mode['value']
    return search_mode


class ISIResponse(requests.Response):
    """
    Extend an requests.Response to translate ISI's frustratingly non-standard
    non-HTTP error messages into HTTPErrors.
    
    Actually, translates them to ISIErrors, but these are subclasses of those.
    """
    def __new__(cls, response, *args, **kwargs):
        #print("ISIResponse.__new__:", cls, id(response), response, args, kwargs) #DEBUG
        # a canonical wrapper would use {g,s}etattr() overloading
        # why do that when we can just carefully tweak the class response thinks it is?
        # this has the same effect: it adds all the methods defined below to the object's search path, walking up to requests.Response otherwise
        #
        # I hope this doesn't bite us down the line
        assert isinstance(response, cls.__mro__[1]), "Make sure the argument is in the expected inheritence tree"
        response = copy.copy(response)
        response.__class__ = cls
        
        # DEBUG
        # being able to see what ISI gives back helps, especially since ISI seems to return 200 OK for *everything* except actual URL typos
        #with open("what.html","w") as what:
        #    what.write(soup.prettify())
        
        return response
    
    def __init__(self, response, *args, **kwargs): #this is only defined to silence the 'response' argument
        #print("ISIResponse.__init__:", id(self), self, id(response), args, kwargs) #DEBUG
        pass #we're already initialized because we copy-constructed in __new__()
        
    def raise_for_status(self):
        """
        raise an error on HTTP status messages *or* on on errors from the ISI thingy 
        
        """
        # first call up, because a 404 will prevent us doing all the rest of the checks
        #super().raise_for_status()
        requests.Response.raise_for_status(self)  #<-- copy.copy() breaks super(); for now, hardcode the parent class. TODO: figure out what magic bit needs twiddling.
        
        # TODO: look at message_key=errors.search.noRecordsFound&error_display_redirect=true instead
        # client_error_input_message is not always where the error is writting; there's also noHitsMessage and newErrorHead
        # 
        
        params = qs_parse(urlparse(self.url).query)
        if 'error_display_redirect' in params:
            assert params['error_display_redirect'] == 'true', "ISI only gives this tag if an error actually happened"
            assert 'message_key' in params, "and in that case, it will give the error key in this"
            err = params['message_key']
            
            # if we see an error, extract the text to go with it by screen scraping
            # 
            msg = ""
            soup = BeautifulSoup(self.content)
            soup = soup.find("div", class_="errorMessage")
            for div in soup("div"):
                # the error might appear in any of several different sub-divs
                # my kludgey approximation is to take the first one we see
                # if we see any
                if div.text.strip():
                    msg = div.text.strip()
                    break
                        
            raise ISIError.ALL.get(err, ISIError)(err, msg) #look up the appropriate ISIError, falling back on ISIError itself if not known, and instantiate it
        

class ISISession(requests.Session):
    """
    A requests.Session that hardcodes the magic URLs needed to access http://apps.webofknowledge.com/
    """
    
    def login(self, *args, **kwargs):
        super().login(*args, **kwargs)
        
        # hit the front page of WoS to extract relevant things that let us pretend to be a Real Browser(TM) better
        r = self.get("http://isiknowledge.com/wos") #go to the front page like a normal person and create a session
        r.raise_for_status()
        # find the WoS SID (which is different than the ezproxy SID!)
        self._SID = qs_parse(urlparse(r.url).query)["SID"]
        self._searchpage = r.url
        # TODO: scrape the search page to extract all the form fields and the form target
        # TODO.. other key things to scrape??
    
    def request(self, *args, **kwargs):
        response = super().request(*args, **kwargs)
        response = ISIResponse(response)
        return response
    
    
    def _generalSearch(self, *fields, timespan=None, editions=["SCI", "SSCI", "AHCI", "ISTP", "ISSHP"], sort='LC.D;PY.A;LD.D;SO.A;VL.D;PG.A;AU.A'):
        """
        Backend for generalSearch(); factored out since some of the other extractions *can only work by first doing a regular search*. ugh.
        
        returns HTTPResponse
        """
        max_field_count = 25
        
        # There are a lot of things that get posted to this form, even though it's just the simple search.
        # most of these were copied raw from a working query
        # most of them are ridiculously unusable and redundant and possibly ignored on the backend
        # but WHEN IN ROME...
        # 
        # For readability, I split up the construction of the POST data into a sections, with a generator for each.
        # They are underscored to avoid conflicts with the input arguments.
        
        def _session():
            """ 
            This is header stuff needed to convince the search engine to listen to us
            """
            yield 'product', 'WOS' # 'UA' == "all databases", "..." == korean thing, "..." = MedLine, ...; we want WOS because WOS can give us bibliographies, not just 
            yield 'action', 'search' 
            yield 'search_mode', 'GeneralSearch'
            yield 'SID', self._SID
        
        def _cruft():
            """
            this is crap ISI probably ignores
            TODO: try commenting this out and seeing if anything breaks. (requires a working test suite, which is annoying because the only server to test against is the real one)
            """
            # (the browser is sending hardcoded error messages as options in its *query*??)
            yield 'input_invalid_notice', 'Search Error: Please enter a search term.'
            yield 'exp_notice', 'Search Error: Patent search term could be found in more than one family (unique patent number required for Expand option) '
            yield 'max_field_notice', 'Notice: You cannot add another field.'
            yield 'input_invalid_notice_limits', ' <br/>Note: Fields displayed in scrolling boxes must be combined with at least one other search field.'
            # LOL what are these for?? "Yes, I Love Descartes Too"
            yield 'x', '0',
            yield 'y', '0',
            # whyyyyyy
            yield 'ss_query_language', 'auto'
            yield 'ss_showsuggestions', 'ON'
            yield 'ss_numDefaultGeneralSearchFields', '1'
            yield 'ss_lemmatization', 'On'
            yield 'limitStatus', 'collapsed'
            yield 'update_back2search_link_param', 'yes'
            #'sa_params': "UA||4ATCGy9dQvV3rtykDa3|http://apps.webofknowledge.com.proxy.lib.uwaterloo.ca|'", #<-- TODO: this seems to repeat things passed elsewhere: product, SID, and URL. The first two I can get, but the URL is tricky because I've abstracted out from coding against the UW proxy directly
                # but I suspect the system won't notice if it's missing...
            yield 'ss_spellchecking', 'Suggest'
            yield 'ssStatus', 'display:none'
            yield 'formUpdated', 'true'
        
        # This is the actual fields
        # This part is rather complicated. This ISI's fault.
        def _fields():
            """
            this generator walks the input and reformats it into key-value pairs 
            returns the number of fields searched (which you need to retrieve from the StopIteration)
            Note: the number of times this yields is larger than the number of fields actually represented, because of ISI cruft, so you can't simply len() the result.
            """
            for i in range(0, len(fields), 2):
                t = (i//2)+1 #terms correspond to every other index, and are themselves indexed from 1
                
                # the field term
                # TODO: wrap this in a better typecheck, because the user has to pass a complicated
                # datastructure down and, if wrong, will get a crash in this pretty obscure place
                (field, querystring) = fields[i]
                
                if isinstance(querystring, list): #TODO: be more geneerric
                    # attempt to coerce lists to the format used by GeneralSearch.do for OR'd enumerations
                    # This is to ###-separarate the points
                    # as far as I know, this is *only* used for but we'll leave that up to the user
                    querystring = str.join("###", querystring)
                
                yield "value(select%d)" % t, field
                yield "value(input%d)" % t, querystring 
                yield "value(hidInput%d)" % t, "" #the fantastic spaztastic no-op hidden input field
                
                # the operand term
                if fields[i+1:]:
                    op = fields[i+1]
                    assert op in ["AND","OR","NOT","SAME","NEAR"], "ISI only knows these operators"
                    yield "value(bool_%d_%d)" % (t,t+1), op
                else:
                    # last field; don't include the operand term
                    assert len(fields)-1 == i, "Double checking I got the if right"
            
            if t > max_field_count:
                warn("Submitting %d > %d fields to ISI. ISI might balk." % (fieldCount, max_field_count))
            yield 'fieldCount', t  #the number of fields processed
            yield 'max_field_count', max_field_count #uhhhh, and what happens if I ignore this? omg, I bet ISI is full of SQL injections. :(
        
        def _period():
            """    
             the period is actually several sub-fields together; as in fields2isi we re-interpret the python arguments into ISI's crufty form
            """
            #default values, as on the HTML form
            period = "Range Selection" # this decides whether we're using the range drop down or the year dropdowns
            range = "ALL"  #this is the value of the range dropdown
            startYear, endYear = 1900, 2000 #this is the value of the year dropdowns
            # obviously, only one of the latter two actually matters, but we POST both because we want to be as close to a browser as possible to avoid mishaps.
            
            if timespan is not None:
                try:
                    # (startYear, endYear)
                    startYear, endYear = timespan
                    period = "Year Range"
                except:
                    if isinstance(timespan, int):
                        # (year,)
                        startYear, endYear = timespan, timespan
                        period = "Year Range"
                    else:
                        # special-case ISI timespan
                        assert timespan in ["ALL","Latest5Years","YearToDate","4week","2week","1week"], "ISI only knows these timespans, besides year ranges."
                        range = timespan
                
            yield ("period", period)
            yield ("startYear", startYear)
            yield ("endYear", endYear)
            yield ("range", range)
        
        def _sort_order():
            yield 'rs_sort_by', sort
        
        def _editions():
            for e in editions:
                yield ("editions", e)
        
        # merge all the sections
        # note: we have to use lists of key-value pairs and not dicts because ISI repeats some parameter names
        # += on a list L and a generator G is the same as .extend(); note that L + G will *not* work.
        form = []
        form += _session()
        form += _cruft()
        form += _fields()
        form += _sort_order()
        form += _editions()
        
        #print(form) #DEBUG
        #import IPython; IPython.embed() #DEBUG
        
        # Do the query
        # this causes ISI to create and cache a resultset
        r = self.post("http://apps.webofknowledge.com/WOS_GeneralSearch.do",
                headers={'Referer': "http://apps.webofknowledge.com/WOS_GeneralSearch.do?product=WOS&SID=%s&search_mode=GeneralSearch" % self._SID}, #TODO: base this URL on the data above
                data=form)
        return r
        
    def generalSearch(self, *fields, timespan=None, editions=["SCI", "SSCI", "AHCI", "ISTP", "ISSHP"], sort='LC.D;PY.A;LD.D;SO.A;VL.D;PG.A;AU.A'):
        """
        Perform a search of the http://apps.webofknowledge.com/WOS_GeneralSearch_input.do form.
        
        fields gives the fields to search; the keyword arguments give the other options.
        
        fields:
            specifies what to search for. This tuple should alternate between fields and operators.
            Specifically, it alternates between:
            - (field, querystring) pairs
              - Field Tags:
                    TS= Topic
                    TI= Title
                    AU= Author
                    AI= Author Identifiers
                    GP= Group Author
                    ED= Editor
                    SO= Publication Name
                    DO= DOI
                    PY= Year Published
                    CF= Conference
                    AD= Address
                    OG= Organization-Enhanced
                    OO= Organization
                    SG= Suborganization
                    SA= Street Address
                    CI= City
                    PS= Province/State
                    CU= Country
                    ZP= Zip/Postal Code
                    FO= Funding Agency
                    FG= Grant Number
                    FT= Funding Text
                    SU= Research Area
                    WC= Web of Science Category
                    IS= ISSN/ISBN
                    UT= Accession Number (aka WOS number: the unique document ID within the WOS database)
                    PMID= PubMed ID 
                You can reuse fields, though it's easy to end up with empty resultsets if you do this.
                Reference: http://apps.webofknowledge.com/WOS_AdvancedSearch_input.do
                           http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_wos_fieldtags.html
                    WARNING: these two pages give inconsistent lists of fields:
                      the first uses "PMID" and the second "PM"
                      the first uses "IS" and the second "BN" to refer to ISBN, much like Harry and Draco.
                      the first doesn't list "DT" and some other fields
                      You apparently can search by anything in the fuller list, regardless.
              - querystring is fed directly into ISI unchecked.
                Anything you can use from the http://isiknowledge.com/wos search engine you can use here (and if things aren't working, try it via the Web UI first).
                ~Generally~ you can use ranges ("2007-2010"), globbing (?, +, *), and boolean operators ("WOS:000348623400019 OR WOS:000348623400022") here, so long as it makes sense.
                Reference: http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_search_rules.html
                Let it be reiterated that this string is fed into ISI **UNCHECKED**, which makes it both powerful and a pain.
            - operator strings: AND, OR, NOT, NEAR, SAME; also fed into ISI unchecked.
                Reference: http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_search_operators.html
            The length of fields should be an odd number because there should be exactly one less operator than query pairs.
            It also, apparently, should not contain more than 49 fields.
            This is an awkward format; you're just going to have to DEAL WITH IT. It's better than trying to parse a string before feeding it.
        timespan: optional timespan to restrict results to.
            Can be:
             - "ALL"
             - "Latest5Years"
             - "YearToDate"
             - "4week"
             - "2week"
             - "1week"
             - an integer year
             - or a pair (startYear, endYear)
            The first set correspond to the first radio button on the search page next to a dropdown;
            The last two correspond to second next to the two year range selection dropdowns (a single integer period=y is the same as period=(y,y)).
            If timespan==None, assumes "ALL"
            (yes, this appears to be partially redundant with the "PY" field. Try not to cringe too much.)
            
        editions: the list of WoS subsections to search:
            #TODO: document what these are
            The default is all known, so you can probably leave it alone mostly.
        sort: the sort order to return
            This isn't actually an option on the form, but it's sent along with the request and is useful
            Currently, passed unchecked to ISI. Thus, it must be given in ISI's internal notation which is this pattern:
            ({field}.{order}(.{lang})?;)*
            * field is a field tag
            * order is "A" for ascending or "D" for descending.
            * lang is an optional 2-letter language code which only applies to certain fields; I don't know what this is for.
            This is essentially a normal table order-by clause:
                records are first sorted by the first field given; ties are broken by looking at the second, if given; ties in that are broken by looking at the third, etc
                Additionally(??) there's extra fields allowed here not listed above? like "LC" which is the citation count (which, confusing, is given as "TC" in the ISI format).
            The default puts most cited and oldest articles first, since those are probbbbbably the articles you care about if you're doing scraping.
        
        # TODO: if we don't get any results we get sent back to GeneralSearch.do; handle this case
        
        returns an ISIQuery object. See ISIQuery for how to proceed from there.
        """
        r = self._generalSearch(*fields, timespan=timespan, editions=editions, sort=sort)
        
        Q = ISIQuery.fromPage(self, r)
        assert Q._search_mode == 'GeneralSearch'
        return Q
        
    def advancedSearch(self, query):
        """
        query should be a string in the form
        """
        raise NotImplementedError
    
    def search(self, topic):
        """
        perform a simple of the Web of Science
        """
        return self.generalSearch(('TS', topic))
    
    def outlinks(self, document):
        """
        Given an ISI document ID (aka WOS number aka UT field aka Accession Number),
        get an ISIQuery over all the documents it cites.
        
        Now, you also get outlinks in the "CR" field, but those are badly mangled
        MLA-esque single line citations; this API actually gives you the full records.
        However, we make no guarantees that these results match up to the "CR" results; that's up
        to ISI (and their database is full of varying formats and inconsistencies).
        In particular, the WOS includes citations to articles which it does not have;
        in this case, the missing records are silently elided during ISIQuery.export().
        If your record counts are not adding up, and especially if you are getting empty .ciw files,
        try the search by hand and see if the results lists "Title: [not available]".
        
        If you use this across a set of related records, you are likely to get duplicates.
        You will just have to merge them by WOS number.
        
        This method does not pretend very well to be a proper browser:
         a proper browser would first search for the WOS number with WOS_GeneralSearch.do
         then click on the link to the article's full_record.do page
         then click on the InterService.do link.
        This method goes straight for the jugular.
        """
        assert is_WOS_number(document)
        
        def _session():
            yield "product", "WOS"
            yield "last_prod", "WOS"
            yield "parentProduct", "WOS"
            yield "toPID", "WOS"
            yield "fromPID", "WOS"
            yield "action", "AllCitationService"
            yield "search_mode", "CitedRefList"
            yield "isLinks", "yes" #maybe this belongs in cruft()
            yield "SID", self._SID
        
        def _cruft():
            yield "returnLink", "http://gilgamesh" #this is, apparently, ignored. Still, TODO: something reasonable, like maybe the same value as headers.referer
            yield "srcDesc", "RET2WOS"
            yield "srcAlt", 'Back+to+Web+of+Science<span+class="TMMark">TM</span>' #HAHAHAHAH
            yield "parentQid", 1 #this is ignored, apparently
            yield "parentDoc", 1 #this too; though you'd think that this should somehow be linked to the WOS number you're earc
            yield "PREC_REFCOUNT", 1 #wot?
            yield "fromRightPanel", "true"
        
        def _query():
            yield "UT", document # this is actually irrelevant: this is used to generate the "From:" header on the page, but it does not affect the search results, hilariously
            yield "recid", document #this one controls the actual search results
        
        form = []
        form += _session()
        form += _cruft()
        form += _query()
            
        r = self.get("http://apps.webofknowledge.com/InterService.do",
                     headers={'Referer': "http://apps.webofknowledge.com/WOS_GeneralSearch.do?product=WOS&SID=%s&search_mode=GeneralSearch" % self._SID}, #TODO: base this URL on the data above
                     params=form) #the outlinks page takes query params, not form POST params; luckily python-requests makes this distinction trivial
        
        Q = ISIQuery.fromPage(self, r)
        assert Q._search_mode == 'CitedRefList'
        return Q
    
    def inlinks(self, document):
        """
        Given an ISI document ID (aka WOS number aka UT field aka Accession Number),
        get an ISIQuery over all the documents that cites it.
        """
        assert is_WOS_number(document)
        
        # there is no way to go for the jugular with this one
        # there is a magic REFID number (an ISI-global ID?) which is *not* the
        # WOS number and has no obvious embedded in a link labeled "Times Cited"
        # We do an entire search just to extract the magic link.
        # And we cannot just use generalSearch() because there's no
        # reasonable way for an ISIQuery to know the magic REFID numbers.
        r = self._generalSearch(("UT", document))
        r.raise_for_status()
        
        soup = BeautifulSoup(r.content)
        
        records = soup(class_="search-results-item")
        assert len(records) == 1, "Since we searched by WOS number, we should only have one result"
        soup = records[0]
        
        cites = soup.find(class_="search-results-data-cite")
        
        link = cites("a")
        assert len(link) == 1, "Ditto"
        link = link[0]
        
        assert link['href'].startswith("/CitingArticles.do"), "The link should be to the inlinks page: CitingArticles.do"
        link = link['href']
        
        base = r.url
        link = urljoin(base, link) #resolve the relative link
        
        r = self.get(link, headers={'Referer': r.url}) #we don't need to deal with params cruft
        # appppparently hitting this with GET creates a new qid on the backend
        
        
        Q = ISIQuery.fromPage(self, r)
        assert Q._search_mode == 'CitingArticles'
        return Q
    
    #def __str__(self):
    #    return "<%s: %s " % (type(self),) #???





class UWISISession(ISISession, UWProxy):
    pass

class AnonymizedUWISISession(AnonymizedUAMixin, UWISISession):
    pass


class ISIQuery:
    """
    You need to create queries in order to extract anything from WOS,
    because their search engine works by first caching result sets.
    
    This class is a brittle nougat shell around a creamy WoS result set.
    """
    def __init__(self, session, search_mode, qid, referer, N=None, estimated=None):
        """
        
        Args:
            search_mode: 'GeneralSearch', 'AdvancedSearch', 'CitedRefList' or 'CitingArticles'
                This is needed to properly tweak the behaviour of the request
                to match the type of search on the server in qid. Incorrect,
                instead of an error, ISI will simply export an empty UTF-8 file
                 (it will have exactly two bytes: the Unicode BOM)
                 TODO: perhaps this is a good place to use an inheritence tree instead of an embedded if-else tree?
            qid: the id (generally a small integer) of the resultset this instance is wrapping.
                (search_mode, qid) need to be consistent together, or else operations will fail in mysterious ways.
            referer: the URL of the page; this is used both for some operations and for making the HTTP headers look less suspicious.
            N is the number of results in the query set, if known.
            estimated: whether 'N' is an approximation or not
        """
        self._session = session
        self.SID = session._SID
        self._search_mode = search_mode
        self.qid = qid
        self.referer = referer
        self._len = N
        self.estimated = estimated
    
    @classmethod
    def fromPage(cls, session, http_response):
        """
        construct an ISI query from a query result page
        the page, of course, should be something representing a qid
        """
        http_response.raise_for_status() #XXX does this belong in here or outside?
        
        soup = BeautifulSoup(http_response.content)
        
        qid = extract_qid(soup)
        count, estimated = extract_count(soup)
        search_mode = extract_search_mode(soup)
        
        return ISIQuery(session, search_mode, qid, http_response.url, count, estimated)
    
    def __len__(self):
        return self._len
    
    
    def _export(self, start, end, format="fieldtagged"):
        """
        backend for export()
        """
        assert start >= 0 and end >= 0
        assert start < end
        assert end - start <= 500, "ISI disallows more than 500 records at a time"
        
        params = {
                            # export ALL THE THINGS
                            # TODO: make configurable
                            'fields_selection': 'PMID USAGEIND AUTHORSIDENTIFIERS ACCESSION_NUM FUNDING SUBJECT_CATEGORY JCR_CATEGORY LANG IDS PAGEC SABBR CITREFC ISSN PUBINFO KEYWORDS CITTIMES ADDRS CONFERENCE_SPONSORS DOCTYPE CITREF ABSTRACT CONFERENCE_INFO SOURCE TITLE AUTHORS  ',
                            'filters': 'PMID USAGEIND AUTHORSIDENTIFIERS ACCESSION_NUM FUNDING SUBJECT_CATEGORY JCR_CATEGORY LANG IDS PAGEC SABBR CITREFC ISSN PUBINFO KEYWORDS CITTIMES ADDRS CONFERENCE_SPONSORS DOCTYPE CITREF ABSTRACT CONFERENCE_INFO SOURCE TITLE AUTHORS  ',
                            
                            
                            # TODO: make configurable
                            'sortBy': 'PY.A;LD.D;SO.A;VL.D;PG.A;AU.A',
                            'locale': 'en_US',
                            
                            # DUPLICATED LOL
                            'markFrom': str(start),
                            'mark_from': str(start),
                            'markTo': str(end),
                            'mark_to': str(end),
                            
                            # just because they didn't already know you were searching the Web of Science
                            'product': 'WOS',
                            'mark_id': 'WOS',
                            'colName': 'WOS',
                            
                            # now this part is important
                            'SID': self._session._SID,
                            'search_mode': self._search_mode,
                            'qid': self.qid,
                            
                            'mode': 'OpenOutputService', # I bet WOS is programmed in Java.
                            'format': 'saveToFile', # this is called 'format'; this corresponds to the ["Save to EndNote Online", "Save to EndNote Desktop", ..., "Save to Other File Formats", ...] dropdown.                                               
                            'save_options': format, # for our purposes, it's not actually the format; we choose "save to other file formats" always and fill in which sub-format via save_options.
                                                    # (format, save_options) = ("saveToRef", _) is identical to both ("saveToFile", {"fieldtagged","othersoftware"}): it gives the ISI Flat File format.
                                                    # the one difference is it sets the extension to .ciw instead of .txt, but we ignore the Content-Disposition header anyway. 
                            
                            # cruft?
                            'displayCitedRefs': 'true',
                            'displayTimesCited': 'true',
                            
                            'viewType': 'summary',
                            'view_name': 'WOS-summary',
                            'IncitesEntitled': 'no',
                            'count_new_items_marked': '0',
                            
                            'value(record_select_type)': 'range', #if set to 'pagerecords' then
                            'selectedIds': '',                    #<-- this gives a semicolon-separated list of indexes of which records to extract 
                            
                            'rurl': 'http://isiknowledge.com', #yep TODO: this should be generated by a combination of qid, search_mode, and guessing
                            'queryNatural': '<b>TOPIC</b>: EVERYTHING IS AWESOME WHEN YOURE PART OF A TEAM', #..this one is just going to have to be stuck like this
                           }
        
        # append mode-specific cruft
        # (some of these are actually updates, overwriting the defaults extracted from GeneralSearch
        #TODO: this is a lot more like a dictionary of dictionaries than an if-else tree
        if self._search_mode == 'GeneralSearch':
            # generalSearch()
            #params.update({})
            pass #defaults above were extracted from GeneralSearch mode
        elif self._search_mode == 'AdvancedSearch':
            # advancedSearch()
            raise NotImplementedError
        elif self._search_mode == 'CitedRefList':
            # outlinks()
            params.update({'view_name': 'WOS-CitedRefList-summary',
                           
                           'mode': 'CitedRefList-OpenOutputService', #without this, the output is empty (but *not* an error, ugh)
                           'mark_id': 'UDB', #???? this seems to be ignored, but is set differently in CitedRefList mode
                           
                           # *undo* the DOWNLOAD ALL THE THINGS option
                           # TODO: experiment with this; can we get ALL THE THINGS even out of CitedRefList-OpenOutputService?
                           'fields_selection': 'AUTHORSIDENTIFIERS ISSN_ISBN ABSTRACT SOURCE TITLE AUTHORS  ',
                           'filters': 'AUTHORSIDENTIFIERS ISSN_ISBN ABSTRACT SOURCE TITLE AUTHORS  ',
                            
                           })
        elif self._search_mode == 'CitingArticles':
            # inlinks()
            params.update({'view_name': 'WOS-CitingArticles-summary',
                            
                            # apparently mode can be left at default here?
                            })
        elif self._search_mode == 'TotalCitingArticles':
            # CitationReport > Citing articles
            params.update({'view_name': 'WOS-TotalCitingArticles-summary',
                            
                            # apparently mode can be left at default here?
                            })
        elif self._search_mode == 'NonSelfCitingTCA':
            # CitationReport > Non-self-citing articles
            params.update({'view_name': 'WOS-NonSelfCitingTCA-summary',
                            
                            # apparently mode can be left at default here?
                            })
        else:
            raise ValueError("Unknown search_mode '%s'" % (self._search_mode,)) #XXX check this in __init__ instead?
        
        assert len(params) == 27, "Expected number of params, extracted by hand-counting in Firefox's web inspector"
        # fire!
        r = self._session.post("http://apps.webofknowledge.com/OutboundService.do?action=go",
                           headers={'Referer': self.referer},
                           data=params)
        return r
    
    def export(self, fname, start=1, end=500, format="fieldtagged"):
        """
        Request records export via the "Save to Other File Formats" dialog.
        Export records for the current query startinf running start through end-1.
        
        format:
         - fieldtagged or othersoftware -- ISI Flat File format
         - {win,mac}Tab{Unicode,UTF8}   -- variants of TSV
         - bibtex                       -- for LaTeX junkies
         - html                         -- if you hate yourself
        
        Returns the HTTP response from ISI's OutboundService.do,
        because I don't want to corner your choices, though this
        does mean you get more information than you expect, probably.
        """
        r = self._export(start, end, format)
        r.raise_for_status()
        
        # TODO: logging.debug()
        print("Exporting records [%d,%d) to %s" % (start, end, fname), file=sys.stderr) #TODO: if we start multiprocessing with this, we should print the query in here to distinguish who is doing what. Though I suppose printing the filename is equally good.
        with open(fname,"wb") as w:
            w.write(r.content) #.content == binary => "wb"; .text would => "w"
    
    
    def bulk_inlinks(self, loops=True):
        """
        ISI provides an obscure way to extract all the in-links that go to a particular search
        But only if the search has less than 10 000 records.
        
        You can access this by
          i. doing a search
         ii. clicking "Creating Citation Report" --- if it appears, which it might not
        iii. clicking "Citing Articles [?] : 	$n"  or  "Citing Articles without self-citations [?] : 	%d"
         iv. exporting as with other searches
       
        arguments:
            loops: whether to use ISI's "Citing Articles" (True) or "without self-citations" (False) options
         
        #TODO: document more clearly what loops=False does
        """
        
        # 0) do a query and get its qid 
        # [..already done: we're in the result]
        
        # 1) "click" Create Citation Report with reference to the current qid
        # --> note: if the query set is too large ISI will deny this
        #  this will make a *new* qid with search_mode == "CitationReport"
        params = {
                  #session
                  'SID': self.SID,
                  
                  #query
                  'search_mode': 'CitationReport',
                  'cr_pqid': self.qid,
                  
                  # cruft
                  'product': 'WOS',
                  'colName':' WOS',
                  'page': 1,
                  'viewType': 'summary',
                  }
          #TODO factor this for error catching
        base = self.referer
        link = "/CitationReport.do"
        link = urljoin(base, link)
        r = self._session.get(link,
                              headers={'Referer': base},
                              params=params)
        r.raise_for_status()
        soup = BeautifulSoup(r.content)
        
        # 2) "click" TotalCitingArticles.do, given the CitationReport qid
        #  this will make a third qid with search_mode == "TotalCitingArticles"
        # to get the link to "click" we could reverse engineer the CGI as in generalSearch()
        # or we could do screenscraping. *However* screenscraping doesn't work because about
        # half of the variable pieces of the page (and half not!) are generated by javascript.
        # find the qid of the CitationReport:
        citationreport_qid = extract_qid(soup) #<-- thank you lazy coders
        
        # construct the bulk inlinks request 
        base = r.url
        params = {'product': 'WOS',
                  'qid': citationreport_qid,
                  'SID': self.SID,
                  'betterCount': "Soy sauce as a stimulative agent in the development of beriberi in pigeons", #this is not ignored, but rather
                  #*if an integer* is fed straight into the count on the resultset page; if not an integer, ISI computes the proper value. Hurrah!.
                  # This is just a UI glitch; export() can extract all records regardless,
                  # but we should try to not make the API appear inconsistent.
                  # (this string is a paper in the WOS database. cutting edge science!)
                  }
        if loops:
            link = "/TotalCitingArticles.do"
            params.update({'search_mode': "TotalCitingArticles",
                           'action': "totalCA"})
        else:
            link = "/NonSelfCitingArticles.do"
            params.update({'search_mode': "NonSelfCitingTCA",
                           'action': "nonselfCA"})
        
        link = urljoin(base, link)
        r = self._session.get(link,
                              headers={'Referer': base},
                              params=params)
        
        Q = ISIQuery.fromPage(self._session, r)
        assert Q._search_mode == params["search_mode"]
        return Q
        
    
    def rip(self, fname, upper_limit=20000):
        """
        Export all records available in this query.
        
        fname: file name. used as a template: if fname == "fname.ext" then records will be exported to ["fname_0001.ext", "fname_0501.ext", ...] 
        upper_limit: the largest record index to export; use this to make an easy guarantee that you won't get stomped by ISI for chewing through their data.
        """
        
        #note!: the web UI declines to let you export more records than available, however the API will accept such a request and just only give you which records it has available.
        #       Here, the *last record block* is making such an illegal request: it requests 500 even if there's only one; it's currently working but it might break if ISI tightens up their game. 
        #       We could use len(self) to determine how many to request, but len(self) is not accurate when self.estimated==True, which happens in large result sets ((on the other hand, you really, really, really should not be ripping large result sets: you'll get yourself banned and/or sued))
               
        base_name, ext = os.path.splitext(fname)
        for k in count(): #TODO: use range() here to somehow get the upper and low bounds simultanouesly
            block = 500*k + 1 #+1 because ISI starts counting at 1, of course
            if upper_limit and block > upper_limit: break
            fname = "%s_%04d%s" % (base_name, block, ext)
            try:
                r = self.export(fname, block, block+500)
            except InvalidInput as exc:
                # break when we run off the end of the valid inputs
                # this is just a littttle bit flakey
                #print("quitting on block %d due to:" % (k,)) #DEBUG
                #print(exc, file=sys.stderr) #DEBUG
                #traceback.print_exc() #DEBUG
                break
    
    def __str__(self):
        return "<%s: %d records%s>" % (type(self).__name__, len(self), " (approximately)" if self.estimated else "") #<-- this could be better
    

def tos_warning():
    print("In using this to download records from the Web of Science, you should be aware of the terms of service:")
    print()
    print(
    "Thomson Reuters determines a “reasonable amount” of data to download by comparing your download activity\n"
    "against the average annual download rates for all Thomson Reuters clients using the product in question.\n"
    "Thomson Reuters determines an “insubstantial portion” of downloaded data to mean an amount of data taken\n"
    "from the product which (1) would not have significant commercial value of its own; and (2) would not act\n"
    "as a substitute for access to a Thomson Reuters product for someone who does not have access to the product.")
	# but they don't seem to say 'no botting', just 'no excessive downloading', which sort of implies they expect some amount of botting.
    print()
    print("The authors of this software take no responsibility for your use of it. Don't get b&.")
    print("")


# ----------------------------- main

if __name__ == '__main__':
    import argparse, datetime
    
    # TODO: pass barcode via stdin to hide it from ps auxww
    # TODO: support non-UW logins
    
    ap = argparse.ArgumentParser(description="Export paper associated metadata from the Web of Science. Currently only works for University of Waterloo members.")
    ap.add_argument('user', type=str, help="Your last name, as you use to log in to the UW library proxy")
    ap.add_argument('barcode', type=str, help="Your 14 digit library card barcode number (not your student ID!)")
    ap.add_argument('query', type=str, nargs="+", help="A query in the form FD=filter where FD is the field and filter is what to search for in that field.")
    ap.add_argument('-q', '--quiet', action="store_true", help="Silence most output")
    ap.add_argument('-d', '--debug', action="store_true", help="Enable debugging")
    ap.epilog = """
    Fields are given by two letter codes as documented at http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_wos_fieldtags.html.
    Filters support globbing as documented at http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_search_rules.html.
    
    If multiple queries are given they will be ANDed together.
    
    ISI supports more search parameters than exposed here.
    If you need more control you can use this program as a library:
    ```
    import isi_scrape
    help(isi_scrape.UWISISession)
    ```
    
    All records in the resultset will be automatically exported, 500 at a time, to the current directory.
    Currently, the exported filenames will be the session ID ISI's web framework assigned, in lieu of something more meaningful. 
    """ #^TODO: argparse helpfully reflows the text but this fucks up the formatting that I do want. What do?
    
    
    args = ap.parse_args()
    
    #by sorting we enforce that each search has a unique reference for each search
    args.query = sorted(args.query)
    
    if args.debug: #<-- a bit dangerous, since if -d breaks we won't know it 
        print(args) #DEBUG
    
    def parse_queries(Q):
        for e in Q:
            
            try:
                field, query = e.split("=")
                yield field, query
            except:
                ap.error("Incorrectly formatted query '%s'" % (e,))
    query = list(parse_queries(args.query))
    
    if not args.quiet:
        tos_warning()
    
    try:
        
        query = flatten(zip(query,  cycle(["AND"]))) #this line is line "AND".join(query)
        query = query[:-1] #chomp the straggling incorrect, "AND"
        
        S = AnonymizedUWISISession()
        S.login(args.user, args.barcode)
        
        print("Logged into ISI as UW:%s." % (args.user,))
        
        print("Querying ISI for %s" % (query,)) #TODO: pretty-print
        Q = S.generalSearch(*query)
        print("Got %s%d results" % ("an estimated " if Q.estimated else "", len(Q)))
        
        # make a new folder for the results, labelled by the query used to generate them
        strquery = str.join(" ", (args.query))
        results_folder = strquery.replace(" ","_") #TODO: find a generalized make_safe_for_filename() function. That's gotta exist somewhere...
        if not os.path.isdir(results_folder):
            print("Making results folder", results_folder)
            os.mkdir(results_folder)
        os.chdir(results_folder)
        # record the parameters used for replicability
        # this could be dne better
        if os.path.exists("parameters.txt"): #ughhhhhh, this is awkward. TODO: handle this case better.
            warn("Overwriting old parameters.txt")
        with open("parameters.txt","w") as desc:
            print("ISI scrape\n"
                  "==========\n"
                  "\n"
                  "Query: %s\n"
                  "Records: %d\n"
                  "ISI Session: %s\n"
                  "Date: %s\n" %
                  (strquery, len(Q), S._SID, datetime.datetime.now()), file=desc)
        fname = "%s.ciw" % (S._SID,) #name according to the SID; this should be redundant since we're also making a new folder *but* it will help if files get mixed together.
        print("Ripping results.")
        Q.rip(fname)
    except Exception as exc:
        if args.debug:
            print("------ EXCEPTION ------")
            traceback.print_exc()
            print()
            print("placing exception into 'exc' and dropping to a shell")
            print()
            import IPython; IPython.embed()
        else:
            raise
    else:
        if args.debug:
            print("Finished ripping. You may continue to experiment with the session S and query Q.");
            import IPython; IPython.embed()
