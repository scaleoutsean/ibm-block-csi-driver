import controllers.array_action.errors as array_errors
import controllers.array_action.settings as array_settings
from controllers.array_action.array_action_types import Volume, Host
from controllers.array_action.array_mediator_abstract import ArrayMediatorAbstract
from controllers.array_action.santricity_rest_client import SANtricityClient
from controllers.array_action.utils import ClassProperty
from controllers.common import settings
from controllers.servers import settings as servers_settings
from controllers.common.csi_logger import get_stdout_logger

logger = get_stdout_logger()

class SANtricityArrayMediator(ArrayMediatorAbstract):
    ARRAY_ACTIONS = {}

    @ClassProperty
    def array_type(self):
        return settings.ARRAY_TYPE_SANTRICITY

    @ClassProperty
    def port(self):
        return [8443, 8443]

    @ClassProperty
    def max_object_name_length(self):
        return 30

    @ClassProperty
    def max_object_prefix_length(self):
        return 20

    @ClassProperty
    def max_connections(self):
        return 5

    @ClassProperty
    def minimal_volume_size_in_bytes(self):
        return 1024 * 1024  # 1 MiB

    @ClassProperty
    def maximal_volume_size_in_bytes(self):
        return 256 * 1024 * 1024 * 1024 * 1024  # 256 TiB

    @ClassProperty
    def max_lun_retries(self):
        return 10

    @ClassProperty
    def default_object_prefix(self):
        return None

    def __init__(self, user, password, endpoint, verify_ssl=False, system_id=None):
        super().__init__(user, password, endpoint, verify_ssl=verify_ssl)
        self.client = SANtricityClient(endpoint, user, password, port=self.port, verify_ssl=verify_ssl, system_id=system_id)
        self._identifier = system_id

    def disconnect(self):
        pass

    @property
    def identifier(self):
        if not self._identifier:
            self._identifier = self.client.system_id
        return self._identifier

    def _get_pool_id(self, pool_name):
        """Resolve a pool name (label) to its volumeGroupRef ID."""
        pools = self.client.get_pools()
        for p in pools:
            if p.get('label') == pool_name or p.get('volumeGroupRef') == pool_name:
                return p['volumeGroupRef']
        return pool_name

    def create_volume(self, name, size_in_bytes, space_efficiency, pool, io_group, volume_group, source_ids,
                      source_type, is_virt_snap_func, partition_name=None, partition_vg=None, extra_parameters=None):
        pool_id = self._get_pool_id(pool)
        
        # SANtricity specific: use 'space_efficiency' parameter from StorageClass 
        # as a hint for RAID level. Defaults to 'raidAll' (inherit from pool)
        # because specifying raid6 can fail on non-DDP pools.
        raid_level = 'raidAll'
        if space_efficiency:
            if space_efficiency.lower() in ['raid1', 'raid5', 'raid6', 'raid10']:
                raid_level = space_efficiency.lower()
            elif space_efficiency.lower() == 'none':
                raid_level = None

        meta_tags = []
        if extra_parameters:
            # Map Kubernetes metadata keys to SANtricity tags
            md_mapping = {
                "csi.storage.k8s.io/pvc/name": "pvc_name",
                "csi.storage.k8s.io/pvc/namespace": "pvc_namespace",
                "csi.storage.k8s.io/pv/name": "pv_name",
                "csi.storage.k8s.io/fstype": "fstype"
            }
            for k8s_key, tag_key in md_mapping.items():
                if value := extra_parameters.get(k8s_key):
                    meta_tags.append({"key": tag_key, "value": value})
            
        try:
            # Use label=name in payload for Embedded REST API
            vol_data = self.client.create_volume(pool_id, name, size_in_bytes, raid_level=raid_level, 
                                                 meta_tags=meta_tags)
            return self._to_volume_object(vol_data)
        except Exception as ex:
            # If raidAll fails, fallback to None
            if raid_level == 'raidAll' and not space_efficiency:
                logger.info("Failed to create volume with raidAll default, retrying with None")
                try:
                    vol_data = self.client.create_volume(pool_id, name, size_in_bytes, raid_level=None,
                                                         meta_tags=meta_tags)
                    return self._to_volume_object(vol_data)
                except Exception:
                    pass
            
            logger.exception("Failed to create volume")
            raise array_errors.VolumeCreationError(name)

    def delete_volume(self, volume_id, partition_name=None):
        # partition_name is accepted for controller compatibility; SANtricity does not use partitions.
        try:
            self.client.delete_volume(volume_id)
        except Exception as ex:
            # Check if not found, if so, consider success or raise ObjectNotFoundError
            logger.exception("Failed to delete volume")
            raise array_errors.ObjectNotFoundError(volume_id)

    def get_volume(self, name, pool, is_virt_snap_func):
        if is_virt_snap_func:
            logger.debug("is_virt_snap_func is not implemented for SANtricity, ignoring")

        pool_id = self._get_pool_id(pool)
        vol_data = self.client.get_volume_by_name(name, pool_id=pool_id)
        if not vol_data:
            raise array_errors.ObjectNotFoundError(name)

        return self._to_volume_object(vol_data)

    def expand_volume(self, volume_id, required_bytes, partition_name=None):
        try:
            self.client.expand_volume(volume_id, required_bytes)
        except Exception as ex:
            raise array_errors.ExpandVolumeError(volume_id, ex)

    def map_volume(self, volume_id, host_name, connectivity_type):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)

        # Embedded API response often uses id, but proxy/unified uses hostRef
        host_id = host_data.get('id') or host_data.get('hostRef')
        
        # Check if host is part of a Host Group (Cluster). 
        # If so, map to the ClusterRef instead of individual HostRef.
        cluster_ref = host_data.get('clusterRef')
        if cluster_ref and cluster_ref != "0000000000000000000000000000000000000000":
            logger.info("Host {} is part of cluster {}, mapping to cluster instead".format(
                host_name, cluster_ref
            ))
            host_id = cluster_ref

        try:
            # We omit the LUN number to let the array allocate it automatically.
            mapping = self.client.create_volume_mapping(volume_id, host_id)
            # Both APIs return a 'lun' field in the mapping object
            return str(mapping['lun'])
        except Exception as ex:
            raise array_errors.MappingError(volume_id, host_name, ex)

    def unmap_volume(self, volume_id, host_name):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            logger.info("Host {} not found, assuming unmapped".format(host_name))
            return

        host_id = host_data.get('id') or host_data.get('hostRef')
        cluster_ref = host_data.get('clusterRef')
        
        mappings = self.client.list_volume_mappings()
        
        for m in mappings:
            # Embedded API response often uses volumeRef/mapRef instead of mappableObjectId/targetId
            vol_ref = m.get('volumeRef') or m.get('mappableObjectId')
            target_ref = m.get('mapRef') or m.get('targetId')
            
            # Match either the host or the cluster it belongs to
            if vol_ref == volume_id and (target_ref == host_id or (cluster_ref and target_ref == cluster_ref)):
                # Use id or lunMappingRef for the mapping itself
                mapping_id = m.get('id') or m.get('lunMappingRef') or m.get('mappingRef')
                if mapping_id:
                    self.client.delete_volume_mapping(mapping_id)
                    return
        
        logger.info("Mapping not found for volume {} and host {}".format(volume_id, host_name))

    def get_host_by_name(self, host_name):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)

        connectivity_types = []
        iqns = []
        nqns = []
        for p in host_data.get('hostSidePorts', []):
            ptype = p.get('type')
            if ptype == 'iscsi':
                iqns.append(p['address'])
                if array_settings.ISCSI_CONNECTIVITY_TYPE not in connectivity_types:
                    connectivity_types.append(array_settings.ISCSI_CONNECTIVITY_TYPE)
            elif ptype in ['nvmeof', 'nvmeRoce', 'nvme']:
                nqns.append(p['address'])
                if array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE not in connectivity_types:
                    connectivity_types.append(array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE)

        return Host(name=host_data['label'],
                    connectivity_types=connectivity_types,
                    iscsi_iqns=iqns,
                    nvme_nqns=nqns)

    def get_host_by_host_identifiers(self, initiators):
        for nqn in initiators.nvme_nqns:
            host_data = self.client.get_host_by_identifiers(nqn)
            if host_data:
                return host_data['label'], [array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE]

        for iqn in initiators.iscsi_iqns:
            host_data = self.client.get_host_by_identifiers(iqn)
            if host_data:
                return host_data['label'], [array_settings.ISCSI_CONNECTIVITY_TYPE]

        raise array_errors.HostNotFoundError(str(initiators))

    def _get_array_initiators(self, host_name, connectivity_type):
        initiators = {}
        if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE:
            target_settings = self.client.get_iscsi_target_settings()
            iqn = target_settings.get('nodeName')
            portals = [p.get('address') for p in target_settings.get('portals', [])]
            if iqn:
                initiators[iqn] = portals
        elif connectivity_type == array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE:
            target_settings = self.client.get_nvme_target_settings()
            nqn = target_settings.get('nodeName')
            portals = [p.get('address') for p in target_settings.get('portals', [])]
            if nqn:
                initiators[nqn] = portals
            
            # For NVMe, deterministic by-id paths use the array's serial
            serial = self.client.get_system_serial()
            if serial:
                initiators["ARRAY_SERIAL_PARAM"] = [serial]

        return initiators

    def _to_volume_object(self, vol_data):
        return Volume(
            capacity_bytes=int(vol_data['capacity']),
            id=vol_data['volumeRef'],
            internal_id=vol_data['volumeRef'],
            name=vol_data['label'],
            array_address=self.endpoint,
            source_id=None,
            array_type=self.array_type,
            pool=vol_data['volumeGroupRef']
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

    def get_nvme_target_ports(self):
        """SANtricity integration currently uses NVMe/RoCE discovery, not NVMe/FC WWNN/WWPN pairs."""
        return []

    def create_host(self, host_name, initiators, connectivity_type, io_group, partition_name=None, port_set=None):
        # We ignore io_group and port_set for SANtricity
        # Host type index -1 is 'linux' or autodetection in many SANtricity versions
        host_type_index = -1
        
        # Check if already exists
        existing = self.client.get_host_by_identifiers(host_name)
        if existing:
            raise array_errors.HostAlreadyExists(host_name, self.endpoint)

        ports = []
        if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE:
            for iqn in initiators.iscsi_iqns:
                ports.append({"type": "iscsi", "address": iqn, "label": f"{host_name}_iscsi"})
        elif connectivity_type == array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE:
            for nqn in initiators.nvme_nqns:
                ports.append({"type": "nvmeof", "address": nqn, "label": f"{host_name}_nvme"})
        
        try:
            self.client.register_host(host_name, ports=ports, host_type_index=host_type_index)
        except Exception as ex:
            logger.exception("Failed to create host {}".format(host_name))
            raise ex

    def delete_host(self, host_name):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            return
        
        try:
            self.client.unregister_host(host_data['id'])
        except Exception as ex:
            logger.exception("Failed to delete host {}".format(host_name))
            raise ex

    def add_ports_to_host(self, host_name, initiators, connectivity_type):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)

        host_id = host_data['id']
        current_ports = [p['address'] for p in host_data.get('hostSidePorts', [])]

        if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE:
            for iqn in initiators.iscsi_iqns:
                if iqn not in current_ports:
                    self.client.append_host_port(host_id, f"{host_name}_iscsi", "iscsi", iqn)
        elif connectivity_type == array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE:
            for nqn in initiators.nvme_nqns:
                if nqn not in current_ports:
                    self.client.append_host_port(host_id, f"{host_name}_nvme", "nvmeof", nqn)

    def remove_ports_from_host(self, host_name, ports, connectivity_type):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            return

        host_id = host_data['id']
        for p in host_data.get('hostSidePorts', []):
            if p['address'] in ports:
                self.client.discard_host_port(host_id, p['portRef'])

    def get_host_connectivity_ports(self, host_name, connectivity_type):
        host_data = self.client.get_host_by_identifiers(host_name)
        if not host_data:
            raise array_errors.HostNotFoundError(host_name)
        
        ports = []
        for p in host_data.get('hostSidePorts', []):
            ptype = p.get('type')
            if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE and ptype == 'iscsi':
                ports.append(p['address'])
            elif connectivity_type == array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE and ptype in ['nvmeof', 'nvmeRoce', 'nvme']:
                ports.append(p['address'])
        return ports

    def get_host_connectivity_type(self, host_name):
        host_obj = self.get_host_by_name(host_name)
        if not host_obj.connectivity_types:
            return None
        return host_obj.connectivity_types[0]

    def is_active(self):
        try:
            self.client.list_volumes()
            return True
        except Exception:
            return False

    def validate_supported_space_efficiency(self, space_efficiency):
        if not space_efficiency:
            return True
        # For SANtricity, we use space_efficiency as RAID level hint
        return space_efficiency.lower() in ['raid1', 'raid5', 'raid6', 'raid10', 'none']



    def get_object_by_id(self, object_id, object_type, is_virt_snap_func=False):
        if object_type == servers_settings.VOLUME_TYPE_NAME:
            try:
                # SANtricity regular volumes. 
                # Linked clones (Snap Volumes) will be handled here later.
                vol_data = self.client.get_volume(object_id)
                return self._to_volume_object(vol_data)
            except Exception:
                return None
        return None



