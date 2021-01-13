from intercom_test import aws_http as subject

from base64 import b64encode
import json
from pathlib import Path
from unittest.mock import patch
from should_dsl import should, should_not

def mock_run_serverless_print(self):
    return json.loads(r"""
        {
          "service": {
            "name": "sls-demo"
          },
          "frameworkVersion": "2",
          "provider": {
            "stage": "dev",
            "region": "us-east-1",
            "name": "aws",
            "runtime": "python3.8",
            "lambdaHashingVersion": "20201221",
            "versionFunctions": true,
            "variableSyntax": "\\${([^{}:]+?(?:\\(|:)(?:[^:{}][^{}]*?)?)}"
          },
          "functions": {
            "hello": {
              "handler": "test/aws_http_tests.hello",
              "events": [
                {
                  "httpApi": {
                    "path": "/greeting",
                    "method": "get"
                  }
                },
                {
                  "httpApi": "get /greeting/{subject}"
                },
                {
                  "httpApi": "post /greeting/{subject}"
                },
                {
                  "httpApi": {
                    "path": "/farewell/{proxy+}",
                    "method": "*"
                  }
                },
                {}
              ],
              "name": "test-hello"
            },
            "get_binary": {
              "handler": "test/aws_http_tests.get_binary",
              "events": [
                {
                  "httpApi": {
                    "path": "/binary_document",
                    "method": "get"
                  }
                }
              ],
              "name": "test-get_binary"
            },
            "problem_child": {
              "handler": "test/aws_http_tests.bad_responder",
              "events": [
                {
                  "httpApi": "GET /bad_response"
                }
              ],
              "name": "test-problem_child"
            },
            "simple_responder": {
              "handler": "test/aws_http_tests.simple_responder",
              "events": [
                {
                  "httpApi": "GET /simple_response"
                }
              ],
              "name": "test-simple_responder"
            }
          }
        }
    """)

mocked_serverless = patch.object(
    subject.ServerlessHandlerMapper,
    '_get_rendered_serverless_config',
    mock_run_serverless_print
)

def hello(event, context):
    body = {
        "message": "Go Serverless v1.0! Your function executed successfully!",
        "input": event
    }

    response = {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
        },
        "multiValueHeaders": {
            "X-Weird-Stuff": ['123', '456'],
        },
        "body": json.dumps(body)
    }

    return response

def get_binary(event, context):
    return {
        'statusCode': 200,
        'body': b64encode(b'123456789').decode('ASCII'),
        'isBase64Encoded': True,
    }

def bad_responder(event, context):
    return {
        'statusCode': 200,
    }

def simple_responder(event, context):
    return {'answer': 42}

@mocked_serverless
def test_unexpected_response_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    (tester, {
        'method': 'GET',
        'url': '/greeting',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
        },
    }) |should| throw(subject.UnexpectedResponseBody)

@mocked_serverless
def test_spec_missing_response_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    (tester, {
        'method': 'GET',
        'url': '/greeting',
    }) |should_not| throw(subject.UnexpectedResponseBody)
    
    (tester, {
        'method': 'GET',
        'url': '/greeting',
    }) |should| throw(Exception)
    

@mocked_serverless
def test_bad_handler_response():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    (tester, {
        'method': 'GET',
        'url': '/bad_response',
        'response body': {},
    }) |should| throw(AssertionError)

@mocked_serverless
def test_static_path():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_query_string():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting?name=Alice',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': 'name=Alice',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {
                    'name': 'Alice',
                },
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_query_string_multivalued():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting?include=food&include=wine',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': 'include=food&include=wine',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {
                    'include': 'food,wine',
                },
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_path_parameter():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting/cat',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting/cat',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting/cat',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {
                    'subject': 'cat'
                },
            },
        },
    })

@mocked_serverless
def test_vartail_path_parameter():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/farewell/cruel/world',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/farewell/cruel/world',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/farewell/cruel/world',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {
                    'proxy': 'cruel/world'
                },
            },
        },
    })

@mocked_serverless
def test_request_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'POST',
        'url': '/greeting/cat',
        'request body': {'name': 'Fluffy'},
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'post',
                        'path': '/greeting/cat',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting/cat',
                'rawQueryString': '',
                'headers': {
                    'Content-Type': 'application/json',
                },
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {
                    'subject': 'cat'
                },
                'body': '{"name": "Fluffy"}',
            },
        },
    })

@mocked_serverless
def test_binary_request_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    body = b'123456789'
    tester({
        'method': 'POST',
        'url': '/greeting/cat',
        'request body': body,
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'post',
                        'path': '/greeting/cat',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting/cat',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': True,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {
                    'subject': 'cat'
                },
                'body': b64encode(body).decode('ASCII'),
            },
        },
    })

@mocked_serverless
def test_binary_response_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    body = b'123456789'
    tester({
        'method': 'GET',
        'url': '/binary_document',
        'response body': b'123456789',
    })

