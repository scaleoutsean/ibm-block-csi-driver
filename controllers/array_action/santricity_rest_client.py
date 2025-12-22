import requests
import urllib3
from controllers.common.csi_logger import get_stdout_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_stdout_logger()

class SANtricityClient:
    """
    Client for interacting with NetApp SANtricity Web Services Proxy or Embedded Web Services.
    """
    def __init__(self, address, user, password, port=8443, verify_ssl=False):
        self.base_url = "https://{}:{}/devmgr/v2".format(address, port)
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def _request(self, method, endpoint, data=None, params=None):
        url = "{}/{}".format(self.base_url, endpoint)
        logger.debug("Sending {} request to {}".format(method, url))
        try:
            response = self.session.request(method, url, json=data, params=params)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP Error: {} - {}".format(e, e.response.text))
            raise
        except Exception as e:
            logger.error("Request Error: {}".format(e))
            raise

    def get_storage_systems(self):
        return self._request("GET", "storage-systems")

    def create_volume(self, pool_id, name, size_gb, raid_level=None, workload_id=None):
        """
        Create a new volume
        """
        logger.info(
            "Creating volume: name={}, size={}GB, pool={}, raid={}, workload={}".format(
                name, size_gb, pool_id, raid_level, workload_id
            )
        )
        
        request_body = {
            "poolId": pool_id,
            "name": name,
            "sizeUnit": "gb",
            "size": str(size_gb),
        }
        
        if raid_level:
            request_body["raidLevel"] = raid_level
        
        if workload_id:
            request_body["workloadId"] = workload_id
        
        endpoint = "storage-systems/1/volumes"
        return self._request("POST", endpoint, data=request_body)

    def delete_volume(self, volume_id):
        """Delete a volume"""
        logger.info("Deleting volume: {}".format(volume_id))
        endpoint = "storage-systems/1/volumes/{}".format(volume_id)
        self._request("DELETE", endpoint)

    def get_volume(self, volume_id):
        """Get specific volume details"""
        endpoint = "storage-systems/1/volumes/{}".format(volume_id)
        return self._request("GET", endpoint)

    def list_volumes(self):
        """List all volumes"""
        endpoint = "storage-systems/1/volumes"
        return self._request("GET", endpoint)

    def create_volume_mapping(self, volume_id, target_id, lun=None):
        """
        Map volume to host or host group
        """
        logger.info(
            "Creating volume mapping: volume={}, target={}, lun={}".format(
                volume_id, target_id, lun
            )
        )
        
        request_body = {
            "mappableObjectId": volume_id,
            "targetId": target_id
        }
        
        if lun is not None:
            request_body["lun"] = lun
        
        endpoint = "storage-systems/1/volume-mappings"
        return self._request("POST", endpoint, data=request_body)

    def delete_volume_mapping(self, mapping_id):
        """Delete a volume mapping"""
        logger.info("Deleting volume mapping: {}".format(mapping_id))
        endpoint = "storage-systems/1/volume-mappings/{}".format(mapping_id)
        self._request("DELETE", endpoint)

    def list_volume_mappings(self):
        """List all volume mappings"""
        endpoint = "storage-systems/1/volume-mappings"
        return self._request("GET", endpoint)

    def list_hosts(self):
        """List all registered hosts"""
        endpoint = "storage-systems/1/hosts"
        return self._request("GET", endpoint)

    def get_host(self, host_id):
        """Get specific host details"""
        endpoint = "storage-systems/1/hosts/{}".format(host_id)
        return self._request("GET", endpoint)

