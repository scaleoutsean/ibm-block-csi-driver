import os
import urllib3
from controllers.common.csi_logger import get_stdout_logger
from .santricity_client.client import SANtricityClient as NewSANtricityClient
from .santricity_client.auth.basic import BasicAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_stdout_logger()

class SANtricityClient:
    """
    Enhanced wrapper for the SANtricity Python Client Library.
    Supports failover across multiple management endpoints.
    """
    def __init__(self, endpoints, user, password, port=8443, verify_ssl=None, system_id=None):
        if verify_ssl is None:
            env_verify = os.getenv("SANTRICITY_VERIFY_SSL", "false").lower()
            verify_ssl = env_verify not in ("false", "0", "no", "off")

        self.user = user
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.requested_system_id = system_id
        
        # Connection details
        if isinstance(endpoints, str):
            self.mgmt_ips = [endpoints]
        else:
            self.mgmt_ips = endpoints

        self._client = self._connect_to_available_endpoint()

    def _connect_to_available_endpoint(self):
        """Iterate through management IPs until a connection is established."""
        auth = BasicAuth(username=self.user, password=self.password)
        last_error = None

        # Handle port being a list or a single int
        ports = self.port
        if not isinstance(ports, list):
            ports = [ports] * len(self.mgmt_ips)

        for i, ip in enumerate(self.mgmt_ips):
            current_port = ports[i] if i < len(ports) else ports[0]
            base_url = "https://{}:{}/devmgr/v2".format(ip, current_port)
            logger.debug("Attempting to connect to SANtricity endpoint: {}".format(base_url))
            try:
                client = NewSANtricityClient(
                    base_url=base_url,
                    auth_strategy=auth,
                    verify_ssl=self.verify_ssl,
                    system_id=self.requested_system_id
                )
                # Verify connection by fetching system_id
                _ = client.system_id
                logger.info("Successfully connected to SANtricity endpoint: {}".format(ip))
                return client
            except Exception as ex:
                logger.warning("Failed to connect to {}: {}".format(ip, ex))
                last_error = ex
        
        raise Exception("Could not connect to any SANtricity endpoints: {}".format(last_error))

    @property
    def system_id(self):
        """Return the actual system ID (WWN) from the client"""
        try:
            return self._client.system_id
        except Exception:
            # Fallback if discovery fails during property access
            return "1"

    def get_storage_systems(self):
        """List storage systems managed by this endpoint"""
        return self._client.request("GET", "/storage-systems", system_scope=False)

    def create_volume(self, pool_id, name, size_bytes, raid_level=None, workload_id=None, meta_tags=None):
        """
        Create a new volume
        """
        logger.info(
            "Creating volume: name={}, size_bytes={}, pool={}, raid={}, workload={}, meta_tags={}".format(
                name, size_bytes, pool_id, raid_level, workload_id, meta_tags
            )
        )
        
        # Embedded REST API requirements (verified by manual test):
        # - 'name' is accepted in POST payload
        # - 'size' should be a string in bytes for type safety
        # - 'poolId' is used to specify the storage pool
        # - 'sizeUnit' should be 'bytes'
        payload = {
            "poolId": pool_id,
            "name": name,
            "sizeUnit": "bytes",
            "size": str(int(size_bytes)),
        }
        if raid_level:
            payload["raidLevel"] = raid_level
        if workload_id:
            payload["workloadId"] = workload_id
        if meta_tags:
            payload["metaTags"] = meta_tags
            
        return self._client.volumes.create(payload)

    def delete_volume(self, volume_id):
        """Delete a volume"""
        logger.info("Deleting volume: {}".format(volume_id))
        return self._client.volumes.delete(volume_id)

    def get_volume(self, volume_id):
        """Get specific volume details"""
        return self._client.volumes.get(volume_id)

    def get_volume_by_name(self, name, pool_id=None):
        """Find a volume by its name or label"""
        for vol in self.list_volumes():
            # Check both 'name' and 'label' for robustness
            if vol.get("name") == name or vol.get("label") == name:
                if pool_id:
                    # Resolve pool name to ID if needed
                    p_id = pool_id
                    if not pool_id.startswith("0400"): # Not a Ref
                         # This should probably be handled by the caller or a helper
                         pass
                    
                    actual_pool_ref = vol.get("volumeGroupRef")
                    if actual_pool_ref != p_id:
                        # Some APIs use 'poolId' in response, some 'volumeGroupRef'
                        if vol.get("poolId") != p_id:
                            continue
                return vol
        return None

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

    def list_host_groups(self):
        """List all host groups (clusters)"""
        return self._client.hosts.list_groups()

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

    def get_nvme_target_settings(self):
        """Get NVMe target settings"""
        return self._client.interfaces.get_nvme_target_settings()

    def get_system_serial(self):
        """Get the array's serial number."""
        try:
            info = self._client.system.get_info()
            return info.get("serialNumber") or info.get("chassisSerialNumber")
        except Exception:
            return None

    def register_host(self, name, ports=None, host_type_index=-1):
        """Register a new host on the array"""
        payload = {
            "name": name,
            "hostType": {"index": host_type_index},
            "ports": ports or []
        }
        return self._client.hosts.create(payload)

    def unregister_host(self, host_id):
        """Remove a host registration"""
        return self._client.hosts.delete(host_id)

    def append_host_port(self, host_id, label, port_type, address):
        """Add a port to an existing host"""
        payload = {
            "label": label,
            "type": port_type,
            "address": address
        }
        return self._client.request("POST", f"/hosts/{host_id}/ports", payload=payload)

    def discard_host_port(self, host_id, port_ref):
        """Remove a port from a host"""
        return self._client.request("DELETE", f"/hosts/{host_id}/ports/{port_ref}")

    def get_host_types(self):
        """Fetch available host types for selection"""
        return self._client.request("GET", "/host-types")




    def create_snapshot_group(self, volume_id, name, percent_capacity=20):
        candidates = self._client.snapshots.get_repo_group_candidates_single(
            base_volume_ref=volume_id,
            percent_capacity=percent_capacity,
            concat_volume_type="snapshotGroup"
        )
        if not candidates:
            raise Exception("No repository candidates found for volume {}".format(volume_id))
        
        payload = {
            "baseMappableObjectId": volume_id,
            "name": name,
            "repositoryCandidate": candidates[0]
        }
        return self._client.snapshots.create_group(payload)

    def list_snapshot_groups(self):
        return self._client.snapshots.list_groups()

    def get_snapshot_group(self, group_id):
        # The library list_groups returns all, we filter
        groups = self._client.snapshots.list_groups()
        for g in groups:
            if g.get("id") == group_id or g.get("pitGroupRef") == group_id:
                return g
        return None

    def delete_snapshot_group(self, group_id):
        return self._client.snapshots.delete_group(group_id)

    def list_snapshot_images(self, group_id):
        return self._client.snapshots.list_images(group_id)

    def create_snapshot_image(self, group_id):
        return self._client.snapshots.create_image(group_id)
