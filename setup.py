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
            'apply = osism.apply:Run',
            'beat = osism.beat:Run',
            'flower = osism.flower:Run',
            'netbox = osism.netbox:Run',
            'netbox connect = osism.netbox:Connect',
            'netbox disable = osism.netbox:Disable',
            'netbox generate = osism.netbox:Generate',
            'netbox import = osism.netbox:Import',
            'netbox init = osism.netbox:Init',
            'netbox manage = osism.netbox:Manage',
            'reconciler = osism.reconciler:Run',
            'watchdog = osism.watchdog:Run',
            'worker = osism.worker:Run'
        ]
    },

    zip_safe=False,
)
