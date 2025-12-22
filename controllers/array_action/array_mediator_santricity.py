import controllers.array_action.errors as array_errors
import controllers.array_action.settings as array_settings
from controllers.array_action.array_action_types import Volume, Host
from controllers.array_action.array_mediator_abstract import ArrayMediatorAbstract
from controllers.array_action.santricity_rest_client import SANtricityClient
from controllers.array_action.utils import ClassProperty
from controllers.common import settings
from controllers.common.csi_logger import get_stdout_logger

logger = get_stdout_logger()

class SANtricityArrayMediator(ArrayMediatorAbstract):
    ARRAY_ACTIONS = {}

    @ClassProperty
    def array_type(self):
        return settings.ARRAY_TYPE_SANTRICITY

    @ClassProperty
    def port(self):
        return 8443

    def __init__(self, user, password, endpoint):
        super().__init__(user, password, endpoint)
        self.client = SANtricityClient(endpoint, user, password)
        self._identifier = None

    def disconnect(self):
        pass

    @property
    def identifier(self):
        if not self._identifier:
            self._identifier = self.client.get_storage_systems()[0]['id']
        return self._identifier

    def create_volume(self, name, size_in_bytes, space_efficiency, pool, io_group, volume_group, source_ids,
                      source_type, is_virt_snap_func, partition_name=None, partition_vg=None):
        size_gb = size_in_bytes / (1024 ** 3)
        try:
            vol_data = self.client.create_volume(pool, name, size_gb)
            return self._to_volume_object(vol_data)
        except Exception as ex:
            logger.exception("Failed to create volume")
            raise array_errors.VolumeCreationError(name)

    def delete_volume(self, volume_id):
        try:
            self.client.delete_volume(volume_id)
        except Exception as ex:
            # Check if not found, if so, consider success or raise ObjectNotFoundError
            logger.exception("Failed to delete volume")
            raise array_errors.ObjectNotFoundError(volume_id)

    def get_volume(self, volume_id):
        try:
            vol_data = self.client.get_volume(volume_id)
            return self._to_volume_object(vol_data)
        except Exception:
            raise array_errors.ObjectNotFoundError(volume_id)

    def map_volume(self, volume_id, host_name, connectivity_type):
        # First check if host exists, if not create it? 
        # The abstract class seems to handle host creation/lookup via get_host_by_host_identifiers
        # But map_volume just takes host_name.
        
        # We need to find the host ID for the name
        host_id = self._get_host_id_by_name(host_name)
        if not host_id:
             raise array_errors.HostNotFoundError(host_name)

        try:
            mapping = self.client.create_volume_mapping(volume_id, host_id)
            return str(mapping['lun'])
        except Exception as ex:
            raise array_errors.MappingError(volume_id, host_name, ex)

    def unmap_volume(self, volume_id, host_name):
        # We need to find the mapping ID.
        # This is inefficient, we should probably add a method to client to find mapping by vol/host
        mappings = self.client.list_volume_mappings()
        host_id = self._get_host_id_by_name(host_name)
        
        for m in mappings:
            if m['mappableObjectId'] == volume_id and m['targetId'] == host_id:
                self.client.delete_volume_mapping(m['mappingRef'])
                return
        
        # If not found, maybe already unmapped?
        logger.info("Mapping not found for volume {} and host {}".format(volume_id, host_name))

    def get_host_by_name(self, host_name):
        host_id = self._get_host_id_by_name(host_name)
        if not host_id:
            raise array_errors.HostNotFoundError(host_name)
        
        # We need to get details to populate connectivity types
        # For now, assuming iSCSI
        return Host(name=host_name, connectivity_types=[array_settings.ISCSI_CONNECTIVITY_TYPE], iscsi_iqns=[])

    def get_host_by_host_identifiers(self, initiators):
        # Search hosts by initiators (IQNs)
        # This requires listing hosts and checking their ports
        # For MVP, we might assume host name matches or something, but better to implement search
        raise NotImplementedError("Host lookup by initiators not implemented yet")

    def _get_array_initiators(self, host_name, connectivity_type):
        # Return list of iSCSI portal IPs/IQNs
        return ["1.1.1.1"] # Placeholder

    def _to_volume_object(self, vol_data):
        return Volume(
            capacity_bytes=int(vol_data['capacity']),
            id=vol_data['id'],
            internal_id=vol_data['id'],
            name=vol_data['name'],
            array_address=self.endpoint,
            source_id=None,
            array_type=self.array_type,
            pool=vol_data['poolId']
        )

    def _get_host_id_by_name(self, host_name):
        hosts = self.client.list_hosts()
        for h in hosts:
            if h['name'] == host_name:
                return h['id']
        return None

    def copy_to_existing_volume(self, volume_id, source_id, source_capacity_in_bytes, minimum_volume_size_in_bytes):
        raise NotImplementedError()
