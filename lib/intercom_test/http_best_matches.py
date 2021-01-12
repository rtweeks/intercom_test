"""Module for finding nearest imperfect match for HTTP request"""

from abc import ABC, abstractmethod
from base64 import b64encode
from collections import namedtuple
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from enum import IntEnum
from heapq import heappush, heappop
import itertools
import json
import Levenshtein
import math
from operator import itemgetter
import time
from typing import Iterable, Tuple, Sequence as SequenceType
from urllib.parse import urlparse, parse_qsl
from intercom_test.cases import hash_from_fields as case_hash
from intercom_test.utils import FilteredDictView

class Database:
    def __init__(self, cases: Iterable[dict], *, add_request_keys=()):
        super().__init__()
        
        if not isinstance(cases, Sequence):
            cases = list(cases)
        
        self._additional_request_keys = frozenset(add_request_keys)
        
        self._responses = dict((self._case_key(case), case) for case in cases)
        self._reqlines = _group_dict(cases, _reqline)
        self._urls = _group_dict(cases, _request_url)
        self._paths = _group_dict(cases, _request_url_path)
    
    def get_case(self, request: dict):
        return self._responses.get(self._case_key(request))
    
    def best_matches(self, request: dict, *, timeout: float = 0.3) -> dict:
        """Given HTTP request parameters, find the best known match"""
        
        return _Reporter(self, request, deadline=time.time() + timeout).report()
    
    def json_exchange(self, request_json, reply_stream):
        request = json.loads(request_json)
        case = self.get_case(request)
        if case is not None:
            # Shallow copy, but only to ensure setting 'response status'
            # doesn't change the test case
            response = dict(case)
            # Ensure there is _always_ a 'response status' when a case is returned
            response.setdefault('response status', 200)
        else:
            response = self.best_matches(request).as_jsonic_data()
            # Ensure there is _never_ a 'response status' when diffs are returned
            response.pop('response status', None)
        
        json.dump(response, reply_stream)
    
    def _case_key(self, request: dict):
        def request_key(k):
            return (
                k in ('method', 'url', 'request body')
                or
                k in self._additional_request_keys
            )
        def value_lens(v):
            import sys; from IPython.core.debugger import Pdb; sys.stdout.isatty() and Pdb().set_trace()
            if isinstance(v, bytes):
                return ('binary', str(v))
            return v
        hash_input = FilteredDictView(
            request,
            key_filter=request_key,
            value_transform=value_lens,
        )
        return case_hash(hash_input)

