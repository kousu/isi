#!/usr/bin/env python2
#Written by Reid McIlroy-Young


import papers
import os
import csv
import sys
import IPython

csvHeader = ['Paper ID', 'Date', 'Subjects', 'RP-Author', 'RP-Country', 'Author', 'Author-Country']

outfile = "LocationCounts.csv"

SubjectTag = 'SC'

ErrorPrinting = True
WarningPrinting = False

FileSuffix = '.isi'

class BadPaper(Warning):
    pass

def paperParser(paper):
    """
    paperParser reads paper until it reaches 'EF' for each field tag it adds an
    entry to the returned dict with the tag as the key and a list of the entries
    for the tag as the value, the list has each line as an entry.   
    """
    tdict = {}
    currentTag = ''
    for l in paper:
        if 'ER' in l[:2]:
            return tdict
        elif '   ' in l[:3]: #the string is three spaces in row
            tdict[currentTag].append(l[3:-1])
        elif l[2] == ' ':
            currentTag = l[:2]
            tdict[currentTag] = [l[3:-1]]
        else:
            raise BadPaper("Field tag not formed correctly: " + l)
    raise BadPaper("End of file reached before EF")

def isiParser(isifile):
    """
    isiParser reads a file, checks that the header is correct then reads each
    paper returning a list of of dicts keyed with the field tags.
    """
    f = open(isifile, 'r')
    if "VR 1.0" not in f.readline() and "VR 1.0" not in f.readline():
        raise BadPaper(isifile + " Does not have a valid header")
    notEnd = True
    plst = []
    while notEnd:
        l = f.next()
        if not l:
            raise BadPaper("No ER found in " + isifile)
        elif l.isspace():
            continue
        elif 'EF' in l[:2]:
            notEnd = False
            continue
        else:
            try:
                if l[:2] != 'PT':
                    raise BadPaper("Paper does not start with PT tag")
                plst.append(paperParser(f))
                plst[-1][l[:2]] = l[3:-1]
            except Warning as w:
                raise BadPaper(str(w.message) + "In " + isifile)
            except Exception as e:
                 raise e
    try:
        f.next()
        print "EF not at end of " + isifile
    except StopIteration as e:
        pass
    finally:
        return plst

def mapAuthorsInstitute(s):
    """
    mapAuthorsInstitute takes in a author location string and returns a dict of
    the authors and their locations. The location will be the same for all.
    """
    ls = s[1:].split(']', 1)
    if len(ls) == 0:
        raise IndexError
    authors = ls[0].split('; ')
    institute = ls[1]
    return zip(authors, [institute * len(authors)])

def americaIsSpecial(s):
    """
    USA country format is unique this deals with it
    """
    if s[-4:-1] == 'USA':
        return 'USA'
    else:
        return s[1:-1]

def csvLocCounter(plst, csvf):
    """
    csvLocCounter takes in a parsed paper list and a csv file to write, for each 
    author in each paper it writes a row in the csv file.
    The row contains the stuff in csvHeader.
    Most of the function deals with isi's inconsistencies, as such the validity
    of locations in particular is less than ideal
    csvLocCounter returns the number of imperfect records it found and could not
    deal with.
    """
    pdict = {}
    ec = 0
    for p in plst:
        try:
            if 'UT' in p:
                pdict[csvHeader[0]] = p['UT'][0]
            else:
                if ErrorPrinting:
                    print "WOS number error, no field:",
                raise Warning
            if 'PY' in p:
                pdict[csvHeader[1]] = p['PY'][0]
            else:
                if ErrorPrinting:
                    print "Year error, no field:",
                    print p['UT'][0]
                raise Warning
            if 'PD' in p:
                pdict[csvHeader[1]] += ' ' + p['PD'][0][:3]
            if SubjectTag in p:
                pdict[csvHeader[2]] = p[SubjectTag][0]
            else:
                if ErrorPrinting:
                    print SubjectTag + " error, no year field:",
                    print p['UT'][0]
                raise Warning
            if 'RP' in p:
                rp = p['RP'][0].split(',')
                pdict[csvHeader[3]] = rp[0] + ',' + rp[1][:-17]
                pdict[csvHeader[4]] = americaIsSpecial(rp[-1])
            else:
                if 'AF' and 'C1' in p:
                    pdict[csvHeader[3]] = p['AF'][0]
                    pdict[csvHeader[4]] = americaIsSpecial(p['C1'][0].split(', ')[-1])
                else:
                    if ErrorPrinting:
                        print "No Locations found in:",
                        print p['UT'][0]
                    raise Warning
            if 'AF' in p:
                if 'C1' in p:
                    if p['C1'][0][0] != '[':
                        for i in range(0, len(p['AF'])):
                            try:
                                pdict[csvHeader[5]] = p['AF'][i]
                            except KeyError as e:
                                if ErrorPrinting:
                                    print "Authors error no author list:",
                                    print p['UT'][0]
                            if i >= len(p['C1']):
                                inloc = p['C1'][0]
                            else:
                                inloc = p['C1'][i]
                            pdict[csvHeader[6]] = americaIsSpecial(inloc.split(', ')[-1])
                            csvf.writerow(pdict)                    
                    else:
                        condict = {}
                        for con in p['C1']:
                            try:
                                condict.update(mapAuthorsInstitute(con))
                            except IndexError as e:
                                if WarningPrinting:
                                  print "Institute list wonky potential error in:",
                                  print p['UT'][0]
                        for auth in p['AF']:
                            pdict[csvHeader[5]] = auth
                            if auth in condict:
                                inloc = condict[auth]
                            else:
                                inloc = p['C1'][0]
                            pdict[csvHeader[6]] = americaIsSpecial(inloc.split(',')[-1])
                            csvf.writerow(pdict)
                else:
                    if ErrorPrinting:
                        print "Author Address error, no field:",
                        print p['UT'][0]
                    raise Warning
            else:
                if ErrorPrinting:
                    print "Author names error, no field:",
                    print p['UT'][0]
                raise Warning
        except Warning as w:
            ec +=1
    return ec

if __name__ == '__main__':
    if os.path.isfile(outfile):
        #Checks if the output outfile already exists and terminates if so
        print outfile +  " already exists\nexisting"
        sys.exit()
        #os.remove(outfile)
    flist = sys.argv[1:] if sys.argv[1:] else [f for f in os.listdir(".") if f.endswith(FileSuffix)]
    if len(flist) == 0:
        #checks for any valid files
        print "No " + FileSuffix + " Files"
        sys.exit()
    else:
        #Tells how many files were found
        print "Found " + str(len(flist)) + FileSuffix + "  files"
    csvOut= csv.DictWriter(open(outfile, 'w'), csvHeader, quotechar='"', quoting=csv.QUOTE_ALL)
    csvOut.writeheader()
    errorsFound = []
    for isi in flist:
            try:
                if ErrorPrinting:
                    print "Reading " + isi
                errorsFound.append((csvLocCounter(isiParser(isi), csvOut), isi))
            except BadPaper as b:
                print b
            except Exception, e:
                print type(e)
                print e
    tot = 0
    for er in errorsFound:
        print str(er[0]) + " errors found in " + er[1]
        tot += er[0]
    print str(tot) + " total errors found"
    if not ErrorPrinting:
        print "turn on ErrorPrinting to see more information"
    print "Done"