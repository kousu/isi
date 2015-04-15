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
    
    def login(self, barcode, last_name):
        # TODO there's apparently a slew of auth methods for ezproxy: https://www.oclc.org/support/services/ezproxy/documentation/usr.en.html
        #      it is not clear if these are backend-only things and "http://login.<ezproxy>/login" is a standard frontend
        #       or if I need to write loginLDAP(), loginCAS(), ....
        #      maybe /login is the default that comes with EzProxy; in that case, when someone wants to extend this for their library, I will gladly accept pull requests
        assert not self._logged_in
        
        try:
            self._logged_in = "logging_in" #workaround the assert in request(). I want to keep that assert for the common case, but it breaks this initial step.
            
            # Log in to by going to https://login.{proxy}/login
            r = self.post("https://login/login", #this crippled URL is because this call itself gets routed through the proxy hackery in self.request()
                data={  #"url": "http://4chan.org",
                        #/login optionally takes a url= parameter to redirect you to a target page (meant to be used to seamlessly send users back)
                        # It actually sends you to https://login.<proxy>/connect?session=s${SID}N&url=${URL} which, if it recognizes the site, sends you to its canonical URL
                        # (and otherwise(???) you get sent to https://login.<proxy>/menu)
                      
                      # credentials
                      #yes, the EzProxy reverses what you'd expect to be the definition of 'username' and 'password'
                      "user": barcode,
                      "pass": last_name})
            
            r.raise_for_status() #quick way to make sure we have 200 OK
            
            #make sure that the login process appears to have given us the magic ticket
            if "ezproxy" not in self.cookies:
                raise LoginError()
            
        except:
            self._logged_in = False # roll back the login state
            raise
            
        # if everything is peachy, record who's account we're using
        self._logged_in = True
        self._user = last_name
        logging.debug("Started new EzProxy session %s" % (self,))
    
    def request(self, verb, url, *args, **kwargs):
        """
        Rewrite all requests going through this session to go through the library proxy.
        """
        
        assert self._logged_in == "logging_in" or self._logged_in, "Must be logged in to use the library proxy" #it will 302 to the login page if you're not; since this would be confusing when scripting, just disallow it.               
        
        # rewrite the referer to use the proxy too
        # TODO: where else do we leak URLs?
        #       anything in self.headers, for one
        if 'headers' in kwargs:
            if 'Referer' in kwargs['headers']:
                kwargs['headers']['Referer'] = self.proxyify(kwargs['headers']['Referer'])
        
        logging.debug("Session.request(%s, %s, *%s, **%s)" % (verb, self.proxyify(url), args, kwargs))
        return super().request(verb, self.proxyify(url), *args, **kwargs)
        
    def proxyify(self, url):
        scheme, host, path, params, query, fragment = urlparse(url)
        #    Response objects returned from this Session should have all references
        #    to the proxy in headers, cookies, and html silently stripped, so that following a link
        #    received from this class with this class doesn't end up going to "http://target.proxy.proxy"
        #  But that problem is unbounded in general. Instead we detect this common case and cancel it
        if not host.endswith(self.address):
            host = host + "." + self.address  #construct the fully
        
        return urlunparse((scheme, host, path, params, query, fragment))
    
    def __str__(self):
        if self._logged_in == True:
                return "<%s@%s [session:%s]>" % (self._user, self.address, self.cookies["ezproxy"])
        else:
                return "<EzProxy @%s>" % (self.address,)


class UWProxy(EzProxy):
    def __init__(self, last_name, barcode):
        """
        
        Notice: UW flips the order of user/pass: name is the username and barcode is the pass. By default, EzProxy has them the other way.
        """
        super().__init__("proxy.lib.uwaterloo.ca")
        self.login(barcode, last_name)
        
    def request(self, *args, **kwargs):
        """
        override request() to *disable* SSL verification because the UW
        proxy has an out of date cert or something.
        but only if verify= is not passed
         
        # TODO: figure out what's going on here; what if I explicitly add UW's cert to the search path (which python-requests lets me do by setting verify to a path instead of a boolean) ?
        """
        if 'verify' not in kwargs:
            kwargs['verify'] = False
        return super().request(*args, **kwargs) 

class GuelphProxy(EzProxy):
    def __init__(self, barcode, last_name):
        super().__init__("subzero.lib.uoguelph.ca")
        self.login(barcode, last_name)

