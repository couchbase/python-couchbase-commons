"""
Collection of methods for using Git via Dulwich, primarily designed
for use with the build database
"""

import logging
import pathlib
import subprocess
import sys

from collections import namedtuple

import dulwich.errors

from dulwich.client import get_transport_and_path
from dulwich.porcelain import clone, open_repo_closing
from dulwich.repo import Repo


logger = logging.getLogger('cbbuild.git')
default_bytes_err_stream = getattr(sys.stderr, 'buffer', sys.stderr)


def broken_fetch(repo, remote_location, errstream=default_bytes_err_stream):
    """
    Modified form of dulwich's porcelain.fetch method which
    fetches from all remotes

    NOTE: This method is BROKEN in that is does NOT update the remotes
    in a local checkout (bare or not); recent versions of Dulwich fix
    this issue
    """

    client, path = get_transport_and_path(remote_location)
    remote_refs = client.fetch(
        path, repo,
        determine_wants=repo.object_store.determine_wants_all,
        progress=errstream.write
    )

    return remote_refs


def fetch_all(repo):
    """
    Call out to Git command to do a 'fetch --all'

    This is a (hopefully) temporary method until Dulwich's porcelain.fetch()
    actually does what is intended
    """

    subprocess.run(['git', 'fetch', '--all'], cwd=repo.path,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def checkout_repo(path, url, bare=True):
    """
    Either clones a new Git repo from URL into path (if it didn't already
    exist), or else fetches new content from URL into repo at path (if it
    did already exist). Returns a Dulwich Repo object on path.
    """

    abspath = pathlib.Path(path).resolve()
    cfgpath = abspath / ('config' if bare else '.git/config')
    abspath = str(abspath)

    if cfgpath.exists():
        logger.debug(f'Fetching {url} into {path}...')
        fetch_all(Repo(abspath))
    else:
        logger.debug(f'Cloning {url} into {path}...')
        clone(url, target=abspath, bare=bare,
              errstream=default_bytes_err_stream)

    return Repo(abspath)


def remote_add_or_update(repo, name, url):
    """
    Modified version of Dulwich's porcelain.remote_add(); adds a remote
    if it doesn't yet exist for the given repository, otherwise updates
    the URL and/or refspec if it's changed
    """

    if not isinstance(name, bytes):
        name = name.encode('utf-8')

    if not isinstance(url, bytes):
        url = url.encode('utf-8')

    with open_repo_closing(repo) as r:
        c = r.get_config()
        section = (b'remote', name)

        refspec = f'+refs/heads/*:refs/remotes/{name.decode()}/*'
        refspec = refspec.encode('utf-8')

        if c.has_section(section):
            if c.get(section, b'url') == url:
                try:
                    if c.get(section, b'fetch') == refspec:
                        return
                except KeyError:
                    # 'fetch' missing, set it in the following code
                    pass

        c.set(section, b'url', url)
        c.set(section, b'fetch', refspec)
        c.write_to_path()


class MissingCommitError(Exception):
    """Module-level exception for missing/invalid commits"""

    pass


class RepoCacheEntry:
    """Simple class to handle entries for the repository cache"""

    def __init__(self, name, directory, remotes, remote_urls):
        """Basic initialization for cache entry"""

        self.name = name
        self.directory = directory
        self.remotes = remotes
        self.urls = set(remote_urls)

    def upsert_remote(self, remote):
        """
        Add remote to the entry if it's new or update it in the entry
        """

        self.remotes[remote.name] = remote


class RepoCache:
    """
    Managed which repositories are being accessed and keep track
    to allow for caching information to avoid excess remote access
    and keep the process moving as quickly as possible
    """

    RemoteEntry = namedtuple('RemoteEntry', ['name', 'url'])

    def __init__(self):
        """Initialize the cache"""

        self.cache = dict()

    def get_remotes(self, repo):
        """Get the current set of remotes for a given repository"""

        conf = repo.get_config()
        remotes = dict()

        for key in conf.keys():
            if key[0] == b'remote':
                remote_name = key[1].decode()
                remotes[remote_name] = self.RemoteEntry(
                    remote_name, conf.get(key, b'url').decode()
                )

        return remotes

    def get_repo(self, project, repo_dir, remote, repo_url=None):
        """
        Given a project and it's repository information (checkout directory,
        remote name and URL), look at the cache and determine what needs
        to be done for the repository.

        Specifically, only fetch from the remote when needed:
          - Repository is checked out, remote URL is new
          - Repository is checked out, but not already in cache
          - Repository is not checked out (the clone essentially
            does the fetching)

        Note that fetches are not necessary each time the repository is
        accessed, as it will contain all the information needed when the
        build-manfiest repository was accessed; only remote changes and
        initial access require a fetch.

        Ensure cache is kept up to date with all changes made, and keep
        track of the remote URLs (needed to know when to do another
        fetch for the repository).
        """

        logger.debug(f'Retrieving or adding repo {project} to cache...')
        repo_dir = str(repo_dir.resolve())
        repo_exists = pathlib.Path(pathlib.Path(repo_dir) / 'config').exists()

        if repo_exists:
            logger.debug(f'    Repo {project} already exists, updating '
                         f'the cache...')
            # Repository is already checked out, so initialize connection
            # and update cache based on current cache information
            repo = Repo(repo_dir)

            if project in self.cache:
                # Repository in cache, do sanity check for repository
                # directory and remote, fetching from URL if it hasn't
                # been seen before, and updating remote information as
                # necessary
                repo_entry = self.cache[project]

                if repo_dir != repo_entry.directory:
                    raise RuntimeError(
                        f'Project directory given does not match what is '
                        f'currently in cache: '
                        f'{repo_dir} != {repo_entry.directory}'
                    )

                remotes = [remote_name for remote_name in repo_entry.remotes]

                # Ensure cache information is updated correctly for
                # given remote and URL (and make sure URL is in current
                # list of those already seen)
                if remote not in remotes:
                    logger.debug(f'    Adding remote {remote} for repo '
                                 f'{project}...')
                elif repo_url != repo_entry.remotes[remote].url:
                    logger.debug(f'    Updating URL to {repo_url} for '
                                 f'remote {remote} in repo {project}...')

                # This only changes information if anything for the
                # remote has changed; running it unconditionally is
                # safe and relatively inexpensive
                remote_add_or_update(repo_dir, remote, repo_url)

                # If we haven't seen the URL yet, fetch from URL
                if repo_url not in repo_entry.urls:
                    logger.debug(f'Fetching from remote {repo_url}...')
                    fetch_all(repo)

                # Potential no-ops, but running unconditionally is safe
                repo_entry.urls.add(repo_url)
                repo_entry.upsert_remote(self.RemoteEntry(remote, repo_url))
            else:
                # Repository needs to be added to cache, ensure URL
                # has been given, then create cache entry, update
                # remote information, then fetch from URL
                if repo_url is None:
                    raise RuntimeError(f'New project "{project}" has no '
                                       f'remote URL')

                remotes = self.get_remotes(repo)
                remote_names = [remote_name for remote_name in remotes]
                remote_urls = [remote.url for remote in remotes.values()]
                remote_urls.append(repo_url)   # Duplicating is safe here

                self.cache[project] = RepoCacheEntry(
                    remote, repo_dir, remotes, remote_urls
                )

                if remote not in remote_names:
                    logger.debug(f'    Adding remote {remote} for repo '
                                 f'{project}...')
                    self.cache[project].upsert_remote(
                        self.RemoteEntry(remote, repo_url)
                    )
                    remote_add_or_update(repo_dir, remote, repo_url)

                logger.debug(f'    Fetching remotes for {project}...')
                fetch_all(repo)
        else:
            logger.debug(f'    Repo {project} is new, cloning and adding '
                         f'to the cache...')
            # Repository has not been checked out yet, therefore
            # there will be no cache entry, so ensure URL is given,
            # set up cache entry and clone the repo, setting the
            # origin to the current remote
            if repo_url is None:
                raise RuntimeError(f'New project "{project}" has no '
                                   f'remote URL')

            remotes = {remote: self.RemoteEntry(remote, repo_url)}
            self.cache[project] = RepoCacheEntry(
                remote, repo_dir, remotes, [repo_url]
            )

            try:
                repo = clone(repo_url, target=repo_dir, bare=True,
                             errstream=default_bytes_err_stream,
                             origin=remote.encode('utf-8'))
            except dulwich.errors.HangupException:
                raise RuntimeError(
                    f'Unable to clone bare repo "{repo_url}" into directory '
                    f'{repo_dir}'
                )

        return repo


class ManifestWalker:
    """
    Walk all branches for a manifest repository and return key info
    and the contents of each commit; this walker moves forward in
    Git history
    """

    def __init__(self, manifest_dir, latest_sha):
        """Initialize the repository connection and encode latest SHAs"""

        self.repo = Repo(manifest_dir)
        self.latest_sha = [sha.encode('utf-8') for sha in latest_sha]

    def walk(self):
        """
        Find all branches and do a full walk from a given commit,
        history forward, returning key information and contents
        of each commit
        """

        branches = [
            self.repo.get_object(self.repo.refs[ref])
            for ref in self.repo.refs.keys()
            if ref.startswith(b'refs/remotes')
        ]

        walker = self.repo.get_walker(
            include=list(set([branch.id for branch in branches])),
            exclude=self.latest_sha, reverse=True
        )

        for entry in walker:
            changes = entry.changes()

            # Skip any commit that doesn't have exactly one change
            # (Zero is a merge commit, more than one is a multi-file
            # commit)
            if len(changes) != 1:
                continue

            change = changes[0]
            yield ((change.new.path, entry.commit),
                   self.repo.get_object(change.new.sha).as_pretty_string())


class CommitWalker:
    """
    Walk a given project's commit history and return key info for each
    commit; handle merges appropriately
    """

    def __init__(self, project, repo_dir, remote, repo_url, repo_cache):
        """Initialize the repository connection and set/update the cache"""

        self.repo = repo_cache.get_repo(project, repo_dir, remote, repo_url)

    def walk(self, commit_sha, cache, check_func, update_func):
        """
        Walk the commit history back starting from the given SHA
        and return key info for each commit; the functions for
        checking termination of a given walk path as well as updating
        a cache for tracking commits are passed through dynamically
        """

        commits = list()

        try:
            stack = [self.repo.get_object(commit_sha)]
        except KeyError:
            raise MissingCommitError(f'Invalid SHA: {commit_sha.decode()}')

        # Instead of using dulwich's get_walker method, use a stack
        # and manually step through the commits; this allows each one
        # to be checked on a given terminating condition to prevent
        # duplicate commits from previous builds being added
        while stack:
            node = stack.pop()

            if check_func(node, cache):
                update_func(node, cache)
                commits.append(node)
                stack.extend(
                    [self.repo.get_object(comm) for comm in node.parents]
                )

        return commits


class DiffWalker:
    """
    Handles determining which new commits occurred between two successive
    builds, taking into account possibly having no previous build
    """

    def __init__(self, repo_dir):
        """Initialize the repository connection"""

        # Making the assumption the repo is already checked out
        # at this location from previous steps
        self.repo = Repo(str(repo_dir.resolve()))

    def walk(self, old_shas, new_shas):
        """
        Walk through the set of commits between the sets of given SHAs
        to determine the new commits and return the list of the commits
        """

        try:
            walker = self.repo.get_walker(include=new_shas, exclude=old_shas)
        except dulwich.errors.MissingCommitError as exc:
            raise MissingCommitError(exc)

        return [entry.commit for entry in walker]
