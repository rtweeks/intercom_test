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

from base64 import b64encode
from codecs import ascii_decode
from contextlib import contextmanager
import enum
import hashlib
from io import StringIO
import itertools
import json
import math
import os.path
import re
import yaml
from ..cases import hash_from_fields as _hash_from_fields
from ..exceptions import DataParseError
from ..json_asn1.convert import asn1_der
from ..utils import def_enum
from ..yaml_tools import (
    YAML_EXT,
    content_events as _yaml_content_events,
    value_from_event_stream as _value_from_events,
    get_load_fn as _get_yaml_loader,
)

class Indexer:
    """Builds an index of the augmentation data in a working/update file
    
    Indexable Case Augmentations
    ----------------------------
    
    While an update file may be in any valid YAML format, certain formats are
    more efficient for the system to manage.  Specifically, it is best if:
    
    * The top-level sequence is represented in block (not flow) format
    * Each case is "atomic" -- that is, contains no aliases to nodes outside
      it's own entry in the sequence
    
    In cases where these conditions are not met, the indexer notes the cases
    in the output, but does not provide a starting offset into the file.  The
    result: augmenting the case (or updating the compact augmentation file)
    requires reloading the entire YAML file, not just the single case.
    """
    
    safe_loading = True
    
    @def_enum
    def State():
        return "header top_sequence case_mapping case_data_key_collection case_data_value case_data_value_collection tail"
    
    def __init__(self, key_fields, *, safe_loading=None):
        super().__init__()
        # instance init code
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        self.key_fields = frozenset(key_fields)
        self._state = self.State.header
        self._index = {}
        self._anchors = {}
    
    def read(self, event):
        self._event = event
        anchor = getattr(event, 'anchor', None)
        if anchor is not None:
            if isinstance(event, yaml.AliasEvent):
                if getattr(self, '_case_data_start', 0) > self._anchors.get(event.anchor, math.inf):
                    self._case_atomic = False
            else:
                self._anchors[anchor] = event.start_mark.index
        return getattr(self, '_read_from_' + self._state.name)(event)
    
    def _read_from_header(self, event):
        if not isinstance(event, yaml.NodeEvent):
            pass
        else:
            self._expect(yaml.SequenceStartEvent)
            self._state = self.State.top_sequence
            self._jumpable = not event.flow_style
    
    def _read_from_top_sequence(self, event):
        if isinstance(event, yaml.SequenceEndEvent):
            self._state = self.State.tail
            self._case_data_start = None
        else:
            # Record the offset into the file of the start of the first line of this data case
            self._case_data_start = event.start_mark.index - event.start_mark.column
            
            self._expect(yaml.MappingStartEvent)
            self._state = self.State.case_mapping
            self._case_id = {}
            self._case_atomic = True
    
    def _read_from_case_mapping(self, event):
        if isinstance(event, yaml.MappingEndEvent):
            self._state = self.State.top_sequence
            return self._capture_case()
        elif isinstance(event, yaml.CollectionStartEvent):
            self._state = self.State.case_data_key_collection
            self._depth = 0
            self._case_data_key = [event]
        else:
            self._expect(yaml.ScalarEvent)
            self._case_data_key = event.value
            self._state = self.State.case_data_value
    
    def _read_from_case_data_key_collection(self, event):
        if isinstance(event, yaml.CollectionStartEvent):
            self._depth += 1
        elif isinstance(event, yaml.CollectionEndEvent):
            self._depth -= 1
        self._case_data_key.append(event)
        
        if self._depth < 0:
            self._state = self.State.case_data_value
            self._case_data_key = _value_from_events(self._case_data_key, safe_loading=self.safe_loading)
    
    def _read_from_case_data_value(self, event):
        if isinstance(event, yaml.CollectionStartEvent):
            self._state = self.State.case_data_value_collection
            self._depth = 0
            self._case_data_value = [event]
        else:
            self._expect(yaml.ScalarEvent)
            self._case_data_value = _value_from_events((event,), safe_loading=self.safe_loading)
            self._state = self.State.case_mapping
            self._capture_case_item()
    
    def _read_from_case_data_value_collection(self, event):
        if isinstance(event, yaml.CollectionStartEvent):
            self._depth += 1
        elif isinstance(event, yaml.CollectionEndEvent):
            self._depth -= 1
        self._case_data_value.append(event)
        
        if self._depth < 0:
            self._state = self.State.case_mapping
            self._case_data_value = _value_from_events(self._case_data_value, safe_loading=self.safe_loading)
            self._capture_case_item()
    
    def _read_from_tail(self, event):
        if isinstance(event, (yaml.DocumentEndEvent, yaml.StreamEndEvent)):
            pass
        elif isinstance(event, yaml.DocumentStartEvent):
            self._state = self.State.header
    
    def _capture_case_item(self, ):
        if self._case_data_key in self.key_fields:
            self._case_id[self._case_data_key] = self._case_data_value
        
        del self._case_data_key
        del self._case_data_value
    
    def _capture_case(self, ):
        case_key = _hash_from_fields(self._case_id)
        if self._jumpable and self._case_atomic:
            result = (case_key, self._case_data_start)
        else:
            result = (case_key, None)
        del self._case_data_start
        del self._case_id
        return result
    
    def _expect(self, event_type):
        if isinstance(self._event, event_type):
            return
        raise DataParseError(
            "{} where {} expected"
            " in line {} while reading {}".format(
                type(self._event).__name__,
                event_type.__name__,
                self._event.start_mark.line,
                self._state.name.replace('_', ' '),
            )
        )

