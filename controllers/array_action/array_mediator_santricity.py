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
                      source_type, is_virt_snap_func, partition_name=None, partition_vg=None):
        size_gb = size_in_bytes / (1024 ** 3)
        pool_id = self._get_pool_id(pool)
        
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
            vol_data = self.client.create_volume(pool_id, name, size_gb, raid_level=raid_level)
            return self._to_volume_object(vol_data)
        except Exception as ex:
            # If raid6 default fails (e.g. on a traditional RAID5 group), retry with None
            if raid_level == 'raid6' and not space_efficiency:
                logger.info("Failed to create volume with raid6 default, retrying with inherited RAID level")
                try:
                    vol_data = self.client.create_volume(pool_id, name, size_gb, raid_level=None)
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

    def get_volume(self, name, pool, is_virt_snap_func):
        if is_virt_snap_func:
            logger.debug("is_virt_snap_func is not implemented for SANtricity, ignoring")

        vol_data = self.client.get_volume_by_name(name, pool_id=pool)
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
        if connectivity_type == array_settings.ISCSI_CONNECTIVITY_TYPE:
            target_settings = self.client.get_iscsi_target_settings()
            iqn = target_settings.get('nodeName')
            portals = [p.get('address') for p in target_settings.get('portals', [])]
            return {iqn: portals}
        if connectivity_type == array_settings.NVME_OVER_ROCE_CONNECTIVITY_TYPE:
            target_settings = self.client.get_nvme_target_settings()
            nqn = target_settings.get('nodeName')
            portals = [p.get('address') for p in target_settings.get('portals', [])]
            return {nqn: portals}
        return {}

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

    def get_snapshot(self, volume_id, snapshot_name, pool, is_virt_snap_func):
        raise NotImplementedError()

    def get_object_by_id(self, object_id, object_type, is_virt_snap_func=False):
        if object_type == array_settings.VOLUME_TYPE:
            try:
                vol_data = self.client.get_volume(object_id)
                return self._to_volume_object(vol_data)
            except Exception:
                return None
        return None

    def create_snapshot(self, volume_id, snapshot_name, space_efficiency, pool, is_virt_snap_func, partition_name=None):
        raise NotImplementedError()

    def delete_snapshot(self, snapshot_id, internal_snapshot_id, partition_name=None):
        raise NotImplementedError()

    def get_array_fc_wwns(self, host_name):
        return []

    def get_replication(self, replication_request):
        return None

    def create_replication(self, replication_request):
        raise NotImplementedError()

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
        all_hosts = {h['id']: h['label'] for h in self.client.list_hosts()}
        
        for m in all_mappings:
            if m['mappableObjectId'] == volume_id:
                host_id = m['targetId']
                host_name = all_hosts.get(host_id, host_id)
                mappings[host_name] = str(m['lun'])
        return mappings

    def register_plugin(self, unique_key, metadata):
        pass