class _Reporter:
    def __init__(self, database, request, *, deadline=math.inf):
        super().__init__()
        self.database = database
        self.request = request
        self.deadline = deadline
    
    @property
    def request_body(self):
        return self.request.get('request body')
    
    def report(self, ):
        db = self.database
        request = self.request
        if _reqline(request) in db._reqlines:
            # TODO: Could be a missing additional field or unknown value in an additional field
            addnl_fields_mismatch = self._get_additional_fields_mismatch()
            if addnl_fields_mismatch:
                return addnl_fields_mismatch
            return self._report_closest_request_bodies()
        
        if _request_url(request) in db._urls:
            return self._report_available_methods()
        
        request_path = _request_url_path(request)
        if request_path in db._paths:
            return self._report_closest_query_params()
        
        def dist_from_request_path(url):
            return Levenshtein.distance(url, request_path)
        
        # TODO: Use a min-priority queue on dist_from_request_url and add items
        # to it until the deadline (or all items added), then pop the top 5
        closest_paths = sorted(db._paths, key=dist_from_request_path)[:5]
        
        return AvailablePathsReport(list(
            (path, db._paths[path])
            for path in closest_paths
        ))
    
    def _get_additional_fields_mismatch(self, ):
        cases = self.database._reqlines[_reqline(self.request)]
        
        addnl_request_keys = set(self.database._additional_request_keys).difference({'method', 'url', 'request body'})
        def is_addnl_field(k):
            return isinstance(k, str) and k in addnl_request_keys
        
        possible_value_sets = []
        for case in cases:
            fvals = sorted(
                FilteredDictView(case, key_filter=is_addnl_field).items()
            )
            if fvals not in possible_value_sets:
                possible_value_sets.append(fvals)
        
        request_addnl_fields = sorted(
            FilteredDictView(self.request, key_filter=is_addnl_field).items()
        )
        if request_addnl_fields in possible_value_sets:
            return None
        def dist_from_request_addnl_fields(case_addnl_fields):
            sm = SequenceMatcher(None, request_addnl_fields, case_addnl_fields)
            opcodes = sm.get_opcodes()
            return sum(
                max(i2 - i1, j2 - j1)
                for op_type, i1, i2, j1, j2 in opcodes
                if op_type != 'equal'
            )
        
        closest_addnl_fields = sorted(
            possible_value_sets,
            key=dist_from_request_addnl_fields
        )[:5]
        
        return AvailableAdditionalFieldsReport(closest_addnl_fields)
    
    def _report_closest_request_bodies(self, ):
        # Report items in the database that have the most similar request bodies
        request_body = self.request_body
        reqbody_is_jsonic = _is_jsonic_body(request_body)
        reqbody_type = type(request_body)
        available_cases = list(
            case
            for case in self.database._reqlines[_reqline(self.request)]
            if type(case.get('request body')) == reqbody_type
        )
        
        if reqbody_is_jsonic:
            jcomp = JsonComparer(self.request_body)
            near_reqbodies_heap = []
            for i, case in enumerate(available_cases):
                if time.time() >= self.deadline:
                    break
                
                diff = jcomp.diff(case.get('request body'))
                
                heappush(near_reqbodies_heap, (
                    diff.edit_distance(),
                    i,
                    diff,
                    case
                ))
            
            closest_reqbody_entries = list(
                heappop(near_reqbodies_heap)[2:]
                for _ in range(min(5, len(near_reqbodies_heap)))
            )
            
            return AvailableJsonRequestBodiesReport(closest_reqbody_entries)
        else:
            # Look for lowest Levenshtein distance between request_body and case['request body']
            def distance_from_request_body(case):
                return Levenshtein.distance(request_body, case['request body'])
            
            # TODO: Use a min-priority queue on distance_from_request_body and
            # add items to it until the deadline (or all items added), then pop
            # the top 5
            closest_reqbodies = sorted(
                available_cases,
                key=distance_from_request_body
            )[:5]
            
            return AvailableScalarRequestBodiesReport(closest_reqbodies)
    
    def _report_available_methods(self, ):
        # Report the HTTP methods that are valid for this URL (path and query-string)
        return AvailableHttpMethodsReport(
            _http_method(case)
            for case in self.database._urls[_request_url(self.request)]
        )
    
    def _report_closest_query_params(self, ):
        # Report the query parameter deltas that would produce a known URL with
        # the same path part
        request_path, request_qsparams = _request_url(self.request)
        qscomp = QStringComparer(request_qsparams)
        near_urls_heap = []
        for i, case in enumerate(self.database._paths[request_path]):
            if time.time() >= self.deadline:
                break
            
            diff = qscomp.diff(_request_url(case)[1])
            
            heappush(near_urls_heap, (
                diff.edits,
                i,
                diff,
                case
            ))
        
        closest_url_entries = list(
            heappop(near_urls_heap)[2:]
            for _ in range(min(5, len(near_urls_heap)))
        )
        
        return AvailableQueryStringParamsetsReport(closest_url_entries)

class Report(ABC):
    @abstractmethod
    def as_jsonic_data(self, ):
        """Convert this report to JSON data"""

class AvailableAdditionalFieldsReport(Report):
    def __init__(self, available_value_sets):
        super().__init__()
        self.available_value_sets = available_value_sets
    
    def as_jsonic_data(self, ):
        return {
            # 'available additional test case field value sets': self.available_value_sets,
            'available additional test case field value sets': list(
                dict(value_set)
                for value_set in self.available_value_sets
            )
        }
    
class AvailablePathsReport(Report):
    def __init__(self, test_case_groups):
        super().__init__()
        self.test_case_groups = test_case_groups
    
    def as_jsonic_data(self, ):
        return {
            'closest URL paths': list(
                (path, list(
                    case.get('description')
                    for case in cases
                    if 'description' in case
                ))
                for path, cases in self.test_case_groups
            )
        }

