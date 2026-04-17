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

const (
	nvmeCmdTimeout                      = 10 * 1000
	nvmeTransportFC                     = "fc"
	nvmeDiscoveryNqn                    = "nqn.2014-08.org.nvmexpress.discovery"
	FCPortPath                          = "/sys/class/fc_host/host*/port_name"
	nvmeTargetPathCount                 = 3
	nvmeMinPathsForNonNativeDmMultipath = 2
	nvmeRoceTargetConnections           = 2
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

// EnsureLogin performs NVMe-oFC discovery and connect for each (arrayTargetPort, hostPort) pair.
// Connects paths until nvmeTargetPathCount is reached. Logs error if 0 paths result,
// warning if below target. For non-native NVMe with find_multipaths=on, logs error if < 2 paths.
func (r OsDeviceConnectivityNvmeOFc) EnsureLogin(ipsByArrayInitiator map[string][]string) {

	if r.Protocol == "nvmeoroce" {
		seen := map[string]bool{}
		uniquePortals := make([]string, 0)
		for _, portals := range ipsByArrayInitiator {
			for _, portal := range portals {
				if portal == "" || seen[portal] {
					continue
				}
				seen[portal] = true
				uniquePortals = append(uniquePortals, portal)
			}
		}

		successfulConnections := 0
		for _, portal := range uniquePortals {
			// Use 'rdma' as the transport for RoCE, as it's the more common and lab-verified value.
			logger.Debugf("NVMe/RoCE discover and connect on portal: {%s}", portal)
			args := []string{"discover", "-t", "rdma", "-a", portal}
			_, err := r.Executer.ExecuteWithTimeout(nvmeCmdTimeout, "nvme", args)
			if err != nil {
				logger.Errorf("Failed to discover NVMe/RoCE on portal %s: %v", portal, err)
				continue
			}

			// connect-all establishes sessions to discovered controllers behind this portal.
			args = []string{"connect-all", "-t", "rdma", "-a", portal}
			_, err = r.Executer.ExecuteWithTimeout(nvmeCmdTimeout, "nvme", args)
			if err != nil {
				logger.Errorf("Failed to connect-all NVMe/RoCE on portal %s: %v", portal, err)
				continue
			}

			successfulConnections++
			if successfulConnections >= nvmeRoceTargetConnections {
				logger.Debugf("NVMe/RoCE reached %d successful portal connections, stopping further login attempts", successfulConnections)
				break
			}
		}
		return
	}
	if len(ipsByArrayInitiator) == 0 {
		logger.Warningf("NVMe-oFC EnsureLogin: no array target ports in publish context, skipping")
		return
	}

	hostPorts, err := r.getHostFCPorts()
	if err != nil || len(hostPorts) == 0 {
		logger.Errorf("NVMe-oFC EnsureLogin: failed to read host FC ports: %v", err)
		return
	}
	logger.Debugf("NVMe-oFC EnsureLogin: host FC ports: %v", hostPorts)

	livePaths := r.getLivePathPairs()
	logger.Debugf("NVMe-oFC EnsureLogin: live path pairs: %v", livePaths)

	currentPaths := countLivePathsForSubsystem(livePaths, ipsByArrayInitiator)
	logger.Infof("NVMe-oFC EnsureLogin: current live paths=%d target=%d", currentPaths, nvmeTargetPathCount)

	if currentPaths >= nvmeTargetPathCount {
		logger.Infof("NVMe-oFC EnsureLogin: already at target path count (%d), skipping connect", nvmeTargetPathCount)
		return
	}

	connectedPaths := currentPaths
	for arrayTargetPort := range ipsByArrayInitiator {
		if connectedPaths >= nvmeTargetPathCount {
			logger.Infof("NVMe-oFC EnsureLogin: reached target path count (%d), stopping", nvmeTargetPathCount)
			break
		}
		for _, hostPort := range hostPorts {
			if connectedPaths >= nvmeTargetPathCount {
				break
			}

			pathKey := arrayTargetPort + "|" + hostPort
			if livePaths[pathKey] {
				logger.Debugf("NVMe-oFC EnsureLogin: path already live target=%s host=%s, skipping",
					arrayTargetPort, hostPort)
				continue
			}

			subNqn, err := r.discoverSubNqn(arrayTargetPort, hostPort)
			if err != nil {
				logger.Debugf("NVMe-oFC EnsureLogin: discover error target=%s host=%s: %v",
					arrayTargetPort, hostPort, err)
				continue
			}
			if subNqn == "" {
				logger.Debugf("NVMe-oFC EnsureLogin: no subnqn found target=%s host=%s, skipping",
					arrayTargetPort, hostPort)
				continue
			}

			logger.Infof("NVMe-oFC EnsureLogin: connecting NQN=%s target=%s host=%s",
				subNqn, arrayTargetPort, hostPort)
			if r.nvmeConnect(arrayTargetPort, hostPort, subNqn) {
				connectedPaths++
			}
		}
	}

	// Re-read to get kernel-confirmed final count (nvmeConnect may have failed silently).
	finalLivePaths := r.getLivePathPairs()
	finalPathCount := countLivePathsForSubsystem(finalLivePaths, ipsByArrayInitiator)
	logger.Infof("NVMe-oFC EnsureLogin: final live paths=%d target=%d", finalPathCount, nvmeTargetPathCount)

	if finalPathCount == 0 {
		logger.Errorf("NVMe-oFC EnsureLogin: 0 live paths after all connect attempts — " +
			"check fabric connectivity and array zoning. NodeStageVolume will fail.")
		return
	}

	if finalPathCount < nvmeTargetPathCount {
		logger.Warningf("NVMe-oFC EnsureLogin: below target path count: final=%d target=%d, continuing with reduced redundancy",
			finalPathCount, nvmeTargetPathCount)
	}

	// Non-native NVMe + find_multipaths=on + < 2 paths: multipathd will not
	// create a dm device, causing GetMpathDevice to fail.
	nativeMpath, err := isNvmeCoreMultipathEnabled()
	if err != nil {
		logger.Warningf("NVMe-oFC EnsureLogin: could not determine nvme_core multipath mode: %v", err)
		return
	}
	if !nativeMpath && finalPathCount < nvmeMinPathsForNonNativeDmMultipath {
		findMpathsOn, err := r.isFindMultipathsOn()
		if err != nil {
			logger.Warningf("NVMe-oFC EnsureLogin: could not read find_multipaths setting: %v", err)
			return
		}
		if findMpathsOn {
			logger.Errorf("NVMe-oFC EnsureLogin: non-native NVMe with find_multipaths=on requires >= %d paths "+
				"but only %d are live — multipathd will not create a dm device. "+
				"Set find_multipaths=no in /etc/multipath.conf or fix fabric connectivity.",
				nvmeMinPathsForNonNativeDmMultipath, finalPathCount)
		}
	}
}

// countLivePathsForSubsystem counts live paths whose traddr matches one of our array target ports.
func countLivePathsForSubsystem(livePaths map[string]bool, ipsByArrayInitiator map[string][]string) int {
	count := 0
	for pathKey := range livePaths {
		parts := strings.SplitN(pathKey, "|", 2)
		if len(parts) != 2 {
			continue
		}
		if _, ok := ipsByArrayInitiator[parts[0]]; ok {
			count++
		}
	}
	return count
}

// isFindMultipathsOn queries multipathd effective config for the find_multipaths setting.
func (r OsDeviceConnectivityNvmeOFc) isFindMultipathsOn() (bool, error) {
	out, err := r.Executer.ExecuteWithTimeout(TimeOutMultipathdCmd, multipathdCmd, []string{"show", "config"})
	if err != nil {
		return false, fmt.Errorf("multipathd show config failed: %w", err)
	}
	for _, line := range strings.Split(string(out), "\n") {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "find_multipaths") {
			continue
		}
		fields := strings.Fields(trimmed)
		if len(fields) < 2 {
			continue
		}
		val := strings.ToLower(fields[1])
		result := val == "yes" || val == "on"
		logger.Debugf("NVMe-oFC isFindMultipathsOn: find_multipaths=%s result=%v", val, result)
		return result, nil
	}
	// Not found — multipathd default is "no".
	return false, nil
}

