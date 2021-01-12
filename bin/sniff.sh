#!/bin/bash

# Coverage: --with-coverage --cover-html --cover-html-dir=coverage --cover-package=intercom_test

NOSE_TESTMATCH='((\b|_)tests?|(\b|[a-zA-Z])Tests?)' nosetests "${@}"
