/**
 * Copyright 2019 IBM Corp.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package device_connectivity

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/ibm/ibm-block-csi-driver/node/logger"
	"github.com/ibm/ibm-block-csi-driver/node/pkg/driver/executer"
)

type OsDeviceConnectivityNvmeOFc struct {
	Executer          executer.ExecuterInterface
	HelperScsiGeneric OsDeviceConnectivityHelperScsiGenericInterface
	Protocol          string
}

func NewOsDeviceConnectivityNvmeOFc(executer executer.ExecuterInterface, clean_scsi_device bool, protocol string) OsDeviceConnectivityInterface {
	return &OsDeviceConnectivityNvmeOFc{
		Executer:          executer,
		HelperScsiGeneric: NewOsDeviceConnectivityHelperScsiGeneric(executer, clean_scsi_device),
		Protocol:          protocol,
	}
}

func (r OsDeviceConnectivityNvmeOFc) EnsureLogin(ipsByArrayIdentifier map[string][]string) {
	if r.Protocol != "nvmeoroce" {
		return
	}

	for _, portals := range ipsByArrayIdentifier {
		for _, portal := range portals {
			logger.Debugf("NVMe/RoCE discover and connect on portal: {%s}", portal)
			// Use 'rdma' as the transport for RoCE, as it's the more common and lab-verified value
			args := []string{"discover", "-t", "rdma", "-a", portal}
			_, err := r.Executer.ExecuteWithTimeout(30000, "nvme", args)
			if err != nil {
				logger.Errorf("Failed to discover NVMe/RoCE on portal %s: %v", portal, err)
				continue
			}

			// After discovery, connect-all is used to establish sessions to all discovered controllers
			args = []string{"connect-all", "-t", "rdma", "-a", portal}
			_, err = r.Executer.ExecuteWithTimeout(30000, "nvme", args)
			if err != nil {
				logger.Errorf("Failed to connect-all NVMe/RoCE on portal %s: %v", portal, err)
			}
		}
	}
}

func (r OsDeviceConnectivityNvmeOFc) RescanDevices(_ int, _ []string) error {
	return nil
}

func (r OsDeviceConnectivityNvmeOFc) getNvmeDevice(volumeId string) (string, error) {
	// volumeId example: 020000006d039ea000493a260000095c699eb957
	// We want to find a device where /sys/block/nvme*n*/wwid contains the unique part.

	uniqueId := volumeId
	if len(volumeId) > 8 && (strings.HasPrefix(volumeId, "02000000") || strings.HasPrefix(volumeId, "03000000")) {
		uniqueId = volumeId[8:]
	}

	logger.Debugf("Searching for NVMe device with uniqueId: %s", uniqueId)

	files, err := r.Executer.FilepathGlob("/sys/block/nvme*n*")
	if err != nil {
		return "", err
	}

	for _, f := range files {
		wwidPath := filepath.Join(f, "wwid")
		content, err := r.Executer.IoutilReadFile(wwidPath)
		if err != nil {
			continue
		}
		wwid := strings.TrimSpace(string(content))
		// Check if uniqueId is in wwid (case-insensitive)
		if strings.Contains(strings.ToLower(wwid), strings.ToLower(uniqueId)) {
			deviceName := filepath.Base(f)
			devicePath := filepath.Join("/dev", deviceName)
			logger.Infof("Found NVMe device %s for volume %s", devicePath, volumeId)
			return devicePath, nil
		}
	}
	return "", nil
}

func (r OsDeviceConnectivityNvmeOFc) GetMpathDevice(volumeId string, lun int, arraySerial string) (string, error) {
	logger.Infof("NVMe GetMpathDevice: Searching devices for volume : [%s] (LUN: %d, Serial: %s)", volumeId, lun, arraySerial)

	// Preference 1: Deterministic path /dev/disk/by-id/nvme-NetApp_E-Series_<SN>_<LUN>
	if arraySerial != "" && lun > 0 {
		deterministicPath := fmt.Sprintf("/dev/disk/by-id/nvme-NetApp_E-Series_%s_%d", arraySerial, lun)
		logger.Debugf("Checking deterministic path: %s", deterministicPath)
		matches, err := r.Executer.FilepathGlob(deterministicPath)
		if err == nil && len(matches) > 0 {
			logger.Infof("Found NVMe device via deterministic path: %s", deterministicPath)
			return deterministicPath, nil
		}
		logger.Warningf("Deterministic path %s not found, falling back to WWID search", deterministicPath)
	}

	// Preference 2: Search by WWID in /sys/block/nvme*n*
	devicePath, err := r.getNvmeDevice(volumeId)
	if err == nil && devicePath != "" {
		return devicePath, nil
	}
	if err != nil {
		logger.Warningf("Error while searching for native NVMe device by WWID: %v", err)
	}

	// Fallback to legacy multipath behavior
	return r.HelperScsiGeneric.GetMpathDevice(volumeId)
}

func (r OsDeviceConnectivityNvmeOFc) FlushMultipathDevice(mpathDevice string) error {
	return r.HelperScsiGeneric.FlushMultipathDevice(mpathDevice)
}

func (r OsDeviceConnectivityNvmeOFc) RemovePhysicalDevice(sysDevices []string) error {
	return r.HelperScsiGeneric.RemovePhysicalDevice(sysDevices)
}

func (r OsDeviceConnectivityNvmeOFc) RemoveGhostDevice(lun int) error {
	return r.HelperScsiGeneric.RemoveGhostDevice(lun)
}

func (r OsDeviceConnectivityNvmeOFc) ValidateLun(_ int, _ []string) error {
	return nil
}
