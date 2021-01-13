"""Module for adapting HTTP requests to AWS API Gateway events"""

from abc import ABC, abstractmethod
from base64 import b64encode, b64decode
from collections import Counter
from collections.abc import Mapping
import contextlib
import importlib
import inspect
import json
from pathlib import Path
import re
import subprocess as subp
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union as OneOf
from urllib.parse import urlparse, parse_qsl, ParseResult as ParsedUrl
from intercom_test.utils import attributed_error, optional_key

AwsLambdaHandler = Callable[[dict, dict], dict]
ApiAdapter = Callable

@attributed_error
class NoRoute(Exception):
    """Raised when no route matched the given method and path"""
    
    ATTRIBUTES = 'method path'
    
    def __str__(self, ):
        return "{} {}".format(self.method, self.path)

@attributed_error
class InvalidPathTemplate(Exception):
    """Raised when an invalid routing path template"""
    
    ATTRIBUTES = 'path_template error_index'
    
    def __str__(self, ):
        return "invalid template syntax at character index {i} of {tmplt}".format(
            i=self.error_index,
            tmplt=self.path_template
        )

@attributed_error
class UnexpectedResponseBody(AssertionError):
    """Raised when the expected HTTP response was not generated"""
    
    ATTRIBUTES = 'actual expected'
    
    def __str__(self):
        actual = self._format_body(self.actual)
        expected = self._format_body(self.expected)
        
        return "\n    ----- ACTUAL -----\n{actual}\n\n    ----- EXPECTED -----\n{expected}".format(
            actual=actual,
            expected=expected,
        )
    
    @classmethod
    def _format_body(cls, body, indent=4):
        if isinstance(body, str):
            body = json.dumps(body)
        elif isinstance(body, bytes):
            content = ' '.join("%02x" % b for b in body)
            if len(content) > 100:
                content = content[:97] + '...'
            body = "<(binary) {content}>".format(content=content)
        else:
            body = json.dumps(body, indent=4)
        
        return ('\n' + body).replace('\n', '\n' + (indent * ' '))

class HandlerMapper(ABC):
    """Abstract base class for classes that can map HTTP requests to handlers"""
    @abstractmethod
    def map(self, method: str, path: str) -> AwsLambdaHandler: # pragma: no cover
        """Given an HTTP method and request path, return a handler function"""
        raise Exception("pure abstract method called")

class FunctionalHandlerMapper(HandlerMapper):
    """Adapter class to convert a mapper function to a :class:`HandlerMapper`"""
    def __init__(self, mapper: Callable[[str, str], AwsLambdaHandler]):
        super().__init__()
        self._mapper = mapper
    
    def map(self, method: str, path: str) -> AwsLambdaHandler:
        return self._mapper(method, path)

class ServerlessHandlerMapper(HandlerMapper):
    """A :class:`HandlerMapper` drawing information from a Serverless project config
    
    :param project_dir: root directory of the Serverless project
    
    The typical usage of this class is with :class:`~intercom_test.framework.InterfaceCaseProvider`,
    as::
    
        import intercom_test.aws_http
        
        def around_interface_case(case: dict):
            # Some kind of setup, possibly using *case*
            try:
                yield
            finally:
                # The corresponding teardown
        
        def test_interface_entrypoints():
            case_provider = intercom_test.InterfaceCaseProvider(<args>)
            service = intercom_test.aws_http.ServerlessHandlerMapper(<path-to-serverless-project>)
            for test_runner in case_provider.case_runners(
                service.case_tester(case_env=around_interface_case)
            ):
                yield (test_runner,)
    """
    
    config_file = 'serverless.yml'
    
    def __init__(self, project_dir: OneOf[str, Path]):
        """Construct an instance"""
        super().__init__()
        self._project_dir = Path(project_dir)
    
    @property
    def project_dir(self) -> Path:
        """Directory of the project"""
        return self._project_dir
    
    def map(self, method: str, path: str) -> AwsLambdaHandler:
        """Use routing defined in the Serverless config to map a handler"""
        if not hasattr(self, '_routing'):
            self._build_routing()
        
        for path_param_parser, handler in self._routing:
            path_params = path_param_parser(method, path)
            if path_params is not None:
                # Integrate path_params into the event dict passed to handler under the key "pathParameters"
                return lambda event, context: handler(
                    dict(event, pathParameters=path_params),
                    context
                )
        
        raise NoRoute(method, path)
    
    def case_tester(self, api_style: Optional[ApiAdapter] = None, **kwargs) -> Callable[[dict], None]:
        """Convenience method for applying the HTTP API event adapter/testing logic
        
        The result of this method is intended to be passed to
        :meth:`intercom_test.framework.InterfaceCaseProvider.case_runners`.
    
        See :class:`.HttpCasePreparer` and :class:`.CasePreparer` for
        information on keys of the test case that are consulted in constructing
        the Lambda Function input event.  See :func:`.confirm_expected_response`
        for information on keys of the test case consulted when evaluating the 
        Lambda Function response.
        """
        if api_style is None:
            api_style = ala_http_api
        
        return api_style(self, **kwargs)
    
    def _build_routing(self, ) -> None:
        """Call 'serverless print' and pull out resource-to-handler routing"""
        
        serverless = self._get_rendered_serverless_config()
        
        routing = []
        for fn_info in serverless['functions'].values():
            routing.extend(_serverless_function_routes(fn_info))
        # Sort routes (literals have precedence over params)
        routing.sort(key=_routing_entry_sort_key)
        self._routing = routing
    
    def _get_rendered_serverless_config(self, ) -> dict: # pragma: no cover
        # This method invokes the "serverless" program; it can be overridden for testing
        return json.loads(subp.check_output(
            ['serverless', 'print', '--format', 'json', '--config', self.config_file],
            cwd=self._project_dir,
        ))

