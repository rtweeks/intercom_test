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

from contextlib import contextmanager, ExitStack
import enum
import functools
import inspect
import shutil
import tempfile

def def_enum(fn):
    """Decorator allowing a function to DRYly define an enumeration
    
    The decorated function should not require any arguments and should return
    an enumeration source, which will be passed to :class:`enum.Enum` along
    with the name of the decorated function.  The resulting
    :class:`enum.Enum`-derived class will be returned.
    
    The value returned by *fn* can be any kind of *source* accepted by the
    functional API of :class:`enum.Enum`.
    """
    return enum.Enum(fn.__name__, fn(), module=fn.__module__, qualname=fn.__qualname__)

@contextmanager
def open_temp_copy(path, binary=False, *, blocksize=None):
    """Make a temporary copy of *path* and return the opened file
    
    The returned file object will be opened with mode ``'w+'`` or ``'w+b'``
    (depending on *binary*) and will be positioned at the beginning of the
    file contents.  If specified, *blocksize* indicates the size of the
    buffer to use (in bytes) when making the copy.
    """
    bflag = 'b' if binary else ''
    with tempfile.TemporaryFile('w+' + bflag) as copied_file:
        with open(path, 'r' + bflag) as content:
            copy_kwargs = {}
            if blocksize is not None:
                copy_kwargs['length'] = blocksize
            shutil.copyfileobj(content, copied_file, **copy_kwargs)
        copied_file.seek(0)
        yield copied_file

class FilteredDictView:
    """:class:`dict`-like access to a key-filtered and value-transformed :class:`dict`
    
    Only _viewing_ methods are supported, not modifications.
    """
    class Keys:
        def __init__(self, dview):
            super().__init__()
            self._dkeys = dview._d.keys()
            self._dview = dview
        
        def _key_filter(self, k):
            return self._dview._key_filter(k)
        
        def __iter__(self, ):
            return (
                k for k in self._dkeys
                if self._key_filter(k)
            )
        
        def __contains__(self, k):
            return k in self._dkeys and self._key_filter(k)
        
        def __repr__(self, ):
            return "dict_keys({!r})".format(list(self))
    
    class Values:
        def __init__(self, dview):
            super().__init__()
            self._ditems = dview._d.items()
            self._dview = dview
        
        def _key_filter(self, k):
            return self._dview._key_filter(k)
        
        def _value_transform(self, v):
            return self._dview._value_transform(v)
        
        def __iter__(self, ):
            return (
                self._value_transform(v)
                for k, v in self._ditems
                if self._key_filter(k)
            )
        
        def __contains__(self, v):
            return any(cv == v for cv in self)
        
        def __repr__(self, ):
            return "dict_values({!r})".format(list(self))
    
    class Items:
        def __init__(self, dview):
            super().__init__()
            self._ditems = dview._d.items()
            self._dview = dview
        
        def _key_filter(self, k):
            return self._dview._key_filter(k)
        
        def _value_transform(self, v):
            return self._dview._value_transform(v)
        
        def __iter__(self, ):
            return (
                (k, self._value_transform(v))
                for k, v in self._ditems
                if self._key_filter(k)
            )
        
        def __contains__(self, v):
            return any(cv == v for cv in self)
        
        def __repr__(self, ):
            return "dict_items({!r})".format(list(self))
    
    def __init__(self, d, *, key_filter=None, value_transform=None):
        """
        :param d: A :class:`dict`-like object
        :keyword key_filter: A callable predicate for keys
        :keyword value_transform: A callable transform for values
        """
        super().__init__()
        self._d = d
        self._key_filter = key_filter or self._unfiltered
        self._value_transform = value_transform or self._untransformed
    
    @staticmethod
    def _unfiltered(k):
        return True
    
    @staticmethod
    def _untransformed(v):
        return v
    
    def get(self, k, defval=None):
        if k not in self._d or not self._key_filter(k):
            return defval
        return self._value_transform(self._d.get(k, defval))
    
    def __getitem__(self, k):
        if not self._key_filter(k):
            raise KeyError(k)
        return self._value_transform(self._d[k])
    
    def __contains__(self, k):
        return k in self._d and self._key_filter(k)
    
    def items(self, ):
        return self.Items(self)
    
    def keys(self, ):
        return self.Keys(self)
    
    def values(self, ):
        return self.Values(self)
    
    def __hash__(self, ):
        raise TypeError("unhashable type: '{}'".format(type(self).__qualname__))

def attributed_error(cls):
    """Expose exception instance constructor arguments (or specified names) as properties
    
    If the only purpose of the exception class constructor would be to generate
    properties from the argument names, the ``ATTRIBUTES`` attribute of the
    class can be assigned with either an iterable of :class:`str` or a single
    :class:`str` (which will be :meth:`str.split`) to more concisely specify
    the names to map to the arguments passed to the constructor.
    """
    ctor_sig = inspect.signature(cls.__init__)
    prop_names = list(
        name
        for name, arg_info
        in ctor_sig.parameters.items()
        if arg_info.kind not in (arg_info.KEYWORD_ONLY, arg_info.VAR_KEYWORD)
    )[1:]
    if len(prop_names) == 1 and ctor_sig.parameters[prop_names[0]].kind is inspect.Parameter.VAR_POSITIONAL:
        prop_names = cls.ATTRIBUTES
        if isinstance(prop_names, str):
            prop_names = prop_names.split()
        else:
            prop_names = list(prop_names)
    
    for i, prop_name in enumerate(prop_names):
        value_extractor = functools.partial(_arg_extractor, i)
        value_extractor.__doc__ = f"Index {i} argument to the constructor"
        setattr(cls, prop_name, property(value_extractor))
    
    return cls

def _arg_extractor(arg, exception):
    return exception.args[arg]

def optional_key(mapping, key):
    """Syntactic sugar for working with dict keys that *might* be present
    
    Typical usage::
    
        for value in optional_key(d, 'answer'):
            # Body executed once, with *value* assigned ``d['answer']``, if
            # *d* contains ``'answer'``.  The body of the ``for`` is not
            # executed at all, otherwise.
            print(f"The answer: {value}")
    """
    if key in mapping:
        yield mapping[key]

def complex_test_context(fn):
    """Decorator to facilitate building a test environment through context managers
    
    The callable decorated should accept a *test case* and a *context entry
    callable*.  The test case is simply passed through from the wrapper.  The
    context entry callable should be called on a context manager to enter its
    context, and all contexts will be exited in reverse order when the
    decorated function exits.  This compares to the ``defer`` statement in
    the Go programming language or ``scope(exit)`` at the function level for
    the D programming language.
    
    Example::
    
        @complex_test_context
        def around_interface_case(case, setup):
            setup(database_fixtures(case))
            setup(stubs(case))
            
            yield
    """
    @functools.wraps(fn)
    def wrapper(case):
        with ExitStack() as env:
            yield from fn(case, env.enter_context)
    
    return wrapper
