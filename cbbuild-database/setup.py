import fnmatch
import importlib
import os

from setuptools import setup

import version


# Let's add this later
# long_description = open('README.txt').read()


def reqfile_read(fname):
    with open(fname, 'r') as reqfile:
        reqs = reqfile.read()

    return filter(None, reqs.strip().splitlines())


def load_requirements(fname):
    requirements = list()

    for req in reqfile_read(fname):
        if 'git+' in req:
            req = '>='.join(req.rsplit('=')[-1].split('-', 3)[:2])
        if req.startswith('--'):
            continue
        requirements.append(req)

    return requirements


REQUIREMENTS = dict()
REQUIREMENTS['install'] = load_requirements('requirements.txt')


def load_github_dependency_links(fname):
    dep_links = list()

    for req in reqfile_read(fname):
        if 'git+' in req and 'github' in req:  # Not exactly precise...
            dep_links.append(req)

    return dep_links


DEPENDENCY_LINKS = load_github_dependency_links('requirements.txt')

setup_args = dict(
    name='cbbuild-database',
    version=version.__version__,
    description='Couchbase Build Team support Python database package',
    # long_description = long_description,
    author='Couchbase Build and Release Team',
    author_email='build-team@couchbase.com',
    license='Apache License, Version 2.0',
    packages=['cbbuild.database'],
    zip_safe=False,
    install_requires=REQUIREMENTS['install'],
    dependency_links=DEPENDENCY_LINKS,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)

if __name__ == '__main__':
    setup(**setup_args)
