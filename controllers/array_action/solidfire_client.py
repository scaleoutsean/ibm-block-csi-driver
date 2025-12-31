import json
import requests
import urllib3
from controllers.common.csi_logger import get_stdout_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_stdout_logger()

class SolidFireClient:
    """
    Client for interacting with NetApp SolidFire JSON-RPC API.
    """
    def __init__(self, mvip, user, password, port=443, verify_ssl=False):
        self.endpoint = "https://{}:{}/json-rpc/12.5".format(mvip, port)
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Content-Type": "application/json",
        })
        self._request_id = 0

    def _request(self, method, params=None):
        self._request_id += 1
        payload = {
            "method": method,
            "params": params or {},
            "id": self._request_id,
        }
        
        logger.debug("Sending SolidFire request: {} {}".format(method, params))
        
        try:
            response = self.session.post(self.endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if 'error' in data:
                logger.error("SolidFire API Error: {}".format(data['error']))
                raise Exception(data['error']['message'])
                
            return data.get('result')
            
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP Error: {} - {}".format(e, e.response.text))
            raise
        except Exception as e:
            logger.error("Request Error: {}".format(e))
            raise

    def get_cluster_info(self):
        return self._request("GetClusterInfo")

    def create_volume(self, name, size_bytes, account_id, enable512e=True):
        params = {
            "name": name,
            "totalSize": int(size_bytes),
            "accountID": account_id,
            "enable512e": enable512e,
        }
        return self._request("CreateVolume", params)

    def delete_volume(self, volume_id):
        return self._request("DeleteVolume", {"volumeID": int(volume_id)})

    def get_volume(self, volume_id):
        result = self._request("ListVolumes", {
            "startVolumeID": int(volume_id),
            "limit": 1
        })
        volumes = result.get('volumes', [])
        if volumes and volumes[0]['volumeID'] == int(volume_id):
            return volumes[0]
        raise Exception("Volume {} not found".format(volume_id))

    def list_volumes_by_name(self, name):
        # SolidFire doesn't filter by name in ListVolumes, so we might need to iterate
        # or rely on the caller to handle ID lookups. 
        # For now, let's assume we might need to search active volumes.
        # This is inefficient for large clusters, but okay for MVP.
        result = self._request("ListActiveVolumes", {})
        for vol in result.get('volumes', []):
            if vol['name'] == name:
                return vol
        return None

    def get_account_by_name(self, username):
        result = self._request("GetAccountByName", {"username": username})
        return result.get('account')

    def create_account(self, username):
        return self._request("AddAccount", {"username": username})

    def create_volume_access_group(self, name, initiators):
        params = {
            "name": name,
            "initiators": initiators
        }
        return self._request("CreateVolumeAccessGroup", params)

    def add_initiators_to_volume_access_group(self, vag_id, initiators):
        params = {
            "volumeAccessGroupID": vag_id,
            "initiators": initiators
        }
        return self._request("AddInitiatorsToVolumeAccessGroup", params)

    def add_volumes_to_volume_access_group(self, vag_id, volume_ids):
        # SolidFire expects the full volume list when updating a VAG, not just deltas.
        vag_id = int(vag_id)
        existing_volumes = []
        try:
            vags = self.list_volume_access_groups().get("volumeAccessGroups", [])
            vag = next((v for v in vags if v.get("volumeAccessGroupID") == vag_id), None)
            if vag:
                existing_volumes = vag.get("volumes", [])
        except Exception as ex:
            logger.warning("Failed to load existing VAG volumes for %s: %s", vag_id, ex)

        merged = []
        for vid in existing_volumes + [int(v) for v in volume_ids]:
            if vid not in merged:
                merged.append(vid)

        params = {
            "volumeAccessGroupID": vag_id,
            "volumes": merged
        }
        return self._request("AddVolumesToVolumeAccessGroup", params)

    def remove_volumes_from_volume_access_group(self, vag_id, volume_ids):
        params = {
            "volumeAccessGroupID": vag_id,
            "volumes": [int(v) for v in volume_ids]
        }
        return self._request("RemoveVolumesFromVolumeAccessGroup", params)
    
    def list_volume_access_groups(self):
        return self._request("ListVolumeAccessGroups", {})

    def modify_volume(self, volume_id, total_size_bytes):
        params = {
            "volumeID": int(volume_id),
            "totalSize": int(total_size_bytes)
        }
        return self._request("ModifyVolume", params)
