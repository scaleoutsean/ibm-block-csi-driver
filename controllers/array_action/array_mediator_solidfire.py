import controllers.array_action.errors as array_errors
import controllers.array_action.settings as array_settings
from controllers.array_action.array_action_types import Volume, Host
from controllers.array_action.array_mediator_abstract import ArrayMediatorAbstract
from controllers.array_action.solidfire_client import SolidFireClient
from controllers.array_action.utils import ClassProperty
from controllers.common import settings
from controllers.common.csi_logger import get_stdout_logger

logger = get_stdout_logger()

class SolidFireArrayMediator(ArrayMediatorAbstract):
    ARRAY_ACTIONS = {}

    @ClassProperty
    def array_type(self):
        return settings.ARRAY_TYPE_SOLIDFIRE

    @ClassProperty
    def port(self):
        return 443

    def __init__(self, user, password, endpoint):
        super().__init__(user, password, endpoint)
        # Endpoint is the MVIP
        self.client = SolidFireClient(endpoint[0], user, password)
        self._identifier = None

    def disconnect(self):
        pass

    @property
    def identifier(self):
        if not self._identifier:
            info = self.client.get_cluster_info()
            self._identifier = info['clusterInfo']['uniqueID']
        return self._identifier

    def create_volume(self, name, size_in_bytes, space_efficiency, pool, io_group, volume_group, source_ids,
                      source_type, is_virt_snap_func, partition_name=None, partition_vg=None):
        
        # SolidFire requires an Account ID to create a volume.
        # For MVP, we'll assume a default account named 'csi-admin' exists or create it.
        # In production, this might come from config or parameters.
        account_name = "csi-admin"
        account = self.client.get_account_by_name(account_name)
        if not account:
            logger.info("Creating default account {}".format(account_name))
            res = self.client.create_account(account_name)
            account_id = res['accountID']
        else:
            account_id = account['accountID']

        try:
            vol_res = self.client.create_volume(name, size_in_bytes, account_id)
            # Fetch full details to return Volume object
            return self.get_volume(vol_res['volumeID'])
        except Exception as ex:
            logger.exception("Failed to create volume")
            raise array_errors.VolumeCreationError(name)

    def delete_volume(self, volume_id):
        try:
            self.client.delete_volume(volume_id)
        except Exception as ex:
            # SolidFire throws error if volume doesn't exist, but we should be idempotent
            if "xVolumeIDDoesNotExist" in str(ex):
                return
            logger.exception("Failed to delete volume")
            raise array_errors.ObjectNotFoundError(volume_id)

    def get_volume(self, volume_id):
        try:
            vol_data = self.client.get_volume(volume_id)
            return self._to_volume_object(vol_data)
        except Exception:
            raise array_errors.ObjectNotFoundError(volume_id)

    def map_volume(self, volume_id, host_name, connectivity_type):
        # SolidFire uses Volume Access Groups (VAGs) to map volumes to initiators.
        # We treat the Host Name as the VAG Name.
        
        # 1. Find VAG by name
        vags = self.client.list_volume_access_groups().get('volumeAccessGroups', [])
        vag = next((v for v in vags if v['name'] == host_name), None)
        
        if not vag:
            # If VAG doesn't exist, we can't map because we don't know the initiators here.
            # The abstract class calls get_host_by_host_identifiers first, which should create it.
            raise array_errors.HostNotFoundError(host_name)

        # 2. Add volume to VAG
        try:
            self.client.add_volumes_to_volume_access_group(vag['volumeAccessGroupID'], [volume_id])
            # SolidFire doesn't have per-host LUN IDs in the same way. 
            # The LUN ID is usually the Volume ID (low 32 bits) or assigned dynamically.
            # For iSCSI, the target IQN is usually the volume IQN.
            # But if using VAG, the LUN ID is determined by the order or explicit assignment.
            # For MVP, let's return '0' and rely on the Node plugin to discover the LUN.
            return '0' 
        except Exception as ex:
            raise array_errors.MappingError(volume_id, host_name, ex)

    def unmap_volume(self, volume_id, host_name):
        vags = self.client.list_volume_access_groups().get('volumeAccessGroups', [])
        vag = next((v for v in vags if v['name'] == host_name), None)
        
        if vag:
            try:
                self.client.remove_volumes_from_volume_access_group(vag['volumeAccessGroupID'], [volume_id])
            except Exception as ex:
                logger.warning("Failed to unmap volume: {}".format(ex))

    def get_host_by_name(self, host_name):
        vags = self.client.list_volume_access_groups().get('volumeAccessGroups', [])
        vag = next((v for v in vags if v['name'] == host_name), None)
        
        if not vag:
            raise array_errors.HostNotFoundError(host_name)
            
        return Host(name=host_name, connectivity_types=[array_settings.ISCSI_CONNECTIVITY_TYPE], iscsi_iqns=vag['initiators'])

    def get_host_by_host_identifiers(self, initiators):
        # initiators is a list of IQNs
        # We need to find a VAG that contains these initiators, or create one.
        # For simplicity, we'll assume the VAG name should match the K8s Node Name (which we don't have here directly).
        # But wait, the caller usually passes initiators to find the host.
        
        # Search all VAGs for these initiators
        vags = self.client.list_volume_access_groups().get('volumeAccessGroups', [])
        for vag in vags:
            if any(i in vag['initiators'] for i in initiators):
                return vag['name'], [array_settings.ISCSI_CONNECTIVITY_TYPE]
        
        raise array_errors.HostNotFoundError(initiators)

    def _get_array_initiators(self, host_name, connectivity_type):
        # Return the SVIP (Storage Virtual IP)
        # In a real implementation, we might query GetClusterInfo to find the SVIP.
        # For now, we'll hardcode or derive it.
        # Let's query cluster info.
        info = self.client.get_cluster_info()
        svip = info['clusterInfo']['svip']
        return [svip]

    def _to_volume_object(self, vol_data):
        return Volume(
            capacity_bytes=int(vol_data['totalSize']),
            id=str(vol_data['volumeID']),
            internal_id=str(vol_data['volumeID']),
            name=vol_data['name'],
            array_address=self.endpoint[0], # MVIP
            source_id=None,
            array_type=self.array_type,
            pool='default' # SolidFire has one pool
        )

    def copy_to_existing_volume(self, volume_id, source_id, source_capacity_in_bytes, minimum_volume_size_in_bytes):
        raise NotImplementedError()