// getLivePathPairs parses "nvme list-subsys" and returns a set of "traddr|host_traddr"
// strings for all currently live paths.
func (r OsDeviceConnectivityNvmeOFc) getLivePathPairs() map[string]bool {
	out, err := r.Executer.ExecuteWithTimeout(nvmeCmdTimeout, "nvme", []string{"list-subsys"})
	if err != nil {
		logger.Warningf("NVMe-oFC getLivePathPairs: nvme list-subsys failed: %v", err)
		return map[string]bool{}
	}
	livePaths := map[string]bool{}
	for _, line := range strings.Split(string(out), "\n") {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "+-") || !strings.Contains(trimmed, " live") {
			continue
		}
		traddr := extractNvmeField(trimmed, "traddr=")
		hostTraddr := extractNvmeField(trimmed, "host_traddr=")
		if traddr != "" && hostTraddr != "" {
			livePaths[traddr+"|"+hostTraddr] = true
			logger.Debugf("NVMe-oFC getLivePathPairs: live path traddr=%s host_traddr=%s", traddr, hostTraddr)
		}
	}
	return livePaths
}

// extractNvmeField extracts a field value from an nvme list-subsys path line.
// e.g. extractNvmeField(line, "traddr=") returns "nn-5005...:pn-5005..."
func extractNvmeField(line, field string) string {
	idx := strings.Index(line, field)
	if idx < 0 {
		return ""
	}
	rest := line[idx+len(field):]
	end := strings.IndexAny(rest, ", ")
	if end < 0 {
		return rest
	}
	return rest[:end]
}

