
# The intercom_test Package

This package provides Python tools to facilitate _Interface by Example_ programming.

Test case data is stored in YAML to provide the widest possible access by tools and programming languages while still being friendly to the humans who often need to manually manipulate it.

Package documentation is available at [Read the Docs][docs].

## Interface by Example

Integration testing has developed a reputation as a gigantic money- and time-suck occurring near the end of a project.  Software components are built _to specification_ in isolation from one another then, near the end of the project, stood up in an actual environment to finally talk to one another.  Inevitably, the two components disagreed on the proper interpretation of some aspect of specifications (think of NASA's lost Mars orbiter), leading to miscommunication or misdesign.  Though the very end of the project is not the best time to discover a need for significant changes, as there is limited opportunity to trade out lower-priority work for the changes required for successful integration, this is exactly when such issues will be discovered.

Beyond the downsides of traditional integration testing enumerated above, the Agile philosophy espouses a general feeling that "Specifications documents are wrong."  This is not saying they are wrong in the sense that writing them is wrong, but that the documents themselves are _providing wrong information_ by:

* Giving incomplete and/or ambiguous specifications
* Contradicting the actual implementation and usage
* Falling out of date with the implementation
* Being more rigid than necessary, promoting byzantine implementations
* Only being testable by writing test code, which may be buggy

In essence, this is another way of saying "If it isn't tested, it isn't true."

A more Agile approach is to document exact input/output pairs conforming to the desired interface.  Consumers of the interface can use these examples to configure mock responses during unit testing, while providers/implementers of the interface can test against the specified cases.  If both consumers and providers are testing against the same cases, a much greater degree of confidence can be developed that both sides are "speaking the same language."

While *intercom_test* is a good tool for testing and communication, it is not a replacement for good communication between the teams developing the service provider and consumer.  Just because the consumer team adds a test case to the interface file does not create a guarantee that the provider could _ever_ make the test pass.  But the consumer development team could use *intercom_test* files to _propose_ a change to the team implementing the provider...in language much less ambiguous than is found in most interface specification documents.


## Test Case Format

Each test case is viewed as a `dict` of values to be consumed by the application's testing system, either as a feasible request/response pair for stubbing in a consumer or as a request/response pair with additional data for generating an integration test case for a provider.

This library provides an iterable of test cases or test case runner callables.  As detailed below, these test cases can come from multiple data files and may be a merge of information in more than one file.  Within the data files, test case data is represented in YAML.

## Challenges Solved

* Correlating augmenting data for the service provider
* Maintaining augmenting data for the service provider
* Merging new test cases


### Correlating Augmenting Data for the Service Provider

The basic idea of storing machine-readable request/response pairs in a shared "repository" between service consumers and providers is straightforward.  The first difficulty arises because service consumers need only the request/response pair for testing where service providers typically need to establish some particular state and/or mocks of other external services for the test cases to pass.  This information will typically be tightly coupled to the provider's implementation (e.g. it's database tables) and really should not be shared as part of the interface example.  This raises the problem of correlating the _augmenting data_ for the service provider with the test case data shared by both components.

The first reasonable solution might be to insist that each test case provide an unique identifier which could be used to look up the augmenting data in a dictionary- or hashtable-like structure.  This is feasible but still puts an additional burden on the format of the data in the shared test cases: it must now incorporate this unique identifier in some way.  This unique identifier is also not typically helpful to the interface consumer and thus constitutes noise on that side of the interface.  The unique identifier also, and subtly as shown below, allows bad behavior by provider-test writers.

An alternative is to derive a hash value for each test case from the key fields of the request.  Since the consumer needs each response to have a different request to effectively make all test case responses available, this also helps to identify cases in the test set where different responses are indicated for the same request.  Using this correlation method, it will be difficult for all the provider-side tests to pass as the provider-side can only have a single augmenting data set correlated with the _request_; when using unique identifiers, the provider side can test multiple cases with different augmentation data for the same request, subtly breaking the consumers' ability to use tests.  Because interface consumers benefit by being able to actually invoke each response, this is the better (if more complicated) solution and the one taken by *intercom_test*.

Typically, the interface case data will be stored in a directory that is shared between consumers and providers (e.g. a Git submodule, a Subversion external) where the augmentation data would live in the same repository as the test code for the provider.  This reduces exposure of implementation details, loosening the coupling between providers and consumers.  It also reduces churn in the interface case files, especially where changes to the persistent storage of the provider occur.


### Maintaining Augmenting Data for the Service Provider

While the hash value derived for identifying the test case described in the previous section works well for _implementation_ of this library, it is much more difficult for a human to use that hash value to correlate the augmenting data with the test case.  Essentially, making a new entry in the compact data format file manually is not feasible.  *intercom_test* incorporates functionality to update such high-performance files from a more human-friendly format, which identifies the test case simply by copying the whole case from the shared interface file and adding new keys to the `dict`.  If the test case runner is wrapped by the provided decorator function (possibly through generation of *case runners*), the compact format data files will be automatically updated from these programmer-friendly _update files_ when all of the interface tests pass.

Beyond automatically wrapping the test function in the compact data updating decorator, the *case runners* that *intercom_test* can generate have an additional advantage: they automatically log the case data they are about to test.  If the testing framework captures and displays logging events for failed tests, it becomes simple to paste the test case data into an update file, alter it as necessary to get the test passing, and have the compact data file automatically updated with the new, correct test data.


## Merging New Test Cases

The simplest organization of the shared test case data (i.e. the request/response pair) would be to put them in a single file using a file format supporting a data sequence: e.g. JSON, XML, or YAML.  This becomes problematic when two branches of development both try to add new items at the end of the file, which inevitably causes a merge conflict.  While this conflict is predictable and fairly easily managed with good tools, it would be preferable to avoid the conflict in the normal course of development.

This essentially means distributing the test cases through multiple files.  *intercom_test* provides facilities for organizing test cases in multiple files and combining them in a predictable, mergeable way as and when desired.


## Command Line Interface (`[cli]` Extra)

When this package is installed with the `[cli]` extra, it makes a command line tool called `icy-test` available to access the core functionality of `intercom_test`, facilitating use of this functionality in languages other than Python.  Help on use of the tool can be obtained by running `icy-test --help`.


## Contributing

1. Fork it ( https://github.com/PayTrace/intercom_test )
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create new Pull Request (on [GitHub](https://github.com))

PayTrace uses *intercom_test* for coordinating testing of protocols between our components, and we consider this library to be in _alpha status_ at this time. It is under active development and maintenance! For further details on contributing, see [CONTRIBUTING.md](./CONTRIBUTING.md).

## TL; DR

This package allows a cheaper version of integration tests to run as part of unit testing.  It reads and maintains the data files necessary for this style of testing.  Service providers and consumers maintain parity by testing with the same test cases.

[docs]: https://intercom-test.readthedocs.io/en/latest/
