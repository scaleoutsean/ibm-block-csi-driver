import urllib3
from controllers.common.csi_logger import get_stdout_logger
from .santricity_client.client import SANtricityClient as NewSANtricityClient
from .santricity_client.auth.basic import BasicAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_stdout_logger()

class SANtricityClient:
    """
    Wrapper for the NetApp SANtricity Python Client Library.
    """
    def __init__(self, address, user, password, port=8443, verify_ssl=False):
        base_url = "https://{}:{}/devmgr/v2".format(address, port)
        auth = BasicAuth(username=user, password=password)
        self._client = NewSANtricityClient(
            base_url=base_url,
            auth_strategy=auth,
            verify_ssl=verify_ssl
        )
        # Default to system '1' if not specified, matching previous behavior
        self.system_id = "1"

    def get_storage_systems(self):
        return self._client.system.list()

    def create_volume(self, pool_id, name, size_gb, raid_level=None, workload_id=None):
        """
        Create a new volume
        """
        logger.info(
            "Creating volume: name={}, size={}GB, pool={}, raid={}, workload={}".format(
                name, size_gb, pool_id, raid_level, workload_id
            )
        )
        payload = {
            "poolId": pool_id,
            "name": name,
            "sizeUnit": "gb",
            "size": str(size_gb),
        }
        if raid_level:
            payload["raidLevel"] = raid_level
        if workload_id:
            payload["workloadId"] = workload_id
            
        return self._client.volumes.create(payload)

    def delete_volume(self, volume_id):
        """Delete a volume"""
        logger.info("Deleting volume: {}".format(volume_id))
        return self._client.volumes.delete(volume_id)

    def get_volume(self, volume_id):
        """Get specific volume details"""
        return self._client.volumes.get(volume_id)

    def expand_volume(self, volume_id, size_bytes):
        """Expand volume capacity"""
        return self._client.volumes.expand(volume_id, size_bytes)

    def list_volumes(self):
        """List all volumes"""
        return self._client.volumes.list()

    def create_volume_mapping(self, volume_id, target_id, lun=None):
        """
        Map volume to host or host group
        """
        logger.info(
            "Creating volume mapping: volume={}, target={}, lun={}".format(
                volume_id, target_id, lun
            )
        )
        return self._client.mappings.map_volume(
            volume_ref=volume_id,
            host_ref=target_id,
            lun=lun
        )

    def delete_volume_mapping(self, mapping_id):
        """Delete a volume mapping"""
        logger.info("Deleting volume mapping: {}".format(mapping_id))
        return self._client.request("DELETE", f"/volume-mappings/{mapping_id}")

    def list_volume_mappings(self):
        """List all volume mappings"""
        return self._client.mappings.list()

    def list_hosts(self):
        """List all registered hosts"""
        return self._client.hosts.list()

    def get_host(self, host_id):
        """Get specific host details"""
        return self._client.hosts.get(host_id)

    def get_host_by_identifiers(self, identifier):
        """Find a host by name, ID, or port address"""
        return self._client.hosts.get_by_identifiers(identifier)

    def get_pools(self):
        """List storage pools"""
        return self._client.pools.list()

    def get_iscsi_target_settings(self):
        """Get iSCSI target settings"""
        return self._client.interfaces.get_iscsi_target_settings()