def index(paths, key_fields, *, safe_loading=True):
    result = {}
    indexer = Indexer(key_fields, safe_loading=safe_loading)
    for path in paths:
        case_index = itertools.count(0)
        with open(path) as instream:
            for event in yaml.parse(instream):
                entry = indexer.read(event)
                if entry is not None:
                    case_key, offset = entry
                    new_augmenter = TestCaseAugmenter(path, offset, key_fields, case_index=next(case_index), safe_loading=safe_loading)
                    new_augmenter.safe_loading = safe_loading
                    if case_key in result and result[case_key].file_path != path:
                        raise MultipleAugmentationEntriesError(
                            "case {} conflicts with case {}".format(
                                new_augmenter.case_reference,
                                result[case_key].case_reference,
                            )
                        )
                    result[case_key] = new_augmenter
    return result

class CaseReader:
    """Given a file and a starting point, reads the case data
    
    Can be used to :meth:`augment` a :class:`dict` of test case values or to
    read :meth:`augmentation_data_events` for updating a compact file.
    """
    TRAILING_WS = re.compile('\\s+\n')
    
    safe_loading = True
    
    @def_enum
    def State():
        return "key value"
    
    def __init__(self, stream, start_byte, key_fields, *, safe_loading=None):
        super().__init__()
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        self.key_fields = frozenset(key_fields)
        stream.seek(start_byte)
        self._events = yaml.parse(stream)
        self._key = None
        self._value = None
        next(self._events) # should be yaml.StreamStartEvent
        next(self._events) # should be yaml.DocumentStartEvent
        
        self._read_start_of_contents()
    
    def _read_start_of_contents(self, ):
        top_container_start = next(self._events)
        if isinstance(top_container_start, yaml.SequenceStartEvent):
            case_start = next(self._events)
        else:
            case_start = top_container_start
        assert isinstance(case_start, yaml.MappingStartEvent)
        self._state = self.State.key
        self._key = []
        self._depth = 0
    
    def augment(self, d):
        for k_events, v_events in self._content_item_events():
            k = _value_from_events(k_events, safe_loading=self.safe_loading)
            if k in self.key_fields:
                continue
            d.setdefault(k, _value_from_events(v_events, safe_loading=self.safe_loading))
    
    def augmentation_data_events(self, ):
        for k_events, v_events in self._content_item_events():
            k = _value_from_events(k_events, safe_loading=self.safe_loading)
            if k not in self.key_fields:
                yield from k_events
                yield from v_events
    
    def _content_item_events(self, ):
        while self._depth >= 0:
            event = next(self._events)
            if isinstance(event, yaml.CollectionStartEvent):
                self._depth += 1
            elif isinstance(event, yaml.CollectionEndEvent):
                self._depth -= 1
                if self._depth < 0:
                    break
            
            # TODO: Move the trailing whitespace suppression to yaml_tools
            if self._state is self.State.value and isinstance(event, yaml.ScalarEvent) and event.style == '|':
                event.value = self.TRAILING_WS.sub("\n", event.value)
            
            getattr(self, '_' + self._state.name).append(event)
            if self._depth == 0:
                if self._state is self.State.key:
                    self._state = self.State.value
                    self._value = []
                elif self._state is self.State.value:
                    self._state = self.State.key
                    yield (self._key, self._value)
                    self._key = []
        self._events = ()

class TestCaseAugmenter:
    """Callable to augment a test case from an update file entry"""
    
    # Set this to False to allow arbitrary object instantiation and code
    # execution from loaded YAML
    safe_loading = True
    
    def __init__(self, file_path, offset, key_fields, *, case_index=None, safe_loading=None):
        super().__init__()
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        self.file_path = file_path
        self.offset = offset
        self.key_fields = key_fields
        self.case_index = case_index
    
    def __call__(self, d):
        with open(self.file_path) as stream:
            if self.offset is None:
                for k, v in self._load_yaml(stream)[self.case_index].items():
                    d.setdefault(k, v)
            else:
                CaseReader(stream, self.offset, self.key_fields, safe_loading=self.safe_loading).augment(d)
    
    @property
    def case_reference(self):
        if self.case_index is None:
            return "at byte offset {} in {}".format(self.offset, self.file_path)
        else:
            return "{} in {}".format(self.case_index + 1, self.file_path)
    
    @property
    def deposit_file_path(self):
        return self.file_path.rsplit('.', 2)[0] + YAML_EXT
    
    def case_data_events(self, ):
        with open(self.file_path) as stream:
            if self.offset is None:
                augmentation_data = self._load_yaml(stream)[self.case_index]
                for k in self.key_fields:
                    augmentation_data.pop(k, None)
                events = list(_yaml_content_events(augmentation_data))[1:-1]
                yield from events
            else:
                yield from CaseReader(
                    stream,
                    self.offset,
                    self.key_fields,
                    safe_loading=self.safe_loading,
                ).augmentation_data_events()
    
    def _load_yaml(self, stream):
        load_yaml = _get_yaml_loader(safe=self.safe_loading)
        return load_yaml(stream)