def _serverless_function_routes(fn_info: dict):
    # Generate (request_matcher, handler) pairs for a value in the 'functions'
    # dict from a Serverless config
    module_name, fn_name = fn_info['handler'].rsplit('.', 1)
    module_name = module_name.replace('/', '.')
    module = importlib.import_module(module_name)
    
    for method, path_template in _httpApi_routes(fn_info['events']):
        handler = getattr(module, fn_name)
        handler = LambdaHandlerProxy(handler, resource=path_template)
        yield (OpenAPIPathMatcher(method, path_template), handler)

def _httpApi_routes(event_list: list):
    # Generate (method, path_template) pairs from an 'events' entry under an
    # entry of 'functions' in a Serverless config
    for entry in event_list:
        http_event = entry.get('httpApi')
        if http_event is None:
            continue
        
        if http_event == '*':
            http_event = '* /{proxy+}'
        
        if isinstance(http_event, str):
            method, path_template = http_event.split(maxsplit=1)
            method = method.lower()
            yield (method, path_template)
        else:
            yield (http_event['method'], http_event['path'])

# TODO: This implementation of OpenAPIPathMatcher restricts parameters to
# segments between slashes, which is more restrictive than the OpenAPI
# specification; fix to remove this restriction
PATH_TEMPLATE_SEGMENT = re.compile(r'/(?:(?:\{(?P<param>[^}]+)\})|(?P<lit>(?!\{)[^/]+))')
PATH_SEGMENT = re.compile(r'/(?P<value>[^/]+)')
class OpenAPIPathMatcher:
    """A callable class to match and extract parameters from a URL path
    
    :param route_method:
        HTTP method or ``'*'`` for a wildcard
    :param route_path:
        path part of a URL to match, which may include OpenAPI template
        parameters
    
    Instances accept a call with an HTTP method and a URL path-part and return
    either ``None`` for no match, or a :class:`dict` mapping path parameter
    names to their extracted values.  A returned mapping may be empty, so be
    sure to use the ``is not None`` test instead of implicit conversion to
    :class:`bool`.
    
    NOTE: With the current implementation, template parameters are only
    allowed to match a full segment of the path (between slashes or from
    a slash to the end of the path).
    """
    
    class Param(str):
        """String giving the name of a path parameter"""

        @property
        def isvartail(self):
            return self.endswith('+')

    def __init__(self, route_method: str, route_path: str):
        """Construct an instance"""
        super().__init__()
        self.method = route_method

        self.path = route_path
        self.path_segments = []
        match_start = 0
        while match_start < len(route_path):
            seg = PATH_TEMPLATE_SEGMENT.match(route_path, match_start)
            if seg is None:
                raise InvalidPathTemplate(route_path, match_start)
            if seg.group('param'):
                param = self.Param(seg.group('param'))
                if param.isvartail and seg.span()[1] < len(route_path):
                    raise InvalidPathTemplate(route_path, seg.span()[1])
                self.path_segments.append(param)
            elif seg.group('lit'):
                self.path_segments.append(seg.group('lit'))
            else: # pragma: no cover
                raise Exception("unknown path segment type for {!r}".format(seg.group()))
            match_start = seg.span()[1]

    def __call__(self, request_method: str, request_path: str) -> Optional[dict]:
        """See class documentation"""
        if self.method != '*' and request_method != self.method:
            return None

        template_segments = list(self.path_segments)
        match_start = 0
        captured_params = {}
        for template_seg in template_segments:
            matching_param = isinstance(template_seg, self.Param)

            if matching_param and template_seg.isvartail:
                captured_params[template_seg[:-1]] = request_path[match_start + 1:]
                match_start = len(request_path)
                continue

            request_seg = PATH_SEGMENT.match(request_path, match_start)
            if request_seg is None:
                return None
            if matching_param:
                captured_params[template_seg[:]] = request_seg.group('value')
            elif request_seg.group('value') != template_seg:
                return None

            match_start = request_seg.span()[1]

        if match_start < len(request_path):
            return None

        return captured_params

    def __repr__(self, ):
        return "<{} method={!r} path={!r}>".format(
            type(self).__name__,
            self.method,
            self.path,
        )


