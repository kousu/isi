
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
            
            
            
def chomp(s):
	"remove trailing newline"
	"assumes universal newlines mode "
	if s.endswith("\n"): s = s[:-1]
	return s
	