from setuptools import find_packages
from setuptools import setup

PROJECT = 'osism'

VERSION = '0.0.2'

try:
    long_description = open('README.md', 'rt').read()
except IOError:
    long_description = ''

setup(
    name=PROJECT,
    version=VERSION,

    description='OSISM manager interface',
    long_description=long_description,
    long_description_content_type='text/markdown',

    author='OSISM GmbH',
    author_email='info@osism.tech',

    maintainer='OSISM GmbH',
    maintainer_email='info@osism.tech',

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
            'netbox sync = osism.netbox:Sync',
            'netbox deploy= osism.netbox:Deploy',
            'reconciler = osism.reconciler:Run',
            'status = osism.status:Run',
            'watchdog = osism.watchdog:Run',
            'worker = osism.worker:Run'
        ]
    },

    zip_safe=False,
)