def _routing_entry_sort_key(route_entry: Tuple[OpenAPIPathMatcher, AwsLambdaHandler]) -> Tuple[Tuple[int, str], ...]:
    path_segs = route_entry[0].path_segments
    
    def seg_sort_key(seg):
        is_param = isinstance(seg, OpenAPIPathMatcher.Param)
        return (
            1 if is_param else 0,
            '' if is_param else seg,
        )
    
    return tuple(seg_sort_key(seg) for seg in path_segs)

class LambdaHandlerProxy:
    """Wrapper for a Lambda handler allowing decoration with additional attributes
    
    A single handler function may be bound to multiple integrations, and the
    information relevant to that binding may be useful or needed for constructing
    the event to send to the handler.
    """
    def __init__(self, handler: AwsLambdaHandler, *, resource: Optional[str] = None):
        super().__init__()
        self.handler = handler
        self.resource = resource
    
    def __call__(self, *args, **kwargs):
        return self.handler(*args, **kwargs)
    
    def __repr__(self, ):
        parts = [
            type(self).__name__,
            "for {}.{}".format(self.handler.__module__, self.handler.__qualname__)
        ]
        if self.resource:
            parts.append("(mapped from {!r})".format(self.resource))
        return "<{}>".format(' '.join(parts))

def ala_rest_api(handler_mapper: HandlerMapper, context: Optional[dict] = None, case_env=None) -> Callable[[dict], None]:
    """Build a case tester from a :class:`HandlerMapper` for a REST API
    
    :param handler_mapper: maps from method and path to an AWS Lambda handler function
    :param context: optional context information to pass to the identified handler
    :param case_env: context function for setup/teardown with access to the test case
    
    The *case_env* (if given) must be either a generator function that yields
    a single time or a callable returning a *context manager*.  If a generator
    function is given, it is converted to a context manager constructor with
    :func:`contextlib.contextmanager`.  In either case, the context manager
    constructor is invoked with the test case data :class:`dict` around
    invocation of the handler callable.
    
    See :class:`.RestCasePreparer` and :class:`.CasePreparer` for
    information on keys of the test case that are consulted in constructing
    the Lambda Function input event.
    """
    if context is None:
        context = {}
    
    case_env = _case_env_contextmanager(case_env)
    
    def tester(case):
        input_key = 'AWS Lambda input'
        case[input_key] = RestCasePreparer(case).lambda_input()
        
        handler = handler_mapper.map(
            case[input_key]['httpMethod'],
            case[input_key]['path']
        )
        if hasattr(handler, 'resource'):
            case[input_key]['resource'] = handler.resource
        with case_env(case):
            handler_result = handler(case[input_key], context)
        
        confirm_expected_response(handler_result, case)
    
    return tester

