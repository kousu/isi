#!/usr/bin/env python3


import sys, os
#import argparse, optparse, ...


import locale
from itertools import count

from urllib.parse import urlparse, urlunparse, quote as urlquote, parse_qsl
import traceback
import requests
from requests.exceptions import HTTPError
from bs4 import BeautifulSoup

from warnings import warn



#------------ utils


def list_ret(g):
    """
    flatten a generator to a list, and additionally return its return value (which will be None if there isn't one and/or if g isn't actually a generator)
    returns: (list(g), return_value)
    
    TODO: is this in stdlib somewhere?
    """
    L = []
    while True:
        try:
            L.append(next(g))
        except StopIteration as stop:
            return L, stop.value

def qs_parse(s):
    """
    the parse_qs in urllib returns lists of single elements for no obvious reason
    and parse_qsl returns a list of pairs.
    both of these suck.
    """
    return dict(parse_qsl(s))
    



#--------------- ripper
class UWProxy(requests.Session):
    """
    rewrite requests to go through the UW library
    TODO: is there a better way to write this? as a python-requests plugin of some sort?
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logged_in = False
        self._user = None
    
    def login(self, last_name, card_barcode):
        """
        Login to the UW library proxy. That is, do this page (which you are probably familiar with): https://login.proxy.lib.uwaterloo.ca/login.
        last_name: your "username". Note that the UW library does *not* use your Quest ID.
        card_barcode: your "password" -- the 14 digit barcode number; not your student ID.
        """
        
        
        try:
            self._logged_in = "logging_in" #workaround the assert in request(). I want to keep that assert for the common case, but it breaks this initial step.
            r = super().post("http://login/login", #this funny URL is because this call itself gets routed through the proxy hackery in self.request()
                data={#"url": "h,
                      #"url": "http://4chan.org",
                        #the proxy optionally will redirect you to
                        # https://login.proxy.lib.uwaterloo.ca/connect?session=s${SID}N&url=${URL} which, if it recognizes the site,
                        # will redirect you to
                        #  http://${HOST}.proxy.lib.uwaterloo.ca/${PATH} ((where ${URL} = http(s)://$HOST/$PATH))
                        # and if it doesn't will just send you to
                        #  $URL
                        #
                        # However, the library proxy doesn't care where you ask to go---you can even go off to 4chan---and it will happily hand out session cookies
                        # So this isn't actually necessary for the sake of the scraper.
                        # (if not given, you get sent to https://login.proxy.lib.uwaterloo.ca/menu)
                      
                      # credentials
                      #yes, the UW proxy reverses the definition of 'username' and 'password':
                      "pass": last_name,
                      "user": card_barcode})
            
            r.raise_for_status() #dirty way to make sure we have 200 OK
            SID = S.cookies["ezproxy"] #make sure that the login process appears to have given us the magic ticket
            
            print("Started new UW Library Proxy session '%s'" % (SID,), file=sys.stderr)
            #import IPython; IPython.embed() #DEBUG
            #print("Library proxy sent us on this goose chase:\n",
            #      "\n->\t".join([p.url for p in r.history] + [r.url]),
            #      file=sys.stderr) #DEBUG
        except Exception as exc:
            # TODO: better exception
            raise Exception("Failed logging in to library proxy", exc)
        
        # if everything is peachy, record who's account we're using
        self._logged_in = True
        self._user = last_name
    
    def request(self, verb, url, *args, **kwargs):
        """
        Rewrite all requests going through this session to go through the library proxy.
        """
        assert self._logged_in == "logging_in" or self._logged_in, "Must be logged in to use the library proxy" #it will 302 to the login page if you're not; since this would be confusing when scripting, just disallow it.
        
        def proxyify(url):
            scheme, host, path, params, query, fragment = urlparse(url)
            proxy_host = host + ".proxy.lib.uwaterloo.ca"
            return urlunparse((scheme, proxy_host, path, params, query, fragment))
        
        proxy_url = proxyify(url)
        
        # rewrite the referer to use the proxy too
        # TODO: where else do we leak URLs?
        if 'headers' in kwargs:
            if 'Referer' in kwargs['headers']:
                kwargs['headers']['Referer'] = proxyify(kwargs['headers']['Referer'])
        
        #*disable* SSL checking because the libary proxy has an out of date cert or something. ugh.
        # TODO: figure out what's going on here; what if I explicitly add UW's cert to the search path (which python-requests lets me do by setting verify to a path instead of a boolean)
        if 'verify' not in kwargs:
            kwargs['verify'] = False 
        return super().request(verb, proxy_url, *args, **kwargs)
        

class ISISession(requests.Session):
    """
    A requests.Session that hardcodes the magic URLs needed to access http://apps.webofknowledge.com/
    """
    
    # TODO: rearchitect stuff so that passwords are passed at __init__
    
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
        return super().request(*args, **kwargs)
    
    def generalSearch(self, *fields, startYear=1900, endYear=2015, editions=["SCI", "SSCI", "AHCI", "ISTP", "ISSHP"], sort='LC.D;PY.A;LD.D;SO.A;VL.D;PG.A;AU.A'):
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
                    UT= Accession Number
                    PMID= PubMed ID 
                You can reuse fields, though it's easy to end up with empty resultsets if you do this.
                Reference: http://apps.webofknowledge.com/WOS_AdvancedSearch_input.do
              - querystring is fed directly into ISI unchecked. You generally can use globbing here (*, $ ?, ...)
                You can also (apparently) embed operator strings here.
                Reference: http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_search_rules.html
            - operator strings: AND, OR, NOT, NEAR, SAME; also fed into ISI unchecked.
                Reference: http://images.webofknowledge.com/WOKRS5161B5_fast5k/help/WOS/hs_search_operators.html
            The length of fields should be an odd number because there should be exactly one less operator than query pairs.
            It also, apparently, should not contain more than 49 fields.
            This is an awkward format; you're just going to have to DEAL WITH IT. It's better than trying to parse a string before feeding it.
        startYear, endYear: the range of years to search.
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
        
        max_field_count = 25
        
        # There are a lot of things that get posted to this form, even though it's just the simple search.
        # most of these were copied raw from a working query
        # most of them are ridiculously unusable and redundant and possibly ignored on the backend
        # but WHEN IN ROME...
        # 
        # For readability, I split up the construction of the POST data into sections.
        
        # this is header stuff needed to convince the search engine to listen to us
        form_target = {
                    'product': 'WOS', # 'UA' == "all databases", "..." == korean thing, "..." = MedLine, ...; we want WOS because WOS can give us bibliographies, not just papers.
                    'action': 'search', 
                    'search_mode': 'GeneralSearch',
                    'SID': self._SID, 
        }
        form_target = list(form_target.items())
        
        # this is crap ISI probably ignores
        form_cruft = {
                    'max_field_count': str(max_field_count), #uhhhh, and what happens if I ignore this? omg, I bet ISI is full of SQL injections. :(
                    # (the browser is sending hardcoded error messages as options in its *query*??)
                    'input_invalid_notice': 'Search Error: Please enter a search term.',
                    'exp_notice': 'Search Error: Patent search term could be found in more than one family (unique patent number required for Expand option) ',
                    'max_field_notice': 'Notice: You cannot add another field.', 
                    'input_invalid_notice_limits': ' <br/>Note: Fields displayed in scrolling boxes must be combined with at least one other search field.',
                    # LOL what are these for?? "Yes, I Love Descartes Too"
                    'x': '0', 'y': '0',
                    # whyyyyyy
                    'ss_query_language': 'auto', 'ss_showsuggestions': 'ON', 'ss_numDefaultGeneralSearchFields': '1',
                    'ss_lemmatization': 'On', 'period': 'Range Selection', 'limitStatus': 'collapsed', 'update_back2search_link_param': 'yes',
                    #'sa_params': "UA||4ATCGy9dQvV3rtykDa3|http://apps.webofknowledge.com.proxy.lib.uwaterloo.ca|'", #<-- TODO: this seems to repeat things passed elsewhere: product, SID, and URL. The first two I can get, but the URL is tricky because I've abstracted out from coding against the UW proxy directly
                        # but I suspect the system won't notice if it's missing...
                    'ss_spellchecking': 'Suggest', 'ssStatus': 'display:none',
                    'formUpdated': 'true',
                    }
        form_cruft = list(form_cruft.items())
        
        # This is the actual fields
        # This part is rather complicated. This ISI's fault.
        def fields2isi():
            """
            this generator walks the input and reformats it into key-value pairs 
            returns the number of fields searched (which you need to retrieve from the StopIteration)
            Note: the number of times this yields is larger than the number of fields actually represented, because of ISI cruft, so you can't simply len() the result.
            """
            
            for i in range(0, len(fields), 2):
                t = i+1 #terms are indexed from 1
                
                # the field term
                (field, querystring) = fields[i]
                
                yield ("value(select%d)" % t, field)
                yield ("value(input%d)" % t, querystring) 
                yield ("value(hidInput%d)" % t, "") #the fantastic spaztastic no-op hidden input field
                
                # the operand term
                if fields[i+1:]:
                    op = fields[i+1]
                    assert op in ["AND","OR","NOT","SAME","NEAR"], "ISI only knows these operators"
                    
                else:
                    # last field; don't include the operand term
                    assert len(fields)-1 == i, "Double checking I got the if right"
            
            return t #the number of fields processed
        
        form_query, fieldCount = list_ret(fields2isi())
        if fieldCount > max_field_count:
            warn("Submitting %d > %d fields to ISI. ISI might balk." % (fieldCount, max_field_count))
        form_query += list(({
                    'fieldCount': str(fieldCount),
                    'startYear': str(startYear), 'endYear': str(endYear), 
                    'rs_sort_by': sort,
                    'range': 'ALL', #????,
                    }).items())
        form_query += [("editions", e) for e in editions] #this reuses the parameter name to pass an array (in contrast to the array of search terms which are passed by a list of differently named params). SWEET.
        
        # merge all the sections
        # note: we have to use lists of key-value pairs and not dicts because ISI repeats some parameter names
        form = form_target + form_cruft + form_query
        
        print("SUBMITTING THIS SHIT")
        print(form)
        import IPython; IPython.embed() #DEBUG
        
        # Do the query
        # this causes ISI to create and cache a resultset
        r = self.post("http://apps.webofknowledge.com/WOS_GeneralSearch.do",
                headers={'Referer': "http://apps.webofknowledge.com/WOS_GeneralSearch.do?product=WOS&SID=%s&search_mode=GeneralSearch" % self._SID}, #TODO: base this URL on the data above
                data=form)
        r.raise_for_status()
        soup = BeautifulSoup(r.content)
        
        # DEBUG
        #with open("what.html","w") as what:
        #    what.write(soup.prettify())
        
        #print("performed a query; dropping to shell; query result is in r and soup")
        #import IPython; IPython.embed()
        
        qid = soup.find("input", {"name": "qid"})['value']
        #count = soup.find(id="hitCount.top").text #this is no good because the count (and most of the rest of the page) are actually loaded *by awful javascript*
        #count = 10*int(soup.find(id="pageCount.top").text) #here's another idea
        count = soup.find(id="footer_formatted_count").text
        estimated = "approximately" in count.lower()
        count = count.split()[-1] #chomp the 'approximately', if it exists
        #locale.setlocale( locale.LC_ALL, 'en_US.UTF-8' )
        #count = locale.atoi(count) #this should but doesn't work because it assumes *my* locale
        count = int(count.replace(",","")) #dirty hack; also what SO decided on: http://stackoverflow.com/questions/2953746/python-parse-comma-separated-number-into-int
        
        
        # warn if we don't have access to citation records
        # As far as I can tell, the only way to find this out is by looking for if the output form gives the option.
        # You can also just try downloading with citation records and looking if it actually gives them to you or not, but that's sketchier
        soup = BeautifulSoup(r.content)
        soup = BeautifulSoup(soup.find(id="qoContentTemplate").text) # the div that contains the output form is not in the HTML: it's in a script tag of type "text/template". so BeautifulSoup misses it.
        soup = soup.find("select", id="bib_fields")
        bib_field_options = soup("option")
        if len(bib_field_options)!=4:
            warn("We appear to not have access to ISI's We cannot export citation records.")
            warn("We have %d options: %s" % (len(bib_field_options), "; ".join(e.text.strip() for e in bib_field_options),))
        
        return ISIQuery(self, qid, count, estimated)
        
    def advancedSearch(self, query):
        """
        query should be a string in the form
        #TODO: other options that advanced search allows, like "articles only"
        """
        raise NotImplementedError
    
    def search(self, topic):
        """
        perform a simple of the Web of Science
        """
        return self.generalSearch(('TS', topic))
    
    #def __str__(self):
    #    return "<%s: %s " % (type(self),) #???




class AnonymizedUAMixin(requests.Session):
    """
    a requests.Session that tweaks settings to try to anonymize some of our details,
    just because there's no reason not to fly under the radar if we can.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers['User-Agent'] = self.random_UA()

    @staticmethod
    def random_UA():
        """
        
        # TODO: a library that automatically downloads common user agents and picks one
        """
        return "Mozilla/5.0 (X11; Linux x86_64; rv:36.0) Gecko/20100101 Firefox/36.0"
    

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
    def __init__(self, session, qid, N=None, estimated=None):
        """
        N is the number of results in the query set, if known.
        """
        self._session = session
        self.SID = session._SID
        self.qid = qid
        self._len = N
        self.estimated = estimated
    
    def __len__(self):
        return self._len
    
    def export(self, start, end, format="fieldtagged"):
        """
        Request records export via the "Save to Other File Formats" dialog.
        Export records for the current query startinf running start through end-1.
        
        format:
         - fieldtagged or othersoftware -- ISI Flat File format
         - {win,mac}Tab{Unicode,UTF8}   -- variants of TSV
         - bibtex                       -- for LaTeX junkies
         - html                         -- if you hate yourself
        
        Returns the HTTP response from ISI's OutboundService.do, because I don't want to corner your choices.
        """
        assert start >= 0 and end >= 0
        assert start < end
        assert end - start <= 500, "ISI disallows more than 500 records at a time"
        
        r =self._session.post("http://apps.webofknowledge.com/OutboundService.do?action=go",
                           #headers={...},
                           data={
                            'IncitesEntitled': 'no',
                            'count_new_items_marked': '0',
                            'displayCitedRefs': 'true',
                            'displayTimesCited': 'true',
                            # export ALL THE THINGS
                            # TODO: make configurable
                            'fields_selection': 'PMID USAGEIND AUTHORSIDENTIFIERS ACCESSION_NUM FUNDING SUBJECT_CATEGORY JCR_CATEGORY LANG IDS PAGEC SABBR CITREFC ISSN PUBINFO KEYWORDS CITTIMES ADDRS CONFERENCE_SPONSORS DOCTYPE CITREF ABSTRACT CONFERENCE_INFO SOURCE TITLE AUTHORS  ',
                            'filters': 'PMID USAGEIND AUTHORSIDENTIFIERS ACCESSION_NUM FUNDING SUBJECT_CATEGORY JCR_CATEGORY LANG IDS PAGEC SABBR CITREFC ISSN PUBINFO KEYWORDS CITTIMES ADDRS CONFERENCE_SPONSORS DOCTYPE CITREF ABSTRACT CONFERENCE_INFO SOURCE TITLE AUTHORS  ',
                            
                            'format': 'saveToFile', # this is called 'format' but it's not actually the format. I guess this is like, the format of the request or something.
                            'mode': 'OpenOutputService', # I bet WOS is programmed in Java.
                            'save_options': format,
                            
                            # TODO: make configurable
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
                            'qid': self.qid,
                            
                            # this too?
                            # guess not
                            #'queryNatural': '(CU=Tunisia and TS=medicine) <i> AND </i><b>DOCUMENT TYPES:</b> (Article)',
                            #'rurl': 'http%3A%2F%2Fapps.webofknowledge.com%2Fsummary.do%3FSID%3D4FhguMhJ6eAMjJarZfa%26product%3DWOS%26doc%3D1%26qid%3D10%26search_mode%3DAdvancedSearch',
                            
                            # uhhh
                            #'search_mode': 'AdvancedSearch',
                            'sortBy': 'PY.A;LD.D;SO.A;VL.D;PG.A;AU.A',
                            'value(record_select_type)': 'range',
                            'viewType': 'summary',
                            'view_name': 'WOS-summary'
                           })
        
        r.raise_for_status()
        #print("performed an export; dropping to shell; query result is in r")
        #import IPython; IPython.embed()
        # translate WOS's happy-go-lucky 302 to a 200 OK with a small little error message into an actual exception
        if "error_display_redirect" in qs_parse(urlparse(r.url).query):
            raise HTTPError("404: invalid export range requested (i guess)")
        return r
    
    def rip(self, fname, upper_limit=20000):
        """
        Export all records available in this query.
        
        fname: file name. used as a template: if fname == "fname.ext" then records will be exported to ["fname_0001.ext", "fname_0501.ext", ...] 
        upper_limit: the largest record index to export; use this to make an easy guarantee that you won't get stomped by ISI for chewing through their data.
        # TODO:
          add random jitter between requests so we don't look so botty
        """
        base_name, ext = os.path.splitext(fname)
        for k in count(): #TODO: use range() here to somehow get the upper and low bounds simultanouesly
            block = 500*k + 1 #+1 because ISI starts counting at 1, of course
            if upper_limit and block > upper_limit: break
            fname = "%s_%04d%s" % (base_name, block, ext)
            try:
                r = self.export(block, block+500)
                print("Exporting %s's records [%d,%d) to %s" % (self, block, block+500, fname), file=sys.stderr)
                with open(fname,"w") as w:
                    w.write(r.text) #assuming ISI returns plain text to us. which it should. because we're telling it to.
            except HTTPError:
                break

