from intercom_test import http_best_matches as subject
from base64 import b64encode
from io import StringIO
import json
from should_dsl import should, should_not

JSON_STR = """[{
  "id": 1,
  "first_name": "Jeanette",
  "last_name": "Penddreth",
  "email": "jpenddreth0@census.gov",
  "gender": "Female",
  "ip_address": "26.58.193.2"
}, {
  "id": 2,
  "first_name": "Giavani",
  "last_name": "Frediani",
  "email": "gfrediani1@senate.gov",
  "gender": "Male",
  "ip_address": "229.179.4.212"
}, {
  "id": 3,
  "first_name": "Noell",
  "last_name": "Bea",
  "email": "nbea2@imageshack.us",
  "gender": "Female",
  "ip_address": "180.66.162.255"
}, {
  "id": 4,
  "first_name": "Willard",
  "last_name": "Valek",
  "email": "wvalek3@vk.com",
  "gender": "Male",
  "ip_address": "67.76.188.26"
}]"""

def new_json_data(mod=None):
    data = json.loads(JSON_STR)
    if mod is not None:
        mod(data)
    return data

def make_case(method, url, body=None):
    result = {'method': method, 'url': url}
    if body is not None:
        result['request body'] = body
    return result

def json_data_pair(mod):
    return (new_json_data(), new_json_data(mod))

def remove_index_2(data):
    del data[2]

def swap_at_indexes(a, b):
    def swapper(data):
        data[a], data[b] = data[b], data[a]
    swapper.swaps = (a, b)
    return swapper

JsonType = subject.JsonType

class JsonDescStrings:
    CASE_DESCRIPTION = 'case description'
    JSON_BODY_DELTAS = 'minimal JSON request body deltas'
    SCALAR_BODY_DELTAS = 'closest request bodies'
    ALTER_SUBSTRUCT = 'alter substructures'
    REARRANGE_SUBSTRUCT = 'rearrange substructures'
    ALTER_SCALARS = 'alter scalar values'
    KNOWN_METHODS = 'available HTTP methods'
    QSTRING_DELTAS = 'minimal query string deltas'
    TARGET_QSPARAMS = 'params with differing value sequences'
    GOOD_PATHS = 'closest URL paths'
    ADDNL_FIELDS_SETS = 'available additional test case field value sets'

################################# TESTS #################################

def test_report_incorrect_scalar_value():
    def alter_request(request):
        request[0]['first_name'] = 'Bob'
    
    case, request = (
        make_case('post', '/foo', body)
        for body in json_data_pair(alter_request)
    )
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableJsonRequestBodiesReport)
    
    suggestions.diff_case_pairs |should| have(1).item
    diff, case = suggestions.diff_case_pairs[0]
    diff.structure_diffs |should| be_empty
    diff.structure_location_diffs |should| be_empty
    diff.scalar_diffs |should_not| be_empty
    diff.scalar_diffs |should| equal_to(({'set': (0, 'first_name'), 'to': 'Jeanette'},))
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.JSON_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.ALTER_SCALARS: [
                        {'set': (0, 'first_name'), 'to': 'Jeanette'},
                    ]
                },
            }
        ]
    })

def test_report_incorrect_scalar_type():
    def alter_request(request):
        request[0]['first_name'] = 7
    
    case, request = (
        make_case('post', '/foo', body)
        for body in json_data_pair(alter_request)
    )
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableJsonRequestBodiesReport)
    
    suggestions.diff_case_pairs |should| have(1).item
    diff, case = suggestions.diff_case_pairs[0]
    diff.structure_diffs |should| have(2).items
    diff.structure_diffs[0] |should| equal_to({'del': (0,)})
    d = diff.structure_diffs[1]
    d['add'][0] |should| equal_to(JsonType.dict)
    d['add'][1] |should| equal_to({
        ('first_name', JsonType.str),
        ('last_name', JsonType.str),
        ('id', JsonType.int),
        ('gender', JsonType.str),
        ('ip_address', JsonType.str),
        ('email', JsonType.str),
    })
    
    del request['request body'][0]
    request['request body'].append(dict(
        (fname, t.construct())
        for fname, t in d['add'][1]
    ))
    
    suggestions2 = db.best_matches(request)
    suggestions2.diff_case_pairs |should| have(1).item
    diff, case = suggestions2.diff_case_pairs[0]
    diff.structure_diffs |should| have(0).items
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.JSON_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.ALTER_SUBSTRUCT: [
                        {'del': (0,)},
                        {'add': {
                            'email': '',
                            'ip_address': '',
                            'first_name': '',
                            'last_name': '',
                            'gender': '',
                            'id': 0,
                        }},
                    ]
                },
            }
        ]
    })