def ala_http_api(handler_mapper: HandlerMapper, context: Optional[dict] = None, case_env=None) -> Callable[[dict], None]:
    """Build a case tester from a :class:`HandlerMapper` for an HTTP API
    
    :param handler_mapper: maps from method and path to an AWS Lambda handler function
    :param context: optional context information to pass to the identified handler
    :param case_env: context function for setup/teardown with access to the test case
    
    The *case_env* (if given) must be either a generator function that yields
    a single time or a callable returning a *context manager*.  If a generator
    function is given, it is converted to a context manager constructor with
    :func:`contextlib.contextmanager`.  In either case, the context manager
    constructor is invoked with the test case data :class:`dict` around
    invocation of the handler callable.
    
    See :class:`.HttpCasePreparer` and :class:`.CasePreparer` for
    information on keys of the test case that are consulted in constructing
    the Lambda Function input event.  See :func:`.confirm_expected_response`
    for information on keys of the test case consulted when evaluating the 
    Lambda Function response.
    """
    if context is None:
        context = {}
    
    case_env = _case_env_contextmanager(case_env)
    
    def tester(case):
        input_key = 'AWS Lambda input'
        case[input_key] = HttpCasePreparer(case).lambda_input()
        
        handler = handler_mapper.map(
            case[input_key]['requestContext']['http']['method'],
            case[input_key]['rawPath']
        )
        with case_env(case):
            handler_result = handler(case[input_key], context)
        
        handler_result = _http_conformed_result(handler_result)
        
        confirm_expected_response(handler_result, case)
    
    return tester

def _http_conformed_result(result: OneOf[Mapping, str, Iterable]) -> dict:
    """Apply HTTP API v2.0 Lambda function output rules"""
    
    if isinstance(result, Mapping) and 'statusCode' in result:
        return result if isinstance(result, dict) else dict(result)
    
    if not isinstance(result, str):
        result = json.dumps(result)
    
    return dict(
        isBase64Encoded=False,
        statusCode=200,
        body=result,
        headers={
            "Content-Type": "application/json",
        },
    )

def _case_env_contextmanager(case_env):
    if case_env is None:
        return lambda _: _nullcontext()
    
    if not inspect.isgeneratorfunction(case_env):
        return case_env
    
    return contextlib.contextmanager(case_env)

class CasePreparer:
    """Common base class for building an AWS API Gateway event for a Lambda Function
    
    :param case: test case data
    
    The following keys in *case* are consulted when generating the Lambda
    Function input value (:meth:`.lambda_input`):
    
    ``'method'``
        (:class:`str`, **required**) The HTTP method
    
    ``'url'``
        (:class:`str`, **required**) The path part of the URL
    
    ``'stageVariables'``
        (:class:`dict`) Mapping of stage variables to their values
    
    ``'request headers'``
        (:class:`dict` or list of 2-item lists) HTTP headers for request
    
    ``'request body'``
        A :class:`str`, :class:`bytes`, or JSONic data type giving the body
        of the request to test; JSONic data is rendered to JSON for submission
        and implies a ``Content-Type`` header of ``'application/json'``
    
    Subclasses may also consult additional keys in *case*; see the
    documentation of the subclass.
    """
    def __init__(self, case: Mapping):
        """Construct an instance"""
        super().__init__()
        self._case = case
    
    @property
    def method(self) -> str:
        """HTTP method of the test case"""
        return self._case.get('method', 'get').lower()
    
    @property
    def url(self) -> ParsedUrl:
        """URL of the test case"""
        if not hasattr(self, '_url'):
            self._url = urlparse(self._case['url'])
        return self._url
    
    def lambda_input(self, ) -> dict:
        """Get the Lambda Function input for the test case"""
        if not hasattr(self, '_event'):
            self._build_event()
        
        return self._event
    
    def _build_event(self, ):
        self._event = event = self._get_base_fields()
        for vars in self._if_given('stageVariables'):
            event['stageVariables'] = vars
        self._incorporate_authorization()
        self._incorporate_qsparams()
        self._incorporate_headers()
        for body in self._if_given('request body'):
            _build_aws_event_body(body, event)
    
    def _incorporate_authorization(self, ): # pragma: no cover
        # Subclass can skip implementing this if desired
        pass
    
    def _if_given(self, key):
        # Use this like:
        #
        #     for vars in self._if_given('stageVariables'):
        #         <body to execute if 'stageVariables' is present in test case data>
        
        return optional_key(self._case, key)

