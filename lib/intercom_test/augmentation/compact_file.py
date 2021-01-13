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

import enum
from io import StringIO
import itertools
import json
import os.path
import yaml
from ..cases import hash_from_fields as _hash_from_fields
from ..exceptions import DataParseError
from ..utils import def_enum
from ..yaml_tools import (
    content_events as _yaml_content_events,
    value_from_event_stream as _yaml_value_from_events,
    get_load_fn as _get_yaml_loader,
)

class CaseIndexer:
    """Collector of case keys and their "jump indexes" in a compact file
    
    Objects of this class consume YAML events (as from :func:`yaml.parse`)
    and collect the test case keys and their corresponding starting offsets
    within the file, assuming the file represents the top level mapping in
    block format.
    """
    @def_enum
    def State():
        return 'header case_key case_data tail'
    
    def __init__(self, ):
        super().__init__()
        self._state = self.State.header
        self.case_keys = []
    
    def read(self, event):
        self._event = event
        getattr(self, '_read_from_' + self._state.name)(event)
    
    def _read_from_header(self, event):
        if not isinstance(event, yaml.NodeEvent):
            pass
        else:
            self._expect(yaml.MappingStartEvent)
            self._state = self.State.case_key
            self._jumpable = not event.flow_style
    
    def _read_from_case_key(self, event):
        if isinstance(event, yaml.MappingEndEvent):
            self._state = self.State.tail
        else:
            self._expect(yaml.ScalarEvent)
            self.case_keys.append((event.value, event.start_mark.index if self._jumpable else None))
            self._state = self.State.case_data
            self._depth = 0
    
    def _read_from_case_data(self, event):
        if isinstance(event, yaml.CollectionStartEvent):
            self._depth += 1
        elif isinstance(event, yaml.CollectionEndEvent):
            self._depth -= 1
        
        if self._depth == 0:
            self._state = self.State.case_key
    
    def _read_from_tail(self, event):
        if isinstance(event, (yaml.DocumentEndEvent, yaml.StreamEndEvent)):
            pass
        elif isinstance(event, yaml.DocumentStartEvent):
            self._state = self.State.header
    
    def _expect(self, event_type):
        if isinstance(self._event, event_type):
            return
        raise DataParseError(
            "{} where {} expected"
            " in line {} while reading {}".format(
                type(self._event).__name__,
                event_type.__name__,
                self._event.start_mark.line,
                self._state.name.replace("_", " "),
            )
        )

class DataValueReader:
    """Reads the augmentation data for a single case in a compact file
    
    The code constructing this object should know the starting byte offset
    into the stream and the test case key located at that offset.  This allows
    the reader to skip directly to that case and process only that case.
    """
    
    safe_loading = True
    
    def __init__(self, stream, start_byte, case_key, *, safe_loading=None):
        super().__init__()
        # instance init code
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        stream.seek(start_byte)
        self._events = yaml.parse(stream)
        next(self._events) # should be yaml.StreamStartEvent
        next(self._events) # should be yaml.DocumentStartEvent
        assert isinstance(next(self._events), yaml.MappingStartEvent)
        key_event = next(self._events)
        assert isinstance(key_event, yaml.ScalarEvent)
        assert key_event.value == case_key
        assert isinstance(next(self._events), yaml.MappingStartEvent)
    
    def augment(self, d):
        while True:
            # "Peek" at next event to see if it is the end of the mapping
            next_event = next(self._events)
            if isinstance(next_event, yaml.MappingEndEvent):
                break
            
            # If *next_event* doesn't end the mapping, we have to chain it
            # in front of *self._events* to read the key
            key = _yaml_value_from_events(
                itertools.chain((next_event,), self._events),
                safe_loading=self.safe_loading
            )
            value = self._get_value()
            d.setdefault(key, value)
    
    def _get_value(self, ):
        return _yaml_value_from_events(self._events, safe_loading=self.safe_loading)
    
    def augmentation_data_events(self, ):
        depth = 0
        while depth >= 0:
            event = next(self._events)
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
            if depth >= 0:
                yield event

def case_keys(data_file):
    reader = CaseIndexer()
    
    with open(data_file) as stream:
        for event in yaml.parse(stream):
            reader.read(event)
    
    return reader.case_keys

def augment_dict_from(d, file_ref, case_key, *, safe_loading=True):
    file, start_byte = file_ref
    load_yaml = _get_yaml_loader(safe=safe_loading)
    with open(file) as stream:
        if start_byte is None:
            for k, v in load_yaml(stream)[case_key].items():
                d.setdefault(k, v)
        else:
            DataValueReader(stream, start_byte, case_key, safe_loading=safe_loading).augment(d)

