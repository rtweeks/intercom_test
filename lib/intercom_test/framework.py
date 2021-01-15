# Copyright 2018 PayTrace, Inc.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from enum import Enum
import functools
from io import StringIO
import json
import logging
import os.path
import shutil
import yaml
from .cases import (
    IdentificationListReader as CaseIdListReader,
    hash_from_fields as _hash_from_fields,
)
from .exceptions import MultipleAugmentationEntriesError, NoAugmentationError
from .augmentation.compact_file import (
    augment_dict_from,
    case_keys as case_keys_in_compact_file,
    TestCaseAugmenter as CompactFileAugmenter,
    Updater as CompactAugmentationUpdater,
)
from .augmentation import update_file
from .utils import (
    FilteredDictView as _FilteredDictView,
    open_temp_copy,
)
from .yaml_tools import (
    YAML_EXT,
    content_events as _yaml_content_events,
    get_load_all_fn as _get_yaml_load_all,
)

logger = logging.getLogger(__name__)

class InterfaceCaseProvider:
    """Test case data manager
    
    Use an instance of this class to:
    
    * Generate test case data :class:`dict`\ s
    * Decorate the case runner function (if auto-updating of compact
      augmentation data files is desired)
    * Merge extension test case files to the main test case file
    * Other case augmentation management tasks
    
    Setting :attr:`use_body_type_magic` to ``True`` automatically parses the
    ``"request body"`` value as JSON if ``"request type"`` in the same test
    case is ``"json"``, and similarly for ``"response body"`` and
    ``"response type"``.
    
    .. automethod:: __init__
    """
    
    use_body_type_magic = False
    
    safe_yaml_loading = True
    
    class _UpdateState(Enum):
        not_requested   = '-'
        requested       = '?'
        aborted         = '!'
        
        def __repr__(self, ):
            return "<{}.{}>".format(type(self).__name__, self.name)
    
    _case_augmenter = None
    
    def __init__(self, spec_dir, group_name, *, case_augmenter=None):
        """Constructing an instance
        
        :param spec_dir: File system directory for test case specifications
        :param group_name: Name of the group of tests to load
        :keyword case_augmenter:
            *optional* An object providing the interface of a
            :class:`.CaseAugmenter`
        
        The main test case file of the group is located in *spec_dir* and is
        named for *group_name* with the '.yml' extension added.  Extension
        test case files are found in the *group_name* subdirectory of
        *spec_dir* and all have '.yml' extensions.
        """
        super().__init__()
        self._spec_dir = spec_dir
        self._group_name = group_name
        self._compact_files_update = self._UpdateState.not_requested
        if case_augmenter:
            self._case_augmenter = case_augmenter
            self._augmented_case = case_augmenter.augmented_test_case
    
    @property
    def spec_dir(self):
        """The directory containing the test specification files for this instance"""
        return self._spec_dir
    
    @property
    def group_name(self):
        """Name of group of test cases to load for this instance"""
        return self._group_name
    
    @property
    def case_augmenter(self):
        """The :class:`.CaseAugmenter` instance used by this object, if any"""
        return self._case_augmenter
    
    @property
    def main_group_test_file(self):
        """Path to the main test file of the group for this instance"""
        return os.path.join(self.spec_dir, self.group_name + YAML_EXT)
    
    def extension_files(self, ):
        """Get an iterable of the extension files of this instance"""
        return extension_files(self.spec_dir, self.group_name)
    
    def cases(self, ):
        """Generates :class:`dict`\ s of test case data
        
        This method reads test cases from the group's main test case file
        and auxiliary files, possibly extending them with augmented data (if
        *case_augmentations* was given in the constructor).
        """
        yield from self._cases_from_file(self.main_group_test_file)
        for ext_file in sorted(self.extension_files()):
            yield from self._cases_from_file(ext_file)
        
        if self._compact_files_update is self._UpdateState.requested:
            self.update_compact_files()
    
    def update_compact_augmentation_on_success(self, fn):
        """Decorator for activating compact data file updates
        
        Using this decorator around the test functions tidies up the logic
        around whether to propagate test case augmentation data from update
        files to compact files.  The compact files will be updated if all
        interface tests succeed and not if any of them fail.
        
        The test runner function can be automatically wrapped with this
        functionality through :meth:`case_runners`.
        """
        CFUpdate = self._UpdateState
        
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if self._compact_files_update is not CFUpdate.aborted:
                self._compact_files_update = CFUpdate.requested
            try:
                return fn(*args, **kwargs)
            except:
                self._compact_files_update = CFUpdate.aborted
                raise
        
        return wrapper
    
    def case_runners(self, fn, *, do_compact_updates=True):
        """Generates runner callables from a callable
        
        The callables in the returned iterable each call *fn* with all the
        positional arguments they are given, the test case :class:`dict` as an
        additional positional argument, and all keyword arguments passed to
        the case runner.
        
        Using this method rather than :meth:`cases` directly for running tests
        has two advantages:
        
        * The default of *do_compact_updates* automatically applies
          :meth:`update_compact_augmentation_on_success` to *fn*
        * Each returned runner callable will log the test case as YAML prior
          to invoking *fn*, which is helpful when updating the augmenting data
          for the case becomes necessary
        """
        
        if do_compact_updates:
            fn = self.update_compact_augmentation_on_success(fn)
        
        for case in self.cases():
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                logger.info("{}\n{}".format(
                    " CASE TESTED ".center(40, '*'),
                    yaml.dump([case]),
                ))
                return fn(*args, case, **kwargs)
            
            yield wrapper
    
    def update_compact_files(self, ):
        """Calls the :class:`CaseAugmenter` to apply compact data file updates
        
        :raises NoAugmentationError:
            when no case augmentation data was specified during construction
            of this object
        """
        if self._case_augmenter is None:
            raise NoAugmentationError("No augmentation data specified")
        return self._case_augmenter.update_compact_files()
    
    def merge_test_extensions(self, ):
        """Merge the extension files of the target group into the group's main file"""
        ext_files = sorted(self.extension_files())
        with open(self.main_group_test_file, 'a') as fixed_version_specs:
            for ext_file in ext_files:
                ext_file_ref = os.path.relpath(ext_file, os.path.join(self.spec_dir, self.group_name))
                print("---\n# From {}\n".format(ext_file_ref), file=fixed_version_specs)
                with open(ext_file) as ext_specs:
                    shutil.copyfileobj(ext_specs, fixed_version_specs)
        
        for ext_file in ext_files:
            os.remove(ext_file)
    
    def _augmented_case(self, x):
        """This method is defined to be overwritten on the instance level when augmented data is used"""
        return x
    
    def _cases_from_file(self, filepath):
        with open(filepath) as file:
            load_all_yaml = _get_yaml_load_all(safe=self.safe_yaml_loading)
            for test_case in (
                tc
                for case_set in load_all_yaml(file)
                for tc in case_set
            ):
                if self.use_body_type_magic:
                    _parse_json_bodies(test_case)
                yield self._augmented_case(test_case)