class RestCasePreparer(CasePreparer):
    """Prepare Lambda Function input event for REST API
    
    :param case: test case data
    
    In addition to the keys listed in base class :class:`CasePreparer`, this
    class also consults the following optional keys of *case* when building the
    Lambda Function input:
    
    ``'identity'``
        (:class:`dict`) Client identity information used to populate
        ``$.requestContext.identity``
    """
    
    def _get_base_fields(self, ):
        case = self._case
        _, stage, path = self.url.path.split('/', 2)
        return dict(
            requestContext=dict(
                stage=stage,
            ),
            stageVariables={},
            path='/' + path,
            httpMethod=self.method,
            queryStringParameters={},
            multiValueQueryStringParameters={},
            headers={},
            multiValueHeaders={},
            isBase64Encoded=False,
        )
    
    def _incorporate_authorization(self, ):
        for identity in self._if_given('identity'):
            self._event['requestContext']['identity'] = identity
    
    def _incorporate_qsparams(self, ):
        self._capture_named(
            'queryStringParameters',
            'multiValueQueryStringParameters',
            parse_qsl(self.url.query)
        )
    
    def _incorporate_headers(self, ):
        for headers in self._if_given('request headers'):
            if hasattr(headers, 'items') and callable(headers.items):
                headers = headers.items()
            
            self._capture_named(
                'headers',
                'multiValueHeaders',
                headers
            )
    
    def _capture_named(self, last_values_key, multi_values_key, name_value_pairs):
        last_values = self._event[last_values_key]
        multi_values = self._event[multi_values_key]
        
        for name, value in name_value_pairs:
            last_values[name] = value
            multi_values.setdefault(name, []).append(value)

class HttpCasePreparer(CasePreparer):
    """Prepare Lambda Function input event for HTTP API
    
    :param case: test case data
    
    In addition to the keys listed in base class :class:`CasePreparer`, this
    class also consults the following optional keys of *case* when building the
    Lambda Function input:
    
    ``'client certificate'``
        (:class:`dict`) The field of the client certificate provided for the
        test, to populate ``$.requestContext.authentication.clientCert``
    
    ``'request authorization'``
        (:class:`dict`) Used to populate ``$.requestContext.authorizer``
    """
    
    def _get_base_fields(self, ):
        case = self._case
        return dict(
            requestContext=dict(
                http=dict(
                    method=self.method,
                    path=self.url.path,
                    protocol='HTTP/1.1',
                ),
                authentication={},
                authorizer={},
            ),
            stageVariables={},
            rawPath=self.url.path,
            rawQueryString=self.url.query,
            queryStringParameters={},
            headers={},
            isBase64Encoded=False,
        )
    
    def _incorporate_authorization(self, ):
        for certificate in self._if_given('client certificate'):
            self._event['requestContext']['authentication']['clientCert'] = certificate
        for authorization in self._if_given('request authorization'):
            self._event['requestContext']['authorizer'] = authorization
    
    def _incorporate_qsparams(self, ):
        event_qsparams = self._event['queryStringParameters']
        for name, value in parse_qsl(self.url.query):
            self._accum_multivalue(event_qsparams, name, value)
    
    def _incorporate_headers(self, ):
        for headers in self._if_given('request headers'):
            if hasattr(headers, 'items') and callable(headers.items):
                headers = headers.items()
            event_headers = self._event['headers']
            for name, value in headers:
                # TODO: Special case for cookies
                self._accum_multivalue(event_headers, name, value)
    
    def _accum_multivalue(self, d, key, value):
        if key in d:
            d[key] += ',' + str(value)
        else:
            d[key] = value

def _build_aws_event_body(request_body: OneOf[str, bytes, list, dict], aws_event: dict) -> None:
    """Modify the AWS Lambda input event based on request body
    
    The type of *request_body* determines how the body is represented in
    *aws_event*.  The ``'body'`` and ``'isBase64Encoded'`` keys of *aws_event*
    and the ``'Content-Type'`` subkey of ``aws_event['headers']`` and
    ``aws_event['multiValueHeaders']`` may be assigned, depending on the
    data in *request_body*.
    
    When this function is called, *aws_event* is expected to *not* have any
    request-body-related information set.
    """
    if isinstance(request_body, str):
        aws_event['body'] = request_body
    elif isinstance(request_body, bytes):
        aws_event.update(body=b64encode(request_body).decode('ASCII'), isBase64Encoded=True)
    else:
        aws_event['body'] = json.dumps(request_body)
        content_type = 'application/json'
        aws_event['headers']['Content-Type'] = content_type
        if 'multiValueHeaders' in aws_event:
            aws_event['multiValueHeaders']['Content-Type'] = [content_type]

