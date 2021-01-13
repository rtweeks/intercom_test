==============================
``icy-test`` Command Line Tool
==============================

Not every test harness is written in Python.  To accommodate this, the
:doc:`intercom_test package </index>` can be installed to provide a command
line tool call ``icy-test`` that provides access to the core functionality.


Installation
------------

To install the ``icy-test`` command line tool, simply install 
:doc:`intercom_test package </index>` with the `[cli]` *extra*, e.g.::

  pip install intercom_test[cli]

This creates a command line tool named ``icy-test``, which can be run with the
``--help`` flag to get usage information.  This information will be the most
recent and detailed available.


Configuration File
------------------

``icy-test`` needs a configuration file to provide information that would,
in a typical Python testing setting, be provided as parameters to the
:py:class:`~intercom_test.framework.InterfaceCaseProvider` constructor.
The path to this file is specified with the ``-c`` or ``--config`` flag when
running ``icy-test``.

A text-mode helper for building a configuration file (which is a YAML file,
usually with a ``.yml`` extension) is provided as ``icy-test init``, and requires
specifying a config file using one of the options mentioned above.


Consuming Test Cases
--------------------

The main use of ``icy-test`` is to access the test cases.  These are available
in the output of ``icy-test enumerate`` in either a stream of YAML documents
(one per test case) or as `JSON Lines`_ (each line contains a JSON document).


Committing Augmentation Data Updates
------------------------------------

Where :py:class:`~intercom_test.framework.InterfaceCaseProvider` used within a
Python testing framework can provide *case runners* that can automatically
update the compact augmentation data files when all test cases have passed,
no such facility is easily implemented when consuming the test cases from
another process and/or language.  The augmentation data changes embodied in the
*update files* need to be explicitly committed to the *compact files* by running
``icy-test commitupdates``.


Merging Interface Extension Test Cases To Main File
---------------------------------------------------

Use the ``icy-test mergecases`` subcommand to invoke
:py:meth:`intercom_test.framework.InterfaceCaseProvider.merge_test_extensions`
with appropriate setup taken from the ``icy-test`` configuration file.


Access HTTP JSON Exchange Stubs Outside Python
----------------------------------------------

Because solutions involving exchanges of JSON documents over HTTP are becoming
very popular, ``icy-test`` provides a subcommand to offload the logic of
matching the elements of the HTTP request (method, URL (path and query string),
and sometimes request body) with a test case.  Moreover,
``icy-test hjx-stubber`` will, when given a request that *doesn't* exist in the
test case set, respond with information on how the request can be changed to
one that is in the test case set.

If changing the method, URL, and request body do not provide enough dimensions
of control to adequately represent the gamut of request/response pairs for
the represented service, ``icy-test hjx-stubber`` does reference the
``request keys`` configuration file entry, which can be used to add fields to
the "test case key."  An example would be listing ``story`` as a request key,
then populating test cases that share the same method, URL, and request body
with individual values for the the ``story`` field.  To fully implement this,
the interface-consuming project has to be willing to inject a ``story`` field
into the request line passed to ``icy-test hjx-stubber`` during testing.

``icy-test hjx-stubber`` accepts a request formatted as a JSON object on a
single line (i.e. `JSON Lines`_), where at least ``method`` and ``url``
properties are present.  It will respond with a similar `JSON Lines`_ object
which is either the full, matching test case (plus a ``response status`` field
if one was not specified in the data files) or a set of diffs for the closest
test cases ``icy-test hjx-stubber`` could find in the whole case set.  See
``icy-test hjx-stubber --help`` for more information.

Starting up ``icy-test hjx-stubber`` is somewhat expensive for large sets of
test cases, so it is best to start it when spinning up the test environment for
a run of tests, then shut it down when testing finishes.  Closing standard
input is enough to get the program to exit.


.. _JSON Lines: http://jsonlines.org