def _to_snapshot_object(self, group_data, volume_data=None):
        return Snapshot(
            capacity_bytes=int(volume_data['capacity']) if volume_data else 0,
            id=group_data['id'],
            internal_id=group_data['id'],
            name=group_data['name'],
            array_address=self.endpoint,
            source_id=group_data['baseVolume'],
            array_type=self.array_type,
            pool=group_data.get('pitGroupRef', ''),
            is_ready=True
        )



def delete_replication(self, replication):
    raise NotImplementedError()

def promote_replication_volume(self, replication):
    raise NotImplementedError()

def demote_replication_volume(self, replication):
    raise NotImplementedError()

def add_io_group_to_host(self, host_name, io_group):
    pass

def remove_io_group_from_host(self, host_name, io_group):
    pass

def get_host_io_group(self, host_name):
    return ""

def change_host_protocol(self, host_name, protocol):
    pass

def verify_host_partition(self, host_name, new_partition_name):
    return True

def verify_volume_group_partition(self, volume_group, partition_name):
    return True

def verify_volume_partition(self, volume, partition_name):
    return True

def get_volume_mappings(self, volume_id):
    mappings = {}
    all_mappings = self.client.list_volume_mappings()
    # Use id or hostRef to match either flavor of REST API
    # Need to collect labels from both individual hosts and host groups (clusters)
    all_targets = {(h.get('id') or h.get('hostRef')): h['label'] for h in self.client.list_hosts()
                    if h.get('id') or h.get('hostRef')}
    try:
        all_targets.update({(g.get('id') or g.get('clusterRef')): g['label'] 
                            for g in self.client.list_host_groups()
                            if g.get('id') or g.get('clusterRef')})
    except Exception:
        pass # Some API versions might only have /hosts or lack /host-groups
    
    for m in all_mappings:
        vol_ref = m.get('volumeRef') or m.get('mappableObjectId')
        if vol_ref == volume_id:
            target_id = m.get('mapRef') or m.get('targetId')
            target_name = all_targets.get(target_id, target_id)
            mappings[target_name] = str(m['lun'])
    return mappings

def register_plugin(self, unique_key, metadata):
    pass
