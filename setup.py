from setuptools import find_packages
from setuptools import setup

PROJECT = 'osism'
exec(open(f'{PROJECT}/version.py').read())

try:
    long_description = open('README.md', 'rt').read()
except IOError:
    long_description = ''

setup(
    name=PROJECT,
    version=__version__,  # noqa

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
            'apply = osism.commands.apply:Run',
            'bifrost = osism.commands.bifrost:Run',
            'bifrost deploy = osism.commands.bifrost:Deploy',
            'compose = osism.commands.compose:Run',
            'console = osism.commands.console:Run',
            'container = osism.commands.container:Run',
            'netbox = osism.commands.netbox:Run',
            'netbox check = osism.commands.netbox:Check',
            'netbox connect = osism.commands.netbox:Connect',
            'netbox deploy= osism.commands.netbox:Deploy',
            'netbox diff = osism.commands.netbox:Diff',
            'netbox disable = osism.commands.netbox:Disable',
            'netbox generate = osism.commands.netbox:Generate',
            'netbox import = osism.commands.netbox:Import',
            'netbox init = osism.commands.netbox:Init',
            'netbox manage = osism.commands.netbox:Manage',
            'netbox ping = osism.commands.netbox:Ping',
            'netbox sync = osism.commands.netbox:Sync',
            'netbox sync bifrost = osism.commands.netbox:Bifrost',
            'netbox sync ironic = osism.commands.netbox:Ironic',
            'reconciler = osism.commands.reconciler:Run',
            'reconciler sync = osism.commands.reconciler:Sync',
            'revoke = osism.commands.revoke:Run',
            'service = osism.commands.service:Run',
            'status = osism.commands.status:Run',
            'worker = osism.commands.worker:Run'
        ]
    },

    zip_safe=False,
)
