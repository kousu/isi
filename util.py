
import logging

from copy import copy    #for abusively making wrappers

def wrap(cls, obj, clone=True):
    """
    Dynamically mix in cls to obj's type
    
    In some cases you cannot use
    class Mixin(): ...
    class Mixed(Mixin, Base): ...
    o = Mixed()
    
    mainly when Base is constructed deep in some library routine.
    In this case, you can do
    class Mixin(): ...
    b = lib.blue_submarine.chug()
    O = wrap(Mixin, b)
    
    The way this works is by tweaking obj's class to be a mixed-in class.
    This is done to a copy to avoid side-effects, unless pass clone=False
    This is only safe to do if you know obj is immutable or you are
    *replacing* the only reference to obj with the wrapper. A caveat is
    that copy() demands obj be pickleable. *In particular*, if a parent
    class of obj defines __setstate__/__getstate__, but a child class
    does not, those child class-specific attribute will be lost.
    """
    
    if not isinstance(clone, bool): raise TypeError("clone")
    
    #A typical wrapper uses {g,s}etattr() overloading,  but why do that when you
    #can just hack up what class the object thinks it is?
    #As far as I can tell, this has the exact same effect:
    #all the methods defined in the wrapper class get added to the object's search path
    
    if clone:
        logging.debug("wrap(%s,%s): making clone" % (cls, obj))
        obj = copy(obj) #make a copy so we are side-effect free
        # XXX should this be 'deepcopy'?
    
    class Wrapped(cls, type(obj)): pass
    obj.__class__ = Wrapped
    return obj


def Wrapped(cls=None, clone=True):
    """
    A decorator which essentially curries cls over wrap()
    
    Suggested use:
    @Wrapped
    class ExtensionLadder(Base): ...
    
    b = lib.blue_submarine.chug()
    b = ExtensionLadder(b)
    
    Via metaprogramming hackery, you can also specify
    
    @Wrapped(clone=False)
    class C: ....
    
    The return is a function, not a class. This is a green curtain you should not look behind. 
    """
    if not isinstance(clone, bool): raise TypeError("clone")
    if cls is None:
        return lambda cls: Wrapped(cls, clone)
    
    return lambda obj: wrap(cls, obj, clone)


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