def test_report_misplaced_substructure():
    def alter_request(request):
        request[2]['oops'] = request[3]
        del request[3]
    
    case, request = (
        make_case('post', '/foo', body)
        for body in json_data_pair(alter_request)
    )
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableJsonRequestBodiesReport)
    
    suggestions.diff_case_pairs |should| have(1).item
    diff, case = suggestions.diff_case_pairs[0]
    diff.structure_diffs |should| have(2).items
    
    d = diff.structure_diffs[0]
    d |should| contain('alt')
    d['alt'] |should| equal_to(())
    d['to'][0] |should| be(JsonType.list)
    d['to'][1] |should| equal_to((JsonType.dict,) * 4)
    
    d = diff.structure_diffs[1]
    d |should| contain('alt')
    d['alt'] |should| equal_to((2,))
    d['to'][0] |should| be(JsonType.dict)
    d['to'][1] |should| equal_to({
        ('first_name', JsonType.str),
        ('last_name', JsonType.str),
        ('id', JsonType.int),
        ('gender', JsonType.str),
        ('ip_address', JsonType.str),
        ('email', JsonType.str),
    })
    set(request['request body'][2]).difference(k for k, _ in d['to'][1]) |should| equal_to({'oops'})
    
    # In particular, note that there is no 'add' key in any of
    # diff.structure_diffs; this indicates that the difference at key_path ()
    # must come from something in request['request body'][2] (which also wants
    # a structural change).
    
    request['request body'].append(request['request body'][2]['oops'])
    del request['request body'][2]['oops']
    
    suggestions2 = db.best_matches(request)
    suggestions2.diff_case_pairs |should| have(1).item
    diff, case = suggestions2.diff_case_pairs[0]
    diff.structure_diffs |should| have(0).items
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.JSON_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.ALTER_SUBSTRUCT: [
                        {'alt': (), 'to': [{}, {}, {}, {}]},
                        {'alt': (2,), 'to': {
                            'email': '',
                            'id': 0,
                            'ip_address': '',
                            'last_name': '',
                            'first_name': '',
                            'gender': ''
                        }}
                    ]
                },
            },
        ]
    })

def test_swapped_substructure():
    case, request = (
        make_case('post', '/foo', body)
        for body in json_data_pair(swap_at_indexes(0, 2))
    )
    case['request body'][0]['foo'] = request['request body'][2]['foo'] = 42
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableJsonRequestBodiesReport)
    
    suggestions.diff_case_pairs |should| have(1).item
    diff, case = suggestions.diff_case_pairs[0]
    diff.structure_diffs |should| have(0).items
    diff.structure_location_diffs |should| have(2).items
    
    d = diff.structure_location_diffs[0]
    d |should| contain('alt')
    d['alt'] |should| equal_to((0,))
    d['to'][0] |should| be(JsonType.dict)
    d['to'][1] |should| equal_to({
        ('first_name', JsonType.str),
        ('last_name', JsonType.str),
        ('id', JsonType.int),
        ('gender', JsonType.str),
        ('ip_address', JsonType.str),
        ('email', JsonType.str),
        ('foo', JsonType.int),
    })
    
    d = diff.structure_location_diffs[1]
    d |should| contain('alt')
    d['alt'] |should| equal_to((2,))
    d['to'][0] |should| be(JsonType.dict)
    d['to'][1] |should| equal_to({
        ('first_name', JsonType.str),
        ('last_name', JsonType.str),
        ('id', JsonType.int),
        ('gender', JsonType.str),
        ('ip_address', JsonType.str),
        ('email', JsonType.str),
    })
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.JSON_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.REARRANGE_SUBSTRUCT: [
                        {'alt': (0,), 'to': {
                            'id': 0,
                            'foo': 0,
                            'gender': '',
                            'first_name': '',
                            'last_name': '',
                            'ip_address': '',
                            'email': ''
                        }},
                        {'alt': (2,), 'to': {
                            'id': 0,
                            'gender': '',
                            'first_name': '',
                            'last_name': '',
                            'ip_address': '',
                            'email': ''
                        }},
                    ]
                }
            }
        ]
    })