class AvailableJsonRequestBodiesReport(Report):
    def __init__(self, diff_case_pairs):
        super().__init__()
        self.diff_case_pairs = diff_case_pairs
    
    def as_jsonic_data(self, ):
        return {
            'minimal JSON request body deltas': list(
                {
                    'case description': case.get('description'),
                    'diff': self._json_diff_json(diff),
                }
                for diff, case in self.diff_case_pairs
            )
        }
    
    @classmethod
    def _json_diff_json(cls, json_diff: 'JsonComparer.Delta'):
        if json_diff.structure_diffs:
            return {'alter substructures': list(
                cls._json_mod_json(mod)
                for mod in json_diff.structure_diffs
            )}
        
        if json_diff.structure_location_diffs:
            return {'rearrange substructures': list(
                cls._json_mod_json(mod)
                for mod in json_diff.structure_location_diffs
            )}
        
        if json_diff.scalar_diffs:
            return {'alter scalar values': list(
                cls._json_mod_json(mod)
                for mod in json_diff.scalar_diffs
            )}
    
    @classmethod
    def _json_mod_json(cls, mod):
        result = {}
        for k in set(mod).intersection({'alt', 'del'}):
            result[k] = mod[k]
        if any(k in mod for k in ('alt', 'add')):
            result.update(
                (k, cls._json_struct_desc(v))
                for k, v in mod.items()
                if k in ('to', 'add')
            )
        if 'set' in mod:
            result.update((k, mod[k]) for k in ('set', 'to'))
        
        return result
    
    @classmethod
    def _json_struct_desc(cls, sig):
        coll_type, element_type_info = sig
        if coll_type is JsonType.list:
            return list(jt.construct() for jt in element_type_info)
        if coll_type is JsonType.dict:
            return dict((name, jt.construct()) for name, jt in element_type_info)
    

class AvailableScalarRequestBodiesReport(Report):
    def __init__(self, test_cases):
        super().__init__()
        self.test_cases = test_cases
    
    def as_jsonic_data(self, ):
        return {'closest request bodies': list(
            {
                'case description': case.get('description'),
                **self._body_json(case['request body']),
            }
            for case in self.test_cases
        )}
    
    @classmethod
    def _body_json(cls, body):
        main_key = 'request body'
        if isinstance(body, bytes):
            return {
                main_key: b64encode(body).decode('ASCII'),
                'isBase64Encoded': True,
            }
        else:
            return {main_key: body}
    

class AvailableHttpMethodsReport(Report):
    def __init__(self, methods):
        super().__init__()
        self.methods = set(methods)
    
    def as_jsonic_data(self, ):
        return {'available HTTP methods': list(self.methods)}
    

class AvailableQueryStringParamsetsReport(Report):
    def __init__(self, deltas):
        super().__init__()
        self.deltas = deltas
    
    def as_jsonic_data(self, ):
        return {
            'minimal query string deltas': list(
                {
                    'case description': case.get('description'),
                    'diff': self._qstring_diff_json(diff),
                }
                for diff, case in self.deltas
            )
        }
    
    def _qstring_diff_json(self, qsparam_diff: 'QStringComparer.Delta'):
        return {
            'params with differing value sequences': qsparam_diff.params,
            'mods': qsparam_diff.mods,
        }

def _request_url_path(case):
    return urlparse(case['url']).path

def _request_url(case):
    url = urlparse(case['url'])
    qsparams = sorted(
        parse_qsl(url.query),
        # key=lambda i: (i[1][0], i[0])
        key=itemgetter(0)
    )
    return (url.path, tuple(qsparams))

def _http_method(case):
    return case.get('method', 'get').lower()

def _reqline(case):
    return (_http_method(case), case['url'])

def _group_dict(a: Iterable, key, *, value=lambda x: x) -> dict:
    result = {}
    for item in a:
        result.setdefault(key(item), []).append(value(item))
    return result

class JsonWalker:
    
    def walk(self, json_data):
        yield from self._walk_node(json_data, ())
    
    def _walk_node(self, node, key_path):
        if isinstance(node, Mapping):
            yield from self._visit_dict(node, key_path)
        elif isinstance(node, (list, tuple)):
            yield from self._visit_list(node, key_path)
        else:
            yield from self._visit_scalar(node, key_path)
    
    def _visit_scalar(self, value, key_path):
        yield ((lookup_json_type(type(value)), value), value, key_path)
    
    def _visit_list(self, L, key_path):
        yield ((JsonType.list, tuple(lookup_json_type(type(i)) for i in L)), L, key_path)
        yield from (
            event
            for i, item in enumerate(L)
            for event in self._walk_node(item, key_path + (i,))
        )
    
    def _visit_dict(self, d, key_path):
        yield ((JsonType.dict, frozenset((k, lookup_json_type(type(v))) for k, v in d.items())), d, key_path)
        yield from (
            event
            for i, k in enumerate(sorted(d))
            for event in self._walk_node(d[k], key_path + (k,))
        )
    
