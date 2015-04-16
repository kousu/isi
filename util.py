
import logging

from copy import deepcopy    #for abusively making wrappers


class BlockReinit:
    #def __new__(cls, *args, **kwargs):
    #    pass
    # ?? is there a sensible way to trick wrapper
    def __init__(self, *args, **kwargs):
        logging.debug("blocking reinitialization of super() of %r; extra args: *%s, **%s" % (self, args, kwargs)) #DEBUG
        pass

def wrapper(*cls, clone=True):
    """
    Dynamically mix in classes before a given obj's type.
    
    (actually returns a callable which will do the mixing)
    
    In some cases you cannot or do not want to use
    ```
    class Mixin(): ...
    class Mixed(Mixin, Base): ...
    o = Mixed()
    ```
    mainly when Base is constructed deep in some library routine,
    With wrapper, you can do
    ```
    class Mixin(): ...
    b = lib.blue_submarine.chug()
    O = wrapper(Mixin)(b)
    ```
    You can also do this if you just don't want to for the sake of
    composability: if you have a lot of mixins it's a nuisance to
    prepare an exponential number of combinations:
    class MixedABC(A,B,C,Base): pass
    class MixedAC(A,C,Base): pass
    ...
    
    rather, at the point of need, you can say
    o = wrapper(A,B)(o)
    to prepend classes A and B to o's search path
    
    This has been coded so that Mixin can be used either normally or under wrap()
    However, since the wrapped version does not receive the construction arguments
    (i.e. Base.__init__() doesn't happen a second time and the arguments to the original are lost)
    Mixin needs to tolerate not either receiving or not receiving the init args.
    Use this idiom for greatest compatibility:
    class Mixin(Base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            del args, kwargs #to ensure no code below can rely on these
            # ...
    (if your class has no specific base you can elide that part)
    Luckily, most mixins fit this mold.
    
    To avoid side-effects, a deep copy is made of obj.
    If you want to save the effort, and *you know obj is immutable* or
    *you are replacing the only reference to obj* you can pass clone=False.
    o = wrapper(A,B, clone=False)(o)
    *CAVEAT*: copy() demands obj be pickleable. *In particular*, if an
    ancestor of obj defines __setstate__/__getstate__, but a more child
    ancestor (including self) does not, any child class-specific attributes
    will be mishandled at wrapping time and you will have only confusion bacon.
    """
    
    if not isinstance(clone, bool): raise TypeError("clone should be a bool")
    
    # Implementation:
    #A typical wrapper uses {g,s}etattr() overloading, but why do that
    #when you can just hack up what class the object thinks it is?
    #As far as I can tell, this has the exact same effect:
    #all the methods defined in the wrapper class get added to the object's search path
    
    # this could also be solved as a metaclass problem
    
    def __new__(obj):
        logging.debug("wrapper.__new__(cls=*%s, obj=%s)" % (cls, obj))
        _cls = cls + (BlockReinit, type(obj))
        class W(*_cls): pass
        if clone:
            logging.debug("wrapper.__new__(cls=%s, obj=%s): cloning" % (cls, obj))
            obj = deepcopy(obj)
        obj.__class__ = W
        obj.__init__()
        return obj
    return __new__


def test_wrap():
    class X:
        def __init__(self, *args, **kwargs):
            logging.debug("X.__init__(*%s, **%s)" % (args, kwargs))
            self.args = args
            self.__dict__.update(kwargs)
    
    
    class W(X):
        "test wrap()-able class"
        def __init__(self, *args, **kwargs):
            logging.debug("W.__init__(*%s,**%s)" % (args, kwargs))
            super().__init__(*args, **kwargs); del args, kwargs
            self.antelope = "deer"
    
    def test_wrapped(clone=False):
        logging.debug("---- wrapped test (clone=%s)" % (clone,))
        logging.debug("Constructing original object")
        o = X(6,7,8,happy="sad",pacha="ziggurat",antelope="monkeyman") #mock "library" construction that we "can't" control
        logging.debug(o.__class__)
        assert o.antelope is "monkeyman"
        logging.debug("Wrapping original object (clone=%s)" %(clone,))
        o = wrapper(W, clone=clone)(o)
        assert o.antelope is "deer"
    def test_nonwrapped():
        logging.debug("---- Non-wrapped test")
        logging.debug("Constructing original (and only) object")
        o = W(sandy_hills="in arabia")
        assert o.sandy_hills is "in arabia"
        assert not hasattr(o, 'happy')
        assert o.antelope is "deer"
    
    test_nonwrapped()
    test_wrapped(True)
    test_wrapped(False)


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


if __name__ == '__main__':
    logging.root.setLevel(logging.DEBUG)
    test_wrap()
    print("%s tests passed" %(__file__))