def test_body_string_diff():
    case, request = (
        make_case('post', '/get_bar_info', "name={}".format(name))
        for name in ('Cheers', 'Cheers!')
    )
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableScalarRequestBodiesReport)
    
    suggestions.test_cases |should| have(1).item
    suggestions.test_cases[0]['request body'] |should| equal_to(case['request body'])
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.SCALAR_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'request body': case['request body'],
            }
        ]
    })

def test_body_binary_diff():
    case, request = (
        make_case('post', '/fingerprint', data)
        for data in (b'123456789', b'123654789')
    )
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableScalarRequestBodiesReport)
    
    suggestions.test_cases |should| have(1).item
    suggestions.test_cases[0]['request body'] |should| equal_to(case['request body'])
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.SCALAR_BODY_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'request body': b64encode(case['request body']).decode('ASCII'),
                'isBase64Encoded': True,
            }
        ]
    })

def test_http_method_suggestion():
    case = make_case('post', '/foo')
    request = make_case('get', '/foo')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableHttpMethodsReport)
    
    suggestions.methods |should| equal_to({'post'})
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.KNOWN_METHODS: ['post']
    })

def test_missing_query_param():
    case = make_case('get', '/foo?bar=BQ')
    request = make_case('get', '/foo')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableQueryStringParamsetsReport)
    
    suggestions.deltas |should| have(1).item
    
    d = suggestions.deltas[0]
    d[0] |should| respond_to('params')
    d[0] |should| respond_to('mods')
    d[0].params |should| equal_to({'bar': ['BQ']})
    d[0].mods |should| equal_to(({'field': 'bar', 'add': 'BQ'},))
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.QSTRING_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.TARGET_QSPARAMS: {
                        'bar': ['BQ'],
                    },
                    'mods': (
                        {'field': 'bar', 'add': 'BQ'},
                    )
                }
            }
        ]
    })

def test_wrong_query_param_value():
    case = make_case('get', '/foo?bar=BQ')
    request = make_case('get', '/foo?bar=Cheers')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableQueryStringParamsetsReport)
    
    suggestions.deltas |should| have(1).item
    
    d = suggestions.deltas[0]
    d[0] |should| respond_to('params')
    d[0] |should| respond_to('mods')
    d[0].params |should| equal_to({'bar': ['BQ']})
    d[0].mods |should| equal_to(({'field': 'bar', 'chg': 'Cheers', 'to': 'BQ'},))
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.QSTRING_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.TARGET_QSPARAMS: {
                        'bar': ['BQ'],
                    },
                    'mods': (
                        {'field': 'bar', 'chg': 'Cheers', 'to': 'BQ'},
                    )
                }
            }
        ]
    })

def test_extra_query_param():
    case = make_case('get', '/foo?bar=BQ')
    request = make_case('get', '/foo?bar=BQ&bar=Cheers')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableQueryStringParamsetsReport)
    
    suggestions.deltas |should| have(1).item
    
    d = suggestions.deltas[0]
    d[0] |should| respond_to('params')
    d[0] |should| respond_to('mods')
    d[0].params |should| equal_to({'bar': ['BQ']})
    d[0].mods |should| equal_to(({'field': 'bar', 'del': 'Cheers'},))
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.QSTRING_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.TARGET_QSPARAMS: {
                        'bar': ['BQ'],
                    },
                    'mods': (
                        {'field': 'bar', 'del': 'Cheers'},
                    )
                }
            }
        ]
    })

def test_misordered_query_params():
    case = make_case('get', '/foo?bar=BQ&bar=Cheers')
    request = make_case('get', '/foo?bar=Cheers&bar=BQ')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableQueryStringParamsetsReport)
    
    suggestions.deltas |should| have(1).item
    
    d = suggestions.deltas[0]
    d[0] |should| respond_to('params')
    d[0] |should| respond_to('mods')
    d[0].params |should| equal_to({'bar': ['BQ', 'Cheers']})
    d[0].mods |should| equal_to(({'field': 'bar', 'add': 'BQ'}, {'field': 'bar', 'del': 'BQ'}))
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.QSTRING_DELTAS: [
            {
                JsonDescStrings.CASE_DESCRIPTION: None,
                'diff': {
                    JsonDescStrings.TARGET_QSPARAMS: {
                        'bar': ['BQ', 'Cheers'],
                    },
                    'mods': (
                        {'field': 'bar', 'add': 'BQ'},
                        {'field': 'bar', 'del': 'BQ'},
                    )
                }
            }
        ]
    })

