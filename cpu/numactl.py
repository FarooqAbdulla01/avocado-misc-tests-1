#!/usr/bin/env python
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: 2017 IBM
# Author:Praveen K Pandey <praveen@linux.vnet.ibm.com>
#


import os
import glob
import re
import netifaces
from random import choice

from avocado import Test
from avocado.utils import archive, build, process, distro, memory
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost
from avocado.utils import genio, process


class Numactl(Test):

    """
    Self test case of numactl

    :avocado: tags=cpu
    """

    def setUp(self):
        '''
        Build Numactl Test
        Source:
        https://github.com/numactl/numactl
        '''
        # Check for basic utilities
        smm = SoftwareManager()

        detected_distro = distro.detect()
        deps = ['gcc', 'libtool', 'autoconf', 'automake', 'make']
        if detected_distro.name in ["Ubuntu", 'debian']:
            deps.extend(['libnuma-dev'])
        elif detected_distro.name in ["centos", "rhel", "fedora"]:
            deps.extend(['numactl-devel'])
        else:
            deps.extend(['libnuma-devel'])

        for package in deps:
            if not smm.check_installed(package) and not smm.install(package):
                self.cancel("Failed to install %s, which is needed for"
                            "the test to be run" % package)

        locations = ["https://github.com/numactl/numactl/archive/master.zip"]
        tarball = self.fetch_asset("numactl.zip", locations=locations,
                                   expire='7d')
        archive.extract(tarball, self.workdir)
        self.sourcedir = os.path.join(self.workdir, 'numactl-master')

        os.chdir(self.sourcedir)
        process.run('./autogen.sh', shell=True)

        process.run('./configure', shell=True)

        build.make(self.sourcedir)

        interfaces = netifaces.interfaces()
        interface = self.params.get("interface")
        if interface not in interfaces:
            self.cancel("%s interface is not available" % interface)
        self.iface = interface
        local = LocalHost()
        self.networkinterface = NetworkInterface(self.iface, local)
        self.ipaddr = self.params.get("host_ip", default="")
        self.netmask = self.params.get("netmask", default="")
        self.peer = self.params.get("peer_ip")
        if not self.peer:
            self.cancel("No peer provided")
        if self.networkinterface.ping_check(self.peer, count=5) is not None:
            self.cancel("No connection to peer")
        self.device = self.params.get('pci_device', default="")
        if not self.device:
            self.cancel("PCI_address not given")
        if not os.path.isdir('/sys/bus/pci/devices/%s' % self.device):
            self.cancel("%s not present in device path" % self.device)

        self.ping_count = 5000000

    def test(self):

        if build.make(self.sourcedir, extra_args='-k -j 1'
                      ' test', ignore_status=True):
            if len(memory.numa_nodes_with_memory()) < 2:
                self.log.warn('Few tests failed due to less NUMA mem-nodes')
            else:
                self.fail('test failed, Please check debug log')

    def get_nodes_with_cpus(self):
        '''
        Returns a dictonary, 
        1. node number as key and 
        2. associated CPUS as values. 
        '''

        cpu_path = '/sys/devices/system/node/has_cpu'
        if not os.path.exists(cpu_path):
            raise CpuError("No NUMA nodes have cpu")
            self.cancel("No NUMA nodes have CPU")
               
        if len(genio.read_file(cpu_path).rstrip('\n')) < 2:
            self.cancel("Required atleast two NUMA nodes with CPU assigned  for this test case!")

        self.dict1 = {}
        for path in glob.glob("/sys/devices/system/node/node[0-9]*"):
            self.node= (int(re.search(r".node(\d+)$",path).group(1)))
            self.node_dir = (path + "/")
            self.pinned_cpus = []
            for cpu_numbers in glob.glob(self.node_dir+"cpu[0-9]*"):
                self.cpu = (int(re.search(r".cpu(\d+)$",cpu_numbers).group(1)))
                self.pinned_cpus.append(self.cpu)
            self.dict1[self.node] = (sorted(self.pinned_cpus))
               
        return (self.dict1)


    def numa_ping(self,cmd):
        '''
        Ping Test to remote Peer with -f and count options.
        '''
        output = process.run(cmd, shell=True,ignore_status=True).stdout.decode("utf-8").split(",")
        if " 0% packet loss"  not in output:
            self.cancel("failed due to packet loss")
    
    def test_interleave(self):
        '''
        To check memory interleave on NUMA nodes.
        '''
                 
        cmd = "numactl --interleave=all ping -I %s %s -c %s -f" % (self.iface, self.ipaddr, self.ping_count)
        self.numa_ping(cmd)

    
    def test_localalloc(self):
        '''
        Test memory allocation on the current node
        '''
                 
        cmd = "numactl --localalloc ping -I %s %s -c %s -f" % (self.iface, self.ipaddr, self.ping_count)
        self.numa_ping(cmd)


    def test_preferred_node(self):
        '''
        Test Preferably allocate memory on node
        '''
        self.get_nodes_with_cpus()
        self.node_number = [key for key in self.dict1.keys()][1]
        cmd = "numactl --preferred=%s  ping -I %s %s -c %s -f" % (self.node_number, self.iface, self.ipaddr, self.ping_count)
        self.numa_ping(cmd)


    def test_cpunode_with_membind(self):
        '''
        Test CPU and memory bind
        '''
        self.get_nodes_with_cpus()
        self.first_cpu_node_number = [key for key in self.dict1.keys()][0]
        self.second_cpu_node_number = [key for key in self.dict1.keys()][1]
        self.membind_node_number = [key for key in self.dict1.keys()][1]
        cmd = "numactl --cpunodebind=%s --membind=%s   ping -I %s %s -c %s -f " % (self.first_cpu_node_number,self.membind_node_number, self.iface, self.ipaddr, self.ping_count)
        self.numa_ping(cmd)
        cmd = "numactl --cpunodebind=%s --membind=%s   ping -I %s %s -c %s -f " % (self.second_cpu_node_number,self.membind_node_number, self.iface, self.ipaddr, self.ping_count)
        self.numa_ping(cmd)


    def test_physical_cpu_bind(self):
        '''
        Test physcial  CPU binds
        '''
        self.get_nodes_with_cpus()
        self.cpu_number = [value for value in self.dict1.values()][0][1]
        cmd = "numactl --physcpubind=%s ping -I %s %s -c %s -f" % (self.cpu_number, self.iface, self.peer, self.ping_count)
        self.numa_ping(cmd)
        

    def test_numa_pci_bind(self):
        '''
        Test PCI binding to diferrent NUMA nodes 
        '''
        self.get_nodes_with_cpus()
        node_numbers = [node for node in self.dict1.keys()]
        pci_node_number = process.system_output('cat /sys/bus/pci/devices/%s/numa_node' %self.device)
        node_path = ('/sys/bus/pci/devices/%s/numa_node' %self.device)
        alternate_node = (choice([i for i in node_numbers if i not in [pci_node_number]]))
        output = process.run('echo %s > %s' %(alternate_node,node_path),shell=True, ignore_status=True)
        if output.exit_status != 0:
            self.fail("Failed to assign the NUMA nodes to PCI, please check the logs")
        else:
            self.log.info(f"Assigned PCI from numa node {pci_node_number} to {alternate_node} sucessfully")
