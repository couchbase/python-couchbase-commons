"""
Module to allow a given Python tool the ability to check for a new
version of itself and execute that instead.  The basically enables
'auto-updating' for any tool which uses this
"""

import importlib
import os
import os.path
import pathlib
import time

import requests

from distutils.version import StrictVersion


def get_version():
    """
    Get the version of the running application

    This depends on the version.py file being available for the
    given application; without it, this method will return None
    """

    try:
        mod = importlib.import_module('version', package='.')
    except ModuleNotFoundError:
        return None

    try:
        return mod.__version__
    except AttributeError:
        return None


def check_for_new_version(tool_info, local_cache_dir):
    """
    Check S3 to see if a new version is available, and if so,
    download and run it instead (via os.execv)
    """

    tool_name, tool_version, tool_args, arch = tool_info
    tool_base_name = tool_name.replace('.exe', '')

    local_cache_version = local_cache_dir / 'current_version.txt'
    local_cache_binary = local_cache_dir / tool_name

    s3_base_dir = f'http://packages.couchbase.com/python_tools/' \
                  f'{tool_base_name}'

    # Get 'latest_version' file from S3 for tool and check it against
    # the current running version; if greater then the latter, then
    # download from S3, ensure executable permissions on Linux/macOS
    # and execv() the new binary, else touch the local version file
    # and continue with the current process
    with requests.get(f'{s3_base_dir}/latest_version.txt') as req:
        req.raise_for_status()
        latest_version = req.content.decode()

    if StrictVersion(latest_version) > StrictVersion(tool_version):
        binary_url = f'{s3_base_dir}/{tool_version}/{arch}/{tool_name}'
        with requests.get(binary_url) as req:
            req.raise_for_status()
            open(local_cache_dir / tool_name, 'w').write(req.content)

        with open(local_cache_version, 'w') as fh:
            fh.write(latest_version)

        os.chmod(local_cache_binary, 0o775)
        os.execv(local_cache_binary, tool_args)
    else:
        local_cache_version.touch(exist_ok=True)


def check_for_update(tool_info):
    """
    For a given tool, check for a new version of the tool, both in the
    local cache directory (if it exists) or on S3; if either is true,
    run the new version instead (via os.execv)
    """

    tool_name, tool_version, tool_args, _ = tool_info
    tool_base_name = tool_name.replace('.exe', '')

    local_cache_dir = pathlib.Path.home() / '.cbcache' / tool_base_name
    local_cache_version = local_cache_dir / 'current_version.txt'
    local_cache_binary = local_cache_dir / tool_name

    pathlib.Path.mkdir(local_cache_dir, parents=True)

    curr_version = tool_version

    # Check for a local version file, writing out if it doesn't yet
    # exist with the current running process' version and check for
    # new version on S3.
    #
    # If it does exist, check the last modification time; if less
    # than an hour, compare the version in the file to the current
    # version and run the cached binary if it's newer, otherwise
    # check for new version on S3.
    if not local_cache_version.exists():
        with open(local_cache_version, 'w') as fh:
            fh.write(curr_version)

        check_for_new_version(tool_info, local_cache_dir)
    else:
        try:
            mod_time = os.path.getmtime(local_cache_version)
        except OSError:
            raise PermissionError(f'Unable to access {local_cache_version}')

        elapsed = time.time() - mod_time

        if elapsed < 3600.0:
            saved_version = open(local_cache_version).read()

            if StrictVersion(saved_version) > StrictVersion(curr_version):
                os.execv(local_cache_binary, tool_args)
        else:
            check_for_new_version(tool_info, local_cache_dir)