class TestCaseAugmenter:
    """Callable to augment a test case from a compact entry"""
    
    # Set this to False to allow arbitrary object instantiation and code
    # execution from loaded YAML
    safe_loading = True
    
    def __init__(self, file_path, offset, case_key, *, safe_loading=None):
        super().__init__()
        if safe_loading is not None and safe_loading is not self.safe_loading:
            self.safe_loading = safe_loading
        self.file_path = file_path
        self.offset = offset
        self.case_key = case_key
    
    def __call__(self, d):
        with open(self.file_path) as stream:
            if self.offset is None:
                for k, v in self._load_yaml(stream)[self.case_key].items():
                    d.setdefault(k, v)
            else:
                DataValueReader(stream, self.offset, self.case_key, safe_loading=self.safe_loading).augment(d)
    
    def case_data_events(self, ):
        with open(self.file_path) as stream:
            if self.offset is None:
                augmentation_data = self._load_yaml(stream)[self.case_key]
                events = list(_yaml_content_events(augmentation_data))[1:-1]
                yield from events
            else:
                yield from DataValueReader(
                    stream,
                    self.offset,
                    self.case_key,
                    safe_loading=self.safe_loading,
                ).augmentation_data_events()
    
    def _load_yaml(self, stream):
        load_yaml = _get_yaml_loader(safe=self.safe_loading)
        return load_yaml(stream)

class Updater:
    """YAML event-stream editor for compact augumentation data files
    
    Objects of this class support applying a set of updates/additions to
    the stream of YAML events from a compact augmentation data file.  Each
    event is fed to :meth:`filter`, which returns an iterable of events to
    include in the output.
    
    Updates are a :class:`dict` (or similar by duck-type) keyed by *case keys*;
    the corresponding or return values are either a :class:`dict` of
    augmentation values to associate with the test case or an iterable of
    :class:`yaml.Event` objects representing a YAML node to be used as the
    augmenting value.  The event list approach allows more fidelity in
    preserving the representation from the update file.
    """
    @def_enum
    def State():
        return 'header top_mapping case_data tail'
    
    def __init__(self, updates, excluded_keys=()):
        super().__init__()
        self.updates = updates
        self.excluded_keys = excluded_keys
        self._state = self.State.header
        self._updated = set()
    
    def filter(self, event):
        """Converts an event into an iterable of events (possibly empty)"""
        self._event = event
        return getattr(self, '_filter_{}_event'.format(self._state.name))(event)
    
    def _filter_header_event(self, event):
        yield event
        if isinstance(event, yaml.MappingStartEvent):
            self._state = self.State.top_mapping
    
    def _filter_top_mapping_event(self, event):
        if isinstance(event, yaml.MappingEndEvent):
            yield from self._new_case_events()
            yield event
            self._state = self.State.tail
        else:
            yield from self._filter_case_key_event(event)
    
    def _filter_case_key_event(self, event):
        self._expect(yaml.ScalarEvent)
        yield event
        self._state = self.State.case_data
        self._depth = 0
        
        updated_value = self.updates.get(event.value)
        self._substituting_case_value = updated_value is not None
        if self._substituting_case_value:
            self._updated.add(event.value)
            if isinstance(updated_value, dict):
                yield from _yaml_content_events(
                    self._augmentation_data(self.updates[event.value])
                )
            else:
                yield from updated_value
    
    def _filter_case_data_event(self, event):
        if isinstance(event, yaml.CollectionStartEvent):
            self._depth += 1
        elif isinstance(event, yaml.CollectionEndEvent):
            self._depth -= 1
        
        if not self._substituting_case_value:
            yield event
        
        if self._depth == 0:
            self._state = self.State.top_mapping
    
    def _new_case_events(self, ):
        for case_key, value in (
            (k, v)
            for k, v in self.updates.items()
            if k not in self._updated
        ):
            yield yaml.ScalarEvent(None, None, (True, False), case_key)
            if isinstance(value, dict):
                yield from _yaml_content_events(
                    self._augmentation_data(value)
                )
            else:
                yield from value
    
    def _filter_tail_event(self, event):
        yield event
    
    def _expect(self, event_type):
        if isinstance(self._event, event_type):
            return
        raise DataParseError(
            "{} where {} expected"
            " in line {} while reading {}".format(
                type(self._event).__name__,
                event_type.__name__,
                self._event.start_mark.line,
                self._state.name.replace("_", " "),
            )
        )
    
    def _augmentation_data(self, test_case):
        return dict(
            (k, v)
            for k, v in test_case.items()
            if k not in self.excluded_keys
        )
