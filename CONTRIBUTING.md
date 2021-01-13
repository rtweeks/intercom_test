Contributing to intercom_test
=================

:+1::tada: First and foremost, thanks for taking the time and effort to contribute! :tada::+1:

The following is a set of guidelines for contributing to this project.  These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Unit Tests

`Development` is a requirements.txt-style file meant to be `pip install`-ed from the root directory of the project.  It will install the `intercom_test` package from the project directory in development mode as well as the development tools needed for running the tests in the repository and other project-related tasks (like coverage reporting).

`intercom_test` is set up to be tested with [nose][nose-package] via `bin/sniff.sh`.  This small bash script may have useful comments about arguments that can be passed.

## Code Review

All pull requests will be reviewed by one or more of the Senior Engineers at PayTrace. As of 2018-October-21, those users are:

* dax-wilson
* ehutchinson
* quachj
* rtweeks

You don't need to pick a reviewer; if you submit a pull request, we'll see it and figure out who should review it.

If your pull request involves large or sensitive changes, it will probably need to be reviewed by our Engineering leadership or in some rare cases our legal counsel.
Obviously for such larger changes, there may be a delay in reviewing/merging if the appropriate PayTracers are unavailable, or if we need to complete merge some other related work first as a prerequisite. If you have any questions along the way, feel free to ask on the thread, and we'll be happy to help out.

## Help us help you!

We highly recommend [allowing edits from maintainers](https://help.github.com/articles/allowing-changes-to-a-pull-request-branch-created-from-a-fork/) (ie, us) to your branch. Since intercom_test is actively developed, there's a good chance that other pull requests will have been merged in between when you submit a pull request and when we approve it. Allowing us to edit your branch means that we can rebase and fix any merge conflicts for you.



[nose-package]: https://pypi.org/project/nose/