def confirm_expected_response(handler_result: dict, case: dict) -> None:
    """Confirm that the (normalized) output of the handler meets case expectations
    
    :param handler_result: result from the Lambda Function handler
    :param case: the test case data
    
    Normalization of the handler function output *does not occur* in this
    function; normalize *handler_result* before passing it in.
    
    The following keys in *case* are consulted when evaluating the Lambda
    Function response:
    
    ``'response status'``
        (:class:`int`) The HTTP response status code number expected, defaulting
        to 200
    
    ``'response headers'``
        (:class:`dict` or list of 2-item lists) HTTP headers required in the
        response; if a header is listed here and is returned as a multi-value
        header (in ``'multiValueHeaders'``), the *set* of values in the
        response is expected to match the *set* of values listed here in the
        test case
    
    ``'response body'``
        (**required**) A :class:`str`, :class:`bytes`, or JSONic data type
        giving the expected body of the response; JSONic data is compared
        against the response by parsing the body of the response as JSON, then
        comparing to the data given here in the test case
    """
    _confirm_response_code(
        handler_result['statusCode'],
        case.get('response status', 200)
    )
    for expected_headers in optional_key(case, 'response headers'):
        _confirm_response_headers(
            handler_result.get('headers', {}),
            handler_result.get('multiValueHeaders', {}),
            expected_headers
        )
    _confirm_response_body(handler_result, case['response body'])

def _confirm_response_code(actual: int, expected: int) -> None:
    assert actual == expected, (
        "expected HTTP response code {expected}, but got {actual}".format(
            expected=expected,
            actual=actual,
        )
    )

def _confirm_response_headers(actual_headers: Dict[str, str], actual_mv_headers: Dict[str, Iterable[str]], expected_headers: OneOf[Dict[str, str], Iterable[Tuple[str, str]]]):
    if hasattr(expected_headers, 'items'):
        expected_headers = expected_headers.items()
    
    errors = []
    mv_header_counts = Counter()
    for name, value in expected_headers:
        if name in actual_headers and actual_headers[name] == value:
            pass
        elif name in actual_mv_headers and value in actual_mv_headers[name]:
            mv_header_counts[name] += 1
        else:
            errors.append(
                "header {name!r} not found with value {value!r}".format(
                    name=name,
                    value=value,
                )
            )
    
    for name, expected_count in mv_header_counts.items():
        if name not in actual_headers:
            pass
        elif actual_headers[name] not in actual_mv_headers[name]:
            expected_count -= 1
        
        actual_count = len(actual_mv_headers[name])
        if actual_count != expected_count:
            errors.append(
                "multi-valued header {name!r} appeared with {actual_count} value(s), but expected {expected_count}".format(
                    name=name,
                    actual_count=actual_count,
                    expected_count=expected_count,
                )
            )
    
    if len(errors) == 1:
        raise AssertionError(errors[0])
    if errors:
        raise AssertionError('\n    * '.join(['multiple errors'] + errors))

def _confirm_response_body(handler_result: dict, expected: OneOf[str, bytes, list, dict]) -> None:
    actual = None
    try:
        assert isinstance(handler_result, dict), "handler result MUST be a dict"
        assert 'body' in handler_result, "handler result MUST have a 'body'"
        
        if isinstance(expected, str):
            actual = handler_result['body']
            assert handler_result['body'] == expected
        elif isinstance(expected, bytes):
            assert handler_result.get('isBase64Encoded', False), (
                "handler result was not Base64 encoded (isBase64Encoded=False) when expected body is binary data"
            )
            actual = b64decode(handler_result['body'])
            assert b64decode(handler_result['body']) == expected
        else:
            actual = json.loads(handler_result['body'])
            assert json.loads(handler_result['body']) == expected
    except AssertionError as e:
        if actual is None:
            raise e
        raise UnexpectedResponseBody(actual, expected).with_traceback(e.__traceback__) from e

# Fallback for Python < 3.7
_nullcontext = getattr(contextlib, 'nullcontext', contextlib.ExitStack)