class JsonMap:
    def __init__(self, json_data):
        super().__init__()
        self._root = json_data
        self._json_index = json_index = list(JsonWalker().walk(json_data))
    
    @property
    def substruct_signatures(self):
        """Indexes correspond with :meth:`.substruct_key_paths`"""
        if not hasattr(self, '_substruct_signatures'):
            self._index_substructures()
        return self._substruct_signatures
    
    @property
    def substruct_key_paths(self):
        """Indexes correspond with :meth:`.substruct_signatures`"""
        if not hasattr(self, '_substruct_key_paths'):
            self._index_substructures()
        return self._substruct_key_paths
    
    @property
    def substruct_locations(self, ):
        if not hasattr(self, '_substruct_locations'):
            self._substruct_locations = tuple(
                (item[2], item[0])
                for item in self._json_index
                if item[0][0].is_collection
            )
        return self._substruct_locations
    
    def items_from_signature(self, sig):
        if not hasattr(self, '_items_by_signature'):
            self._items_by_signature = _group_dict(
                self._json_index,
                key=itemgetter(0),
                value=itemgetter(1),
            )
        return self._items_by_signature.get(sig, [])
    
    @property
    def scalars(self):
        """Indexes correspond with :meth:`.scalar_key_paths`"""
        if not hasattr(self, '_scalars'):
            self._scalars = tuple(
                (item[2], item[1])
                for item in self._json_index
                if not item[0][0].is_collection
            )
        return self._scalars
    
    def _index_substructures(self, ):
        type_sorted_substructures = sorted(
            (
                item for item in self._json_index
                if item[0][0].is_collection
            ),
            key=itemgetter(0)
        )
        
        self._substruct_signatures = tuple(
            item[0] for item in type_sorted_substructures
        )
        self._substruct_key_paths = tuple(
            item[2] for item in type_sorted_substructures
        )

class JsonComparer:
    """Utility to compare one JSON document with several others"""
    
    CONGRUENT_DATA = 'congruent options'
    
    def __init__(self, ref):
        super().__init__()
        self.ref_map = JsonMap(ref)
    
    class Delta(tuple):
        """Differences between two JSON documents
        
        This difference always consists of three parts, in decreasing order of
        precedence:
        
        * Changes to which substructures are present,
        * Changes to where substructures are located, and
        * Changes to scalar values.
        
        Only one of these three will be non-empty.
        
        Use :meth:`.distance` to get a sortable distance measure for this
        delta.
        """
        __slots__ = []
        
        def __new__(cls, struct, struct_loc, scalar):
            return tuple.__new__(cls, (struct, struct_loc, scalar))
        
        @property
        def structure_diffs(self):
            return self[0]
        
        @property
        def structure_location_diffs(self):
            return self[1]
        
        @property
        def scalar_diffs(self):
            return self[2]
        
        def edit_distance(self, ):
            return tuple(map(len, self))
    
    def diff(self, case) -> Delta:
        """Diffs two JSON documents
        
        The difference evaluation proceeds in three steps, with each of the
        later steps proceeding only if the earlier step produced no differences.
        
        The steps are:
        
        *   All substructures (lists and dicts, with correct subitem signatures)
            are present.
        *   All substructures are in the correct locations.
        *   Each scalar value location holds the expected scalar value.
        
        To reflect this, the differences are returned as a tuple of three
        :class:`.Sequence`s wrapped in a :class:`.JsonComparer.Delta`, only one
        of which will contain any items:
        
        *   Changes to which substructures are present.
        *   Changes to where substructures are located.
        *   Changes to scalar values.
        
        """
        ref_map = self.ref_map
        case_map = JsonMap(case)
        
        # First, diff sorted substructures
        diffs = tuple(self._substruct_signature_diffs(ref_map, case_map))
        if diffs:
            return self.Delta(diffs, (), ())
        # Second, diff (key_path, substruct_sig) pairs
        diffs = tuple(self._substruct_location_diffs(ref_map, case_map))
        if diffs:
            return self.Delta((), diffs, ())
        # Finally, diff scalars in document order
        diffs = tuple(self._scalar_diffs(ref_map, case_map))
        return self.Delta((), (), diffs)
    
    def _substruct_signature_diffs(self, ref_map: JsonMap, case_map: JsonMap):
        sm = SequenceMatcher(None, ref_map.substruct_signatures, case_map.substruct_signatures)
        
        for op_type, i1, i2, j1, j2 in sm.get_opcodes():
            if op_type == 'equal':
                continue
            
            current = (ref_map.substruct_key_paths[i] for i in range(i1, i2))
            target = (case_map.substruct_signatures[j] for j in range(j1, j2))
            
            # Use weird range iterator to prevent pulling an extra item from current while zipping
            for _, key_path, struct_sig in zip(_alt_range(i1, i2, j1, j2), current, target):
                yield {'alt': key_path, 'to': struct_sig, self.CONGRUENT_DATA: case_map.items_from_signature(struct_sig)}
            for key_path in current:
                yield {'del': key_path}
            for struct_sig in target:
                yield {'add': struct_sig, self.CONGRUENT_DATA: case_map.items_from_signature(struct_sig)}
    
    def _substruct_location_diffs(self, ref_map: JsonMap, case_map: JsonMap):
        sm = SequenceMatcher(None, ref_map.substruct_locations, case_map.substruct_locations)
        
        for op_type, i1, i2, j1, j2 in sm.get_opcodes():
            if op_type == 'equal':
                continue
            
            current = (ref_map.substruct_locations[i][0] for i in range(i1, i2))
            target = (case_map.substruct_locations[j][1] for j in range(j1, j2))
            
            # Use weird range iterator to prevent pulling an extra item from current while zipping
            for _, key_path, struct_sig in zip(_alt_range(i1, i2, j1, j2), current, target):
                yield {'alt': key_path, 'to': struct_sig, self.CONGRUENT_DATA: case_map.items_from_signature(struct_sig)}
            for key_path in current:
                yield {'del': key_path}
            for struct_sig in target:
                yield {'add': struct_sig, self.CONGRUENT_DATA: case_map.items_from_signature(struct_sig)}
    
    def _scalar_diffs(self, ref_map: JsonMap, case_map: JsonMap):
        sm = SequenceMatcher(None, ref_map.scalars, case_map.scalars)
        
        opcodes = sm.get_opcodes()
        for op_type, i1, i2, j1, j2 in opcodes:
            if op_type == 'equal':
                continue
            
            current = (ref_map.scalars[i][0] for i in range(i1, i2))
            target = (case_map.scalars[j][1] for j in range(j1, j2))
            
            # Use weird range iterator to prevent pulling an extra item from current while zipping
            for _, key_path, value in zip(_alt_range(i1, i2, j1, j2), current, target):
                # For scalars, this is intentionally different than substructure
                yield {'set': key_path, 'to': value}
            for key_path in current:
                yield {'del': key_path}
            for value in target:
                yield {'ins': value}