def extension_files(spec_dir, group_name):
    """Iterator of file paths for extensions of a test case group
    
    :param spec_dir: Directory in which specifications live
    :param group_name: Name of the group to iterate
    """
    yield from data_files(os.path.join(spec_dir, group_name))

def data_files(dir_path):
    """Generate data file paths from the given directory"""
    try:
        dir_listing = os.listdir(dir_path)
    except FileNotFoundError:
        return
    
    for entry in dir_listing:
        entry = os.path.join(dir_path, entry)
        if not os.path.isfile(entry):
            continue
        if not entry.endswith(YAML_EXT):
            continue
        
        yield entry

def _parse_json_bodies(test_case):
    if test_case.get('request type') == 'json':
        test_case['request body'] = json.loads(test_case['request body'])
    if test_case.get('response type') == 'json':
        test_case['response body'] = json.loads(test_case['response body'])

class CaseAugmenter:
    """Base class of case augmentation data managers
    
    This class uses and manages files in a case augmentation directory.  The
    data files are intended to either end in '.yml' or '.update.yml'.
    The version control system should, typically, be set up to ignore files
    with the '.update.yml' extension.  These two kinds of files have a different
    "data shape".
    
    Update files (ending in '.update.yml') are convenient for manual editing
    because they look like the test case file from which the case came, but
    with additional entries in the case data :class:`dict`.  The problems with
    long term use of this file format are A) it is inefficient for correlation
    to test cases, and B) it duplicates data from the test case, possibly
    leading to confusion when modifying the .update.yml file does not change
    the test case.
    
    Compact data files (other files ending in '.yml') typically are generated
    through this package.  The format is difficult to manually correlate with
    the test file, but does not duplicate all of the test case data as does the
    update file data format.  Instead, the relevant keys of the test case are
    hashed and the hash value is used to index the additional augmentation
    value entries.
    
    It is an error for a test case to have multiple augmentations defined
    within .yml files (excluding .update.yml files), whether in the same or
    different files.  It is also an error for multiple files with the
    .update.yml extension to specify augmentation for the same case, though
    within the same file the last specification is taken.  When augmentations
    for a case exist within both one .update.yml and one .yml file, the
    .update.yml is used (with the goal of updating the .yml file with the
    new augmentation values).
    
    Methods of this class depend on the class-level presence of
    :const:`CASE_PRIMARY_KEYS`, which is not provided in this class.  To use
    this class's functionality, derive from it and define this constant in
    the subclass.  Two basic subclasses are defined in this module:
    :class:`HTTPCaseAugmenter` and :class:`RPCCaseAugmenter`.
    
    .. automethod:: __init__
    """
    UPDATE_FILE_EXT = ".update" + YAML_EXT
    
    # Set this to False to allow arbitrary object instantiation and code
    # execution from loaded YAML
    safe_loading = True
    
    def __init__(self, augmentation_data_dir):
        """Constructing an instance
        
        :param augmentation_data_dir:
            path to directory holding the augmentation data
        """
        super().__init__()
        # Initialize info on extension data location
        self._case_augmenters = {}
        self._updates = {} # compact_file_path -> dict of update readers
        working_files = []
        self._augmentation_data_dir = augmentation_data_dir
        for file_path in data_files(augmentation_data_dir):
            if file_path.endswith(self.UPDATE_FILE_EXT):
                working_files.append(file_path)
            else:
                self._load_compact_refs(file_path)
        self._index_working_files(working_files)
    
    @property
    def augmentation_data_dir(self):
        return self._augmentation_data_dir
    
    def _load_compact_refs(self, file_path):
        for case_key, start_byte in case_keys_in_compact_file(file_path):
            if case_key in self._case_augmenters:
                self._excessive_augmentation_data(case_key, self._case_augmenters[case_key].file_path, file_path)
            self._case_augmenters[case_key] = CompactFileAugmenter(file_path, start_byte, case_key, safe_loading=self.safe_loading)
            self._case_augmenters[case_key].safe_loading = self.safe_loading
    
    def _excessive_augmentation_data(self, case_key, file1, file2):
        if file1 == file2:
            error_msg = "Test case key \"{}\" has multiple augmentation entries in {}".format(
                case_key,
                file1,
            )
        else:
            error_msg = "Test case key \"{}\" has augmentation entries in {} and {}".format(
                case_key,
                file1,
                file2,
            )
        raise MultipleAugmentationEntriesError(error_msg)
    
    def _index_working_files(self, working_files):
        for case_key, augmenter in update_file.index(working_files, self.CASE_PRIMARY_KEYS, safe_loading=self.safe_loading).items():
            existing_augmenter = self._case_augmenters.get(case_key)
            if isinstance(existing_augmenter, CompactFileAugmenter):
                if augmenter.deposit_file_path != existing_augmenter.file_path:
                    raise MultipleAugmentationEntriesError(
                        "case {} conflicts with case \"{}\" in {}; if present, this case must be in {}".format(
                            augmenter.case_reference,
                            case_key,
                            existing_augmenter.file_path,
                            os.path.basename(existing_augmenter.file_path).replace(
                                YAML_EXT,
                                self.UPDATE_FILE_EXT
                            ),
                        )
                    )
            elif existing_augmenter is not None:
                raise MultipleAugmentationEntriesError(
                    "case {} conflicts with case {}".format(
                        augmenter.case_reference,
                        existing_augmenter.case_reference,
                    )
                )
            self._updates.setdefault(augmenter.deposit_file_path, {})[case_key] = augmenter
            self._case_augmenters[case_key] = augmenter
    
    @classmethod
    def key_of_case(cls, test_case):
        """Compute the key (hash) value of the given test case"""
        if hasattr(test_case, 'items'):
            test_case = test_case.items()
        return _hash_from_fields(
            (k, v) for k, v in test_case
            if k in cls.CASE_PRIMARY_KEYS
        )
    
    def augmented_test_case(self, test_case):
        """Add key/value pairs to *test_case* per the stored augmentation data
        
        :param dict test_case: The test case to augment
        :returns: Test case with additional key/value pairs
        :rtype: dict
        """
        case_key = self.key_of_case(test_case)
        augment_case = self._case_augmenters.get(case_key)
        if not augment_case:
            return test_case
        
        aug_test_case = dict(test_case)
        augment_case(aug_test_case)
        return aug_test_case
    
    def augmented_test_case_events(self, case_key, case_id_events):
        """Generate YAML events for a test case
        
        :param str case_key:
            The case key for augmentation
        :param case_id_events:
            An iterable of YAML events representing the key/value pairs of the
            test case identity
        
        This is used internally when extending an updates file with the existing
        data from a case, given the ID of the case as YAML.
        """
        case_augmenter = self._case_augmenters.get(case_key)
        yield yaml.MappingStartEvent(None, None, True, flow_style=False)
        yield from case_id_events
        if case_augmenter is not None:
            yield from case_augmenter.case_data_events()
        yield yaml.MappingEndEvent()
    
    def update_compact_files(self, ):
        """Update compact data files from update data files"""
        for file_path, updates in self._updates.items():
            if os.path.exists(file_path):
                with open_temp_copy(file_path) as instream, open(file_path, 'w') as outstream:
                    updated_events = self._updated_compact_events(
                        yaml.parse(instream),
                        updates
                    )
                    
                    yaml.emit(updated_events, outstream)
            else:
                with open(file_path, 'w') as outstream:
                    yaml.emit(self._fresh_content_events(updates.items()), outstream)
    
    def extend_updates(self, file_name_base):
        """Create an object for extending a particular update file
        
        The idea is::
        
            case_augmenter.extend_updates('foo').with_current_augmentation(sys.stdin)
        
        """
        return UpdateExtender(file_name_base, self, safe_loading=self.safe_loading)
    
    def _updated_compact_events(self, events, updates):
        mutator = CompactAugmentationUpdater(
            _FilteredDictView(
                updates,
                value_transform=self._full_yaml_mapping_events_from_update_augmentation
            ),
            self.CASE_PRIMARY_KEYS
        )
        yield from (
            output_event
            for input_event in events
            for output_event in mutator.filter(input_event)
        )
    
    @classmethod
    def _full_yaml_mapping_events_from_update_augmentation(cls, augmenter):
        yield yaml.MappingStartEvent(None, None, True, flow_style=False)
        yield from augmenter.case_data_events()
        yield yaml.MappingEndEvent()
    
    def _fresh_content_events(self, content_iterable):
        # Header events
        yield yaml.StreamStartEvent()
        yield yaml.DocumentStartEvent()
        yield yaml.MappingStartEvent(None, None, True, flow_style=False)
        
        # Content events
        for key, value in content_iterable:
            yield yaml.ScalarEvent(None, None, (True, False), key)
            if isinstance(value, dict):
                yield from _yaml_content_events(dict(
                    (k, v)
                    for k, v in value.items()
                    if k not in self.CASE_PRIMARY_KEYS
                ))
            elif callable(getattr(value, 'case_data_events')):
                yield yaml.MappingStartEvent(None, None, True, flow_style=False)
                yield from value.case_data_events()
                yield yaml.MappingEndEvent()
            else:
                yield yaml.MappingStartEvent(None, None, True, flow_style=False)
                yield from value
                yield yaml.MappingEndEvent()
        
        # Tail events
        yield yaml.MappingEndEvent()
        yield yaml.DocumentEndEvent()
        yield yaml.StreamEndEvent()
    

