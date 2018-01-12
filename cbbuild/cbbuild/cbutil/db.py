"""
Collection of classes and methods to work with Couchbase Server via
the Python API
"""

import couchbase.bucket
import couchbase.exceptions
from couchbase.n1ql import N1QLQuery

class NotFoundError(Exception):
    """Module-level exception for missing keys in database"""

    pass

class CouchbaseBuild:
    """
    Represents a Build entry in the build database
    """

    def __init__(self, db, data):
        """Constructor from dict"""

        self.__db = db
        self.__key = f'{data["key_"]}'
        self.__data = data

    def __getattr__(self, key):
        """Passes through attribute requests to underlying data"""

        return self.__data.get(key)

    def set_metadata(self, key, value):
        """
        Assigns arbitrary metadata to a build. Returns the modified
        build dictionary
        """

        self.__data.setdefault('metadata', {})[key] = value
        self.__db.upsert_documents({self.__key: self.__data})

    @property
    def key(self):
        return self.__key

class CouchbaseCommit:
    """
    Represents a Commit entry in the build database
    """

    def __init__(self, db, data):
        """Constructor from dict"""

        self.__db = db
        self.__key = f'{data["key_"]}'
        self.__data = data

    def __getattr__(self, key):
        """Passes through attribute requests to underlying data"""

        return self.__data.get(key)

    @property
    def key(self):
        return self.__key

    @property
    def project(self):
        """Computes the project name from the key"""

        return '-'.join(self.__key.split('-')[0:-1])

    @property
    def sha(self):
        """Computes the SHA from the key"""

        return self.__key.split('-')[-1]

class CouchbaseDB:
    """
    Manage connection and access to a Couchbase Server database,
    with some specific methods for the build database (dealing
    with the product-version index key)
    """

    def __init__(self, db_info):
        """Set up connection to desired Couchbase Server bucket"""

        self.bucket = couchbase.bucket.Bucket(
            db_info['db_uri'], username=db_info['username'],
            password=db_info['password']
        )

    def get_build(self, product, version, bld_num):
        """Get the CouchbaseBuild object for a specific build"""

        data = self.get_document(f'{product}-{version}-{bld_num}')
        return CouchbaseBuild(self, data)

    def query_builds(self, where_clause, **kwargs):
        """
        Uses a N1QL query to return a list of CouchbaseBuild objects.
        Pass everything *after* the WHERE. You may also pass additional
        named parameters which will be associated with $variables in
        the query string.
        """
        query = N1QLQuery(
            f"SELECT * FROM build_info WHERE type='build' AND {where_clause}",
            **kwargs
        )
        return [
            CouchbaseBuild(self, row["build_info"])
            for row in self.bucket.n1ql_query(query)
        ]

    def get_commit(self, project, sha):
        """Get the CouchbaseCommit object for a specific commit"""

        return self.get_commit(f'{project}-{sha}')

    def get_commit(self, commit_key):
        """Get the CouchbaseCommit object for a specific commit, by key"""

        data = self.get_document(commit_key)
        return CouchbaseCommit(self, data)

    def query_commits(self, where_clause, **kwargs):
        """
        Uses a N1QL query to return a list of CouchbaseCommit objects.
        Pass everything *after* the WHERE. You may also pass additional
        named parameters which will be associated with $variables in
        the query string.
        """
        query = N1QLQuery(
            f"SELECT * FROM build_info WHERE type='commit' AND {where_clause}",
            **kwargs
        )
        return [
            CouchbaseCommit(self, row["build_info"])
            for row in self.bucket.n1ql_query(query)
        ]

    def get_document(self, key):
        """Retrieve the document with the given key"""

        try:
            return self.bucket.get(key).value
        except couchbase.exceptions.NotFoundError:
            raise NotFoundError(f'Unable to find key "{key}" in database')

    def get_product_version_index(self):
        """
        Retrieve the product-version index, returning an empty dict
        if it doesn't already exist
        """

        try:
            return self.bucket.get('product-version-index').value
        except couchbase.exceptions.NotFoundError:
            return dict()

    def upsert_documents(self, data):
        """Do bulk insert/update of a set of documents"""

        try:
            self.bucket.upsert_multi(data)
        except couchbase.exceptions.CouchbaseError as exc:
            print(f'Unable to insert/update data: {exc.message}')

    def key_in_db(self, key):
        """Simple test for checking if a given key is in the database"""

        try:
            self.bucket.get(key)
            return True
        except couchbase.exceptions.NotFoundError:
            return False

    def update_product_version_index(self, prod_ver_index):
        """Update the product-version index entry"""

        self.upsert_documents({'product-version-index': prod_ver_index})