class QStringComparer:
    """Utility to compare one URL query string with several others"""
    
    class Delta(tuple):
        __slots__ = []
        
        def __new__(cls, edits, params, mods):
            return tuple.__new__(cls, (edits, params, mods))
        
        @property
        def edits(self):
            return self[0]
        
        @property
        def params(self):
            return self[1]
        
        @property
        def mods(self):
            return self[2]
    
    def __init__(self, qsparams: SequenceType[Tuple[str, str]]):
        super().__init__()
        self.ref_qsparams = qsparams
    
    def diff(self, case_qsparams: SequenceType[Tuple[str, str]]):
        sm = SequenceMatcher(None, self.ref_qsparams, case_qsparams)
        opcodes = sm.get_opcodes()
        delta_params = set()
        edits = 0
        for op_type, i1, i2, j1, j2 in opcodes:
            if op_type == 'equal':
                continue
            
            delta_params.update(self.ref_qsparams[i][0] for i in range(i1, i2))
            delta_params.update(case_qsparams[j][0] for j in range(j1, j2))
            
            edits += max(i2 - i1, j2 - j1)
        
        delta_param_values = _group_dict(
            (
                param for param in case_qsparams
                if param[0] in delta_params
            ),
            key=itemgetter(0),
            value=itemgetter(1),
        )
        
        return self.Delta(
            edits,
            delta_param_values,
            tuple(self._mods(case_qsparams, opcodes))
        )
    
    def _mods(self, case_qsparams, opcodes):
        for op_type, i1, i2, j1, j2 in opcodes:
            if op_type == 'equal':
                continue
            
            current = (self.ref_qsparams[i] for i in range(i1, i2))
            target = (case_qsparams[j] for j in range(j1, j2))
            
            for _, cur, targ in zip(_alt_range(i1, i2, j1, j2), current, target):
                if cur[0] == targ[0]:
                    yield {'field': cur[0], 'chg': cur[1], 'to': targ[1]}
                else:
                    yield {'field': cur[0], 'del': cur[1]}
                    yield {'field': targ[0], 'add': targ[1]}
            for field, value in current:
                yield {'field': field, 'del': value}
            for field, value in target:
                yield {'field': field, 'add': value}

JSON_TYPES = (type(None), str, int, float, list, dict) # list and dict must be the last two, in that order
JsonType = IntEnum('JsonType', list(t.__name__ for t in JSON_TYPES))
JsonType.is_collection = property(lambda self: self >= self.list)
JsonType.construct = lambda self: JSON_TYPES[self.value - 1]()
lookup_json_type = dict(zip(JSON_TYPES, JsonType)).get

def _is_jsonic_body(body):
    return not isinstance(body, (str, bytes))

def _alt_range(i1, i2, j1, j2):
    return range(min(i2 - i1, j2 - j1))
