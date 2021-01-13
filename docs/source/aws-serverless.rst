==================================================
Support for Testing Serverless API Services on AWS
==================================================

Many API services are currently hosted on AWS, and `Serverless`_ is one common
Infrastructure-as-Code (IaC) system for organizing the bevy of resources
necessary for a "serverless" service.  Custom code for handling API requests in
a Serverless application is integrated through Lambda Functions, which have a
simple call interface in several languages.  Where the language chosen is
Python, using the :doc:`intercom_test package </index>` allows development of
the interface test cases in familiar HTTP terms but, through
:py:class:`~intercom_test.aws_http.ServerlessHandlerMapper`, allows the Lambda
handler functions to be tested.

Extended Example
----------------

.. figure:: example_project_structure.png
   :width: 9cm
   
   Example directory tree for using :py:mod:`intercom_test`

Building on the :doc:`base example </index>`, if we had a ``serverless.yml``
file in the ``src`` directory, we could create test code like::
  
    from contextlib import ExitStack
    
    from unittest import TestCase
    from intercom_test import InterfaceCaseProvider, HTTPCaseAugmenter, aws_http, utils as icy_utils
    
    @icy_utils.complex_test_context
    def around_interface_case(case, setup):
        setup(database(case))
        setup(stubs(case))
        
        yield
    
    # ... define `database` and `stubs` to return context managers for the
    # test case data they are given ...
    
    class InterfaceTests(TestCase):
        def test_interface_case(self):
            # Construct an AWS Lambda handler function mapper from a Serverless
            # configuration (targeting the "aws" provider)
            service = aws_http.ServerlessHandlerMapper("src")
            
            # Get the case-testing callable, which accepts an entry (a dict)
            # from the test data file(s)
            case_tester = service.case_tester(case_env=around_interface_case)
            
            # Construct the case provider
            case_provider = InterfaceCaseProvider(
                "test/component_interfaces", "service",
                case_augmenter=HTTPCaseAugmenter("test/component_test_env/service")
            )
            
            # Use case_provider to construct a generator of case runner callables
            case_runners = case_provider.case_runners(case_tester)
            
            for i, run_test in enumerate(case_runners):
                with self.subTest(i=i):
                    run_test()
    
    if __name__ == '__main__':
        unittest.main()

The callable returned from :py:meth:`intercom_test.aws_http.ServerlessHandlerMapper.case_tester`
accepts a :py:class:`dict` of test case data.  It does not care where this
:py:class:`dict` comes from, but an
:py:class:`intercom_test.framework.InterfaceCaseProvider` is specifically
designed to provide such a value.

Certain keys of the test case :class:`dict` are consulted (documented in
:py:class:`intercom_test.aws_http.HttpCasePreparer`) when building the event
passed to the handler function, and certain other keys (documented in
:py:func:`intercom_test.aws_http.confirm_expected_response`) are used for
evaluating correctness of the handler function's result.

.. _Serverless: https://www.serverless.com