def test_ignores_order_between_query_params():
    case = make_case('get', '/foo?bar=BQ&baz=Cheers&zapf=1')
    request = make_case('get', '/foo?baz=Cheers&bar=BQ&zapf=2')
    db = subject.Database([case])
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailableQueryStringParamsetsReport)
    
    suggestions.deltas |should| have(1).item
    
    d = suggestions.deltas[0]
    d[0] |should| respond_to('params')
    d[0] |should| respond_to('mods')
    d[0].params |should| equal_to({'zapf': ['1']})
    d[0].mods |should| equal_to(({'field': 'zapf', 'chg': '2', 'to': '1'},))
    
    # The as_jsonic_data is covered in test_wrong_query_param_value
    pass

def test_wrong_path():
    cases = [
        make_case('get', '/food/hippopatamus'),
        make_case('get', '/food'),
        make_case('get', '/food/cat'),
        make_case('get', '/food/goat'),
        make_case('get', '/food/dog'),
        make_case('get', '/food/pig'),
        make_case('get', '/food/brachiosaurus'),
    ]
    request = make_case('get', '/foo')
    db = subject.Database(cases)
    
    suggestions = db.best_matches(request)
    suggestions |should| be_instance_of(subject.AvailablePathsReport)
    
    suggestions.test_case_groups |should| have(5).items
    tcgs = suggestions.test_case_groups
    list(g[0] for g in tcgs) |should| include_all_of(c['url'] for c in cases[1:6])
    
    suggestions.as_jsonic_data() |should| equal_to({
        JsonDescStrings.GOOD_PATHS: [
            ('/food', []),
            ('/food/cat', []),
            ('/food/dog', []),
            ('/food/pig', []),
            ('/food/goat', []), # Note this is moved later in the list because of higher edit distance
        ]
    })

def test_json_exchange_get_case():
    case = {
        'method': 'get',
        'url': '/pet_name',
        'response body': 'Fluffy',
    }
    db = subject.Database([case])
    
    output = StringIO()
    db.json_exchange(json.dumps(make_case('get', '/pet_name')), output)
    output.tell() |should_not| equal_to(0)
    output.seek(0)
    result = json.load(output)
    
    result |should| contain('response status')
    list(result.items()) |should| include_all_of(case.items())

def test_json_exchange_miss_case():
    db = subject.Database([
        {
            'method': 'post',
            'url': '/pet_name',
            'response body': 'Fluffy',
        }
    ])
    
    output = StringIO()
    db.json_exchange(json.dumps(make_case('get', '/pet_name')), output)
    output.tell() |should_not| equal_to(0)
    output.seek(0)
    result = json.load(output)
    
    result |should_not| contain('response status')

def test_json_exchange_differentiate_on_addnl_field():
    cases = [
        {
            'story': "Alice's pet",
            'description': "Getting Alice's pet's name",
            'method': 'get',
            'url': '/pet_name',
            'response body': 'Fluffy',
        },
        {
            'story': "Bob's pet",
            'description': "Getting Bob's pet's name",
            'method': 'get',
            'url': '/pet_name',
            'response body': 'Max',
        },
    ]
    db = subject.Database(cases, add_request_keys=('story',))
    
    base_request = make_case('get', '/pet_name')
    def exchange_for_story(story):
        output = StringIO()
        db.json_exchange(
            json.dumps(dict(base_request, story=story)),
            output
        )
        output.tell() |should_not| equal_to(0)
        output.seek(0)
        return json.load(output)
    
    result = exchange_for_story("Alice's pet")
    result |should| contain('response status')
    result['response body'] |should| equal_to('Fluffy')
    
    result = exchange_for_story("Bob's pet")
    result |should| contain('response status')
    result['response body'] |should| equal_to('Max')
    
    result = exchange_for_story("Charlie's pet")
    result |should_not| contain('response status')
    result |should| contain(JsonDescStrings.ADDNL_FIELDS_SETS)
    result[JsonDescStrings.ADDNL_FIELDS_SETS] |should| include_all_of({'story': case['story']} for case in cases)
