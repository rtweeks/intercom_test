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

from setuptools import setup, find_packages

with open("README.md", "r") as readme:
    long_description = readme.read()

ver_info = {'__file__': 'lib/intercom_test/version.py'}
with open(ver_info['__file__']) as vf:
    exec(vf.read(), ver_info)

setup(
    name='intercom_test',
    url='https://github.com/PayTrace/intercom_test',
    version=ver_info['__version__'],
    package_dir={'': 'lib'},
    packages=find_packages('lib'),
    use_2to3=False,
    description='Inter-component testing support code for "Interface By Example"',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Richard T. Weeks',
    author_email='rtweeks21@gmail.com',
    license='Apache License 2.0',
    install_requires=[
        'PyYAML >=3.11, <6',
        'pyasn1 >=0.4.2, <1',
        'packaging >=20.8, <21',
        'python-Levenshtein >=0.12, <1',
    ],
    extras_require={
        'cli': ['docopt-subcommands>=3.0, <4', 'pick>=0.6.4, <1'],
    },
    entry_points={
        'console_scripts': [
            'icy-test = intercom_test.foreign:csmain [cli]',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3 :: Only",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Other Audience",
        "Topic :: Software Development :: Testing",
    ],
)
