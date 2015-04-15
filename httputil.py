"""
supporting routines for isi_scrape

"""

import logging

from urllib.parse import urlparse, urlunparse, quote as urlquote, parse_qsl, urljoin

import requests
from requests.exceptions import HTTPError

def qs_parse(s):
    """
    the parse_qs in urllib returns lists of single elements for no obvious reason
    and parse_qsl returns a list of pairs.
    both of these suck.
    """
    return dict(parse_qsl(s))

class AnonymizedSession(requests.Session):
    """
    a requests.Session mixin that tweaks settings to try to anonymize some of our details,
    just because there's no reason not to fly under the radar if we can.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers['User-Agent'] = self.random_UA() #fix the user agent to a random string at boot time

    @staticmethod
    def random_UA():
        """
        
        # TODO: a library that automatically downloads common user agents and picks one
        """
        return "Mozilla/5.0 (X11; Linux x86_64; rv:36.0) Gecko/20100101 Firefox/36.0"
    
    #TODO: other countermeasures