@mocked_serverless
def test_unrouted():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    body = b'123456789'
    (tester, {
        'method': 'GET',
        'url': '/no-such',
        'response body': b'123456789',
    }) |should| throw(subject.NoRoute)

@mocked_serverless
def test_response_header():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting',
        'response headers': {
            'Content-Type': 'application/json',
        },
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_response_header_multivalued():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting',
        'response headers': [
            ['X-Weird-Stuff', '123'],
            ['X-Weird-Stuff', '456'],
        ],
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_response_header_multivalued_incomplete():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    (tester, {
        'method': 'GET',
        'url': '/greeting',
        'response headers': [
            ['X-Weird-Stuff', '123'],
            ['X-Weird-Stuff', '456'],
            ['X-Weird-Stuff', '789'],
        ],
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    }) |should| throw(AssertionError)

@mocked_serverless
def test_response_header_multivalued_excessive():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    (tester, {
        'method': 'GET',
        'url': '/greeting',
        'response headers': [
            ['X-Weird-Stuff', '123'],
        ],
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    }) |should| throw(AssertionError)

def test_exception_messages():
    exceptions = [
        subject.InvalidPathTemplate('/{foo}bar/baz', 6),
        subject.UnexpectedResponseBody(b'1234', b'4321'),
        subject.UnexpectedResponseBody(b'1234' * 9, b'4321' * 9),
        subject.UnexpectedResponseBody('Barbara', 'Yvonne'),
    ]
    
    def str_does_not_error(e):
        # (str, e) |should_not| throw(BaseException)
        str(e)
    
    for e in exceptions:
        yield (str_does_not_error, e)
        
def test_ServerlessHandlerMapper_project_dir_property():
    service = subject.ServerlessHandlerMapper('test')
    service.project_dir |should| be_kind_of(Path)

def test_full_proxy_routing():
    def full_proxy_routing(self):
        sls_config = mock_run_serverless_print(self)
        sls_config['functions']['hello']['events'][0]['httpApi'] = '*'
        return sls_config
    
    import sys; from IPython.core.debugger import Pdb; sys.stdout.isatty() and Pdb().set_trace()
    with patch.object(subject.ServerlessHandlerMapper, '_get_rendered_serverless_config', full_proxy_routing):
        service = subject.ServerlessHandlerMapper('test')
        service.map('patch', '/worn_pants')

class WeakOpenAPIPathMatcherTests:
    def test_path_template_segment_match_failure(self):
        (subject.OpenAPIPathMatcher, 'get', '/{foo}bar/baz') |should| throw(subject.InvalidPathTemplate)

    def test_path_nonterminal_vartail_path_template_segment(self):
        (subject.OpenAPIPathMatcher, 'get', '/{foobar+}/baz') |should| throw(subject.InvalidPathTemplate)
        

@mocked_serverless
def test_simple_handler_response():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/simple_response',
        'response body': "{\"answer\": 42}",
    })

def test_OpenAPIPathMatcher_repr():
    m = subject.OpenAPIPathMatcher('get', '/fuzzy')
    repr(m)

def test_genfunc_case_env():
    def my_case_env(case):
        yield
    
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester(case_env=my_case_env)

def test_contextmgr_case_env():
    def my_case_env(case):
        yield
    
    from contextlib import contextmanager
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester(case_env=contextmanager(my_case_env))

@mocked_serverless
def test_client_certificate():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    client_cert = {'degree': 'master clown'}
    
    tester({
        'client certificate': client_cert,
        'method': 'GET',
        'url': '/greeting',
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {
                        'clientCert': client_cert,
                    },
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_authorizer():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    authorization = {'Vinny': {'limit': 10e6}}
    
    tester({
        'method': 'GET',
        'url': '/greeting',
        'request authorization': authorization,
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': authorization,
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_request_headers():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'GET',
        'url': '/greeting',
        'request headers': {
            'X-Weird-Stuff': 'goop',
        },
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'get',
                        'path': '/greeting',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting',
                'rawQueryString': '',
                'headers': {
                    'X-Weird-Stuff': 'goop',
                },
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {},
            },
        },
    })

@mocked_serverless
def test_str_request_body():
    service = subject.ServerlessHandlerMapper('test')
    tester = service.case_tester()
    
    tester({
        'method': 'POST',
        'url': '/greeting/neighbor',
        'request body': "name=Fred",
        'response body': {
            'message': 'Go Serverless v1.0! Your function executed successfully!',
            'input': {
                'requestContext': {
                    'http': {
                        'method': 'post',
                        'path': '/greeting/neighbor',
                        'protocol': 'HTTP/1.1',
                    },
                    'authentication': {},
                    'authorizer': {},
                },
                'rawPath': '/greeting/neighbor',
                'rawQueryString': '',
                'headers': {},
                'isBase64Encoded': False,
                'stageVariables': {},
                'queryStringParameters': {},
                'pathParameters': {
                    'subject': 'neighbor',
                },
                'body': 'name=Fred',
            },
        },
    })
