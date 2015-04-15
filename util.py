
def query(ask, options=["Y","N"], catch="N"):
    "TODO: document"
    options = list(options)
    assert catch in options, "Catchall case should be in your list of valid options, or else what are you doing with your life?"
    R = input("%s [%s] " % (ask, "/".join(options))).upper()
    if not R: R = options[0]
    if R not in options: R = catch
    return R

def ask(ask): return query(ask) == "Y"

from itertools import chain

def list_ret(g):
    """
    Exhaust a generator to a list, and additionally return its return value which normally you need to catch in an exception handler.
    returns: (list(g), return_value)
    
    As with regular functions, return_value will be None if there isn't one and/or if g isn't actually a generator.
    
    TODO: is this in stdlib somewhere?
    """
    L = []
    while True:
        try:
            L.append(next(g))
        except StopIteration as stop:
            return L, stop.value

from itertools import islice
def window(g, n):
    """
    moving window generator
    example:
     given a sequence g = [1,2,3,4,...] and windowsize n=2, return the sequence [(1,2), (2,3), (3,4), ...]
    """
    g = iter(g)
    W = []
    W.extend(islice(g, n-1))
    for e in g:
        W.append(e)
        yield tuple(W)
        W.pop(0)

def pairs(g):
    return window(g,2)            

def chomp(s):
	"remove trailing newline"
	"assumes universal newlines mode "
	if s.endswith("\n"): s = s[:-1]
	return s



import os
from shutil import rmtree
def rm(path):
    "rm -r"
    if os.path.isdir(path):
        rmtree(path)
    else:
        os.unlink(path)
	
def flatten(L):
    """
    flatten a nested list by one level
    """
    return list(chain.from_iterable(L))


def parse_american_int(c):
    """
    Parse an integer, possibly an American-style comma-separated integer.
    """
    if not isinstance(c, str):
        raise TypeError
    #dirty hack; also what SO decided on: http://stackoverflow.com/questions/2953746/python-parse-comma-separated-number-into-int
    return int(c.replace(",",""))
