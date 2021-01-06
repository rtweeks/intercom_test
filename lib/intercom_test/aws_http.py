"""Module for adapting HTTP requests to AWS API Gateway events"""

from abc import ABC, abstractmethod
from base64 import b64encode, b64decode
import contextlib
import inspect
import json
from pathlib import Path
import subprocess as subp
from typing import Any, Callable, Optional, Union as OneOf
from urllib.parse import urlparse, parse_qsl

AwsLambdaHandler = Callable[[dict, dict], dict]

class NoRouteError(Exception):
    """Raised to indicate no route matched the given method and path"""
    def __init__(self, method: str, path: str):
        super().__init__(f"{method.upper()} {path}")
        self.method = method.upper()
        self.path = path

class HandlerMapper(ABC):
    """Abstract base class for classes that can map HTTP requests to handlers"""
    @abstractmethod
    def map(self, method: str, path: str) -> AwsLambdaHandler:
        raise Exception("pure abstract method called")

class FunctionalHandlerMapper(HandlerMapper):
    def __init__(self, mapper: Callable[[str, str], AwsLambdaHandler]):
        super().__init__()
        self._mapper = mapper
    
    def map(self, method: str, path: str) -> AwsLambdaHandler:
        return self._mapper(method, path)

class ServerlessHandlerMapper(HandlerMapper):
    PROJECT_FILE = 'serverless.yml'
    
    def __init__(self, project_dir):
        super().__init__()
        self._project_dir = Path(project_dir)
    
    def map(self, method: str, path: str) -> AwsLambdaHandler:
        if not hasattr(self, '_routing'):
            self._build_routing()
        
        for pred, handler in self._routing:
            if pred(method, path):
                return handler
        
        raise NoRoute(method, path)
    
    def case_tester(self, api_style: OneOf[str, ApiAdapter], **kwargs):
        if isinstance(api_style, str):
            api_style = globals()[f"ala_{api_style}_api"]
        
        return api_style(self, **kwargs)
    
    def _build_routing(self, ):
        """Call 'serverless print' and pull out resource-to-handler routing"""
        
        raise Exception("not implemented")

def ala_rest_api(handler_mapper: HandlerMapper, context: Optional[dict] = None, case_env=None) -> Callabe[[dict], None]:
    """Build a case tester from a :class:`HandlerMapper`
    
    :param handler_mapper: maps from method and path to an AWS Lambda handler function
    :param context: optional context information to pass to the identified handler
    :param case_env: context function for setup/teardown with access to the test case
    
    The *case_env* (if given) must be either a generator function that yields
    a single time or a callable returning a *context manager*.  If a generator
    function is given, it is converted to a context manager constructor with
    :func:`contextlib.contextmanager`.  In either case, the context manager
    constructor is invoked with the test case data :class:`dict` around
    invocation of the handler callable.
    """
    if context is None:
        context = {}
    
    if inspect.isgeneratorfunction(case_env):
        case_env = contextlib.contextmanager(case_env)
    elif case_env is None:
        if hasattr(contextlib, 'nullcontext'):
            case_env = lambda _: contextlib.nullcontext
        else:
            case_env = lambda _: contextlib.ExitStack
    
    def tester(case):
        input_key = 'AWS Lambda input'
        _rest_prep_case(case, input_key)
        
        handler = handler_mapper.map(case['method'], case['resource'])
        if hasattr(handler, 'resource'):
            case[input_key]['resource'] = handler.resource
        with case_env(case):
            handler_result = handler(case[input_key], context)
        
        # TODO: test handler_result['statusCode'] against case['response status']
        # TODO: test handler_result['mutliValueHeaders'] and/or handler_result['headers'] against case['response headers']
        _rest_test_response_body(handler_result, case['response body'])
    
    return tester

def _rest_prep_case(case: dict, aws_lambda_input_key: Any) -> None:
    url = urlparse(case['url'])
    _, stage, path = url.path.split('/', 2)
    aws_event = dict(
        requestContext=dict(
            stage=stage,
        ),
        path='/' + path,
        httpMethod=(case['method'] or 'get').lower(),
        headers={},
        multiValueHeaders={},
        isBase64Encoded=False,
    )
    if 'stageVariables' in case:
        aws_event['stageVariables'] = case['stageVariables']
    # TODO: 'resource' in case?
    if 'identity' in case:
        aws_event['requestContext']['identity'] = case['identity']
    if 'request headers' in case:
        headers = case['request headers']
        if hasattr(headers, 'items') and callable(headers.items):
            headers = headers.items()
        for name, value in headers:
            aws_event['headers'][name] = value
            aws_event['multiValueHeaders'].setdefault(name, []).append(value)
    for name, value in parse_qsl(url.query):
        aws_event['queryStringParameters'][name] = value
        aws_event['multiValueQueryStringParameters'].setdefault(name, []).append(value)
    if 'request body' in case:
        _build_aws_event_body(case['request body'], aws_event)
    
    case[aws_lambda_input_key] = aws_event

def _build_aws_event_body(request_body: OneOf[str, bytes, list, dict], aws_event) -> None:
    if isinstance(request_body, str):
        aws_event['body'] = case_request_body
    elif isinstance(request_body, bytes):
        aws_event.update(body=b64encode(request_body), isBase64Encoded=True)
    else:
        aws_event['body'] = json.dumps(request_body)
        content_type = 'application/json'
        aws_event['headers']['Content-Type'] = content_type
        aws_event['multiValueHeaders']['Content-Type'] = [content_type]

def _rest_test_response_body(handler_result: dict, expected: OneOf[str, bytes, list, dict]) -> None:
    try:
        assert isinstance(handler_result, dict), "handler result MUST be a dict"
        assert 'body' in handler_result, "handler result MUST have a 'body'"
        
        if isinstance(expected, str):
            assert handler_result['body'] == expected
        elif isinstance(expected, bytes):
            assert handler_result.get('isBase64Encoded', False), (
                "handler result was not Base64 encoded (isBase64Encoded=False) when expected body is binary data"
            )
            assert b64decode(handler_result['body']) == expected
        else:
            assert json.loads(handler_result['body']) == expected
    except AssertionError as e:
        raise UnexpectedResponse(expected) from e

"""
def around_interface_case(case: dict):
    # TODO: Set up data fixtures, service stubs, etc.
    
    yield
    
    # TODO: Tear down data fixtures, etc.

def test_entrypoints():
    case_provider = intercom_test.InterfaceCaseProvider(...)
    service = intercom_test.aws_api.ServerlessHandlerMapper('../service')
    for runner in case_provider.case_runners(service.case_tester('rest', case_env=around_interface_case)):
        yield (runner,)
"""
