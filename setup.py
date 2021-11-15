#!/usr/bin/env python

from setuptools import find_packages
from setuptools import setup

PROJECT = 'osism'

VERSION = '0.0.1'

try:
    long_description = open('README.md', 'rt').read()
except IOError:
    long_description = ''

setup(
    name=PROJECT,
    version=VERSION,

    description='OSISM manager interface',
    long_description=long_description,

    author='Christian Berendt',
    author_email='berendt@osism.tech',

    url='https://github.com/osism/python-osism',
    download_url='https://github.com/osism/python-osism/tarball/main',

    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Intended Audience :: Developers',
        'Environment :: Console',
    ],

    platforms=['Any'],

    scripts=[],

    provides=[],
    install_requires=['cliff'],

    namespace_packages=[],
    packages=find_packages(),
    include_package_data=True,

    entry_points={
        'console_scripts': [
            'osism = osism.main:main'
        ],
        'osism.commands': [
            'beat = osism.beat:Run',
            'deploy = osism.deploy:Run',
            'flower = osism.flower:Run',
            'worker = osism.worker:Run'
        ]
    },

    zip_safe=False,
)
