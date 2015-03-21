ISI Tools
===========

These are a bunch of tools for dealing with the ISI Web of Science.
You can use them to extract, clean, and process article records in the [ISI Flat File format](TODO).

Some examples of the sorts of work that can be done with this data:
* Kieran Healy: [Gender and Citation](http://kieranhealy.org/blog/archives/2015/02/25/gender-and-citation-in-four-general-interest-philosophy-journals-1993-2013/)
* Neal Caren: [A Sociology Citation Network](http://nealcaren.web.unc.edu/a-sociology-citation-network/)

The tools are very alpha at this stage and have a heavy Unix bias.
Please submit bug reports and feature requests.
I would love to be useful to the wider world.

ISI Scraper
-----------

### Example

```
[kousu@galleon isi]$ ./isi_scrape.py [user name] [library barcode] SU=Sociology PY="2006-2015"
In using this to download records from the Web of Science, you should be aware of the terms of service:

Thomson Reuters determines reasonable  of data to download by comparing your download activity
against the average annual download rates for all Thomson Reuters clients using the product in question.
Thomson Reuters determines insubstantial  of downloaded data to mean an amount of data taken
from the product which (1) would not have significant commercial value of its own; and (2) would not act
as a substitute for access to a Thomson Reuters product for someone who does not have access to the product.

The authors of this software take no responsibility for your use of it. Don't get b&.

Started new UW Library Proxy session 'oUeCh7QJ89pR15H'
Logged into ISI as UW:[user name].
Got 69220 results
Ripping results.
Exporting records [1,501) to 2AiZ7oSbJ2Y7a2MctLA_0001.isi
Exporting records [501,1001) to 2AiZ7oSbJ2Y7a2MctLA_0501.isi
Exporting records [1001,1501) to 2AiZ7oSbJ2Y7a2MctLA_1001.isi
Exporting records [1501,2001) to 2AiZ7oSbJ2Y7a2MctLA_1501.isi
Exporting records [2001,2501) to 2AiZ7oSbJ2Y7a2MctLA_2001.isi
Exporting records [2501,3001) to 2AiZ7oSbJ2Y7a2MctLA_2501.isi
[...]
[kousu@galleon isi]$ ls PY\=2006-2015_SU\=Sociology/
2AiZ7oSbJ2Y7a2MctLA_0001.isi  2AiZ7oSbJ2Y7a2MctLA_1001.isi  2AiZ7oSbJ2Y7a2MctLA_2001.isi  parameters.txt
2AiZ7oSbJ2Y7a2MctLA_0501.isi  2AiZ7oSbJ2Y7a2MctLA_1501.isi  2AiZ7oSbJ2Y7a2MctLA_2501.isi  [...]
[kousu@galleon isi]$ cat PY\=2006-2015_SU\=Sociology/parameters.txt 
ISI scrape
==========

Query: PY=2006-2015 SU=Sociology
Records: 69220
ISI Session: 2AiZ7oSbJ2Y7a2MctLA
Date: 2015-03-12 13:20:38.785762

[kousu@galleon isi]$ 
```


ISI Join
-------

Combine separate .isi files into a single file.
This is needed for processing with [sci^2](https://sci2.cns.iu.edu/user/index.php).

### Example

TODO


ISI Count
----------

Counts the number of records in a set of ISI files.

### Example

TODO