// discoverSubNqn runs "nvme discover" for one (arrayTargetPort, hostPort) pair
// and returns the storage subsystem NQN. Returns ("", nil) if no path exists.
func (r OsDeviceConnectivityNvmeOFc) discoverSubNqn(arrayTargetPort, hostPort string) (string, error) {
	args := []string{
		"discover",
		"--transport=" + nvmeTransportFC,
		"--traddr=" + arrayTargetPort,
		"--host-traddr=" + hostPort,
	}
	out, err := r.Executer.ExecuteWithTimeout(nvmeCmdTimeout, "nvme", args)
	if err != nil {
		logger.Debugf("NVMe-oFC discoverSubNqn: nvme discover failed target=%s host=%s: %v",
			arrayTargetPort, hostPort, err)
		return "", nil
	}
	subNqn := parseSubNqnFromDiscoverOutput(string(out))
	if subNqn != "" {
		logger.Debugf("NVMe-oFC discoverSubNqn: discovered subnqn=%s target=%s host=%s",
			subNqn, arrayTargetPort, hostPort)
	}
	return subNqn, nil
}

// parseSubNqnFromDiscoverOutput extracts the storage subsystem NQN from "nvme discover" output.
// Skips the discovery controller NQN (nqn.2014-08.org.nvmexpress.discovery).
func parseSubNqnFromDiscoverOutput(output string) string {
	for _, line := range strings.Split(output, "\n") {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "subnqn:") {
			continue
		}
		// SplitN limit=2 preserves colons in the NQN itself.
		parts := strings.SplitN(trimmed, ":", 2)
		if len(parts) != 2 {
			continue
		}
		nqn := strings.TrimSpace(parts[1])
		if nqn == "" || nqn == nvmeDiscoveryNqn {
			continue
		}
		return nqn
	}
	return ""
}

// nvmeConnect runs "nvme connect" for one (arrayTargetPort, hostPort, subNqn) combination.
func (r OsDeviceConnectivityNvmeOFc) nvmeConnect(arrayTargetPort, hostPort, subNqn string) bool {
	args := []string{
		"connect",
		"--transport=" + nvmeTransportFC,
		"--traddr=" + arrayTargetPort,
		"--host-traddr=" + hostPort,
		"--nqn=" + subNqn,
	}
	out, err := r.Executer.ExecuteWithTimeout(nvmeCmdTimeout, "nvme", args)
	if err != nil {
		logger.Errorf("NVMe-oFC nvmeConnect: failed NQN=%s target=%s host=%s: %v output=%s",
			subNqn, arrayTargetPort, hostPort, err, string(out))
		return false
	}
	logger.Infof("NVMe-oFC nvmeConnect: connected NQN=%s target=%s host=%s", subNqn, arrayTargetPort, hostPort)
	return true
}