def tos_warning():
    print("In using this to download records from the Web of Science, you should aware of the terms of service:")
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

if __name__ == '__main__':
    import argparse
    
    # TODO: pass barcode via stdin to hide it from ps auxww
    # TODO: support non-UW logins
    
    ap = argparse.ArgumentParser(description="Export paper associated metadata from the Web of Science. Currently only works for University of Waterloo members.")
    ap.add_argument('user', type=str, help="Your last name, as you use to log in to the UW library proxy")
    ap.add_argument('barcode', type=str, help="Your 14 digit library card barcode number (not your student ID!)")
    # TODO: support more than just 'topic'
    # TODO: support year filtering, item type filtering, the sort order (which matters since we're not going to get everything)
    ap.add_argument('topic', type=str, help="The topic to query for (TODO: extend this)")
    
    args = ap.parse_args()
    #print(args) #DEBUG
    
    tos_warning()
    
    try:
        S = AnonymizedUWISISession()
        S.login(args.user, args.barcode) #TODO take from command line
        print("Logged into ISI as UW:%s." % (args.user,))
        print("Querying ISI for 'TS=%s'" % (args.topic,))
        Q = S.search(args.topic)
        print("Got %s%d results" % ("an estimated " if Q.estimated else "", len(Q)))
        print("Ripping resultset", Q)
        Q.rip("%s.isi" % (args.topic)) #just save to topic.isi; TODO: when we get more search options we'll need to rework this.
    except Exception as exc:
        print("------ EXCEPTION ------")
        traceback.print_exc()
        print()
        print("placing exception into 'exc' and dropping to a shell")
        print()
        import IPython; IPython.embed()
    else:
        print("Finished ripping. You may continue to experiment with the session S and query Q.");
        import IPython; IPython.embed()