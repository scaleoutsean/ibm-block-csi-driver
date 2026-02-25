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
        
        # SANtricity specific: use 'space_efficiency' parameter from StorageClass 
        # as a hint for RAID level. Defaults to 'raid6' if not specified, 
        # which is preferred for DDP pools.
        raid_level = 'raid6'
        if space_efficiency:
            if space_efficiency.lower() in ['raid1', 'raid5', 'raid6', 'raid10']:
                raid_level = space_efficiency.lower()
            elif space_efficiency.lower() == 'none':
                raid_level = None
            
        try:
            vol_data = self.client.create_volume(pool, name, size_gb, raid_level=raid_level)
            return self._to_volume_object(vol_data)
        except Exception as ex:
            # If raid6 default fails (e.g. on a traditional RAID5 group), retry with None
            if raid_level == 'raid6' and not space_efficiency:
                logger.info("Failed to create volume with raid6 default, retrying with inherited RAID level")
                try:
                    vol_data = self.client.create_volume(pool, name, size_gb, raid_level=None)
                    return self._to_volume_object(vol_data)
                except Exception:
                    pass
            
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

    def expand_volume(self, volume_id, required_bytes, partition_name=None):
        try:
            self.client.expand_volume(volume_id, required_bytes)
        except Exception as ex:
            raise array_errors.ExpandVolumeError(volume_id, ex)

    def map_volume(self, volume_id, host_name, connectivity_type):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)

        host_id = host_data['id']
        try:
            mapping = self.client.create_volume_mapping(volume_id, host_id)
            return str(mapping['lun'])
        except Exception as ex:
            raise array_errors.MappingError(volume_id, host_name, ex)

    def unmap_volume(self, volume_id, host_name):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            logger.info("Host {} not found, assuming unmapped".format(host_name))
            return

        host_id = host_data['id']
        mappings = self.client.list_volume_mappings()
        
        for m in mappings:
            if m['mappableObjectId'] == volume_id and m['targetId'] == host_id:
                self.client.delete_volume_mapping(m['mappingRef'])
                return
        
        logger.info("Mapping not found for volume {} and host {}".format(volume_id, host_name))

    def get_host_by_name(self, host_name):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)

        iqns = [p['address'] for p in host_data.get('hostSidePorts', []) if p.get('type') == 'iscsi']
        return Host(name=host_data['label'],
                    connectivity_types=[array_settings.ISCSI_CONNECTIVITY_TYPE],
                    iscsi_iqns=iqns)

    def get_host_by_host_identifiers(self, initiators):
        iqns = initiators.iscsi_iqns
        for iqn in iqns:
            host_data = self.client.get_host_by_identifiers(iqn)
            if host_data:
                return host_data['label'], [array_settings.ISCSI_CONNECTIVITY_TYPE]

        raise array_errors.HostNotFoundError(str(iqns))

    def _get_array_initiators(self, host_name, connectivity_type):
        if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE:
            target_settings = self.client.get_iscsi_target_settings()
            iqn = target_settings.get('nodeName')
            portals = [p.get('address') for p in target_settings.get('portals', [])]
            return {iqn: portals}
        return {}

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

    def copy_to_existing_volume(self, volume_id, source_id, source_capacity_in_bytes, minimum_volume_size_in_bytes):
        raise NotImplementedError()

    def get_iscsi_targets_by_iqn(self, host_name):
        target_settings = self.client.get_iscsi_target_settings()
        iqn = target_settings.get('nodeName')
        portals = [p.get('address') for p in target_settings.get('portals', [])]
        if not iqn or not portals:
            raise array_errors.NoIscsiTargetsFoundError(self.endpoint)
        return {iqn: portals}
