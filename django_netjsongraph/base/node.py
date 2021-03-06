import json
from collections import OrderedDict
from datetime import timedelta

from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.functional import cached_property
from django.utils.timezone import now
from jsonfield import JSONField
from rest_framework.utils.encoders import JSONEncoder

from .. import settings
from ..utils import print_info
from .base import TimeStampedEditableModel


@python_2_unicode_compatible
class AbstractNode(TimeStampedEditableModel):
    """
    NetJSON NetworkGraph Node Object implementation
    """
    topology = models.ForeignKey('django_netjsongraph.Topology',
                                 on_delete=models.CASCADE)
    label = models.CharField(max_length=64, blank=True)
    # netjson ID and local_addresses
    addresses = models.CharField(max_length=510, db_index=True)
    properties = JSONField(default=dict,
                           blank=True,
                           load_kwargs={'object_pairs_hook': OrderedDict},
                           dump_kwargs={'indent': 4})

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    def clean(self):
        if self.properties is None:
            self.properties = {}

    def save(self, *args, **kwargs):
        self._format_addresses()
        super(AbstractNode, self).save(*args, **kwargs)

    def _format_addresses(self):
        """
        Ensure address format is correct: ";addr1;addr2;addr3;"
        """
        self.addresses = self.addresses.replace(',', ';')\
                                       .replace(' ', '')\
                                       .replace(';', ';')
        if not self.addresses.startswith(';'):
            self.addresses = ';' + self.addresses
        if not self.addresses.endswith(';'):
            self.addresses += ';'

    def truncate_addresses(self):
        """
        ensures "addresses" field is not too long
        """
        max_length = self._meta.get_field('addresses').max_length
        if len(self.addresses) <= max_length:
            return
        addresses = self.address_list
        # +1 stands for the character added in self._format_address()
        while len(';'.join(addresses)) + 2 > max_length:
            addresses.pop()
        self.addresses = ';'.join(addresses)

    @cached_property
    def address_list(self):
        addresses = self.addresses.replace(' ', '')
        if addresses.startswith(';'):
            addresses = addresses[1:]
        return addresses[0:-1].split(';')

    @property
    def netjson_id(self):
        if self.addresses:
            return self.address_list[0]

    @cached_property
    def local_addresses(self):
        if self.addresses and len(self.address_list) > 1:
            return self.address_list[1:]

    @property
    def name(self):
        if self.label:
            return self.label
        return self.netjson_id

    def json(self, dict=False, **kwargs):
        """
        returns a NetJSON NetworkGraph Node object
        """
        netjson = OrderedDict({'id': self.netjson_id})
        for attr in ['label', 'local_addresses', 'properties']:
            value = getattr(self, attr)
            if value or attr == 'properties':
                netjson[attr] = value
        netjson['properties']['created'] = self.created
        netjson['properties']['modified'] = self.modified
        if dict:
            return netjson
        return json.dumps(netjson, cls=JSONEncoder, **kwargs)

    @classmethod
    def get_from_address(cls, address, topology):
        """
        Find node from one of its addresses and its topology.
        :param address: string
        :param topology: Topology instance
        :returns: Node object or None
        """
        address = ';{0};'.format(address)
        return cls.objects.filter(topology=topology,
                                  addresses__contains=address).first()

    @classmethod
    def count_address(cls, address, topology):
        """
        Count nodes with the specified address and topology.
        :param address: string
        :param topology: Topology instance
        :returns: int
        """
        address = ';{0};'.format(address)
        return cls.objects.filter(topology=topology,
                                  addresses__contains=address).count()

    @classmethod
    def delete_expired_nodes(cls):
        """
        deletes nodes that have not been  connected to the network
        for more than ``NETJSONGRAPH__EXPIRATION`` days
        """
        NODE_EXPIRATION = settings.NODE_EXPIRATION
        LINK_EXPIRATION = settings.LINK_EXPIRATION
        if NODE_EXPIRATION not in [False, None] and LINK_EXPIRATION not in [False, None]:
            expiration_date = now() - timedelta(days=int(NODE_EXPIRATION))
            expired_nodes = cls.objects.filter(modified__lt=expiration_date,
                                               source_link_set__isnull=True,
                                               target_link_set__isnull=True)
            expired_nodes_length = len(expired_nodes)
            if expired_nodes_length:
                print_info('Deleting {0} expired nodes'.format(expired_nodes_length))
                for node in expired_nodes:
                    node.delete()
