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
            'beat = osism.services.beat:Run',  # deprecated in favor of service
            'flower = osism.services.flower:Run',  # deprecated in favor of service
            'netbox = osism.netbox:Run',
            'netbox connect = osism.netbox:Connect',
            'netbox deploy= osism.netbox:Deploy',
            'netbox disable = osism.netbox:Disable',
            'netbox generate = osism.netbox:Generate',
            'netbox import = osism.netbox:Import',
            'netbox init = osism.netbox:Init',
            'netbox manage = osism.netbox:Manage',
            'netbox sync = osism.netbox:Sync',
            'reconciler = osism.reconciler:Run',
            'service = osism.service:Run',
            'status = osism.status:Run',
            'watchdog = osism.services.watchdog:Run',  # deprecated in favor of service
            'worker = osism.worker:Run'
        ]
    },

    zip_safe=False,
)
