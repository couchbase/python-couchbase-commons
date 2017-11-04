import fnmatch
import importlib
import os

from setuptools import setup

import cbbuild.version


# Let's add this later
# long_description = open('README.txt').read()


def discover_packages(base):
    """
    Discovers all sub-packages for a base package
    Note: does not work with namespaced packages (via pkg_resources
    or similar)
    """

    mod = importlib.import_module(base)
    mod_fname = mod.__file__
    mod_dirname = os.path.normpath(os.path.dirname(mod_fname))

    for root, _dirnames, filenames in os.walk(mod_dirname):
        for _ in fnmatch.filter(filenames, '__init__.py'):
            yield '.'.join(os.path.relpath(root).split(os.sep))


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
        if 'git+' in req and 'github' in req:  # not exactly precise...
            url, ref_egg = req.split('git+', 1)[-1].rsplit('@', 1)
            dep_links.append(url + '/tarball/' + ref_egg)

    return dep_links


DEPENDENCY_LINKS = load_github_dependency_links('requirements.txt')

setup_args = dict(
    name='cbbuild',
    version=cbbuild.version.__version__,
    description='Couchbase Build Team support Python packages',
    # long_description = long_description,
    author='Couchbase Build and Release Team',
    author_email='build-team@couchbase.com',
    license='Apache License, Version 2.0',
    packages=list(discover_packages('cbbuild')),
    install_requires=REQUIREMENTS['install'],
    dependency_links=DEPENDENCY_LINKS,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
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
