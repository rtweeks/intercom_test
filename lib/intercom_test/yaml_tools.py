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

from io import StringIO
import packaging.version
import yaml

YAML_EXT = '.yml'
PYYAML_REQUIRES_LOADER = packaging.version.parse('5.1') <= packaging.version.parse(yaml.__version__)

def content_events(value):
    """Return an iterable of events presenting *value* within a YAML document"""
    return (
        e for e in yaml.parse(StringIO(yaml.dump(value)))
        if not isinstance(e, (
            yaml.StreamStartEvent,
            yaml.DocumentStartEvent,
            yaml.DocumentEndEvent,
            yaml.StreamEndEvent,
        ))
    )

class EventsToNodes(yaml.composer.Composer, yaml.resolver.Resolver):

    def __init__(self, events):
        super(EventsToNodes, self).__init__()
        if isinstance(events, list):
            events = iter(events)
        self.events = events
        self.current_event = None

    def check_event(self, *choices):
        if self.current_event is None:
            self.current_event = next(self.events)
        if not choices:
            return True
        for choice in choices:
            if isinstance(self.current_event, choice):
                return True
        return False

    def peek_event(self):
        if self.current_event is None:
            self.current_event = next(self.events)
        return self.current_event

    def get_event(self):
        if self.current_event is None:
            self.current_event = next(self.events)
        value = self.current_event
        self.current_event = None
        return value

    def dispose(self):
        pass

def value_from_event_stream(content_events, *, safe_loading=True):
    """Convert an iterable of YAML events to a Pythonic value
    
    The *content_events* MUST NOT include stream or document events.
    """
    content_events = iter(content_events)
    events = [yaml.StreamStartEvent(), yaml.DocumentStartEvent()]
    depth = 0
    while True:
        events.append(next(content_events))
        if isinstance(events[-1], yaml.CollectionStartEvent):
            depth += 1
        elif isinstance(events[-1], yaml.CollectionEndEvent):
            depth -= 1
        
        if depth == 0:
            break
    events.extend([yaml.DocumentEndEvent(), yaml.StreamEndEvent()])
    node = yaml.compose(events, Loader=EventsToNodes)
    node_constructor = (
        yaml.constructor.SafeConstructor
        if safe_loading else
        yaml.constructor.Constructor
    )()
    return node_constructor.construct_object(node, True)

def get_load_fn(*, safe=True):
    if safe:
        return yaml.safe_load
    if PYYAML_REQUIRES_LOADER:
        return yaml.unsafe_load
    return yaml.load