class HTTPCaseAugmenter(CaseAugmenter):
    """A :class:`.CaseAugmenter` subclass for augmenting HTTP test cases"""
    CASE_PRIMARY_KEYS = frozenset((
        'url', 'method', 'request body',
    ))

class RPCCaseAugmenter(CaseAugmenter):
    """A :class:`.CaseAugmenter` subclass for augmenting RPC test cases"""
    CASE_PRIMARY_KEYS = frozenset((
        'endpoint', 'request parameters',
    ))


class UpdateExtender:
    safe_loading = True
    
    def __init__(self, file_name_base, case_augmenter, *, safe_loading=None):
        super().__init__()
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        self._file_name = os.path.join(
            case_augmenter.augmentation_data_dir,
            file_name_base + case_augmenter.UPDATE_FILE_EXT
        )
        self._case_augmenter = case_augmenter
    
    @property
    def file_name(self):
        return self._file_name
    
    def with_current_augmentation(self, stream):
        """Append the full test case with its current augmentation data to the target file
        
        :param stream:
            A file-like object (which could be passed to :func:`yaml.parse`)
        
        The *stream* contains YAML identifying the test case in question.  The
        identifying YAML from the test case _plus_ the augmentative key/value
        pairs as currently defined in the augmenting data files will be written
        to the file :attr:`file_name`.
        """
        if stream.isatty():
            print("Input test cases from interface, ending with a line containing only '...':")
            buffered_input = StringIO()
            for line in stream:
                if line.rstrip() == "...":
                    break
                buffered_input.write(line)
            buffered_input.seek(0)
            stream = buffered_input
        
        id_list_reader = CaseIdListReader(self._case_augmenter.CASE_PRIMARY_KEYS, safe_loading=self.safe_loading)
        for event in yaml.parse(stream):
            test_case = id_list_reader.read(event)
            if test_case is None:
                continue
            
            # Look up augmentation for case_id
            case_as_currently_augmented_events = (
                self._case_augmenter.augmented_test_case_events(*test_case)
            )
            # Append augmentation case to self.file_name
            with open(self.file_name, 'a') as outstream:
                yaml.emit(
                    self._case_yaml_events(case_as_currently_augmented_events),
                    outstream,
                )
    
    def _case_yaml_events(self, content_events):
        yield yaml.StreamStartEvent()
        yield yaml.DocumentStartEvent(explicit=True)
        yield yaml.SequenceStartEvent(None, None, implicit=True, flow_style=False)
        
        yield from content_events
        
        yield yaml.SequenceEndEvent()
        yield yaml.DocumentEndEvent()
        yield yaml.StreamEndEvent()
