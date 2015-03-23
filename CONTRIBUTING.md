Guidelines for Contributions
============================

We welcome use cases, questions, and patches!
Please use the github flow: issues, forks and pull requests.


Dev Tips
--------

This code currently is built around scraping the Web of Science database, available at http://isiknowledge.com/wos.
Notice the /wos: without this you are directed to a different sub-database and you will get confused.
If you have access to WOS, you are probably behind a university proxy; if your school is using ezproxy then this URL
for you will be something like http://isiknowledge.com.proxy.lib.your.school.tld/wos


When debugging `export()` and friends, to quickly get record counts by document type, try this:
```
$ egrep ^PT *.ciw | sort | uniq -c
```

License
-------

By submitting a pull request you agree that you are releasing your contibution under the terms of the [license](LICENSE).
