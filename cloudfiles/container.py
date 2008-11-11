"""
container operations

Containers are storage compartments where you put your data (objects).
A container is similar to a directory or folder on a conventional filesystem
with the exception that they exist in a flat namespace, you can not create
containers inside of containers.

See COPYING for license information.
"""

from storage_object import Object, ObjectResults
from errors import ResponseError, InvalidContainerName, InvalidObjectName, \
                   ContainerNotPublic, CDNNotEnabled
from utils import requires_name
from consts import default_cdn_ttl

# Because HTTPResponse objects *have* to have read() called on them 
# before they can be used again ...
# pylint: disable-msg=W0612

class Container(object):
    """
    Container object and Object instance factory.

    If your account has the feature enabled, containers can be publically
    shared over a global content delivery network.

    @ivar name: the container's name (generally treated as read-only)
    @type name: str
    @ivar object_count: the number of objects in this container (cached)
    @type object_count: number
    @ivar size_used: the sum of the sizes of all objects in this container
            (cached)
    @type size_used: number
    @ivar cdn_ttl: the time-to-live of the CDN's public cache of this container
            (cached, use make_public to alter)
    @type cdn_ttl: number
    """
    def __set_name(self, name):
        # slashes make for invalid names
        if isinstance(name, (str, unicode)) and '/' in name:
            raise InvalidContainerName(name)
        self._name = name

    name = property(fget=lambda self: self._name, fset=__set_name,
        doc="the name of the container (read-only)")

    def __init__(self, connection=None, name=None, count=None, size=None):
        """
        Containers will rarely if ever need to be instantiated directly by the
        user.

        Instead, use the L{create_container<Connection.create_container>},
        L{get_container<Connection.get_container>},
        L{list_containers<Connection.list_containers>} and
        other methods on a valid Connection object.
        """
        self._name = None
        self.name = name
        self.conn = connection
        self.object_count = count
        self.size_used = size
        self.cdn_uri = None
        self.cdn_ttl = None
        self.cdn_agent_acl = None
        self.cdn_referer_acl = None
        if connection.cdn_enabled:
            self._fetch_cdn_data()

    @requires_name(InvalidContainerName)
    def _fetch_cdn_data(self):
        """
        Fetch the object's CDN data from the CDN service
        """
        response = self.conn.cdn_request('HEAD', [self.name])
        if (response.status >= 200) and (response.status < 300):
            for hdr in response.getheaders():
                if hdr[0].lower() == 'x-cdn-uri':
                    self.cdn_uri = hdr[1]
                if hdr[0].lower() == 'x-ttl':
                    self.cdn_ttl = int(hdr[1])
                if hdr[0].lower() == 'x-user-agent-acl':
                    self.cdn_agent_acl = hdr[1]
                if hdr[0].lower() == 'x-referrer-acl':
                    self.cdn_referer_acl = hdr[1]

    @requires_name(InvalidContainerName)
    def make_public(self, ttl=default_cdn_ttl, user_agent_acl=None,
            referer_acl=None):
        """
        Either publishes the current container to the CDN or updates its
        CDN attributes.  Requires CDN be enabled on the account.

        @param ttl: cache duration in seconds of the CDN server
        @type ttl: number
        @param user_agent_acl: no documentation at this time
        @type user_agent_acl: str
        @param referer_acl: no documentation at this time
        @type referer_acl: str
        """
        if not self.conn.cdn_enabled:
            raise CDNNotEnabled()
        if self.cdn_uri:
            request_method = 'POST'
            user_agent_acl = user_agent_acl or self.cdn_agent_acl
            referer_acl = referer_acl or self.cdn_referer_acl
        else:
            request_method = 'PUT'
        hdrs = {'X-TTL': str(ttl), 'X-CDN-Enabled': 'True'}
        if user_agent_acl:
            hdrs['X-User-Agent-ACL'] = user_agent_acl
        if referer_acl:
            hdrs['X-Referrer-ACL'] = referer_acl
        response = self.conn.cdn_request(request_method, [self.name], hdrs=hdrs)
        if (response.status < 200) or (response.status >= 300):
            raise ResponseError(response.status, response.reason)
        self.cdn_ttl = ttl
        self.cdn_agent_acl = user_agent_acl
        self.cdn_referer_acl = referer_acl
        for hdr in response.getheaders():
            if hdr[0].lower() == 'x-cdn-uri':
                self.cdn_uri = hdr[1]

    @requires_name(InvalidContainerName)
    def make_private(self):
        """
        Disables CDN access to this container.
        It may continue to be available until its TTL expires.
        """
        if not self.conn.cdn_enabled:
            raise CDNNotEnabled()
        hdrs = {'X-CDN-Enabled': 'False'}
        response = self.conn.cdn_request('POST', [self.name], hdrs=hdrs)
        if (response.status < 200) or (response.status >= 300):
            raise ResponseError(response.status, response.reason)

    def is_public(self):
        """
        Returns a boolean indicating whether or not this container is
        publically accessible via the CDN.
        @rtype: bool
        @return: whether or not this container is published to the CDN
        """
        if not self.conn.cdn_enabled:
            raise CDNNotEnabled()
        return self.cdn_uri is not None

    @requires_name(InvalidContainerName)
    def public_uri(self):
        """
        Return the URI for this container, if it is publically
        accessible via the CDN.
        @rtype: str
        @return: the public URI for this container
        """
        if not self.is_public():
            raise ContainerNotPublic()
        return self.cdn_uri

    @requires_name(InvalidContainerName)
    def create_object(self, object_name):
        """
        Return an L{Object} instance, creating it if necessary.
        
        When passed the name of an existing object, this method will 
        return an instance of that object, otherwise it will create a
        new one.

        @type object_name: str
        @param object_name: the name of the object to create
        @rtype: L{Object}
        @return: an object representing the newly created storage object
        """
        return Object(self, object_name)

    @requires_name(InvalidContainerName)
    def get_objects(self, **parms):
        """
        Return a result set of all Objects in the Container.
        
        Keyword arguments are treated as HTTP query parameters and can
        be used limit the result set (see the API documentation).

        @rtype: L{ObjectResults}
        @return: an iterable collection of all storage objects in the container
        """
        return ObjectResults(self, self.list_objects(**parms))

    @requires_name(InvalidContainerName)
    def get_object(self, object_name):
        """
        Return an Object instance for an existing storage object.
        
        If an object with a name matching object_name does not exist
        then a L{NoSuchObject} exception is raised.

        @param object_name: the name of the object to retrieve
        @type object_name: str
        @rtype: L{Object}
        @return: an Object representing the storage object requested
        """
        return Object(self, object_name, force_exists=True)

    @requires_name(InvalidContainerName)
    def list_objects(self, **parms):
        """
        Returns a list of storage object names.
        
        Keyword arguments are treated as HTTP query parameters and can
        be used limit the result set (see the API documentation).

        @rtype: list(str)
        @return: a list of the names of all objects in the container
        """
        response = self.conn.make_request('GET', [self.name], parms=parms)
        if (response.status < 200) or (response.status > 299):
            buff = response.read()
            raise ResponseError(response.status, response.reason)
        return response.read().splitlines()

    def __getitem__(self, key):
        return self.get_object(key)

    def __str__(self):
        return self.name

    @requires_name(InvalidContainerName)
    def delete_object(self, object_name):
        """
        Permanently remove a storage object.
        
        @param object_name: the name of the object to retrieve
        @type object_name: str
        """
        if isinstance(object_name, Object):
            object_name = object_name.name
        if not object_name:
            raise InvalidObjectName(object_name)
        response = self.conn.make_request('DELETE', [self.name, object_name])
        if (response.status < 200) or (response.status > 299):
            buff = response.read()
            raise ResponseError(response.status, response.reason)
        buff = response.read()

class ContainerResults(object):
    """
    An iterable results set object for Containers. 

    This class implements dictionary- and list-like interfaces.
    """
    def __init__(self, conn, containers=list()):
        self._containers = containers
        self.conn = conn

    def __getitem__(self, key):
        return Container(self.conn, self._containers[key])

    def __getslice__(self, i, j):
        return [Container(self._containers, k) for k in self._containers[i:j]]

    def __contains__(self, item):
        return item in self._containers

    def __repr__(self):
        return repr(self._containers)

    def __len__(self):
        return len(self._containers)

    def index(self, value, *args):
        """
        returns an integer for the first index of value
        """
        return self._containers.index(value, *args)

    def count(self, value):
        """
        returns the number of occurrences of value
        """
        return self._containers.count(value)

# vim:set ai sw=4 ts=4 tw=0 expandtab: