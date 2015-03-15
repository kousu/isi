#!/usr/bin/env python2

import papers
import os
import csv
import sys

csvHeader = ['Paper ID', 'Date', 'Subjects', 'RP-Author', 'RP-Country', 'Author', 'Author-Country']

outfile = "LocationCounts.csv"

SubjectTag = 'SC'

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
        raise BadPaper(file + " Does not have a valid header")
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
    ls = s[1:].split(']', 1)
    if len(ls) == 0:
        raise IndexError
    authors = ls[0].split('; ')
    institute = ls[1]
    return zip(authors, [institute * len(authors)])

def csvLocCounter(plst, csvf):
    pdict = {}
    for p in plst:
        try:
            if 'UT' in p:
                pdict[csvHeader[0]] = p['UT'][0]
            else:
                print "WOS number error, no field:",
                print '\n'.join(p['TI'])
                raise Warning
            if 'PY' in p:
                pdict[csvHeader[1]] = p['PY'][0]
            else:
                print "Year error, no field:",
                print p['UT'][0]
                print '\n'.join(p['TI'])
                raise Warning
            if 'PD' in p:
                pdict[csvHeader[1]] += ' ' + p['PD'][0][:3]
            
            if SubjectTag in p:
                pdict[csvHeader[2]] = p[SubjectTag][0]
            else:
                print SubjectTag + " error, no year field:",
                print p['UT'][0]
                print '\n'.join(p['TI'])
                raise Warning
            if 'RP' in p:
                rp = p['RP'][0].split(',')
                pdict[csvHeader[3]] = rp[0] + ',' + rp[1][:-17]
                pdict[csvHeader[4]] = rp[-1][1:-1] if rp[-1][-4:-1] != 'USA' else 'USA'
            else:
                print "Reprint address error, no field:",
                print p['UT'][0]
                print '\n'.join(p['TI'])
                raise Warning
            if 'C1' in p:
                if p['C1'][0][0] != '[':
                    for i in range(0, len(p['AF'])):
                        try:
                            pdict[csvHeader[5]] = p['AF'][i]
                        except KeyError as e:
                            print "Authors error no author list:",
                            try:
                                print p['UT'][0]
                                print '\n'.join(p['TI'])
                            except KeyError as e:
                                print "No Title"
                                print p
                        if i >= len(p['C1']):
                            inloc = p['C1'][0]
                        else:
                            inloc = p['C1'][i]
                        pdict[csvHeader[6]] = inloc.split(',')[-1][1:-1] if inloc.split(',')[-1][-4:-1] != 'USA' else 'USA'
                        csvf.writerow(pdict)                    
                else:
                    condict = {}
                    for con in p['C1']:
                        try:
                            condict.update(mapAuthorsInstitute(con))
                        except IndexError as e:
                            print ' '.join(p['TI']),
                            print "Has weird institute list " + con,
                    for auth in p['C1']:
                        pdict[csvHeader[5]] = auth
                        inloc = condict[auth]
                        pdict[csvHeader[6]] = inloc.split(',')[-1][1:-1] if inloc.split(',')[-1][-4:-1] != 'USA' else 'USA'
                        csvf.writerow(pdict)
            else:
                print "Author Address error, no field:",
                print p['UT'][0]
                print '\n'.join(p['TI'])
                raise Warning
        except KeyError as e:
            print "No title"
            print '\n'.join(p['TI'])
        except Warning as w:
            pass

if __name__ == '__main__':
    if os.path.isfile(outfile):
        #Checks if the output csv already exists and terminates if so
        print outfile +  " already exists\nexisting"
        #sys.exit()
        os.remove(outfile)
    flist = sys.argv[1:] if sys.argv[1:] else [f for f in os.listdir(".") if f.endswith(".isi")]
    if len(flist) == 0:
        #checks for any valid files
        print "No isi Files"
        sys.exit()
    else:
        #Tells how many files were found
        print "Found " + str(len(flist)) + " isi files"
    csvOut= csv.DictWriter(open(outfile, 'w'), csvHeader, quotechar='"', quoting=csv.QUOTE_ALL)
    csvOut.writeheader()
    for isi in flist:
            try:
                csvLocCounter(isiParser(isi), csvOut)
            except Exception, e:
                print type(e)
                print e
        
    print "Done"
