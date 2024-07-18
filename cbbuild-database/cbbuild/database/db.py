"""
Collection of classes and methods to work with Couchbase Server via
the Python API
"""

import couchbase.bucket
import couchbase.exceptions

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, ClusterTimeoutOptions, QueryOptions

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

        auth = PasswordAuthenticator(db_info['username'], db_info['password'])
        self.cluster = Cluster(db_info['db_uri'], ClusterOptions(auth))
        self.bucket_name = db_info['bucket']
        self.coll = self.cluster.bucket(self.bucket_name).default_collection()

    def get_document(self, key):
        """Retrieve the document with the given key"""

        try:
            return self.coll.get(key).value
        except couchbase.exceptions.DocumentNotFoundException:
            raise NotFoundError(f'Unable to find key "{key}" in database')

    def get_build(self, product, version, bld_num):
        """Get the CouchbaseBuild object for a specific build"""

        data = self.get_document(f'{product}-{version}-{bld_num}')

        return CouchbaseBuild(self, data)

    def get_commit(self, *args):
        """
        Get the CouchbaseCommit object for a specific commit

        Either a document key itself can be passed, or a project name
        and SHA which are then combined into a document key; more than
        two arguments raises an exception
        """

        if len(args) == 1:  # Document key
            commit_key = args[0]
        elif len(args) == 2:  # Project and SHA
            commit_key = '-'.join(args)
        else:
            raise ValueError(f'Only 1 or 2 arguments can be passed: {args}')

        data = self.get_document(commit_key)

        return CouchbaseCommit(self, data)

    def query_documents(self, doctype, where_clause=None, simple=False,
                        **kwargs):
        """
        Acquire all documents of a given type and create a generator
        to loop through them

        Will return a specific object for each result based on the type
        if 'simple' is not True, else just returns the document

        Pass everything *after* the WHERE, along with any additional
        optional named parameters which will be associated with
        $variables in the query string
        """

        query = f"SELECT * FROM {self.bucket_name} where type='{doctype}'"

        if where_clause is not None:
            query += f' AND {where_clause}'

        for row in self.cluster.query(query, **kwargs):
            if simple:
                yield row[self.bucket_name]
            else:
                yield document_types[doctype](self, row[self.bucket_name])

    def get_product_version_index(self):
        """
        Retrieve the product-version index, returning an empty dict
        if it doesn't already exist
        """

        try:
            return self.coll.get('product-version-index').value
        except couchbase.exceptions.DocumentNotFoundException:
            return dict()

    def upsert_documents(self, data):
        """Do bulk insert/update of a set of documents"""

        try:
            self.coll.upsert_multi(data)
        except couchbase.exceptions.CouchbaseError as exc:
            print(f'Unable to insert/update data: {exc.message}')

    def key_in_db(self, key):
        """Simple test for checking if a given key is in the database"""

        try:
            self.coll.get(key)
            return True
        except couchbase.exceptions.DocumentNotFoundException:
            return False

    def update_product_version_index(self, prod_ver_index):
        """Update the product-version index entry"""

        self.upsert_documents({'product-version-index': prod_ver_index})


document_types = {
    'build': CouchbaseBuild,
    'commit': CouchbaseCommit,
}