// getHostFCPorts reads node_name and port_name for every FC host adapter from sysfs
// and returns them as "nn-<node_name>:pn-<port_name>" strings for use as --host-traddr.
func (r OsDeviceConnectivityNvmeOFc) getHostFCPorts() ([]string, error) {
	portPaths, err := r.Executer.FilepathGlob(FCPortPath)
	if err != nil {
		return nil, fmt.Errorf("glob %s failed: %w", FCPortPath, err)
	}
	if len(portPaths) == 0 {
		return nil, fmt.Errorf("no FC host ports found under /sys/class/fc_host")
	}

	var hostPorts []string
	for _, portPath := range portPaths {
		hostDir := portPath[:strings.LastIndex(portPath, "/")]
		nodePath := hostDir + "/node_name"

		portBytes, err := r.Executer.IoutilReadFile(portPath)
		if err != nil {
			logger.Warningf("NVMe-oFC getHostFCPorts: cannot read %s: %v", portPath, err)
			continue
		}
		nodeBytes, err := r.Executer.IoutilReadFile(nodePath)
		if err != nil {
			logger.Warningf("NVMe-oFC getHostFCPorts: cannot read %s: %v", nodePath, err)
			continue
		}

		portName := strings.TrimPrefix(strings.TrimSpace(string(portBytes)), "0x")
		nodeName := strings.TrimPrefix(strings.TrimSpace(string(nodeBytes)), "0x")

		if portName == "" || nodeName == "" {
			logger.Warningf("NVMe-oFC getHostFCPorts: empty port/node name at %s, skipping", hostDir)
			continue
		}
		hostPorts = append(hostPorts, fmt.Sprintf("nn-%s:pn-%s", nodeName, portName))
	}

	if len(hostPorts) == 0 {
		return nil, fmt.Errorf("no valid host FC port pairs could be read from sysfs")
	}
	logger.Debugf("NVMe-oFC getHostFCPorts: found host ports: %v", hostPorts)
	return hostPorts, nil
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
		// Check if uniqueId is in wwid (case-insensitive) or vice versa
		// This handles cases where volumeRef contains metadata not in the host WWID
		lWwid := strings.ToLower(wwid)
		lUniqueId := strings.ToLower(uniqueId)
		if strings.Contains(lWwid, lUniqueId) || strings.Contains(lUniqueId, lWwid) {
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
	if arraySerial != "" && lun >= 0 {
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

	// Preference 3: Wildcard by-id glob on namespace number (lun == NVMe namespace ID).
	// Does not depend on array serial and is stable as long as the namespace ID is fixed.
	if lun >= 0 {
		pattern := fmt.Sprintf("/dev/disk/by-id/nvme-*_%d", lun)
		matches, globErr := r.Executer.FilepathGlob(pattern)
		if globErr == nil && len(matches) > 0 {
			logger.Infof("Found NVMe device via namespace-id glob %s -> %s", pattern, matches[0])
			return matches[0], nil
		}
		logger.Warningf("Namespace-id glob %s found no matches", pattern)
	}

	// ANA does not create DM devices; do not fall through to multipath.
	return "", fmt.Errorf("NVMe device not found for volume %s (lun %d) — device may not yet be visible", volumeId, lun)
}

func (r OsDeviceConnectivityNvmeOFc) FlushMultipathDevice(mpathDevice string) error {
	// For native NVMe multipathing (ANA), we don't use 'multipath -f'.
	// Instead, we just flush the device buffers.
	logger.Infof("NVMe: Flushing buffers for device %s", mpathDevice)
	return r.HelperScsiGeneric.FlushDeviceBuffers(mpathDevice)
}

func (r OsDeviceConnectivityNvmeOFc) RemovePhysicalDevice(sysDevices []string) error {
	// For native NVMe multipathing (ANA), there isn't a simple "delete" file like in SCSI.
	// We rely on 'nvme disconnect' if we want to remove the connection, but for now we'll
	// skip the SCSI-specific logic.
	logger.Infof("NVMe: Skipping SCSI-specific physical device removal for %v", sysDevices)
	return nil
}

func (r OsDeviceConnectivityNvmeOFc) RemoveGhostDevice(lun int) error {
	return r.HelperScsiGeneric.RemoveGhostDevice(lun)
}

func (r OsDeviceConnectivityNvmeOFc) ValidateLun(_ int, _ []string) error {
	return nil
}
