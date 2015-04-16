"""
A collection of EzProxy variants.
"""

import requests
from urllib.parse import urlparse, urlunparse
import logging

class LoginError(Exception): pass

class EzProxy(requests.Session):
    """
    rewrite requests to go through an EzProxy installation,
    which is a piece of software commonly used by institutional libraries
    to give single-signon access to paywalled content.
    
    EzProxy is a proxy for HTTP, but it is not an HTTP proxy in the usual transparent sense.
    Instead, EzProxy rewrites URLs and hands out a magical auth cookie ('ezproxy') and then required on every request.
    The rewriting protocol is http://domain/path -> http://domain.ezproxy/path
    (this has the advantage over standard SOCKS and HTTP proxies that users don't need to tweak any settings whatsoever on their side)
    
    Reference: https://www.oclc.org/support/services/ezproxy/documentation.en.html
    """
    address = None
    
    # requests.Session defines __setstate__ and __getstate__
    # this means that on pickle() or copy() the extensions this class adds get lost
    # requests.Session uses its own invented list __attrs__ to track which attrs to use
    # One approach is to extend that set with the local attrs, e.g.
    #  https://github.com/sigmavirus24/requests-toolbelt/pull/61
    # But I am wary of doing the extension like, especially @ util.wrap():
    #  if you mix together two subclasses which both cloned __attrs__,
    #  one set of attrs is going to get lost at copy-time because instead
    #  but the good ol' super() mechanism works just fine!
    #  So even though it's more code, I override and extend __getstate__ and __setstate__
    # Bloo
    # It would be better if requests blacklisted (as in the [example](https://docs.python.org/3.4/library/pickle.html#pickle-state)) instead of whitelisted attributes: 
    # then I could add attrs willy nilly and assume 
    # because really, the set of attrs is the *union* of attrs across all subclasses 
    def __getstate__(self):
        state = super().__getstate__()
        for attr in ["address","_logged_in","_user"]:
            if hasattr(self,attr): state[attr] = getattr(self, attr)
        return state
    def __setstate__(self, state):
        for attr in ["address","_logged_in","_user"]:
            if attr in state:
                setattr(self, attr, state[attr])
                del state[attr]
        return super().__setstate__(state)
    
    
    def __init__(self, address, *args, **kwargs):
        """
        Proxy should be the domain name EzProxy is installed on.
        See the subclasses that come with with this code for some examples.
        """
        super().__init__(*args, **kwargs)
        self.address = address
        self._logged_in = False
        self._user = None
    
    def login(self, barcode, last_name, url=None):
        """
        login to an EzProxy proxy using its default login address and
        its default credentials of a library barcode number + last name
        
        login optionally takes a url= parameter which is meant for
        seamlessly bouncing users back to their target article database
        You almost certainly do not need this, but some URLs get mapped
        via a secret per-institution(?) database to a canonical URL, so
        this parameter is supported just in case.
        # XXX maybe this is feature creep
        
        For sites which do not use the default, anything else listed in, 
        https://www.oclc.org/support/services/ezproxy/documentation/usr.en.html
        (which includes custom CGI scripts, so *anything* is possible)
        override or otherwise don't use this method.
        """
        assert not self._logged_in
        
        # Log in to by POSTing to https://login.{proxy}/login
        
        params = {#credentials
                  # yes, the EzProxy reverses what you'd expect to be
                  # the definition of 'username' and 'password'
                  "user": barcode,
                  "pass": last_name}
                  
        # If you use url, /login sends you to
        # https://login.<proxy>/connect?session=s${SID}N&url=${URL} which,
        # if it recognizes the site, sends you to its canonical URL
        # If you don't use URL (or if it's not recognized??) you are sent to
        # https://login.<proxy>/menu
        if url is not None:
            params['url'] = url
        
        # we super().request() instead of super().post() to avoid
        # recursing badly into self.request() which expects the login up
        # (super().post() helpfully calls self.request(), see, and
        #  normally this is helpful but here it gets in the way)
        r = super().request('POST',
                            self.proxify("https://login/login"), #this funny looking URL will be fixed by proxify() munges it
                            data=params)
        
        r.raise_for_status() #quick way to make sure we have 200 OK
        
        #make sure that the login process appears to have given us the magic ticket
        if "ezproxy" not in self.cookies:
            raise LoginError()
        
        # if everything is peachy, record who's account we're using
        self._logged_in = True
        self._user = last_name
        
        logging.debug("Started new EzProxy session %s" % (self,))
    
    def request(self, verb, url, *args, **kwargs):
        """
        Rewrite all requests going through this session to go through the library proxy.
        """
        if not self._logged_in:
            # it will 302 to the login page if you're not logged in
            # since this would be confusing when scripting (you'd end up with a 200),
            # just disallow it.
            raise RuntimeError("Must be logged in to use the library proxy") 
        
        # TODO: implement backoff on timeouts.
        #   My first guess is that right here is a good place for it,
        #   since I'm 99% sure it's EzProxy that's tracking request rates
        #   so if we accidentally go over their limits, here is where
        #  specifics: quadratic backoff + retry (like TCP)
        #        or : rate limit (perhaps add an instance attribute) so that we, hopefully, never
        #     the latter is probably easier to program with in general, because timeouts would immediately percolate up
        #  --> requests *already does* retrials, but gives up after 3 attempts  
        
        # rewrite the referer to use the proxy too
        # TODO: where else do have leak URLs that might be leaking?
        #       anything in self.headers, for one.. what about other cookies?
        if 'headers' in kwargs:
            if 'Referer' in kwargs['headers']:
                kwargs['headers']['Referer'] = self.proxify(kwargs['headers']['Referer'])
        
        return super().request(verb, self.proxify(url), *args, **kwargs)
        
    def send(self, *args, **kwargs):
        "hook send() purely for tracing"    
        logging.debug("%r.send(*%s, **%s)" % (self, args, kwargs)) 
        return super().send(*args, **kwargs)
    
    def proxify(self, url):
        scheme, host, path, params, query, fragment = urlparse(url)
        #    Response objects returned from this Session should have all references
        #    to the proxy in headers, cookies, and html silently stripped, so that following a link
        #    received from this class with this class doesn't end up going to "http://target.proxy.proxy"
        #  But that problem is unbounded in general. Instead we detect this common case and cancel it
        if not host.endswith(self.address):
            host = host + "." + self.address  #construct the fully
        
        return urlunparse((scheme, host, path, params, query, fragment))
    
    def __str__(self):
        if self.__dict__.get('_logged_in', False):
                return "<%s@%s [session:%s]>" % (self._user, self.address, self.cookies["ezproxy"])
        else:
                return "<EzProxy @%s>" % (self.address,)


class UWProxy(EzProxy):
    def __init__(self, last_name, barcode):
        """
        
        Notice: UW flips the order of user/pass: name is the username and barcode is the pass. By default, EzProxy has them the other way.
        """
        super().__init__("proxy.lib.uwaterloo.ca")
        
        # all connections through this proxy go through a single server
        #*disable* SSL verification because the UW
        #proxy has an out of date cert or something.
        #but only if verify= is not passed
        # TODO: figure out what's going on here; what if I explicitly add UW's cert to the search path (which python-requests lets me do by setting verify to a path instead of a boolean) ?
        # (be mindful: this must happen after super init since super init sets a default value)
        self.verify = False
        
        # automatically login, since why would you create a proxy without logging in?
        # the only reason EzProxy doesn't is because some sites might require complicated auth dances
        # which cannot(?) be done in one step and definitely
        self.login(barcode, last_name)

class GuelphProxy(EzProxy):
    def __init__(self, barcode, last_name):
        super().__init__("subzero.lib.uoguelph.ca")
        self.login(barcode, last_name)

